"""Forward and backward raster rows land in the same place; nothing else moves (pi400/marlin/scan_offset.py)."""
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi400"))
if "marlin" not in sys.modules:
    pkg = types.ModuleType("marlin")
    pkg.__path__ = [str(ROOT / "pi400" / "marlin")]
    sys.modules["marlin"] = pkg
from marlin import scan_offset as so  # noqa: E402

TABLE = [(1000.0, -0.4), (3000.0, -0.6)]
FORWARD = ["G0 X97.500 Y50.000", "G1 X100.000 Y50.000 F3000 S0", "G1 X110.000 Y50.000 F3000 S64", "G1 X112.500 Y50.000 F3000 S0"]
BACK = ["G0 X112.500 Y50.100", "G1 X110.000 Y50.100 F3000 S0", "G1 X100.000 Y50.100 F3000 S64", "G1 X97.500 Y50.100 F3000 S0"]


class ScanOffsetTests(unittest.TestCase):
    def test_both_directions_move_half_against_the_error(self):
        out, n = so.apply(FORWARD + BACK, TABLE, 370.0)
        self.assertEqual(n, 2)
        self.assertEqual(out[0], "G0 X97.800 Y50.000")
        self.assertEqual(out[2], "G1 X110.300 Y50.000 F3000 S64")
        self.assertEqual(out[4], "G0 X112.200 Y50.100")
        self.assertEqual(out[6], "G1 X99.700 Y50.100 F3000 S64")

    def test_measured_error_is_gone_afterwards(self):
        out, _ = so.apply(FORWARD + BACK, TABLE, 370.0)
        # the machine burns a forward row 0.6 mm below a backward row: +0.3 / -0.3 around the command
        burned_forward_end = 110.3 - 0.3
        burned_back_start = 110.0 - 0.3 + 0.3
        self.assertAlmostEqual(burned_forward_end, burned_back_start)

    def test_interpolates_and_never_extrapolates(self):
        self.assertAlmostEqual(so.offset_at(TABLE, 2000), -0.5)
        self.assertAlmostEqual(so.offset_at(TABLE, 500), -0.4)
        self.assertAlmostEqual(so.offset_at(TABLE, 9000), -0.6)

    def test_vector_lines_and_everything_else_stay(self):
        lines = ["G21", "G90", "M3 I", "G0 X10 Y10", "G1 X20 Y10 F1500 S100", "G1 X20 Y20 F1500 S100", "G0 X30 Y30", "G1 X40 Y30 F1500 S100", "M5 I"]
        self.assertEqual(so.apply(lines, TABLE, 370.0), (lines, 0))

    def test_no_table_and_opted_out_jobs_stay(self):
        self.assertEqual(so.apply(FORWARD, None, 370.0), (FORWARD, 0))
        job = ["; " + so.NO_SCAN_OFFSET] + FORWARD
        self.assertEqual(so.apply(job, TABLE, 370.0), (job, 0))

    def test_runup_at_the_edge_is_clamped_a_burn_is_refused(self):
        out, _ = so.apply(["G0 X369.900 Y50", "G1 X369.950 Y50 F3000 S0", "G1 X300 Y50 F3000 S64"], [(3000.0, 0.6)], 370.0)
        self.assertEqual(out[0], "G0 X370.000 Y50")
        with self.assertRaisesRegex(ValueError, "Rand"):
            so.apply(["G0 X10 Y50", "G1 X11 Y50 F3000 S0", "G1 X369.900 Y50 F3000 S64", "G1 X370 Y50 F3000 S0"], TABLE, 370.0)

    def test_table_text(self):
        self.assertEqual(so.parse_table("3000:-0.64, 1000:-0.44"), [(1000.0, -0.44), (3000.0, -0.64)])
        self.assertIsNone(so.parse_table(" "))
        for bad in ("1000:-3", "0:0.1", "1000:0.1,1000:0.2"):
            with self.assertRaises(ValueError):
                so.parse_table(bad)


if __name__ == "__main__":
    unittest.main()
