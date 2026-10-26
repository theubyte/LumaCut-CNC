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
    # Same keys as web.py ``job`` (no "phase": the real Pi sends none).
    "job": {"file": "", "state": "idle", "line": 0, "total": 0, "error": "",
            "probe": None},
    "frame": {"state": "idle", "mode": "", "line": 0, "total": 0, "error": ""},
    "activity": "idle",
    # Job origin support (#16); an older Pi has no "origin" key.
    "origin": {"modes": ["absolute", "current", "user"],
               "anchors": ["tl", "tr", "bl", "br", "center"],
               "coord_convention": "origin_top_right",
               "user": None, "placement": None},
    # Job queue (#17); a Pi before #17 has no "queue" key.
    "queue": {"items": [], "state": "idle", "current": None, "max": 50},
    "firmware": "marlin", "config": {"focus_gap_mm": 7.0},
    # Anchor semantics (2026-10-26): "tr" = endstop corner. Older Pi: missing.
    "coord_convention": "origin_top_right",
}

ACTIONS = ("home", "jog", "probe", "light", "exhaust", "start", "autorun",
           "abort", "estop", "estop_reset", "connect", "park", "frame",
           "origin_set", "origin_clear", "place", "place_clear",
           "queue_add", "queue_run", "queue_pause", "queue_skip", "queue_remove",
           "queue_clear")
