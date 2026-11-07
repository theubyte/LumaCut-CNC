"""The optimizer may change the order, never what is lasered (pi400/marlin/job_optimizer.py)."""
import math
import pathlib
import sys
import types
import unittest
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi400"))
if "marlin" not in sys.modules:
    pkg = types.ModuleType("marlin")
    pkg.__path__ = [str(ROOT / "pi400" / "marlin")]
    sys.modules["marlin"] = pkg
from marlin import focus_compensation as focus  # noqa: E402
from marlin import job_optimizer as opt  # noqa: E402


def head():
    return ["; LumaCut App 1.0.57 \u2013 Test", "G21", "G90", "M5 I", "M3 I"]


def tail():
    return ["M5 I", "M400"]


def row(y, runs, forward, f=5000, s=66, over=2.6):
    """A row like the app writes it: run-up, burns, gaps at burn speed, run-out."""
    runs = runs if forward else [(b, a) for a, b in reversed(runs)]
    d = 1 if forward else -1
    out = ["G0 X%.3f Y%.3f" % (runs[0][0] - d * over, y), "G1 X%.3f Y%.3f F%d S0" % (runs[0][0], y, f)]
    at = runs[0][0]
    for a, b in runs:
        if abs(a - at) > 1e-9:
            out.append("G1 X%.3f Y%.3f F%d S0" % (a, y, f))
        out.append("G1 X%.3f Y%.3f F%d S%d" % (b, y, f, s))
        at = b
    out.append("G1 X%.3f Y%.3f F%d S0" % (at + d * over, y, f))
    return out


def two_islands(rows=120, pitch=0.1, left=(40, 60), right=(200, 220)):
    lines = head() + ["; Ebene Gravieren"]
    for r in range(rows):
        lines += row(50 + r * pitch, [left, right], r % 2 == 0)
    return lines + tail()


class Flat:
    def __init__(self, z=3.0, slope=0.0):
        self.z, self.slope = z, slope

    def surface(self, x, y):
        return self.z + self.slope * x, True


