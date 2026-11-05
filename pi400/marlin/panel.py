"""Bedienpanel am USB des Pi (Waveshare ESP32-S3-Touch-LCD-7, firmware/panel).

The panel is one more client like the web UI and the apps: every action it
asks for goes through the Pi's own HTTP API on 127.0.0.1, so owner, homing,
release and G-code guard stay on the Pi. The panel only shows and asks.

It is connected to the native USB-C socket of the ESP32-S3 (Espressif
USB-Serial/JTAG, vendor 303a) and talks in JSON lines:

panel -> Pi   {"t": "hello", "v": ver}  {"t": "ping", "cam": 0|1, "v": ver}
              {"t": "jobs"}  {"t": "mats"}  {"t": "events"}  {"t": "sys"}
              {"t": "act", "id": n, "op": ..., <fields>}
Pi -> panel   {"t": "st", ...}            compact status, every 0.5..1 s
              {"t": "res", "id": n, "ok": bool, "msg": str}
              {"t": "jobs", "files": [{"name", "kb"}]}
              {"t": "mats", "items": [{"name", "mm", "proc", "start"}]}
              {"t": "events", "items": [{"time", "level", "text"}]}, newest first
              {"t": "sys", ...}           network, versions, update state
              {"t": "img", "w": w, "h": h, "len": n} + n bytes JPEG

Never here, on purpose: the service menu (service_*), raw G-code and anything
else that is not in ACTIONS. tests/test_panel.py pins that list.

The panel's serial port is never the SKR: Marlin is found by its own path,
and grbl_bridge.open_controller() skips Espressif devices.

Updates: panel_fw/ next to this file holds the current panel firmware
(app image, built by firmware/panel/tools/release.sh) and arrives with every
deploy. When the panel reports an older version and the machine is idle, the
bridge lets go of the port and flashes it with esptool over the same USB
cable (USB-Serial/JTAG reset into the ROM loader). Automatic unless switched
off in the web UI; a failed version is not retried by itself.
"""
from __future__ import annotations

import bisect
import collections
import glob
import hashlib
import importlib.util
import json
import logging
import os
import re
import socket
import subprocess
import sys
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
LINE_LIMIT = 8000                  # the panel drops longer JSON lines (LINK_LINE_MAX in link.c)
NAME_LIMIT = 95                    # bytes of a job name the panel can keep and send back
SCREEN_OFF_CHOICES = (0, 2, 5, 15, 30)   # minutes, 0 = never (the panel has the same buttons)
SCREEN_OFF_DEFAULT = 15

# What the panel may ask for, and which form fields pass through.
ACTIONS = {
    "estop": (),
    "estop_reset": (),
    "abort": (),
    "home": ("clear",),
    "jog": ("axis", "distance"),
    "probe": (),
    "park": (),
    "light": ("on", "brightness"),
    "exhaust": ("on",),
    "queue_pause": (),
    "queue_run": (),
    "autorun": ("name", "clear"),
    "frame_job": ("name",),
    "material": ("name", "thickness"),   # handled here: only an entry of /api/materials, only when idle
    "screen_off": ("minutes",),          # handled here: the panel's own setting, kept on the Pi
    "panel_update": (),                  # the Pi checks that the machine is idle
}
FIRMWARE_DIR = Path(__file__).resolve().parent / "panel_fw"
FLASH_TIMEOUT_S = 240
# The service sees no home directory (ProtectHome): esptool lives in the data folder,
# pip3 install --target /var/lib/lumacut/pylib esptool. Only the esptool process gets it.
PYLIB = Path(os.environ.get("LUMACUT_DATA", "/var/lib/lumacut")) / "pylib"
PREFS_FILE = Path(os.environ.get("LUMACUT_DATA", "/var/lib/lumacut")) / "panel.json"
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


def version_key(text: str) -> tuple:
    """"1.10" > "1.9"; anything unreadable sorts first."""
    try:
        return tuple(int(part) for part in str(text).split("."))
    except ValueError:
        return ()


def bundled_firmware(folder: Path = FIRMWARE_DIR) -> dict | None:
    """panel_fw/manifest.json: {"version", "file", "address", "sha256"}; None without one."""
    try:
        meta = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        image = folder / meta["file"]
        return {"version": str(meta["version"]), "path": image, "address": meta.get("address", "0x10000"),
                "sha256": meta["sha256"], "bytes": image.stat().st_size}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def flash_command(port: str, firmware: dict) -> list[str]:
    # default_reset on the USB-Serial/JTAG port puts the ESP32-S3 into its ROM loader
    return [sys.executable, "-m", "esptool", "--chip", "esp32s3", "--port", port,
            "--before", "default_reset", "--after", "hard_reset",
            "write_flash", firmware["address"], str(firmware["path"])]


