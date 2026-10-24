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
import secrets
import socket
import subprocess
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file, send_from_directory

from .core import Controller, serve_lightburn

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
}
try:
    if CONFIG_PATH.exists():
        saved = json.loads(CONFIG_PATH.read_text())
        if isinstance(saved, dict):
            for name in ("focus", "probe", "parks", "jog_percent"):
                if name in saved:
                    config[name] = saved[name]
except Exception:
    logging.exception("Configuration recovery; previous config retained")


def persist():
    with config_lock:
        DATA.mkdir(parents=True, exist_ok=True)
        temporary = CONFIG_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
        os.replace(temporary, CONFIG_PATH)


@app.before_request
def check_token():
    if request.path == "/" or request.path.startswith("/static/"):
        return None
    if controller.maintenance_file.exists() and request.method in ("POST", "PUT", "DELETE"):
        return Response("LumaCut Pi-Update: Steuerung gesperrt", 423)
    supplied = request.headers.get("X-LumaCut-Key", "")
    if not secrets.compare_digest(supplied, TOKEN):
        return Response("LumaCut Zugangscode erforderlich", 401)
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
    if isinstance(exc, (ValueError, KeyError, RuntimeError)):
        return jsonify({"error": str(exc)}), 400
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return jsonify({"error": str(exc)}), 503
    return jsonify({"error": "Servicefehler; Serverprotokoll prüfen"}), 500


@app.get("/")
def index():
    return send_from_directory(str(ROOT / "static"), "index.html")


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
                                 "zero_at_max": True}},
        diagnostics=stat["diagnostics"],
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
        # M7/M8/M9 require controller ownership. No commands injected into
        # an active LightBurn G-code stream. grblHAL override byte support
        # is hardware-version dependent; use M commands only while idle.
        require_free()
        if op.startswith("light"):
            value = "M7" if op in ("lightOn", "lightToggle") else "M9"
        else:
            value = "M8" if op in ("exhaustOn", "exhaustToggle") else "M9"
        return run_commands([value])
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
        return "Halt angefordert"
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
    if op in ("motorHold", "motorRelease", "softon", "flipx", "flipy", "flipz",
              "origin", "zlift", "frame", "pause", "next"):
        raise RuntimeError("Diese Aktion wird auf dem Pi erst nach kompatiblem SKR-Protokoll freigeschaltet")
    raise ValueError("Unbekannter Befehl " + op)


@app.post("/api/ui/action")
def ui_action():
    return jsonify(message=do_action(request.form.get("op", "")))


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
    job_thread = threading.Thread(target=_run_job, name="gcode-job", daemon=True)
    job_thread.start()
    return "Job gestartet: " + selected_job


def _run_job():
    with controller.lock:
        controller._acquire_local("job")
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
    return jsonify(hotspot_ssid="", hotspot_password="", hotspot_ip="",
                   router_ssid="", connected=True, router_ip=host + ".local",
                   lightburn_tcp_enabled=True, lightburn_port=TCP_PORT)


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
    cmd = os.getenv("LUMACUT_CAMERA_CMD", "/usr/bin/rpicam-still")
    if not Path(cmd).is_file():
        return jsonify(error="Kamera nicht installiert"), 503
    result = subprocess.run([cmd, "-n", "-t", "100",
                             "--width", "1280", "--height", "720", "-o", "-"],
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
