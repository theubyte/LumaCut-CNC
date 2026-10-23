"""Regression guards for the user's actual 3-endstop / 3-stepper machine.

These assertions verify source configuration, not electrical function or safe
physical behaviour. Real hardware commissioning remains mandatory.
"""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
BUILD=(ROOT/"firmware"/"skr"/"build.py").read_text(encoding="utf-8")
CONTROL=(ROOT/"firmware"/"hmi"/"src"/"pro_main.cpp").read_text(encoding="utf-8")
CONFIG=(ROOT/"config"/"laser.yaml").read_text(encoding="utf-8")

class HardwareProfileTests(unittest.TestCase):
    def test_three_single_motor_axes(self):
        self.assertIn("  -D PROBE_ENABLE=0", BUILD)
        self.assertNotIn('h.write("  -D Y_GANGED=1', BUILD)
        self.assertIn("extruder_driver_used: false", CONFIG)
        for axis in "xyz":
            self.assertIn(f"{axis}: {{count: 1,", CONFIG)

    def test_one_physical_z_switch(self):
        self.assertIn("shared_z_switch_count: 1", CONFIG)
        self.assertIn("total_axis_endstop_count: 3", CONFIG)
        self.assertIn("physical_signal_pin: PC2", CONFIG)
        self.assertIn("pc14_probe_input_wired: false", CONFIG)
        self.assertIn("probing_enabled_in_firmware: false", CONFIG)
        self.assertIn("x_switch_present: true", CONFIG)
        self.assertIn("x_endstop_pin: PC0", CONFIG)
        self.assertIn("y_switch_present: true", CONFIG)
        self.assertIn("y_endstop_pin: PC1", CONFIG)

    def test_regular_xyz_homing_reenabled(self):
        self.assertIn('if(op=="home"){', CONTROL)
        self.assertIn('script[0]="$H"', CONTROL)
        self.assertIn('script[0]="$22=1"', CONTROL)
        self.assertIn('bool canCommand(){return owner==Owner::None&&idle();}', CONTROL)

if __name__=="__main__":
    unittest.main()
