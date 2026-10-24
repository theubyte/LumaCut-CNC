"""SKR OTA integration contract: app-only flash, ST ROM framing, chip ID and readback.

This is a source/CI regression check. Physical BOOT0/NRST and failure recovery
must still be demonstrated on the specific assembled controller.
"""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
HMI=(ROOT/"firmware/hmi/src/pro_main.cpp").read_text(encoding="utf-8")
UPD=(ROOT/"firmware/hmi/src/skr_stm32_uart_ota.h").read_text(encoding="utf-8")
BUILD=(ROOT/"firmware/skr/build.py").read_text(encoding="utf-8")
DOC=(ROOT/"docs/SKR_AUTOMATIC_UPDATE.md").read_text(encoding="utf-8")


class AutomaticSkrUpdateTests(unittest.TestCase):
    def test_download_authentication_and_staged_sha256(self):
        for phrase in (
            'SKR_URL="https://luma.millione.de/api/updates/file/skr"',
            'tls.setCACert(ca)',
            'http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS)',
            '"X-LumaCut-Device-Key"',
            'hexDigest(digest)!=expected',
            'hexDigest(staged)==expectedSha',
            'validVector(head,bytes)',
            'fs.rename(PARTIAL,STAGING)',
        ):
            self.assertIn(phrase,UPD)

    def test_rom_target_and_preserved_bootloader(self):
        for phrase in (
            'APP_BASE=0x08007000UL',
            'FLASH_END=0x08040000UL',
            'PAGE_BYTES=2048',
            'FIRST_PAGE=14',
            'STM32F103_HIGH_DENSITY_ID=0x0414',
            'SERIAL_8E1,44,43',
            'SERIAL_8N1,44,43',
            'void runApplication()',
            'getStreamPtr()',
            'rom.erasePages(FIRST_PAGE,pages,extended)',
            '!rom.read(address,returned,padded)',
            'memcmp(written,returned,padded)!=0',
        ):
            self.assertIn(phrase,UPD)
        self.assertNotIn('0xFFFF',UPD)  # No mass erase!
        self.assertIn('STM32F103RCTX_BL28K_FLASH.ld',BUILD)

    def test_external_reset_hardware_is_documented_and_required(self):
        for phrase in ('PCA_ADDR=0x40','Wire.beginTransmission(PCA_ADDR)',
                       'if(!reset.begin())','if(!reset.enter())'):
            self.assertIn(phrase,UPD)
        for phrase in ('PCA9685','BOOT0','NRST','NPN','3,3 V','GND',
                       'microSD','Ruecklesen'):
            self.assertIn(phrase,DOC)

    def test_end_to_end_hmi_button_and_serial_ownership(self):
        for phrase in ('#include "skr_stm32_uart_ota.h"',
                       'void installSkrUpdate()',
                       'SkrUpdate::fetchVerified(fs,',
                       'SkrUpdate::flashVerified(fs,machine,updateSkrSha256,',
                       'if(op=="skrinstall")',
                       '"SKR installieren"',
                       'installSkrUpdate();',
                       'prefs.putString("skrLast",offeredUpdateSha)',
                       'machineState!=MachineState::Idle',
                       'writeCmd("M5");machine.flush();',
                       'skrUpdateProgress'):
            self.assertIn(phrase,HMI)


if __name__=="__main__":
    unittest.main()