def esptool_installed() -> bool:
    return (PYLIB / "esptool").is_dir() or importlib.util.find_spec("esptool") is not None


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


class EventLog:
    """What happened lately, for the panel's event list: taken from the status changes.

    Lives on the Pi, so it survives a restart of the panel. The Pi has no event
    API; this only remembers what /api/status showed.
    """

    def __init__(self, size: int = 30):
        self.items: collections.deque = collections.deque(maxlen=size)
        self.seq = 0                  # number of the newest event
        self.problem = 0              # number of the newest warning or error
        self.last: dict | None = None

    def add(self, level: str, text: str, clock: str) -> None:
        self.seq += 1
        if level in ("warn", "err"):
            self.problem = self.seq
        self.items.appendleft({"time": clock, "level": level, "text": text[:140]})

    def observe(self, s: dict, clock: str) -> None:
        job = s.get("job") or {}
        now = {
            "conn": bool(s.get("connected")),
            "latched": bool(s.get("emergency_latched")),
            "fault": s.get("fault") or "",
            "state": job.get("state") or "idle",
            "file": job.get("file") or "",
            "error": job.get("error") or "",
            "frame": (s.get("frame") or {}).get("state") or "idle",
            "frame_error": (s.get("frame") or {}).get("error") or "",
            "queue": (s.get("queue") or {}).get("state") or "idle",
            "lost": (s.get("reference") or {}).get("lost") or "",
            "stray": bool(s.get("laser_armed")) and (s.get("activity") or "idle") == "idle",
        }
        old, self.last = self.last, now
        if old is None:               # first look after a start: only what still needs attention
            if now["latched"]:
                self.add("err", "Notstopp aktiv: %s" % (now["fault"] or "quittieren"), clock)
            if now["stray"]:
                self.add("err", "Laser scharf ohne Auftrag", clock)
            return
        if old["conn"] != now["conn"]:
            self.add("info" if now["conn"] else "err",
                     "Steuerung verbunden" if now["conn"] else "Steuerung getrennt (USB prüfen)", clock)
        if now["latched"] and not old["latched"]:
            self.add("err", "Notstopp aktiv: %s" % (now["fault"] or "quittieren"), clock)
        elif old["latched"] and not now["latched"]:
            self.add("ok", "Notstopp quittiert", clock)
        elif now["fault"] and now["fault"] != old["fault"]:
            self.add("warn", now["fault"], clock)
        if now["stray"] and not old["stray"]:
            self.add("err", "Laser scharf ohne Auftrag", clock)
        if now["lost"] and now["lost"] != old["lost"]:
            self.add("warn", "Referenz verloren: %s" % now["lost"], clock)
        if now["state"] != old["state"]:
            name = now["file"] or "Auftrag"
            if now["state"] in ACTIVE and old["state"] not in ACTIVE:
                self.add("info", "Gestartet: %s" % name, clock)
            elif now["state"] == "complete":
                self.add("ok", "Fertig: %s" % name, clock)
            elif now["state"] == "aborted":
                self.add("warn", "Abgebrochen: %s" % name, clock)
            elif now["state"] == "error":
                self.add("err", "%s: %s" % (name, now["error"] or "Fehler"), clock)
        if now["frame"] == "error" and old["frame"] != "error":
            self.add("err", "Rahmenfahrt: %s" % (now["frame_error"] or "Fehler"), clock)
        if now["queue"] == "stopped" and old["queue"] != "stopped":
            self.add("warn", "Warteschlange angehalten", clock)


