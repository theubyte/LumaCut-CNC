"""Schnittstellen zur Maschine (Machine-Agent) und Kamera.

Der Scan-/Probe-Kern spricht nur diese Protokolle. Die echte Implementierung
(Pi-API ``lumacut.local``) liefert der Machine-Agent; Tests nutzen
``scanprobe.fakes``.

Koordinaten sind immer **Laserpunkt-Koordinaten** in mm. Den Tasterversatz
(X −23 / Y +15) rechnet der Pi beim G30 selbst ein (docs/MASCHINE.md).
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class MachineInterface(Protocol):
    def move_to(self, x: Optional[float], y: Optional[float], z: Optional[float] = None,
                feed: Optional[float] = None) -> None:
        """Absolute Leerfahrt (Laser aus). ``None`` = Achse bleibt stehen.

        ``feed`` in mm/min. Der Scanner fährt Z immer zuerst allein an.
        """

    def wait_idle(self) -> None:
        """Blockiert, bis alle Bewegungen beendet sind (M400)."""


@runtime_checkable
class ProbeInterface(Protocol):
    def probe_z(self, x: float, y: float, *, safe_z: float, feed: float,
                max_depth: float) -> Optional[float]:
        """Oberfläche unter dem Laserpunkt (x, y) messen.

        Erwarteter Ablauf auf dem Pi: Laser aus, auf ``safe_z``, Kopf um den
        Tasterversatz verschieben, G30 mit ``feed`` mm/min bis höchstens
        ``max_depth`` (absolutes Z), zurück auf ``safe_z``. Rückgabe: Z der
        Oberfläche in Maschinen-Z oder ``None`` (kein Kontakt / Fehler).
        """


@runtime_checkable
class CameraInterface(Protocol):
    def capture(self) -> np.ndarray:
        """Ein Bild (H×W×3 BGR uint8 oder H×W Graustufen)."""
