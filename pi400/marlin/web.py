"""Headless Raspberry Pi 400 control server for native Marlin on SKR Mini MZ.

Web UI and HTTP API on port 8080 for LumaCut Studio and browsers.
TCP 23 remains for LightBurn (Marlin device) until Studio replaces it.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from .transport import (Aborted, MarlinTransport, MarlinLaserGuard, ProbeFailed, normalize,
                        serve_tcp, MOTION_ACCEL_RANGE, MOTION_SPEED_RANGE, Z_MAX_MM)
from .smart_cam import analyze_job
from . import placement as placing
from . import heightmap
from . import bedmap
from . import matcal
from . import focus_compensation as focus
from .materials import ConflictError, MaterialStore, NotFoundError
from .camera_calibration import CalibrationStore, create_blueprint as camera_calibration_api
from . import camera as head_camera
from .workspace import WorkspaceStore, create_blueprint as workspace_api
from .projects import ProjectStore, create_blueprint as projects_api
from .line_laser import LineLaser
from .app_update import AppUpdates

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("LUMACUT_DATA", "/var/lib/lumacut")) / "marlin"
# Shared by every program (docs/ZUSAMMENARBEIT_CLAUDE_GROK.md §3).
MATERIALS = MaterialStore(DATA.parent / "materials.json")
# /api/status "features": clients switch on Pi-side behaviour by these names.
# autorun_mesh: op=autorun probes the motif areas and compensates the focus
# itself (Studio and Android then upload the job without Z, docs/SCAN_PROBE.md).
FEATURES = ("autorun_mesh", "materials", "app_update", "camera_settings", "workspace",
            "report", "backup", "exhaust_auto", "bed_map", "material_calibration", "projects")
JOBS = DATA / "jobs"
# Camera pictures taken inside a job while the laser runs (measuring spot/line).
CAPTURES = DATA / "captures"
_CAPTURE = re.compile(r"^\s*;\s*LUMACUT-CAPTURE\b(.*)$", re.I)
_CAPTURE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_CAPTURE_WORD = re.compile(r"(id|w|h|delay)=([A-Za-z0-9-]+)")
USB = os.environ.get("LUMACUT_SKR", "/dev/ttyACM0")
# Head camera (USB/UVC or CSI via V4L2) for the workspace scan.
CAMERA = os.environ.get("LUMACUT_CAMERA", "/dev/video0")
HTTP = int(os.environ.get("LUMACUT_HTTP", "8080"))
TCP = int(os.environ.get("LUMACUT_TCP", "23"))
machine = MarlinTransport(USB)
app = Flask(__name__, static_folder=None)
app.register_blueprint(camera_calibration_api())  # GET/PUT /api/camera/calibration
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
config = {
    "validated": False,        # mechanics confirmed once via /api/commission
    "z_clearance_mm": 20.0,
    "focus_gap_mm": 7.0,
    "z_switch_tip_offset_mm": 1.5,
    "probe_offset_x_mm": None,
    "probe_offset_y_mm": None,  # tip height above reference plane at switch trigger
    "travels": {"x": 390.0, "y": 370.0, "z": 80.0},
    "user_origin": None,        # [x, y] machine mm, op=origin_set (job placement)
    "light_brightness": 60,     # % for the dimmable LED strip on PC8
    "light_effects": True,      # light effects at homing, job start/end, error
    # Fixed head-camera exposure from the tablet's light calibration (camera.py), None = automatic.
    "camera": dict(head_camera.DEFAULTS),
    # X/Y acceleration (mm/s²) and top speed (mm/s) from the motion calibration, None = firmware.
    "motion": {"accel": None, "speed": None},
    # Probed surface may differ this much from the chosen material's thickness.
    "thickness_tolerance_mm": 2.0,
    # Pi GPIO (BCM) of the red measuring line laser on the head, None = not fitted.
    "line_laser_gpio": None,
    # Shown in the web UI and in the apps' laser search.
    "machine_name": "LumaCut",
    # Exhaust on at every job start; off this many seconds after the job (fumes).
    "exhaust_auto": False,
    "exhaust_after_s": 60,
}
MACHINE_NAME_MAX = 40
EXHAUST_AFTER_RANGE = (0, 900)
# op=report: Marlin queries that only read (transport.READ_ONLY without M400).
REPORTS = {"M105": "Temperaturen", "M114": "Position", "M115": "Firmware",
           "M119": "Endschalter", "M503": "Firmware-Einstellungen"}
CONFIG = DATA / "config.json"
DATA.mkdir(parents=True, exist_ok=True)
JOBS.mkdir(parents=True, exist_ok=True)
if CONFIG.is_file():
    try:
        saved = json.loads(CONFIG.read_text("utf-8"))
        if isinstance(saved, dict):
            config.update({k: saved[k] for k in config if k in saved})
    except Exception:
        logging.exception("Marlin config corrupt, using safe disabled default")
# An older config.json may still say 90 mm: never above the rail limit.
config["travels"]["z"] = min(float(config["travels"].get("z", Z_MAX_MM)), Z_MAX_MM)
machine.homing_verified = bool(config["validated"])
machine.clearance_mm = float(config["z_clearance_mm"])
machine.probe_tip_offset_mm = float(config["z_switch_tip_offset_mm"])
machine.focus_gap_mm = float(config["focus_gap_mm"])
machine.light_pct = int(round(float(config["light_brightness"])))
machine.light_effects = bool(config["light_effects"])
if (config.get("motion") or {}).get("accel") and (config.get("motion") or {}).get("speed"):
    machine.motion_limits = (float(config["motion"]["accel"]), float(config["motion"]["speed"]))
# Shared work state (material, areas, project, scan): every app sees the same (workspace.py).
WORKSPACE = WorkspaceStore(DATA.parent / "workspace")
app.register_blueprint(workspace_api(WORKSPACE))
machine.material_mm = WORKSPACE.material_thickness()
WORKSPACE.on_change = lambda state: setattr(machine, "material_mm", WORKSPACE.material_thickness())
# Saved projects next to the open one: every app stores and opens them by name (projects.py).
PROJECTS = ProjectStore(DATA.parent / "projects")
app.register_blueprint(projects_api(PROJECTS))
# Measuring line laser (3D): off at start, on only while the app measures.
LINE_LASER = LineLaser()
try:
    LINE_LASER.configure(config.get("line_laser_gpio"))
except Exception:
    logging.exception("Linienlaser-GPIO nicht eingerichtet")
# Last known head height, so homing after an emergency stop knows how far to lift.
LAST_Z = DATA / "last_z.json"
try:
    machine.last_known_z = float(json.loads(LAST_Z.read_text("utf-8"))["z"])
except Exception:
    machine.last_known_z = None
if config["probe_offset_x_mm"] is not None and config["probe_offset_y_mm"] is not None:
    machine.probe_xy_offset_mm = (float(config["probe_offset_x_mm"]),
                                  float(config["probe_offset_y_mm"]))
# Bed map (bedmap.py): the empty bed probed once; None until measured.
BED_MAP_FILE = DATA / bedmap.FILENAME
BED = bedmap.load(BED_MAP_FILE)
MATCAL_FILE = DATA / "matcal.json"
# probe: {"done", "total"} while op=autorun probes (and afterwards), else None.
# phase: finer step while active (homing, probing, focusing, running,
# finishing, parking), None otherwise.
job = {"file": "", "state": "idle", "line": 0, "total": 0, "error": "", "probe": None,
       "phase": None}
job_lock = threading.Lock()
stop_job = threading.Event()
# Framing (op=frame) runs laser-off outline moves from a request payload. It
# shares job_lock/stop_job with jobs (never both at once, abort/estop stop
# it) but has its own state so the uploaded job and its status stay intact.
frame = {"state": "idle", "mode": "", "line": 0, "total": 0, "error": ""}
FRAME_MAX_BYTES = 64 * 1024
FRAME_MAX_MOVES = 2000
FRAME_MODES = {"box": "Rechteck", "hull": "Gummiband"}
_FRAME_SETUP = ("G21", "G90", "M5", "M5 I", "M400")
_FRAME_MOVE = re.compile(r"^G0?[01](?:\s*[XYFS]\s*[-+]?(?:\d+(?:\.\d*)?|\.\d+))+$")
_FRAME_WORD = re.compile(r"([XYFS])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
running = False
# Job placement (op=place, gap analysis #16): the offset that moves the
# stored job so its anchor lands on the chosen origin. Kept until the job
# file changes (sha), another job is placed or op=place_clear; a placement
# on the "current" head position is dropped as soon as the head is moved
# by hand (jog/moveto/home), so Start never uses a stale position.
job_placement = None


def persist():
    temporary = CONFIG.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.replace(temporary, CONFIG)


@app.after_request
def headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.errorhandler(Exception)
def handle_error(exc):
    from werkzeug.exceptions import HTTPException
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, ConflictError):
        return jsonify(error=str(exc), revision=exc.revision), 409
    if isinstance(exc, NotFoundError):
        return jsonify(error="Material nicht gefunden"), 404
    logging.exception("Marlin Control server request failed: %s", exc)
    if isinstance(exc, (ValueError, RuntimeError, PermissionError)):
        return jsonify(error=str(exc)), 400
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return jsonify(error=str(exc)), 503
    return jsonify(error="Interner Fehler – Pi-Protokoll ansehen"), 500


@app.get("/")
def homepage():
    return send_from_directory(str(ROOT), "index.html")


#: /api/status waits at most this long for machine.lock. Home, park, probe
#: and every frame edge (M400) hold the lock for the whole move; status must
#: never wait for that (Studio and web UI would see a dead Pi).
STATUS_LOCK_WAIT_S = 0.25
_status_cache = {"snapshot": None, "at": None}
_status_cache_lock = threading.Lock()
# Read without machine.lock: plain attribute reads, safe in CPython, and the
# values that matter during a move (owner, latch, laser, homed).
_LIVE_STATUS_FIELDS = {
    "state": lambda m: m.state,
    "owner": lambda m: m.owner or "Frei",
    "homed": lambda m: m.homed,
    "z_homed": lambda m: m.z_homed,
    "emergency_latched": lambda m: m.emergency_latched,
    "laser_armed": lambda m: m.laser_enabled,
    "laser_cooling_fan_on": lambda m: m.fan_power,
    "position": lambda m: m.position,
    "fault": lambda m: m.fault,
    "workpiece_surface_z": lambda m: m.surface_z,
}


def machine_snapshot():
    """Machine status that never blocks behind a long move.

    Returns ``(status, busy, stale_ms)``. If machine.lock is free within
    STATUS_LOCK_WAIT_S this is the full, consistent ``machine.status()``
    (busy False, stale_ms 0) and becomes the cached snapshot. Otherwise the
    last full snapshot is returned with the live fields above overlaid,
    ``busy`` True and ``stale_ms`` the age of the cached part.
    """
    if machine.lock.acquire(timeout=STATUS_LOCK_WAIT_S):
        try:
            result = machine.status()
        finally:
            machine.lock.release()
        with _status_cache_lock:
            _status_cache.update(snapshot=dict(result), at=time.monotonic())
        return result, False, 0
    with _status_cache_lock:
        cached, at = _status_cache["snapshot"], _status_cache["at"]
    result = dict(cached or {})
    for key, read in _LIVE_STATUS_FIELDS.items():
        try:
            value = read(machine)
        except Exception:      # pragma: no cover - defensive
            continue
        result[key] = list(value) if isinstance(value, list) else value
    result["connected"] = machine.serial is not None and bool(machine.identity)
    stale_ms = (None if at is None else int((time.monotonic() - at) * 1000))
    return result, True, stale_ms


@app.get("/api/status")
def status():
    result, busy, stale_ms = machine_snapshot()
    # This is an estimate, not a measured surface map. Marlin Z=0
    # represents the endstop trigger, not necessarily the laser tip.
    tip_gap = None
    if result["homed"] and result["position"] is not None:
        surface = result.get("workpiece_surface_z")
        tip_gap = (None if surface is None else
                   round(result["position"][2] - surface +
                         config["z_switch_tip_offset_mm"], 3))
    result.update(estimated_tip_gap_mm=tip_gap,
                  estimated_focus_adjust_mm=(None if tip_gap is None else
                    round(config["focus_gap_mm"] - tip_gap, 3)),
                  job=dict(job), frame=dict(frame),
                  activity=("framing" if frame["state"] == "running" else
                            "job" if (job["state"] in ("homing", "probing", "running") or
                                      job_queue["state"] in QUEUE_ACTIVE)
                            else "idle"),
                  firmware="marlin",
                  coord_convention=placing.COORD_CONVENTION,
                  features=list(FEATURES),
                  busy=busy, stale_ms=stale_ms,
                  expected_pwm="PA1 / M3 I / S0..255",
                  io={"laser_supply_switch":"FAN1 / PC6 (M106/M107, low-side)",
                      "laser_pwm":"BL-Touch / PA1",
                      "fan_cooldown":"180s via Pi: requires firmware FAN0 PC6; no crash-proof fan timer",
                      "exhaust":"BED PC9 M8",
                      "lights":"HE0 PC8 M355 (dimmbar), alte Firmware M7",
                      "aux":"FAN2 PC7 unused"},
                  config=dict(config),
                  sync=WORKSPACE.revisions(),
                  line_laser=LINE_LASER.status(),
                  travel_z_mm=round(machine.travel_z, 2),
                  bed_map=None if BED is None else BED.summary(),
                  material_calibration=_matcal_summary(),
                  workpiece_above_bed_mm=_above_bed(),
                  home_needs_confirm=(not machine.z_homed and machine.last_known_z is None),
                  origin=_origin_status(),
                  queue=_queue_status(),
                  camera={"device": CAMERA, "available": os.path.exists(CAMERA)})
    return jsonify(result)


def local_owner():
    with machine.lock:
        if machine.owner == "frame":
            raise RuntimeError("Rahmenfahrt läuft – abwarten oder abbrechen")
        if machine.owner is not None:
            raise RuntimeError(
                "Steuerung belegt durch " + machine.owner +
                " – LightBurn zuerst trennen")
        if machine.serial is None or not machine.identity:
            raise ConnectionError("Marlin SKR noch nicht per USB identifiziert")
        if machine.state not in ("Idle",):
            raise RuntimeError("SKR beschäftigt: " + machine.state)


def manual(command, timeout=20):
    local_owner()
    return machine.command(command, owner="web", timeout=timeout)


def home_z_first(operator_clear=False):
    # Reuse the exact same atomic safe-home transaction as the LightBurn
    # G28 compatibility layer. Never let two implementations diverge.
    local_owner()
    machine.safe_home(owner="web", clearance_mm=config["z_clearance_mm"], operator_clear=operator_clear)


@app.post("/api/settings")
def settings():
    # Configuration can be edited while homed and while LightBurn owns TCP.
    # This endpoint never sends motion or laser commands to the SKR.
    # Every field is optional: a missing one keeps its value, so a page can
    # save one group of settings at a time.
    import math
    form = request.form

    def number(name, low, high, message):
        raw = form.get(name)
        if raw is None:
            return config[name]
        value = float(raw)
        if not (math.isfinite(value) and low <= value <= high):
            raise ValueError(message)
        return value

    clearance = number("z_clearance_mm", 0.5, 50, "Z-Rückzug muss zwischen 0,5 und 50 mm liegen")
    gap = number("focus_gap_mm", 0.1, 30, "Fokusabstand muss zwischen 0,1 und 30 mm liegen")
    offset = number("z_switch_tip_offset_mm", -20, 20,
                    "Schalter-zu-Spitze-Offset muss zwischen -20 und +20 mm liegen")
    # Off-axis switch displacement relative to laser spot, signed machine XY.
    probe_x, probe_y = config["probe_offset_x_mm"], config["probe_offset_y_mm"]
    if "probe_offset_x_mm" in form or "probe_offset_y_mm" in form:
        probe_x_raw = form.get("probe_offset_x_mm", "").strip()
        probe_y_raw = form.get("probe_offset_y_mm", "").strip()
        if bool(probe_x_raw) != bool(probe_y_raw):
            raise ValueError("X/Y-Tasterversatz entweder beide eintragen oder beide leer lassen")
        probe_x = float(probe_x_raw) if probe_x_raw else None
        probe_y = float(probe_y_raw) if probe_y_raw else None
        if probe_x is not None and not (math.isfinite(probe_x) and -80 <= probe_x <= 80 and
                math.isfinite(probe_y) and -80 <= probe_y <= 80):
            raise ValueError("Taster-X/Y-Versatz muss -80..80 mm sein")
    tolerance = config["thickness_tolerance_mm"]
    if form.get("thickness_tolerance_mm", "").strip():
        # how far the probed surface may differ from the material thickness
        tolerance = number("thickness_tolerance_mm", 0.5, 10,
                           "Toleranz der Materialstärke muss 0,5..10 mm sein")
    name = config["machine_name"]
    if "machine_name" in form:
        name = " ".join(form.get("machine_name", "").split())
        if not 1 <= len(name) <= MACHINE_NAME_MAX:
            raise ValueError("Gerätename: 1 bis %d Zeichen" % MACHINE_NAME_MAX)
    exhaust_auto = config["exhaust_auto"]
    if "exhaust_auto" in form:
        if form["exhaust_auto"] not in ("0", "1"):
            raise ValueError("exhaust_auto 0/1 erwartet")
        exhaust_auto = form["exhaust_auto"] == "1"
    exhaust_after = int(number("exhaust_after_s", *EXHAUST_AFTER_RANGE,
                               "Abluft-Nachlauf muss %d..%d s sein" % EXHAUST_AFTER_RANGE))
    # optional: GPIO of the measuring line laser ("" = none)
    if "line_laser_gpio" in form:
        raw = form.get("line_laser_gpio", "").strip()
        pin = int(raw) if raw else None
        LINE_LASER.configure(pin)
        config["line_laser_gpio"] = pin
    geometry_changed = ((probe_x, probe_y, offset, gap) !=
                        (config["probe_offset_x_mm"], config["probe_offset_y_mm"],
                         config["z_switch_tip_offset_mm"], config["focus_gap_mm"]))
    with machine.lock:
        machine.probe_xy_offset_mm = (probe_x, probe_y) if probe_x is not None else None
        machine.clearance_mm = clearance
        machine.probe_tip_offset_mm = offset
        machine.focus_gap_mm = gap
        if geometry_changed:
            # New probe geometry invalidates the prior measured material height.
            machine.surface_z = None
            machine.focused_this_job = False
    config.update(probe_offset_x_mm=probe_x, probe_offset_y_mm=probe_y,
                  z_clearance_mm=clearance, focus_gap_mm=gap, z_switch_tip_offset_mm=offset,
                  thickness_tolerance_mm=tolerance, machine_name=name,
                  exhaust_auto=exhaust_auto, exhaust_after_s=exhaust_after)
    persist()
    return jsonify(message="Einstellungen dauerhaft auf dem Pi gespeichert",
                   z_clearance_mm=clearance, focus_gap_mm=gap,
                   z_switch_tip_offset_mm=offset,
                   probe_offset_x_mm=probe_x, probe_offset_y_mm=probe_y,
                   config=dict(config),
                   note="LightBurn G28 referenziert Boden, G30 tastet Werkstück über X/Y-Tasterversatz ab, ohne Maschinen-Z0 zu verändern.")


@app.get("/api/backup")
def backup():
    """Every setting the Pi keeps, as one JSON file to download (reads only)."""
    calibration = DATA.parent / "camera_calibration.json"
    try:
        camera_cal = json.loads(calibration.read_text("utf-8")) if calibration.is_file() else None
    except Exception:
        camera_cal = None
    body = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "machine_name": config["machine_name"],
            "config": config, "materials": MATERIALS.list(), "workspace": WORKSPACE.get_state(),
            "camera_calibration": camera_cal}
    stamp = time.strftime("%Y-%m-%d")
    return (json.dumps(body, indent=2, ensure_ascii=False), 200,
            {"Content-Type": "application/json; charset=utf-8",
             "Content-Disposition": 'attachment; filename="lumacut-sicherung-%s.json"' % stamp})


def _json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValueError("JSON-Objekt erwartet (Content-Type: application/json)")
    return body


@app.get("/api/materials")
def materials_list():
    return jsonify(MATERIALS.list())


@app.post("/api/materials")
def materials_create():
    return jsonify(MATERIALS.create(_json_body()))


@app.put("/api/materials/<material_id>")
def materials_update(material_id):
    return jsonify(MATERIALS.update(material_id, _json_body()))


@app.delete("/api/materials/<material_id>")
def materials_delete(material_id):
    return jsonify(MATERIALS.delete(material_id, request.args.get("base_revision")))


@app.post("/api/commission")
def commission():
    # Confirmation is NEVER an electrical test. Physical inspections are
    # required before real laser use. This only unlocks software motion.
    if machine.owner is not None:
        raise RuntimeError("LightBurn/Job trennen vor Hardwarefreigabe")
    if request.form.get("confirm") != "TESTS_BESTANDEN_LASER_GETRENNT":
        raise ValueError("Zuerst die dokumentierten Prüfungen ohne Laser durchführen")
    if request.form.get("enable") not in ("0","1"):
        raise ValueError("enable 0/1 erwartet")
    enable = request.form["enable"] == "1"
    config["validated"] = enable
    machine.homing_verified = enable
    persist()
    return jsonify(message="Test-Freigabe " + ("aktiviert" if enable else "gesperrt"),
                   hardware_electrically_verified=False)


@app.post("/api/firmware")
def firmware_upload():
    """Flash a new SKR firmware.bin through USB (no SD card handling)."""
    from .firmware_flash import MAX_IMAGE, validate_image
    incoming = request.files.get("file")
    if incoming is None or not incoming.filename:
        raise ValueError("firmware.bin auswählen")
    image = incoming.read(MAX_IMAGE + 1)
    info = validate_image(image)
    local_owner()
    if job_lock.locked():
        raise RuntimeError("Während eines Auftrags wird nicht geflasht")
    if not machine.cap_binary_transfer:
        raise RuntimeError("Aktuelle SKR-Firmware kann keine Dateien empfangen: "
                           "einmalig per SD-Karte eine Firmware mit Pi-Update flashen")
    threading.Thread(target=_flash_worker, args=(image,), daemon=True,
                     name="skr-firmware-update").start()
    return jsonify(message="Firmware-Update gestartet (%d KB, Build %s). SKR startet gleich neu."
                   % (info["bytes"] // 1024, info["build"] or "unbekannt"))


def _flash_worker(image):
    try:
        logging.info("SKR firmware update: %s", machine.flash_firmware(image))
    except Exception:
        logging.exception("SKR firmware update failed")


@app.post("/api/action")
def action():
    op = request.form.get("op", "")
    if op == "estop":
        stop_job.set()
        machine.emergency_stop()
        return jsonify(message="Marlin M112 ausgelöst – physischen Not-Aus prüfen")
    if op == "estop_reset":
        return jsonify(message=machine.clear_emergency())
    if op == "connect":
        machine.ensure_ready()
        return jsonify(message="Marlin M115 + LumaCut-Kennung bestätigt")
    if op == "home":
        _forget_current_placement()
        # clear=1: the operator confirmed the head stands clear (only asked when Z is unknown)
        home_z_first(request.form.get("clear") == "1")
        return jsonify(message="X/Y zuerst, danach Maschinenboden Z=0 und Z-Rückzug: referenziert.")
    if op in ("info","position","endstops"):
        cmd = {"info":"M115", "position":"M114", "endstops":"M119"}[op]
        reply = manual(cmd, timeout=12)
        return jsonify(message="\n".join(reply))
    if op == "report":
        # Read-only Marlin queries for the diagnosis page, nothing else.
        cmd = request.form.get("cmd", "").strip().upper()
        if cmd not in REPORTS:
            raise ValueError("Nur Abfragen: " + ", ".join(REPORTS))
        reply = manual(cmd, timeout=15)
        return jsonify(message="%s (%s) gelesen" % (REPORTS[cmd], cmd), cmd=cmd, lines=reply)
    if op == "jog":
        if not machine.homed:
            raise RuntimeError("Marlin muss zuerst referenziert werden")
        axis = request.form.get("axis","").upper()
        distance = float(request.form.get("distance","0"))
        if axis not in ("X","Y","Z") or distance not in (
                -10.0,-1.0,-0.1,0.1,1.0,10.0):
            raise ValueError("Ungültige Achse oder Schrittweite")
        local_owner()
        _forget_current_placement()
        # Stage a finite move and synchronize before accepting another jog.
        machine.command("M5 I", owner="web")
        machine.command("G91", owner="web")
        machine.command("G0 %s%+.3f F%d" % (
            axis, distance, 360 if axis=="Z" else 1800), owner="web", timeout=30)
        machine.command("M400", owner="web", timeout=45)
        machine.command("G90", owner="web")
        machine.command("M114", owner="web")
        return jsonify(message="Bewegung ausgeführt: " + axis + " " + str(distance))
    if op == "app_update_check":
        # Network only, never touches the machine: allowed at any time.
        info = app_updates.check()
        if info["error"]:
            return jsonify({**info, "error": "App-Update: " + info["error"]}), 503
        text = ("App-Version %s auf dem Pi bereit" % info["version_name"]) if info["available"] else \
            "Noch keine App-Version auf dem Pi"
        return jsonify(message=text, **info)
    if op == "light":
        # Dimmable LED strip on PC8: on=1|0, optional brightness 1..100 %,
        # optional effects=1|0. Without "on" only the settings change.
        local_owner()
        changed = False
        if "effects" in request.form:
            machine.light_effects = config["light_effects"] = request.form.get("effects") == "1"
            changed = True
        pct = request.form.get("brightness")
        pct = None if pct in (None, "") else float(pct)
        target = machine.lights if "on" not in request.form else request.form.get("on") == "1"
        on, level, dimmable = machine.set_light(target, pct, owner="web")
        if pct is not None:
            config["light_brightness"] = level
            changed = True
        if changed:
            persist()
        text = "Licht " + ("EIN" if on else "AUS")
        if on and dimmable:
            text += " · %d %%" % round(level)
        elif dimmable is False and pct is not None:
            text += " (Firmware ohne Dimmen: neue Firmware flashen)"
        return jsonify(message=text, lights=on, brightness=level, dimmable=dimmable)
    if op == "exhaust":
        local_owner()
        target = request.form.get("on") == "1"
        if target != machine.exhaust:
            if target:
                manual("M8")
            else:
                lights = machine.lights
                manual("M9")
                if lights and not machine.lights:
                    machine.set_light(True, owner="web")   # old firmware: M9 also hit PC8
        return jsonify(message="Abluft" + (" EIN" if target else " AUS"))
    if op == "probe":
        # Web counterpart of LightBurn G30: measure the workpiece below the
        # current laser XY (or at an explicitly given point).
        local_owner()
        if not machine.homed:
            raise RuntimeError("Vor dem Abtasten referenzieren")
        point = _optional_point(request.form)
        if point is not None:
            machine.command("G0 X%.3f Y%.3f" % point, owner="web", timeout=60)
        reply = machine.probe_workpiece(owner="web")
        text = "Werkstückoberfläche Z=%.3f mm, Fokus Z=%.3f mm" % (
            machine.surface_z, machine.status()["laser_focus_z"])
        above = _above_bed()
        if above is not None:
            text += ", %.2f mm über dem Bett" % above
        return jsonify(message=text, above_bed_mm=above, detail="\n".join(reply[:6]))
    if op == "bedmap":
        return start_bed_map()
    if op == "matcal":
        return start_material_calibration()
    if op == "bedmap_clear":
        local_owner()
        _set_bed(None)
        return jsonify(message="Bettkarte gelöscht")
    if op == "park":
        # Same routine as LightBurn M2 / end of job: laser off, Z never
        # downward, then X0/Y0 inside the empty keep-out band.
        local_owner()
        machine.park_safezone(owner="web")
        return jsonify(message="Geparkt: Laser aus, Z-Rückzug, X0/Y0")
    if op == "moveto":
        # Laser-off absolute move for the camera scan (machine mm).
        local_owner()
        _forget_current_placement()
        x = float(request.form.get("x", "nan")); y = float(request.form.get("y", "nan"))
        machine.move_to(x, y, owner="web")
        return jsonify(message="Kopf auf X%.1f Y%.1f" % (x, y), position=machine.position)
    if op == "line_laser":
        # Red measuring line laser (never burns); switches itself off after 120 s.
        LINE_LASER.set(request.form.get("on") == "1")
        return jsonify(message="Linienlaser " + ("an" if LINE_LASER.on else "aus"), line_laser=LINE_LASER.status())
    if op == "motion_test":
        # Laser-off stress moves at a test acceleration/speed (motion calibration).
        local_owner()
        _forget_current_placement()
        accel = float(request.form.get("accel", "nan")); speed = float(request.form.get("speed", "nan"))
        x = float(request.form.get("x", "nan")); y = float(request.form.get("y", "nan"))
        span = float(request.form.get("span", "40")); cycles = int(request.form.get("cycles", "6"))
        machine.motion_test(accel, speed, x, y, span, cycles, owner="web")
        return jsonify(message="Testfahrt %g mm/s² · %g mm/s fertig" % (accel, speed), position=machine.position)
    if op == "motion_limits":
        # Measured X/Y limits; both empty = back to the firmware values.
        accel_raw = request.form.get("accel", "").strip(); speed_raw = request.form.get("speed", "").strip()
        if bool(accel_raw) != bool(speed_raw):
            raise ValueError("Beschleunigung und Tempo beide angeben oder beide leer lassen")
        limits = None
        if accel_raw:
            accel = float(accel_raw); speed = float(speed_raw)
            if not (MOTION_ACCEL_RANGE[0] <= accel <= MOTION_ACCEL_RANGE[1]
                    and MOTION_SPEED_RANGE[0] <= speed <= MOTION_SPEED_RANGE[1]):
                raise ValueError("Beschleunigung %g..%g mm/s², Tempo %g..%g mm/s" % (MOTION_ACCEL_RANGE + MOTION_SPEED_RANGE))
            limits = (accel, speed)
        local_owner()
        machine.set_motion_limits(limits, owner="web")
        config["motion"] = {"accel": limits[0] if limits else None, "speed": limits[1] if limits else None}
        persist()
        return jsonify(message=("Bewegung: %g mm/s², bis %g mm/s" % limits) if limits else "Bewegung: Firmware-Werte",
                       motion=config["motion"])
    if op == "origin_set":
        return set_user_origin()
    if op == "origin_clear":
        config["user_origin"] = None
        persist()
        _forget_placement(lambda p: p["origin"] == "user")
        return jsonify(message="Benutzer-Ursprung gelöscht", origin=_origin_status())
    if op == "place":
        return place_job()
    if op == "place_clear":
        _forget_placement(lambda p: True)
        return jsonify(message="Platzierung aufgehoben: Aufträge laufen absolut",
                       origin=_origin_status())
    if op == "queue_add":
        return queue_add()
    if op == "queue_run":
        return queue_run()
    if op in ("queue_remove", "queue_skip", "queue_clear", "queue_pause"):
        return queue_edit(op)
    if op == "frame":
        return start_frame()
    if op == "start":
        return start_job()
    if op == "autorun":
        return start_job(automatic=True)
    if op == "abort":
        if frame["state"] == "running":
            stop_job.set()
            return jsonify(message="Rahmen-Abbruch angefordert: stoppt an der nächsten Ecke, Laser bleibt aus")
        if job_queue["state"] in QUEUE_ACTIVE:
            stop_job.set()
            return jsonify(message="Abbruch angefordert: Laser aus, Parkposition, Warteschlange hält an")
        if job["state"] not in ("homing", "probing", "running"):
            raise RuntimeError("Kein laufender Auftrag")
        stop_job.set()
        return jsonify(message="Abbruch angefordert: Laser aus, danach Parkposition")
    raise ValueError("Unbekannte Marlin-Aktion: " + op)


def _origin_status():
    return {"modes": list(placing.ORIGIN_MODES), "anchors": list(placing.ANCHORS),
            "coord_convention": placing.COORD_CONVENTION,
            "user": config.get("user_origin"),
            "placement": None if job_placement is None else
            {k: v for k, v in job_placement.items() if k != "sha"}}


def _forget_placement(predicate):
    global job_placement
    if job_placement is not None and predicate(job_placement):
        job_placement = None


def _forget_current_placement():
    _forget_placement(lambda p: p["origin"] == "current")


def _content_sha(content):
    import hashlib
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _cut_point(x, y, what):
    import math
    travels = config["travels"]
    limit = machine.safe_zone_xy_mm
    if not (math.isfinite(x) and math.isfinite(y) and
            limit <= x <= travels["x"] and limit <= y <= travels["y"]):
        raise ValueError("%s X%.1f Y%.1f außerhalb des Schneidbereichs X%g..%g / Y%g..%g" % (
            what, x, y, limit, travels["x"], limit, travels["y"]))
    return x, y


def set_user_origin():
    """op=origin_set: store a user origin (explicit x/y, else the head XY)."""
    local_owner()
    if not machine.homed:
        raise RuntimeError("Vor dem Setzen des Ursprungs referenzieren")
    raw_x = request.form.get("x", "").strip()
    raw_y = request.form.get("y", "").strip()
    if raw_x or raw_y:
        x, y = float(raw_x), float(raw_y)
    else:
        x, y = _head_xy()
    x, y = _cut_point(x, y, "Ursprung")
    config["user_origin"] = [round(x, 3), round(y, 3)]
    persist()
    _forget_placement(lambda p: p["origin"] == "user")
    return jsonify(message="Benutzer-Ursprung gesetzt: X%.1f Y%.1f" % (x, y),
                   origin=_origin_status())


def _head_xy():
    """Fresh head XY via M114 (caller holds the web ownership)."""
    machine.command("M114", owner="web", timeout=10)
    pos = machine.position
    if not pos:
        raise RuntimeError("Kopfposition unbekannt – Position abfragen")
    return float(pos[0]), float(pos[1])


def _origin_target(origin):
    if not machine.homed:
        raise RuntimeError("Vor dem Platzieren referenzieren (Ursprung braucht Maschinenkoordinaten)")
    if origin == "current":
        return _cut_point(*_head_xy(), "Kopfposition")
    if origin == "user":
        user = config.get("user_origin")
        if not user:
            raise RuntimeError("Kein Benutzer-Ursprung gesetzt (op=origin_set)")
        return _cut_point(float(user[0]), float(user[1]), "Benutzer-Ursprung")
    raise ValueError("Ursprung muss absolute, current oder user sein")


def _apply_offset(lines, dx, dy):
    """Translated job lines after bounds + guard checks (raises ValueError)."""
    if (dx or dy) and placing.has_relative_xy(lines):
        raise ValueError("Auftrag enthält relative X/Y-Bewegungen (G91) – nur absolut platzierbar")
    placed = placing.translate(lines, dx, dy)
    placing.check_extent(placed, config["travels"], machine.safe_zone_xy_mm)
    preflight("\n".join(placed))
    return placed


def make_placement(filename, content, origin, anchor):
    """Placement dict + translated lines for a stored job (no motion)."""
    origin = origin or "absolute"
    anchor = anchor or placing.DEFAULT_ANCHOR
    if origin not in placing.ORIGIN_MODES:
        raise ValueError("Ursprung muss absolute, current oder user sein")
    if anchor not in placing.ANCHORS:
        raise ValueError("Bezugspunkt muss tl, tr, bl, br oder center sein")
    lines = content.splitlines()
    dx = dy = 0.0
    target = None
    if origin != "absolute":
        target = _origin_target(origin)
        _, powered = placing.scan(lines)
        if powered is None:
            raise ValueError("Auftrag ohne Laserbahnen: Bezugspunkt nicht bestimmbar")
        ax, ay = placing.anchor_point(powered, anchor)
        dx, dy = round(target[0] - ax, 3), round(target[1] - ay, 3)
    placed = _apply_offset(lines, dx, dy)
    motion, powered = placing.scan(placed)
    result = {"file": filename, "origin": origin, "anchor": anchor,
              "dx": dx, "dy": dy, "target": None if target is None else [round(v, 3) for v in target],
              "bounds": None if powered is None else powered.as_dict(),
              "travel": None if motion is None else motion.as_dict(),
              "sha": _content_sha(content)}
    return result, placed


def _job_file(filename):
    if filename != Path(filename).name or not (JOBS / filename).is_file():
        raise ValueError("Unbekannte Auftragsdatei")
    return (JOBS / filename).read_text(encoding="utf-8")


def place_job():
    """op=place: compute and store where a job will run (nothing moves)."""
    global job_placement
    local_owner()
    filename = request.form.get("name", "")
    content = _job_file(filename)
    result, _ = make_placement(filename, content, request.form.get("origin", ""),
                               request.form.get("anchor", ""))
    job_placement = None if result["origin"] == "absolute" else result
    box = result["bounds"]
    where = ("" if box is None else " – Motiv X%.1f..%.1f / Y%.1f..%.1f" % (
        box["xmin"], box["xmax"], box["ymin"], box["ymax"]))
    return jsonify(message="Platziert: %s (%s, Versatz X%+.1f Y%+.1f)%s" % (
        filename, result["origin"], result["dx"], result["dy"], where),
        placement={k: v for k, v in result.items() if k != "sha"})


def _stored_placement(filename, content):
    p = job_placement
    if p is None or (filename and p["file"] != filename):
        raise RuntimeError("Keine gültige Platzierung für %s – neu platzieren (op=place)" % (
            filename or "den Rahmen"))
    if content is not None and p["sha"] != _content_sha(content):
        raise RuntimeError("Auftrag seit dem Platzieren geändert – neu platzieren")
    return p


def _job_lines(filename, content, form):
    """Lines to run: as stored, placed (placement=1) or freshly placed (origin=)."""
    global job_placement
    if form.get("placement") == "1":
        p = _stored_placement(filename, content)
        return _apply_offset(content.splitlines(), p["dx"], p["dy"])
    origin = form.get("origin", "").strip()
    if origin and origin != "absolute":
        result, placed = make_placement(filename, content, origin, form.get("anchor", ""))
        job_placement = result
        return placed
    preflight(content)
    return content.splitlines()


def _optional_point(form):
    raw_x = form.get("x", "").strip()
    raw_y = form.get("y", "").strip()
    if not raw_x and not raw_y:
        return None
    import math
    x, y = float(raw_x), float(raw_y)
    travels = config["travels"]
    if not (math.isfinite(x) and math.isfinite(y) and
            machine.safe_zone_xy_mm <= x <= travels["x"] and
            machine.safe_zone_xy_mm <= y <= travels["y"]):
        raise ValueError("Abtastpunkt außerhalb X30..390 / Y30..370")
    return x, y


app_updates = AppUpdates(DATA)


@app.get("/api/app/android")
def app_android_info():
    """Newest Android app the Pi holds (fetched from the GitHub release)."""
    return jsonify(app_updates.status())


@app.get("/api/app/android.apk")
def app_android_apk():
    if not app_updates.meta():
        return jsonify(error="Keine App-Version auf dem Pi – „Jetzt prüfen“ oder später erneut versuchen"), 404
    return send_from_directory(str(app_updates.dir), app_updates.apk.name,
                               mimetype="application/vnd.android.package-archive",
                               as_attachment=True, download_name="LumaCut.apk")


@app.get("/api/camera/snapshot")
def camera_snapshot():
    """One JPEG from the head camera. Safe at any time: never moves or lasers.

    w/h must be a size the camera offers (else 400). exposure, gain and wb
    override the stored settings for this one picture ("auto" = automatic),
    used by the tablet's light calibration while it searches the values.
    """
    if not os.path.exists(CAMERA):
        raise ConnectionError("Keine Kamera an " + CAMERA + " (LUMACUT_CAMERA in /etc/lumacut/lumacut.env)")
    width = int(request.args.get("w", "1280")); height = int(request.args.get("h", "720"))
    if not (160 <= width <= 4096 and 120 <= height <= 3072):
        raise ValueError("Bildgröße unzulässig")
    settings = dict(head_camera.DEFAULTS, **(config.get("camera") or {}))
    for arg, key in (("exposure", "exposure"), ("gain", "gain"), ("wb", "white_balance")):
        v = request.args.get(arg)
        if v is not None:
            settings[key] = None if v == "auto" else int(v)
    settings = head_camera.validate(settings)
    if request.args.get("light") != "keep":
        _camera_light_on()
    data = head_camera.snapshot(CAMERA, width, height, settings)
    return data, 200, {"Content-Type": "image/jpeg", "Cache-Control": "no-store"}


# Camera light: every snapshot switches the LEDs on at the camera level (the
# app's light calibration, config camera.light; else the normal brightness).
# CAMERA_LIGHT_HOLD_S after the last snapshot the light goes back to how it
# was, so a scan or the live view does not flicker. While a job or LightBurn
# has the machine the light is left alone.
CAMERA_LIGHT_HOLD_S = 8.0
CAMERA_LIGHT_SETTLE_S = 0.3
_cam_light = {"saved": None, "set": None, "timer": None}
_cam_light_lock = threading.Lock()


def _camera_light_level():
    level = (config.get("camera") or {}).get("light")
    return int(level if level is not None else machine.light_pct)


def _camera_light_on():
    level = _camera_light_level()
    changed = False
    with _cam_light_lock:
        if _cam_light["timer"] is not None:
            _cam_light["timer"].cancel()
            _cam_light["timer"] = None
        if not (machine.lights and machine.light_pct == level):
            saved = (machine.lights, machine.light_pct)
            try:
                machine.set_light(True, level, owner="web")
                changed = True
                if _cam_light["saved"] is None:
                    _cam_light["saved"] = saved
                _cam_light["set"] = (True, level)
            except Exception as exc:
                logging.info("Kameralicht nicht geschaltet: %s", exc)
        if _cam_light["saved"] is not None:
            timer = threading.Timer(CAMERA_LIGHT_HOLD_S, _camera_light_restore)
            timer.daemon = True
            _cam_light["timer"] = timer
            timer.start()
    if changed:
        time.sleep(CAMERA_LIGHT_SETTLE_S)


def _camera_light_restore():
    with _cam_light_lock:
        saved, mine = _cam_light["saved"], _cam_light["set"]
        _cam_light.update(saved=None, set=None, timer=None)
        # Someone switched the light in between (app, web UI): theirs stays.
        if saved is None or (machine.lights, machine.light_pct) != mine:
            return
        try:
            machine.set_light(saved[0], saved[1], owner="web")
        except Exception as exc:
            logging.info("Kameralicht nicht zurückgestellt: %s", exc)


def _above_bed():
    """Probed surface above the bed map at the probed point, or None."""
    xy = machine.last_probe_laser_xy
    if BED is None or machine.surface_z is None or xy is None:
        return None
    return round(BED.above_bed(machine.surface_z, *xy), 3)


def _set_bed(bed):
    global BED
    BED = bed
    if bed is None:
        bedmap.delete(BED_MAP_FILE)
    else:
        bedmap.save(BED_MAP_FILE, bed)


@app.get("/api/bedmap")
def bed_map_get():
    """The stored bed map (grid, heights relative to Z0), or bed_map: null."""
    return jsonify(bed_map=None if BED is None else BED.as_dict())


def start_bed_map():
    """op=bedmap: probe the EMPTY bed on a grid with the switch (laser off),
    store the map, park. Runs like a job (job state, abort, progress)."""
    local_owner()
    machine.check_reference()
    if not machine.homed:
        raise RuntimeError("Vor der Bettkarte referenzieren")
    limit = machine.safe_zone_xy_mm
    grid = bedmap.plan(heightmap.Box(limit, limit, config["travels"]["x"], config["travels"]["y"]),
                       machine.probe_reachable)
    order = [i for i in grid.order() if grid.reachable[i]]
    if not job_lock.acquire(blocking=False):
        raise RuntimeError("Ein Auftrag läuft bereits")
    stop_job.clear()
    with machine.lock:
        if machine.owner is not None:
            job_lock.release()
            raise RuntimeError("Steuerung belegt: " + machine.owner)
        machine.owner = "job"
    job.update(file="Bettkarte", state="probing", phase="probing", line=0, total=0,
               error="", probe={"done": 0, "total": len(order) + 1})
    threading.Thread(target=_bed_map_worker, args=(grid, order), daemon=True,
                     name="bed-map").start()
    return jsonify(message="Bettkarte: %d Punkte werden abgetastet – das Bett muss leer sein" % len(order))


def _bed_map_worker(grid, order):
    try:
        values = machine.probe_surface(
            [[grid.probe_point(i) for i in order]], owner="job", hop_mm=bedmap.HOP_MM,
            skip_missing=True,
            progress=lambda done, total: job["probe"].update(done=done, total=total),
            should_stop=stop_job.is_set)
        for i, z in zip(order, values[0]):
            grid.z[i] = z
        bed = bedmap.BedMap.from_measured(grid)
        _set_bed(bed)
        logging.info("Bed map: %s", bed.summary())
        # The bed is no workpiece: the next job must probe its own surface.
        machine.surface_z = None
        _set_phase("parking")
        machine.park_safezone(owner="job")
        job.update(state="complete", phase=None)
    except Exception as exc:
        _job_failed(exc)
    finally:
        with machine.lock:
            machine.owner = None
        job_lock.release()


# --- Adaptive material calibration (op=matcal, matcal.py) ----------------
# Engraving: field by field (laser, photo, measure, next power). Cutting on a
# raised plate: pass by pass until the camera sees the hole open. Runs like a
# job (job state, abort, park); the results are stored as materials.
MATCAL_TITLES = {"engrave": "Materialtest Gravur", "cut": "Materialtest Schnitt"}


def _load_matcal():
    try:
        return json.loads(MATCAL_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return None


MATCAL = {"run": _load_matcal()}


def _save_matcal():
    tmp = MATCAL_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(MATCAL["run"], ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, MATCAL_FILE)


def _matcal_summary():
    run = MATCAL["run"]
    if run is None:
        return None
    steps = run.get("fields") if run["kind"] == "engrave" else run.get("passes")
    return {"kind": run["kind"], "material": run["material"], "state": run["state"],
            "steps": len(steps or ()), "last": (steps or [None])[-1], "result": run.get("result"),
            "saved": run.get("saved"), "error": run.get("error", "")}


@app.get("/api/matcal")
def matcal_get():
    """The last (or running) material calibration with every field/pass."""
    return jsonify(material_calibration=MATCAL["run"])


def _camera_model():
    return matcal.CameraModel(CalibrationStore().load().get("android") or {})


def _matcal_photo(cam, head):
    """Head to the camera position (laser off, Z only up), one grey picture."""
    machine.move_to(head[0], head[1], owner="job")
    settings = head_camera.validate(dict(head_camera.DEFAULTS, **(config.get("camera") or {})))
    error = None
    for _ in range(3):        # the USB camera sometimes drops out for a moment
        _check_stop()
        try:
            jpeg = head_camera.snapshot(CAMERA, cam.photo_w, cam.photo_h, settings)
            return matcal.decode_gray(jpeg, cam.photo_w, cam.photo_h), machine.position[2]
        except Exception as exc:
            error = exc
            time.sleep(1.0)
    raise RuntimeError("Kamera liefert kein Bild (%s) – Kamerakabel prüfen, dann neu starten" % error)


def _matcal_laser(lines):
    for line in lines:
        _check_stop()
        machine.stream_command(line, owner="job", timeout=150)
    machine.drain(owner="job")


def start_material_calibration():
    """op=matcal: kind=engrave|cut, x/y = corner of the test area (machine mm,
    the fields grow towards +X/+Y), name = material. Optional: thickness,
    power/speed (engraving start), power/speeds (cutting, comma list),
    raised=1 (cutting: the plate lies on spacers so pieces can fall out)."""
    local_owner()
    machine.check_reference()
    if not machine.homed:
        raise RuntimeError("Vor dem Materialtest referenzieren")
    if WORKSPACE.material_thickness() is None:
        raise RuntimeError("Erst Material wählen – die Stärke bestimmt die Fahrhöhe")
    form = request.form
    kind = form.get("kind", "")
    if kind not in MATCAL_TITLES:
        raise ValueError("kind muss engrave oder cut sein")
    name = form.get("name", "").strip()
    if not 1 <= len(name) <= 60:
        raise ValueError("Materialname fehlt")
    origin = (float(form.get("x", "nan")), float(form.get("y", "nan")))
    thickness = float(form.get("thickness") or WORKSPACE.material_thickness() or 0)
    if not 0 < thickness <= 50:
        raise ValueError("Materialstärke 0..50 mm")
    if kind == "engrave":
        area = matcal.engrave_area(origin)
        start_power = float(form.get("power") or 10.0)
        speed = float(form.get("speed") or 4500.0)
        if not (1 <= start_power <= 60 and 500 <= speed <= 9000):
            raise ValueError("Startleistung 1..60 %, Tempo 500..9000 mm/min")
        search = matcal.EngraveSearch(start_power=start_power, speed=speed)
    else:
        if form.get("raised") != "1":
            raise RuntimeError("Platte zuerst hochlegen (Abstandhalter, ca. 10 mm Luft): nur dann fällt ein "
                               "durchgeschnittenes Teil heraus und die Kamera sieht das Loch")
        speeds = tuple(float(v) for v in (form.get("speeds") or "").split(",") if v.strip()) or matcal.CUT_SPEEDS
        power = float(form.get("power") or 100.0)
        if not (1 <= len(speeds) <= 6 and all(60 <= v <= 6000 for v in speeds) and 10 <= power <= 100):
            raise ValueError("1..6 Tempi 60..6000 mm/min, Leistung 10..100 %")
        area = matcal.cut_area(origin, len(speeds))
        search = matcal.CutSearch(speeds=speeds, power=power)
    limit = machine.safe_zone_xy_mm
    if not all(v == v for v in origin) or area[0] < limit or area[1] < limit or area[2] > 390 or area[3] > 370:
        raise ValueError("Testbereich X%.0f..%.0f / Y%.0f..%.0f liegt nicht im Arbeitsbereich X%.0f..390 / Y%.0f..370"
                         % (area[0], area[2], area[1], area[3], limit, limit))
    centre = ((area[0] + area[2]) / 2, (area[1] + area[3]) / 2)
    if not machine.probe_reachable(*centre):
        raise ValueError("Die Mitte des Testbereichs ist für den Taster nicht erreichbar")
    if not os.path.exists(CAMERA):
        raise ConnectionError("Keine Kamera an " + CAMERA)
    cam = _camera_model()
    head = cam.head_for(*centre)
    if not (0 <= head[0] <= 390 and 0 <= head[1] <= 370):
        raise ValueError("Für das Foto müsste der Kopf nach X%.0f Y%.0f – Testbereich weiter zur Mitte legen" % head)
    if not job_lock.acquire(blocking=False):
        raise RuntimeError("Ein Auftrag läuft bereits")
    stop_job.clear()
    with machine.lock:
        if machine.owner is not None:
            job_lock.release()
            raise RuntimeError("Steuerung belegt: " + machine.owner)
        machine.owner = "job"
    total = matcal.ENGRAVE_MAX_FIELDS if kind == "engrave" else len(search.speeds) * search.max_passes
    job.update(file=MATCAL_TITLES[kind], state="probing", phase="probing", line=0, total=total,
               error="", probe=None)
    MATCAL["run"] = {"kind": kind, "material": name, "thickness_mm": thickness, "origin": list(origin),
                     "area": [round(v, 2) for v in area], "state": "running",
                     "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "fields" if kind == "engrave" else "passes": [], "result": None, "saved": [], "error": ""}
    threading.Thread(target=_matcal_worker, args=(kind, origin, centre, head, cam, search, name, thickness),
                     daemon=True, name="material-calibration").start()
    what = "Gravur Feld für Feld" if kind == "engrave" else "Schnitt Durchgang für Durchgang"
    return jsonify(message="%s: %s, Testbereich X%.0f..%.0f / Y%.0f..%.0f" % (MATCAL_TITLES[kind], what, *area[0::2], *area[1::2]))


def _matcal_worker(kind, origin, centre, head, cam, search, name, thickness):
    run = MATCAL["run"]
    lights = (machine.lights, machine.light_pct)

    def restore_light():
        try:
            machine.set_light(lights[0], lights[1], owner="job")
        except Exception:
            logging.info("Licht nach dem Materialtest nicht zurückgestellt")
    try:
        machine.command("G0 X%.3f Y%.3f" % centre, owner="job", timeout=60)
        machine.probe_workpiece(owner="job")
        surface, focus_z = machine.surface_z, machine.status()["laser_focus_z"]
        run.update(surface_z=surface, focus_z=focus_z)
        try:
            machine.set_light(True, _camera_light_level(), owner="job")
        except Exception as exc:
            logging.info("Kameralicht nicht geschaltet: %s", exc)
        if config["exhaust_auto"] and not machine.exhaust:
            machine.command("M8", owner="job")
        if kind == "engrave":
            _matcal_engrave(run, origin, head, cam, search, surface, focus_z)
            results = search.results
            run["result"] = {k: {a: v[a] for a in ("power", "speed", "tone", "approximate")} for k, v in results.items()}
            run["saved"] = _matcal_save_engrave(name, thickness, results, matcal.tone_curve(search.fields))
        else:
            _matcal_cut(run, origin, head, cam, search, surface, focus_z)
            best = search.best()
            run["result"] = {"squares": search.squares, "best": best}
            if best is None:
                raise RuntimeError("Kein Quadrat ist durchgefallen – Platte hochgelegt? Langsamer oder mit mehr "
                                   "Leistung testen")
            run["saved"] = _matcal_save_cut(name, thickness, best, search.power)
        run["state"] = "complete"
        restore_light()
        _set_phase("parking")
        machine.park_safezone(owner="job")
        job.update(state="complete", phase=None)
    except Exception as exc:
        run.update(state="aborted" if stop_job.is_set() or isinstance(exc, Aborted) else "error",
                   error=job_error_text(exc))
        restore_light()
        _job_failed(exc)
    finally:
        run["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            _save_matcal()
        except OSError:
            logging.exception("Materialtest nicht gespeichert")
        with machine.lock:
            machine.owner = None
        job_lock.release()
        _exhaust_after_job()


def _matcal_engrave(run, origin, head, cam, search, surface, focus_z):
    before, z = _matcal_photo(cam, head)
    lum_before = cam.sampler(before, head, z, surface)
    guess, reach = (0.0, 0.0), 3.0
    while True:
        step = search.next()
        if step is None:
            return
        k = len(search.fields)
        x, y = matcal.engrave_slot(origin, k)
        _set_phase("running", "running")
        _matcal_laser(matcal.engrave_field(x, y, step["power"], step["speed"], focus_z))
        _set_phase("measuring")
        after, z = _matcal_photo(cam, head)
        lum_after = cam.sampler(after, head, z, surface)
        dx, dy, dark = matcal.locate(lum_before, lum_after, x, y, matcal.ENGRAVE_CELL_MM, guess, reach)
        if dark < 8 and k > 0:
            dx, dy = guess            # hardly any colour: keep the registration seen so far
        else:
            guess, reach = (dx, dy), 1.0
        measured = matcal.measure_field(lum_after, x + dx, y + dy)
        search.add(step, measured)
        run["fields"].append(dict(search.fields[-1], x=round(x, 2), y=round(y, 2),
                                  shift=[round(dx, 2), round(dy, 2)]))
        job["line"] = k + 1
        lum_before = lum_after


def _matcal_cut(run, origin, head, cam, search, surface, focus_z):
    img, z = _matcal_photo(cam, head)
    lum = cam.sampler(img, head, z, surface)
    start = None
    while True:
        step = search.next()
        if step is None:
            return
        x, y = matcal.cut_slot(origin, step["square"])
        if step["pass"] == 0:
            start = matcal.hole_ratio(lum, x, y)
        _set_phase("running", "running")
        _matcal_laser(matcal.cut_pass(x, y, step["speed"], step["power"], focus_z, step["pass"]))
        _set_phase("measuring")
        img, z = _matcal_photo(cam, head)
        lum = cam.sampler(img, head, z, surface)
        ratio = matcal.hole_ratio(lum, x, y)
        fell = ratio < 0.5 * start
        search.add(step, fell)
        run["passes"].append(dict(step, ratio=round(ratio, 3), fell=fell))
        job["line"] = len(run["passes"])


def _upsert_material(name, process, body):
    """Create or update the material with this name and process (Pi = master)."""
    for _ in range(3):
        listing = MATERIALS.list()
        same = [m for m in listing["materials"] if m["name"] == name and m["process"] == process
                and not m.get("builtin")]
        data = dict(body, name=name, process=process, base_revision=listing["revision"])
        try:
            if same:
                return MATERIALS.update(same[0]["id"], data)["material"]
            return MATERIALS.create(data)["material"]
        except ConflictError:
            continue
    raise RuntimeError("Materialliste wurde gleichzeitig geändert – Ergebnis nicht gespeichert")


def _matcal_save_engrave(name, thickness, results, curve=None):
    today = time.strftime("%Y-%m-%d")
    labels = {"dunkel": name, "mittel": name + " (mittel)", "hell": name + " (hell)"}
    saved = []
    for key, label in labels.items():
        f = results.get(key)
        if f is None:
            continue
        note = "Automatische Gravur-Kalibrierung %s: Ton %.2f (Ziel %.2f)%s%s." % (
            today, f["tone"], f["tone_target"], "" if f["clean"] else ", fleckig/streifig",
            ", nur ungefähr getroffen" if f["approximate"] else "")
        m = _upsert_material(label, "Gravieren", {
            "mode": "fill", "thickness_mm": thickness, "power_pct": f["power"],
            "speed_mm_min": round(f["speed"]), "passes": 1, "interval_mm": matcal.INTERVAL_MM,
            "z_step_mm": 0.0, "depth_per_pass_mm": 0.0, "notes": note,
            **({"tone_curve": curve} if curve else {})})
        saved.append({"id": m["id"], "name": label, "process": "Gravieren"})
    return saved


def _matcal_save_cut(name, thickness, best, power):
    note = ("Automatische Schnitt-Kalibrierung %s auf hochgelegter Platte: %d × %d mm/min fiel durch "
            "(wenigste Energie). Immer hochgelegt schneiden." % (time.strftime("%Y-%m-%d"), best["passes"], best["speed"]))
    m = _upsert_material(name, "Schneiden", {
        "mode": "line", "thickness_mm": thickness, "power_pct": power, "speed_mm_min": best["speed"],
        "passes": best["passes"], "interval_mm": matcal.INTERVAL_MM,
        "z_step_mm": matcal.CUT_Z_STEP_MM if best["passes"] > 1 else 0.0, "depth_per_pass_mm": 0.0,
        "notes": note})
    return [{"id": m["id"], "name": name, "process": "Schneiden"}]


@app.get("/api/camera/settings")
def camera_settings():
    """Stored values plus the camera's own ranges (empty without camera)."""
    limits = head_camera.ranges(CAMERA) if os.path.exists(CAMERA) else {}
    return jsonify(dict(head_camera.DEFAULTS, **(config.get("camera") or {}),
                        ranges={k: list(v) for k, v in limits.items()}))


