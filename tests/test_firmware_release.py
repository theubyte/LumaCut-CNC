"""Firmware updates from GitHub releases (pi400/marlin/firmware_release.py)."""
import hashlib
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path

from pi400.marlin.firmware_release import FirmwareReleases, board_of, running_build

SKR_ID = "FIRMWARE_NAME:LumaCut CNC 0.1 (Oct 30 2026 10:00:00) MACHINE_TYPE:LumaCut CNC"
MARLIN_ID = ("FIRMWARE_NAME:Marlin 2.1.2.9 (Oct 30 2026 10:00:00) SOURCE_CODE_URL:github.com/MarlinFirmware/Marlin "
             "PROTOCOL_VERSION:1.0 MACHINE_TYPE:LumaCut CNC Marlin EXTRUDER_COUNT:0")
BUILD = "Oct 31 2026 16:54:31"
IMAGE = (struct.pack("<II", 0x20010000, 0x08007000 + 0x1235)
         + b"FIRMWARE_NAME:LumaCut CNC 0.1 (" + BUILD.encode() + b") MACHINE_TYPE:LumaCut CNC\x00"
         + b"Cap:SELF_UPDATE:1\x00").ljust(32 * 1024, b"\xff")
MARLIN_IMAGE = (struct.pack("<II", 0x2000C000, 0x08007000 + 0x1235)
                + b"FIRMWARE_NAME:Marlin Oct 31 2026 16:54:31 MACHINE_TYPE:LumaCut CNC Marlin\x00"
                + b"Switching to Binary Protocol\x00").ljust(128 * 1024, b"\xff")
ASSET = "LumaCut-Firmware-SKR.bin"


def fake_github(number, image=IMAGE, build=BUILD, digest=None, extra_releases=()):
    meta = {"number": number, "commit": "abc", "boards": {"skr": {
        "asset": ASSET, "build": build, "size": len(image),
        "sha256": digest or hashlib.sha256(image).hexdigest()}}}
    releases = list(extra_releases) + [{"tag_name": "lumacut-fw-%d" % number, "assets": [
        {"name": "LumaCut-Firmware.json", "browser_download_url": "https://dl/json"},
        {"name": ASSET, "browser_download_url": "https://dl/bin"}]}]
    urls = {"https://api.github.com/repos/o/r/releases?per_page=30": json.dumps(releases).encode(),
            "https://dl/json": json.dumps(meta).encode(), "https://dl/bin": image}
    calls = []

    def opener(url, timeout):
        calls.append(url)
        return io.BytesIO(urls[url])
    return opener, calls


