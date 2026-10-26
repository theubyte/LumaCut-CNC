"""Automatic job op=autorun (docs/ZUSAMMENARBEIT_CLAUDE_GROK.md §4).

Probe plan from the laser paths, fast multi-point probing, focus compensation
on the Pi and the whole run against a simulated Marlin.
"""
import math
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi400"))
from marlin import heightmap as hm  # noqa: E402
from marlin.focus_compensation import compensate, has_absolute_z  # noqa: E402

BOUNDS = hm.Box(30, 30, 390, 370)
ALL = lambda x, y: True


def square(x, y, size, s=100):
    return ["G0 X%g Y%g" % (x, y), "G1 X%g Y%g F1500 S%d" % (x + size, y, s),
            "G1 X%g Y%g S%d" % (x + size, y + size, s), "G1 X%g Y%g S%d" % (x, y + size, s),
            "G1 X%g Y%g S%d" % (x, y, s)]


def flat(z, region=hm.Box(30, 30, 390, 370)):
    return hm.HeightMapSet([hm.HeightGrid(region, region.xmin, region.ymin, region.width,
                                          region.height, 2, 2, [z] * 4, [True] * 4)])


def zs(lines):
    return [float(re.search(r"Z([-+]?[0-9.]+)", l).group(1)) for l in lines if " Z" in l]


class ProbePlanTests(unittest.TestCase):
    def test_separate_motifs_get_separate_areas_with_margin(self):
        lines = ["M3 I"] + square(50, 50, 40) + square(250, 200, 100) + ["M5 I"]
        regions = hm.motif_regions(lines, BOUNDS)
        self.assertEqual(regions, [hm.Box(48, 48, 92, 92), hm.Box(248, 198, 352, 302)])
        # Rapids and unpowered moves do not count.
        lines = ["G0 X40 Y40", "G0 X380 Y360", "G1 X100 Y100 S0"] + square(100, 100, 20)
        self.assertEqual(hm.motif_regions(lines, BOUNDS), [hm.Box(98, 98, 122, 122)])

    def test_close_parts_merge_and_area_is_clamped(self):
        lines = square(100, 100, 30) + square(136, 100, 30)    # 6 mm gap
        self.assertEqual(len(hm.motif_regions(lines, BOUNDS)), 1)
        self.assertEqual(hm.motif_regions(square(30, 30, 20), BOUNDS), [hm.Box(30, 30, 52, 52)])

    def test_point_count_follows_size_and_stays_small(self):
        def counts(size):
            g = hm.plan_probe(square(40, 40, size), BOUNDS, ALL)[0]
            return g.cols, g.rows
        self.assertEqual(counts(8), (1, 1))
        self.assertEqual(counts(50), (2, 2))
        self.assertEqual(counts(150), (3, 3))
        self.assertEqual(counts(320), (4, 4))
        many = []
        for i in range(4):
            for j in range(3):
                many += square(40 + i * 90, 40 + j * 110, 70)
        grids = hm.plan_probe(many, BOUNDS, ALL)
        self.assertEqual(len(grids), 12)
        self.assertLessEqual(sum(g.cols * g.rows for g in grids), hm.MAX_TOTAL_POINTS)
        g = hm.plan_probe(square(100, 100, 100), BOUNDS, ALL)[0]
        pts = [g.point(i) for i in range(len(g.z))]
        self.assertEqual(min(p[0] for p in pts), 103.0)    # 2 mm margin, 5 mm inset
        self.assertEqual(max(p[1] for p in pts), 197.0)
        self.assertEqual(g.order(), [0, 1, 2, 5, 4, 3, 6, 7, 8])

    def test_unreachable_points_are_filled_from_neighbours(self):
        reach = lambda x, y: x < 200
        g = hm.plan_probe(square(100, 100, 200), BOUNDS, reach)[0]
        self.assertEqual((g.cols, g.rows), (4, 4))
        self.assertIn(False, g.reachable)
        g.z = [x * 0.01 if ok else None for (x, _), ok in
               ((g.point(i), g.reachable[i]) for i in range(len(g.z)))]
        filled = g.filled()
        self.assertNotIn(None, filled.z)
        for i, ok in enumerate(g.reachable):
            if not ok:
                self.assertAlmostEqual(filled.z[i], max(v for v in g.z if v is not None), places=6)
        with self.assertRaises(ValueError):
            hm.plan_probe(square(100, 100, 50), BOUNDS, lambda x, y: False)
        # An area the switch cannot reach at all is dropped (highest surface there).
        grids = hm.plan_probe(square(50, 50, 20) + square(300, 300, 20), BOUNDS, reach)
        self.assertEqual([g.region.xmin for g in grids], [48])

    def test_motif_at_the_edge_is_probed_next_to_it(self):
        # Real machine: switch 23 mm towards X-, 15 mm towards Y+. The head reaches
        # X10..380 / Y10..360 while probing (laser off, safezone allowed).
        from marlin.transport import MarlinTransport
        m = MarlinTransport("/dev/null")
        m.probe_xy_offset_mm = (-23.0, 15.0)
        reach = m.probe_reachable
        # Upper edge (small machine Y): head goes into the safezone, now reachable.
        self.assertTrue(reach(200.0, 32.0))
        self.assertFalse(reach(370.0, 200.0))            # head would need X393
        # A motif entirely in the strip the switch never reaches (X > 357):
        g = hm.plan_probe(square(362, 150, 25), BOUNDS, reach)[0]
        self.assertTrue(all(g.reachable), g.as_dict())
        self.assertEqual(g.substituted, len(g.z))
        for i in range(len(g.z)):
            px, py = g.point(i)
            sx, sy = g.probe_point(i)
            self.assertTrue(reach(sx, sy))
            self.assertLessEqual(math.hypot(px - sx, py - sy), hm.SUBSTITUTE_MAX_MM)
            self.assertAlmostEqual(sy, py)               # straight inwards in X
            self.assertGreaterEqual(sx, 356.0)          # as close as possible
        # Reachable points are probed where they are.
        g = hm.plan_probe(square(100, 100, 50), BOUNDS, reach)[0]
        self.assertEqual(g.substituted, 0)
        self.assertEqual([g.probe_point(i) for i in range(len(g.z))],
                         [g.point(i) for i in range(len(g.z))])

    def test_surface_is_bilinear_and_never_too_low_outside(self):
        g = hm.HeightGrid(hm.Box(100, 100, 200, 200), 100, 100, 100, 100, 2, 2,
                          [1.0, 2.0, 3.0, 4.0], [True] * 4)
        maps = hm.HeightMapSet([g])
        self.assertEqual(maps.surface(150, 150), (2.5, True))
        self.assertEqual(maps.surface(100, 200), (3.0, True))
        self.assertEqual(maps.surface(300, 300), (4.0, False))
        self.assertEqual((maps.lowest, maps.highest), (1.0, 4.0))


