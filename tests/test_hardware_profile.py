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

    def test_workspace_and_direction_controls(self):
        self.assertIn('String cmds[]={"$3="+String(newMask),"$23="+String(newHomeMask),"$$"}',CONTROL)
        self.assertIn('script[0]="$H"',CONTROL)
        self.assertIn('cfg.bounce_buffer_size_px=W*10',CONTROL)
        self.assertIn('LV_DISP_ROT_180',CONTROL)
        self.assertIn('lv_obj_t *areaField=',CONTROL)
        self.assertIn('String jsonMachine()',CONTROL)
        self.assertIn('http.on("/api/machine"',CONTROL)
        self.assertIn('"$130="+String(x,3)',CONTROL)
        self.assertIn('softLimitsEnabled&&workX>0',CONTROL)
        self.assertNotIn('String cmds[]={"$"}',CONTROL)

    def test_coordinated_focus_and_keyboard(self):
        self.assertIn('DEFAULT_STEPPER_IDLE_LOCK_TIME=255',BUILD)
        self.assertIn('DEFAULT_HOMING_SINGLE_AXIS_COMMANDS=1',BUILD)
        self.assertIn('DEFAULT_HOMING_ENABLE=1',BUILD)
        self.assertIn('lv_obj_add_event_cb(field,openKeyboard,LV_EVENT_CLICKED',CONTROL)
        self.assertIn('editOverlay=lv_obj_create(root)',CONTROL)
        self.assertIn('lv_keyboard_set_textarea(keyboard,editInput)',CONTROL)
        self.assertIn('prefs.putFloat("zlift"',CONTROL)
        self.assertIn('prefs.putFloat("focgap"',CONTROL)
        self.assertIn('focusGapMm-tipOffsetMm',CONTROL)
        self.assertIn('postHomePending',CONTROL)
        self.assertIn('script[1]="$1=255"',CONTROL)
        self.assertIn('String cmds[]={"$1=0","$"}',CONTROL)

    def test_single_z_switch_workpiece_reference(self):
        self.assertIn('switch_must_contact_material: true',CONFIG)
        self.assertIn('grbl_g38_probe_supported: false',CONFIG)
        self.assertIn('physical_input: PC2',CONFIG)
        self.assertIn('String cmds[]={"M5","$22=3","$HZ","$1=255"}',CONTROL)
        self.assertIn('cmd=="$H"||cmd=="$HZ"',CONTROL)
        self.assertIn('if(!contactSwitchAtHead)',CONTROL)

    def test_touch_to_go_limits_and_laser_off(self):
        self.assertIn('void areaTap(lv_event_t* e)',CONTROL)
        self.assertIn('if(!machineHomed||!canMotion()||postHomePending)',CONTROL)
        self.assertIn('lv_obj_add_event_cb(areaTouch,areaTap,LV_EVENT_CLICKED',CONTROL)
        self.assertIn('String cmds[]={"M5","G53 G0 X"+String(x,3)',CONTROL)
        self.assertIn('softLimitsEnabled&&workX>0',CONTROL)

if __name__=="__main__":
    unittest.main()
