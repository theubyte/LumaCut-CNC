"""Regression tests for approval of legacy, incomplete firmware build archives."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

# The builder creates its artifacts folder at import. CI must never require /data.
_TEST_DATA_ROOT=tempfile.TemporaryDirectory(prefix="lumacut-release-test-")
os.environ["LUMACUT_DATA_ROOT"]=_TEST_DATA_ROOT.name
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"builder"))
import app as builder


class ReleaseReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.meta={
            "status":"success",
            "target":"lumacut_complete_suite_unverified",
            "paired_firmware":True,
            "source_sha":"a"*40,
            "files":[],
        }

    def add_image(self,name,data):
        path=self.folder/name
        path.write_bytes(data)
        self.meta["files"].append({
            "name":name,
            "bytes":len(data),
            "sha256":hashlib.sha256(data).hexdigest(),
        })

    def test_older_successful_build_without_hmi_ota_must_rebuild(self):
        self.add_image(builder.SKR_RELEASE_IMAGE_NAME,b"skr")
        ready,reason=builder.release_readiness(self.meta,self.folder)
        self.assertFalse(ready)
        self.assertIn("HMI-OTA",reason)
        self.assertIn("Komplett",reason)

    def test_paired_build_with_both_images_is_ready(self):
        self.add_image(builder.SKR_RELEASE_IMAGE_NAME,b"skr")
        self.add_image(builder.OTA_IMAGE_NAME,b"esp32")
        self.assertEqual(builder.release_readiness(self.meta,self.folder),(True,""))

    def test_missing_hmi_file_is_not_ready(self):
        self.add_image(builder.SKR_RELEASE_IMAGE_NAME,b"skr")
        self.add_image(builder.OTA_IMAGE_NAME,b"esp32")
        (self.folder/builder.OTA_IMAGE_NAME).unlink()
        self.assertFalse(builder.release_readiness(self.meta,self.folder)[0])

    def test_size_mismatch_is_not_ready(self):
        self.add_image(builder.SKR_RELEASE_IMAGE_NAME,b"skr")
        self.add_image(builder.OTA_IMAGE_NAME,b"esp32")
        (self.folder/builder.OTA_IMAGE_NAME).write_bytes(b"larger file")
        self.assertFalse(builder.release_readiness(self.meta,self.folder)[0])

    def test_single_hmi_build_is_not_ready(self):
        self.add_image(builder.SKR_RELEASE_IMAGE_NAME,b"skr")
        self.add_image(builder.OTA_IMAGE_NAME,b"esp32")
        self.meta["paired_firmware"]=False
        self.assertFalse(builder.release_readiness(self.meta,self.folder)[0])


if __name__=="__main__":
    unittest.main()
