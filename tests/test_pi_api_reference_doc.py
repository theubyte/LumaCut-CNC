"""docs/PI_API_REFERENZ.md must cover every Pi HTTP route, op and status field.

Reads pi400/marlin/web.py, transport.py and camera_calibration.py with ast
(no Flask import needed) and fails when the reference misses something, or
documents an op that no longer exists, so the doc cannot silently drift.
"""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARLIN = ROOT / "pi400" / "marlin"
DOC = ROOT / "docs" / "PI_API_REFERENZ.md"


def _tree(name):
    return ast.parse((MARLIN / name).read_text(encoding="utf-8"))


def _function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("function %s not found" % name)


def _routes(tree, owner):
    """(METHOD, path) for every @<owner>.get/post/put/delete/route decorator."""
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for deco in node.decorator_list:
            if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                    and isinstance(deco.func.value, ast.Name) and deco.func.value.id == owner):
                continue
            method = deco.func.attr.upper()
            if method in ("AFTER_REQUEST", "ERRORHANDLER"):
                continue
            path = deco.args[0].value
            if method == "ROUTE":
                methods = [k for k in deco.keywords if k.arg == "methods"]
                method = ",".join(e.value for e in methods[0].value.elts) if methods else "GET"
            found.add((method, path))
    return found


def _ops():
    """Every string compared with ``op`` inside web.action()."""
    ops = set()
    for node in ast.walk(_function(_tree("web.py"), "action")):
        if not (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)
                and node.left.id == "op"):
            continue
        for operator, right in zip(node.ops, node.comparators):
            if isinstance(operator, ast.Eq) and isinstance(right, ast.Constant):
                ops.add(right.value)
            elif isinstance(operator, ast.In) and isinstance(right, (ast.Tuple, ast.List)):
                ops.update(e.value for e in right.elts if isinstance(e, ast.Constant))
    return ops


def _dict_keys(node):
    return [k.value for k in node.keys if isinstance(k, ast.Constant)]


def _module_dict(tree, name):
    for node in tree.body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)):
            return _dict_keys(node.value)
    raise AssertionError("dict %s not found" % name)


def _status_fields():
    web = _tree("web.py")
    fields = set(_module_dict(web, "_LIVE_STATUS_FIELDS"))
    for node in ast.walk(_function(web, "status")):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "update":
            fields.update(k.arg for k in node.keywords)
    transport = _tree("transport.py")
    for node in ast.walk(_function(transport, "status")):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            fields.update(_dict_keys(node.value))
    return fields


def _doc_path(path):
    return re.sub(r"<(?:\w+:)?\w+>", "<name>", path)


class PiApiReferenceDocTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = DOC.read_text(encoding="utf-8")

    def test_every_route_is_documented_with_its_method(self):
        routes = (_routes(_tree("web.py"), "app") | _routes(_tree("camera_calibration.py"), "blueprint")
                  | _routes(_tree("workspace.py"), "bp"))
        self.assertGreaterEqual(len(routes), 14, routes)
        for method, path in sorted(routes):
            row = "| %s | `%s` |" % (method, _doc_path(path))
            self.assertIn(row, self.doc, "Route fehlt in der Übersicht: %s %s" % (method, path))

    def test_every_op_is_documented_and_no_stale_ops(self):
        ops = _ops()
        self.assertIn("estop", ops)
        self.assertIn("queue_run", ops)
        for op in sorted(ops):
            self.assertIn("`op=%s`" % op, self.doc, "op fehlt: " + op)
        documented = set(re.findall(r"`op=([a-z_]+)`", self.doc))
        self.assertEqual(documented - ops, set(), "Dokument nennt nicht existierende ops")

    def test_every_status_field_is_documented(self):
        fields = _status_fields()
        self.assertGreater(len(fields), 40, fields)
        for field in sorted(fields):
            self.assertIn("| `%s` |" % field, self.doc, "Statusfeld fehlt: " + field)

    def test_nested_status_objects_match(self):
        web = _tree("web.py")
        for name in ("job", "frame"):
            keys = _module_dict(web, name)
            self.assertIn("`{%s}`" % ", ".join(keys), self.doc, name)
        queue = _function(web, "_queue_status")
        returned = [n.value for n in ast.walk(queue) if isinstance(n, ast.Return)][0]
        self.assertIn("`{%s}`" % ", ".join(_dict_keys(returned)), self.doc, "queue")
        origin = _function(web, "_origin_status")
        returned = [n.value for n in ast.walk(origin) if isinstance(n, ast.Return)][0]
        self.assertIn("`{%s}`" % ", ".join(_dict_keys(returned)), self.doc, "origin")
        add = _function(web, "queue_add")
        item = [n for n in ast.walk(add) if isinstance(n, ast.Dict) and "sha" in _dict_keys(n)][0]
        for key in _dict_keys(item):
            if key != "sha":
                self.assertIn("`items[].%s`" % key, self.doc, "Warteschlangen-Feld fehlt: " + key)
        for key in _module_dict(web, "config"):
            self.assertIn("`%s`" % key, self.doc, "config-Feld fehlt: " + key)

    def test_documented_limits_match_code(self):
        web = (MARLIN / "web.py").read_text(encoding="utf-8")
        self.assertIn("STATUS_LOCK_WAIT_S = 0.25", web)
        self.assertIn("0,25 s", self.doc)
        self.assertIn("QUEUE_MAX = 50", web)
        self.assertIn("FRAME_MAX_MOVES = 2000", web)
        self.assertIn("FRAME_MAX_BYTES = 64 * 1024", web)
        self.assertIn("-10.0,-1.0,-0.1,0.1,1.0,10.0", web)
        self.assertIn("`-10`, `-1`, `-0.1`, `0.1`, `1`, `10`", self.doc)

    def test_linked_from_readme_and_api_docs(self):
        for path in ("README.md", "docs/PI_BETRIEB.md",
                     "software/lumacut-studio-native/docs/MACHINE_API.md"):
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertIn("PI_API_REFERENZ.md", text, path)


if __name__ == "__main__":
    unittest.main()