class OptimizerTests(unittest.TestCase):
    def run_opt(self, lines, budget=0.3):
        return opt.optimize(lines, opt.Motion(2100.0, 150.0), budget_s=budget)

    def test_parts_are_finished_one_after_the_other_and_it_is_faster(self):
        lines = two_islands()
        out, rep = self.run_opt(lines)
        self.assertTrue(rep["applied"], rep)
        self.assertLess(rep["after_s"], rep["before_s"] * 0.7)
        xs = [float(l.split("X")[1].split()[0]) for l in out if l.startswith("G1") and " S66" in l]
        # the head changes sides once, not on every row
        changes = sum(1 for a, b in zip(xs, xs[1:]) if (a < 100) != (b < 100))
        self.assertEqual(changes, 1)

    def test_every_burn_survives_with_power_and_speed(self):
        lines = two_islands()
        out, rep = self.run_opt(lines)
        self.assertTrue(rep["applied"])
        self.assertEqual(opt._burn_set(lines), opt._burn_set(out))

    def test_cuts_stay_last_and_in_their_order(self):
        lines = head() + ["; Ebene Schneiden", "G0 X10 Y10", "G1 X20 Y10 F400 S217", "G0 X30 Y10", "G1 X40 Y10 F400 S217",
                          "; Ebene Gravieren"]
        for r in range(40):
            lines += row(50 + r * 0.1, [(40, 60), (200, 220)], r % 2 == 0)
        lines += ["; Ebene Linie", "G0 X100 Y100", "G1 X110 Y100 F1500 S102"] + tail()
        out, rep = self.run_opt(lines)
        self.assertTrue(rep["applied"], rep)
        first_cut = out.index("G1 X20 Y10 F400 S217")
        self.assertLess(first_cut, out.index("G1 X40 Y10 F400 S217"))
        self.assertTrue(all("S0" in l or "S217" in l for l in out[first_cut:] if l.startswith("G1")))
        self.assertFalse(any(" S66" in l or " S102" in l for l in out[first_cut:]))

    def test_strong_line_under_another_name_counts_as_a_cut(self):
        lines = head() + ["; Ebene Rot", "G0 X10 Y10", "G1 X20 Y10 F300 S255", "; Ebene Gravieren"]
        for r in range(40):
            lines += row(50 + r * 0.1, [(40, 60), (200, 220)], r % 2 == 0)
        lines += tail()
        out, _ = self.run_opt(lines)
        self.assertGreater(out.index("G1 X20 Y10 F300 S255"), max(i for i, l in enumerate(out) if " S66" in l))

    def test_passes_keep_their_focus_steps(self):
        cut = ["; Ebene Schneiden", "; Durchgang 1/2", "G0 X10 Y10", "G1 X20 Y10 F400 S217", "G91", "G0 Z-0.500 F600", "G90",
               "; Durchgang 2/2", "G0 X10 Y10", "G1 X20 Y10 F400 S217", "G91", "G0 Z0.500 F600", "G90"]
        lines = head() + cut + ["; Ebene Gravieren"]
        for r in range(40):
            lines += row(50 + r * 0.1, [(40, 60), (200, 220)], r % 2 == 0)
        lines += tail()
        out, rep = self.run_opt(lines)
        self.assertTrue(rep["applied"], rep)
        i = out.index("G91")
        self.assertEqual(out[i:i + 3], ["G91", "G0 Z-0.500 F600", "G90"])
        self.assertEqual(Counter(out)["G1 X20 Y10 F400 S217"], 2)
        self.assertLess(max(k for k, l in enumerate(out) if " S66" in l), out.index("G1 X20 Y10 F400 S217"))

    def test_rows_of_a_strip_run_towards_plus_y(self):
        out, _ = self.run_opt(two_islands())
        last = {}
        for l in out:
            if l.startswith("G1") and " S66" in l:
                x = float(l.split("X")[1].split()[0])
                y = float(l.split("Y")[1].split()[0])
                side = x < 100
                if side in last:
                    self.assertGreaterEqual(y, last[side] - 1e-9)
                last[side] = y

    def test_a_strip_is_approached_from_below(self):
        rows = [opt.Stroke([(38.0, 50.0 + k), (40.0, 50.0 + k), (60.0, 50.0 + k), (62.0, 50.0 + k)],
                           [(5000.0, 0.0), (5000.0, 66.0), (5000.0, 0.0)]) for k in range(2)]
        out = []
        opt._emit_group([0], [0], [opt._strip_block(rows)], (50.0, 90.0), out)
        self.assertEqual(out[0], "G0 X38.000 Y49.000")
        self.assertEqual(out[1], "G0 X38.000 Y50.000")
        out = []
        opt._emit_group([0], [0], [opt._strip_block(rows)], (50.0, 10.0), out)
        self.assertEqual(out[0], "G0 X38.000 Y50.000")

    def test_closed_lines_start_where_the_head_is(self):
        square = ["G0 X100 Y100", "G1 X110 Y100 F1500 S80", "G1 X110 Y110 F1500 S80", "G1 X100 Y110 F1500 S80", "G1 X100 Y100 F1500 S80"]
        lines = head() + ["; Ebene Linie"] + ["G0 X10 Y10", "G1 X115 Y115 F1500 S80"] + square + tail()
        out, rep = opt.optimize(lines, opt.Motion(2100, 150), budget_s=0.1)
        self.assertEqual(opt._burn_set(lines), opt._burn_set(out))

    def test_other_files_are_not_touched(self):
        lines = ["G21", "G0 X1 Y1", "G1 X2 Y2 F100 S10"]
        out, rep = self.run_opt(lines)
        self.assertEqual(out, lines)
        self.assertFalse(rep["applied"])
        capture = head() + ["; Ebene A", "G0 X1 Y1", "; LUMACUT-CAPTURE id=a w=10 h=10", "G1 X2 Y2 F100 S10"] + tail()
        self.assertEqual(self.run_opt(capture)[0], capture)

    def test_unknown_lines_leave_the_file_as_it_is(self):
        for line in ("G2 X1 Y1 I1 J0", "G0 X1 Y1 Z5", "M8", "G1 X5 Y5 Z2 S10 F100"):
            lines = head() + ["; Ebene A", "G0 X0 Y0", line] + tail()
            out, rep = self.run_opt(lines)
            self.assertEqual(out, lines, line)
            self.assertFalse(rep["applied"])

    def test_a_job_that_cannot_get_faster_stays(self):
        lines = head() + ["; Ebene A", "G0 X0 Y0", "G1 X10 Y0 F1500 S80"] + tail()
        out, rep = opt.optimize(lines, opt.Motion(2100, 150), budget_s=0.05)
        self.assertEqual(opt._burn_set(lines), opt._burn_set(out))

    def test_the_budget_holds(self):
        import time
        lines = head() + ["; Ebene Linie"]
        for k in range(400):
            x, y = (k * 37) % 300 + 5, (k * 53) % 200 + 5
            lines += ["G0 X%d Y%d" % (x, y), "G1 X%d Y%d F1500 S80" % (x + 3, y)]
        lines += tail()
        t = time.monotonic()
        out, rep = opt.optimize(lines, opt.Motion(2100, 150), budget_s=0.5)
        self.assertLess(time.monotonic() - t, 3.0)
        self.assertLess(rep["after_s"], rep["before_s"])

    def test_abort_while_planning(self):
        with self.assertRaises(RuntimeError):
            opt.optimize(two_islands(), opt.Motion(2100, 150), budget_s=0.2, should_stop=lambda: True)


