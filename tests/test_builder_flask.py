"""Real Flask integration checks for the private Build Lab's read-only API.

No GitHub checkout/build process or physical hardware is started during tests.
"""
import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

BUILDER=Path(__file__).resolve().parents[1]/"builder"

class BuildLabFlaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix="lumacut-builder-tests-")
        os.environ["LUMACUT_DATA_ROOT"]=cls.tmp.name
        os.environ["BUILDER_PASSWORD"]="CI_TEST_PASSWORD_ONLY"
        sys.path.insert(0,str(BUILDER))
        spec=importlib.util.spec_from_file_location("lumacut_build_app",BUILDER/"app.py")
        cls.module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)
        cls.client=cls.module.app.test_client()
        basic=base64.b64encode(b"lumacut:CI_TEST_PASSWORD_ONLY").decode()
        cls.auth={"Authorization":"Basic "+basic}
        cls.job_id="0123456789abcdef"
        cls.folder=cls.module.ART/cls.job_id
        cls.folder.mkdir(parents=True)
        firmware=cls.folder/"UNVERIFIED_DO_NOT_FLASH_firmware.bin"
        firmware.write_bytes(b"REAL_TEST_FIRMWARE")
        manifest={
            "id":cls.job_id,
            "target":"stm32_hmi_bridge_unverified",
            "status":"success",
            "created_utc":"2026-10-24T12:00:00+00:00",
            "finished_utc":"2026-10-24T12:02:00+00:00",
            "files":[{"name":firmware.name,"bytes":firmware.stat().st_size,
                      "sha256":"a"*64}]
        }
        (cls.folder/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_auth_blocks_anonymous_requests(self):
        self.assertEqual(self.client.get("/").status_code,401)
        self.assertEqual(self.client.get("/api/jobs").status_code,401)

    def test_dashboard_html_css_js_served(self):
        for path,expected in (("/","Build. Flash."),("/ui/dashboard.css",".action-card"),
                              ("/ui/dashboard.js","showFinish")):
            response=self.client.get(path,headers=self.auth)
            self.assertEqual(response.status_code,200,path)
            self.assertIn(expected,response.get_data(as_text=True))

    def test_progress_and_history_endpoints(self):
        response=self.client.get("/api/jobs",headers=self.auth)
        self.assertEqual(response.status_code,200)
        data=response.get_json()
        self.assertEqual(data["jobs"][0]["id"],self.job_id)
        self.assertEqual(data["jobs"][0]["progress_pct"],100)
        self.assertEqual(data["jobs"][0]["elapsed_seconds"],120)

    def test_sd_firmware_is_downloaded_with_bootloader_name(self):
        result=self.client.get("/api/jobs/"+self.job_id+"/sd-image",headers=self.auth)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.data,b"REAL_TEST_FIRMWARE")
        self.assertIn("firmware.bin",result.headers.get("Content-Disposition",""))

    def test_restrict_assets_and_build_targets(self):
        self.assertEqual(self.client.get("/ui/app.py",headers=self.auth).status_code,404)
        response=self.client.post("/api/build",headers={**self.auth,
            "X-LumaCut-Action":"build"},json={"target":"touch --shell=true"})
        self.assertEqual(response.status_code,400)

if __name__=="__main__":
    unittest.main()