@app.put("/api/camera/settings")
def camera_settings_put():
    """Fixed exposure, gain, white balance and light level (null = automatic)."""
    config["camera"] = head_camera.validate(_json_body())
    persist()
    return jsonify(message="Kamera-Einstellungen gespeichert", **config["camera"])


@app.get("/api/jobs")
def jobs():
    return jsonify(files=[{"name": p.name, "bytes": p.stat().st_size,
                           "modified": int(p.stat().st_mtime)}
                          for p in sorted(JOBS.iterdir())
                          if p.is_file() and p.suffix.lower() in (".gcode",".gc",".nc")])


def _job_path(filename):
    if filename != Path(filename).name:
        raise ValueError("Unzulässiger Dateiname")
    path = JOBS / filename
    if not path.is_file() or path.suffix.lower() not in (".gcode", ".gc", ".nc"):
        raise ValueError("Auftrag nicht gefunden")
    return path


@app.get("/api/jobs/<path:filename>/content")
def job_content(filename):
    """Raw G-code for the toolpath preview in Studio and the tablet app."""
    return _job_path(filename).read_text(encoding="utf-8"), 200, {
        "Content-Type": "text/plain; charset=utf-8"}


@app.post("/api/jobs/<path:filename>/delete")
def job_delete(filename):
    path = _job_path(filename)
    if job["state"] in ("homing", "probing", "running") and job["file"] == path.name:
        raise RuntimeError("Laufender Auftrag kann nicht gelöscht werden")
    if _file_queued(path.name):
        raise RuntimeError("Auftrag steht in der Warteschlange – zuerst dort entfernen")
    path.unlink()
    _forget_placement(lambda p: p["file"] == path.name)
    return jsonify(message="Auftrag gelöscht: " + path.name)