class CompensationTests(unittest.TestCase):
    def test_flat_focus_split_and_rapid_order(self):
        out, rep = compensate(["G21", "G90", "M3 I", "G0 X50 Y50", "G1 X60 Y50 F1200 S90", "M5 I"],
                              flat(3.0), 7.0, 1.5, start_z=20.0)
        self.assertEqual(out[:6], ["G90", "G21", "M3 I", "G0 X50.000 Y50.000",
                                   "G0 Z8.500 F600", "G1 X52.000 Y50.000 S90 F1200"])
        self.assertEqual(sum(l.startswith("G1") for l in out), 5)
        self.assertEqual(rep.segments, 5)
        self.assertEqual((rep.z_min, rep.z_max), (8.5, 8.5))

    def test_rapid_goes_up_first_over_higher_part(self):
        region_low, region_high = hm.Box(30, 30, 100, 370), hm.Box(200, 30, 390, 370)
        maps = hm.HeightMapSet([
            hm.HeightGrid(region_low, 30, 30, 70, 340, 2, 2, [3.0] * 4, [True] * 4),
            hm.HeightGrid(region_high, 200, 30, 190, 340, 2, 2, [10.0] * 4, [True] * 4)])
        out, _ = compensate(["G0 X50 Y50", "G1 X52 Y50 S10", "G0 X250 Y50",
                             "G1 X252 Y50 S10", "G0 X50 Y60"], maps, 7.0, 1.5, start_z=20.0)
        i = out.index("G0 X250.000 Y50.000")
        self.assertEqual(out[i - 1], "G0 Z15.500 F600")           # up first
        j = out.index("G0 X50.000 Y60.000")
        self.assertEqual(out[j + 1], "G0 Z8.500 F600")            # down at the target

    def test_pass_drop_becomes_offset_and_floor_is_kept(self):
        job = ["G0 X50 Y50", "G1 X52 Y50 F600 S200", "G91", "G0 Z-0.500 F600", "G90",
               "G0 X50 Y50", "G1 X52 Y50 F600 S200", "G91", "G0 Z0.500 F600", "G90",
               "G0 X60 Y60"]
        out, rep = compensate(job, flat(3.0), 7.0, 1.5, start_z=20.0)
        self.assertNotIn("G91", out)
        self.assertEqual(zs(out), [8.5, 8.0, 8.5])
        self.assertEqual(rep.lowest_offset_mm, -0.5)
        with self.assertRaises(ValueError) as ctx:
            compensate(["G0 X50 Y50", "G91", "G0 Z-3.6", "G90", "G1 X52 Y50 S9"],
                       flat(3.0), 7.0, 1.5)
        self.assertIn("Oberfläche + 2 mm", str(ctx.exception))
        with self.assertRaises(ValueError):
            compensate(["G0 X50 Y50"], flat(3.0), 3.0, 1.5)     # focus 1.5 mm above surface

    def test_refuses_what_it_cannot_compensate(self):
        for job, word in ((["G0 X50 Y50", "G2 X60 Y50 I5 J0 S10"], "Bögen"),
                          (["G91", "G1 X5 S10"], "relative"),
                          (["G0 X50 Y50 Z9"], "Z-Werte")):
            with self.subTest(job=job):
                with self.assertRaises(ValueError) as ctx:
                    compensate(job, flat(3.0), 7.0, 1.5)
                self.assertIn(word, str(ctx.exception))
        self.assertTrue(has_absolute_z(["G0 X1 Y1", "G1 X2 Y1 Z9.5 S3"]))
        self.assertFalse(has_absolute_z(["G91", "G0 Z-0.5", "G90", "G1 X2 Y1 S3"]))

    def test_steep_piece_slows_down_and_feed_returns(self):
        g = hm.HeightGrid(hm.Box(50, 50, 52, 60), 50, 50, 2, 10, 2, 2,
                          [3.0, 6.0, 3.0, 6.0], [True] * 4)
        out, rep = compensate(["G0 X50 Y50", "G1 X52 Y50 F6000 S50", "G1 X50 Y50 S50"],
                              hm.HeightMapSet([g]), 7.0, 1.5, start_z=20.0)
        self.assertEqual(rep.feed_limited, 2)
        feeds = [float(l.split("F")[1]) for l in out if l.startswith("G1") and " F" in l]
        self.assertLess(max(feeds), 6000)      # 3 mm Z on 2 mm XY: Z limits the speed

    def test_large_z_jump_before_cut_happens_laser_off_with_power_kept(self):
        out, _ = compensate(["G0 X50 Y50", "G1 X52 Y50 F600 S120", "G91", "G0 Z-2", "G90",
                             "G1 X54 Y50"], flat(3.0), 7.0, 1.5, start_z=20.0)
        i = out.index("G0 Z6.500 F600")
        self.assertEqual(out[i + 1], "G1 X54.000 Y50.000 S120 F600")


