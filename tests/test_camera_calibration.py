"""Camera calibration stored on the Pi: storage, validation, atomic write, HTTP API."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi400"))
from marlin import camera_calibration as cc


def measured(**changes):
    data = {
        "image_width": 1280, "image_height": 720, "px_per_mm": 7.5, "scan_z": 35.0,
        "offset_mm": [28.5, -21.0], "rotation_deg": 1.5, "flip_x": 1, "flip_y": -1,
        "crop_fraction": 0.05,
        "camera_matrix": [[900.0, 0, 640], [0, 905.0, 360], [0, 0, 1]],
        "dist_coeffs": [-0.1, 0.02, 0, 0, 0],
        "exposure": -6, "homography": [[0.13, 0, -80], [0, 0.13, -45], [0, 0, 1]],
        "calibrated": True, "notes": "Schachbrett 9x6", "updated_by": "Studio Werkstatt",
    }
    data.update(changes)
    return data


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "etc" / "camera_calibration.json"
        self.store = cc.CalibrationStore([self.path])

    def test_missing_file_returns_flagged_placeholder(self):
        record = self.store.load()
        self.assertTrue(record["placeholder"])
        self.assertFalse(record["calibrated"])
        self.assertEqual(record["status"], "platzhalter")
        self.assertEqual(record["revision"], 0)
        self.assertEqual((record["image_width"], record["px_per_mm"], record["offset_mm"]),
                         (640, 4.0, [30.0, -20.0]))
        self.assertEqual(record["storage"]["path"], str(self.path))
        self.assertTrue(record["storage"]["writable"])
        self.assertFalse(self.path.exists(), "GET must not create the file")

    def test_save_roundtrip_increments_revision_and_writes_json(self):
        saved = self.store.save(measured(), 0)
        self.assertEqual(saved["revision"], 1)
        self.assertFalse(saved["placeholder"])
        self.assertEqual(saved["status"], "kalibriert")
        self.assertTrue(saved["updated_at"].endswith("Z"))
        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["format"], cc.FORMAT)
        self.assertEqual(on_disk["schema_version"], 1)
        self.assertEqual(on_disk["homography"][0][0], 0.13)
        self.assertNotIn("storage", on_disk)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o644)
        again = self.store.save(dict(saved, px_per_mm=8.0), 1)
        self.assertEqual((again["revision"], again["px_per_mm"]), (2, 8.0))
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), [self.path.name])

    def test_stale_revision_is_conflict_and_keeps_file(self):
        self.store.save(measured(), 0)
        before = self.path.read_bytes()
        with self.assertRaises(cc.CalibrationConflict) as ctx:
            self.store.save(measured(px_per_mm=9.0), 0)
        self.assertIn("inzwischen geändert", str(ctx.exception))
        self.assertEqual(ctx.exception.current["revision"], 1)
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "revision fehlt"):
            self.store.save(measured(), None)

    def test_failed_write_keeps_old_file_and_leaves_no_temp(self):
        self.store.save(measured(), 0)
        before = self.path.read_bytes()
        with mock.patch.object(cc.os, "replace", side_effect=OSError("Datenträger voll")):
            with self.assertRaises(PermissionError):
                self.store.save(measured(px_per_mm=9.0), 1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], [self.path.name])

    def test_corrupt_file_falls_back_to_placeholder_with_error(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{kaputt", encoding="utf-8")
        record = self.store.load()
        self.assertTrue(record["placeholder"])
        self.assertIn("unlesbar", record["storage"]["error"])
        # Overwriting a corrupt file is allowed with the placeholder's revision 0.
        self.assertEqual(self.store.save(measured(), 0)["revision"], 1)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can write everywhere")
    def test_unwritable_etc_falls_back_to_next_candidate(self):
        etc = self.dir / "etc"
        etc.mkdir()
        etc.chmod(0o555)
        self.addCleanup(etc.chmod, 0o755)
        fallback = self.dir / "data" / "camera_calibration.json"
        store = cc.CalibrationStore([etc / "camera_calibration.json", fallback])
        self.assertEqual(store.write_path(), fallback)
        store.save(measured(), 0)
        self.assertTrue(fallback.is_file())
        self.assertEqual(store.load()["storage"]["path"], str(fallback))

    def test_existing_readonly_etc_file_is_still_read(self):
        etc = self.dir / "etc"
        etc.mkdir()
        record = dict(measured(), revision=4, updated_at="2026-10-01T10:00:00Z")
        (etc / "camera_calibration.json").write_text(json.dumps(record), encoding="utf-8")
        store = cc.CalibrationStore([etc / "camera_calibration.json", self.dir / "data" / "c.json"])
        with mock.patch.object(cc.CalibrationStore, "_writable",
                               staticmethod(lambda p: "data" in str(p))):
            loaded = store.load()
        self.assertEqual((loaded["revision"], loaded["px_per_mm"]), (4, 7.5))

    def test_candidate_paths_env_override_and_defaults(self):
        self.assertEqual(cc.candidate_paths({"LUMACUT_CAMERA_CALIBRATION": "/x/cal.json"}),
                         [Path("/x/cal.json")])
        paths = cc.candidate_paths({"LUMACUT_DATA": "/var/lib/lumacut"})
        self.assertEqual(paths[0], Path("/etc/lumacut/camera_calibration.json"))
        self.assertEqual(paths[1], ROOT / "pi400" / "config" / "camera_calibration.json")
        self.assertEqual(paths[2], Path("/var/lib/lumacut/camera_calibration.json"))


class ValidationTests(unittest.TestCase):
    def assertRejected(self, pattern, **changes):
        with self.assertRaisesRegex(ValueError, pattern):
            cc.validate(measured(**changes))

    def test_ranges_and_types_have_german_messages(self):
        self.assertRejected("px_per_mm: 0 liegt außerhalb", px_per_mm=0)
        self.assertRejected("scan_z: 120", scan_z=120)
        self.assertRejected("image_width: ganze Zahl", image_width=640.5)
        self.assertRejected("image_height: Zahl erwartet", image_height="480")
        self.assertRejected("offset_mm", offset_mm=[300, 0])
        self.assertRejected("offset_mm", offset_mm=[1])
        self.assertRejected("flip_y: \\+1 oder -1", flip_y=0)
        self.assertRejected("crop_fraction", crop_fraction=0.5)
        self.assertRejected("crop_fraction: muss kleiner als 0.4", crop_fraction=0.4)
        self.assertEqual(cc.validate(measured(crop_fraction=0.395))["crop_fraction"], 0.395)
        self.assertRejected("homography: invertierbare", homography=[[0, 0, 0]] * 3)
        self.assertRejected("camera_matrix: 3×3", camera_matrix=[[1, 2], [3, 4]])
        self.assertRejected("dist_coeffs", dist_coeffs=[0.1, 0.2, 0.3])
        self.assertRejected("nur zusammen", dist_coeffs=None)
        self.assertRejected("calibrated: true oder false", calibrated="ja")
        self.assertRejected("notes", notes="x" * 2001)
        self.assertRejected("px_per_mm: endliche Zahl", px_per_mm=float("nan"))

    def test_unknown_fields_format_and_schema(self):
        self.assertRejected("Unbekannte Felder: farbe", farbe="rot")
        self.assertRejected("Unbekanntes Format", format="andere/2")
        self.assertRejected("Schema-Version 2", schema_version=2)
        with self.assertRaisesRegex(ValueError, "JSON-Objekt"):
            cc.validate([1, 2])

    def test_studio_camera_json_and_get_response_are_accepted(self):
        studio = {"format": cc.FORMAT, "image_width": 640, "image_height": 480,
                  "px_per_mm": 4.0, "scan_z": 40.0, "offset_mm": [30.0, -20.0],
                  "rotation_deg": 0.0, "flip_x": 1, "flip_y": 1, "crop_fraction": 0.04,
                  "camera_matrix": None, "dist_coeffs": None, "exposure": None,
                  "comment": "Platzhalter"}
        self.assertEqual(cc.validate(studio)["px_per_mm"], 4.0)
        with tempfile.TemporaryDirectory() as tmp:
            record = cc.CalibrationStore([Path(tmp) / "c.json"]).load()
        self.assertFalse(cc.validate(record)["calibrated"])


WEB_PRELUDE = r"""
import json, os
from marlin import web
c = web.app.test_client()
"""


class ApiTests(unittest.TestCase):
    def run_web(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["LUMACUT_DATA"] = tmp
            env["LUMACUT_CAMERA_CALIBRATION"] = str(Path(tmp) / "etc" / "camera_calibration.json")
            env["PYTHONPATH"] = str(ROOT / "pi400")
            result = subprocess.run([sys.executable, "-c", WEB_PRELUDE + source], env=env,
                                    cwd=ROOT, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_get_put_conflict_and_validation(self):
        data = json.dumps(measured())
        self.run_web(r"""