#: Ops an older Pi service (before #16) does not know.
ORIGIN_ACTIONS = ("origin_set", "origin_clear", "place", "place_clear")
#: Ops a Pi service before the job queue (#17) does not know.
QUEUE_ACTIONS = ("queue_add", "queue_run", "queue_pause", "queue_skip",
                 "queue_remove", "queue_clear")


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
        #: requests currently held back by ``delay``, keyed like delay
        self.waiting: dict[str, int] = {}
        #: number of requests to drop without any answer, keyed like delay
        self.drop: dict[str, int] = {}
        #: raw bytes to send instead of the status JSON (malformed answers)
        self.raw_status: bytes | None = None
        #: names of uploaded jobs, in order (framing must never add one)
        self.uploads: list[str] = []
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
                    with fake.lock:
                        fake.waiting[key] = fake.waiting.get(key, 0) + 1
                    try:
                        time.sleep(delay)
                    finally:
                        with fake.lock:
                            fake.waiting[key] -= 1
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
                    # Like web.py: start and queue_run need a homed machine,
                    # op=autorun homes itself (and probes) when needed.
                    unhomed = {"start": "Vor dem Job referenzieren",
                               "queue_run": "Vor der Warteschlange referenzieren"}
                    if op in unhomed and not fake.status.get("homed"):
                        return self._reply(400, {"error": unhomed[op]})
                    if op == "frame":
                        # Like web.py start_frame: own state, job untouched.
                        moves = [l for l in form.get("gcode", "").splitlines()
                                 if l.strip().upper().startswith(("G0", "G1"))]
                        with fake.lock:
                            fake.status["frame"] = {"state": "running",
                                                    "mode": form.get("mode", "box"),
                                                    "line": 0, "total": len(moves),
                                                    "error": ""}
                            fake.status["owner"] = "frame"
                            fake.status["activity"] = "framing"
                        return self._reply(200, {"message": "Rahmenfahrt gestartet",
                                                 "frame": fake.status["frame"]})
                    if op in ORIGIN_ACTIONS:
                        return self._reply(200, fake._origin_op(op, form))
                    if op in QUEUE_ACTIONS:
                        code, data = fake._queue_op(op, form)
                        return self._reply(code, data)
                    return self._reply(200, {"message": "ok " + op})
                if self.path == "/api/upload":
                    if self._hiccup("upload"):
                        return
                    if "upload" in fake.fail:
                        code, data = fake.fail["upload"]
                        return self._reply(code, data)
                    name = entry["body"].split(b'filename="', 1)[-1].split(b'"', 1)[0]
                    with fake.lock:
                        fake.uploads.append(name.decode("utf-8", "replace"))
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

    @property
    def status_waiting(self) -> bool:
        """True while a /api/status request is held back by ``delay``."""
        with self.lock:
            return self.waiting.get("status", 0) > 0

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def make_older_pi(self) -> None:
        """Behave like a Pi service before job origins (#16) and the queue (#17)."""
        with self.lock:
            self.status.pop("origin", None)
            self.actions -= set(ORIGIN_ACTIONS)
        self.make_pre_queue_pi()

    def make_pre_autorun_pi(self) -> None:
        """Behave like a Pi service without the one-click op=autorun."""
        with self.lock:
            self.actions.discard("autorun")

    def set_features(self, *names: str) -> None:
        """``features`` like web.py FEATURES (e.g. "autorun_mesh",
        "materials"); no names = drop the key like an older Pi. Opt-in so
        tests of the Studio-side mesh path keep their behaviour."""
        with self.lock:
            if names:
                self.status["features"] = list(names)
            else:
                self.status.pop("features", None)

    def set_job_phase(self, state: str, probe: tuple[int, int] | None = None,
                      phase: str | None = None, file: str = "a.gcode",
                      line: int | None = None, total: int | None = None) -> None:
        """Mirror the one-click status of web.py ``_execute_job``: job.state
        homing/probing/running/complete/error/aborted and job.probe while
        probing. The real Pi sends no job.phase (it parks while "running"
        with line == total); ``phase`` simulates a finer future Pi."""
        with self.lock:
            job = dict(self.status.get("job") or {})
            job.update({"file": file, "state": state})
            if line is not None:
                job["line"] = line
            if total is not None:
                job["total"] = total
            job.pop("probe", None)
            job.pop("phase", None)
            if probe is not None:
                job["probe"] = {"done": probe[0], "total": probe[1]}
            if phase is not None:
                job["phase"] = phase
            self.status["job"] = job

    def make_pre_queue_pi(self) -> None:
        """Behave like a Pi service with origins (#16) but no job queue (#17)."""
        with self.lock:
            self.status.pop("queue", None)
            self.actions -= set(QUEUE_ACTIONS)

    def _queue_op(self, op: str, form: dict) -> tuple[int, dict]:
        """Simplified web.py queue ops (no placement math, no motion)."""
        with self.lock:
            q = self.status["queue"]
            items = q["items"]
            if op == "queue_add":
                ids = [i["id"] for i in items]
                items.append({"id": max(ids, default=0) + 1, "file": form.get("name"),
                              "origin": form.get("origin") or "absolute",
                              "anchor": form.get("anchor") or "tr", "dx": 0.0, "dy": 0.0,
                              "target": None, "bounds": None, "state": "queued",
                              "error": ""})
            elif op == "queue_run":
                waiting = [i for i in items if i["state"] == "queued"]
                if not waiting:
                    return 400, {"error": "Keine wartenden Aufträge in der Warteschlange"}
                waiting[0]["state"] = "running"
                q.update(state="running", current=waiting[0]["id"])
                self.status["owner"] = "job"
                self.status["activity"] = "job"
            elif op == "queue_pause":
                q["state"] = "pausing"
            elif op == "queue_clear":
                q["items"] = [i for i in items if i["state"] == "running"]
            else:
                item = next((i for i in items if str(i["id"]) == form.get("id")), None)
                if item is None:
                    return 400, {"error": "Warteschlangen-Eintrag nicht gefunden"}
                if op == "queue_skip":
                    item["state"] = "skipped"
                else:
                    items.remove(item)
            return 200, {"message": "ok " + op, "queue": json.loads(json.dumps(q))}

    def finish_queue(self, state: str = "complete", item_state: str = "done",
                     error: str = "") -> None:
        """End the simulated queue run: the running item gets ``item_state``."""
        with self.lock:
            q = self.status["queue"]
            for item in q["items"]:
                if item["state"] == "running":
                    item.update(state=item_state, error=error)
            if state == "complete":
                for item in q["items"]:
                    if item["state"] == "queued":
                        item["state"] = "done"
            q.update(state=state, current=None)
            self.status["owner"] = "Frei"
            self.status["activity"] = "idle"

    def _origin_op(self, op: str, form: dict) -> dict:
        """Simplified web.py origin ops (no geometry: dx/dy = target)."""
        with self.lock:
            origin = self.status["origin"]
            if op == "origin_set":
                x = form.get("x"); y = form.get("y")
                pos = self.status["position"]
                origin["user"] = [float(x), float(y)] if x else [pos[0], pos[1]]
                origin["placement"] = None
            elif op == "origin_clear":
                origin["user"] = None
            elif op == "place":
                origin["placement"] = {"file": form.get("name"),
                                       "origin": form.get("origin"),
                                       "anchor": form.get("anchor") or "tr",
                                       "dx": 0.0, "dy": 0.0}
            else:
                origin["placement"] = None
            return {"message": "ok " + op, "origin": json.loads(json.dumps(origin))}

    def finish_frame(self, state: str = "complete", error: str = "") -> None:
        """End the simulated frame run (complete/aborted/error)."""
        with self.lock:
            frame = dict(self.status["frame"], state=state, error=error)
            frame["line"] = frame["total"] if state == "complete" else frame["line"]
            self.status["frame"] = frame
            self.status["owner"] = "Frei"
            self.status["activity"] = "idle"

    def last(self, path: str | None = None) -> dict:
        with self.lock:
            items = [r for r in self.requests if path is None or r["path"] == path]
        return items[-1]
