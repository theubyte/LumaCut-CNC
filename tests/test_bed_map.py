"""Bed map (pi400/marlin/bedmap.py, op=bedmap): the empty bed probed once.

The bare bed lies below Z0 on the machine (0.7 to 1.2 mm, 2026-10-29), so
contacts below Z0 must be accepted; the map then gives the thickness of a
probed workpiece above the bed.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi400"))
sys.path.insert(0, str(ROOT / "tests"))
from marlin import bedmap  # noqa: E402
from marlin import heightmap as hm  # noqa: E402
from test_autorun import SIM  # noqa: E402

BOUNDS = hm.Box(30, 30, 390, 370)


class BedMapPlanTests(unittest.TestCase):
    def test_grid_covers_the_bed_inside_the_y_limit(self):
        g = bedmap.plan(BOUNDS, lambda x, y: True)
        self.assertEqual((g.cols, g.rows), (bedmap.COLS, bedmap.ROWS))
        xs = [g.point(i)[0] for i in range(len(g.z))]
        ys = [g.point(i)[1] for i in range(len(g.z))]
        self.assertAlmostEqual(min(xs), 40.0)
        self.assertAlmostEqual(max(xs), 380.0)
        self.assertAlmostEqual(min(ys), 40.0)
        self.assertAlmostEqual(max(ys), bedmap.Y_LIMIT_MM - bedmap.INSET_MM)

    def test_unreachable_points_are_probed_next_to_them(self):
        g = bedmap.plan(BOUNDS, lambda x, y: x <= 360)
        self.assertTrue(all(g.reachable))
        moved = [p for p in g.probe_at if p is not None]
        self.assertEqual(len(moved), bedmap.ROWS)
        self.assertTrue(all(p[0] <= 360 for p in moved))

    def test_heights_round_trip_and_thickness_above_bed(self):
        g = bedmap.plan(BOUNDS, lambda x, y: True)
        g.z = [-0.7 - 0.002 * (g.point(i)[0] - 40) for i in range(len(g.z))]
        bed = bedmap.BedMap.from_measured(g, measured_at=1_800_000_000)
        self.assertAlmostEqual(bed.at(40, 100), -0.7)
        self.assertAlmostEqual(bed.at(210, 100), -1.04)
        self.assertAlmostEqual(bed.above_bed(14.77, 210, 100), 15.81)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / bedmap.FILENAME
            bedmap.save(path, bed)
            back = bedmap.load(path)
        self.assertEqual(back.summary(), bed.summary())
        self.assertAlmostEqual(back.at(300, 200), bed.at(300, 200))
        self.assertEqual(bed.summary()["range"], 0.68)

    def test_missing_or_broken_file_is_no_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / bedmap.FILENAME
            self.assertIsNone(bedmap.load(path))
            path.write_text("{kaputt", "utf-8")
            self.assertIsNone(bedmap.load(path))


class BedMapWebTests(unittest.TestCase):
    def _run(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["LUMACUT_DATA"] = tmp
            env["PYTHONPATH"] = str(ROOT / "pi400")
            result = subprocess.run([sys.executable, "-c", SIM + source], env=env, cwd=ROOT,
                                    text=True, capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_bed_below_z0_is_mapped_and_gives_workpiece_thickness(self):
        self._run(r"""
import time
OFFSET = (-27.4, 13.0)
bed = lambda x, y: -0.7 - 0.002 * x            # bare bed below Z0, sloping
sim, m = connect(bed)
c = web.app.test_client()
assert c.post("/api/action", data={"op": "home"}).status_code == 200
r = c.post("/api/action", data={"op": "bedmap"})
assert r.status_code == 200, r.data
for _ in range(4000):
    s = c.get("/api/status").get_json()
    if s["job"]["state"] in ("complete", "error", "aborted"):
        break
    time.sleep(0.005)
assert s["job"]["state"] == "complete", s["job"]
assert s["job"]["file"] == "Bettkarte"
summary = s["bed_map"]
assert summary["lowest"] < -1.3 and summary["highest"] > -0.8, summary
assert m.surface_z is None                     # the bed is no workpiece
# Hops between bed points stay well above the bed (forgotten clamps).
w = sim.writes
i0, i1 = w.index("G30 E0"), w.index("M402")
hops = [float(x.split("Z")[1].split()[0]) for x in w[i0:i1] if x.startswith("G0 Z")]
assert min(hops) >= 8.5, hops
full = c.get("/api/bedmap").get_json()["bed_map"]
assert len(full["z"]) == 36 and full["format"] == "lumacut-bed-map/1"
# Kept across a restart of the service.
from marlin import bedmap
assert bedmap.load(web.BED_MAP_FILE).summary() == summary
# A workpiece 14.5 mm thick on the bed: the probe now reports it.
sim.surface = lambda x, y: bed(x, y) + 14.5
r = c.post("/api/action", data={"op": "probe", "x": "200", "y": "150"})
assert r.status_code == 200, r.data
above = r.get_json()["above_bed_mm"]
assert abs(above - 14.5) < 0.05, r.get_json()
assert "ber dem Bett" in r.get_json()["message"]
assert abs(c.get("/api/status").get_json()["workpiece_above_bed_mm"] - 14.5) < 0.05
assert c.post("/api/action", data={"op": "bedmap_clear"}).status_code == 200
assert c.get("/api/status").get_json()["bed_map"] is None
assert not web.BED_MAP_FILE.exists()
""")


if __name__ == "__main__":
    unittest.main()
