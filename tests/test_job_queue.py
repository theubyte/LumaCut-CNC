"""Multi-job queue on the Pi (#17): add/run/skip/remove/pause and status."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class JobQueueWebTests(unittest.TestCase):
    def _run(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["LUMACUT_DATA"] = tmp
            env["PYTHONPATH"] = str(ROOT / "pi400")
            result = subprocess.run([sys.executable, "-c", PRELUDE + source], env=env,
                                    cwd=ROOT, text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_add_status_and_frozen_placement(self):
        self._run(r"""
s = c.get("/api/status").get_json()
assert s["queue"] == {"items": [], "state": "idle", "current": None, "max": 50}, s["queue"]
r = post(op="queue_add", name="A.gcode"); assert r.status_code == 200, r.data
r = post(op="queue_add", name="B.gcode", origin="current", anchor="tr")
assert r.status_code == 200, r.data
items = r.get_json()["queue"]["items"]
assert [i["file"] for i in items] == ["A.gcode", "B.gcode"]
assert items[0]["origin"] == "absolute" and (items[0]["dx"], items[0]["dy"]) == (0, 0)
assert (items[1]["dx"], items[1]["dy"]) == (100.0, 50.0), items[1]
assert all(i["state"] == "queued" and "sha" not in i for i in items)
# Moving the head later does not move the queued item (frozen at add).
m.position = [60.0, 60.0, 20.0]
r = post(op="queue_add", name="Nope.gcode"); assert r.status_code == 400
r = post(op="queue_add", name="A.gcode", origin="current", anchor="bl")
assert r.status_code == 400 and "außerhalb" in r.get_json()["error"], r.data
r = post(op="queue_add", name="A.gcode", placement="1")
assert r.status_code == 400 and "neu platzieren" in r.get_json()["error"], r.data
r = post(op="place", name="A.gcode", origin="current", anchor="tr"); assert r.status_code == 200
r = post(op="queue_add", name="A.gcode", placement="1"); assert r.status_code == 200, r.data
assert r.get_json()["queue"]["items"][-1]["dx"] == -40.0
# Queued files cannot be deleted.
r = c.post("/api/jobs/A.gcode/delete")
assert r.status_code == 400 and "Warteschlange" in r.get_json()["error"], r.data
# Every item runs automatically (probing): without the probe offset nothing runs.
m.probe_xy_offset_mm = None
r = post(op="queue_run")
assert r.status_code == 400 and "Tasterversatz" in r.get_json()["error"], r.data
assert "#1" in r.get_json()["error"]
m.probe_xy_offset_mm = (0.0, 0.0)
# Not homed is fine: the automatic run homes itself when needed.
m.homed = False
r = post(op="queue_run"); assert r.status_code == 200, r.data
wait()
assert all(a is not None and a["grids"] for a in autos), autos
q = c.get("/api/status").get_json()["queue"]
assert q["state"] == "complete" and q["current"] is None, q
assert [i["state"] for i in q["items"]] == ["done", "done", "done"], q
assert [f for f, _ in ran] == ["A.gcode", "B.gcode", "A.gcode"]
assert "G1 X250 Y170 F1500 S80" in ran[1][1], ran[1]
assert "G1 X110 Y60 F1500 S80" in ran[2][1], ran[2]
assert m.owner is None and not web.job_lock.locked()
r = post(op="queue_run")
assert r.status_code == 400 and "Keine wartenden" in r.get_json()["error"]
""")

    def test_skip_remove_error_stops_and_resume(self):
        self._run(r"""
for name in ("A.gcode", "B.gcode", "A.gcode", "B.gcode"):
    assert post(op="queue_add", name=name).status_code == 200
