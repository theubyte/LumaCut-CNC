"""Adaptive material calibration (pi400/marlin/matcal.py, op=matcal).

Engraving field by field and cutting pass by pass, each step photographed
and measured; against the simulated Marlin with a stand-in camera that
shows what was lasered (tone from the energy per area, holes once a square
got its passes).
"""
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi400"))
sys.path.insert(0, str(ROOT / "tests"))
from marlin import matcal  # noqa: E402
from test_autorun import SIM  # noqa: E402

# Tablet lens model of the machine (2026-10-29), shortened.
ANDROID = {"photoWidth": 1920, "photoHeight": 1080, "scanZ": 33.3, "aboveSurface": 31.04,
           "lens": {"cx": 960.0, "cy": 540.0, "f": 1101.45, "k1": -0.4385, "k2": 0.1746,
                    "g": [0.00337, -0.03199, -0.0533, 0.03237, 0.00059, 0.0091, 0.0, 0.0, 1.0]}}


def plywood_tone(power, speed):
    """Poplar plywood 2026-10-29: 4.5 % at 3000 -> 0.34, 8.5 % -> 0.87."""
    e = power / speed * 1000
    return 1 / (1 + math.exp(-(e - 1.95) * 3.2))


class CameraModelTests(unittest.TestCase):
    def test_head_for_puts_the_point_in_the_picture_centre(self):
        cam = matcal.CameraModel(ANDROID)
        head = cam.head_for(150.0, 120.0)
        seen = []
        img = matcal.Gray(1920, 1080, bytes(1920 * 1080))
        img.at = lambda u, v: seen.append((u, v)) or 0.0
        cam.sampler(img, head, 24.0, 4.0)(150.0, 120.0)
        self.assertAlmostEqual(seen[0][0], 960.0, delta=0.5)
        self.assertAlmostEqual(seen[0][1], 540.0, delta=0.5)

    def test_higher_camera_sees_points_closer_to_the_centre(self):
        cam = matcal.CameraModel(ANDROID)
        head = cam.head_for(150.0, 120.0)
        def pixel(z):
            seen = []
            img = matcal.Gray(1920, 1080, bytes(1920 * 1080))
            img.at = lambda u, v: seen.append((u, v)) or 0.0
            cam.sampler(img, head, z, 4.0)(160.0, 120.0)
            return seen[0]
        near, far = pixel(24.0), pixel(70.0)
        self.assertGreater(abs(near[1] - 540), abs(far[1] - 540))

    def test_uncalibrated_camera_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "Punktraster"):
            matcal.CameraModel({})

    def test_bilinear_sampling(self):
        img = matcal.Gray(3, 2, bytes([0, 100, 200, 50, 150, 250]))
        self.assertEqual(img.at(0.5, 0.5), 75.0)
        self.assertTrue(math.isnan(img.at(5, 0)))


def world(fields, wood=180.0):
    """lum(x, y) of a plate with dark squares [(x, y, size, tone)]."""
    def lum(x, y):
        for fx, fy, size, tone in fields:
            if fx <= x <= fx + size and fy <= y <= fy + size:
                return wood * (1 - tone)
        return wood
    return lum


class MeasureTests(unittest.TestCase):
    def test_tone_and_clean_field(self):
        lum = world([(100, 100, 5, 0.6)])
        m = matcal.measure_field(lum, 100, 100)
        self.assertAlmostEqual(m["tone"], 0.6, places=2)
        self.assertTrue(matcal.clean(m))

    def test_stripes_and_halo_are_seen(self):
        def stripes(x, y):
            if 100 <= x <= 105 and 100 <= y <= 105:
                return 60.0 if int(y * 10) % 4 < 2 else 110.0
            return 180.0
        self.assertGreater(matcal.measure_field(stripes, 100, 100)["stripes"], matcal.CLEAN_STRIPES)
        halo = world([(99.0, 99.0, 7.0, 0.3), (100, 100, 5, 1.0)])     # smoke 1 mm around
        m = matcal.measure_field(halo, 100, 100)
        self.assertGreater(m["halo"], matcal.CLEAN_HALO)
        self.assertFalse(matcal.clean(m))

    def test_locate_finds_the_registration_shift(self):
        before = world([])
        after = world([(101.0, 98.75, 5, 0.8)])
        dx, dy, dark = matcal.locate(before, after, 100, 100, 5.0, reach=3.0)
        self.assertEqual((dx, dy), (1.0, -1.25))
        self.assertGreater(dark, 100)

    def test_hole_ratio(self):
        self.assertAlmostEqual(matcal.hole_ratio(world([]), 100, 100), 1.0)
        self.assertLess(matcal.hole_ratio(world([(100, 100, 8, 0.97)]), 100, 100), 0.1)


