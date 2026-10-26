"""Anbindung des Scan/Probe-Workflows an echte Hardware oder die Simulation.

Qt-frei. Quellen:

* **Pi-API** (``machine.client.LumaCutClient``)
  - ``PiProbe``: ``op=probe`` mit X/Y. Der Pi fährt hin, rechnet den Tasterversatz
    selbst ein und meldet die Oberfläche (G30).
  - ``PiMachine``: XY absolut über ``op=moveto`` (ein Aufruf je Kachel, der Pi
    antwortet nach ``M400``, hebt Z höchstens auf seine Rückzugshöhe an und senkt
    nie). Z gibt es dort nicht – Z fährt weiter in Jog-Schritten (einmal je Scan,
    abwärts abgerundet, nie unter Oberfläche + 2 mm). Ältere Pis ohne ``moveto``:
    automatisch alles in Jog-Schritten 10 / 1 / 0,1 mm (langsam).
  - ``PiSnapshotCamera``: Kopfkamera am Pi über ``GET /api/camera/snapshot``.
  - ``pi_features``: erkennt anhand von ``/api/status`` → ``camera`` (kam mit
    ``moveto`` und dem Snapshot-Endpunkt), was der Pi kann.
* **Kamera lokal** ``OpenCvCamera``: USB-Index (``0``) oder Stream-URL
  (z. B. MJPEG ``http://lumacut.local:8081/stream``).
* **Simulation** ``simulated_setup()``: synthetisches Bett mit zwei Werkstücken,
  Fake-Maschine, -Kamera und -Taster – die Oberfläche ist ohne Hardware testbar.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import threading
import time
from typing import Any, Callable, Optional

import numpy as np

from .calibration import CameraCalibration
from .geometry import DEFAULT_LIMITS, MachineLimits

JOG_STEPS = (10.0, 1.0, 0.1)
_SURFACE_RE = re.compile(r"Z\s*=\s*([-+]?\d+(?:\.\d+)?)")


class HardwareNotReady(RuntimeError):
    """Maschine/Kamera nicht bereit – Text ist für die Oberfläche gedacht."""


def _check_ready(client) -> Any:
    st = client.status()
    if not st.skr_connected:
        raise HardwareNotReady("SKR-Steuerung am Pi nicht verbunden")
    if st.emergency_latched:
        raise HardwareNotReady("Notstopp aktiv – erst quittieren")
    if not st.homed:
        raise HardwareNotReady("Maschine ist nicht referenziert – zuerst „Home“ (Maschinen-Panel, "
                               "„Erweitert: Bewegung, Taster, Jog“)")
    if st.job.active:
        raise HardwareNotReady("Es läuft ein Auftrag")
    return st


class PiProbe:
    """``ProbeInterface`` über ``op=probe`` der Pi-API."""

    def __init__(self, client, api_error: type[Exception] = Exception,
                 fatal_errors: tuple[type[Exception], ...] = ()):
        self.client = client
        self.api_error = api_error
        self.fatal_errors = fatal_errors
        self._ready = False

    def probe_z(self, x, y, *, safe_z, feed, max_depth):
        if not self._ready:
            _check_ready(self.client)
            self._ready = True
        try:
            msg = self.client.probe(float(x), float(y))
        except self.fatal_errors:
            raise
        except self.api_error:
            return None  # kein Kontakt / Pi lehnt Punkt ab -> Wiederholung/Interpolation
        m = _SURFACE_RE.search(msg or "")
        if m:
            return float(m.group(1))
        z = self.client.status().workpiece_surface_z
        return None if z is None else float(z)


#: Mindestabstand des Kopfes zur gemessenen Oberfläche (wie Pi ``probe_clearance_mm``).
SURFACE_CLEARANCE_MM = 2.0
#: Fahrbereich Z laut Pi-Konfiguration (``travels.z``), falls der Pi nichts meldet.
DEFAULT_Z_TRAVEL_MM = 90.0
OLD_PI_NOTE = ("Pi-Software ohne Snapshot/moveto – Scan fährt in Jog-Schritten (langsam), "
               "Kamera nur lokal (USB/URL). Pi aktualisieren (pi400/update.sh).")


def _client_errors():
    from machine.client import ApiError, ConnectionFailed, StatusTimeout
    return ApiError, ConnectionFailed, StatusTimeout


def _unknown_op(exc) -> bool:
    return "Unbekannte Marlin-Aktion" in str(exc)


@dataclass
class PiFeatures:
    """Was der verbundene Pi kann (aus ``/api/status``)."""
    moveto: bool = False
    snapshot: bool = False          # Endpunkt vorhanden UND Kameragerät gefunden
    camera_device: str = ""
    note: str = ""

    @property
    def summary(self) -> str:
        if self.snapshot and self.moveto:
            return f"Pi: Kamera {self.camera_device} (Snapshot) und moveto verfügbar"
        return self.note


def pi_features(client, status: Any = None) -> PiFeatures:
    """Feature-Erkennung ohne Seiteneffekt: ``camera`` in ``/api/status`` gibt es
    seit dem Pi-Stand mit ``op=moveto`` und ``/api/camera/snapshot``."""
    st = status if status is not None else client.status()
    raw = getattr(st, "raw", None) or {}
    cam = raw.get("camera") if isinstance(raw, dict) else None
    if not isinstance(cam, dict):
        return PiFeatures(note=OLD_PI_NOTE)
    device = str(cam.get("device") or "/dev/video0")
    if not cam.get("available"):
        return PiFeatures(moveto=True, snapshot=False, camera_device=device,
                          note=f"Pi meldet keine Kamera an {device} (LUMACUT_CAMERA in "
                               "/etc/lumacut/lumacut.env) – Kamera lokal (USB/URL) wählen; "
                               "Fahrten über moveto")
    return PiFeatures(moveto=True, snapshot=True, camera_device=device)


def _pi_config(st) -> dict:
    raw = getattr(st, "raw", None) or {}
    cfg = raw.get("config") if isinstance(raw, dict) else None
    return cfg if isinstance(cfg, dict) else {}


class PiMachine:
    """``MachineInterface`` über die Pi-API.

    XY: ``op=moveto`` (absolut, ein Aufruf), Rückfall Jog-Schritte. Z: Jog-Schritte
    (Pi hat keine absolute Z-Fahrt), abwärts abgerundet, nie unter Oberfläche + 2 mm.
    ``use_moveto=None`` erkennt die Fähigkeit beim ersten Zug aus ``/api/status``.
    """

    def __init__(self, client, limits: MachineLimits = DEFAULT_LIMITS,
                 use_moveto: Optional[bool] = None, poll_s: float = 0.2,
                 idle_timeout_s: float = 120.0, sleep: Callable[[float], None] = time.sleep):
        self.client = client
        self.limits = limits
        self.use_moveto = use_moveto
        self.poll_s = poll_s
        self.idle_timeout_s = idle_timeout_s
        self._sleep = sleep
        self.pos: Optional[list[float]] = None  # zuletzt angefahren (nur Info)
        self.notes: list[str] = []
        #: Fahr-Aufrufe an den Pi (moveto + jog) – für Tests/Abschätzung
        self.motion_requests = 0

    def _note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    # ---- Vorabprüfung (vor dem Start, nicht mitten im Scan) --------------
    def check_scan_height(self, scan_z: float) -> list[str]:
        """Prüft vor dem Scan, ob die Scanhöhe sicher anfahrbar ist.

        Wirft ``HardwareNotReady`` mit deutschem Text; gibt Hinweise zurück
        (z. B. Rückfall auf Jog-Schritte)."""
        st = _check_ready(self.client)
        if st.position is None:
            raise HardwareNotReady("Pi meldet keine Position (M114)")
        cfg = _pi_config(st)
        travels = cfg.get("travels") if isinstance(cfg.get("travels"), dict) else {}
        z_max = _num(travels.get("z"), DEFAULT_Z_TRAVEL_MM)
        if not 0.0 <= scan_z <= z_max:
            raise HardwareNotReady(f"Scanhöhe Z{scan_z:.1f} liegt außerhalb des Fahrbereichs "
                                   f"Z0..{z_max:.0f} – Kalibrierung prüfen")
        surface = st.workpiece_surface_z
        z_now = float(st.position[2])
        if surface is None and abs(scan_z - z_now) >= 0.05:
            raise HardwareNotReady(
                "Werkstückhöhe unbekannt: Der Pi gibt Z-Fahrten erst nach einer Messung der "
                "Oberfläche frei. Vor dem Scan einmal „Fokus (G30)“ ausführen (Maschinen-Panel, "
                "„Erweitert: Bewegung, Taster, Jog“; Kopf über Werkstück oder leerem Bett) "
                f"(Kopf steht auf Z{z_now:.1f}, Scanhöhe Z{scan_z:.1f}).")
        if surface is not None and scan_z < surface + SURFACE_CLEARANCE_MM - 1e-6:
            raise HardwareNotReady(
                f"Scanhöhe Z{scan_z:.1f} liegt weniger als {SURFACE_CLEARANCE_MM:.0f} mm über der "
                f"Werkstückoberfläche Z{surface:.1f} – Werkstück zu hoch für die kalibrierte "
                "Scanhöhe (Kalibrierung bei größerer Höhe nötig)")
        if self.use_moveto is None:
            self.use_moveto = pi_features(self.client, st).moveto
        if not self.use_moveto:
            self._note(OLD_PI_NOTE)
        clearance = _num(cfg.get("z_clearance_mm"), None)
        if self.use_moveto and clearance is not None and scan_z < clearance - 0.05:
            # moveto hebt Z bei jeder Kachel auf die Rückzugshöhe – falsche Bildhöhe
            self.use_moveto = False
            self._note(f"Scanhöhe Z{scan_z:.1f} liegt unter der Rückzugshöhe Z{clearance:.1f} des Pi "
                       "– moveto würde den Kopf anheben; Scan fährt in Jog-Schritten (langsam). "
                       "Rückzugshöhe senken oder Scanhöhe ≥ Rückzugshöhe kalibrieren.")
        return list(self.notes)

    # ---- MachineInterface --------------------------------------------------
    def move_to(self, x=None, y=None, z=None, feed=None):
        # Position jedes Mal frisch lesen: der Pi bewegt den Kopf beim Proben selbst.
        st = _check_ready(self.client)
        if st.position is None:
            raise HardwareNotReady("Pi meldet keine Position (M114)")
        if self.use_moveto is None:
            self.use_moveto = pi_features(self.client, st).moveto
        pos = list(st.position)
        target = [pos[0] if x is None else float(x), pos[1] if y is None else float(y),
                  pos[2] if z is None else float(z)]
        if not self.limits.reachable(target[0], target[1]):
            raise ValueError(f"Ziel außerhalb des Fahrbereichs: X{target[0]:.1f} Y{target[1]:.1f}")
        if st.workpiece_surface_z is not None and target[2] < st.workpiece_surface_z + SURFACE_CLEARANCE_MM:
            target[2] = st.workpiece_surface_z + SURFACE_CLEARANCE_MM  # nie unter Oberfläche + 2 mm
        xy_moves = abs(target[0] - pos[0]) >= 0.05 or abs(target[1] - pos[1]) >= 0.05
        if self.use_moveto and xy_moves:
            if target[2] > pos[2]:
                self._jog_axis(2, target[2] - pos[2], pos)        # Z zuerst hoch
            if self._moveto(target[0], target[1], pos):
                if z is not None and pos[2] > target[2] + 0.05:  # nur wenn Z verlangt war
                    self._jog_axis(2, target[2] - pos[2], pos)    # abwärts, abgerundet
                self.pos = pos
                return
        # Jog-Schritte (alter Pi oder nur Z): Z zuerst, wenn es hochgeht; sonst zuletzt
        order = (2, 0, 1) if target[2] >= pos[2] else (0, 1, 2)
        for axis in order:
            self._jog_axis(axis, target[axis] - pos[axis], pos)
        self.pos = pos

    def _jog_axis(self, axis: int, delta: float, pos: list[float]) -> None:
        for step in jog_steps(delta, floor=(axis == 2 and delta < 0)):
            self.client.jog("XYZ"[axis], step)
            self.motion_requests += 1
            pos[axis] += step

    def _moveto(self, x: float, y: float, pos: list[float]) -> bool:
        """``op=moveto``; False = Pi kennt es nicht (dann Jog-Rückfall)."""
        api_error, _conn, status_timeout = _client_errors()
        self.motion_requests += 1
        try:
            reply = self.client.move_to(x, y)
        except api_error as exc:
            if _unknown_op(exc):
                self.use_moveto = False
                self._note(OLD_PI_NOTE)
                return False
            raise HardwareNotReady(f"Fahrt nach X{x:.1f} Y{y:.1f} abgelehnt: {exc}") from None
        except status_timeout:
            # Antwort zu spät: abwarten, dann die echte Position prüfen
            self.wait_idle()
            reply = {}
        new = _position_of(reply)
        if new is None:
            st = self.client.status()
            new = list(st.position) if st.position is not None else None
        if new is None or abs(new[0] - x) > 0.2 or abs(new[1] - y) > 0.2:
            got = "unbekannt" if new is None else f"X{new[0]:.2f} Y{new[1]:.2f}"
            raise HardwareNotReady(f"Pi meldet nach moveto Position {got}, Ziel X{x:.2f} Y{y:.2f}")
        pos[:] = [float(v) for v in new[:3]]
        return True

    def wait_idle(self):
        """Wartet per ``/api/status``, bis der Pi steht (moveto/Jog warten auf dem
        Pi schon mit ``M400`` – normalerweise genügt eine Abfrage)."""
        _api, conn_failed, status_timeout = _client_errors()
        deadline = time.monotonic() + self.idle_timeout_s
        last = ""
        while True:
            try:
                st = self.client.status()
            except status_timeout:
                st = None   # älterer Pi hält /api/status während der Fahrt an
            if st is not None:
                if getattr(st, "emergency_latched", False):
                    raise HardwareNotReady("Notstopp aktiv – Scan angehalten")
                state = str(getattr(st, "state", "") or "")
                if not getattr(st, "pi_busy", False) and state in ("", "Idle"):
                    return
                last = state or "beschäftigt"
            if time.monotonic() >= deadline:
                raise HardwareNotReady(f"Pi meldet nach {self.idle_timeout_s:.0f} s noch Bewegung "
                                       f"({last or 'keine Antwort'})")
            self._sleep(self.poll_s)


def _num(value: Any, default: Optional[float]) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _position_of(reply: Any) -> Optional[list[float]]:
    p = reply.get("position") if isinstance(reply, dict) else None
    if isinstance(p, (list, tuple)) and len(p) >= 3:
        try:
            vals = [float(v) for v in p[:3]]
        except (TypeError, ValueError):
            return None
        if all(math.isfinite(v) for v in vals):
            return vals
    return None


def jog_steps(delta: float, floor: bool = False) -> list[float]:
    """Zerlegt eine Strecke in erlaubte Jog-Schritte (Rest < 0,05 mm entfällt).

    ``floor``: Betrag abrunden statt runden (Z nach unten – nie zu tief).
    """
    sign = 1.0 if delta >= 0 else -1.0
    tenths = int(math.floor(abs(delta) * 10 + 1e-6)) if floor else int(round(abs(delta) * 10))          # ganzzahlig rechnen, keine Float-Reste
    out: list[float] = []
    for s, unit in ((10.0, 100), (1.0, 10), (0.1, 1)):
        n, tenths = divmod(tenths, unit)
        out += [sign * s] * n
    return out


class OpenCvCamera:
    """``CameraInterface`` über ``cv2.VideoCapture`` (USB-Index oder URL)."""

    def __init__(self, source: int | str = 0, width: Optional[int] = None,
                 height: Optional[int] = None, exposure: Optional[float] = None):
        import cv2
        if isinstance(source, str) and source.strip().isdigit():
            source = int(source)
        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            raise HardwareNotReady(f"Kamera „{source}“ lässt sich nicht öffnen")
        if width:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if exposure is not None:
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # manuell (V4L2/DirectShow)
            self.cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
        self._lock = threading.Lock()
        self.flush_frames = 2

    def capture(self) -> np.ndarray:
        with self._lock:
            for _ in range(self.flush_frames):   # gepufferte Bilder von vor der Bewegung verwerfen
                self.cap.grab()
            ok, frame = self.cap.read()
        if not ok or frame is None:
            raise HardwareNotReady("Kamera liefert kein Bild")
        return frame

    def close(self):
        self.cap.release()


class PiSnapshotCamera:
    """``CameraInterface`` über ``GET /api/camera/snapshot`` (Kopfkamera am Pi).

    Der Pi liest per ffmpeg/V4L2 einige Bilder (Belichtung) und liefert das
    letzte als JPEG – ohne Kamerapuffer, also ohne veraltete Bilder.
    Wiederholt bei 503/Netzfehler; Bildgröße muss zur Kalibrierung passen.
    """

    def __init__(self, client, width: int, height: int, retries: int = 2,
                 retry_delay_s: float = 0.5, timeout_s: Optional[float] = None,
                 sleep: Callable[[float], None] = time.sleep):
        from machine.client import SNAPSHOT_SIZE_RANGE, SNAPSHOT_TIMEOUT_S
        (wmin, wmax), (hmin, hmax) = SNAPSHOT_SIZE_RANGE
        if not (wmin <= int(width) <= wmax and hmin <= int(height) <= hmax):
            raise HardwareNotReady(f"Bildgröße {width}×{height} aus der Kalibrierung kann die "
                                   f"Pi-Kamera nicht liefern ({wmin}..{wmax} × {hmin}..{hmax})")
        self.client = client
        self.width, self.height = int(width), int(height)
        self.retries = max(0, int(retries))
        self.retry_delay_s = retry_delay_s
        self.timeout_s = SNAPSHOT_TIMEOUT_S if timeout_s is None else timeout_s
        self._sleep = sleep
        self.requests = 0

    def capture(self) -> np.ndarray:
        import cv2
        api_error, conn_failed, _st = _client_errors()
        last = ""
        for attempt in range(self.retries + 1):
            if attempt:
                self._sleep(self.retry_delay_s)
            self.requests += 1
            try:
                data = self.client.camera_snapshot(self.width, self.height, timeout=self.timeout_s)
            except api_error as exc:
                status = getattr(exc, "status", None)
                if status in (404, 405):
                    raise HardwareNotReady("Pi-Software ohne Kamera-Snapshot – Pi aktualisieren "
                                           "(pi400/update.sh) oder Kamera „Lokal (USB/URL)“ wählen") from None
                if status != 503:
                    raise HardwareNotReady(f"Pi-Kamera: {exc}") from None
                last = str(exc)          # keine Kamera / kein Bild: nochmal versuchen
                continue
            except conn_failed as exc:   # inkl. Zeitüberschreitung
                last = str(exc)
                continue
            frame = cv2.imdecode(np.frombuffer(data or b"", np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                last = "kein gültiges JPEG"
                continue
            h, w = frame.shape[:2]
            if (w, h) != (self.width, self.height):
                raise HardwareNotReady(f"Pi-Kamera liefert {w}×{h}, die Kalibrierung erwartet "
                                       f"{self.width}×{self.height} – Kalibrierung prüfen")
            return frame
        raise HardwareNotReady(f"Pi-Kamera liefert kein Bild nach {self.retries + 1} Versuchen: {last}")

    def close(self):
        pass


@dataclass
class Hardware:
    machine: Any
    camera: Any
    probe: Any
    calibration: CameraCalibration
    simulated: bool = False
    description: str = ""


def default_calibration() -> CameraCalibration:
    """Platzhalter bis zur echten Kalibrierung (siehe docs/SCAN_PROBE.md)."""
    return CameraCalibration(640, 480, px_per_mm=4.0, scan_z=40.0, offset_mm=(30.0, -20.0))


def simulated_setup(delay_s: float = 0.0, seed: int = 1) -> Hardware:
    """Synthetisches Bett: Holzplatte (geneigt) + runde Scheibe (gewölbt)."""
    from .fakes import FakeCamera, FakeMachine, SyntheticBed
    bed = SyntheticBed.with_objects(seed=seed, objects=[
        {"kind": "rect", "rect": (70, 80, 190, 170),
         "z": lambda x, y: 3.0 + 0.008 * (x - 70) + 0.004 * (y - 80)},
        {"kind": "circle", "center": (285, 255), "r": 45,
         "z": lambda x, y: 4.0 + 0.4 * math.exp(-((x - 285) ** 2 + (y - 255) ** 2) / 800)},
    ])
    cal = default_calibration()
    machine = FakeMachine(bed, position_error_mm=0.3, probe_noise_mm=0.01, seed=seed)
    camera = FakeCamera(machine, bed, cal)
    if delay_s:
        _slow(machine, "move_to", delay_s)
        _slow(machine, "probe_z", delay_s)
    return Hardware(machine, camera, machine, cal, True, "Simulation (ohne Hardware)")


def _slow(obj, name: str, delay: float) -> None:
    fn: Callable = getattr(obj, name)

    def wrapped(*a, **kw):
        time.sleep(delay)
        return fn(*a, **kw)

    setattr(obj, name, wrapped)


CAMERA_PI = "pi"
CAMERA_LOCAL = "local"


def pi_setup(client, calibration: CameraCalibration, camera_source: int | str | None,
             camera_kind: str = CAMERA_LOCAL, features: Optional[PiFeatures] = None) -> Hardware:
    """Echte Maschine über die Pi-API; Kamera optional (nur für den Scan nötig).

    ``camera_kind`` ``"pi"``: Kopfkamera über den Pi-Snapshot, ``"local"``:
    OpenCV mit ``camera_source`` (USB-Index/URL). Versatz, Drehung, Spiegelung und
    Entzerrung kommen in beiden Fällen gleich aus ``calibration`` (TileScanner/Stitch).
    """
    from machine.client import ApiError, AuthFailed, ConnectionFailed, ProtocolError
    if camera_kind == CAMERA_PI:
        if features is not None and not features.snapshot:
            raise HardwareNotReady(features.note or OLD_PI_NOTE)
        camera = PiSnapshotCamera(client, calibration.image_width, calibration.image_height)
    elif camera_source not in (None, ""):
        camera = OpenCvCamera(camera_source, calibration.image_width, calibration.image_height,
                              calibration.exposure)
    else:
        camera = None
    probe = PiProbe(client, ApiError, (ConnectionFailed, AuthFailed, ProtocolError))
    machine = PiMachine(client, use_moveto=None if features is None else features.moveto)
    desc = "Pi-API" + (" + Pi-Kamera" if camera_kind == CAMERA_PI else "")
    return Hardware(machine, camera, probe, calibration, False, desc)
