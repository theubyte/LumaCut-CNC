"""Cross-component checks for LumaCut version notifications.

These are design/regression tests; actual OTA flashing stays disabled pending
the physical recovery/bootloader commissioning.
"""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SERVER=(ROOT/"builder/app.py").read_text(encoding="utf-8")
HMI=(ROOT/"firmware/hmi/src/pro_main.cpp").read_text(encoding="utf-8")
STAMP=(ROOT/"firmware/hmi/stamp.py").read_text(encoding="utf-8")
INI=(ROOT/"firmware/hmi/platformio.ini").read_text(encoding="utf-8")
CA=(ROOT/"firmware/hmi/src/update_ca.h").read_text(encoding="utf-8")

class ReleaseNotificationTests(unittest.TestCase):
    def test_approved_only(self):
        self.assertIn("def validated_release(job_id):",SERVER)
        self.assertIn('meta.get("paired_firmware")',SERVER)
        self.assertIn('meta.get("status")!="success"',SERVER)
        self.assertIn('RELEASE_FILE=ROOT/"approved-release.json"',SERVER)
        self.assertIn('@app.post("/api/updates/approve")',SERVER)
        self.assertIn('@app.get("/api/updates/latest")',SERVER)
        self.assertIn('"hmi_ota_enabled":False',SERVER)
        self.assertIn('"automatic_skr_flash_enabled":False',SERVER)

    def test_application_only_hmi_image_not_merged(self):
        self.assertIn('ota_src=hmi_out/"firmware.bin"',SERVER)
        self.assertIn('ota_dest=folder/"HMI_OTA_APP_UNVERIFIED.bin"',SERVER)
        self.assertIn('ota_dest.read_bytes()',SERVER)
        self.assertIn('UPDATE_DEVICE_KEY',SERVER)

    def test_hmi_https_and_hardware_safety(self):
        self.assertIn("setCACert(LUMACUT_UPDATE_CA)",HMI)
        self.assertIn('"https://luma.millione.de/api/updates/latest"',HMI)
        self.assertIn("void updateCheckService()",HMI)
        self.assertIn('owner!=Owner::None||jobRunning||scriptActive',HMI)
        self.assertIn('void checkLumaCutUpdates()',HMI)
        self.assertIn('if(op=="updatecheck")',HMI)
        self.assertIn('"/api/update/status"',HMI)
        self.assertNotIn("setInsecure()",HMI)
        self.assertIn("BEGIN CERTIFICATE",CA)
        self.assertIn("LUMACUT_SOURCE_SHA",STAMP)
        self.assertIn("extra_scripts = pre:stamp.py",INI)

if __name__=="__main__":
    unittest.main()
