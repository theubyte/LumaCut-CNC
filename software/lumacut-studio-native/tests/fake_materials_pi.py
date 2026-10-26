"""Kleiner Fake der Material-API des Pi für Tests (beide Server-Varianten).

``variant="db"``: ``/api/materials`` (Datenbank, ETag, 304) +
``/api/materials/presets[/<id>]`` (If-Match, 412, ``current``).
``variant="list"``: flache Liste mit ``revision``/``base_revision``
(docs/ZUSAMMENARBEIT_CLAUDE_GROK.md Abschnitt 3), 409 bei veralteter Revision.
``variant="none"``: älterer Pi ohne Material-API (404).
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _tag(obj) -> str:
    return '"%s"' % hashlib.sha1(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:12]


LIST_FIELDS = ("id", "name", "thickness_mm", "process", "mode", "power_pct", "speed_mm_min",
               "passes", "interval_mm", "depth_per_pass_mm", "z_step_mm", "builtin", "updated")


def validate_list_material(data: dict, mid: str, builtin: bool = False) -> dict:
    """Gekürzte Fassung von ``pi400/marlin/materials.validate`` (gleiche Grenzen)."""
    def num(key, low, high, default=None):
        raw = data.get(key, default)
        if raw is None or isinstance(raw, bool):
            raise ValueError("%s fehlt" % key)
        value = float(raw)
        if not low <= value <= high:
            raise ValueError("%s muss zwischen %g und %g liegen" % (key, low, high))
        return value
    name = data.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        raise ValueError("name: 1 bis 80 Zeichen")
    if data.get("process") not in ("Schneiden", "Gravieren", "Markieren"):
        raise ValueError("process muss Schneiden, Gravieren oder Markieren sein")
    if data.get("mode") not in ("line", "fill"):
        raise ValueError("mode muss line oder fill sein")
    passes = data.get("passes", 1)
    if isinstance(passes, bool) or not isinstance(passes, (int, float)) or passes != int(passes) \
            or not 1 <= int(passes) <= 30:
        raise ValueError("passes muss eine ganze Zahl zwischen 1 und 30 sein")
    item = {"id": mid, "name": name.strip(), "thickness_mm": num("thickness_mm", 0, 50),
            "process": data["process"], "mode": data["mode"],
            "power_pct": num("power_pct", 0, 100), "speed_mm_min": num("speed_mm_min", 1, 6000),
            "passes": int(passes), "interval_mm": num("interval_mm", 0.01, 5, 0.1),
            "depth_per_pass_mm": num("depth_per_pass_mm", 0, 50, 0.0),
            "z_step_mm": num("z_step_mm", 0, 2, 0.0), "builtin": bool(builtin),
            "updated": "2026-10-26T12:00:00Z"}
    item.update({k: v for k, v in data.items() if k not in LIST_FIELDS and k != "base_revision"})
    passes = item["passes"]
    if item["depth_per_pass_mm"] > 0 and item["thickness_mm"] > 0:
        passes = max(1, math.ceil(item["thickness_mm"] / item["depth_per_pass_mm"] - 1e-9))
        if passes > 30:
            raise ValueError("Dicke / Tiefe je Durchgang ergibt mehr als 30 Durchgänge")
    if (passes - 1) * item["z_step_mm"] > 3.0 + 1e-9:
        raise ValueError("Z-Absenkung über alle Durchgänge höchstens 3 mm")
    return item


class FakeMaterialsPi:
    def __init__(self, db: dict | None = None, variant: str = "db"):
        self.variant = variant
        self.db = db or {}
        self.presets: dict[str, dict] = {}
        self.revision = 1
        self.items: dict[str, dict] = {}  # Variante B
        self.requests: list[tuple[str, str, dict]] = []
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    # -- Hilfen für Tests --------------------------------------------------------
    def put_remote(self, pid: str, data: dict) -> None:
        """Ändern, als hätte ein anderes Gerät geschrieben."""
        with self.lock:
            if self.variant == "list":
                self.items[pid] = dict(data, id=pid)
                self.revision += 1
            else:
                self.presets[pid] = dict(data, id=pid)

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=None, headers=None):
                raw = b"" if body is None else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n)) if n else None

            def _route(self, method):
                url = urllib.parse.urlsplit(self.path)
                body = self._body() if method in ("PUT", "POST") else None
                fake.requests.append((method, self.path, dict(self.headers)))
                with fake.lock:
                    if fake.variant == "none":
                        return self._send(404, {"ok": False, "error": "not found"})
                    if fake.variant == "list":
                        return self._list(method, url, body)
                    return self._db(method, url.path, body)

            def _db(self, method, path, body):
                if path == "/api/materials" and method == "GET":
                    tag = _tag(fake.db)
                    if self.headers.get("If-None-Match") == tag:
                        return self._send(304, None, {"ETag": tag})
                    return self._send(200, {"ok": True, "db": fake.db, "version": fake.db.get("version"),
                                            "etag": tag}, {"ETag": tag})
                if path == "/api/materials/presets" and method == "GET":
                    items = [dict(p, etag=_tag(p)) for p in fake.presets.values()]
                    return self._send(200, {"ok": True, "presets": items}, {"ETag": _tag(items)})
                if path.startswith("/api/materials/presets/"):
                    pid = urllib.parse.unquote(path.rsplit("/", 1)[1])
                    cur = fake.presets.get(pid)
                    match = self.headers.get("If-Match")
                    if match and (cur is None or _tag(cur) != match):
                        return self._send(412, {"ok": False, "error": "Preset geändert",
                                                "current": None if cur is None else dict(cur, etag=_tag(cur))})
                    if method == "PUT":
                        fake.presets[pid] = dict({k: v for k, v in body.items() if k != "etag"}, id=pid)
                        p = fake.presets[pid]
                        return self._send(200, {"ok": True, "preset": p}, {"ETag": _tag(p)})
                    if method == "DELETE":
                        if cur is None:
                            return self._send(404, {"ok": False, "error": "unbekannt"})
                        del fake.presets[pid]
                        return self._send(200, {"ok": True})
                return self._send(405, {"ok": False, "error": "method"})

            def _list(self, method, url, body):
                """Wie pi400/marlin/materials.py + web.py (geprüft gegen den echten Pi,
                tests/test_materials_pi_real.py): erst Revision (400 fehlt / 409),
                dann ID (404), dann Prüfung (400); PUT ergänzt fehlende Felder."""
                path = url.path
                q = urllib.parse.parse_qs(url.query)
                if path == "/api/materials" and method == "GET":
                    return self._send(200, {"revision": fake.revision, "materials": list(fake.items.values())})
                if method in ("POST", "PUT") and not isinstance(body, dict):
                    return self._send(400, {"error": "JSON-Objekt erwartet (Content-Type: application/json)"})
                raw = body.get("base_revision") if body else q.get("base_revision", [None])[0]
                if raw is None or isinstance(raw, bool):
                    return self._send(400, {"error": "base_revision fehlt"})
                if int(raw) != fake.revision:
                    return self._send(409, {"error": "Materialliste wurde inzwischen geändert (Revision %d)"
                                                     % fake.revision, "revision": fake.revision})
                if path == "/api/materials" and method == "POST":
                    mid, old = str(uuid.uuid4()), {}
                elif path.startswith("/api/materials/") and method in ("PUT", "DELETE"):
                    mid = urllib.parse.unquote(path.rsplit("/", 1)[1])
                    if mid not in fake.items:
                        return self._send(404, {"error": "Material nicht gefunden"})
                    old = fake.items[mid]
                else:
                    return self._send(405, {"error": "method"})
                if method == "DELETE":
                    del fake.items[mid]
                    fake.revision += 1
                    return self._send(200, {"revision": fake.revision})
                try:
                    item = validate_list_material({**old, **body}, mid, old.get("builtin", False))
                except ValueError as exc:
                    return self._send(400, {"error": str(exc)})
                fake.items[mid] = item
                fake.revision += 1
                return self._send(200, {"revision": fake.revision, "material": item})

            def do_GET(self):
                self._route("GET")

            def do_PUT(self):
                self._route("PUT")

            def do_POST(self):
                self._route("POST")

            def do_DELETE(self):
                self._route("DELETE")

        return H