def fit_line(key: str, items: list, base: dict) -> dict:
    """base + items, as many as fit into one line the panel accepts."""
    msg = dict(base)
    for count in range(len(items), -1, -1):
        msg[key] = items[:count]
        if len(json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= LINE_LIMIT:
            break
    return msg


def material_choices(materials: list) -> list[dict]:
    """One line per material and thickness (that is what the Pi keeps as the chosen material)."""
    found: dict = {}
    for m in materials:
        try:
            name, mm = m["name"], round(float(m["thickness_mm"]), 3)
        except (KeyError, TypeError, ValueError):
            continue
        entry = found.setdefault((name, mm), {"name": name, "mm": mm, "proc": [], "start": True})
        if m.get("process") and m["process"] not in entry["proc"]:
            entry["proc"].append(m["process"])
        entry["start"] = entry["start"] and bool(m.get("builtin"))   # only starting values, not measured
    return [{**e, "proc": ", ".join(e["proc"])} for _, e in sorted(found.items())][:40]


def load_prefs(path: Path | None) -> dict:
    prefs = {"screen_off": SCREEN_OFF_DEFAULT}
    if path is not None:
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get("screen_off")
            if value in SCREEN_OFF_CHOICES:
                prefs["screen_off"] = value
        except (OSError, ValueError, AttributeError):
            pass
    return prefs


def save_prefs(path: Path | None, prefs: dict) -> None:
    if path is None:
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(prefs), encoding="utf-8")
    os.replace(tmp, path)


def local_address() -> str:
    """The address others reach this Pi at; the socket sends nothing."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            return probe.getsockname()[0]
    except OSError:
        return ""


def wifi_name(run=subprocess.run) -> str:
    try:
        done = run(["iwgetid", "-r"], capture_output=True, text=True, timeout=2)
        return done.stdout.strip() if done.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def wifi_signal(path: Path = Path("/proc/net/wireless")) -> int | None:
    """Link quality in percent (the driver counts to 70), None without WLAN."""
    try:
        for line in path.read_text().splitlines():
            if ":" in line:
                return min(100, round(float(line.split(":", 1)[1].split()[1].rstrip(".")) * 100 / 70))
    except (OSError, ValueError, IndexError):
        pass
    return None


def software_version(run=subprocess.run) -> str:
    """Commit and date of the Pi's checkout: the API has no version field."""
    try:
        done = run(["git", "-C", str(Path(__file__).resolve().parents[2]), "log", "-1", "--format=%h %cs"],
                   capture_output=True, text=True, timeout=3)
        return done.stdout.strip() if done.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


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
    queue = s.get("queue") or {}
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
        "bright": s.get("light_brightness"),
        "dim": s.get("light_dimmable"),
        "fpow": config.get("frame_power_pct") or 0,
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
        "queue": queue.get("state") or "idle",
        "qn": sum(1 for item in queue.get("items") or [] if item.get("state") == "queued"),
        "frame": (s.get("frame") or {}).get("state") or "idle",
        "elapsed": elapsed,
        "remain": remain,
        "power": None if power is None else round(power / 2.55),
        "feed": None if feed is None else round(feed),
    }


class Api:
    """The Pi's own HTTP API on 127.0.0.1."""

    def __init__(self, port: int):
        self.port = port
        self.base = "http://127.0.0.1:%d" % port

    def call(self, method: str, path: str, form: dict | None = None, timeout: float = 15):
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as err:
            return err.code, err.read(), err.headers.get("Content-Type", "")

    @staticmethod
    def _decode(status: int, body: bytes):
        try:
            return status, json.loads(body.decode("utf-8"))
        except ValueError:
            return status, {"error": "Pi antwortet mit HTTP %d" % status}

    def json(self, method: str, path: str, form: dict | None = None, timeout: float = 15):
        status, body, _ = self.call(method, path, form, timeout)
        return self._decode(status, body)

    def send_json(self, method: str, path: str, body: dict, timeout: float = 15):
        """For the API parts that take a JSON body (/api/workspace)."""
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode("utf-8"), method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return self._decode(resp.status, resp.read())
        except urllib.error.HTTPError as err:
            return self._decode(err.code, err.read())