SIM = r"""
import re
from marlin import web
from marlin.transport import MarlinTransport

class MarlinSim:
    def __init__(self, surface):
        self.surface = surface
        self.pos = [150.0, 150.0, 40.0]
        self.absolute = True
        self.out = []
        self.writes = []
        self.hook = None          # called with every command (test hooks)
        self.no_contact = False   # G30 finds no material
    def report(self):
        return "X:%.3f Y:%.3f Z:%.3f E:0.00 Count X:0 Y:0 Z:0" % tuple(self.pos)
    def write(self, raw):
        cmd = raw.decode().strip()
        self.writes.append(cmd)
        if self.hook is not None:
            self.hook(cmd)
        words = dict((k, float(v)) for k, v in re.findall(r"([XYZ])([-+]?[0-9.]+)", cmd))
        reply = []
        if cmd == "M115":
            reply += ["FIRMWARE_NAME:Marlin 2.1.2.9 MACHINE_TYPE:LumaCut CNC Marlin", "Cap:Z_PROBE:1"]
        elif cmd == "G28 X Y":
            self.pos[0] = self.pos[1] = 0.0
        elif cmd == "G28 Z":
            self.pos[2] = 0.0
        elif cmd in ("G90", "G91"):
            self.absolute = cmd == "G90"
        elif re.match(r"G[0123] ", cmd):
            for i, axis in enumerate("XYZ"):
                if axis in words:
                    self.pos[i] = words[axis] if self.absolute else self.pos[i] + words[axis]
        elif cmd == "M114":
            reply.append(self.report())
        elif cmd.startswith("G30") and self.no_contact:
            self.pos[2] = -2.0 if self.pos[2] > 1 else self.pos[2]
            reply += ["Error:Probing Failed"]
        elif cmd == "M119":
            reply += ["Reporting endstop status", "z_min: open"]
        elif cmd.startswith("G30"):
            contact = self.surface(self.pos[0] + OFFSET[0], self.pos[1] + OFFSET[1])
            assert contact < self.pos[2] - 0.5, ("switch would already touch", self.pos, contact)
            self.pos[2] = contact
            reply += ["Bed X: %.3f Y: %.3f Z: %.3f" % tuple(self.pos), self.report()]
        self.out += [r + "\n" for r in reply] + ["ok\n"]
        return len(raw)
    def readline(self):
        return self.out.pop(0).encode() if self.out else b""
    def reset_input_buffer(self):
        pass
    def close(self):
        pass

def connect(surface):
    sim = MarlinSim(surface)
    web.machine = m = MarlinTransport("/dev/null", serial_factory=lambda *a, **k: sim)
    m.homing_verified = True
    m.probe_xy_offset_mm = OFFSET
    m.ensure_ready()
    web.machine.homing_verified = True
    return sim, m
"""


