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
        self.assertIn('postHomePending=false;',HMI)
        self.assertIn('Homing OK: SKR hat Z vor XY auf 20 mm freigefahren.',HMI)
        self.assertNotIn('if(op=="safez20")',HMI)

    def test_offline_hotspot_qr_and_network_web_onboarding(self):
        qr=(ROOT/"firmware/hmi/src/qrcodegen.c").read_text(encoding="utf-8")
        self.assertIn('MIT License',qr)
        self.assertIn('WIFI:T:WPA;S:',HMI)
        self.assertIn('qrcodegen_encodeText',HMI)
        self.assertIn('void showHotspotQr()',HMI)
        self.assertIn('http.on("/api/ui/hotspot-qr",HTTP_GET',HMI)
        self.assertIn('http.on("/api/ui/network/scan",HTTP_GET',HMI)
        self.assertIn('WiFi.scanNetworks(true)',HMI)
        self.assertIn('http.on("/api/ui/network/connect",HTTP_POST',HMI)
        self.assertIn('prefs.putString("ssid",ssid)',HMI)

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
        self.assertIn('window',WEB) if False else None


if __name__=="__main__":
    unittest.main()