class PanelBridge:
    def __init__(self, api, serial_factory=None, finder=find_panel, clock=time.time,
                 firmware=bundled_firmware, auto=lambda: True, flasher=None, has_esptool=esptool_installed,
                 prefs_path: Path | None = None):
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
        # firmware update
        self.path = None                      # device path of the open panel
        self.version = None                   # reported by hello/ping
        self.firmware = firmware              # () -> bundled_firmware()
        self.auto = auto                      # () -> automatic updates on?
        self.flasher = flasher                # (command) -> (ok, text)
        self.has_esptool = has_esptool
        self.hold = False                     # port left to esptool
        self.port_free = threading.Event()    # serve_forever holds no port
        self.update = {"state": "idle", "message": "", "target": None}
        self.connected_at = 0.0
        self.failed = None                    # version that failed: no automatic retry
        # shown on the panel
        self.events = EventLog()
        self.prefs_path = prefs_path
        self.prefs = load_prefs(prefs_path)
        self.workspace_revision = None        # the material is read again when this changes
        self.material = None
        self.pi_version = None                # a deploy restarts the service: read once

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
            if msg.get("v"):
                self.version = str(msg["v"])
            if msg.get("cam"):
                self.camera_wanted = self.last_ping
            elif kind == "ping":
                self.camera_wanted = 0.0
        elif kind in self.QUERIES:
            # in the background: a slow answer must never hold up a STOPP on the same line
            threading.Thread(target=self.answer_query, args=(kind,), daemon=True).start()
        elif kind == "act":
            self.start_action(msg)

    QUERIES = {"jobs": "send_jobs", "mats": "send_materials", "events": "send_events", "sys": "send_system"}

    def answer_query(self, kind: str) -> None:
        try:
            getattr(self, self.QUERIES[kind])()
        except Exception as exc:              # Pi still starting, or the panel is gone
            LOG.debug("panel query %s: %s", kind, exc)

    def send_jobs(self) -> None:
        status, data = self.api.json("GET", "/api/jobs")
        # a longer name would arrive cut off at the panel and not name the file any more
        files = [{"name": f.get("name", ""), "kb": round((f.get("bytes") or 0) / 1024)}
                 for f in data.get("files", [])
                 if len(f.get("name", "").encode("utf-8")) <= NAME_LIMIT] if status == 200 else []
        self.send(fit_line("files", files[:60], {"t": "jobs"}))

    def send_materials(self) -> None:
        status, data = self.api.json("GET", "/api/materials")
        items = material_choices(data.get("materials", [])) if status == 200 else []
        self.send(fit_line("items", items, {"t": "mats"}))

    def send_events(self) -> None:
        self.send(fit_line("items", list(self.events.items), {"t": "events"}))

    def send_system(self) -> None:
        status, s = self.api.json("GET", "/api/status", timeout=5)
        s = s if status == 200 else {}
        address = local_address()
        info = self.info()
        firmware = s.get("firmware_release") or {}
        if self.pi_version is None:
            self.pi_version = software_version()
        self.send({"t": "sys", "ip": address, "host": socket.gethostname(),
                   "http": "http://%s:%s" % (address, getattr(self.api, "port", 8080)) if address else "",
                   "wifi": wifi_name(), "signal": wifi_signal(), "pi": self.pi_version,
                   "panel_new": info["available"] if info["update_available"] else "",
                   "panel_state": info["state"], "panel_msg": info["message"], "auto": info["auto"],
                   "skr": firmware.get("running_build") or "", "skr_conn": bool(s.get("connected")),
                   "skr_new": (firmware.get("release_build") or "") if firmware.get("update_available") else "",
                   "serial_err": s.get("serial_errors") or 0})

    def start_action(self, msg: dict) -> None:
        op = msg.get("op")
        ident = msg.get("id", 0)
        if op not in ACTIONS:
            self.send({"t": "res", "id": ident, "op": op, "ok": False, "msg": "Aktion am Panel nicht erlaubt: %s" % op})
            return
        if op in ("estop", "abort"):
            # never queued behind a running action
            threading.Thread(target=self.run_action, args=(msg, False), daemon=True).start()
            return
        if not self.busy.acquire(blocking=False):
            self.send({"t": "res", "id": ident, "op": op, "ok": False, "msg": "Vorherige Aktion läuft noch"})
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
        if not ok:
            self.events.add("warn", text or "Aktion abgelehnt: %s" % op,
                            time.strftime("%H:%M", time.localtime(self.clock())))
        try:
            self.send({"t": "res", "id": ident, "op": op, "ok": ok, "msg": text})
        except Exception:
            LOG.warning("panel gone before the answer to %s", op)

    def action(self, op: str, form: dict) -> tuple[bool, str]:
        if op == "frame_job":
            return self.frame_job(form.get("name", ""))
        if op == "material":
            return self.choose_material(form.get("name", ""), form.get("thickness", ""))
        if op == "screen_off":
            return self.set_screen_off(form.get("minutes", ""))
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

    def choose_material(self, name: str, thickness: str) -> tuple[bool, str]:
        """The material of all devices, like the web UI; its thickness sets the travel height."""
        status, s = self.api.json("GET", "/api/status", timeout=5)
        reason = self.update_blocked(s) if status == 200 else "Pi-Status nicht lesbar"
        if reason:
            return False, "%s: Material jetzt nicht änderbar" % reason
        try:
            mm = round(float(thickness), 3)
        except ValueError:
            return False, "Materialstärke unlesbar"
        status, data = self.api.json("GET", "/api/materials")
        if status != 200 or not any(e["name"] == name and e["mm"] == mm
                                    for e in material_choices(data.get("materials", []))):
            return False, "Material steht nicht in der Liste"
        status, state = self.api.json("GET", "/api/workspace")
        if status != 200:
            return False, state.get("error") or "Arbeitsstand nicht lesbar"
        status, answer = self.api.send_json("PUT", "/api/workspace", {
            "material": {"name": name, "thickness_mm": mm},
            "base_revision": state.get("revision"), "updated_by": "panel"})
        self.workspace_revision = None
        if status == 409:
            return False, "Ein anderes Gerät hat das Material gerade geändert – bitte nochmal wählen"
        if status != 200:
            return False, answer.get("error") or "Material nicht gespeichert"
        return True, "Material: %s %g mm – gilt auf allen Geräten" % (name, mm)

    def set_screen_off(self, minutes: str) -> tuple[bool, str]:
        try:
            value = int(minutes)
        except ValueError:
            value = -1
        if value not in SCREEN_OFF_CHOICES:
            return False, "Zeit für den Bildschirm nicht erlaubt"
        self.prefs["screen_off"] = value
        try:
            save_prefs(self.prefs_path, self.prefs)
        except OSError as exc:
            LOG.warning("panel prefs: %s", exc)
            return False, "Nicht gespeichert: gilt nur bis zum nächsten Neustart des Pi"
        return True, "Bildschirm bleibt an" if value == 0 else "Bildschirm aus nach %d min" % value

    def panel_fields(self, s: dict) -> dict:
        """What compact() cannot take from /api/status alone."""
        revision = (s.get("sync") or {}).get("workspace")
        if revision is None or revision != self.workspace_revision:
            try:
                status, state = self.api.json("GET", "/api/workspace", timeout=3)
                if status == 200:
                    self.material = state.get("material")
                    self.workspace_revision = revision
            except Exception as exc:          # the status must reach the panel anyway
                LOG.debug("panel workspace: %s", exc)
        material = self.material or {}
        return {"mat": material.get("name") or "", "mat_mm": material.get("thickness_mm"),
                "ev": self.events.seq, "evp": self.events.problem, "soff": self.prefs["screen_off"]}

    # ---------- firmware update ----------
    def info(self) -> dict:
        """For /api/status: what runs on the panel, what the Pi has, update state."""
        fw = self.firmware()
        connected = self.port is not None and self.running and time.monotonic() - self.last_ping < PING_TIMEOUT_S
        return {"connected": connected, "port": self.path, "version": self.version,
                "available": fw["version"] if fw else None, "update_available": self.outdated(fw),
                "auto": bool(self.auto()), "esptool": self.has_esptool(), **self.update}

    def outdated(self, fw: dict | None) -> bool:
        # 1.0 sent its version only in hello: unknown after a bridge restart counts as old
        return bool(fw) and self.path is not None and version_key(self.version or "0") < version_key(fw["version"])

    def update_blocked(self, s: dict) -> str:
        """Why the panel must not go dark now ("" = it may)."""
        job = s.get("job") or {}
        if (s.get("activity") or "idle") != "idle" or job.get("state") in ACTIVE:
            return "Maschine beschäftigt"
        if (s.get("queue") or {}).get("state") == "running":
            return "Warteschlange läuft"
        if s.get("laser_armed"):
            return "Laser freigegeben"
        return ""

    def request_update(self, manual: bool = False) -> tuple[bool, str]:
        fw = self.firmware()
        if self.update["state"] == "flashing":
            return False, "Panel-Update läuft schon"
        if not fw:
            return False, "Keine Panel-Firmware auf dem Pi"
        if self.path is None:
            return False, "Kein Bedienpanel angeschlossen"
        if not self.has_esptool():
            return False, "esptool fehlt auf dem Pi (pip3 install --target %s esptool)" % PYLIB
        if not manual and (not self.outdated(fw) or self.failed == fw["version"]):
            return False, "Panel ist aktuell"
        status, s = self.api.json("GET", "/api/status", timeout=5)
        reason = self.update_blocked(s) if status == 200 else "Pi-Status nicht lesbar"
        if reason:
            return False, reason + " – Panel-Update später"
        self.update = {"state": "flashing", "message": "Panel wird auf %s aktualisiert" % fw["version"],
                       "target": fw["version"]}
        threading.Thread(target=self.flash, args=(fw,), daemon=True, name="panel-update").start()
        return True, self.update["message"]

    def flash(self, fw: dict) -> None:
        path = self.path
        try:
            digest = hashlib.sha256(fw["path"].read_bytes()).hexdigest()
            if digest != fw["sha256"]:
                raise RuntimeError("Prüfsumme der Panel-Firmware falsch")
            try:
                self.send({"t": "res", "id": 0, "op": "update", "ok": True,
                           "msg": "Update auf %s – Bildschirm ist kurz aus" % fw["version"]})
            except Exception:
                pass
            self.hold = True
            self.port_free.clear()
            port = self.port
            if port is not None:
                port.close()                  # ends session(); serve_forever then waits
            if not self.port_free.wait(40):
                raise RuntimeError("Panel-Verbindung ließ sich nicht freigeben")
            ok, text = self.flasher(flash_command(path, fw))
            if not ok:
                raise RuntimeError(text)
            self.version = None               # the new firmware tells its own
            self.update = {"state": "done", "message": "Panel auf %s aktualisiert" % fw["version"],
                           "target": fw["version"]}
            LOG.info("Bedienpanel auf %s aktualisiert", fw["version"])
        except Exception as exc:
            LOG.warning("Panel-Update fehlgeschlagen: %s", exc)
            self.failed = fw["version"]
            self.update = {"state": "error", "message": "Panel-Update fehlgeschlagen: %s" % str(exc)[:200],
                           "target": fw["version"]}
        finally:
            self.hold = False

    def auto_update(self, s: dict) -> None:
        fw = self.firmware()
        if (self.auto() and self.version_known() and self.outdated(fw) and self.failed != fw["version"]
                and self.update["state"] != "flashing" and not self.update_blocked(s)):
            ok, text = self.request_update()
            LOG.info("automatisches Panel-Update: %s", text)

    def version_known(self) -> bool:
        # give a fresh panel a few pings to report its version first
        return self.version is not None or time.monotonic() - self.connected_at > 10

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
                    clock = time.strftime("%H:%M", time.localtime(self.clock()))
                    self.events.observe(s, clock)
                    msg = compact(s, time.monotonic(), clock, self.track, self.trace)
                    msg.update(self.panel_fields(s))
                    self.send(msg)
                    pause = 0.5 if msg["act"] != "idle" else 1.0
                    self.auto_update(s)
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
        self.connected_at = time.monotonic()
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
                if t is not threading.current_thread():
                    t.join(timeout=30)
            self.port = None

    def serve_forever(self) -> None:
        import serial   # pyserial; imported here so tests need no hardware
        factory = self.serial_factory or (lambda p: serial.Serial(p, 115200, timeout=0.2, write_timeout=2,
                                                                  exclusive=True))
        while True:
            if self.hold:                     # esptool has the port
                self.port_free.set()
                time.sleep(0.5)
                continue
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
            self.path = path
            self.version = None
            try:
                self.session(port)
            except Exception as exc:
                LOG.info("Bedienpanel getrennt: %s", exc)
            finally:
                try:
                    port.close()
                except Exception:
                    pass
            if not self.hold:
                self.path = None
            time.sleep(1.0)


def run_esptool(command: list[str]) -> tuple[bool, str]:
    try:
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(PYLIB), os.environ.get("PYTHONPATH")])))
        done = subprocess.run(command, capture_output=True, text=True, timeout=FLASH_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired:
        return False, "esptool hängt (Zeitüberschreitung)"
    out = (done.stdout + done.stderr).strip().splitlines()
    LOG.info("esptool: %s", " | ".join(out[-6:]))
    return done.returncode == 0, (out[-1] if out else "esptool Fehler %d" % done.returncode)


BRIDGE: PanelBridge | None = None


def start(http_port: int, auto=lambda: True) -> PanelBridge:
    """Run the bridge in the background of the Pi service (marlin.web)."""
    global BRIDGE
    BRIDGE = PanelBridge(Api(http_port), auto=auto, flasher=run_esptool, prefs_path=PREFS_FILE)
    threading.Thread(target=BRIDGE.serve_forever, daemon=True, name="panel-bridge").start()
    return BRIDGE
