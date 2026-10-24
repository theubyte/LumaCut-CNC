"""LumaCut Control Studio for Raspberry Pi 400 (headless).

Raspberry Pi owns HTTP and GRBL TCP; SKR owns real-time motion over USB.
Do not expose ports 8080 or 23 outside a trusted LAN.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import secrets
import socket
import subprocess
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file, send_from_directory, session

from .core import Controller, serve_lightburn
from .pins import DEFAULT_ROLES, accessories_for_roles, manifest, override_for_role, validate_roles
from .service_auth import ServiceAuth

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv("LUMACUT_DATA", "/var/lib/lumacut"))
JOBS = DATA / "jobs"
JOBS.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = DATA / "config.json"
TOKEN = os.getenv("LUMACUT_KEY", "")
if len(TOKEN) < 16:
    raise RuntimeError("LUMACUT_KEY must be >=16 characters; configure the service environment")
SKR_PORT = os.getenv("LUMACUT_SKR", "/dev/serial/by-id/lumacut-skr")
HTTP_PORT = int(os.getenv("LUMACUT_HTTP", "8080"))
TCP_PORT = int(os.getenv("LUMACUT_TCP", "23"))
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024
service_auth = ServiceAuth(DATA)
app.secret_key = service_auth.signing_secret
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict")
controller = Controller(SKR_PORT)
controller.maintenance_file = DATA / "maintenance.lock"
started = False
selected_job = ""
job_thread = None
job_cancel = threading.Event()
job_pause = threading.Event()
job_progress = {"name": "", "line": 0, "total": 0, "state": "idle"}
config_lock = threading.RLock()
config = {
    "focus": {"lift": 20.0, "gap": 7.0, "tip": 0.0, "auto": True},
    "probe": {"x": 10, "y": 10, "width": 100, "height": 100,
              "offset_x": 0, "offset_y": 0, "pitch": 10},
    "parks": [{"name": "Park 1", "stored": False, "x": 0, "y": 0},
              {"name": "Park 2", "stored": False, "x": 0, "y": 0},
              {"name": "Park 3", "stored": False, "x": 0, "y": 0}],
    "jog_percent": 100,
    "lightburn_tcp_enabled": True,
    "pin_roles": dict(DEFAULT_ROLES),
}
try:
    if CONFIG_PATH.exists():
        saved = json.loads(CONFIG_PATH.read_text())
        if isinstance(saved, dict):
            for name in ("focus", "probe", "parks", "jog_percent", "lightburn_tcp_enabled", "pin_roles"):
                if name in saved:
                    config[name] = saved[name]
except Exception:
    logging.exception("Configuration recovery; previous config retained")
config["pin_roles"] = __import__("lumacut.pins", fromlist=["effective_roles"]).effective_roles(config["pin_roles"])
controller.lightburn_enabled = bool(config["lightburn_tcp_enabled"])


def persist():
    with config_lock:
        DATA.mkdir(parents=True, exist_ok=True)
        temporary = CONFIG_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
        os.replace(temporary, CONFIG_PATH)


@app.before_request
def check_token():
    if request.path in ("/", "/service") or request.path.startswith("/static/"):
        return None
    supplied = request.headers.get("X-LumaCut-Key", "")
    if not secrets.compare_digest(supplied, TOKEN):
        return Response("LumaCut Zugangscode erforderlich", 401)
    if controller.maintenance_file.exists() and request.method in ("POST", "PUT", "DELETE"):
        return Response("LumaCut Pi-Update: Steuerung gesperrt", 423)
    return None


@app.after_request
def security_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.errorhandler(Exception)
def handle_error(exc):
    from werkzeug.exceptions import HTTPException
    if isinstance(exc, HTTPException):
        return exc
    logging.exception("Control Studio request failed")
    if isinstance(exc, PermissionError):
        return jsonify({"error": str(exc)}), 403
    if isinstance(exc, (ValueError, KeyError, RuntimeError)):
        return jsonify({"error": str(exc)}), 400
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return jsonify({"error": str(exc)}), 503
    return jsonify({"error": "Servicefehler; Serverprotokoll prüfen"}), 500


@app.get("/")
def index():
    return send_from_directory(str(ROOT / "static"), "index.html")


@app.get("/service")
def service_page():
    return send_from_directory(str(ROOT / "static"), "service.html")


def require_service():
    if session.get("service_until", 0) <= time.time():
        raise PermissionError("Service-Anmeldung erforderlich")


@app.get("/api/service/auth")
def service_auth_status():
    return jsonify(active=session.get("service_until", 0) > time.time())


@app.post("/api/service/login")
def service_login():
    client = request.remote_addr or "unknown"
    if not service_auth.authenticate(request.form.get("password", ""), client):
        raise PermissionError("Servicepasswort falsch")
    session.clear()
    session["service_until"] = time.time() + 600
    return jsonify(message="Service freigeschaltet (10 Minuten)", active=True)


@app.post("/api/service/logout")
def service_logout():
    session.clear()
    return jsonify(message="Service gesperrt", active=False)


@app.post("/api/service/password")
def service_password():
    require_service()
    service_auth.change_password(request.form.get("old", ""),
                                 request.form.get("new", ""),
                                 request.remote_addr or "unknown")
    app.secret_key = service_auth.signing_secret
    session.clear()
    return jsonify(message="Servicepasswort geändert. Erneut anmelden.")


@app.get("/api/service/pins")
def service_pins():
    require_service()
    return jsonify(manifest(config["pin_roles"]))


@app.post("/api/service/pins")
def service_save_pins():
    require_service()
    require_free()
    proposed = validate_roles({"lights": request.form.get("lights"),
                               "exhaust": request.form.get("exhaust")})
    with config_lock:
        config["pin_roles"] = proposed
        persist()
    return jsonify(message="Logische M7/M8-Zubehörbelegung gespeichert",
                   roles=proposed)


@app.get("/api/service/diagnostics")
def service_diagnostics():
    require_service()
    info = controller.status()
    return jsonify(connected=info["connected"], state=info["state"],
                   homed=info["homed"], owner=info["owner"],
                   serial_faults=info["diagnostics"]["serial_faults"],
                   suppressed_status=info["diagnostics"]["suppressed_status"],
                   settings=info["settings"], recent=info["recent"],
                   limitations=manifest(config["pin_roles"])["limitations"])


@app.post("/api/service/command")
def service_command():
    require_service()
    require_free()
    command = request.form.get("command", "").strip()
    # Read-only GRBL queries and bounded numeric settings only.
    if command not in ("$", "$I", "$G", "$#"):
        match = re.fullmatch(r"\$([0-9]{1,3})=([-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))", command)
        if not match:
            raise ValueError("Nur GRBL-Abfragen oder numerische $ID=Wert Einstellungen")
        ident, value = int(match.group(1)), float(match.group(2))
        if not __import__("math").isfinite(value):
            raise ValueError("Wert nicht endlich")
        if ident in (20, 21, 22) and value < 1:
            raise ValueError("Softlimits, Hardlimits und Homing dürfen nicht deaktiviert werden")
        if ident in (130, 131, 132) and not 0 < value <= 3000:
            raise ValueError("Ungültiger Achsfahrweg")
    response = run_commands([command], timeout=20)
    return jsonify(message=response, command=command)



@app.get("/api/status")
def status():
    stat = controller.status()
    dims = [stat["settings"].get(i, 0) for i in (130, 131, 132)]
    p = stat["position"]
    return jsonify(
        connected=stat["connected"],
        state=stat["state"],
        owner=stat["owner"],
        position="X %.2f Y %.2f Z %.2f" % tuple(p) if p else "X — Y — Z —",
        job=selected_job,
        progress=job_progress,
        machine={"homed": stat["homed"],
                 "work_area": {"x_mm": dims[0], "y_mm": dims[1], "z_mm": dims[2]},
                 "coordinates": {"valid": bool(p),
                                 "x_mm": p[0] if p else 0,
                                 "y_mm": p[1] if p else 0,
                                 "z_mm": p[2] if p else 0,
                                 "zero_at_max": bool(config.get("zero_at_max", True))}},
        diagnostics=stat["diagnostics"],
        accessories=accessories_for_roles(stat["accessories"], config["pin_roles"]),
        last_error=stat["last_error"],
        recent=stat["recent"],
    )


@app.get("/api/ui/params")
def params():
    return jsonify(settings=controller.status()["settings"])


@app.get("/api/ui/config")
def get_config():
    with config_lock:
        output = dict(config)
    settings = controller.status()["settings"]
    output["travel"] = {name: settings.get(n, 0)
                        for name, n in (("x", 130), ("y", 131), ("z", 132))}
    output["speed_pct"] = config["jog_percent"]
    output["step"] = 1
    return jsonify(output)


def numeric(key, minimum=None, maximum=None):
    value = float(request.form[key])
    if not __import__("math").isfinite(value):
        raise ValueError(key + " not finite")
    if minimum is not None and value < minimum:
        raise ValueError(key + " too small")
    if maximum is not None and value > maximum:
        raise ValueError(key + " too large")
    return value


def require_free():
    state = controller.status()
    if state["owner"] != "Frei":
        raise RuntimeError("Steuerung belegt: " + state["owner"])
    if state["state"] not in ("Idle", "Alarm"):
        raise RuntimeError("SKR nicht im Leerlauf: " + state["state"])
    if not state["connected"]:
        raise ConnectionError("SKR nicht verbunden")


def run_commands(lines, timeout=15):
    responses = controller.command_batch(lines, timeout=timeout)
    for index, answer in enumerate(responses):
        if answer != "ok":
            raise RuntimeError("SKR meldet %s für %s" % (answer, lines[index]))
    return "SKR bestätigt " + str(len(responses)) + " Befehl(e)"


@app.post("/api/ui/setting")
def set_param():
    require_service()
    require_free()
    identifier = int(request.form["id"])
    if identifier not in controller.status()["settings"]:
        raise ValueError("Parameter wurde vom SKR nicht gemeldet")
    value = numeric("value")
    if identifier in (130, 131, 132) and not 0 < value <= 3000:
        raise ValueError("Ungültiger Verfahrweg")
    if identifier in (20, 21, 22) and value < 1:
        raise ValueError("Homing / Hardware-Limits aktiv lassen")
    result = run_commands(["$%d=%s" % (identifier, request.form["value"]), "$$"])
    return jsonify(message=result, value=controller.status()["settings"].get(identifier))


@app.post("/api/ui/config")
def set_config():
    section = request.form["section"]
    if section == "travel":
        require_service()
        require_free()
        vals = [numeric(i, 0.01, 3000) for i in ("x", "y", "z")]
        result = run_commands(["$%d=%0.4f" % (id, val)
                               for id, val in zip((130, 131, 132), vals)] + ["$$"])
        return jsonify(message=result)
    if section == "focus":
        with config_lock:
            config["focus"] = {"lift": numeric("lift", 0.1, 200),
                               "gap": numeric("gap", 0.1, 200),
                               "tip": numeric("tip", -100, 100),
                               "auto": config["focus"].get("auto", True)}
    elif section == "probe":
        with config_lock:
            config["probe"] = {
                "x": numeric("x"), "y": numeric("y"),
                "width": numeric("width", 0.01),
                "height": numeric("height", 0.01),
                "offset_x": numeric("offset_x", -1000, 1000),
                "offset_y": numeric("offset_y", -1000, 1000),
                "pitch": numeric("pitch", 0.01, 500),
            }
        if request.form.get("plan") == "1":
            return jsonify(message=build_probe_plan())
    elif section == "macro":
        i = int(request.form["slot"])
        if i < 0 or i >= 3:
            raise ValueError("Parkplatz 0..2")
        name = request.form["name"][:24].strip()
        if not name:
            raise ValueError("Name erforderlich")
        with config_lock:
            config["parks"][i]["name"] = name
    else:
        raise ValueError("Unbekannte Konfiguration")
    persist()
    return jsonify(message="Konfiguration gespeichert")


def build_probe_plan():
    p = dict(config["probe"])
    vals = controller.status()["settings"]
    if vals.get(130, 0) <= 0 or vals.get(131, 0) <= 0:
        raise RuntimeError("SKR-Fahrwege $130/$131 zuerst einlesen")
    import math
    # Workpiece probe-point intersection with laser-carriage travel.
    x0 = max(p["x"], p["offset_x"] + 0.5)
    x1 = min(p["x"] + p["width"], vals[130] - 0.5 + p["offset_x"])
    y0 = max(p["y"], p["offset_y"] + 0.5)
    y1 = min(p["y"] + p["height"], vals[131] - 0.5 + p["offset_y"])
    if x1 <= x0 or y1 <= y0:
        raise ValueError("Taster erreicht das Rechteck nicht")
    nx = math.ceil((x1-x0) / p["pitch"]) + 1
    ny = math.ceil((y1-y0) / p["pitch"]) + 1
    if nx * ny > 100000:
        raise ValueError("Raster zu fein, mehr als 100000 Punkte")
    path = DATA / "probe_plan.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["probe_x_mm", "probe_y_mm", "laser_x_mm", "laser_y_mm"])
        for row in range(ny):
            y = min(y1, y0 + row * p["pitch"])
            xs = [min(x1, x0 + col * p["pitch"]) for col in range(nx)]
            if row % 2:
                xs.reverse()
            for x in xs:
                writer.writerow([round(x, 3), round(y, 3),
                                 round(x - p["offset_x"], 3),
                                 round(y - p["offset_y"], 3)])
    persist()
    return "%s XY-Rasterpunkte berechnet (noch keine gemessene Z-Höhenkarte)" % (nx * ny)


@app.get("/api/probe-plan")
def probe_download():
    if not (DATA / "probe_plan.csv").is_file():
        return jsonify(error="Noch kein Raster"), 404
    return send_file(DATA / "probe_plan.csv", as_attachment=True)


def do_action(op):
    if op in ("enablehome", "softon", "motorHold", "motorRelease",
              "flipx", "flipy", "flipz", "origin"):
        require_service()
    if op == "host":
        controller.lightburn_enabled = not controller.lightburn_enabled
        config["lightburn_tcp_enabled"] = controller.lightburn_enabled
        if not controller.lightburn_enabled:
            controller.disconnect_host()
        persist()
        return "LightBurn TCP: " + ("EIN" if controller.lightburn_enabled else "AUS")
    if op == "readcfg":
        require_free()
        return run_commands(["$$"], timeout=15)
    if op in ("home", "enablehome"):
        require_free()
        return run_commands(["$H" if op == "home" else "$22=1"], timeout=150)
    if op == "jogsound":
        config["jog_percent"] = {100: 50, 50: 25, 25: 100}.get(config["jog_percent"], 100)
        persist()
        return "Jog: %s%% SKR-Maximalgeschwindigkeit" % config["jog_percent"]
    if op in ("x+", "x-", "y+", "y-", "z+", "z-"):
        require_free()
        if not controller.homed:
            raise RuntimeError("Zuerst XYZ referenzieren")
        axis = op[0].upper()
        distance = float(request.form.get("step", "1"))
        if distance not in (0.1, 1, 10):
            raise ValueError("Jog nur 0.1/1/10mm")
        if op[1] == "-":
            distance *= -1
        maximum = controller.settings.get({"X": 110, "Y": 111, "Z": 112}[axis])
        if not maximum:
            raise RuntimeError("GRBL Achstempo nicht verfügbar")
        percent = config["jog_percent"]
        return run_commands(["$J=G91 G21 %s%0.3f F%0.1f" %
                             (axis, distance, maximum * percent / 100)],
                            timeout=30)
    if op in ("lightToggle", "exhaustToggle", "lightOn", "lightOff",
              "exhaustOn", "exhaustOff"):
        # Independent grblHAL real-time coolant overrides: 0xA1 M7/LED,
        # 0xA0 M8/exhaust. A plain M9 would turn BOTH off, so avoid it.
        state = controller.status()
        if not state["connected"]:
            raise ConnectionError("SKR USB nicht verbunden")
        import time as _time
        if _time.monotonic() - controller.last_accessory_toggle < 0.65:
            raise RuntimeError("Schaltung wird noch bestätigt")
        lights = op.startswith("light")
        role = "lights" if lights else "exhaust"
        current = accessories_for_roles(state["accessories"], config["pin_roles"])[role]
        desired = (not current if op.endswith("Toggle") else op.endswith("On"))
        if current == desired:
            return "LED/Abluft bereits im gewählten Zustand"
        controller.realtime(override_for_role(role, config["pin_roles"]))
        controller.last_accessory_toggle = _time.monotonic()
        return "LED" if lights else "Abluft" + " umgeschaltet"
    if op == "toggle":
        controller.realtime(b"~" if job_pause.is_set() else b"!")
        if job_pause.is_set():
            job_pause.clear()
            return "Fortgesetzt"
        job_pause.set()
        return "Angehalten"
    if op == "abort":
        job_cancel.set()
        controller.realtime(b"!")
        controller.realtime(b"\x18")  # hard GRBL soft reset, kills queued motion
        controller.disconnect_host()
        controller.homed = False
        return "SKR G-Code-Puffer abgebrochen. Vor dem nächsten Job neu homen."
    if op == "capture":
        idx = int(request.form.get("slot", "0"))
        if not 0 <= idx <= 2:
            raise ValueError("Parkplatz")
        position = controller.status()["position"]
        if not position:
            raise RuntimeError("Keine Position")
        with config_lock:
            config["parks"][idx].update(x=position[0], y=position[1], stored=True)
        persist()
        return "Parkposition gespeichert"
    if op in ("park", "p0", "p1", "p2"):
        idx = int(op[-1]) if op != "park" else int(request.form.get("slot", "0"))
        if not 0 <= idx <= 2 or not config["parks"][idx]["stored"]:
            raise RuntimeError("Parkposition fehlt")
        require_free()
        park = config["parks"][idx]
        return run_commands(["M5", "G90 G21",
                             "G53 G0 X%.3f Y%.3f" % (park["x"], park["y"])])
    if op == "start":
        return start_job()
    if op == "updatecheck":
        return "Updates werden über die Pi-400-Verwaltung geprüft."
    if op in ("updateinstall", "skrinstall"):
        return "Firmwareupdates nur über abgesicherten Pi-Updatepfad."
    if op == "softon":
        require_free()
        return run_commands(["$20=1", "$21=1", "$"])
    if op == "motorHold":
        require_free()
        return run_commands(["$1=255", "$"])
    if op == "motorRelease":
        require_free()
        if controller.state == "Alarm":
            raise RuntimeError("Achsen bereits Alarm; erst Referenzfahrt prüfen")
        result = run_commands(["$SLP"])
        controller.homed = False
        return "Achsen im Schlafmodus; Neustart und Homing zum Aufwecken. " + result
    if op in ("flipx", "flipy", "flipz"):
        require_free()
        setting = controller.settings.get(3)
        if setting is None:
            raise RuntimeError("SKR-Richtung $3 erst mit $ einlesen")
        bit = {"flipx": 1, "flipy": 2, "flipz": 4}[op]
        controller.homed = False
        return run_commands(["$3=%d" % (int(setting) ^ bit), "$"])
    if op == "origin":
        with config_lock:
            config["zero_at_max"] = not config.get("zero_at_max", True)
        persist()
        return "Koordinatenansicht gewechselt"
    if op == "zlift":
        require_free()
        stat = controller.status()
        if not stat["homed"] or not stat["position"]:
            raise RuntimeError("Erst XYZ referenzieren")
        lift = float(config["focus"]["lift"])
        zmax = stat["settings"].get(132, 0)
        if not 0 < lift < zmax:
            raise RuntimeError("Z-Sicherheitsabstand außerhalb $132")
        target = -lift if config.get("zero_at_max", True) else lift
        if abs(target - stat["position"][2]) < 0.005:
            return "Z bereits auf Sicherheitsabstand"
        if 112 not in stat["settings"]:
            raise RuntimeError("Z Maximaltempo $112 fehlt")
        return run_commands(["M5", "G53 G0 Z%.3f" % target], timeout=30)
    if op == "pause":
        return do_action("toggle")
    if op == "frame":
        require_free()
        if not controller.homed or not selected_job:
            raise RuntimeError("Erst homen und G-Code auswählen")
        bounds = job_bounds(JOBS / selected_job)
        if bounds is None:
            raise RuntimeError("Kontur aus diesem G-Code nicht sicher bestimmbar")
        x0, y0, x1, y1 = bounds
        return run_commands(["M5", "G21 G90",
            "G0 X%.3f Y%.3f" % (x0,y0),
            "G0 X%.3f Y%.3f" % (x1,y0),
            "G0 X%.3f Y%.3f" % (x1,y1),
            "G0 X%.3f Y%.3f" % (x0,y1),
            "G0 X%.3f Y%.3f" % (x0,y0)],timeout=35)
    if op == "next":
        return "GCode-Jobs über die Dateiliste auswählen"

    raise ValueError("Unbekannter Befehl " + op)


@app.post("/api/ui/action")
def ui_action():
    return jsonify(message=do_action(request.form.get("op", "")))


def job_bounds(path: Path):
    # Parse GRBL absolute XY contours; unsupported modal transformations
    # do not trigger a potentially incorrect unpowered frame.
    import re
    xs,ys = [],[]
    absolute = True
    metric = True
    x = y = None
    for line in path.read_text(encoding="utf-8",errors="replace").splitlines():
        raw = line.split(";",1)[0]
        raw = re.sub(r"\\([^()]*\\)","",raw).upper()
        if not raw.strip():
            continue
        words = re.findall(r"([A-Z])\\s*([-+]?\\d*\\.?\\d+)",raw)
        for letter,value in words:
            if letter == "G":
                code = int(float(value))
                if code == 91: absolute = False
                if code == 90: absolute = True
                if code == 20: metric = False
                if code == 21: metric = True
                if code in (2,3,51,68,92): return None
            if letter == "X": x=float(value)
            if letter == "Y": y=float(value)
        if not absolute or not metric:
            return None
        if x is not None and y is not None:
            xs.append(x);ys.append(y)
        if len(xs)>100000: return None
    if not xs or not ys: return None
    result=min(xs),min(ys),max(xs),max(ys)
    if result[0]==result[2] or result[1]==result[3]: return None
    return result


@app.get("/api/jobs")
def jobs_list():
    return jsonify(files=[{"name": p.name, "bytes": p.stat().st_size}
                          for p in sorted(JOBS.iterdir()) if p.is_file()])


@app.post("/api/select")
def select():
    global selected_job
    name = Path(request.form["name"]).name
    if name != request.form["name"] or not (JOBS / name).is_file():
        raise ValueError("Ungültiger Dateiname")
    selected_job = name
    return jsonify(message="Job gewählt: " + name)


@app.post("/api/upload")
def upload():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        raise ValueError("Datei fehlt")
    name = Path(upload.filename).name
    if name != upload.filename or Path(name).suffix.lower() not in (
            ".gc", ".gcode", ".nc", ".tap", ".txt"):
        raise ValueError("Nur GRBL-G-Code-Dateien erlaubt")
    target = JOBS / name
    temporary = JOBS / (name + ".partial")
    upload.save(temporary)
    os.replace(temporary, target)
    return jsonify(message="Hochgeladen: " + name)


def start_job():
    global job_thread
    require_free()
    if not selected_job or not (JOBS / selected_job).is_file():
        raise RuntimeError("Zuerst Job auswählen")
    if not controller.homed:
        raise RuntimeError("Maschine zuerst referenzieren")
    if job_thread and job_thread.is_alive():
        raise RuntimeError("Job läuft")
    job_cancel.clear()
    job_pause.clear()
    with controller.lock:
        controller._acquire_local("job")
    job_thread = threading.Thread(target=_run_job, name="gcode-job", daemon=True)
    try:
        job_thread.start()
    except Exception:
        with controller.lock:
            if controller.owner == "job":
                controller.owner = None
        raise
    return "Job gestartet: " + selected_job


def _run_job():
    job_progress.update(name=selected_job, line=0, state="running")
    try:
        path = JOBS / selected_job
        lines = path.read_text(encoding="utf-8").splitlines()
        job_progress["total"] = len(lines)
        for i, raw in enumerate(lines):
            if job_cancel.is_set():
                break
            while job_pause.is_set() and not job_cancel.is_set():
                time.sleep(0.1)
            if job_cancel.is_set():
                break
            cmd = raw.strip()
            if not cmd or cmd.startswith(";") or cmd.startswith("("):
                continue
            ack = controller.command(cmd, owner="job", timeout=30)
            if ack != "ok":
                raise RuntimeError("Zeile %s: %s" % (i + 1, ack))
            job_progress["line"] = i + 1
        if job_cancel.is_set():
            job_progress["state"] = "stopped"
        else:
            # Wait for GRBL planner to become idle before releasing ownership.
            deadline = time.monotonic() + 120
            while controller.state not in ("Idle", "Alarm") and time.monotonic() < deadline:
                time.sleep(0.1)
            job_progress["state"] = "complete" if controller.state == "Idle" else "check"
    except Exception as exc:
        logging.exception("G-code job aborted")
        job_progress["state"] = "error: " + str(exc)[:100]
        try:
            controller.realtime(b"!")
        except Exception:
            pass
    finally:
        with controller.lock:
            if controller.owner == "job":
                controller.owner = None


@app.get("/api/ui/network")
def network():
    host = socket.gethostname()
    try:
        ip = subprocess.run(["hostname", "-I"], capture_output=True,
                            text=True, timeout=2).stdout.split()[0]
    except (IndexError, OSError, subprocess.TimeoutExpired):
        ip = host + ".local"
    ssid = ""
    try:
        result = subprocess.run(["nmcli", "-t", "-f", "IN-USE,SSID",
                                 "device", "wifi", "list"],
                                capture_output=True, text=True, timeout=4)
        for line in result.stdout.splitlines():
            if line.startswith("*:"):
                ssid = line.split(":", 1)[1].replace("\\:", ":")
                break
    except (OSError, subprocess.TimeoutExpired):
        pass
    return jsonify(hotspot_ssid=host + ".local", hotspot_password="",
                   hotspot_ip=ip, router_ssid=ssid, connected=bool(ssid),
                   router_ip=ip,
                   lightburn_tcp_enabled=controller.lightburn_enabled,
                   lightburn_port=TCP_PORT,
                   cabinet_leds_on=accessories_for_roles(controller.status()["accessories"], config["pin_roles"])["lights"],
                   exhaust_on=accessories_for_roles(controller.status()["accessories"], config["pin_roles"])["exhaust"])


@app.get("/api/ui/network/scan")
def wifi_scan():
    result = subprocess.run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY",
                             "dev", "wifi", "list", "--rescan", "yes"],
                            capture_output=True, text=True, timeout=20)
    entries = []
    for line in result.stdout.splitlines():
        pieces = line.split(":")
        if pieces and pieces[0]:
            entries.append({"ssid": pieces[0], "rssi": pieces[1] if len(pieces) > 1 else "",
                            "secured": bool(pieces[2]) if len(pieces) > 2 else False})
    return jsonify(networks=entries[:30], scanning=False)


@app.post("/api/ui/network/connect")
def wifi_connect():
    require_service()
    require_free()
    ssid = request.form["ssid"].strip()
    password = request.form.get("password", "")
    if not 0 < len(ssid) <= 32 or (password and not 8 <= len(password) <= 63):
        raise ValueError("SSID oder Passwort ungültig")
    # NetworkManager handles Wi-Fi persistence; never log password.
    args = ["nmcli", "--wait", "20", "dev", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    out = subprocess.run(args, capture_output=True, text=True, timeout=25)
    if out.returncode != 0:
        raise RuntimeError("Netzwerkverbindung fehlgeschlagen")
    return jsonify(accepted=True)


@app.get("/api/lightburn/profile")
def lbprofile():
    settings = controller.status()["settings"]
    path = ROOT.parent / "lightburn" / "LumaCut-CNC-USB.lbdev"
    template = json.loads(path.read_text(encoding="utf-8"))
    dev = template["DeviceList"][0]
    dev["Width"] = settings.get(130, dev["Width"])
    dev["Height"] = settings.get(131, dev["Height"])
    dev["Settings"]["SValueMax"] = settings.get(30, 1000)
    response = Response(json.dumps(template, indent=2), mimetype="application/json")
    response.headers["Content-Disposition"] = 'attachment; filename="LumaCut-CNC-USB.lbdev"'
    return response


@app.get("/api/camera/snapshot")
def camera():
    # Raspberry Pi 400 has NO CSI connector: use a UVC USB webcam.
    device = os.getenv("LUMACUT_CAMERA_DEVICE", "/dev/video0")
    if not Path(device).is_char_device():
        return jsonify(error="USB-Kamera an /dev/video0 nicht erkannt"), 503
    result = subprocess.run(["/usr/bin/ffmpeg", "-nostdin", "-hide_banner",
                             "-loglevel", "error", "-f", "v4l2",
                             "-i", device, "-frames:v", "1",
                             "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                            capture_output=True, timeout=12)
    if result.returncode or not result.stdout.startswith(b"\xff\xd8"):
        return jsonify(error="Kamera liefert kein JPEG"), 503
    return Response(result.stdout, mimetype="image/jpeg")


@app.get("/api/update/status")
def update_status():
    # The installer/updater is a distinct privileged systemd task, not
    # callable by arbitrary web requests.
    return jsonify(pi_auto_update=True,
                   maintenance=controller.maintenance_file.exists(),
                   skr_auto_flash=False,
                   skr_requires="verified SWD/ST-Link or supported bootloader flashing",
                   warning="Kein Firmwareflash während Laserbetrieb")


def main():
    global started
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    controller.start()
    started = True
    bridge = threading.Thread(target=serve_lightburn,
                              args=(controller, "0.0.0.0", TCP_PORT, lambda: started),
                              name="grbl-tcp", daemon=True)
    bridge.start()
    try:
        app.run(host="0.0.0.0", port=HTTP_PORT, threaded=True, use_reloader=False)
    finally:
        started = False
        controller.stop()


if __name__ == "__main__":
    main()
