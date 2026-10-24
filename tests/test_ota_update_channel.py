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
        self.assertIn('"hmi_ota_enabled":HMI_OTA_ENABLED',SERVER)
        self.assertIn('HMI_OTA_ENABLED=os.environ.get(',SERVER)
        self.assertIn('"automatic_skr_flash_enabled":False',SERVER)

    def test_hmi_ota_writer_is_part_of_pro_firmware(self):
        ota=(ROOT/"firmware/hmi/src/secure_ota.h").read_text(encoding="utf-8")
        self.assertIn('#include "secure_ota.h"',HMI)
        self.assertIn("LumaOta::install(updateImageSha256,updateImageBytes",HMI)
        self.assertIn('http.addHeader("X-LumaCut-Device-Key",deviceKey)',ota)
        self.assertIn('http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS)',ota)
        self.assertIn('client.setCACert(ca)',ota)
        self.assertIn('if(expectedSha!=String(textSha))',ota)
        self.assertIn('if(!Update.end(false))',ota)
        self.assertIn('Update.abort()',ota)
        self.assertIn('esp_ota_get_next_update_partition(nullptr)',ota)
        self.assertIn('bool restorePrior(',ota)
        self.assertIn('prefs.putBool("otaPending",true)',HMI)
        self.assertIn('if(attempts>1)restoreHmiIfBootBroken()',HMI)
        self.assertIn('if(op=="updateinstall")',HMI)
        self.assertIn('if(op=="updatekeysave")',HMI)
        self.assertIn('machineState!=MachineState::Idle',HMI)
        self.assertIn('void installHmiUpdate()',HMI)

    def test_optional_sd_mount_after_expander_and_littlefs_fallback(self):
        self.assertIn('#include <SD.h>',HMI)
        self.assertIn("SD.begin((uint8_t)-1,SPI,4000000)",HMI)
        self.assertIn('jobStore().open("/jobs/"+selectedJob,FILE_READ)',HMI)
        self.assertIn('storageOk=sdReady||internalStorageReady;',HMI)
        self.assertIn('File dir=LittleFS.open("/jobs");',HMI)
        self.assertIn('if(!SD.exists("/jobs"))sdReady=SD.mkdir("/jobs");',HMI)
        self.assertLess(HMI.index('    touchInit();'),HMI.index('sdReady=SD.begin('))
        self.assertNotIn('SD.format()',HMI)

    def test_application_only_hmi_image_not_merged(self):
        self.assertIn('ota_src=hmi_out/"firmware.bin"',SERVER)
        self.assertIn('ota_dest=folder/"HMI_OTA_APP_UNVERIFIED.bin"',SERVER)
        self.assertIn('ota_dest.read_bytes()',SERVER)
        self.assertIn('UPDATE_DEVICE_KEY',SERVER)

    def test_hmi_https_and_hardware_safety(self):
        self.assertIn("setCACert(LUMACUT_UPDATE_CA)",HMI)
        self.assertIn('else if(code==401||code==403)',HMI)
        self.assertIn('Update-API verlangt Login: Unraid-Compiler oder Reverse-Proxy pruefen.',HMI)
        self.assertIn('Update-API fehlt (404): Compiler aktualisieren',HMI)
        self.assertIn('updateAvailable=false;updateOtaApproved=false;',HMI)
        self.assertIn('"https://luma.millione.de/api/updates/latest"',HMI)
        self.assertIn("void updateCheckService()",HMI)
        self.assertIn('owner!=Owner::None||jobRunning||scriptActive',HMI)
        self.assertIn('void checkLumaCutUpdates()',HMI)
        self.assertIn('if(op=="updatecheck")',HMI)
        self.assertIn('"/api/update/status"',HMI)
        self.assertNotIn("tls.setInsecure();",HMI)
        self.assertIn("BEGIN CERTIFICATE",CA)
        self.assertIn("LUMACUT_SOURCE_SHA",STAMP)
        self.assertIn("extra_scripts = pre:stamp.py",INI)

if __name__=="__main__":
    unittest.main()
