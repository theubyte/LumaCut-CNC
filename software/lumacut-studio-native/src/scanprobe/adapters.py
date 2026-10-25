"""Anbindung des Scan/Probe-Workflows an echte Hardware oder die Simulation.

Qt-frei. Drei Quellen:

* **Pi-API** (``machine.client.LumaCutClient``)
  - ``PiProbe``: ``op=probe`` mit X/Y. Der Pi fährt hin, rechnet den Tasterversatz
    selbst ein und meldet die Oberfläche (G30).
  - ``PiMachine``: Die Pi-API kennt noch keine Absolutfahrt (``op=move`` fehlt in
    ``pi400/marlin/web.py``). Übergangsweise wird jede Fahrt in die erlaubten
    Jog-Schritte 10 / 1 / 0,1 mm zerlegt (langsam, aber nur über die geprüfte API).
* **Kamera** ``OpenCvCamera``: USB-Index (``0``) oder Stream-URL
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
        raise HardwareNotReady("Maschine ist nicht referenziert – zuerst „Home“")
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


class PiMachine:
    """``MachineInterface`` über Pi-Jog-Schritte (Übergang bis ``op=move``)."""

    def __init__(self, client, limits: MachineLimits = DEFAULT_LIMITS):
        self.client = client
        self.limits = limits
        self.pos: Optional[list[float]] = None  # zuletzt angefahren (nur Info)

    def move_to(self, x=None, y=None, z=None, feed=None):
        # Position jedes Mal frisch lesen: der Pi bewegt den Kopf beim Proben selbst.
        st = _check_ready(self.client)
        if st.position is None:
            raise HardwareNotReady("Pi meldet keine Position (M114)")
        pos = list(st.position)
        target = [pos[0] if x is None else float(x), pos[1] if y is None else float(y),
                  pos[2] if z is None else float(z)]
        if not self.limits.reachable(target[0], target[1]):
            raise ValueError(f"Ziel außerhalb des Fahrbereichs: X{target[0]:.1f} Y{target[1]:.1f}")
        if st.workpiece_surface_z is not None and target[2] < st.workpiece_surface_z + 2.0:
            target[2] = st.workpiece_surface_z + 2.0  # nie unter Oberfläche + 2 mm
        # Z zuerst, wenn es hochgeht; sonst zuletzt
        order = (2, 0, 1) if target[2] >= pos[2] else (0, 1, 2)
        for axis in order:
            delta = target[axis] - pos[axis]
            for step in jog_steps(delta, floor=(axis == 2 and delta < 0)):
                self.client.jog("XYZ"[axis], step)
                pos[axis] += step
        self.pos = pos

    def wait_idle(self):
        pass  # jeder Jog wartet auf dem Pi mit M400


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


def pi_setup(client, calibration: CameraCalibration, camera_source: int | str | None) -> Hardware:
    """Echte Maschine über die Pi-API; Kamera optional (nur für den Scan nötig)."""
    from machine.client import ApiError, AuthFailed, ConnectionFailed, ProtocolError
    camera = OpenCvCamera(camera_source, calibration.image_width, calibration.image_height,
                          calibration.exposure) \
        if camera_source not in (None, "") else None
    probe = PiProbe(client, ApiError, (ConnectionFailed, AuthFailed, ProtocolError))
    return Hardware(PiMachine(client), camera, probe, calibration, False, "Pi-API")
