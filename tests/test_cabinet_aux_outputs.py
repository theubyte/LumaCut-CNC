"""Ensure laser, exhaust and cabinet LED pins stay separate on SKR Mini MZ.

The grblHAL bridge must expose the three physical MOSFET channels:
 PC9 BED  = laser power switch controlled by spindle enable (low side)
 PC6 FAN0 = M8 flood/exhaust
 PC8 HE0  = M7 mist/cabinet 24 V LED
 PC7 FAN1 = unused spare
"""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
BUILD=(ROOT/"firmware/skr/build.py").read_text(encoding="utf-8")
HMI=(ROOT/"firmware/hmi/src/pro_main.cpp").read_text(encoding="utf-8")
PORTAL=(ROOT/"firmware/hmi/src/mobile_portal.h").read_text(encoding="utf-8")

class AuxOutputContractTest(unittest.TestCase):
    def test_24v_channels_are_unique_and_enabled(self):
        self.assertIn('-D COOLANT_ENABLE=3',BUILD)
        self.assertIn('AUXOUTPUT3_PIN          6',BUILD)
        self.assertIn('AUXOUTPUT4_PIN          8',BUILD)
        self.assertIn('AUXOUTPUT2_PIN          9',BUILD)
        self.assertIn('PC9 BED now directly switches',BUILD)
        self.assertIn('galvanic isolation',BUILD)
        self.assertNotIn('-D COOLANT_ENABLE=1',BUILD)

    def test_mist_flood_independent_realtime_override(self):
        self.assertIn('machine.write((uint8_t)(lights?0xA1:0xA0));',HMI)
        self.assertIn('lightOn=a.indexOf(\'M\')>=0;',HMI)
        self.assertIn('exhaustOn=a.indexOf(\'F\')>=0;',HMI)
        self.assertIn('if(op=="lightToggle"||op=="exhaustToggle"',HMI)
        self.assertIn('"lightToggle","exhaustToggle","lightOn","lightOff"',HMI)
        self.assertIn('btn(c,"LEDs EINSCHALTEN"',HMI)
        self.assertIn('btn(c,"Abluft EINSCHALTEN"',HMI)

    def test_browser_matches_touchscreen(self):
        self.assertIn('data-op="lightToggle"',PORTAL)
        self.assertIn('data-op="exhaustToggle"',PORTAL)
        self.assertIn('id="ledControl"',PORTAL)
        self.assertIn('id="exhaustControl"',PORTAL)
        self.assertIn('d["cabinet_leds_on"]=lightOn;',HMI)
        self.assertIn('d["exhaust_on"]=exhaustOn;',HMI)

if __name__=="__main__":unittest.main()