ids = [i["id"] for i in c.get("/api/status").get_json()["queue"]["items"]]
r = post(op="queue_skip", id=str(ids[0])); assert r.status_code == 200, r.data
r = post(op="queue_skip", id=str(ids[0])); assert r.status_code == 400
r = post(op="queue_remove", id=str(ids[3])); assert r.status_code == 200
r = post(op="queue_remove", id="999"); assert r.status_code == 400
fail_on.add("B.gcode")
r = post(op="queue_run"); assert r.status_code == 200, r.data
wait()
q = c.get("/api/status").get_json()["queue"]
assert q["state"] == "stopped", q
assert [i["state"] for i in q["items"]] == ["skipped", "error", "queued"], q
assert "Zeile kaputt" in q["items"][1]["error"]
assert web.job["state"] == "error" and stopped_after_error, web.job
# Resume runs the remaining item only.
fail_on.clear()
r = post(op="queue_run"); assert r.status_code == 200, r.data
wait()
q = c.get("/api/status").get_json()["queue"]
assert [i["state"] for i in q["items"]] == ["skipped", "error", "done"], q
assert [f for f, _ in ran] == ["A.gcode"]
# A file changed after queue_add is refused at run time.
assert post(op="queue_clear").status_code == 200
assert c.get("/api/status").get_json()["queue"]["items"] == []
assert post(op="queue_add", name="A.gcode").status_code == 200
import io
c.post("/api/upload", data={"file": (io.BytesIO(JOB.replace("S80", "S90").encode()), "A.gcode")})
# (checked before anything moves, the item keeps waiting)
r = post(op="queue_run")
assert r.status_code == 400 and "neu einreihen" in r.get_json()["error"], r.data
q = c.get("/api/status").get_json()["queue"]
assert q["items"][0]["state"] == "queued" and q["state"] != "running", q
assert len(ran) == 1
""")

    def test_pause_and_abort_stop_after_current(self):
        self._run(r"""
for name in ("A.gcode", "B.gcode", "A.gcode"):
    assert post(op="queue_add", name=name).status_code == 200
block.clear()
r = post(op="queue_run"); assert r.status_code == 200
started.wait(5)
s = c.get("/api/status").get_json()
assert s["activity"] == "job" and s["queue"]["state"] == "running", s["queue"]
assert s["queue"]["current"] == s["queue"]["items"][0]["id"]
r = post(op="queue_remove", id=str(s["queue"]["current"])); assert r.status_code == 400
r = post(op="start", name="B.gcode"); assert r.status_code == 400
r = post(op="queue_run"); assert r.status_code == 400
r = post(op="queue_pause"); assert r.status_code == 200, r.data
assert c.get("/api/status").get_json()["queue"]["state"] == "pausing"
block.set(); wait()
q = c.get("/api/status").get_json()["queue"]
assert q["state"] == "paused" and [i["state"] for i in q["items"]] == ["done", "queued", "queued"], q
# Abort while queued work runs: current item aborted, rest stays queued.
block.clear(); started.clear()
assert post(op="queue_run").status_code == 200
started.wait(5)
r = post(op="abort"); assert r.status_code == 200, r.data
block.set(); wait()
q = c.get("/api/status").get_json()["queue"]
assert q["state"] == "stopped" and [i["state"] for i in q["items"]] == ["done", "aborted", "queued"], q
assert m.owner is None
""")


PRELUDE = r"""
import threading, time
from marlin import web
m = web.machine
m.serial = object()
m.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
m.state = "Idle"
m.homing_verified = True
m.homed = True
m.position = [200.0, 150.0, 20.0]
sent = []
m.command = lambda cmd, **k: sent.append(cmd)
ran, fail_on = [], set()
block, started = threading.Event(), threading.Event()
block.set()
autos = []
m.probe_xy_offset_mm = (0.0, 0.0)
def fake_execute(filename, commands, auto=None):
    autos.append(auto)
    web.job.update(file=filename, state="running")
    started.set()
    block.wait(5)
    if web.stop_job.is_set():
        raise RuntimeError("Abgebrochen")
    if filename in fail_on:
        raise ValueError("Zeile kaputt")
    ran.append((filename, list(commands)))
    web.job["state"] = "complete"
web._execute_job = fake_execute
stopped_after_error = []
web._stop_after_job_error = lambda: stopped_after_error.append(True)
JOB = "G21\nG90\nM5 I\nM3 I\nG0 X100 Y100\nG1 X150 Y100 F1500 S80\nG1 X150 Y120 F1500 S80\nM5 I\n"
(web.JOBS / "A.gcode").write_text(JOB, encoding="utf-8")
(web.JOBS / "B.gcode").write_text(JOB, encoding="utf-8")
def wait():
    for _ in range(500):
        if not web.job_lock.locked():
            return
        time.sleep(0.01)
    raise AssertionError("queue did not finish")
c = web.app.test_client()
post = lambda **d: c.post("/api/action", data=d)
"""


if __name__ == "__main__":
    unittest.main()
