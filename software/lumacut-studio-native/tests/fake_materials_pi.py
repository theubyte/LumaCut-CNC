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
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _tag(obj) -> str:
    return '"%s"' % hashlib.sha1(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:12]


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
                path = url.path
                q = urllib.parse.parse_qs(url.query)
                if path == "/api/materials" and method == "GET":
                    return self._send(200, {"revision": fake.revision, "materials": list(fake.items.values())})
                base = (body or {}).get("base_revision") if body else \
                    int(q["base_revision"][0]) if "base_revision" in q else None
                if base != fake.revision:
                    return self._send(409, {"error": "veraltet", "revision": fake.revision})
                if path == "/api/materials" and method == "POST":
                    mid = str(uuid.uuid4())
                    fake.items[mid] = dict({k: v for k, v in body.items() if k != "base_revision"},
                                           id=mid, updated="now")
                    fake.revision += 1
                    return self._send(200, {"revision": fake.revision, "material": fake.items[mid]})
                mid = urllib.parse.unquote(path.rsplit("/", 1)[1])
                if mid not in fake.items:
                    return self._send(404, {"error": "unbekannt"})
                if method == "PUT":
                    fake.items[mid] = dict({k: v for k, v in body.items() if k != "base_revision"},
                                           id=mid, updated="now")
                    fake.revision += 1
                    return self._send(200, {"revision": fake.revision, "material": fake.items[mid]})
                if method == "DELETE":
                    del fake.items[mid]
                    fake.revision += 1
                    return self._send(200, {"revision": fake.revision})
                return self._send(405, {"error": "method"})

            def do_GET(self):
                self._route("GET")

            def do_PUT(self):
                self._route("PUT")

            def do_POST(self):
                self._route("POST")

            def do_DELETE(self):
                self._route("DELETE")

        return H