class SearchTests(unittest.TestCase):
    def test_engraving_finds_three_tones_in_few_fields(self):
        s = matcal.EngraveSearch()
        while (step := s.next()) is not None:
            t = plywood_tone(step["power"], step["speed"])
            s.add(step, {"tone": t, "uneven": 0.05, "stripes": 0.04, "halo": 0.02})
        self.assertEqual(set(s.results), {"dunkel", "mittel", "hell"})
        self.assertLessEqual(len(s.fields), 10)
        for name, target in matcal.TARGETS:
            self.assertLessEqual(abs(s.results[name]["tone"] - target), matcal.TONE_TOL)
        self.assertLess(s.results["hell"]["power"], s.results["mittel"]["power"])

    def test_streaky_dark_is_tried_slower_with_the_same_energy(self):
        s = matcal.EngraveSearch(start_power=14, speed=6000)
        step = s.next()
        s.add(step, {"tone": 0.85, "uneven": 0.13, "stripes": 0.10, "halo": 0.02})
        nxt = s.next()
        self.assertEqual(nxt["speed"], 4000)
        self.assertAlmostEqual(nxt["power"] / nxt["speed"], 14 / 6000, places=4)

    def test_smoky_dark_is_tried_faster(self):
        s = matcal.EngraveSearch(start_power=10, speed=1500)
        step = s.next()
        s.add(step, {"tone": 0.88, "uneven": 0.02, "stripes": 0.02, "halo": 0.3})
        self.assertEqual(s.next()["speed"], 2250)

    def test_never_more_fields_than_the_area_holds(self):
        s = matcal.EngraveSearch()
        while (step := s.next()) is not None:
            s.add(step, {"tone": 0.0, "uneven": 0.5, "stripes": 0.5, "halo": 0.0})   # material takes no colour
        self.assertLessEqual(len(s.fields), matcal.ENGRAVE_MAX_FIELDS)

    def test_cutting_stops_each_speed_when_it_cannot_win(self):
        need = lambda v: math.ceil(v / 260)
        c = matcal.CutSearch()
        lasered = 0
        while (step := c.next()) is not None:
            lasered += 1
            c.add(step, step["pass"] + 1 >= need(step["speed"]))
        self.assertEqual(c.best(), {"speed": 500.0, "passes": 2, "fell": True})
        # 1200 mm/min would need 5 passes; 1.6 x the best energy allows 7: falls in time.
        self.assertEqual([s["passes"] for s in c.squares], [2, 2, 4, 5])
        self.assertEqual(lasered, 13)
        c = matcal.CutSearch(speeds=(500.0, 1200.0))
        c.add(c.next(), False); c.add(c.next(), True)              # 500 x 2
        while (step := c.next()) is not None:
            c.add(step, False)                                      # 1200 never falls
        self.assertEqual(c.squares[1], {"speed": 1200.0, "passes": 7, "fell": False})

    def test_gcode_stays_in_the_area_and_the_focus_follows_the_cut(self):
        lines = matcal.engrave_field(100, 120, 12.8, 4500, 12.5)
        xs = [float(w[1:]) for l in lines for w in l.split() if w.startswith("X")]
        self.assertEqual((min(xs), max(xs)), (97.0, 108.0))
        self.assertIn("G0 Z12.500 F600", lines)
        self.assertIn("S32.6", " ".join(lines))
        self.assertEqual(lines[0], "M5 I")
        self.assertEqual(lines[-1], "M5 I")
        self.assertIn("G0 Z12.100 F600", matcal.cut_pass(100, 120, 500, 100, 12.5, 1))
        self.assertIn("G0 Z9.500 F600", matcal.cut_pass(100, 120, 500, 100, 12.5, 9))


