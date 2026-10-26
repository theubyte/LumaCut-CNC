"""HTTP client for the LumaCut Pi 400 control server (pi400/marlin/web.py).

Only the Python standard library is used, so the client works in tests
without Qt and in the PyInstaller build without extra hidden imports.

All safety rules (homing order, 30 mm safe zone, Z floor, focus, laser
interlocks, single operator) are enforced on the Pi. This client only
asks for actions and reports the Pi's German explanation back to the UI.

Endpoints (see docs/PI_BETRIEB.md, derived from pi400/marlin/web.py):
    GET  /api/status                 machine + job state
    POST /api/action  op=...         form-encoded actions (op=frame: outline)
    POST /api/upload  file=...       multipart G-code upload (preflighted)
    GET  /api/jobs                   stored jobs
    GET  /api/jobs/<name>/geometry   powered toolpath bounds
Errors come back as HTTP 4xx/5xx with {"error": "..."}.
"""
from __future__ import annotations

import json
import math
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "http://lumacut.local:8080"
AUTH_HEADER = "X-LumaCut-Key"

#: Jog distances accepted by the Pi (web.py rejects every other value).
JOG_STEPS = (0.1, 1.0, 10.0)
JOG_AXES = ("X", "Y", "Z")
JOB_SUFFIXES = (".gcode", ".gc", ".nc")
MAX_JOB_BYTES = 32 * 1024 * 1024
#: Job states reported by the Pi job worker.
JOB_ACTIVE_STATES = ("homing", "probing", "running")
#: Frame outlines accepted by the Pi op=frame (box = bounding box,
#: hull = convex hull / rubber band).
FRAME_MODES = ("box", "hull")
#: Pi limit for one frame program (web.py FRAME_MAX_BYTES).
MAX_FRAME_BYTES = 64 * 1024

# The Pi holds the HTTP request open until the SKR has finished, so motion
# requests need long timeouts (mirrors the Tauri studio bridge).
STATUS_TIMEOUT_S = 4.0
DEFAULT_TIMEOUT_S = 60.0
LONG_TIMEOUT_S = 240.0
UPLOAD_TIMEOUT_S = 120.0
#: Per attempt. The Pi answers estop without taking machine.lock, so a
#: healthy Pi replies within milliseconds even during a running move.
ESTOP_TIMEOUT_S = 3.0
#: Extra attempts after a network failure (never after a Pi answer).
ESTOP_RETRIES = 2
ESTOP_RETRY_PAUSE_S = 0.2
_LONG_OPS = ("home", "probe", "park")


class MachineError(Exception):
    """Base class for all errors raised by :class:`LumaCutClient`."""


class ConnectionFailed(MachineError):
    """The Pi could not be reached (DNS, refused, timeout, bad URL)."""


class StatusTimeout(ConnectionFailed):
    """The Pi accepted the connection but did not answer in time.

    GET /api/status takes ``machine.lock`` on the Pi, which home, park and
    probe hold for the whole move, so this is expected while such a
    command runs and does not mean the Pi is gone.
    """


class AuthFailed(MachineError):
    """The Pi rejected the X-LumaCut-Key (HTTP 401/403)."""