r = c.get("/api/camera/calibration")
d = r.get_json()
assert r.status_code == 200 and d["placeholder"] and d["revision"] == 0, d
assert d["storage"]["path"] == os.environ["LUMACUT_CAMERA_CALIBRATION"], d
body = json.loads(%r)
body["revision"] = 0
r = c.put("/api/camera/calibration", json=body)
d = r.get_json()
assert r.status_code == 200 and d["revision"] == 1 and d["status"] == "kalibriert", d
assert "Revision 1" in d["message"], d
# Same edit again with the stale revision: 409 with the current record.
r = c.put("/api/camera/calibration", json=body)
assert r.status_code == 409 and "inzwischen geändert" in r.get_json()["error"], r.data
assert r.get_json()["current"]["revision"] == 1
# GET -> edit -> PUT roundtrip keeps working (read-only fields are ignored).
cur = c.get("/api/camera/calibration").get_json()
cur["px_per_mm"] = 8.25
r = c.put("/api/camera/calibration", json=cur)
assert r.status_code == 200 and r.get_json()["revision"] == 2, r.data
assert c.get("/api/camera/calibration").get_json()["px_per_mm"] == 8.25
# Validation errors: 400 in German, file unchanged.
bad = dict(cur, revision=2, scan_z=500)
r = c.put("/api/camera/calibration", json=bad)
assert r.status_code == 400 and "scan_z" in r.get_json()["error"], r.data
r = c.put("/api/camera/calibration", json=dict(cur, revision=None))
assert r.status_code == 400 and "revision fehlt" in r.get_json()["error"], r.data
assert c.get("/api/camera/calibration").get_json()["revision"] == 2
""" % data)

    def test_put_requires_json_and_same_origin(self):
        self.run_web(r"""
