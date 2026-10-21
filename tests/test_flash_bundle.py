"""Regression checks for safe HMI flash packaging and target manifest."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "builder"))
from flash_bundle import build_flash_package, find_boot_app0, flash_manifest, IMAGE_NAME


class FlashBundleTests(unittest.TestCase):
    def test_manifest_is_waveshare_s3_only(self):
        manifest = flash_manifest("/artifacts/123/firmware.bin", "v-test")
        self.assertEqual(manifest["builds"][0]["chipFamily"], "ESP32-S3")
        self.assertEqual(manifest["builds"][0]["parts"][0]["offset"], 0)
        self.assertFalse(manifest["new_install_prompt_erase"])

    def test_missing_bootloader_refuses_flash_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(RuntimeError, "bootloader fehlt"):
                build_flash_package(root / "missing", root, "0123456789" * 4, "offline", root, root)

    def test_successful_package_contains_localhost_installer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            core = root / "pio"
            packages = core / "packages" / "framework-arduinoespressif32" / "tools" / "partitions"
            packages.mkdir(parents=True)
            (packages / "boot_app0.bin").write_bytes(b"x" * 100)
            self.assertEqual(find_boot_app0(core), packages / "boot_app0.bin")
            output = root / "build"
            output.mkdir()
            (output / "bootloader.bin").write_bytes(b"\xe9" + b"x" * 100)
            (output / "partitions.bin").write_bytes(b"x" * 100)
            (output / "firmware.bin").write_bytes(b"x" * 100)
            templates = Path(__file__).resolve().parents[1] / "builder"

            def fake_merge(args, check, timeout):
                self.assertIn("--flash_size", args)
                self.assertIn("16MB", args)
                dest = Path(args[args.index("-o") + 1])
                dest.write_bytes(b"\xe9" + b"x" * 70000)

            with patch("flash_bundle.subprocess.run", side_effect=fake_merge):
                files = build_flash_package(output, root, "0123456789" * 4, "offline",
                                            templates, core)
            self.assertEqual(len(files), 2)
            self.assertTrue((root / IMAGE_NAME).is_file())
            bundle = root / "Waveshare-HMI-Flash-Paket-Windows.zip"
            with zipfile.ZipFile(bundle) as z:
                self.assertEqual(set(z.namelist()),
                                 {"firmware.bin", "manifest.json", "flash_local.py",
                                  "flash_ui.html", "Flash-Waveshare-Windows.cmd",
                                  "BITTE-LESEN.txt"})
                manifest = json.loads(z.read("manifest.json"))
                self.assertEqual(manifest["builds"][0]["parts"][0]["path"], "firmware.bin")
                self.assertIn(b"127.0.0.1", z.read("flash_local.py"))


if __name__ == "__main__":
    unittest.main()