class AutorunWebTests(unittest.TestCase):
    def _run(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["LUMACUT_DATA"] = tmp
            env["PYTHONPATH"] = str(ROOT / "pi400")
            result = subprocess.run([sys.executable, "-c", SIM + source], env=env, cwd=ROOT,
                                    text=True, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_autorun_two_areas_unreachable_points_and_status(self):
        # Real offset of the machine: switch 23 mm towards X- and 15 mm towards Y+.
        self._run(r"""
import time
OFFSET = (-23.0, 15.0)
step = lambda x, y: 6.0 if x > 300 else 3.0          # thicker part on the right
sim, m = connect(step)
job = ("G21\nG90\nM5 I\nM3 I\n"
       "G0 X60 Y60\nG1 X160 Y60 F1500 S100\nG1 X160 Y110 S100\nG1 X60 Y110 S100\nG1 X60 Y60 S100\n"
       "G0 X320 Y300\nG1 X380 Y300 F1500 S100\nG1 X380 Y340 S100\nG1 X320 Y340 S100\n"
       "G1 X320 Y300 S100\nM5 I\nM2\n")
(web.JOBS / "Zwei.gcode").write_text(job, encoding="utf-8")
c = web.app.test_client()
seen = []
real_home, real_probe = m.safe_home, m.probe_surface
def home(**k):
    seen.append(dict(web.job))
    return real_home(**k)
def probe(groups, progress=None, **k):
    def report(done, total):
        progress(done, total)
        seen.append(dict(web.job, probe=dict(web.job["probe"])))
    seen.append(dict(web.job, probe=dict(web.job["probe"])))
    return real_probe(groups, progress=report, **k)
m.safe_home, m.probe_surface = home, probe
r = c.post("/api/action", data={"op": "autorun", "name": "Zwei.gcode"})
assert r.status_code == 200, r.data
msg = r.get_json()["message"]
assert msg.startswith("Automatischer Ablauf gestartet: Referenzieren → Abtasten"), msg
for _ in range(3000):
    s = c.get("/api/status").get_json()["job"]
    if s["state"] in ("complete", "error"):
        break
    time.sleep(0.005)
assert s["state"] == "complete", s
assert seen[0]["state"] == "homing" and seen[1]["state"] == "probing", seen[:2]
assert seen[1]["probe"]["done"] == 0 and [x["probe"]["done"] for x in seen[2:]] == list(
    range(1, seen[1]["probe"]["total"] + 1)), seen
w = sim.writes
probes = w.count("G30 E0")
assert s["probe"]["done"] == s["probe"]["total"] == probes, (s["probe"], probes)
# Area 2 (X318..382) lies partly where the head cannot go (X > 380 - 23 = 357):
# those points are filled from their neighbours, the reachable ones are probed.
heads = [c for i, c in enumerate(w) if c.startswith("G0 X") and "G30 E0" in w[i + 1:i + 3]]
assert len(heads) == probes, heads
xs = [float(re.search(r"X([-+0-9.]+)", h).group(1)) for h in heads]
assert max(xs) <= 380.0 and min(xs) >= 30.0, heads
assert any(x - 23.0 > 300 for x in xs), "right area probed too"
# Between areas the head travels at the clearance, inside an area only hops.
i0, i1 = w.index("G30 E0"), w.index("M402")
hop_z = [float(c.split("Z")[1].split()[0]) for c in w[i0:i1] if c.startswith("G0 Z")]
assert 20.0 in hop_z and sorted(set(hop_z)) == [6.0, 9.0, 20.0], hop_z
# The lowest point was probed last: the Z floor is the thin part.
assert m.surface_z == 3.0
# Focus: 3 + 5.5 on the left, 6 + 5.5 on the right.
cut_z = [float(c.split("Z")[1].split()[0]) for c in w[i1:] if c.startswith(("G0 Z", "G1 X")) and "Z" in c]
assert 8.5 in cut_z and 11.5 in cut_z and min(cut_z) >= 5.0, sorted(set(cut_z))
assert w[-1] != "M112" and "M112" not in w
assert "G28 X Y" in w and w.count("G28 X Y") == 1
# Second run: already homed, no homing again; status never shows homing.
sim.writes.clear()
r = c.post("/api/action", data={"op": "autorun", "name": "Zwei.gcode"})
assert r.status_code == 200 and "Referenzieren" not in r.get_json()["message"], r.data
for _ in range(3000):
    s = c.get("/api/status").get_json()["job"]
    if s["state"] in ("complete", "error"):
        break
    time.sleep(0.005)
assert s["state"] == "complete" and "G28 X Y" not in sim.writes, s
""")

    def test_job_with_own_z_is_probed_but_not_compensated_again(self):
        self._run(r"""
OFFSET = (10.0, 5.0)
sim, m = connect(lambda x, y: 3.0)
lines = ["G21", "G90", "M3 I", "G0 X100 Y100", "G0 Z9.000 F600",
         "G1 X120 Y100 Z9.100 F1500 S80", "M5 I"]
auto = web.auto_plan(lines)
assert auto["compensate"] is False and auto["commands"] == lines
web.job_lock.acquire()
m.owner = "job"
web._job_worker("eigen.gcode", auto["commands"], auto)
assert web.job["state"] == "complete", web.job
w = sim.writes
assert "G30 E0" in w and m.surface_z == 3.0
cuts = [c for c in w if c.startswith("G1 X")]
assert cuts == ["G1 X120 Y100 Z9.100 F1500 S80"], cuts
assert "G0 Z8.500 F600" not in w, "no single-surface focus over the job's own Z"
""")

    def test_refusals_before_anything_moves(self):
        self._run(r"""
OFFSET = (10.0, 5.0)
sim, m = connect(lambda x, y: 3.0)
c = web.app.test_client()
(web.JOBS / "Bogen.gcode").write_text("M3 I\nG0 X100 Y100\nG2 X120 Y100 I10 J0 S50\nM5 I\n", encoding="utf-8")
(web.JOBS / "Rand.gcode").write_text("M3 I\nG0 X385 Y40\nG1 X389 Y40 F600 S50\nM5 I\n", encoding="utf-8")
before = len(sim.writes)
r = c.post("/api/action", data={"op": "autorun", "name": "Bogen.gcode"})
assert r.status_code == 400 and "Linien" in r.get_json()["error"], r.data
# Near the edge the switch probes next to the motif (within 40 mm). Only when
# nothing that close is reachable (here: switch 200 mm beside the laser) the
# Pi refuses before anything moves.
m.probe_xy_offset_mm = (-200.0, 0.0)
r = c.post("/api/action", data={"op": "autorun", "name": "Rand.gcode"})
assert r.status_code == 400 and "erreichbar" in r.get_json()["error"], r.data
m.probe_xy_offset_mm = None
r = c.post("/api/action", data={"op": "autorun", "name": "Rand.gcode"})
assert r.status_code == 400 and "Tasterversatz" in r.get_json()["error"], r.data
assert len(sim.writes) == before, sim.writes[before:]
assert web.job["state"] == "idle"
""")

    def test_abort_while_probing_stows_switch_and_parks(self):
        self._run(r"""
OFFSET = (10.0, 5.0)
sim, m = connect(lambda x, y: 3.0)
m.safe_home(owner="web")
lines = ["M3 I", "G0 X100 Y100", "G1 X300 Y100 F1500 S80", "G1 X300 Y300 S80", "M5 I"]
auto = web.auto_plan(lines)
count = {"n": 0}
real = m._probe_here_locked
def probe_then_abort(start_z):
    count["n"] += 1
    if count["n"] == 2:
        web.stop_job.set()
    return real(start_z)
m._probe_here_locked = probe_then_abort
web.job_lock.acquire()
web.stop_job.clear()
m.owner = "job"
web._job_worker("a.gcode", auto["commands"], auto)
assert web.job["state"] == "aborted", web.job
w = sim.writes
assert w.count("G30 E0") == 2 and "M402" in w and "M3 I" not in w, w
assert w.index("M402") < w.index("G0 X0.000 Y0.000 F9000")
assert m.surface_z is None and "M112" not in w
assert web.job["error"] == "Abgebrochen" and web.job["phase"] is None, web.job
assert "M5 I" in w[w.index("M402"):], "laser off after the abort"
""")

    def test_abort_during_homing_stops_in_park_corner_without_m112(self):
        self._run(r"""
OFFSET = (10.0, 5.0)
sim, m = connect(lambda x, y: 3.0)
auto = web.auto_plan(["G0 X100 Y100", "M3 I", "G1 X150 Y100 F1500 S80", "M5 I"])
def hook(cmd):
    if cmd == "G28 X Y":
        web.stop_job.set()
sim.hook = hook
web.job_lock.acquire()
web.stop_job.clear()
m.owner = "job"
web._job_worker("a.gcode", auto["commands"], auto)
w = sim.writes
assert web.job["state"] == "aborted" and web.job["error"] == "Abgebrochen", web.job
assert "G28 Z" not in w and "G30 E0" not in w and "M3 I" not in w, w
assert w[-1] == "M5 I" and "M112" not in w, w
assert sim.pos[:2] == [0.0, 0.0] and not m.homed and m.serial is not None
""")

    def test_abort_during_parking_finishes_park_once(self):
        self._run(r"""
OFFSET = (10.0, 5.0)
sim, m = connect(lambda x, y: 3.0)
auto = web.auto_plan(["G0 X100 Y100", "M3 I", "G1 X104 Y100 F1500 S80", "M5 I"])
phases = []
def hook(cmd):
    phases.append(web.job["phase"])
    if cmd == "G0 X0.000 Y0.000 F9000":
        web.stop_job.set()
sim.hook = hook
web.job_lock.acquire()
web.stop_job.clear()
m.owner = "job"
web._job_worker("a.gcode", auto["commands"], auto)
w = sim.writes
assert web.job["state"] == "aborted" and web.job["error"] == "Abgebrochen", web.job
assert w.count("G0 X0.000 Y0.000 F9000") == 1 and "M112" not in w, w
seen = [p for i, p in enumerate(phases) if i == 0 or p != phases[i - 1]]
# focusing/finishing send nothing to Marlin here (instant), so they may not show.
assert seen == ["homing", "probing", "running", "parking"], seen
""")

    def test_probe_without_material_is_one_sentence_error(self):
        self._run(r"""
OFFSET = (10.0, 5.0)
sim, m = connect(lambda x, y: 3.0)
sim.no_contact = True
auto = web.auto_plan(["G0 X100 Y100", "M3 I", "G1 X150 Y100 F1500 S80", "M5 I"])
web.job_lock.acquire()
web.stop_job.clear()
m.owner = "job"
web._job_worker("a.gcode", auto["commands"], auto)
w = sim.writes
assert web.job["state"] == "error", web.job
err = web.job["error"]
assert err.startswith("Der Taster hat bei X") and "kein Material gefunden" in err, err
assert err.endswith("dann neu starten.") and err.count(".") == 1, err
assert "M402" in w and "M3 I" not in w and "M112" not in w, w
assert "G0 X0.000 Y0.000 F9000" in w[w.index("M402"):], "parked after the error"
""")

    def test_first_cut_needs_a_known_start_point(self):
        self._run(r"""
OFFSET = (10.0, 5.0)
sim, m = connect(lambda x, y: 3.0)
import io
c = web.app.test_client()
NL = chr(10)
bad = NL.join(["G21", "G90", "M3 I", "G1 X150 Y100 F1500 S80", "M5 I"])
r = c.post("/api/upload", data={"file": (io.BytesIO(bad.encode()), "bad.gcode")})
assert r.status_code == 400 and "unbekannten Kopfposition" in r.get_json()["error"], r.data
assert "Zeile 4" in r.get_json()["error"]
for ok in (["M3 I", "G0 X100 Y100", "G1 X150 Y100 S80"],
           ["M3 I", "G1 X100 Y100 S0 F600", "G1 X150 Y100 S80"]):
    web.preflight(NL.join(ok))
web.focus.check_first_cut(["G28", "M3 I", "G1 X150 Y100 S80"])   # G28 = X0/Y0
# G28 of the file is dropped in the automatic run: the head stands elsewhere.
try:
    web.auto_plan(["G28", "M3 I", "G1 X150 Y100 S80"])
except ValueError as exc:
    assert "unbekannten Kopfposition" in str(exc), exc
else:
    raise AssertionError("autorun accepted a cut from an unknown position")
# Relative positioning does not count as a known point.
try:
    web.preflight(NL.join(["G91", "G0 X10 Y10", "G90", "M3 I", "G1 X150 Y100 S80"]))
except ValueError as exc:
    assert "Zeile 5" in str(exc), exc
else:
    raise AssertionError("relative move accepted as start point")
assert sim.writes.count("G28 X Y") == 0
""")

    def test_queue_runs_every_item_automatically(self):
        self._run(r"""
import time
OFFSET = (10.0, 5.0)
sim, m = connect(lambda x, y: 3.0)
c = web.app.test_client()
job = chr(10).join(["M3 I", "G0 X100 Y100", "G1 X104 Y100 F1500 S80",
                     "G91", "G0 Z-0.500 F600", "G90",
                     "G0 X100 Y100", "G1 X104 Y100 F1500 S80", "M5 I"])
(web.JOBS / "A.gcode").write_text(job, encoding="utf-8")
(web.JOBS / "B.gcode").write_text(job.replace("X100", "X200").replace("X104", "X204"), encoding="utf-8")
states = []
sim.hook = lambda cmd: states.append((web.job["file"], web.job["state"]))
assert c.post("/api/action", data={"op": "queue_add", "name": "A.gcode"}).status_code == 200
assert c.post("/api/action", data={"op": "queue_add", "name": "B.gcode"}).status_code == 200
assert not m.homed
r = c.post("/api/action", data={"op": "queue_run"})
assert r.status_code == 200, r.data
for _ in range(3000):
    if not web.job_lock.locked():
        break
    time.sleep(0.005)
q = c.get("/api/status").get_json()["queue"]
assert q["state"] == "complete" and [i["state"] for i in q["items"]] == ["done", "done"], q
w = sim.writes
assert w.count("G28 X Y") == 1, "homing only once, when needed"
assert w.count("M402") == 2, "every item probed"
for name in ("A.gcode", "B.gcode"):
    seq = [s for f, s in states if f == name]
    seen = [s for i, s in enumerate(seq) if i == 0 or s != seq[i - 1]]
    assert seen[-2:] == ["probing", "running"] and "complete" not in seen[:-1], (name, seen)
# Two passes with a 0.5 mm focus drop: compensated, no G91 sent.
assert "G91" not in w[w.index("M402"):], "relative drop became a Z offset"
assert "G0 Z8.500 F600" in w and "G0 Z8.000 F600" in w, [c for c in w if c.startswith("G0 Z")]
assert "M112" not in w
""")


if __name__ == "__main__":
    unittest.main()