r = c.put("/api/camera/calibration", data={"revision": "0"})
assert r.status_code == 415 and "application/json" in r.get_json()["error"], r.data
r = c.put("/api/camera/calibration", data="{kaputt", content_type="application/json")
assert r.status_code == 400 and "Ungültiges JSON" in r.get_json()["error"], r.data
r = c.put("/api/camera/calibration", json={"revision": 0},
          headers={"Origin": "http://evil.example"})
assert r.status_code == 403 and "Fremde Webseite" in r.get_json()["error"], r.data
r = c.put("/api/camera/calibration", json={"revision": 0},
          headers={"Origin": "http://localhost"})
assert r.status_code == 200, r.data
r = c.put("/api/camera/calibration", data="x" * 70000, content_type="application/json")
assert r.status_code == 413, r.status_code
assert c.post("/api/camera/calibration").status_code == 405
""")


class InstallTests(unittest.TestCase):
    def test_install_and_service_allow_atomic_writes_in_etc(self):
        install = (ROOT / "pi400" / "install.sh").read_text(encoding="utf-8")
        unit = (ROOT / "pi400" / "marlin" / "lumacut-marlin.service").read_text(encoding="utf-8")
        self.assertIn("chown root:lumacut /etc/lumacut", install)
        self.assertIn("chmod 1775 /etc/lumacut", install)
        self.assertIn('install -m 600 /dev/null "$PORT_ENV"', install)
        self.assertIn("ReadWritePaths=/var/lib/lumacut -/etc/lumacut", unit)


if __name__ == "__main__":
    unittest.main()
