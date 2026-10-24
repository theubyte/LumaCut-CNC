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
        self.assertIn('script[1]="$H"', CONTROL)
        self.assertIn('script[0]="$22=1"', CONTROL)
        self.assertIn('bool canCommand(){return owner==Owner::None&&idle();}', CONTROL)

    def test_workspace_and_direction_controls(self):
        self.assertIn('String cmds[]={"$3="+String(newMask),"$23="+String(newHomeMask),"$$"}',CONTROL)
        self.assertIn('script[1]="$H"',CONTROL)
        self.assertIn('cfg.bounce_buffer_size_px=W*10',CONTROL)
        self.assertIn('LV_DISP_ROT_180',CONTROL)
        self.assertIn('lv_obj_t *areaField=',CONTROL)
        self.assertIn('String jsonMachine()',CONTROL)
        self.assertIn('http.on("/api/machine"',CONTROL)
        self.assertIn('"$130="+String(x,3)',CONTROL)
        self.assertIn('softLimitsEnabled&&workX>0',CONTROL)
        self.assertNotIn('String cmds[]={"$"}',CONTROL)

    def test_catalog_declared_before_first_call(self):
        # Regression: Arduino/C++ standalone .cpp does not generate prototypes.
        call=CONTROL.index("void updateUi(){")
        decl=CONTROL.index("void refreshCatalog();")
        definition=CONTROL.index("void refreshCatalog(){")
        self.assertLess(decl,call)
        self.assertLess(call,definition)

    def test_black_screen_startup_regression(self):
        config=(ROOT/"firmware/hmi/src/lv_conf.h").read_text(encoding="utf-8")
        self.assertIn("#define LV_MEM_CUSTOM 1",config)
        self.assertIn("MALLOC_CAP_SPIRAM",config)
        self.assertIn("heap_caps_realloc",config)
        self.assertIn('if(!psramFound())',CONTROL)
        touch=CONTROL[CONTROL.index('void touchInit(){'):CONTROL.index('void touchRead(')]
        self.assertIn('if(!expander(LCD_RESET|TP_RESET|BACKLIGHT))',touch)
        self.assertIn('void loop(){\n    if(!uiReady)',CONTROL)
        init=CONTROL[CONTROL.index("void internalInit(){"):CONTROL.index("void setup(){")]
        self.assertLess(init.index('expander(LCD_RESET|TP_RESET|BACKLIGHT)'),
                        init.index('makeUi();'))
        self.assertLess(init.index('makeUi();'),init.index('networkInit();'))
        self.assertIn('lv_label_set_text(boot,"LumaCut Studio',init)

    def test_coordinated_focus_and_keyboard(self):
        self.assertIn('DEFAULT_STEPPER_IDLE_LOCK_TIME=255',BUILD)
        self.assertIn('DEFAULT_HOMING_SINGLE_AXIS_COMMANDS=1',BUILD)
        self.assertIn('DEFAULT_HOMING_ENABLE=1',BUILD)
        self.assertIn('lv_obj_add_event_cb(field,openKeyboard,LV_EVENT_CLICKED',CONTROL)
        self.assertIn('editOverlay=lv_obj_create(lv_layer_top())',CONTROL)
        self.assertIn('lv_keyboard_set_textarea(keyboard,editInput)',CONTROL)
        self.assertIn('prefs.putFloat("zlift"',CONTROL)
        self.assertIn('prefs.putFloat("focgap"',CONTROL)
        self.assertIn('focusGapMm-tipOffsetMm',CONTROL)
        self.assertIn('postHomePending',CONTROL)
        self.assertIn('script[0]="$1=255"',CONTROL)
        self.assertIn("machine.print(", CONTROL)
        self.assertIn("$SLP", CONTROL)
        self.assertIn("String(char(36))+char(36)", CONTROL)

    def test_keyboard_fits_real_800x480_display(self):
        # The editor is deliberately separated from LVGL's scrollable root.
        self.assertIn("void layoutKeyboardDialog()",CONTROL)
        self.assertIn("lv_disp_get_hor_res(disp)",CONTROL)
        self.assertIn("lv_disp_get_ver_res(disp)",CONTROL)
        self.assertIn("lv_obj_set_scrollbar_mode(editOverlay,LV_SCROLLBAR_MODE_OFF)",CONTROL)
        self.assertIn("lv_keyboard_set_popovers(keyboard,false)",CONTROL)
        self.assertIn("lv_obj_get_coords(keyboard,&bounds)",CONTROL)
        # LVGL v8 constructs keyboards at BOTTOM_MID. set_pos alone leaves
        # the anchor at the bottom and shifts the widget off-screen.
        layout=CONTROL[CONTROL.index("void layoutKeyboardDialog()"):CONTROL.index("void openKeyboard(")]
        self.assertIn("lv_obj_align(editOverlay,LV_ALIGN_TOP_LEFT,0,0)",layout)
        self.assertIn("lv_obj_align(keyboard,LV_ALIGN_TOP_LEFT,margin,kbY)",layout)
        self.assertNotIn("lv_obj_set_pos(keyboard,margin,kbY)",layout)
        self.assertLess(layout.index("lv_obj_align(keyboard,LV_ALIGN_TOP_LEFT,margin,kbY)"),
                        layout.index("lv_obj_set_size(keyboard,width,keyboardH)"))
        self.assertIn("bounds.y2>=buttonsY-4",layout)
        self.assertIn("layoutKeyboardDialog();",CONTROL)
        self.assertIn("editSaveButton=btn(editOverlay",CONTROL)
        self.assertIn("editCancelButton=btn(editOverlay",CONTROL)
        self.assertLess(CONTROL.index("lv_keyboard_set_mode(keyboard"),
                        CONTROL.index("    layoutKeyboardDialog();",CONTROL.index("lv_keyboard_set_mode(keyboard")))
        # Expected screen geometry uses >=80px free space underneath
        # every control; the bottom row never approaches the bezel edge.
        h=480
        bottom_safe=max(65,h//6)
        button_h=min(52,max(40,h//8))
        buttons_y=h-bottom_safe-button_h
        kb_y=97
        kb_h=max(90,buttons_y-kb_y-14)
        self.assertEqual(buttons_y,348)
        self.assertEqual(kb_h,237)
        self.assertLessEqual(kb_y+kb_h,buttons_y-14)
        self.assertLess(buttons_y+button_h, h-60)

    def test_grbl_parameter_readback_active(self):
        self.assertIn("line[0]==char(36) && isDigit(line[1])",CONTROL)

    def test_single_z_switch_workpiece_reference(self):
        self.assertIn('switch_must_contact_material: true',CONFIG)
        self.assertIn('grbl_g38_probe_supported: false',CONFIG)
        self.assertIn('physical_input: PC2',CONFIG)
        self.assertIn('String cmds[]={"M5","$22=3","$1=255","$HZ"}',CONTROL)
        self.assertIn('cmd=="$H"||cmd=="$HZ"',CONTROL)
        self.assertIn('if(!contactSwitchAtHead)',CONTROL)

    def test_settings_editor_keeps_unsaved_values(self):
        self.assertIn("bool travelInputsDirty=false",CONTROL)
        self.assertIn("if(travelInputsDirty)return;",CONTROL)
        self.assertIn("travelInputsDirty=true;",CONTROL)
        self.assertIn("ConfigWrite::Travel",CONTROL)
        self.assertIn("fabsf(savedSetting[key]-travelRequested[i])>0.01f",CONTROL)
        self.assertIn('SKR bestaetigt alle drei Verfahrwege',CONTROL)
        self.assertIn('SKR hat Einstellung ABGELEHNT',CONTROL)
        self.assertIn('SKR bestaetigt $1=255',CONTROL)

    def test_positive_operator_coordinates_and_exact_seven_mm_target(self):
        self.assertIn('float operatorPos(float machinePos)',CONTROL)
        self.assertIn('machineZeroAtMax?-machinePos:machinePos',CONTROL)
        self.assertIn('display_x_mm',CONTROL)
        self.assertIn('display_y_mm',CONTROL)
        self.assertIn('display_z_mm',CONTROL)
        self.assertIn('String(operatorPos(mx),2)',CONTROL)
        self.assertIn('String(operatorPos(my),2)',CONTROL)
        self.assertIn('String(operatorPos(mz),2)',CONTROL)
        self.assertIn('bool zLift(float targetOperatorMm)',CONTROL)
        self.assertIn('const float machineTarget=machinePosFromOperator(targetOperatorMm)',CONTROL)
        self.assertIn('const float rawDelta=machineTarget-mz',CONTROL)
        self.assertIn('zJogRawDelta(rawDelta)',CONTROL)
        self.assertIn('Auto-Z auf ',CONTROL)
        self.assertNotIn('if(!softLimitsEnabled){zLiftReason=',CONTROL)
        # Example: after 1 mm homing pull-off, target +7 mm is -6 raw.
        machine_pos=-1.0
        display=lambda pos:-pos
        machine_target=lambda val:-val
        self.assertEqual(display(machine_pos),1.0)
        self.assertEqual(machine_target(7.0)-machine_pos,-6.0)
        self.assertEqual(display(machine_pos-6.0),7.0)

    def test_post_home_z_diagnostics_and_guard(self):
        self.assertIn('bool canZMotion()',CONTROL)
        self.assertIn('startScript(cmds,2,true,true)',CONTROL)
        self.assertNotIn('Z-Lift wartet auf MPos, Z-Weg und Soft Limits.',CONTROL)
        self.assertIn('postHomePending=false; // Never show an endless waiting notice',CONTROL)
        self.assertIn('const float rawDelta=machineTarget-mz',CONTROL)
        self.assertIn('const float requested=postContactLift?',CONTROL)
        self.assertNotIn('if(!zLiftDirectionVerified){\n                zLiftReason=',CONTROL)
        self.assertNotIn('if(op=="ztest")',CONTROL)
        self.assertNotIn('if(op=="zverify")',CONTROL)
        self.assertNotIn('btn(c,"Z-Test 0,5 mm"',CONTROL)
        self.assertNotIn('btn(c,"Z-Richtung OK"',CONTROL)
        self.assertIn('autoZlift',CONTROL)
        self.assertIn('GRBL $1:',CONTROL)

    def test_homed_bounded_jog_without_soft_limits_extra_workflow(self):
        self.assertIn("bool canJog(){return canCommand()&&machineHomed&&haveMpos&&",CONTROL)
        self.assertIn("!motorsReleased&&workX>0&&workY>0&&workZ>0;",CONTROL)
        self.assertIn("if(!canJog()){",CONTROL)
        self.assertIn("const float dist=machinePosFromOperator(operatorDistance);",CONTROL)
        self.assertIn("int jogStep=1;",CONTROL)
        self.assertIn('if(op=="jogsound")',CONTROL)
        self.assertIn("const float speed=savedSetting[speedId]*float(jogSpeedPercent)/100.f;",CONTROL)
        self.assertIn('jogSpeedPercent=prefs.getInt("jogPct",100)',CONTROL)
        self.assertIn("const int speedId=axis=='X'?110:",CONTROL)
        self.assertIn('DEFAULT_X_MAX_RATE=6000.0f',BUILD)
        self.assertIn('DEFAULT_Y_MAX_RATE=6000.0f',BUILD)
        # G0/laser work stays gated by controller soft limits.
        self.assertIn("bool canMotion(){return canCommand()&&machineHomed&&haveMpos&&",CONTROL)
        self.assertIn("!motorsReleased&&softLimitsEnabled&&workX>0",CONTROL)

    def test_steps_per_mm_calibration_and_20mm_pre_xy_homing(self):
        self.assertIn('DEFAULT_X_STEPS_PER_MM=80.0f',BUILD)
        self.assertIn('DEFAULT_Y_STEPS_PER_MM=80.0f',BUILD)
        self.assertNotIn('DEFAULT_Z_STEPS_PER_MM=',BUILD)
        self.assertIn('LUMACUT_SAFE_Z20=1',BUILD)
        self.assertIn('limits_lumacut_z_clearance',BUILD)
        self.assertIn('settings.homing.pulloff - 2.5f',BUILD)
        self.assertIn('if(idx == 0 && cycle.mask == bit(Z_AXIS))',BUILD)
        self.assertIn('if(op=="safez20")',CONTROL)
        self.assertIn('if(!zScaleMeasured||workZ<21.f',CONTROL)
        self.assertIn('String cmds[]={"$27=2.5",String(char(36))+char(36)};',CONTROL)
        self.assertIn("const float corrected=savedSetting[id]*commanded/actual;",CONTROL)
        self.assertIn("pendingCalibrationAxis=axis;",CONTROL)
        self.assertIn('prefs.putBool("zScaleOK",matching)',CONTROL)
        self.assertIn('btn(c,"Wege kalibrieren"',CONTROL)
        self.assertIn('btn(c,"Z20 aktivieren"',CONTROL)

    def test_inline_settings_have_value_and_per_row_confirmation(self):
        self.assertIn('lv_obj_t* catalogFields[6]',CONTROL)
        self.assertIn('catalogNamesLabel[i]=lbl(stripe',CONTROL)
        self.assertIn('catalogFields[i]=configEntry(stripe',CONTROL)
        self.assertIn('btn(stripe,LV_SYMBOL_OK',CONTROL)
        self.assertIn('if(op.startsWith("catsave")',CONTROL)
        self.assertIn('if(catalogPendingSlot>=0&&catalogPendingSlot<6)',CONTROL)
        self.assertIn('if(editTarget==catalogFields[i])catalogDirty[i]=true;',CONTROL)

    def test_offset_raster_plan_is_explicitly_not_a_probe_reading(self):
        self.assertIn('#include "probe_grid.h"',CONTROL)
        self.assertIn('LumaProbe::clip(probeRegion,workX,workY,0.5f,plan)',CONTROL)
        self.assertIn('LumaProbe::point(probeRegion,plan,n,sx,sy,lx,ly)',CONTROL)
        self.assertIn('prefs.putFloat("prOX"',CONTROL)
        self.assertIn('prefs.putFloat("prOY"',CONTROL)
        self.assertIn('"/logs/probe_plan.csv"',CONTROL)
        self.assertIn('http.on("/api/probe-plan",HTTP_GET',CONTROL)
        portal=(ROOT/"firmware"/"hmi"/"src"/"mobile_portal.h").read_text(encoding="utf-8")
        self.assertIn("downloadProbePlan()",portal)
        self.assertIn("X-LumaCut-Key",portal)
        self.assertIn('PC14-G38-Abtastung nicht vorhanden.',CONTROL)
        self.assertIn('LumaProbe::Region candidate{',CONTROL)

    def test_serial_timeout_unblocks_configuration(self):
        self.assertIn('scriptCommandStartedMs=millis()',CONTROL)
        self.assertIn('ConfigWrite timedOut=configWrite',CONTROL)
        self.assertIn('!homingInProgress&&',CONTROL)

    def test_touch_to_go_limits_and_laser_off(self):
        self.assertIn('void areaTap(lv_event_t* e)',CONTROL)
        self.assertIn('if(!machineHomed||!canMotion()||postHomePending)',CONTROL)
        self.assertIn('lv_obj_add_event_cb(areaTouch,areaTap,LV_EVENT_CLICKED',CONTROL)
        self.assertIn('String cmds[]={"M5","G53 G0 X"+String(x,3)',CONTROL)
        self.assertIn('softLimitsEnabled&&workX>0',CONTROL)

if __name__=="__main__":
    unittest.main()