WEB = r"""
import json, math, re, time
OFFSET = (-23.0, 15.0)
sim, m = connect(lambda x, y: 4.0)
m.homed = True
web.WORKSPACE.put_state({"material": {"name": "Testplatte", "thickness_mm": 4.0}}, None)
web.CAMERA = web.CONFIG.parent.as_posix()          # an existing path stands in for /dev/video0
SHIFT = (1.0, -1.0)                                 # camera/laser registration

class World:
    # what the plate looks like: powered raster rows and cut passes from the G-code
    def __init__(self):
        self.rows, self.cuts, self.pos, self.s = {}, {}, [0.0, 0.0], 0.0
    def feed(self, cmd):
        w = dict((k, float(v)) for k, v in re.findall(r"([XYS])([-+]?[0-9.]+)", cmd))
        if not re.match(r"G[01] ", cmd):
            return
        if "S" in w:
            self.s = w["S"]
        new = [w.get("X", self.pos[0]), w.get("Y", self.pos[1])]
        if cmd.startswith("G1") and self.s > 0:
            f = float(re.search(r"F(\d+)", cmd).group(1))
            if new[1] == self.pos[1] and abs(new[0] - self.pos[0]) < 6:      # raster row
                self.rows.setdefault(round(new[1], 1), []).append(
                    (min(new[0], self.pos[0]), max(new[0], self.pos[0]), self.s / 2.55, f))
            elif self.s >= 250:                                              # cut edge
                key = (round(min(new[0], self.pos[0]) / 4), round(min(new[1], self.pos[1]) / 4))
                self.cuts.setdefault("n", []).append((tuple(self.pos), tuple(new), f))
        self.pos = new
    def snapshot(self):
        rows = {k: list(v) for k, v in self.rows.items()}
        cuts = list(self.cuts.get("n", []))
        def lum(x, y):
            x, y = x - SHIFT[0], y - SHIFT[1]
            for x0, x1, p, f in rows.get(round(y, 1), ()):
                if x0 <= x <= x1:
                    e = p / f * 1000
                    return 180.0 * (1 - 1 / (1 + math.exp(-(e - 1.95) * 3.2)))
            for i, sp in enumerate(SPEEDS):
                sx = ORIGIN[0] + i * 12
                if sx < x < sx + 8 and ORIGIN[1] < y < ORIGIN[1] + 8:
                    n = sum(1 for a, b, f in cuts if f == sp and sx - 0.1 <= a[0] <= sx + 8.1 and ORIGIN[1] - 0.1 <= a[1] <= ORIGIN[1] + 8.1)
                    return 5.0 if n / 4 >= math.ceil(sp / 260) else 175.0
            return 180.0
        return lum

world = World()
sim.hook = world.feed
class Cam:
    photo_w, photo_h = 1920, 1080
    def head_for(self, x, y):
        return x - 51.3, y + 1.7
    def sampler(self, img, head, z, surface):
        return img
web._camera_model = lambda: Cam()
web.head_camera.snapshot = lambda *a, **k: b"jpeg"
shots = []
def decode(data, w, h):
    shots.append(tuple(m.position))
    return world.snapshot()
web.matcal.decode_gray = decode
lights = []
real_light = m.set_light
def set_light(on, pct=None, owner="web"):
    lights.append((on, pct, owner))
    m.lights = on
    return on, pct, True
m.set_light = set_light
c = web.app.test_client()

def wait():
    for _ in range(20000):
        s = c.get("/api/status").get_json()
        if s["job"]["state"] in ("complete", "error", "aborted"):
            return s
        time.sleep(0.005)
    raise AssertionError("hängt")
"""