class FirmwareReleaseTests(unittest.TestCase):
    def test_identity_parsing(self):
        self.assertEqual(board_of(SKR_ID), "skr")
        self.assertEqual(running_build(SKR_ID), "Oct 30 2026 10:00:00")
        self.assertEqual(running_build("FIRMWARE_NAME:LumaCut CNC 0.1 (Oct  1 2026 08:00:00) "
                                       "MACHINE_TYPE:LumaCut CNC"), "Oct  1 2026 08:00:00")
        # Marlin builds, the Grbl bridge and foreign firmwares are never offered an image.
        self.assertIsNone(board_of(MARLIN_ID))
        self.assertIsNone(board_of(MARLIN_ID.replace("CNC Marlin", "CNC Marlin Anet")))
        self.assertIsNone(board_of("MACHINE_TYPE:LumaCut CNC Atomstack-Grbl EXTRUDER_COUNT:0"))
        self.assertIsNone(board_of("FIRMWARE_NAME:Marlin 2.0.9.7 MACHINE_TYPE:Anet A8 plus"))

    def test_newer_build_is_offered_and_stored_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            # The Android release is newer in the list and must be skipped.
            android = {"tag_name": "android-1.0.60", "assets": []}
            opener, calls = fake_github(7, extra_releases=[android])
            fw = FirmwareReleases(Path(tmp), repo="o/r", opener=opener)
            self.assertFalse(fw.offer(SKR_ID)["update_available"])
            fw.check()
            offer = fw.offer(SKR_ID)
            self.assertIsNone(offer["error"])
            self.assertTrue(offer["update_available"])
            self.assertEqual((offer["board"], offer["number"], offer["release_build"]),
                             ("skr", 7, BUILD))
            self.assertEqual(fw.image("skr"), IMAGE)
            # Same release again: no second image download.
            calls.clear()
            fw.check()
            self.assertNotIn("https://dl/bin", calls)

    def test_same_or_older_build_on_the_board_is_not_offered(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = FirmwareReleases(Path(tmp), repo="o/r", opener=fake_github(7)[0])
            fw.check()
            same = SKR_ID.replace("Oct 30 2026 10:00:00", BUILD)
            newer = SKR_ID.replace("Oct 30 2026 10:00:00", "Nov  2 2026 09:00:00")
            self.assertFalse(fw.offer(same)["update_available"])
            self.assertFalse(fw.offer(newer)["update_available"])
            # The running Marlin gets nothing: this path goes over SD once.
            self.assertFalse(fw.offer(MARLIN_ID)["update_available"])

    def test_old_marlin_releases_are_not_taken(self):
        with tempfile.TemporaryDirectory() as tmp:
            marlin = {"tag_name": "marlin-62", "assets": [
                {"name": "LumaCut-Marlin.json", "browser_download_url": "https://dl/old"}]}
            opener = lambda url, timeout: io.BytesIO(json.dumps([marlin]).encode())
            fw = FirmwareReleases(Path(tmp), repo="o/r", opener=opener)
            fw.check()
            self.assertIn("noch keine Firmware", fw.offer(SKR_ID)["error"])
            self.assertFalse(fw.offer(SKR_ID)["update_available"])
            # Newest first in the list, ours further down: ours is the one.
            fw._open = fake_github(3, extra_releases=[marlin])[0]
            fw.check()
            self.assertEqual(fw.offer(SKR_ID)["number"], 3)

    def test_marlin_release_still_on_disk_is_never_offered(self):
        # A Pi that ran Marlin holds its release.json and skr.bin (numbers up to 62).
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "firmware"
            base.mkdir()
            (base / "skr.bin").write_bytes(MARLIN_IMAGE)
            (base / "release.json").write_text(json.dumps({
                "number": 62, "commit": "old", "boards": {"skr": {
                    "build": "Dec 31 2026 16:54:31", "size": len(MARLIN_IMAGE),
                    "sha256": hashlib.sha256(MARLIN_IMAGE).hexdigest()}}}), encoding="utf-8")
            opener, calls = fake_github(1)
            fw = FirmwareReleases(Path(tmp), repo="o/r", opener=opener)
            self.assertIsNone(fw.meta())
            self.assertFalse(fw.offer(SKR_ID)["update_available"])
            self.assertIsNone(fw.image("skr"))
            # A release with a lower number than the old Marlin ones still counts.
            fw.check()
            self.assertEqual(fw.offer(SKR_ID)["number"], 1)
            self.assertEqual(fw.image("skr"), IMAGE)

    def test_bad_checksum_or_stamp_keeps_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = FirmwareReleases(Path(tmp), repo="o/r", opener=fake_github(7, digest="0" * 64)[0])
            fw.check()
            self.assertIn("Prüfsumme", fw.offer(SKR_ID)["error"])
            self.assertFalse(fw.offer(SKR_ID)["update_available"])
            fw._open = fake_github(8, build="Nov  1 2026 00:00:00")[0]
            fw.check()
            self.assertIn("Build-Stempel", fw.offer(SKR_ID)["error"])
            self.assertIsNone(fw.meta())

    def test_foreign_or_marlin_image_is_refused(self):
        foreign = IMAGE.replace(b"LumaCut CNC", b"Other Stuff")
        for image in (foreign, MARLIN_IMAGE):
            with self.subTest(image=image[8:30]), tempfile.TemporaryDirectory() as tmp:
                fw = FirmwareReleases(Path(tmp), repo="o/r", opener=fake_github(7, image=image)[0])
                fw.check()
                self.assertIsNotNone(fw.offer(SKR_ID)["error"])
                self.assertFalse(fw.offer(SKR_ID)["update_available"])

    def test_tampered_file_on_disk_is_not_flashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = FirmwareReleases(Path(tmp), repo="o/r", opener=fake_github(7)[0])
            fw.check()
            path = Path(tmp) / "firmware" / "skr.bin"
            path.write_bytes(IMAGE[:-3] + b"000")
            self.assertIsNone(fw.image("skr"))


if __name__ == "__main__":
    unittest.main()