class ApiError(MachineError):
    """The Pi answered but refused the request (HTTP 4xx/5xx with a reason)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ProtocolError(MachineError):
    """The server answered something that is not the LumaCut Marlin API."""


def normalize_base_url(raw: str) -> str:
    """Accept ``lumacut.local``, ``192.168.2.89:8080`` or a full URL."""
    text = (raw or "").strip()
    if not text:
        return DEFAULT_BASE_URL
    if "://" not in text:
        text = "http://" + text
    parts = urllib.parse.urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Ungültige Pi-Adresse: " + raw)
    netloc = parts.netloc
    if parts.port is None and parts.scheme == "http":
        netloc += ":8080"
    path = parts.path.rstrip("/")
    return urllib.parse.urlunsplit((parts.scheme, netloc, path, "", ""))


@dataclass
class JobState:
    file: str = ""
    state: str = "idle"
    line: int = 0
    total: int = 0
    error: str = ""

    @property
    def active(self) -> bool:
        return self.state in JOB_ACTIVE_STATES

    @property
    def progress(self) -> float | None:
        """Fraction 0..1 of executed G-code lines, None if unknown."""
        if self.total <= 0:
            return None
        return max(0.0, min(1.0, self.line / self.total))

    @classmethod
    def from_json(cls, data: Any) -> "JobState":
        if not isinstance(data, dict):
            return cls()
        return cls(file=str(data.get("file") or ""),
                   state=str(data.get("state") or "idle"),
                   line=_int(data.get("line")),
                   total=_int(data.get("total")),
                   error=str(data.get("error") or ""))


@dataclass
class FrameState:
    """Laser-off outline run (Pi ``frame`` status, op=frame)."""

    state: str = "idle"              # idle/running/complete/aborted/error
    mode: str = ""
    line: int = 0
    total: int = 0
    error: str = ""

    @property
    def active(self) -> bool:
        return self.state == "running"

    @classmethod
    def from_json(cls, data: Any) -> "FrameState":
        if not isinstance(data, dict):
            return cls()
        return cls(state=str(data.get("state") or "idle"),
                   mode=str(data.get("mode") or ""),
                   line=_int(data.get("line")),
                   total=_int(data.get("total")),
                   error=str(data.get("error") or ""))


@dataclass
class MachineStatus:
    """Subset of GET /api/status the Studio displays."""

    skr_connected: bool = False      # SKR identified over USB on the Pi
    state: str = ""                  # Marlin state, e.g. "Idle" / "Busy"
    owner: str = "Frei"              # "Frei", "web", "job", "lightburn", ...
    homed: bool = False
    z_homed: bool = False
    homing_verified: bool = False    # mechanics commissioned (/api/commission)
    position: tuple[float, float, float] | None = None
    laser_armed: bool | None = False   # None = Pi did not report it
    laser_fan_on: bool = False
    emergency_latched: bool = False
    fault: str = ""
    lights: bool = False
    exhaust: bool = False
    workpiece_surface_z: float | None = None
    laser_focus_z: float | None = None
    probe_offset_set: bool = False
    job: JobState = field(default_factory=JobState)
    frame: FrameState = field(default_factory=FrameState)
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def framing(self) -> bool:
        """A laser-off frame run is in progress (owner "frame" on the Pi)."""
        return self.frame.active or self.owner == "frame"

    @property
    def busy(self) -> bool:
        return self.owner not in ("Frei", "") or self.job.active or self.frame.active

    @classmethod
    def from_json(cls, data: Any) -> "MachineStatus":
        """Parse a status answer; tolerant of missing or mistyped fields.

        Missing fields fall back to the safe display value (not homed,
        laser off, no position). A different ``firmware`` (e.g. an old GRBL
        service) or an answer without any known status field is rejected.
        """
        if not isinstance(data, dict):
            raise ProtocolError("Ungültige Pi-Antwort: kein Status-Objekt")
        firmware = data.get("firmware")
        if firmware is not None and firmware != "marlin":
            raise ProtocolError(
                "Der Server meldet nicht die erwartete LumaCut-Marlin-Firmware")
        if firmware is None and not any(k in data for k in _CORE_FIELDS):
            raise ProtocolError("Ungültige Pi-Antwort: keine Statusfelder")
        owner = data.get("owner")
        return cls(
            skr_connected=_bool(data.get("connected")),
            state=str(data.get("state") or ""),
            owner=owner if isinstance(owner, str) and owner else "Frei",
            homed=_bool(data.get("homed")),
            z_homed=_bool(data.get("z_homed")),
            homing_verified=_bool(data.get("homing_verified")),
            position=_position(data.get("position")),
            # Missing laser state stays unknown (None): never claim "off" blindly.
            laser_armed=(None if data.get("laser_armed") is None
                         else _bool(data.get("laser_armed"))),
            laser_fan_on=_bool(data.get("laser_cooling_fan_on")),
            emergency_latched=_bool(data.get("emergency_latched")),
            fault=str(data.get("fault") or ""),
            lights=_bool(data.get("lights")),
            exhaust=_bool(data.get("exhaust")),
            workpiece_surface_z=_float(data.get("workpiece_surface_z")),
            laser_focus_z=_float(data.get("laser_focus_z")),
            probe_offset_set=data.get("probe_xy_offset_mm") is not None,
            job=JobState.from_json(data.get("job")),
            frame=FrameState.from_json(data.get("frame")),
            raw=data,
        )


_CORE_FIELDS = ("connected", "homed", "position", "owner", "emergency_latched")


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "ja", "on")
    return False


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _position(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    axes = [_float(v) for v in value[:3]]
    if any(v is None for v in axes):
        return None
    return (axes[0], axes[1], axes[2])  # type: ignore[return-value]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Never follow redirects: the key header must only go to the Pi.
    def redirect_request(self, *args, **kwargs):  # noqa: D401
        return None


class LumaCutClient:
    """Thread-safe (stateless per request) client for one Pi."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, api_key: str = ""):
        self.base_url = normalize_base_url(base_url)
        self._api_key = (api_key or "").strip()
        self._opener = urllib.request.build_opener(_NoRedirect())

    def __repr__(self) -> str:  # never expose the key in logs/tracebacks
        return "LumaCutClient(%r, key=%s)" % (
            self.base_url, "set" if self._api_key else "none")

    @property
    def has_key(self) -> bool:
        return bool(self._api_key)

    # ---- transport -----------------------------------------------------
    def _request(self, method: str, path: str, *, body: bytes | None = None,
                 content_type: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT_S) -> dict:
        url = self.base_url + path
        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Accept", "application/json")
        if content_type:
            request.add_header("Content-Type", content_type)
        if self._api_key:
            request.add_header(AUTH_HEADER, self._api_key)
        try:
            with self._opener.open(request, timeout=timeout) as response:
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read() if exc.fp is not None else b""
        except (urllib.error.URLError, socket.timeout, TimeoutError,
                ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise StatusTimeout("Pi antwortet nicht innerhalb %.0f s (%s)" % (
                    timeout, self.base_url)) from None
            raise ConnectionFailed("Pi nicht erreichbar (%s): %s" % (
                self.base_url, reason)) from None
        data = _decode(raw)
        if status in (401, 403):
            raise AuthFailed("Pi lehnt den Schlüssel ab (HTTP %d): %s" % (
                status, _reason(data) or "X-LumaCut-Key prüfen"))
        if 300 <= status < 400:
            raise ProtocolError("Pi leitet um (HTTP %d) – Adresse prüfen" % status)
        if status >= 400:
            raise ApiError("Pi lehnt ab (HTTP %d): %s" % (
                status, _reason(data) or "ohne Begründung"), status)
        if not isinstance(data, dict):
            raise ProtocolError("Ungültige Pi-Antwort (HTTP %d)" % status)
        return data

    def _get(self, path: str, timeout: float = DEFAULT_TIMEOUT_S) -> dict:
        return self._request("GET", path, timeout=timeout)

    def _post_form(self, path: str, fields: dict, timeout: float) -> dict:
        body = urllib.parse.urlencode(
            {k: str(v) for k, v in fields.items() if v is not None}).encode()
        return self._request("POST", path, body=body, timeout=timeout,
                             content_type="application/x-www-form-urlencoded")

    # ---- reads ---------------------------------------------------------
    def status(self, timeout: float = STATUS_TIMEOUT_S) -> MachineStatus:
        return MachineStatus.from_json(self._get("/api/status", timeout=timeout))

    def jobs(self) -> list[dict]:
        files = self._get("/api/jobs").get("files")
        return files if isinstance(files, list) else []

    def job_geometry(self, name: str) -> dict:
        _check_job_name(name)
        return self._get("/api/jobs/%s/geometry" % urllib.parse.quote(name))

    # ---- actions -------------------------------------------------------
    def action(self, op: str, timeout: float | None = None, **fields) -> str:
        if timeout is None:
            timeout = LONG_TIMEOUT_S if op in _LONG_OPS else DEFAULT_TIMEOUT_S
        data = self._post_form("/api/action", {"op": op, **fields}, timeout)
        return str(data.get("message") or "Bestätigt")

    def connect_machine(self) -> str:
        """Ask the Pi to (re)identify the SKR over USB (M115)."""
        return self.action("connect")

    def home(self) -> str:
        return self.action("home")

    def jog(self, axis: str, distance: float) -> str:
        axis = axis.upper()
        if axis not in JOG_AXES:
            raise ValueError("Achse muss X, Y oder Z sein")
        if abs(distance) not in JOG_STEPS:
            raise ValueError("Schrittweite muss 0,1 / 1 / 10 mm sein")
        return self.action("jog", axis=axis, distance=repr(float(distance)))

    def park(self) -> str:
        """Laser off, Z retract, then XY to X0/Y0 (Pi ``park_safezone``).

        ``op=park`` needs a Pi service that exposes the park routine over
        HTTP (today it only runs after a job and for LightBurn ``M2``).
        Older Pi services answer "Unbekannte Marlin-Aktion: park".
        """
        try:
            return self.action("park")
        except ApiError as exc:
            if "Unbekannte Marlin-Aktion" in str(exc):
                raise ApiError("Pi-Dienst bietet noch kein Parken über die API "
                               "(op=park fehlt in pi400/marlin/web.py)",
                               exc.status) from None
            raise

    def frame(self, gcode: str, mode: str = "box") -> str:
        """Trace the design outline with the laser off (Pi ``op=frame``).

        The Pi checks the program (only G0/G1 X/Y with S0, no M3, no Z),
        needs a homed, idle machine, and runs it in the background without
        touching the uploaded job, so "start" can follow without a new
        upload. Progress is in ``status().frame``; ``abort_job`` stops it at
        the next corner. Older Pi services answer "Unbekannte
        Marlin-Aktion: frame".
        """
        if mode not in FRAME_MODES:
            raise ValueError("Rahmenart muss box oder hull sein")
        if not gcode or not gcode.strip():
            raise ValueError("Kein Rahmen: Design ist leer")
        if len(gcode.encode("utf-8")) > MAX_FRAME_BYTES:
            raise ValueError("Rahmenprogramm zu groß (max. 64 KB)")
        try:
            return self.action("frame", gcode=gcode, mode=mode)
        except ApiError as exc:
            if "Unbekannte Marlin-Aktion" in str(exc):
                raise ApiError("Pi-Dienst bietet noch keine Rahmenfahrt über die API "
                               "(op=frame fehlt in pi400/marlin/web.py – Pi aktualisieren)",
                               exc.status) from None
            raise

    def focus(self, x: float | None = None, y: float | None = None) -> str:
        """Measure the workpiece (G30) to establish the focus height.

        The Pi has no separate "focus" motion: after a successful probe it
        stores the surface Z and moves the head to focus height
        automatically before the first powered move of a job.
        """
        return self.probe(x, y)

    def probe(self, x: float | None = None, y: float | None = None) -> str:
        if (x is None) != (y is None):
            raise ValueError("Abtastpunkt: X und Y gemeinsam angeben")
        point = {} if x is None else {"x": "%.3f" % x, "y": "%.3f" % y}
        return self.action("probe", **point)

    def emergency_stop(self, retries: int = ESTOP_RETRIES,
                       timeout: float = ESTOP_TIMEOUT_S) -> str:
        """Software E-Stop (M112). Retries only network failures.

        Every attempt is a fresh HTTP connection with a short timeout. A Pi
        answer (also an error such as "USB getrennt") is final and never
        retried: it is the Pi's verdict. Sending M112 twice is harmless.
        """
        last: ConnectionFailed | None = None
        for attempt in range(1 + max(0, retries)):
            if attempt:
                time.sleep(ESTOP_RETRY_PAUSE_S)
            try:
                message = self.action("estop", timeout=timeout)
            except ConnectionFailed as exc:
                last = exc
                continue
            if attempt:
                message += " (Versuch %d)" % (attempt + 1)
            return message
        raise ConnectionFailed(
            "NOT-AUS nicht bestätigt nach %d Versuchen – physischen Not-Aus "
            "benutzen! (%s)" % (1 + max(0, retries), last))

    def reset_emergency(self) -> str:
        return self.action("estop_reset")

    def abort_job(self) -> str:
        return self.action("abort")

    def start_job(self, name: str) -> str:
        """Start a stored job. The Pi requires a homed machine."""
        _check_job_name(name)
        return self.action("start", name=name)

    def autorun_job(self, name: str, x: float | None = None,
                    y: float | None = None) -> str:
        """One-click: home → probe under motif centre → focus → job → park."""
        _check_job_name(name)
        if (x is None) != (y is None):
            raise ValueError("Abtastpunkt: X und Y gemeinsam angeben")
        point = {} if x is None else {"x": "%.3f" % x, "y": "%.3f" % y}
        return self.action("autorun", name=name, **point)

    def upload_job(self, name: str, content: bytes | str) -> str:
        """Upload G-code; the Pi validates every line and the safe zone."""
        _check_job_name(name)
        if isinstance(content, str):
            content = content.encode("utf-8")
        if len(content) > MAX_JOB_BYTES:
            raise ValueError("Auftrag über 32 MB")
        boundary = "----LumaCut" + uuid.uuid4().hex
        body = b"".join((
            b"--", boundary.encode(), b"\r\n",
            b'Content-Disposition: form-data; name="file"; filename="',
            name.encode("utf-8"), b'"\r\n',
            b"Content-Type: text/plain\r\n\r\n",
            content, b"\r\n--", boundary.encode(), b"--\r\n"))
        data = self._request("POST", "/api/upload", body=body,
                             content_type="multipart/form-data; boundary=" + boundary,
                             timeout=UPLOAD_TIMEOUT_S)
        return str(data.get("message") or "Hochgeladen")

    def upload_job_file(self, path: str | Path) -> tuple[str, str]:
        """Upload a local file under its basename. Returns (name, message)."""
        path = Path(path)
        return path.name, self.upload_job(path.name, path.read_bytes())


def _check_job_name(name: str) -> None:
    if (not name or name != Path(name).name or "\"" in name or
            Path(name).suffix.lower() not in JOB_SUFFIXES):
        raise ValueError("Auftragsname: nur Dateiname mit .gcode, .gc oder .nc")


def _decode(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, ValueError):
        return None


def _reason(data: Any) -> str:
    if isinstance(data, dict):
        return str(data.get("error") or data.get("message") or "")
    return ""
