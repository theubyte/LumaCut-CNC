"""Bedienpanel am USB des Pi (Waveshare ESP32-S3-Touch-LCD-7, firmware/panel).

The panel is one more client like the web UI and the apps: every action it
asks for goes through the Pi's own HTTP API on 127.0.0.1, so owner, homing,
release and G-code guard stay on the Pi. The panel only shows and asks.

It is connected to the native USB-C socket of the ESP32-S3 (Espressif
USB-Serial/JTAG, vendor 303a) and talks in JSON lines:

panel -> Pi   {"t": "hello"}  {"t": "ping", "cam": 0|1}  {"t": "jobs"}
              {"t": "act", "id": n, "op": ..., <fields>}
Pi -> panel   {"t": "st", ...}            compact status, every 0.5..1 s
              {"t": "res", "id": n, "ok": bool, "msg": str}
              {"t": "jobs", "files": [{"name", "kb"}]}
              {"t": "img", "w": w, "h": h, "len": n} + n bytes JPEG

The panel's serial port is never the SKR: Marlin is found by its own path,
and grbl_bridge.open_controller() skips Espressif devices.
"""
from __future__ import annotations

import bisect
import glob
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LOG = logging.getLogger("lumacut.panel")
ESPRESSIF_VID = "303a"
CAMERA_SIZE = (640, 480)
CONTENT_LIMIT = 8 * 1024 * 1024    # larger jobs show no laser power/feed
PING_TIMEOUT_S = 5.0

# What the panel may ask for, and which form fields pass through.
ACTIONS = {
    "estop": (),
    "estop_reset": (),
    "abort": (),
    "home": ("clear",),
    "jog": ("axis", "distance"),
    "probe": (),
    "park": (),
    "light": ("on",),
    "exhaust": ("on",),
    "queue_pause": (),
    "queue_run": (),
    "autorun": ("name", "clear"),
    "frame_job": ("name",),
}
SLOW = {"home": 200, "probe": 120, "park": 90, "estop_reset": 30, "jog": 60}

_S = re.compile(r"\bS\s*([-+]?\d*\.?\d+)", re.I)
_F = re.compile(r"\bF\s*([-+]?\d*\.?\d+)", re.I)
_CODE = re.compile(r"^\s*([GM])\s*0*(\d+)", re.I)


def usb_vendor(port: str, sys_root: Path = Path("/sys")) -> str:
    """USB vendor id (lower-case hex) of a tty, "" if unknown."""
    try:
        name = os.path.basename(os.path.realpath(port))
        node = (sys_root / "class" / "tty" / name / "device").resolve()
    except OSError:
        return ""
    for folder in (node, *node.parents):
        vid = folder / "idVendor"
        if vid.is_file():
            try:
                return vid.read_text().strip().lower()
            except OSError:
                return ""
        if folder == sys_root:
            break
    return ""


def is_panel(port: str, sys_root: Path = Path("/sys")) -> bool:
    return "espressif" in port.lower() or usb_vendor(port, sys_root) == ESPRESSIF_VID


def find_panel(dev_root: Path = Path("/dev"), sys_root: Path = Path("/sys")) -> str | None:
    by_id = sorted(glob.glob(str(dev_root / "serial" / "by-id" / "*Espressif*")))
    if by_id:
        return by_id[0]
    for port in sorted(glob.glob(str(dev_root / "ttyACM*"))):
        if usb_vendor(port, sys_root) == ESPRESSIF_VID:
            return port
    return None


def frame_gcode(bounds: dict) -> str:
    """Rectangle around the laser paths, laser off (same as the web UI)."""
    x0, y0, x1, y1 = (round(float(bounds[k]), 2) for k in ("xmin", "ymin", "xmax", "ymax"))
    return "\n".join(["G21", "G90", "G0 X%s Y%s F6000" % (x0, y0), "G0 X%s Y%s" % (x1, y0),
                      "G0 X%s Y%s" % (x1, y1), "G0 X%s Y%s" % (x0, y1), "G0 X%s Y%s" % (x0, y0)])


