"""Modal GRBL job preflight and geometry regressions (no real motion)."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"pi400"))
from lumacut.planner import analyze_text


class MotionPlannerTests(unittest.TestCase):
    def test_absolute_rectangle_and_rapid_moves(self):
        program=analyze_text("""G90 G21
G0 X10 Y20
M3 S500
G1 X40 Y20 F1000
Y50
X10
Y20
M5
""")
        self.assertEqual(program.errors,[])
        self.assertEqual(program.bounds,(0,0,40,50))
        self.assertEqual(program.estimated_segments,5)
        self.assertEqual(program.segments[0][-1],1)
        self.assertEqual(program.segments[-1][-1],0)

    def test_relative_and_inches_are_converted_by_pi(self):
        program=analyze_text("G21 G90 G0 X0 Y0\nG91 G20\nG1 X1 Y2\nX-0.5\n")
        self.assertEqual(program.errors,[])
        self.assertEqual(program.bounds,(0,0,25.4,50.8))

    def test_arc_quarter_circle_and_full_circle(self):
        arc=analyze_text("G90 G21 G0 X10 Y0\nG3 X0 Y10 I-10 J0")
        self.assertEqual(arc.errors,[])
        self.assertGreater(len(arc.segments),3)
        self.assertAlmostEqual(arc.bounds[2],10,delta=.1)
        self.assertAlmostEqual(arc.bounds[3],10,delta=.1)
        full=analyze_text("G90 G21 G0 X10 Y0\nG2 I-10 J0")
        self.assertEqual(full.errors,[])
        self.assertAlmostEqual(full.bounds[0],-10,delta=.5)
        self.assertAlmostEqual(full.bounds[3],10,delta=.5)

    def test_r_arc_and_inconsistent_center_rejected(self):
        p=analyze_text("G90 G21 G0 X0 Y0\nG3 X10 Y0 R5")
        self.assertFalse(p.errors)
        self.assertAlmostEqual(p.bounds[2],10,delta=.1)
        bad=analyze_text("G90 G21 G0 X10 Y0\nG3 X0 Y20 I-10 J0")
        self.assertTrue(bad.errors)
        self.assertIsNone(bad.bounds)

    def test_unsafe_transformation_and_absolute_machine_moves_not_framed(self):
        for source in ("G91 G21 G1 X10\nG92 X0",
                       "G90 G21 G51 X2",
                       "G90 G53 G0 X20",
                       "G90 G21 G3 X40 Y50",
                       "$LCIO=1",
                       "G90 G21 G1 X[10+2]"):
            with self.subTest(source=source):
                out=analyze_text(source)
                self.assertTrue(out.errors)
                self.assertIsNone(out.bounds)

    def test_geometry_is_deterministic(self):
        source="G21\nG90\nG0 X1 Y1\nG1 X2 Y2\n"
        self.assertEqual(analyze_text(source).as_dict(),analyze_text(source).as_dict())


if __name__=="__main__":
    unittest.main()
