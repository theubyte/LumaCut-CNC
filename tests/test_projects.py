"""pi400/marlin/projects.py: saved projects every app can open (no machine needed)."""
import json
import tempfile
import unittest
from pathlib import Path

from flask import Flask

from pi400.marlin.projects import ProjectStore, create_blueprint

DOC = {"title": "Karte", "layers": [{"id": "a"}], "elements": [{"id": "e"}, {"id": "f"}], "plateCount": 1}


class ProjectStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ProjectStore(Path(self.tmp.name))
        app = Flask(__name__)
        app.register_blueprint(create_blueprint(self.store))

        @app.errorhandler(ValueError)
        def bad(exc):
            return {"error": str(exc)}, 400
        self.client = app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, name, doc=DOC, by="Tablet"):
        return self.client.post("/api/projects", query_string={"name": name, "by": by},
                                data=json.dumps(doc), content_type="application/json")

    def test_save_list_open_replace_delete(self):
        c = self.client
        self.assertEqual(c.get("/api/projects").get_json(), {"projects": []})
        r = self.save("  Maxim   Einladung ")
        self.assertEqual(r.status_code, 200, r.data)
        p = r.get_json()["project"]
        self.assertEqual((p["name"], p["elements"], p["layers"], p["updated_by"], p["replaced"]),
                         ("Maxim Einladung", 2, 1, "Tablet", False))
        self.save("Schild")
        # same name without case replaces, keeps the id
        r = self.save("maxim einladung", dict(DOC, elements=[]), by="Handy").get_json()["project"]
        self.assertEqual((r["id"], r["replaced"], r["elements"]), (p["id"], True, 0))
        listing = c.get("/api/projects").get_json()["projects"]
        self.assertEqual(sorted(x["name"] for x in listing), ["Schild", "maxim einladung"])
        body = c.get("/api/projects/" + p["id"])
        self.assertEqual(body.status_code, 200)
        self.assertEqual(json.loads(body.data)["elements"], [])
        # survives a restart of the service
        self.assertEqual(len(ProjectStore(Path(self.tmp.name)).list()), 2)
        self.assertEqual(c.delete("/api/projects/" + p["id"]).status_code, 200)
        self.assertEqual(c.get("/api/projects/" + p["id"]).status_code, 404)
        self.assertEqual(c.delete("/api/projects/" + p["id"]).status_code, 404)
        self.assertFalse((Path(self.tmp.name) / (p["id"] + ".json")).exists())

    def test_refuses_what_is_not_a_project(self):
        self.assertEqual(self.save("").status_code, 400)
        self.assertEqual(self.save("x" * 81).status_code, 400)
        self.assertIn("layers", self.save("Leer", {"title": "x"}).get_json()["error"])
        r = self.client.post("/api/projects?name=Kaputt", data=b"{nope", content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get("/api/projects").get_json(), {"projects": []})


if __name__ == "__main__":
    unittest.main()