class MaterialCalibrationWebTests(unittest.TestCase):
    def _run(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["LUMACUT_DATA"] = tmp
            env["PYTHONPATH"] = str(ROOT / "pi400")
            result = subprocess.run([sys.executable, "-c", SIM + WEB + source], env=env, cwd=ROOT,
                                    text=True, capture_output=True, timeout=300)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:])

    def test_engraving_field_by_field_saves_three_materials(self):
        self._run(r"""
SPEEDS, ORIGIN = (), (0, 0)
r = c.post("/api/action", data={"op": "matcal", "kind": "engrave", "x": "150", "y": "120", "name": "Sperrholz Test"})
assert r.status_code == 200, r.data
assert "Feld für Feld" in r.get_json()["message"], r.data
s = wait()
assert s["job"]["state"] == "complete", s["job"]
run = c.get("/api/matcal").get_json()["material_calibration"]
assert run["state"] == "complete", run
fields = run["fields"]
assert 3 <= len(fields) <= 12, len(fields)
assert all(f["shift"] == [1.0, -1.0] for f in fields if f["tone"] > 0.2), [f["shift"] for f in fields]
for name, target in (("dunkel", 0.85), ("mittel", 0.55), ("hell", 0.30)):
    assert abs(run["result"][name]["tone"] - target) <= 0.06, run["result"]
mats = {(m["name"], m["process"]): m for m in c.get("/api/materials").get_json()["materials"]}
dark = mats[("Sperrholz Test", "Gravieren")]
assert dark["mode"] == "fill" and dark["passes"] == 1 and dark["thickness_mm"] == 4.0, dark
assert ("Sperrholz Test (mittel)", "Gravieren") in mats and ("Sperrholz Test (hell)", "Gravieren") in mats
assert mats[("Sperrholz Test (hell)", "Gravieren")]["power_pct"] < dark["power_pct"]
assert "Automatische Gravur-Kalibrierung" in dark["notes"]
# every field lasered at focus, inside the area, one photo per field plus the first
w = sim.writes
z = [float(x.split("Z")[1].split()[0]) for x in w if x.startswith("G0 Z") and "F600" in x]
focus = run["focus_z"]
assert focus is not None and focus in z, (focus, sorted(set(z)))
xs = [float(v) for x in w if x.startswith("G1 X") for v in re.findall(r"X([-+0-9.]+)", x)]
assert min(xs) >= 147.0 - 0.01 and max(xs) <= 150 + 5 * 8 + 5 + 3 + 0.01, (min(xs), max(xs))
assert len(shots) == len(fields) + 1, (len(shots), len(fields))
assert all(abs(p[0] - (150 + 22.5 - 51.3)) < 0.01 for p in shots), shots[:2]
assert lights[0][:2] == (True, web._camera_light_level()) and lights[-1][0] is False, lights
assert s["material_calibration"]["state"] == "complete" and s["material_calibration"]["steps"] == len(fields)
# a second run updates the same materials instead of adding new ones
before = len(c.get("/api/materials").get_json()["materials"])
c.post("/api/action", data={"op": "matcal", "kind": "engrave", "x": "150", "y": "160", "name": "Sperrholz Test"})
assert wait()["job"]["state"] == "complete"
assert len(c.get("/api/materials").get_json()["materials"]) == before
""")

    def test_cutting_pass_by_pass_on_a_raised_plate(self):
        self._run(r"""
SPEEDS, ORIGIN = (350.0, 500.0, 800.0, 1200.0), (150.0, 120.0)
r = c.post("/api/action", data={"op": "matcal", "kind": "cut", "x": "150", "y": "120", "name": "Sperrholz Test"})
assert r.status_code == 400 and "hochlegen" in r.get_json()["error"], r.data
r = c.post("/api/action", data={"op": "matcal", "kind": "cut", "x": "150", "y": "120", "name": "Sperrholz Test", "raised": "1"})
assert r.status_code == 200, r.data
s = wait()
assert s["job"]["state"] == "complete", s["job"]
run = c.get("/api/matcal").get_json()["material_calibration"]
assert run["result"]["best"] == {"speed": 500.0, "passes": 2, "fell": True}, run["result"]
assert [q["passes"] for q in run["result"]["squares"]] == [2, 2, 4, 5], run["result"]
assert len(run["passes"]) == 13 and run["passes"][1]["fell"] is True, run["passes"][:3]
cut = [m for m in c.get("/api/materials").get_json()["materials"] if m["process"] == "Schneiden" and m["name"] == "Sperrholz Test"]
assert len(cut) == 1 and cut[0]["speed_mm_min"] == 500.0 and cut[0]["passes"] == 2 and cut[0]["z_step_mm"] == 0.4, cut
# the focus followed the cut: pass 2 of every square 0.4 mm lower
z = sorted(set(float(x.split("Z")[1].split()[0]) for x in sim.writes if x.startswith("G0 Z") and "F600" in x))
assert round(run["focus_z"] - 0.4, 3) in z, (run["focus_z"], z)
""")

    def test_refusals_before_anything_moves(self):
        self._run(r"""
SPEEDS, ORIGIN = (), (0, 0)
sim.writes.clear()
for data, text in (({"kind": "x", "x": "150", "y": "120", "name": "A"}, "kind"),
                   ({"kind": "engrave", "x": "150", "y": "120", "name": ""}, "Materialname"),
                   ({"kind": "engrave", "x": "10", "y": "120", "name": "A"}, "Arbeitsbereich"),
                   ({"kind": "engrave", "x": "360", "y": "120", "name": "A"}, "Arbeitsbereich")):
    r = c.post("/api/action", data=dict(data, op="matcal"))
    assert r.status_code == 400 and text in r.get_json()["error"], (data, r.data)
web._camera_model = lambda: web.matcal.CameraModel({})
r = c.post("/api/action", data={"op": "matcal", "kind": "engrave", "x": "150", "y": "120", "name": "A"})
assert r.status_code == 400 and "Punktraster" in r.get_json()["error"], r.data
assert not [w for w in sim.writes if w.startswith(("G0", "G1", "M3"))], sim.writes
""")

    def test_abort_between_fields_parks_and_keeps_the_fields(self):
        self._run(r"""
SPEEDS, ORIGIN = (), (0, 0)
real = web.matcal.measure_field
def measure(lum, x, y, **k):
    web.stop_job.set()                      # operator presses Abbrechen after the first field
    return real(lum, x, y, **k)
web.matcal.measure_field = measure
r = c.post("/api/action", data={"op": "matcal", "kind": "engrave", "x": "150", "y": "120", "name": "A"})
assert r.status_code == 200, r.data
s = wait()
assert s["job"]["state"] == "aborted" and s["job"]["error"] == "Abgebrochen", s["job"]
run = c.get("/api/matcal").get_json()["material_calibration"]
assert run["state"] == "aborted" and len(run["fields"]) == 1, run
assert not [m for m in c.get("/api/materials").get_json()["materials"] if m["name"] == "A"]
assert "M112" not in sim.writes
""")


if __name__ == "__main__":
    unittest.main()
