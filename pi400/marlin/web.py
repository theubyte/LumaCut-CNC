"""Headless Raspberry Pi 400 control server for native Marlin on SKR Mini MZ.

Web UI and HTTP API on port 8080 for LumaCut Studio and browsers.
TCP 23 remains for LightBurn (Marlin device) until Studio replaces it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from .transport import MarlinTransport, MarlinLaserGuard, normalize, serve_tcp
from .smart_cam import analyze_job

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("LUMACUT_DATA", "/var/lib/lumacut")) / "marlin"
JOBS = DATA / "jobs"
USB = os.environ.get("LUMACUT_SKR", "/dev/ttyACM0")
# Head camera (USB/UVC or CSI via V4L2) for the workspace scan.
CAMERA = os.environ.get("LUMACUT_CAMERA", "/dev/video0")
JPEG_MAGIC = bytes([0xFF, 0xD8])
HTTP = int(os.environ.get("LUMACUT_HTTP", "8080"))
TCP = int(os.environ.get("LUMACUT_TCP", "23"))
machine = MarlinTransport(USB)
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
config = {
    "validated": False,        # mechanics confirmed once via /api/commission
    "z_clearance_mm": 20.0,
    "focus_gap_mm": 7.0,
    "z_switch_tip_offset_mm": 1.5,
    "probe_offset_x_mm": None,
    "probe_offset_y_mm": None,  # tip height above reference plane at switch trigger
    "travels": {"x": 390.0, "y": 370.0, "z": 90.0},
}
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
machine.homing_verified = bool(config["validated"])
machine.clearance_mm = float(config["z_clearance_mm"])
machine.probe_tip_offset_mm = float(config["z_switch_tip_offset_mm"])
machine.focus_gap_mm = float(config["focus_gap_mm"])
if config["probe_offset_x_mm"] is not None and config["probe_offset_y_mm"] is not None:
    machine.probe_xy_offset_mm = (float(config["probe_offset_x_mm"]),
                                  float(config["probe_offset_y_mm"]))
job = {"file": "", "state": "idle", "line": 0, "total": 0, "error": ""}
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
    logging.exception("Marlin Control server request failed: %s", exc)
    if isinstance(exc, (ValueError, RuntimeError, PermissionError)):
        return jsonify(error=str(exc)), 400
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return jsonify(error=str(exc)), 503
    return jsonify(error="Interner Fehler – Pi-Protokoll ansehen"), 500


@app.get("/")
def homepage():
    return send_from_directory(str(ROOT), "index.html")


@app.get("/api/status")
def status():
    result = machine.status()
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
                            "job" if job["state"] in ("homing", "probing", "running")
                            else "idle"),
                  firmware="marlin",
                  expected_pwm="PA1 / M3 I / S0..255",
                  io={"laser_supply_switch":"FAN1 / PC6 (M106/M107, low-side)",
                      "laser_pwm":"BL-Touch / PA1",
                      "fan_cooldown":"180s via Pi: requires firmware FAN0 PC6; no crash-proof fan timer",
                      "exhaust":"BED PC9 M8",
                      "lights":"HE0 PC8 M7",
                      "aux":"FAN2 PC7 unused"},
                  config=dict(config),
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


def home_z_first():
    # Reuse the exact same atomic safe-home transaction as the LightBurn
    # G28 compatibility layer. Never let two implementations diverge.
    local_owner()
    machine.safe_home(owner="web", clearance_mm=config["z_clearance_mm"])


@app.post("/api/settings")
def settings():
    # Configuration can be edited while homed and while LightBurn owns TCP.
    # This endpoint never sends motion or laser commands to the SKR.
    import math
    clearance = float(request.form.get("z_clearance_mm", "nan"))
    gap = float(request.form.get("focus_gap_mm", "nan"))
    offset = float(request.form.get("z_switch_tip_offset_mm", "nan"))
    # Off-axis switch displacement relative to laser spot, signed machine XY.
    probe_x_raw = request.form.get("probe_offset_x_mm", "").strip()
    probe_y_raw = request.form.get("probe_offset_y_mm", "").strip()
    if bool(probe_x_raw) != bool(probe_y_raw):
        raise ValueError("X/Y-Tasterversatz entweder beide eintragen oder beide leer lassen")
    probe_x = float(probe_x_raw) if probe_x_raw else None
    probe_y = float(probe_y_raw) if probe_y_raw else None
    if not (math.isfinite(clearance) and 0.5 <= clearance <= 50):
        raise ValueError("Z-Rückzug muss zwischen 0,5 und 50 mm liegen")
    if not (math.isfinite(gap) and 0.1 <= gap <= 30):
        raise ValueError("Fokusabstand muss zwischen 0,1 und 30 mm liegen")
    if not (math.isfinite(offset) and -20 <= offset <= 20):
        raise ValueError("Schalter-zu-Spitze-Offset muss zwischen -20 und +20 mm liegen")
    if probe_x is not None and not (math.isfinite(probe_x) and -80 <= probe_x <= 80 and
            math.isfinite(probe_y) and -80 <= probe_y <= 80):
        raise ValueError("Taster-X/Y-Versatz muss -80..80 mm sein")
    config["probe_offset_x_mm"] = probe_x
    config["probe_offset_y_mm"] = probe_y
    with machine.lock:
        machine.probe_xy_offset_mm = (probe_x, probe_y) if probe_x is not None else None
        machine.clearance_mm = clearance
        machine.probe_tip_offset_mm = offset
        machine.focus_gap_mm = gap
        # Any new probe geometry invalidates the prior measured material height.
        machine.surface_z = None
        machine.focused_this_job = False
    config["z_clearance_mm"] = clearance
    config["focus_gap_mm"] = gap
    config["z_switch_tip_offset_mm"] = offset
    persist()
    return jsonify(message="Z-Offset, Sicherheitsabstand und Fokusreferenz dauerhaft gespeichert",
                   z_clearance_mm=clearance, focus_gap_mm=gap,
                   z_switch_tip_offset_mm=offset,
                   probe_offset_x_mm=probe_x, probe_offset_y_mm=probe_y,
                   note="LightBurn G28 referenziert Boden, G30 tastet Werkstück über X/Y-Tasterversatz ab, ohne Maschinen-Z0 zu verändern.")

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
        home_z_first()
        return jsonify(message="X/Y zuerst, danach Maschinenboden Z=0 und Z-Rückzug: referenziert.")
    if op in ("info","position","endstops"):
        cmd = {"info":"M115", "position":"M114", "endstops":"M119"}[op]
        reply = manual(cmd, timeout=12)
        return jsonify(message="\n".join(reply))
    if op == "jog":
        if not machine.homed:
            raise RuntimeError("Marlin muss zuerst referenziert werden")
        axis = request.form.get("axis","").upper()
        distance = float(request.form.get("distance","0"))
        if axis not in ("X","Y","Z") or distance not in (
                -10.0,-1.0,-0.1,0.1,1.0,10.0):
            raise ValueError("Ungültige Achse oder Schrittweite")
        local_owner()
        # Stage a finite move and synchronize before accepting another jog.
        machine.command("M5 I", owner="web")
        machine.command("G91", owner="web")
        machine.command("G0 %s%+.3f F%d" % (
            axis, distance, 360 if axis=="Z" else 1800), owner="web", timeout=30)
        machine.command("M400", owner="web", timeout=45)
        machine.command("G90", owner="web")
        machine.command("M114", owner="web")
        return jsonify(message="Bewegung ausgeführt: " + axis + " " + str(distance))
    if op in ("light","exhaust"):
        local_owner()
        target = request.form.get("on") == "1"
        if op=="light":
            old, other = machine.lights, machine.exhaust
            if target!=old:
                if target:
                    manual("M7")
                else:
                    manual("M9")
                    if other: manual("M8")
        else:
            old, other = machine.exhaust, machine.lights
            if target!=old:
                if target:
                    manual("M8")
                else:
                    manual("M9")
                    if other: manual("M7")
        return jsonify(message=("Licht" if op=="light" else "Abluft") +
                       (" EIN" if target else " AUS"))
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
        return jsonify(message="Werkstückoberfläche Z=%.3f mm, Fokus Z=%.3f mm" % (
            machine.surface_z, machine.status()["laser_focus_z"]),
            detail="\n".join(reply[:6]))
    if op == "park":
        # Same routine as LightBurn M2 / end of job: laser off, Z never
        # downward, then X0/Y0 inside the empty keep-out band.
        local_owner()
        machine.park_safezone(owner="web")
        return jsonify(message="Geparkt: Laser aus, Z-Rückzug, X0/Y0")
    if op == "moveto":
        # Laser-off absolute move for the camera scan (machine mm).
        local_owner()
        x = float(request.form.get("x", "nan")); y = float(request.form.get("y", "nan"))
        machine.move_to(x, y, owner="web")
        return jsonify(message="Kopf auf X%.1f Y%.1f" % (x, y), position=machine.position)
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
        if job["state"] not in ("homing", "probing", "running"):
            raise RuntimeError("Kein laufender Auftrag")
        stop_job.set()
        return jsonify(message="Abbruch angefordert: Laser aus, danach Parkposition")
    raise ValueError("Unbekannte Marlin-Aktion: " + op)


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


@app.get("/api/camera/snapshot")
def camera_snapshot():
    """One JPEG from the head camera. Safe at any time: never moves or lasers."""
    import subprocess
    if not os.path.exists(CAMERA):
        raise ConnectionError("Keine Kamera an " + CAMERA + " (LUMACUT_CAMERA in /etc/lumacut/lumacut.env)")
    width = int(request.args.get("w", "1280")); height = int(request.args.get("h", "960"))
    if not (160 <= width <= 4096 and 120 <= height <= 3072):
        raise ValueError("Bildgröße unzulässig")
    # Several frames are read so auto exposure settles; only the last one is kept.
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "v4l2",
           "-video_size", "%dx%d" % (width, height), "-i", CAMERA,
           "-vf", r"select=gte(n\,5)", "-frames:v", "1", "-q:v", "3", "-f", "image2", "pipe:1"]
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConnectionError("Kamera antwortet nicht: " + str(exc)[:120])
    if done.returncode != 0 or not done.stdout.startswith(JPEG_MAGIC):
        raise ConnectionError("Kamera lieferte kein Bild: " + done.stderr.decode("utf-8", "replace")[:160])
    return done.stdout, 200, {"Content-Type": "image/jpeg", "Cache-Control": "no-store"}


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
    path.unlink()
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


def _job_worker(filename, commands, probe_point=None):
    job.update(file=filename, state="running", line=0, total=len(commands), error="")
    try:
        if probe_point is not None:
            # One-click: home XY then Z, probe the material under the motif,
            # focus happens automatically before the first powered G1.
            job["state"] = "homing"
            machine.safe_home(owner="job", clearance_mm=config["z_clearance_mm"])
            if stop_job.is_set():
                raise RuntimeError("Abgebrochen")
            job["state"] = "probing"
            machine.command("G0 X%.3f Y%.3f" % probe_point, owner="job", timeout=60)
            machine.probe_workpiece(owner="job")
            job["state"] = "running"
        machine.command("M5 I", owner="job")
        for i, command in enumerate(commands, 1):
            if stop_job.is_set():
                raise RuntimeError("Abgebrochen")
            normalized = normalize(command)
            if normalized == "G28":
                machine.safe_home(owner="job", clearance_mm=config["z_clearance_mm"])
            elif normalized == "G30":
                machine.probe_workpiece(owner="job")
            elif normalized == "M2":
                pass  # the worker always parks once at the end
            elif normalized:
                machine.command(command, owner="job", timeout=150)
            job["line"]=i
        machine.park_safezone(owner="job")
        job["state"]="complete"
    except Exception as exc:
        job.update(state="aborted" if stop_job.is_set() else "error", error=str(exc))
        if not machine.emergency_latched:
            _stop_after_job_error()
    finally:
        with machine.lock:
            machine.owner=None
        job_lock.release()


def start_job(automatic=False):
    local_owner()
    if not machine.homed and not automatic:
        raise RuntimeError("Vor dem Job referenzieren")
    filename = request.form.get("name","")
    if filename != Path(filename).name or not (JOBS / filename).is_file():
        raise ValueError("Unbekannte Auftragsdatei")
    content = (JOBS / filename).read_text(encoding="utf-8")
    preflight(content)
    probe_point = None
    if automatic:
        if machine.probe_xy_offset_mm is None:
            raise ValueError("X/Y-Tasterversatz zuerst unter Fokus & Taster eintragen")
        probe_point = _optional_point(request.form)
        if probe_point is None:
            bounds = _powered_bounds(content)
            if bounds is None:
                raise ValueError("Motivmitte nicht bestimmbar: Abtastpunkt X/Y angeben")
            # The material lies under the motif; its centre is the most
            # likely point with material below the switch.
            probe_point = bounds.center
    if not job_lock.acquire(blocking=False):
        raise RuntimeError("Ein Auftrag läuft bereits")
    stop_job.clear()
    with machine.lock:
        if machine.owner is not None:
            job_lock.release()
            raise RuntimeError("LightBurn hat inzwischen die Steuerung")
        machine.owner="job"
    commands = content.splitlines()
    thread = threading.Thread(target=_job_worker,
                              args=(filename,commands,probe_point), daemon=True,
                              name="marlin-gcode-job")
    thread.start()
    if automatic:
        return jsonify(message="Ein-Klick-Ablauf gestartet: Homing → Abtasten bei X%.1f Y%.1f "
                       "→ Fokus → %s → Park" % (probe_point[0], probe_point[1], filename))
    return jsonify(message="Job gestartet: " + filename)


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
    if not machine.homed:
        raise RuntimeError("Vor dem Rahmen referenzieren")
    mode = request.form.get("mode", "box") or "box"
    if mode not in FRAME_MODES:
        raise ValueError("Rahmenart muss box oder hull sein")
    commands = frame_program(request.form.get("gcode", ""))
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


def monitor_loop():
    last_attempt=0.0
    while running:
        time.sleep(2.0)
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
            except Exception:
                logging.warning("Marlin heartbeat failed", exc_info=True)


def main():
    global running
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    running=True
    threading.Thread(target=monitor_loop, daemon=True,
                     name="marlin-usb-heartbeat").start()
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
