"""Android app updates through the Pi (pi400/marlin/app_update.py, /api/app/android)."""
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi400"))
from marlin.app_update import AppUpdates  # noqa: E402

APK = b"PK\x03\x04 fake apk " * 100


def fake_github(version_code, apk=APK, digest=None):
    meta = {"version_code": version_code, "version_name": "1.0.%d" % version_code,
            "sha256": digest or hashlib.sha256(apk).hexdigest(), "size": len(apk), "commit": "abc"}
    urls = {
        "https://api.github.com/repos/o/r/releases/latest": json.dumps({"assets": [
            {"name": "LumaCut-Android.apk", "browser_download_url": "https://dl/apk"},
            {"name": "LumaCut-Android.json", "browser_download_url": "https://dl/json"}]}).encode(),
        "https://dl/json": json.dumps(meta).encode(),
        "https://dl/apk": apk,
    }
    calls = []

    def opener(url, timeout):
        calls.append(url)
        return io.BytesIO(urls[url])
    return opener, calls


class AppUpdateTests(unittest.TestCase):
    def test_newer_release_is_downloaded_once_and_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            opener, calls = fake_github(41)
            u = AppUpdates(Path(tmp), repo="o/r", opener=opener)
            self.assertFalse(u.status()["available"])
            s = u.check()
            self.assertTrue(s["available"])
            self.assertEqual((s["version_code"], s["version_name"], s["size"]), (41, "1.0.41", len(APK)))
            self.assertEqual(u.apk.read_bytes(), APK)
            self.assertIsNone(s["error"])
            # Same version again: only the small files, no second APK download.
            calls.clear()
            u.check()
            self.assertNotIn("https://dl/apk", calls)

    def test_wrong_checksum_keeps_the_old_apk(self):
        with tempfile.TemporaryDirectory() as tmp:
            opener, _ = fake_github(41)
            u = AppUpdates(Path(tmp), repo="o/r", opener=opener)
            u.check()
            bad, _ = fake_github(42, apk=b"evil" * 10, digest="0" * 64)
            u._open = bad
            s = u.check()
            self.assertIn("Prüfsumme", s["error"])
            self.assertEqual(s["version_code"], 41)
            self.assertEqual(u.apk.read_bytes(), APK)

    def test_endpoints_serve_info_and_apk(self):
        script = r"""
import io, json, hashlib
from marlin import web
apk = b"PK\x03\x04 fake apk " * 100
meta = {"version_code": 7, "version_name": "1.0.7", "sha256": hashlib.sha256(apk).hexdigest(), "size": len(apk)}
urls = {"https://api.github.com/repos/theubyte/LumaCut-CNC/releases/latest": json.dumps({"assets": [
    {"name": "LumaCut-Android.apk", "browser_download_url": "a"},
    {"name": "LumaCut-Android.json", "browser_download_url": "j"}]}).encode(), "j": json.dumps(meta).encode(), "a": apk}
web.app_updates._open = lambda url, timeout: io.BytesIO(urls[url])
c = web.app.test_client()
assert c.get("/api/app/android").get_json()["available"] is False
assert c.get("/api/app/android.apk").status_code == 404
r = c.post("/api/action", data={"op": "app_update_check"})
assert r.status_code == 200 and "1.0.7" in r.get_json()["message"], r.data
info = c.get("/api/app/android").get_json()
assert info["available"] and info["version_code"] == 7 and info["sha256"] == meta["sha256"], info
r = c.get("/api/app/android.apk")
assert r.status_code == 200 and r.data == apk and r.mimetype == "application/vnd.android.package-archive"
assert "app_update" in c.get("/api/status").get_json()["features"]
web.app_updates._open = lambda url, timeout: (_ for _ in ()).throw(OSError("kein Internet"))
r = c.post("/api/action", data={"op": "app_update_check"})
assert r.status_code == 503 and "kein Internet" in r.get_json()["error"], r.data
assert c.get("/api/app/android").get_json()["available"] is True   # old version stays
"""
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, LUMACUT_DATA=tmp, PYTHONPATH=str(ROOT / "pi400"))
            r = subprocess.run([sys.executable, "-c", script], env=env, cwd=ROOT,
                               text=True, capture_output=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
