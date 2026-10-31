"""Firmware updates from GitHub releases (pi400/marlin/firmware_release.py)."""
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from pi400.marlin.firmware_release import FirmwareReleases, board_of, running_build
from tests.test_avr_flash import lumacut_image, to_hex

ANET_ID = ("FIRMWARE_NAME:Marlin 2.1.2.9 (Oct 30 2026 10:00:00) SOURCE_CODE_URL:github.com/MarlinFirmware/Marlin "
           "PROTOCOL_VERSION:1.0 MACHINE_TYPE:LumaCut CNC Marlin Anet EXTRUDER_COUNT:0")
HEX = to_hex(lumacut_image()).encode()          # build stamp "Oct 31 2026 16:54:31"


def fake_github(number, hex_data=HEX, build="Oct 31 2026 16:54:31", digest=None, extra_releases=()):
    meta = {"number": number, "commit": "abc", "boards": {"anet": {
        "asset": "LumaCut-Marlin-Anet.hex", "build": build, "size": len(hex_data),
        "sha256": digest or hashlib.sha256(hex_data).hexdigest()}}}
    releases = list(extra_releases) + [{"tag_name": "marlin-%d" % number, "assets": [
        {"name": "LumaCut-Marlin.json", "browser_download_url": "https://dl/json"},
        {"name": "LumaCut-Marlin-Anet.hex", "browser_download_url": "https://dl/hex"}]}]
    urls = {"https://api.github.com/repos/o/r/releases?per_page=30": json.dumps(releases).encode(),
            "https://dl/json": json.dumps(meta).encode(), "https://dl/hex": hex_data}
    calls = []

    def opener(url, timeout):
        calls.append(url)
        return io.BytesIO(urls[url])
    return opener, calls


class FirmwareReleaseTests(unittest.TestCase):
    def test_identity_parsing(self):
        self.assertEqual(board_of(ANET_ID), "anet")
        self.assertEqual(running_build(ANET_ID), "Oct 30 2026 10:00:00")
        self.assertEqual(board_of("FIRMWARE_NAME:Marlin 2.1.2.9 (Oct  1 2026 08:00:00) "
                                  "MACHINE_TYPE:LumaCut CNC Marlin EXTRUDER_COUNT:0"), "skr")
        # The Grbl bridge and foreign firmwares are never offered an image.
        self.assertIsNone(board_of("MACHINE_TYPE:LumaCut CNC Atomstack-Grbl EXTRUDER_COUNT:0"))
        self.assertIsNone(board_of("FIRMWARE_NAME:Marlin 2.0.9.7 MACHINE_TYPE:Anet A8 plus"))

    def test_newer_build_is_offered_and_stored_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            # The Android release is newer in the list and must be skipped.
            android = {"tag_name": "android-1.0.60", "assets": []}
            opener, calls = fake_github(7, extra_releases=[android])
            fw = FirmwareReleases(Path(tmp), repo="o/r", opener=opener)
            self.assertFalse(fw.offer(ANET_ID)["update_available"])
            fw.check()
            offer = fw.offer(ANET_ID)
            self.assertIsNone(offer["error"])
            self.assertTrue(offer["update_available"])
            self.assertEqual((offer["board"], offer["number"], offer["release_build"]),
                             ("anet", 7, "Oct 31 2026 16:54:31"))
            self.assertEqual(fw.image("anet"), HEX)
            # Same release again: no second image download.
            calls.clear()
            fw.check()
            self.assertNotIn("https://dl/hex", calls)

    def test_same_or_older_build_on_the_board_is_not_offered(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = FirmwareReleases(Path(tmp), repo="o/r", opener=fake_github(7)[0])
            fw.check()
            same = ANET_ID.replace("Oct 30 2026 10:00:00", "Oct 31 2026 16:54:31")
            newer = ANET_ID.replace("Oct 30 2026 10:00:00", "Nov  2 2026 09:00:00")
            self.assertFalse(fw.offer(same)["update_available"])
            self.assertFalse(fw.offer(newer)["update_available"])
            skr = ANET_ID.replace("Marlin Anet", "Marlin")
            self.assertFalse(fw.offer(skr)["update_available"])     # no SKR image in it

    def test_bad_checksum_or_stamp_keeps_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = FirmwareReleases(Path(tmp), repo="o/r", opener=fake_github(7, digest="0" * 64)[0])
            fw.check()
            self.assertIn("Prüfsumme", fw.offer(ANET_ID)["error"])
            self.assertFalse(fw.offer(ANET_ID)["update_available"])
            fw._open = fake_github(8, build="Nov  1 2026 00:00:00")[0]
            fw.check()
            self.assertIn("Build-Stempel", fw.offer(ANET_ID)["error"])
            self.assertIsNone(fw.meta())

    def test_foreign_image_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            foreign = to_hex(lumacut_image().replace(b"LumaCut CNC Marlin Anet", b"Some Other Firmware!!!!")).encode()
            fw = FirmwareReleases(Path(tmp), repo="o/r", opener=fake_github(7, hex_data=foreign)[0])
            fw.check()
            self.assertIsNotNone(fw.offer(ANET_ID)["error"])
            self.assertFalse(fw.offer(ANET_ID)["update_available"])

    def test_tampered_file_on_disk_is_not_flashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = FirmwareReleases(Path(tmp), repo="o/r", opener=fake_github(7)[0])
            fw.check()
            path = Path(tmp) / "firmware" / "anet.hex"
            path.write_bytes(HEX[:-3] + b"00\n")
            self.assertIsNone(fw.image("anet"))


if __name__ == "__main__":
    unittest.main()