class JobTrace:
    """Laser power and feed at a job line, read from the job file.

    autorun splits lines for the focus correction, so job.line/total count
    the processed program; the position in the file is taken in proportion.
    """

    def __init__(self, text: str):
        self.lines = 0
        self.power: list[tuple[int, float]] = []
        self.feed: list[tuple[int, float]] = []
        for self.lines, line in enumerate(text.splitlines(), 1):
            line = line.split(";", 1)[0]
            code = _CODE.match(line)
            if not code:
                continue
            kind, num = code.group(1).upper(), int(code.group(2))
            if kind == "M" and num == 5:
                self.power.append((self.lines, 0.0))
                continue
            if (kind, num) in (("G", 1), ("M", 3), ("M", 4)):
                s = _S.search(line)
                if s:
                    self.power.append((self.lines, float(s.group(1))))
            if (kind, num) == ("G", 1):
                f = _F.search(line)
                if f:
                    self.feed.append((self.lines, float(f.group(1))))

    @staticmethod
    def _at(points, line):
        i = bisect.bisect_right(points, (line, float("inf"))) - 1
        return points[i][1] if i >= 0 else None

    def at(self, line: int, total: int) -> tuple[float | None, float | None]:
        if not self.lines or total <= 0:
            return None, None
        pos = max(1, round(line * self.lines / total))
        return self._at(self.power, pos), self._at(self.feed, pos)


ACTIVE = ("homing", "probing", "running")


def compact(s: dict, now: float, clock: str, track: dict, trace: JobTrace | None) -> dict:
    """The panel's view of /api/status (small: it travels every second).

    track keeps the start of the running job between calls (elapsed time).
    """
    job = s.get("job") or {}
    state, line, total = job.get("state") or "idle", job.get("line") or 0, job.get("total") or 0
    if state in ACTIVE:
        if track.get("file") != job.get("file") or track.get("start") is None:
            track.update(file=job.get("file"), start=now)
    else:
        track["start"] = None
    elapsed = int(now - track["start"]) if track.get("start") is not None else None
    remain = None
    if elapsed is not None and state == "running" and total and line > total * 0.02:
        remain = int(elapsed * (total - line) / line)
    power = feed = None
    if trace is not None and state == "running":
        power, feed = trace.at(line, total)
    config = s.get("config") or {}
    probe = job.get("probe")
    origin = s.get("origin") or {}
    placed = (origin.get("placement") or {}).get("file")
    return {
        "t": "st",
        "time": clock,
        "conn": bool(s.get("connected")),
        "owner": s.get("owner") or "Frei",
        "homed": bool(s.get("homed")),
        "latched": bool(s.get("emergency_latched")),
        "fault": s.get("fault") or "",
        "armed": bool(s.get("laser_armed")),
        "supply": bool(s.get("laser_cooling_fan_on")),
        "exhaust": bool(s.get("exhaust")),
        "lights": bool(s.get("lights")),
        "pos": s.get("position"),
        "act": s.get("activity") or "idle",
        "clear": bool(s.get("home_needs_confirm")),
        "valid": bool(config.get("validated")),
        "cool": s.get("cooldown_remaining_s"),
        "placed": placed or "",
        "job": {
            "file": job.get("file") or "",
            "state": state,
            "phase": job.get("phase") or "",
            "line": line,
            "total": total,
            "error": job.get("error") or "",
            "probe": [probe.get("done", 0), probe.get("total", 0)] if isinstance(probe, dict) else None,
        },
        "queue": (s.get("queue") or {}).get("state") or "idle",
        "frame": (s.get("frame") or {}).get("state") or "idle",
        "elapsed": elapsed,
        "remain": remain,
        "power": None if power is None else round(power / 2.55),
        "feed": None if feed is None else round(feed),
    }


class Api:
    """The Pi's own HTTP API on 127.0.0.1."""

    def __init__(self, port: int):
        self.base = "http://127.0.0.1:%d" % port

    def call(self, method: str, path: str, form: dict | None = None, timeout: float = 15):
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as err:
            return err.code, err.read(), err.headers.get("Content-Type", "")

    def json(self, method: str, path: str, form: dict | None = None, timeout: float = 15):
        status, body, _ = self.call(method, path, form, timeout)
        try:
            data = json.loads(body.decode("utf-8"))
        except ValueError:
            data = {"error": "Pi antwortet mit HTTP %d" % status}
        return status, data