@app.get("/api/jobs/<path:filename>/geometry")
def job_geometry(filename):
    """Preview actual powered toolpath envelope before an automatic probe."""
    if filename != Path(filename).name:
        raise ValueError("Unzulässiger Dateiname")
    path = JOBS / filename
    if not path.is_file():
        raise ValueError("Auftrag nicht gefunden")
    bounds = analyze_job(path.read_text(encoding="utf-8"))
    return jsonify(bounds={"xmin": bounds.xmin, "ymin": bounds.ymin,
                           "xmax": bounds.xmax, "ymax": bounds.ymax},
                   segments=bounds.segments,
                   center=bounds.center,
                   probe_candidates=bounds.probe_grid(),
                   warning="Rasterpunkte sind Kandidaten: Materialabdeckung noch nicht vermessen.")

@app.post("/api/upload")
def upload():
    incoming = request.files.get("file")
    if incoming is None or not incoming.filename:
        raise ValueError("G-Code-Datei auswählen")
    basename = Path(incoming.filename).name
    if (basename != incoming.filename or
            Path(basename).suffix.lower() not in (".gcode", ".gc", ".nc")):
        raise ValueError("Nur .gcode, .gc oder .nc Dateien")
    raw = incoming.read()
    if len(raw) > 32*1024*1024:
        raise ValueError("Auftrag über 32 MB")
    text = raw.decode("utf-8")
    preflight(text)
    temporary = JOBS / (basename + ".partial")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(JOBS / basename)
    _forget_placement(lambda p: p["file"] == basename)
    return jsonify(message="Marlin-Auftrag geprüft und gespeichert: " + basename)


