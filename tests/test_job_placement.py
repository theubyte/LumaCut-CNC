"""Job origin options (#16): placement math, bounds and the web API."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi400"))
from marlin import placement as placing  # noqa: E402
from marlin.transport import MarlinLaserGuard  # noqa: E402

JOB = ("; studio\nG21\nG90\nM5 I\nM3 I\nG0 X100 Y100 ; start\n"
       "G1 X150 Y100 F1500 S80\nG1 X150 Y120 F1500 S80\nG0 X0 Y0\n"
       "G91\nG0 Z-1 F600\nG90\nM5 I\nM400\n")
TRAVELS = {"x": 390.0, "y": 370.0}


class PlacementMathTests(unittest.TestCase):
    def test_translate_only_absolute_xy_and_guard_still_holds(self):
        out = placing.translate(JOB.splitlines(), 10.5, -20)
        self.assertIn("G0 X110.5 Y80", out)
        self.assertIn("G1 X160.5 Y80 F1500 S80", out)
        self.assertIn("G1 X160.5 Y100 F1500 S80", out)
        self.assertIn("G0 Z-1 F600", out)      # relative Z untouched
        self.assertIn("G0 X10.5 Y-20", out)    # rapid to 0/0 moves too ...
        with self.assertRaisesRegex(ValueError, "außerhalb des Arbeitsbereichs"):
            placing.check_extent(out, TRAVELS, 30.0)  # ... and is then rejected
        guard = MarlinLaserGuard()
        for line in out:
            guard.check(line, True)
        self.assertEqual(placing.translate(JOB.splitlines(), 0, 0), JOB.splitlines())

    def test_anchor_points_and_powered_box(self):
        motion, powered = placing.scan(JOB.splitlines())
        self.assertEqual((powered.xmin, powered.ymin, powered.xmax, powered.ymax),
                         (100.0, 100.0, 150.0, 120.0))
        self.assertEqual((motion.xmin, motion.ymin), (0.0, 0.0))
        # Visible corners, endstops top right: "r" = small X, "t" = small Y.
        self.assertEqual(placing.anchor_point(powered, "tr"), (100.0, 100.0))
        self.assertEqual(placing.anchor_point(powered, "bl"), (150.0, 120.0))
        self.assertEqual(placing.anchor_point(powered, "tl"), (150.0, 100.0))
        self.assertEqual(placing.anchor_point(powered, "br"), (100.0, 120.0))
        self.assertEqual(placing.anchor_point(powered, "center"), (125.0, 110.0))
        with self.assertRaises(ValueError):
            placing.anchor_point(powered, "middle")

    def test_powered_moves_must_stay_out_of_safe_zone(self):
        cut = ["M3 I", "G0 X100 Y100", "G1 X150 Y100 F1500 S80"]
        placing.check_extent(placing.translate(cut, -70, 0), TRAVELS, 30.0)
        with self.assertRaisesRegex(ValueError, "Safezone"):
            placing.check_extent(placing.translate(cut, -71, 0), TRAVELS, 30.0)
        with self.assertRaisesRegex(ValueError, "außerhalb"):
            placing.check_extent(placing.translate(cut, 241, 0), TRAVELS, 30.0)

    def test_arc_extremes_count(self):
        # Half circle from (100,100) to (140,100) around (120,100), CCW below? G3 = CCW.
        arc = ["M3 I", "G0 X100 Y100", "G3 X140 Y100 I20 J0 F600 S50"]
        _, powered = placing.scan(arc)
        self.assertAlmostEqual(powered.ymin, 80.0)   # CCW from 180° to 0° passes 270°
        self.assertAlmostEqual(powered.ymax, 100.0)
        _, powered = placing.scan(["M3 I", "G0 X100 Y100", "G2 X140 Y100 I20 J0 F600 S50"])
        self.assertAlmostEqual(powered.ymax, 120.0)
        out = placing.translate(arc, 5, 5)
        self.assertEqual(out[-1], "G3 X145 Y105 I20 J0 F600 S50")

    def test_relative_xy_detected(self):
        self.assertTrue(placing.has_relative_xy(["G91", "G1 X5 S10"]))
        self.assertFalse(placing.has_relative_xy(["G91", "G0 Z-1", "G90", "G1 X5 S10"]))


class PlacementWebTests(unittest.TestCase):
    def _run(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["LUMACUT_DATA"] = tmp
            env["PYTHONPATH"] = str(ROOT / "pi400")
            result = subprocess.run([sys.executable, "-c", source], env=env, cwd=ROOT,
                                    text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)

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
def command(cmd, **k):
    sent.append(cmd)
m.command = command
ran = []
def fake_worker(filename, commands, probe_point=None):
    ran.append((filename, list(commands), probe_point))
    with m.lock:
        m.owner = None
    web.job_lock.release()
web._job_worker = fake_worker
JOB = "G21\nG90\nM5 I\nM3 I\nG0 X100 Y100\nG1 X150 Y100 F1500 S80\nG1 X150 Y120 F1500 S80\nM5 I\n"
(web.JOBS / "Schild.gcode").write_text(JOB, encoding="utf-8")
def wait():
    for _ in range(200):
        if not web.job_lock.locked():
            return
        time.sleep(0.01)
c = web.app.test_client()
post = lambda **d: c.post("/api/action", data=d)
"""

    def test_status_start_modes_and_absolute_default(self):
        self._run(self.PRELUDE + r"""
s = c.get("/api/status").get_json()
assert s["origin"]["modes"] == ["absolute", "current", "user"], s["origin"]
# Anchor semantics are versioned: "tr" = visible top right = endstop corner.
assert s["coord_convention"] == "origin_top_right" == s["origin"]["coord_convention"], s
assert s["origin"]["user"] is None and s["origin"]["placement"] is None
# Default (LightBurn/web UI/older Studio): runs exactly as stored.
r = post(op="start", name="Schild.gcode"); wait()
assert r.status_code == 200, r.data
assert ran[-1][1] == JOB.splitlines(), ran[-1]
# Current head position = top-left of the motif.
r = post(op="start", name="Schild.gcode", origin="current", anchor="tr"); wait()
assert r.status_code == 200, r.data
lines = ran[-1][1]
assert "G0 X200 Y150" in lines and "G1 X250 Y170 F1500 S80" in lines, lines
assert "M114" in sent, "fresh head position"
p = c.get("/api/status").get_json()["origin"]["placement"]
assert p["origin"] == "current" and p["dx"] == 100 and p["dy"] == 50, p
assert "sha" not in p
# Jogging drops a placement on the current position.
r = post(op="jog", axis="X", distance="1"); assert r.status_code == 200, r.data
assert c.get("/api/status").get_json()["origin"]["placement"] is None
r = post(op="start", name="Schild.gcode", placement="1")
assert r.status_code == 400 and "neu platzieren" in r.get_json()["error"], r.data
""")

    def test_user_origin_place_frame_and_bounds(self):
        self._run(self.PRELUDE + r"""
FRAME = "G21\nG90\nM5 I\nG0 X100 Y100\nG1 X150 Y100 F3000 S0\nG1 X150 Y120 F3000 S0\nM5 I\nM400\n"
# Not homed: nothing placed, nothing stored.
m.homed = False
r = post(op="origin_set", x="60", y="60")
assert r.status_code == 400 and "referenzieren" in r.get_json()["error"], r.data
m.homed = True
r = post(op="origin_set", x="20", y="60")
assert r.status_code == 400 and "Schneidbereich" in r.get_json()["error"], r.data
r = post(op="origin_set", x="60", y="70")
assert r.status_code == 200, r.data
assert web.config["user_origin"] == [60.0, 70.0]
import json; assert json.loads(web.CONFIG.read_text())["user_origin"] == [60.0, 70.0]
r = post(op="place", name="Schild.gcode", origin="user", anchor="center")
assert r.status_code == 200, r.data
p = r.get_json()["placement"]
assert (p["dx"], p["dy"]) == (-65.0, -40.0) and p["bounds"]["xmin"] == 35.0, p
# Frame follows the placement (laser off, same offset).
sent.clear()
web.frame_program_seen = None
orig = web.frame_program
def spy(text):
    web.frame_program_seen = text
    return orig(text)
web.frame_program = spy
r = post(op="frame", gcode=FRAME, placement="1", name="Schild.gcode"); wait()
assert r.status_code == 200, r.data
assert "G0 X35 Y60" in web.frame_program_seen and "G1 X85 Y80 F3000 S0" in web.frame_program_seen
assert "G1 X85 Y80 F3000 S0" in sent and not any(x.startswith("M3") for x in sent), sent
# Start with the stored placement.
r = post(op="start", name="Schild.gcode", placement="1"); wait()
assert r.status_code == 200, r.data
assert "G1 X85 Y60 F1500 S80" in ran[-1][1], ran[-1]
# Autorun probes at the placed motif centre.
m.probe_xy_offset_mm = (10.0, 5.0)
r = post(op="autorun", name="Schild.gcode", placement="1"); wait()
assert r.status_code == 200 and ran[-1][2] == (60.0, 70.0), (r.data, ran[-1][2])
# A changed file invalidates the placement.
import io
r = c.post("/api/upload", data={"file": (io.BytesIO(JOB.replace("S80", "S90").encode()), "Schild.gcode")})
assert r.status_code == 200
r = post(op="start", name="Schild.gcode", placement="1")
assert r.status_code == 400 and "Platzierung" in r.get_json()["error"], r.data
# Motif pushed into the safe zone / out of travel: refused, nothing runs.
n = len(ran)
r = post(op="origin_set", x="30", y="30")
assert r.status_code == 200, r.data
r = post(op="place", name="Schild.gcode", origin="user", anchor="bl")
assert r.status_code == 400 and "außerhalb" in r.get_json()["error"], r.data
r = post(op="start", name="Schild.gcode", origin="user", anchor="bl")
assert r.status_code == 400 and len(ran) == n, r.data
m.position = [389.0, 369.0, 20.0]
r = post(op="start", name="Schild.gcode", origin="current", anchor="tr")
assert r.status_code == 400 and "außerhalb" in r.get_json()["error"], r.data
assert len(ran) == n
r = post(op="place", name="Schild.gcode", origin="moon")
assert r.status_code == 400
r = post(op="origin_clear"); assert r.status_code == 200
r = post(op="start", name="Schild.gcode", origin="user")
assert r.status_code == 400 and "Kein Benutzer-Ursprung" in r.get_json()["error"], r.data
""")


if __name__ == "__main__":
    unittest.main()