class PanelBridge:
    def __init__(self, api, serial_factory=None, finder=find_panel, clock=time.time):
        self.api = api
        self.serial_factory = serial_factory
        self.finder = finder
        self.clock = clock
        self.port = None
        self.write_lock = threading.Lock()
        self.busy = threading.Lock()          # one machine action at a time
        self.camera_wanted = 0.0              # monotonic time of the last ping with cam=1
        self.last_ping = 0.0
        self.track: dict = {}
        self.trace: JobTrace | None = None
        self.trace_file = None
        self.running = True

    # ---------- sending ----------
    def send(self, msg: dict, payload: bytes = b"") -> None:
        line = (json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self.write_lock:
            self.port.write(line + payload)

    # ---------- requests from the panel ----------
    def handle_line(self, raw: bytes) -> None:
        try:
            msg = json.loads(raw.decode("utf-8"))
        except ValueError:
            return            # boot messages, M115 from a port probe, noise
        if not isinstance(msg, dict):
            return
        kind = msg.get("t")
        if kind in ("hello", "ping"):
            self.last_ping = time.monotonic()
            if msg.get("cam"):
                self.camera_wanted = self.last_ping
            elif kind == "ping":
                self.camera_wanted = 0.0
        elif kind == "jobs":
            self.send_jobs()
        elif kind == "act":
            self.start_action(msg)

    def send_jobs(self) -> None:
        status, data = self.api.json("GET", "/api/jobs")
        files = [{"name": f.get("name", ""), "kb": round((f.get("bytes") or 0) / 1024)}
                 for f in data.get("files", [])] if status == 200 else []
        self.send({"t": "jobs", "files": files[:60]})

    def start_action(self, msg: dict) -> None:
        op = msg.get("op")
        ident = msg.get("id", 0)
        if op not in ACTIONS:
            self.send({"t": "res", "id": ident, "ok": False, "msg": "Aktion am Panel nicht erlaubt: %s" % op})
            return
        if op in ("estop", "abort"):
            # never queued behind a running action
            threading.Thread(target=self.run_action, args=(msg, False), daemon=True).start()
            return
        if not self.busy.acquire(blocking=False):
            self.send({"t": "res", "id": ident, "ok": False, "msg": "Vorherige Aktion läuft noch"})
            return
        threading.Thread(target=self.run_action, args=(msg, True), daemon=True).start()

    def run_action(self, msg: dict, release: bool) -> None:
        op, ident = msg["op"], msg.get("id", 0)
        try:
            ok, text = self.action(op, {k: str(msg[k]) for k in ACTIONS[op] if k in msg})
        except Exception as exc:            # network or Pi error: report, never crash the bridge
            LOG.exception("panel action %s", op)
            ok, text = False, "Pi-Fehler: %s" % str(exc)[:120]
        finally:
            if release:
                self.busy.release()
        try:
            self.send({"t": "res", "id": ident, "op": op, "ok": ok, "msg": text})
        except Exception:
            LOG.warning("panel gone before the answer to %s", op)

    def action(self, op: str, form: dict) -> tuple[bool, str]:
        if op == "frame_job":
            return self.frame_job(form.get("name", ""))
        if op == "autorun":
            status, s = self.api.json("GET", "/api/status")
            placed = ((s.get("origin") or {}).get("placement") or {}).get("file")
            if placed and placed == form.get("name"):
                form["placement"] = "1"
        form["op"] = op
        status, data = self.api.json("POST", "/api/action", form, timeout=SLOW.get(op, 20))
        return status == 200, data.get("message") or data.get("error") or ""

    def frame_job(self, name: str) -> tuple[bool, str]:
        status, s = self.api.json("GET", "/api/status")
        placement = (s.get("origin") or {}).get("placement") or {}
        status, geo = self.api.json("GET", "/api/jobs/%s/geometry" % urllib.parse.quote(name, safe=""))
        if status != 200:
            return False, geo.get("error") or "Auftrag nicht lesbar"
        form = {"op": "frame", "mode": "box", "gcode": frame_gcode(geo["bounds"])}
        if placement.get("file") == name:
            form.update(placement="1", name=name)
        status, data = self.api.json("POST", "/api/action", form)
        return status == 200, data.get("message") or data.get("error") or ""

    # ---------- status and camera ----------
    def update_trace(self, s: dict) -> None:
        job = s.get("job") or {}
        name = job.get("file") if job.get("state") in ACTIVE else None
        if name == self.trace_file:
            return
        self.trace_file, self.trace = name, None
        if not name:
            return
        status, body, _ = self.api.call("GET", "/api/jobs/%s/content" % urllib.parse.quote(name, safe=""))
        if status == 200 and len(body) <= CONTENT_LIMIT:
            self.trace = JobTrace(body.decode("utf-8", "replace"))

    def status_loop(self) -> None:
        while self.running:
            pause = 1.0
            try:
                status, s = self.api.json("GET", "/api/status", timeout=3)
                if status == 200:
                    self.update_trace(s)
                    msg = compact(s, time.monotonic(), time.strftime("%H:%M", time.localtime(self.clock())),
                                  self.track, self.trace)
                    self.send(msg)
                    pause = 0.5 if msg["act"] != "idle" else 1.0
            except Exception as exc:          # Pi still starting, or the panel stopped reading
                LOG.debug("panel status: %s", exc)
            time.sleep(pause)

    def camera_loop(self) -> None:
        w, h = CAMERA_SIZE
        while self.running:
            if time.monotonic() - self.camera_wanted > PING_TIMEOUT_S:
                time.sleep(0.3)
                continue
            try:
                status, body, kind = self.api.call("GET", "/api/camera/snapshot?w=%d&h=%d" % (w, h), timeout=25)
                if status == 200 and kind.startswith("image/jpeg"):
                    self.send({"t": "img", "w": w, "h": h, "len": len(body)}, body)
                    continue
                try:
                    text = json.loads(body.decode("utf-8")).get("error", "")
                except ValueError:
                    text = "HTTP %d" % status
                self.send({"t": "res", "id": 0, "op": "camera", "ok": False, "msg": text or "Kein Kamerabild"})
            except Exception as exc:
                LOG.debug("panel camera: %s", exc)
            time.sleep(3.0)

    # ---------- connection ----------
    def session(self, port) -> None:
        self.port = port
        self.running = True
        threads = [threading.Thread(target=self.status_loop, daemon=True, name="panel-status"),
                   threading.Thread(target=self.camera_loop, daemon=True, name="panel-camera")]
        for t in threads:
            t.start()
        buf = b""
        try:
            while True:
                chunk = port.read(512)
                if not chunk:
                    continue
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self.handle_line(line.strip())
                if len(buf) > 8192:
                    buf = b""
        finally:
            self.running = False
            for t in threads:
                t.join(timeout=30)

    def serve_forever(self) -> None:
        import serial   # pyserial; imported here so tests need no hardware
        factory = self.serial_factory or (lambda p: serial.Serial(p, 115200, timeout=0.2, write_timeout=2,
                                                                  exclusive=True))
        while True:
            path = self.finder()
            if not path:
                time.sleep(3.0)
                continue
            try:
                port = factory(path)
            except Exception as exc:
                LOG.info("Panel an %s nicht zu öffnen: %s", path, exc)
                time.sleep(3.0)
                continue
            LOG.info("Bedienpanel verbunden: %s", path)
            try:
                self.session(port)
            except Exception as exc:
                LOG.info("Bedienpanel getrennt: %s", exc)
            finally:
                try:
                    port.close()
                except Exception:
                    pass
            time.sleep(1.0)


def start(http_port: int) -> None:
    """Run the bridge in the background of the Pi service (marlin.web)."""
    bridge = PanelBridge(Api(http_port))
    threading.Thread(target=bridge.serve_forever, daemon=True, name="panel-bridge").start()