# Workflow commands a LightBurn export may contain. The job worker runs them
# through the same staged Pi routines as the LightBurn TCP gateway.
WORKFLOW = ("G28", "G30", "M2")


def preflight(text):
    if not machine.homing_verified:
        raise RuntimeError("Mechanik noch nicht freigegeben")
    safety = MarlinLaserGuard()
    lines = 0
    for number, line in enumerate(text.splitlines(), 1):
        if normalize(line) in WORKFLOW:
            continue
        try:
            command = safety.check(line, machine.homing_verified)
            if command: lines+=1
        except Exception as exc:
            raise ValueError("G-Code Zeile %d: %s" % (number, exc))
    if not lines:
        raise ValueError("G-Code ist leer")
    focus.check_first_cut(text.splitlines())
    # Reject a motif touching the 30 mm home bands before anything moves,
    # instead of stopping half-way through the job.
    bounds = _powered_bounds(text)
    travels = config["travels"]
    limit = machine.safe_zone_xy_mm
    if bounds is not None and (bounds.xmin < limit or bounds.ymin < limit or
                               bounds.xmax > travels["x"] or bounds.ymax > travels["y"]):
        raise ValueError(
            "Motiv X%.1f..%.1f / Y%.1f..%.1f liegt außerhalb X%g..%g / Y%g..%g "
            "(30-mm-Safezone)" % (bounds.xmin, bounds.xmax, bounds.ymin, bounds.ymax,
                                   limit, travels["x"], limit, travels["y"]))


