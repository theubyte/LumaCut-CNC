"""Smart CAM geometry regression tests, without motors/laser."""
import unittest
from marlin.smart_cam import analyze_job

class SmartCAMTests(unittest.TestCase):
    def test_lightburn_rectangle_bounds_exclude_rapid(self):
        source = """G21
G90
G0 X50 Y60 F9000
M3 I
G1 X90 Y60 S80 F1500
G1 X90 Y100
G1 X50 Y100
G1 X50 Y60
M5 I
M2
"""
        b=analyze_job(source)
        self.assertEqual((b.xmin,b.ymin,b.xmax,b.ymax),(50,60,90,100))
        self.assertEqual(b.center,(70,80))
        self.assertEqual(b.segments,4)
        self.assertTrue(b.probe_grid())

    def test_relative_coordinates(self):
        b=analyze_job("G90\nG0 X45 Y45\nM3 I\nG91\nG1 X20 S60\nG1 Y10\n")
        self.assertEqual((b.xmin,b.ymin,b.xmax,b.ymax),(45,45,65,55))

    def test_arcs_not_silently_misparsed(self):
        with self.assertRaisesRegex(ValueError,"arc"):
            analyze_job("G0 X50 Y50\nG2 X70 Y70 I10 J0 S70")

    def test_blank_job_rejected(self):
        with self.assertRaisesRegex(ValueError,"No powered"):
            analyze_job("G90\nG0 X120 Y120\nM2")

    def test_sampling_cap(self):
        b=analyze_job("G0 X30 Y30\nG1 X390 Y370 S60")
        with self.assertRaisesRegex(ValueError,"Too many"):
            b.probe_grid(spacing=5)

if __name__=="__main__":
    unittest.main()
