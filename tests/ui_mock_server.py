"""Mock-Server für Screenshots der Pi-Weboberfläche (kein SKR nötig).

Aufruf (aus dem Repo-Root):
  LUMACUT_DATA=$(mktemp -d) PYTHONPATH=pi400 python tests/ui_mock_server.py <szenario> <port>
Nur für Screenshots/Entwicklung, NIE auf dem Pi starten (überschreibt Maschinenzustand).
Szenarien: idle | running | offline
"""
import sys, time, threading
from marlin import web

scenario = sys.argv[1] if len(sys.argv) > 1 else "idle"
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8099
m = web.machine
web.config["validated"] = True
m.homing_verified = True
JOB = """G21\nG90\nM3 I\nG0 X80 Y90\nG1 X260 Y90 S180 F1200\nG1 X260 Y240 S180\nG1 X80 Y240 S180\nG1 X80 Y90 S180\nM5 I\n"""
(web.JOBS / "schild_eiche.gcode").write_text(JOB)
(web.JOBS / "untersetzer_rund.gcode").write_text(JOB.replace("260", "200"))

class FakeSerial:
    def close(self): pass
    def write(self, *_): pass

def fake_command(cmd, owner=None, timeout=20, use_guard=True):
    m.lines.append("> " + cmd); m.lines.append("ok")
    return ["ok"]

if scenario != "offline":
    m.serial = FakeSerial()
    m.identity = "FIRMWARE_NAME:Marlin 2.1.2.4 LumaCut-SKR-MiniMZ (LUMACUT_KEY v3) MACHINE_TYPE:LumaCut CNC"
    m.state = "Idle"; m.homed = True; m.z_homed = True
    m.position = [142.5, 118.25, 20.0]
    m.surface_z = 3.0
    m.command = fake_command
    m.ensure_ready = lambda: None
    for l in ("echo:LumaCut gateway ready", "ok", "X:142.50 Y:118.25 Z:20.00 E:0.00 Count X:11400", "ok"):
        m.lines.append(l)
if scenario == "running":
    m.owner = "job"; m.lights = True; m.exhaust = True
    m.laser_enabled = True; m.fan_power = True
    web.job.update(file="schild_eiche.gcode", state="running", line=1873, total=4410, error="")
    web.job_queue["items"] = [
        {"id": 1, "file": "schild_eiche.gcode", "origin": "absolute", "anchor": "tl", "dx": 0, "dy": 0,
         "target": None, "bounds": None, "sha": "x", "state": "running", "error": ""},
        {"id": 2, "file": "untersetzer_rund.gcode", "origin": "absolute", "anchor": "tl", "dx": 0, "dy": 0,
         "target": None, "bounds": None, "sha": "x", "state": "queued", "error": ""}]
    web.job_queue["state"] = "running"; web.job_queue["current"] = 1
    # Hold machine.lock so /api/status reports busy/stale_ms like during a move.
    web.machine_snapshot()
    def hold():
        while True:
            with m.lock:
                time.sleep(30)
    threading.Thread(target=hold, daemon=True).start()
@web.app.get("/shot")
def shot():
    # Nur Mock: index.html mit automatischem Klick auf "Motiv analysieren".
    from flask import request as rq
    html = (web.ROOT / "index.html").read_text(encoding="utf-8")
    tab = rq.args.get("tab", "")
    inject = ("<script>setTimeout(()=>{document.getElementById('previewGeometry').click();"
              + ("document.getElementById('tab-%s').click();" % tab if tab else "") + "},600)</script>")
    return html.replace("</body>", inject + "</body>")
web.app.run(host="127.0.0.1", port=port, threaded=True)
