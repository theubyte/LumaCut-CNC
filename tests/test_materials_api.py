"""Material database on the Pi (docs/ZUSAMMENARBEIT_CLAUDE_GROK.md §3)."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi400"))
from marlin.materials import FIELDS, ConflictError, MaterialStore, NotFoundError  # noqa: E402

NEW = {"name": "Buche 4 mm", "thickness_mm": 4.0, "process": "Schneiden", "mode": "line",
       "power_pct": 100.0, "speed_mm_min": 250.0, "passes": 3, "interval_mm": 0.1,
       "depth_per_pass_mm": 0.0, "z_step_mm": 0.5}


class MaterialStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "materials.json"
        self.store = MaterialStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_start_creates_defaults_on_disk(self):
        data = self.store.list()
        self.assertEqual(data["revision"], 1)
        names = [m["name"] for m in data["materials"]]
        self.assertEqual(names, ["Pappelsperrholz", "Pappelsperrholz", "MDF", "Acryl schwarz",
                                 "Leder", "Karton", "Schiefer"])
        for m in data["materials"]:
            self.assertEqual(set(m), set(FIELDS))
            self.assertTrue(m["builtin"])
            self.assertTrue(m["updated"].endswith("Z"))
        acryl = data["materials"][3]
        self.assertEqual((acryl["passes"], acryl["z_step_mm"], acryl["mode"]), (3, 0.5, "line"))
        self.assertEqual(json.loads(self.path.read_text("utf-8")), data)

    def test_revision_conflict_and_persistence(self):
        created = self.store.create(dict(NEW, base_revision=1))
        self.assertEqual(created["revision"], 2)
        material = created["material"]
        self.assertFalse(material["builtin"])
        with self.assertRaises(ConflictError) as ctx:
            self.store.create(dict(NEW, base_revision=1))
        self.assertEqual(ctx.exception.revision, 2)
        updated = self.store.update(material["id"], {"power_pct": 80, "base_revision": 2})
        self.assertEqual(updated["revision"], 3)
        self.assertEqual(updated["material"]["power_pct"], 80.0)
        self.assertEqual(updated["material"]["name"], "Buche 4 mm")
        self.assertEqual(updated["material"]["id"], material["id"])
        # A fresh process sees exactly the same list.
        again = MaterialStore(self.path).list()
        self.assertEqual(again, self.store.list())
        self.assertEqual(self.store.delete(material["id"], "3"), {"revision": 4})
        with self.assertRaises(NotFoundError):
            self.store.delete(material["id"], 4)
        with self.assertRaises(ConflictError):
            self.store.delete(self.store.list()["materials"][0]["id"], 3)

    def test_builtin_stays_builtin_when_edited(self):
        first = self.store.list()["materials"][0]
        result = self.store.update(first["id"], {"builtin": False, "speed_mm_min": 300,
                                                 "base_revision": 1})
        self.assertTrue(result["material"]["builtin"])
        self.assertEqual(result["material"]["speed_mm_min"], 300.0)

    def test_limits(self):
        bad = [
            {"power_pct": 100.5}, {"power_pct": -1}, {"speed_mm_min": 0.5},
            {"speed_mm_min": 6001}, {"passes": 0}, {"passes": 31}, {"passes": 2.5},
            {"z_step_mm": 2.1}, {"passes": 3, "z_step_mm": 2.0},          # 4 mm in total
            {"thickness_mm": 6, "depth_per_pass_mm": 1.0, "z_step_mm": 0.7},  # 6 passes, 3.5 mm
            {"process": "Fräsen"}, {"mode": "raster"}, {"name": " "}, {"power_pct": "viel"},
            {"power_pct": float("nan")},
        ]
        for change in bad:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.store.create(dict(NEW, base_revision=1, **change))
        self.assertEqual(self.store.list()["revision"], 1)
        ok = self.store.create(dict(NEW, base_revision=1, passes=7, z_step_mm=0.5))   # 3 mm
        self.assertEqual(ok["revision"], 2)
        with self.assertRaises(ValueError):
            self.store.create(dict(NEW))   # base_revision missing

    def test_corrupt_file_is_kept_and_defaults_return(self):
        self.path.write_text("{kaputt", encoding="utf-8")
        data = self.store.list()
        self.assertEqual(data["revision"], 1)
        self.assertEqual(len(data["materials"]), 7)
        self.assertEqual(self.path.with_suffix(".corrupt").read_text("utf-8"), "{kaputt")

    def test_parallel_writers_only_one_wins(self):
        results = []

        def write(i):
            try:
                results.append(self.store.create(dict(NEW, name="M%d" % i, base_revision=1)))
            except ConflictError:
                results.append(None)
        threads = [threading.Thread(target=write, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(self.store.list()["revision"], 2)


class MaterialHttpTests(unittest.TestCase):
    def test_http_contract(self):
        source = r"""
import json
from marlin import web
c = web.app.test_client()
r = c.get("/api/materials")
assert r.status_code == 200, r.data
data = r.get_json()
assert data["revision"] == 1 and len(data["materials"]) == 7, data
new = {"name": "Kork", "thickness_mm": 2, "process": "Gravieren", "mode": "fill",
       "power_pct": 20, "speed_mm_min": 2000}
r = c.post("/api/materials", json=dict(new, base_revision=1))
assert r.status_code == 200, r.data
body = r.get_json()
assert body["revision"] == 2 and body["material"]["passes"] == 1, body
mid = body["material"]["id"]
r = c.post("/api/materials", json=dict(new, base_revision=1))
assert r.status_code == 409 and r.get_json()["revision"] == 2, r.data
assert "neu laden" in r.get_json()["error"]
r = c.put("/api/materials/" + mid, json={"power_pct": 30, "base_revision": 2})
assert r.status_code == 200 and r.get_json()["material"]["power_pct"] == 30, r.data
r = c.put("/api/materials/" + mid, json={"power_pct": 300, "base_revision": 3})
assert r.status_code == 400 and "power_pct" in r.get_json()["error"], r.data
r = c.put("/api/materials/unbekannt", json={"power_pct": 30, "base_revision": 3})
assert r.status_code == 404, r.data
r = c.post("/api/materials", data="kein json", content_type="text/plain")
assert r.status_code == 400, r.data
r = c.delete("/api/materials/%s?base_revision=2" % mid)
assert r.status_code == 409 and r.get_json()["revision"] == 3, r.data
r = c.delete("/api/materials/%s?base_revision=3" % mid)
assert r.status_code == 200 and r.get_json() == {"revision": 4}, r.data
r = c.delete("/api/materials/%s" % mid)
assert r.status_code == 400, r.data
stored = json.loads((web.DATA.parent / "materials.json").read_text("utf-8"))
assert stored["revision"] == 4 and len(stored["materials"]) == 7, stored
"""
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["LUMACUT_DATA"] = tmp
            env["PYTHONPATH"] = str(ROOT / "pi400")
            result = subprocess.run([sys.executable, "-c", source], env=env, cwd=ROOT,
                                    text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(tmp) / "materials.json").is_file())


if __name__ == "__main__":
    unittest.main()