def _powered_bounds(text):
    try:
        return analyze_job(text)
    except ValueError:
        # Arcs or no powered moves: the live cut guard still checks them.
        return None


def _stop_after_job_error():
    """Laser off and park without M112 when the USB link still works.

    An M112 latches the gateway until the service restarts and the SKR is
    power-cycled; a rejected line or an operator abort does not need that.
    M5 waits for the already buffered segments, then switches PA1 off.
    Escalates to M112 if the controlled stop itself fails.
    """
    try:
        machine.command("M5 I", owner="job", timeout=60)
        if machine.homed:
            machine.park_safezone(owner="job")
    except Exception:
        logging.exception("Controlled job stop failed; issuing M112")
        try:
            machine.emergency_stop()
        except Exception:
            pass


def _job_sets_focus(commands):
    """True when the job moves Z to an absolute height before its first cut.

    Focus-compensated jobs (height mesh) carry their own Z per segment.
    The automatic focus to the single probed surface would then put the
    head at the wrong height over taller workpieces, so it is skipped.
    The Z floor guard still checks every one of those Z targets.
    """
    absolute = True
    z_set = False
    for raw in commands:
        cmd = normalize(raw)
        if cmd == "G90":
            absolute = True
        elif cmd == "G91":
            absolute = False
        elif re.match(r"^G0?[01](?:\s|$)", cmd):
            words = dict(re.findall(r"([A-Z])\s*([-+]?[0-9.]+)", cmd))
            if "Z" in words and absolute:
                z_set = True
            if re.match(r"^G0?1(?:\s|$)", cmd) and float(words.get("S") or 0) > 0:
                return z_set
    return False


