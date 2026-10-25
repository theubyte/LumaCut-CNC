"""Headless Raspberry Pi 400 control server for native Marlin on SKR Mini MZ.

Dedicated process and systemd unit, separate from existing grblHAL app.
LightBurn uses Custom GCode/Marlin + Network TCP 23 via the Pi Wi-Fi.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from .transport import MarlinTransport, MarlinLaserGuard, normalize, serve_tcp

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("LUMACUT_DATA", "/var/lib/lumacut")) / "marlin"
JOBS = DATA / "jobs"
KEY = os.environ.get("LUMACUT_KEY", "")
if len(KEY) < 16:
    raise RuntimeError("LUMACUT_KEY muss mindestens 16 Zeichen lang sein")
USB = os.environ.get("LUMACUT_SKR", "/dev/ttyACM0")
HTTP = int(os.environ.get("LUMACUT_HTTP", "8080"))
TCP = int(os.environ.get("LUMACUT_TCP", "23"))
machine = MarlinTransport(USB)
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
config = {
    "validated": False,        # NEVER assumed from old grblHAL firmware
    "z_clearance_mm": 20.0,
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
job = {"file": "", "state": "idle", "line": 0, "total": 0, "error": ""}
job_lock = threading.Lock()
stop_job = threading.Event()
running = False


def persist():
    temporary = CONFIG.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.replace(temporary, CONFIG)


@app.before_request
def authorize():
    if request.path == "/":
        return None
    if not secrets.compare_digest(request.headers.get("X-LumaCut-Key", ""), KEY):
        return Response("LumaCut Maschinenzugangscode erforderlich", 401)
    return None


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
    result.update(job=dict(job), firmware="marlin", wifi_connected=True,
                  expected_pwm="PA1 / M3 I / S0..255",
                  io={"laser_enable":"FAN1 PC7",
                      "exhaust":"BED PC9 M8",
                      "lights":"HE0 PC8 M7",
                      "aux":"FAN0 PC6 unused"},
                  config=dict(config))
    return jsonify(result)


def local_owner():
    with machine.lock:
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
    if not machine.homing_verified:
        raise RuntimeError("Z-Homingrichtung/Endstop nicht verifiziert")
    # For *this machine* the independent Z-min switch must be shown to
    # retract the tool by POSITIVE Z; only commission after dry run.
    # Homing X/Y is deliberately forbidden before Z is clear.
    local_owner()
    machine.command("M5 I", owner="web")
    machine.command("G28 Z", owner="web", timeout=150)
    machine.command("M400", owner="web", timeout=30)
    machine.command("G91", owner="web")
    machine.command("G0 Z%.2f F360" % config["z_clearance_mm"],
                    owner="web", timeout=30)
    machine.command("G90", owner="web")
    machine.command("G28 X Y", owner="web", timeout=150)
    machine.command("M400", owner="web", timeout=30)
    machine.command("M114", owner="web", timeout=10)
    machine.homed = True


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


@app.post("/api/action")
def action():
    op = request.form.get("op", "")
    if op == "estop":
        stop_job.set()
        machine.emergency_stop()
        return jsonify(message="Marlin M112 ausgelöst – physischen Not-Aus prüfen")
    if op == "connect":
        machine.ensure_ready()
        return jsonify(message="Marlin M115 + LumaCut-Kennung bestätigt")
    if op == "home":
        home_z_first()
        return jsonify(message="Z, Z-Sicherheitsabstand, X/Y und M400 bestätigt")
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
    if op == "start":
        return start_job()
    raise ValueError("Unbekannte Marlin-Aktion: " + op)


@app.get("/api/jobs")
def jobs():
    return jsonify(files=[{"name": p.name, "bytes": p.stat().st_size}
                          for p in sorted(JOBS.iterdir())
                          if p.is_file() and p.suffix.lower() in (".gcode",".gc",".nc")])


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


def preflight(text):
    if not machine.homing_verified:
        raise RuntimeError("Mechanik noch nicht freigegeben")
    safety = MarlinLaserGuard()
    lines = 0
    for number, line in enumerate(text.splitlines(), 1):
        try:
            command = safety.check(line, machine.homing_verified)
            if command: lines+=1
        except Exception as exc:
            raise ValueError("G-Code Zeile %d: %s" % (number, exc))
    if not lines:
        raise ValueError("G-Code ist leer")


def _job_worker(filename, commands):
    job.update(file=filename, state="running", line=0, total=len(commands), error="")
    try:
        machine.command("M5 I", owner="job")
        for i, command in enumerate(commands, 1):
            if stop_job.is_set():
                raise RuntimeError("Abgebrochen: M112 / Hardware prüfen")
            if normalize(command):
                machine.command(command, owner="job", timeout=150)
            job["line"]=i
        machine.command("M5 I", owner="job")
        machine.command("M400", owner="job", timeout=120)
        job["state"]="complete"
    except Exception as exc:
        job.update(state="error", error=str(exc))
        try:
            machine.emergency_stop()
        except Exception:
            pass
    finally:
        with machine.lock:
            machine.owner=None
        job_lock.release()


def start_job():
    local_owner()
    if not machine.homed:
        raise RuntimeError("Vor dem Job referenzieren")
    filename = request.form.get("name","")
    if filename != Path(filename).name or not (JOBS / filename).is_file():
        raise ValueError("Unbekannte Auftragsdatei")
    content = (JOBS / filename).read_text(encoding="utf-8")
    preflight(content)
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
                              args=(filename,commands), daemon=True,
                              name="marlin-gcode-job")
    thread.start()
    return jsonify(message="Job gestartet: " + filename)


def monitor_loop():
    last_attempt=0.0
    while running:
        time.sleep(2.0)
        if machine.owner is not None:
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
        try:
            machine.emergency_stop()
        except Exception:
            pass


if __name__=="__main__":
    main()
