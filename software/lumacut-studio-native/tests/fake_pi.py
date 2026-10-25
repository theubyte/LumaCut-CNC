"""Tiny fake of the Pi 400 HTTP API (pi400/marlin/web.py) for tests."""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATUS = {
    "connected": True, "state": "Idle", "owner": "Frei", "identity": "LumaCut",
    "homed": True, "z_homed": True, "homing_verified": True,
    "position": [120.5, 80.25, 20.0], "fault": "", "lights": False,
    "exhaust": False, "laser_armed": False, "laser_cooling_fan_on": False,
    "emergency_latched": False, "workpiece_surface_z": None,
    "laser_focus_z": None, "probe_xy_offset_mm": [-23.0, 15.0],
    "job": {"file": "", "state": "idle", "line": 0, "total": 0, "error": ""},
    "firmware": "marlin", "config": {"focus_gap_mm": 7.0},
}

ACTIONS = ("home", "jog", "probe", "light", "exhaust", "start", "autorun",
           "abort", "estop", "estop_reset", "connect", "park")


class FakePi:
    def __init__(self, required_key: str | None = None):
        self.required_key = required_key
        self.requests: list[dict] = []
        self.status = json.loads(json.dumps(STATUS))
        self.actions = set(ACTIONS)
        self.fail: dict[str, tuple[int, dict]] = {}
        self.redirect = False
        #: seconds to sleep before answering, keyed by "status" or an op
        #: (simulates the Pi holding machine.lock during home/park/probe)
        self.delay: dict[str, float] = {}
        #: number of requests to drop without any answer, keyed like delay
        self.drop: dict[str, int] = {}
        #: raw bytes to send instead of the status JSON (malformed answers)
        self.raw_status: bytes | None = None
        self.lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, code, data, headers=None):
                raw = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            def _record(self, body=b""):
                entry = {"method": self.command, "path": self.path,
                         "headers": self.headers, "body": body}
                with fake.lock:
                    fake.requests.append(entry)
                return entry

            def _hiccup(self, key):
                """Apply delay/drop for key. Returns True if the request was dropped."""
                with fake.lock:
                    delay = fake.delay.get(key, 0.0)
                    dropped = fake.drop.get(key, 0) > 0
                    if dropped:
                        fake.drop[key] -= 1
                if delay:
                    time.sleep(delay)
                if dropped:
                    self.close_connection = True
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                return dropped

            def _auth(self):
                if fake.required_key and self.headers.get("X-LumaCut-Key") != fake.required_key:
                    self._reply(401, {"error": "Schlüssel fehlt oder falsch"})
                    return False
                return True

            def do_GET(self):
                self._record()
                if fake.redirect:
                    return self._reply(302, {}, {"Location": "http://127.0.0.1:9/evil"})
                if not self._auth():
                    return
                if self.path == "/api/status":
                    if self._hiccup("status"):
                        return
                    if "status" in fake.fail:
                        code, data = fake.fail["status"]
                        return self._reply(code, data)
                    if fake.raw_status is not None:
                        raw = fake.raw_status
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(raw)))
                        self.end_headers()
                        self.wfile.write(raw)
                        return
                    return self._reply(200, fake.status)
                if self.path == "/api/jobs":
                    return self._reply(200, {"files": [{"name": "a.gcode", "bytes": 3}]})
                if self.path.startswith("/api/jobs/") and self.path.endswith("/geometry"):
                    return self._reply(200, {"bounds": {}, "center": [50, 50]})
                self._reply(404, {"error": "nicht gefunden"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                entry = self._record(self.rfile.read(length))
                if not self._auth():
                    return
                if self.path == "/api/action":
                    form = dict(urllib.parse.parse_qsl(entry["body"].decode()))
                    entry["form"] = form
                    op = form.get("op", "")
                    if self._hiccup(op):
                        return
                    if op in fake.fail:
                        code, data = fake.fail[op]
                        return self._reply(code, data)
                    if op not in fake.actions:
                        return self._reply(400, {"error": "Unbekannte Marlin-Aktion: " + op})
                    return self._reply(200, {"message": "ok " + op})
                if self.path == "/api/upload":
                    if "upload" in fake.fail:
                        code, data = fake.fail["upload"]
                        return self._reply(code, data)
                    return self._reply(200, {"message": "Marlin-Auftrag geprüft und gespeichert"})
                self._reply(404, {"error": "nicht gefunden"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def last(self, path: str | None = None) -> dict:
        with self.lock:
            items = [r for r in self.requests if path is None or r["path"] == path]
        return items[-1]