def auto_plan(commands, point=None):
    """Plan op=autorun without moving: probe grids and whether to compensate.

    Workflow lines (G28/G30/M2) are dropped, the automatic run does that
    itself. A job with its own absolute Z is already compensated and only
    gets the surface probed (for the Z floor), never compensated again.
    Unsupported jobs (arcs, relative X/Y) are refused here, before anything
    moves, by compensating once against a flat test surface.
    """
    if machine.probe_xy_offset_mm is None:
        raise ValueError("X/Y-Tasterversatz zuerst unter Fokus & Taster eintragen")
    commands = [c for c in commands if normalize(c) not in WORKFLOW]
    # Without the file's G28 the head stands wherever probing left it.
    focus.check_first_cut(commands)
    own_z = focus.has_absolute_z(commands)
    limit = machine.safe_zone_xy_mm
    bounds = heightmap.Box(limit, limit, config["travels"]["x"], config["travels"]["y"])
    tapped = WORKSPACE.probe_points()
    if point is not None:
        grids = heightmap.single_point_plan(point[0], point[1], machine.probe_reachable)
    elif tapped:
        # the operator tapped where material lies (work mm -> machine mm, X mirrored)
        grids = [g for wx, wy in tapped for g in heightmap.single_point_plan(
            config["travels"]["x"] - wx, machine.safe_zone_xy_mm + wy, machine.probe_reachable)]
    else:
        grids = heightmap.plan_probe(commands, bounds, machine.probe_reachable)
    if not own_z:
        flat = heightmap.HeightMapSet([dataclasses.replace(g, z=[0.0] * len(g.z)) for g in grids])
        focus.compensate(commands, flat, machine.focus_gap_mm, machine.probe_tip_offset_mm)
    return {"commands": commands, "grids": grids, "compensate": not own_z,
            "points": sum(sum(g.reachable) for g in grids)}


def _check_stop():
    if stop_job.is_set():
        raise Aborted()


def _set_phase(phase, state=None):
    job.update(phase=phase, state=state or job["state"])


def _check_thickness(measured):
    """The probed surface must fit the chosen material (thickness from the
    bed): a taller object under the probe, the wrong material or a probe
    beside the workpiece stop the job before anything is lasered."""
    thickness = WORKSPACE.material_thickness()
    if thickness is None or not measured:
        return
    tol = float(config["thickness_tolerance_mm"])
    name = (WORKSPACE.get_state().get("material") or {}).get("name", "")
    hi, lo = max(measured), min(measured)
    if hi > thickness + tol:
        raise RuntimeError("Gemessen %.1f mm, Material „%s“ hat %.1f mm – liegt ein höheres Objekt unter dem Taster? "
                           "Material oder Höhe anpassen (Toleranz %.1f mm)." % (hi, name, thickness, tol))
    if lo < thickness - tol:
        raise RuntimeError("Gemessen nur %.1f mm, Material „%s“ hat %.1f mm – falsches Material gewählt oder "
                           "Taster neben dem Werkstück? (Toleranz %.1f mm)" % (lo, name, thickness, tol))


def _auto_prepare(auto):
    """op=autorun before lasering: home if needed, probe, compensate.

    Every step starts and ends with the laser off (safe_home and
    probe_surface send M5 I themselves) and checks for an abort.
    """
    if not machine.homed:
        # Only when needed: after connecting, a reset or an emergency stop.
        _set_phase("homing", "homing")
        machine.safe_home(owner="job", clearance_mm=config["z_clearance_mm"],
                          should_stop=stop_job.is_set, operator_clear=auto.get("operator_clear", False))
    _check_stop()
    _set_phase("probing", "probing")
    grids = [dataclasses.replace(g, z=list(g.z)) for g in auto["grids"]]
    order = [[i for i in g.order() if g.reachable[i]] for g in grids]
    job["probe"] = {"done": 0, "total": sum(len(o) for o in order) + 1}
    values = machine.probe_surface(
        [[g.probe_point(i) for i in o] for g, o in zip(grids, order)], owner="job",
        progress=lambda done, total: job["probe"].update(done=done, total=total),
        should_stop=stop_job.is_set)
    for g, o, measured in zip(grids, order, values):
        for i, z in zip(o, measured):
            g.z[i] = z
    _check_thickness([z for measured in values for z in measured])
    _check_stop()
    commands = auto["commands"]
    if auto["compensate"]:
        _set_phase("focusing")
        commands, report = focus.compensate(
            commands, heightmap.HeightMapSet(grids), machine.focus_gap_mm,
            machine.probe_tip_offset_mm,
            start_z=machine.position[2] if machine.position else None,
            should_stop=stop_job.is_set, travel_z=machine.travel_z)
        logging.info("Autorun focus compensation: %s", report.as_dict())
    _check_stop()
    job.update(state="running", phase="running", total=len(commands))
    return commands