class FocusKeepsTheRasterTests(unittest.TestCase):
    """06.11.: Z gathered into one pixel slowed the head to F359 at F3000, about 8 x the energy, in dark spots."""

    def test_a_tilted_surface_never_slows_a_burning_row(self):
        lines = ["G0 X0 Y50", "M3 I"]
        x = 0.0
        for k in range(600):
            lines.append("G1 X%.1f Y50 F3000 S%d" % (x + 0.1, 64 if k % 2 else 0))
            x += 0.1
        out, rep = focus.compensate(lines, Flat(3.0, 0.01), 10.0, 2.0, start_z=11.0)
        self.assertEqual(rep.feed_limited, 0)
        self.assertFalse([l for l in out if l.startswith("G1") and " F" in l and "F3000" not in l])

    def test_where_z_cannot_follow_the_feed_counts_the_3d_path(self):
        class Step:
            def surface(self, x, y):
                return (3.0 if x < 0.5 else 3.5), True
        out, rep = focus.compensate(["G0 X0 Y50", "M3 I", "G1 X1 Y50 F3000 S200"], Step(), 10.0, 2.0, start_z=11.0)
        self.assertEqual(rep.feed_limited, 1)
        line = next(l for l in out if l.startswith("G1") and "Z" in l)
        feed = float(line.split("F")[1])
        self.assertAlmostEqual(feed, math.hypot(1.0, 0.5) / (0.5 / 9.0) * 60.0, delta=0.5)

    def test_no_lift_when_no_travel_height_is_given(self):
        lines = ["G0 X0 Y50", "M3 I", "G1 X1 Y50 F5000 S66", "G0 X200 Y50", "G1 X201 Y50 F5000 S66"]
        out, rep = focus.compensate(lines, Flat(), 10.0, 2.0, start_z=11.0, travel_z=None)
        self.assertEqual(rep.travel_lifts, 0)

    def test_estimate_counts_the_lifts(self):
        m = opt.Motion(2100, 150)
        flat = ["G0 X0 Y0 Z8", "G0 X200 Y0"]
        lifted = ["G0 X0 Y0 Z8", "G0 Z23 F600", "G0 X200 Y0", "G0 Z8 F600"]
        self.assertGreater(opt.estimate_seconds(lifted, m), opt.estimate_seconds(flat, m) + 2.5)


if __name__ == "__main__":
    unittest.main()
