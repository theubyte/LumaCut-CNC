"""Cross-component checks for the integrated LightBurn/Web/QR machine workflow."""
from pathlib import Path
import json
import unittest

ROOT=Path(__file__).resolve().parents[1]
HMI=(ROOT/"firmware/hmi/src/pro_main.cpp").read_text(encoding="utf-8")
SKR=(ROOT/"firmware/skr/build.py").read_text(encoding="utf-8")
WEB=(ROOT/"firmware/hmi/src/mobile_portal.h").read_text(encoding="utf-8")


class ControlStudioTests(unittest.TestCase):
    def test_lbdev_real_device_list_schema(self):
        profile=json.loads((ROOT/"lightburn/LumaCut-CNC-USB.lbdev").read_text(encoding="utf-8"))
        self.assertEqual(len(profile["DeviceList"]),1)
        device=profile["DeviceList"][0]
        self.assertEqual(device["Name"],"GRBL")
        self.assertEqual(device["Type"],"Serial")
        self.assertGreater(device["Width"],0)
        self.assertGreater(device["Height"],0)
        self.assertEqual(device["Settings"]["SValueMax"],1000)
        self.assertEqual(device["Settings"]["TransferMode"],0)

    def test_bed_profile_precharge_and_aftercool(self):
        profile=json.loads((ROOT/"lightburn/LumaCut-CNC-USB.lbdev").read_text(encoding="utf-8"))
        conf=profile["DeviceList"][0]["Settings"]
        self.assertTrue(conf["StartGCode"].endswith("M4 S0\nG4 P2"))
        self.assertEqual(conf["EndGCode"],"M4 S0\nG4 P30\nM5\nM9")
        self.assertIn('settings["StartGCode"]=',HMI)
        self.assertIn('settings["EndGCode"]=',HMI)

    def test_timed_lightburn_restriction_removed(self):
        self.assertIn('wifiLightburnEnabled=prefs.getBool("lbTcp",true)',HMI)
        self.assertIn('wifiLightburnEnabled=!wifiLightburnEnabled;',HMI)
        self.assertIn('tcp.setNoDelay(true)',HMI)
        self.assertIn('owner=Owner::Tcp;lastInputMs=millis();',HMI)
        self.assertNotIn('!wifiHostAuthorized()||owner!=Owner::None',HMI)
        self.assertIn('if(owner==Owner::Tcp&&(!tcp||!tcp.connected()))',HMI)
        self.assertIn('if(machineState==MachineState::Run)feedHold()',HMI)

    def test_z_clearance_is_pre_xy_and_no_late_macro(self):
        self.assertIn('if(idx == 0 && cycle.mask == bit(Z_AXIS))',SKR)
        self.assertIn('limits_lumacut_z_clearance()',SKR)
        self.assertIn('settings.axis[Z_AXIS].max_travel > -21.0f',SKR)
        self.assertNotIn('settings.homing.pulloff - 2.5f',SKR)
        self.assertIn('postHomePending=postContactLift&&autoLiftAfterHome;',HMI)
        self.assertIn('Homing OK: SKR hat Z vor XY auf 20 mm freigefahren.',HMI)
        self.assertNotIn('if(op=="safez20")',HMI)

    def test_offline_hotspot_qr_and_network_web_onboarding(self):
        # LVGL v8 already compiles Nayuki's qrcodegen.c. Compiling a
        # second local implementation caused duplicate-symbol linker failures.
        # Only a local API declaration header is retained for the firmware.
        qr_header=(ROOT/"firmware/hmi/src/qrcodegen.h").read_text(encoding="utf-8")
        self.assertIn('MIT License',qr_header)
        self.assertFalse((ROOT/"firmware/hmi/src/qrcodegen.c").exists())
        self.assertIn('#include "qrcodegen.h"',HMI)
        self.assertIn('WIFI:T:WPA;S:',HMI)
        self.assertIn('qrcodegen_encodeText',HMI)
        self.assertIn('void showHotspotQr()',HMI)
        self.assertIn('http.on("/api/ui/hotspot-qr",HTTP_GET',HMI)
        self.assertIn('http.on("/api/ui/network/scan",HTTP_GET',HMI)
        self.assertIn('WiFi.scanNetworks(true)',HMI)
        self.assertIn('http.on("/api/ui/network/connect",HTTP_POST',HMI)
        self.assertIn('prefs.putString("ssid",ssid)',HMI)

    def test_lightburn_gcode_files_use_sd_when_available(self):
        self.assertIn('name.endsWith(".gc")',HMI)
        self.assertIn('sdReady?64u*1024u*1024u:MAX_JOB_BYTES',HMI)
        self.assertIn('jobStore().rename(uploadTemporary,uploadDestination)',HMI)

    def test_web_tabs_and_backend_share_actions(self):
        for tab in ("home","motion","jobs","settings","probe","network","system"):
            self.assertIn('id="'+tab+'" class="tab',WEB)
        for path in ("/api/ui/action","/api/ui/setting","/api/ui/params",
                     "/api/ui/config","/api/ui/network","/api/ui/network/scan",
                     "/api/ui/network/connect","/api/ui/hotspot-qr",
                     "/api/lightburn/profile","/api/probe-plan"):
            self.assertIn(path,HMI)
            self.assertIn(path,WEB)
        self.assertIn('action(op.c_str())',HMI)
        self.assertIn('action("setparam")',HMI)
        self.assertIn('action("savearea")',HMI)
        self.assertIn('action("focusSave")',HMI)
        self.assertIn('action(http.arg("plan")=="1"?"probePlan":"probeSave")',HMI)
        self.assertIn('if(!auth()){fail(401',HMI)


if __name__=="__main__":
    unittest.main()