def _execute_job(filename, commands, auto=None):
    """Run one job under the "job" ownership; raises on error/abort.

    Shared by the single-job worker and the queue worker (#17), so both
    use exactly the same homing/probe/focus/park sequence. ``auto`` (from
    auto_plan) makes it the automatic run: home if needed, probe the motif
    areas, let the focus follow the surface, laser, park.
    """
    if auto is None:
        first = "running"
    else:
        first = "probing" if machine.homed else "homing"
    job.update(file=filename, state=first, phase=first, line=0, total=len(commands),
               error="", probe=None)
    if auto is not None:
        commands = _auto_prepare(auto)
    if _job_sets_focus(commands):
        machine.focused_this_job = True
    machine.command("M5 I", owner="job")
    if config["exhaust_auto"] and not machine.exhaust:
        machine.command("M8", owner="job")
    # Start melody on the motor coils (no motion, laser off); a missing or
    # failing melody never stops the job.
    machine.play_melody("start", owner="job")
    for i, command in enumerate(commands, 1):
        _check_stop()
        if _CAPTURE.match(command):
            _capture(command)     # a picture while the line before runs; never stops the job
            job["line"] = i
            continue
        normalized = normalize(command)
        if normalized == "G28":
            machine.safe_home(owner="job", clearance_mm=config["z_clearance_mm"])
        elif normalized == "G30":
            machine.probe_workpiece(owner="job")
        elif normalized == "M2":
            pass  # the worker always parks once at the end
        elif normalized:
            # Plain moves go out in a small ok-counted window (#18); all
            # other lines drain it and run one at a time as before.
            machine.stream_command(command, owner="job", timeout=150)
        job["line"]=i
    _set_phase("finishing")
    machine.drain(owner="job")
    _set_phase("parking")
    machine.park_safezone(owner="job")
    # An abort during the last lines or the park: the job is parked like
    # after any abort, but did not finish as asked.
    if stop_job.is_set():
        aborted = Aborted()
        aborted.parked = True
        raise aborted
    job.update(state="complete", phase=None)


