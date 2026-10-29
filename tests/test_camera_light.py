"""Camera light (web.py): every snapshot switches the LEDs on at the camera
level and puts them back a little after the last one."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r"""
import subprocess, types, time
from marlin import web
web.CAMERA = web.CONFIG.parent.as_posix()          # an existing path stands in for /dev/video0
FORMATS = "[0]: 'MJPG' (Motion-JPEG, compressed)\n\t\tSize: Discrete 1920x1080\n"
def fake_run(cmd, **k):
    out = FORMATS if "--list-formats-ext" in cmd else ""
    return types.SimpleNamespace(returncode=0, stdout=out if k.get("text") else out.encode(), stderr=b"")
class FakeProc:
    def __init__(self, cmd, **k):
        self.returncode = 0
        self.stderr = iter([b"  Stream #0:0: Video: mjpeg\n"])
    def communicate(self, timeout=None):
        return bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"jpeg", b""
    def kill(self):
        pass
subprocess.run, subprocess.Popen = fake_run, FakeProc
m = web.machine
m.lights, m.light_pct = False, 60
calls = []
def set_light(on, pct=None, owner="web"):
    calls.append((on, pct))
    m.lights = on
    if pct is not None:
        m.light_pct = pct
    return m.lights, m.light_pct, True
m.set_light = set_light
web.CAMERA_LIGHT_HOLD_S, web.CAMERA_LIGHT_SETTLE_S = 0.2, 0.0
web.config["camera"] = dict(web.config["camera"], light=90)
c = web.app.test_client()
snap = lambda q="": c.get("/api/camera/snapshot?w=1920&h=1080" + q).status_code
# off -> on at the camera level, two pictures in a row switch only once
assert snap() == 200 and snap() == 200
assert calls == [(True, 90)], calls
time.sleep(0.4)
assert calls == [(True, 90), (False, 60)], calls          # back to how it was
# light=keep: the light calibration controls the LEDs itself
calls.clear()
assert snap("&light=keep") == 200 and calls == [], calls
# someone switches the light while it is held: theirs stays
calls.clear()
assert snap() == 200
m.lights, m.light_pct = True, 30
time.sleep(0.4)
assert calls == [(True, 90)], calls
# without a camera level the normal brightness is used
calls.clear()
m.lights, m.light_pct = False, 45
web.config["camera"]["light"] = None
assert snap() == 200 and calls == [(True, 45)], calls
time.sleep(0.4)
# a job owns the machine: set_light refuses, the picture is still taken
calls.clear()
m.lights = False
def busy(on, pct=None, owner="web"):
    raise RuntimeError("Steuerung belegt: job")
m.set_light = busy
assert snap() == 200
"""


class CameraLightTests(unittest.TestCase):
    def test_snapshot_switches_the_light_and_puts_it_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["LUMACUT_DATA"] = tmp
            env["PYTHONPATH"] = str(ROOT / "pi400")
            result = subprocess.run([sys.executable, "-c", SCRIPT], env=env, cwd=ROOT,
                                    text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
