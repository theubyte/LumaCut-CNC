"""pi400/marlin/workspace.py: the shared work state every app sees (no machine needed)."""
import tempfile
import unittest
from pathlib import Path

from flask import Flask

from pi400.marlin.workspace import WorkspaceStore, create_blueprint

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = WorkspaceStore(Path(self.tmp.name))
        app = Flask(__name__)
        app.register_blueprint(create_blueprint(self.store))

        @app.errorhandler(ValueError)
        def bad(exc):
            return {"error": str(exc)}, 400
        self.client = app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_state_revisions_and_conflict(self):
        c = self.client
        self.assertEqual(c.get("/api/workspace").get_json()["revision"], 0)
        r = c.put("/api/workspace", json={"material": {"name": "MDF", "thickness_mm": 3}, "areas": [[10, 20, 60, 80]],
                                          "base_revision": 0, "updated_by": "Tablet"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.get_json()["revision"], 1)
        self.assertEqual(self.store.material_thickness(), 3.0)
        # a second device still on revision 0: refused, nothing overwritten
        r = c.put("/api/workspace", json={"areas": [], "base_revision": 0})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["revision"], 1)
        self.assertEqual(c.get("/api/workspace").get_json()["areas"], [[10.0, 20.0, 60.0, 80.0]])
        # only the given keys change
        c.put("/api/workspace", json={"settings": {"gridPower": 30}, "base_revision": 1})
        state = c.get("/api/workspace").get_json()
        self.assertEqual(state["material"]["name"], "MDF")
        self.assertEqual(state["settings"], {"gridPower": 30})
        self.assertEqual(self.store.revisions()["workspace"], 2)
        # survives a restart of the service
        self.assertEqual(WorkspaceStore(Path(self.tmp.name)).get_state()["areas"], [[10.0, 20.0, 60.0, 80.0]])

    def test_material_limits_and_change_callback(self):
        seen = []
        self.store.on_change = lambda s: seen.append(s["material"])
        for bad in ({"material": {"name": "Klotz", "thickness_mm": 61}}, {"material": {"thickness_mm": 3}},
                    {"areas": [[0, 0, 500, 10]]}, {"color": "rot"}, {"settings": {"x": [1, 2]}}):
            r = self.client.put("/api/workspace", json=bad)
            self.assertEqual(r.status_code, 400, (bad, r.data))
        self.assertEqual(self.client.put("/api/workspace", json={"material": {"name": "Hoch", "thickness_mm": 60}}).status_code, 200)
        self.assertEqual(seen, [{"name": "Hoch", "thickness_mm": 60.0}])
        self.client.put("/api/workspace", json={"material": None})
        self.assertIsNone(self.store.material_thickness())

    def test_project_and_scan_with_revisions(self):
        c = self.client
        self.assertEqual(c.get("/api/workspace/project").status_code, 404)
        r = c.put("/api/workspace/project?base_revision=0&by=Tablet", data=b'{"title": "Schild", "plates": []}')
        self.assertEqual(r.get_json()["revision"], 1)
        self.assertEqual(r.get_json()["title"], "Schild")
        r = c.get("/api/workspace/project")
        self.assertEqual(r.headers["X-Revision"], "1")
        self.assertEqual(r.get_json()["title"], "Schild")
        self.assertEqual(c.put("/api/workspace/project?base_revision=0", data=b'{"title": "alt"}').status_code, 409)
        self.assertEqual(c.put("/api/workspace/project", data=b"kein json").status_code, 400)
        self.assertEqual(c.put("/api/workspace/scan?base_revision=0", data=b"GIF89a").status_code, 400)
        self.assertEqual(c.put("/api/workspace/scan?base_revision=0", data=PNG).status_code, 200)
        r = c.get("/api/workspace/scan")
        self.assertEqual((r.data, r.headers["X-Revision"], r.mimetype), (PNG, "1", "image/png"))
        self.assertEqual(c.delete("/api/workspace/scan?base_revision=1").status_code, 200)
        self.assertEqual(c.get("/api/workspace/scan").status_code, 404)
        self.assertEqual(self.store.revisions(), {"workspace": 0, "project": 1, "scan": 2})


if __name__ == "__main__":
    unittest.main()