def _capture(command):
    """'; LUMACUT-CAPTURE id=<name> w=<px> h=<px> delay=<ms>' in a job: wait
    [delay] after the line before was sent (the job puts M400 in front of a
    slow line, so it is running), then take one camera picture and keep it as
    captures/<id>.jpg for the app (laser spot / line height measurement)."""
    words = dict(_CAPTURE_WORD.findall(_CAPTURE.match(command).group(1)))
    name = words.get("id", "").lower()
    if not _CAPTURE_NAME.match(name) or not os.path.exists(CAMERA):
        logging.warning("Capture ignored: %s", command.strip())
        return
    try:
        time.sleep(min(int(words.get("delay", "800")), 5000) / 1000.0)
        settings = head_camera.validate(dict(head_camera.DEFAULTS, **(config.get("camera") or {})))
        data = head_camera.snapshot(CAMERA, int(words.get("w", "1920")), int(words.get("h", "1080")), settings)
        CAPTURES.mkdir(parents=True, exist_ok=True)
        old = sorted(CAPTURES.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
        for p in old[:-199]:
            p.unlink(missing_ok=True)
        (CAPTURES / (name + ".jpg")).write_bytes(data)
    except Exception:
        logging.exception("Capture %s failed", name)


@app.get("/api/camera/captures/<name>")
def camera_capture(name):
    """A picture a job took while the laser ran (see _capture)."""
    if not _CAPTURE_NAME.match(name):
        raise ValueError("Unzulässiger Name")
    path = CAPTURES / (name + ".jpg")
    if not path.is_file():
        return jsonify(error="Kein solches Bild"), 404
    return path.read_bytes(), 200, {"Content-Type": "image/jpeg", "Cache-Control": "no-store"}


@app.delete("/api/camera/captures")
def camera_captures_clear():
    removed = 0
    if CAPTURES.is_dir():
        for p in CAPTURES.glob("*.jpg"):
            p.unlink(missing_ok=True)
            removed += 1
    return jsonify(message="%d Bilder gelöscht" % removed)


def job_error_text(exc):
    """One German sentence with the next step for job.error."""
    if stop_job.is_set() or isinstance(exc, Aborted):
        return "Abgebrochen"
    if isinstance(exc, ProbeFailed):
        cause = str(exc.cause)
        where = "bei X%.0f Y%.0f" % (exc.x, exc.y)
        if "ohne Tasterkontakt" in cause:
            return ("Der Taster hat %s kein Material gefunden – Material unter das Motiv "
                    "legen oder den Tasterversatz prüfen, dann neu starten." % where)
        if "schon beim G30-Start" in cause:
            return ("Der Taster war %s schon gedrückt – Taster und Kabel prüfen, dann neu "
                    "starten." % where)
        return ("Abtasten %s fehlgeschlagen (%s) – Taster prüfen, dann neu starten."
                % (where, cause.rstrip(".")))
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return ("Verbindung zur Steuerung unterbrochen (%s) – USB-Kabel prüfen, dann neu "
                "starten." % str(exc).rstrip("."))
    return str(exc)


def _job_failed(exc):
    job.update(state="aborted" if stop_job.is_set() or isinstance(exc, Aborted) else "error",
               error=job_error_text(exc), phase=None)
    if not machine.emergency_latched and not getattr(exc, "parked", False):
        _stop_after_job_error()
    if job["state"] == "error" and not machine.emergency_latched:
        try:
            machine.light_effect("error", owner="job")   # light only, no tones; not on operator abort
        except Exception:
            logging.exception("Error light effect failed")


def _exhaust_after_job():
    """With exhaust_auto: switch the exhaust off exhaust_after_s after a job,
    unless the next job or someone else has the machine by then."""
    if not config["exhaust_auto"] or not machine.exhaust:
        return

    def off():
        time.sleep(float(config["exhaust_after_s"]))
        if job_lock.locked() or not machine.exhaust or machine.emergency_latched:
            return
        with machine.lock:
            if machine.owner is not None:
                return
        try:
            lights = machine.lights
            machine.command("M9", owner="web", timeout=10)
            if lights and not machine.lights:
                machine.set_light(True, owner="web")   # old firmware: M9 also hit PC8
        except Exception:
            logging.exception("Exhaust run-on: switching off failed")
    threading.Thread(target=off, daemon=True, name="exhaust-run-on").start()


def _job_worker(filename, commands, auto=None):
    try:
        _execute_job(filename, commands, auto)
    except Exception as exc:
        _job_failed(exc)
    finally:
        with machine.lock:
            machine.owner=None
        job_lock.release()
        _exhaust_after_job()


def start_job(automatic=False):
    local_owner()
    # Head moved by hand / steps lost? (X/Y switches at X0/Y0) - then not homed:
    # the automatic run homes first, a plain start is refused below.
    machine.check_reference()
    if WORKSPACE.material_thickness() is None:
        raise RuntimeError("Erst Material wählen – die Stärke bestimmt die Fahrhöhe")
    if not machine.homed and not automatic:
        raise RuntimeError("Vor dem Job referenzieren")
    filename = request.form.get("name","")
    content = _job_file(filename)
    # Absolute by default (LightBurn/web UI/older Studio); placed with
    # placement=1 or origin=current|user (Studio #16). Bounds and guard
    # are checked on the lines that will actually be sent.
    commands = _job_lines(filename, content, request.form)
    auto = None
    if automatic:
        # x/y: probe only that one point (old one-click behaviour).
        auto = auto_plan(commands, _optional_point(request.form))
        auto["operator_clear"] = request.form.get("clear") == "1"
        commands = auto["commands"]
    needs_home = not machine.homed
    if not job_lock.acquire(blocking=False):
        raise RuntimeError("Ein Auftrag läuft bereits")
    stop_job.clear()
    with machine.lock:
        if machine.owner is not None:
            job_lock.release()
            raise RuntimeError("LightBurn hat inzwischen die Steuerung")
        machine.owner="job"
    thread = threading.Thread(target=_job_worker,
                              args=(filename,commands,auto), daemon=True,
                              name="marlin-gcode-job")
    thread.start()
    if automatic:
        return jsonify(message="Automatischer Ablauf gestartet: %sAbtasten (%d Punkte) → %s → "
                       "%s → Parken" % ("Referenzieren → " if needs_home else "",
                                        auto["points"] + 1,
                                        "Höhenkorrektur" if auto["compensate"]
                                        else "eigenes Z des Auftrags", filename))
    return jsonify(message="Job gestartet: " + filename)


# --- Multi-job queue (gap analysis #17) --------------------------------
# An in-memory list of stored jobs that run one after another under one
# "job" ownership, each through the same automatic run as op=autorun (home
# when needed, probe, focus compensation, park after every job, laser off
# between jobs). The placement
# (origin/anchor -> dx/dy) is frozen when an item is added, so jogging after
# queue_add does not move queued work; the file sha is frozen too and a job
# changed since then is refused. Abort, E-stop or an error stop the queue;
# the remaining items stay "queued" for a later queue_run. Not persisted:
# a service restart empties the queue (nothing runs without a new run).
QUEUE_MAX = 50
job_queue = {"items": [], "state": "idle", "current": None, "next_id": 1}
queue_lock = threading.Lock()
queue_pause = threading.Event()
QUEUE_ACTIVE = ("running", "pausing")


def _queue_status():
    with queue_lock:
        return {"items": [{k: v for k, v in item.items() if k != "sha"}
                          for item in job_queue["items"]],
                "state": job_queue["state"], "current": job_queue["current"],
                "max": QUEUE_MAX}


def _queue_item(raw_id):
    """Item by id (caller holds queue_lock)."""
    try:
        wanted = int(raw_id)
    except (TypeError, ValueError):
        raise ValueError("Warteschlangen-Eintrag fehlt (Feld id)")
    for item in job_queue["items"]:
        if item["id"] == wanted:
            return item
    raise ValueError("Warteschlangen-Eintrag %d nicht gefunden" % wanted)


def queue_add():
    """op=queue_add: append a stored job with a frozen placement (nothing moves)."""
    filename = request.form.get("name", "")
    content = _job_file(filename)
    origin = request.form.get("origin", "").strip() or "absolute"
    if request.form.get("placement") == "1":
        p = _stored_placement(filename, content)
        _apply_offset(content.splitlines(), p["dx"], p["dy"])
        result = dict(p)
    else:
        if origin == "current":
            local_owner()   # fresh M114 needs the controller
        result, _ = make_placement(filename, content, origin,
                                   request.form.get("anchor", ""))
    with queue_lock:
        if len(job_queue["items"]) >= QUEUE_MAX:
            raise RuntimeError("Warteschlange voll (max. %d Einträge)" % QUEUE_MAX)
        item = {"id": job_queue["next_id"], "file": filename,
                "origin": result["origin"], "anchor": result["anchor"],
                "dx": result["dx"], "dy": result["dy"], "target": result.get("target"),
                "bounds": result.get("bounds"), "sha": result["sha"],
                "state": "queued", "error": ""}
        job_queue["next_id"] += 1
        job_queue["items"].append(item)
    return jsonify(message="Eingereiht: %s (#%d, %s)" % (filename, item["id"], item["origin"]),
                   queue=_queue_status())


def queue_edit(op):
    """op=queue_remove|queue_skip|queue_clear|queue_pause."""
    with queue_lock:
        if op == "queue_pause":
            if job_queue["state"] != "running":
                raise RuntimeError("Warteschlange läuft nicht")
            queue_pause.set()
            job_queue["state"] = "pausing"
            message = "Warteschlange hält nach dem laufenden Auftrag an"
        elif op == "queue_clear":
            job_queue["items"] = [i for i in job_queue["items"] if i["state"] == "running"]
            message = "Warteschlange geleert"
        else:
            item = _queue_item(request.form.get("id"))
            if item["state"] == "running":
                raise RuntimeError("Laufender Auftrag: zuerst abbrechen")
            if op == "queue_skip":
                if item["state"] != "queued":
                    raise RuntimeError("Nur wartende Aufträge können übersprungen werden")
                item["state"] = "skipped"
                message = "Übersprungen: %s (#%d)" % (item["file"], item["id"])
            else:
                job_queue["items"].remove(item)
                message = "Entfernt: %s (#%d)" % (item["file"], item["id"])
    return jsonify(message=message, queue=_queue_status())


def _queue_commands(item):
    """Lines for a queued item, re-checked now (file, sha, bounds, guard)."""
    content = _job_file(item["file"])
    if _content_sha(content) != item["sha"]:
        raise RuntimeError("%s seit dem Einreihen geändert – neu einreihen" % item["file"])
    return _apply_offset(content.splitlines(), item["dx"], item["dy"])


def _queue_worker():
    final = "complete"
    try:
        while True:
            if stop_job.is_set():
                final = "stopped"
                break
            if queue_pause.is_set():
                final = "paused"
                break
            with queue_lock:
                item = next((i for i in job_queue["items"] if i["state"] == "queued"), None)
                if item is None:
                    break
                item.update(state="running", error="")
                job_queue["current"] = item["id"]
            try:
                job.update(file=item["file"], error="")
                # Same automatic run as op=autorun: home if needed, probe,
                # focus follows the surface, laser, park.
                auto = auto_plan(_queue_commands(item))
                _execute_job(item["file"], auto["commands"], auto)
            except Exception as exc:
                _job_failed(exc)
                with queue_lock:
                    item.update(state="aborted" if job["state"] == "aborted" else "error",
                                error=job["error"])
                final = "stopped"
                break
            with queue_lock:
                item["state"] = "done"
    except Exception:       # pragma: no cover - defensive
        logging.exception("Queue worker failed")
        final = "stopped"
    finally:
        with queue_lock:
            job_queue.update(state=final, current=None)
        with machine.lock:
            machine.owner = None
        job_lock.release()
        _exhaust_after_job()


def queue_run():
    """op=queue_run: run the waiting items in order (stops on error/abort)."""
    local_owner()
    machine.check_reference()     # moved by hand: the first item homes first
    with queue_lock:
        if job_queue["state"] in QUEUE_ACTIVE:
            raise RuntimeError("Warteschlange läuft bereits")
        queued = [dict(i) for i in job_queue["items"] if i["state"] == "queued"]
    waiting = len(queued)
    if not waiting:
        raise RuntimeError("Keine wartenden Aufträge in der Warteschlange")
    # Every item runs automatically (homing only when needed); refuse what
    # cannot run before anything moves.
    for item in queued:
        try:
            auto_plan(_queue_commands(item))
        except (ValueError, RuntimeError) as exc:
            raise ValueError("Warteschlange #%d (%s): %s" % (item["id"], item["file"], exc))
    if not job_lock.acquire(blocking=False):
        raise RuntimeError("Ein Auftrag oder Rahmen läuft bereits")
    stop_job.clear()
    queue_pause.clear()
    with machine.lock:
        if machine.owner is not None:
            job_lock.release()
            raise RuntimeError("Steuerung inzwischen belegt durch " + machine.owner)
        machine.owner = "job"
    with queue_lock:
        job_queue["state"] = "running"
    threading.Thread(target=_queue_worker, daemon=True, name="marlin-job-queue").start()
    return jsonify(message="Warteschlange gestartet: %d Auftrag/Aufträge" % waiting,
                   queue=_queue_status())


def _file_queued(name):
    with queue_lock:
        return any(i["file"] == name and i["state"] in ("queued", "running")
                   for i in job_queue["items"])


def frame_program(text):
    """Validate a Studio frame program: laser-off absolute XY moves only.

    Stricter than a job: no M3, no Z, no arcs, no relative moves, S only 0,
    every point inside the machine travel. Each line also passes a fresh
    MarlinLaserGuard, and the transport guard checks it again when sent.
    """
    if not machine.homing_verified:
        raise RuntimeError("Mechanik noch nicht freigegeben")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Rahmenprogramm fehlt (Feld gcode)")
    if len(text.encode("utf-8")) > FRAME_MAX_BYTES:
        raise ValueError("Rahmenprogramm zu groß (max. 64 KB)")
    guard = MarlinLaserGuard()
    travels = config["travels"]
    commands, moves = [], 0
    for number, line in enumerate(text.splitlines(), 1):
        cmd = normalize(line)
        if not cmd:
            continue
        try:
            if cmd not in _FRAME_SETUP:
                if not _FRAME_MOVE.match(cmd):
                    raise ValueError("im Rahmen nur G0/G1 X/Y (S0), G21, G90, M5 I, M400")
                words = _FRAME_WORD.findall(cmd)
                letters = [k for k, _ in words]
                if len(set(letters)) != len(letters):
                    raise ValueError("Parameter doppelt")
                values = {k: float(v) for k, v in words}
                if "X" not in values and "Y" not in values:
                    raise ValueError("Fahrbewegung ohne X/Y")
                if values.get("S", 0.0) != 0.0:
                    raise ValueError("Laserleistung im Rahmen verboten (nur S0)")
                if not (0.0 <= values.get("X", 0.0) <= travels["x"] and
                        0.0 <= values.get("Y", 0.0) <= travels["y"]):
                    raise ValueError("Punkt außerhalb X0..%g / Y0..%g" % (
                        travels["x"], travels["y"]))
                if "F" in values and not 60.0 <= values["F"] <= 9000.0:
                    raise ValueError("Vorschub außerhalb 60..9000 mm/min")
                moves += 1
            guard.check(cmd, True)
        except ValueError as exc:
            raise ValueError("Rahmen Zeile %d: %s" % (number, exc))
        commands.append(cmd)
    if not moves:
        raise ValueError("Rahmen enthält keine Fahrbewegung")
    if moves > FRAME_MAX_MOVES:
        raise ValueError("Rahmen mit mehr als %d Fahrbewegungen" % FRAME_MAX_MOVES)
    return commands


def _frame_worker(commands):
    try:
        machine.command("M5 I", owner="frame", timeout=30)
        machine.command("G90", owner="frame", timeout=8)
        for i, command in enumerate(commands, 1):
            if stop_job.is_set():
                raise RuntimeError("Abgebrochen")
            if machine.laser_enabled:
                raise RuntimeError("Laser unerwartet aktiv – Rahmen gestoppt")
            machine.command(command, owner="frame", timeout=150)
            if _FRAME_MOVE.match(command):
                # Wait for each edge, so an abort stops at the next corner
                # instead of after Marlin has drained the whole outline.
                machine.command("M400", owner="frame", timeout=600)
            frame["line"] = i
        machine.command("M5 I", owner="frame", timeout=30)
        frame["state"] = "complete"
    except Exception as exc:
        frame.update(state="aborted" if stop_job.is_set() else "error", error=str(exc))
        if not machine.emergency_latched:
            try:
                machine.command("M5 I", owner="frame", timeout=60)
            except Exception:
                logging.exception("Controlled frame stop failed; issuing M112")
                try:
                    machine.emergency_stop()
                except Exception:
                    pass
    finally:
        with machine.lock:
            machine.owner = None
        job_lock.release()


def start_frame():
    """op=frame: trace a laser-off outline without touching stored jobs."""
    local_owner()
    if machine.emergency_latched:
        raise RuntimeError("Notstopp aktiv – erst quittieren")
    machine.check_reference()
    if not machine.homed:
        raise RuntimeError("Vor dem Rahmen referenzieren")
    mode = request.form.get("mode", "box") or "box"
    if mode not in FRAME_MODES:
        raise ValueError("Rahmenart muss box oder hull sein")
    text = request.form.get("gcode", "")
    if request.form.get("placement") == "1":
        # Same offset as the placed job, so the frame shows where it will run.
        p = _stored_placement(request.form.get("name", ""), None)
        if isinstance(text, str) and len(text.encode("utf-8")) <= FRAME_MAX_BYTES:
            text = "\n".join(placing.translate(text.splitlines(), p["dx"], p["dy"]))
    commands = frame_program(text)
    if not job_lock.acquire(blocking=False):
        raise RuntimeError("Ein Auftrag oder Rahmen läuft bereits")
    stop_job.clear()
    with machine.lock:
        if machine.owner is not None:
            job_lock.release()
            raise RuntimeError("Steuerung inzwischen belegt durch " + machine.owner)
        machine.owner = "frame"
    frame.update(state="running", mode=mode, line=0, total=len(commands), error="")
    threading.Thread(target=_frame_worker, args=(commands,), daemon=True,
                     name="marlin-frame").start()
    return jsonify(message="Rahmenfahrt gestartet (%s, Laser aus)" % FRAME_MODES[mode],
                   frame=dict(frame))


def _remember_z(state={"z": None}):
    """Keeps the last known head height on disk (decides the lift before
    homing after an emergency stop or SKR reset)."""
    z = machine.last_known_z
    if z is None or (state["z"] is not None and abs(z - state["z"]) < 0.2):
        return
    try:
        tmp = LAST_Z.with_suffix(".tmp")
        tmp.write_text(json.dumps({"z": round(z, 3), "at": int(time.time())}), encoding="utf-8")
        os.replace(tmp, LAST_Z)
        state["z"] = z
    except OSError:
        logging.warning("Letzte Z-Höhe nicht gespeichert", exc_info=True)


def monitor_loop():
    last_attempt=0.0
    while running:
        time.sleep(2.0)
        _remember_z()
        try:
            machine.service_cooldown()
        except Exception:
            logging.exception("Laser fan cooldown processing failed")
        if machine.owner is not None or machine.emergency_latched:
            continue
        if machine.serial is None and time.monotonic()-last_attempt >= 8.0:
            last_attempt=time.monotonic()
            try:
                machine.ensure_ready()
            except Exception as exc:
                logging.debug("Marlin USB unavailable: %s", exc)
        elif machine.serial is not None and machine.identity:
            try:
                machine.command("M114", owner="monitor", use_guard=False, timeout=5)
                if job["state"] not in ("homing", "probing", "running") and frame["state"] != "running":
                    machine.check_reference()
            except Exception:
                logging.warning("Marlin heartbeat failed", exc_info=True)


def main():
    global running
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    running=True
    threading.Thread(target=monitor_loop, daemon=True,
                     name="marlin-usb-heartbeat").start()
    threading.Thread(target=app_updates.run_forever,
                     args=(lambda: running, lambda: job["state"] in ("homing", "probing", "running")),
                     daemon=True, name="android-app-updates").start()
    threading.Thread(target=serve_tcp,
                     args=(machine,"0.0.0.0",TCP,lambda: running),
                     daemon=True, name="marlin-lightburn-server").start()
    try:
        app.run(host="0.0.0.0", port=HTTP, threaded=True, use_reloader=False)
    finally:
        running=False
        # Normal service maintenance must not leave the SKR hard-killed.
        # Still hard-stop any live LightBurn/job ownership or armed cutter.
        # With idle, verified USB, explicitly send cutter-off and wait for
        # completion; if that fails, escalate to the emergency parser.
        with machine.lock:
            unsafe = (machine.owner is not None or
                      machine.laser_enabled or
                      machine.state == "Busy")
            idle_connected = (machine.serial is not None and
                              bool(machine.identity) and
                              not machine.emergency_latched)
        if unsafe:
            try:
                machine.emergency_stop()
            except Exception:
                logging.exception("Could not issue emergency stop on exit")
        elif idle_connected:
            try:
                machine.command("M5 I", owner="shutdown", timeout=5)
                machine.command("M400", owner="shutdown", timeout=5)
            except Exception:
                logging.exception("Cutter-off handshake failed; issuing M112")
                try:
                    machine.emergency_stop()
                except Exception:
                    logging.exception("Emergency stop failed")
        # No USB means there is no safe software stop to send.
        # Physical laser power interlocks remain necessary.


if __name__=="__main__":
    main()
