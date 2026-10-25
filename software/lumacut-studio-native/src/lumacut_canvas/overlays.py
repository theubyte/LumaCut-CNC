"""Hintergrund-Ebenen (Overlays) für die Arbeitsfläche.

Andere Module (z. B. Scan & Probe) können Bilder oder eigene Zeichnungen
*unter* den Objekten einblenden, ohne den Canvas-Code zu ändern::

    from lumacut_canvas.overlays import ImageOverlay, PainterOverlay

    editor.add_overlay("scan", ImageOverlay(qimage))                  # ganze Fläche
    editor.add_overlay("hoehe", ImageOverlay(heat, Rect(0, 0, 180, 170), opacity=0.6), z=10)
    editor.add_overlay("raster", PainterOverlay(lambda p, work: ...), z=20)
    editor.remove_overlay("scan")

Alle Koordinaten sind Arbeitsflächen-mm (0,0 = links oben, 360 × 340 mm).
Overlays werden nach dem Flächenhintergrund und vor dem Raster gezeichnet,
aufsteigend nach ``z``; sie sind nie anklickbar und landen nicht in Export
oder G-Code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter

from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, Rect


class CanvasOverlay(Protocol):
    """Alles mit ``visible``, ``opacity`` und ``paint(painter, work_rect)``."""

    visible: bool
    opacity: float

    def paint(self, painter: QPainter, work: QRectF) -> None: ...


def _target(rect: Rect | None) -> QRectF:
    if rect is None:
        return QRectF(0, 0, WORK_WIDTH_MM, WORK_HEIGHT_MM)
    return QRectF(rect.x, rect.y, rect.w, rect.h)


@dataclass
class ImageOverlay:
    """Bild (Kamerascan, Höhenkarte …) auf ``rect`` (mm) gespannt; ``None`` = ganze Fläche."""

    image: QImage
    rect: Rect | None = None
    opacity: float = 1.0
    visible: bool = True

    def paint(self, painter: QPainter, work: QRectF) -> None:
        if self.image is None or self.image.isNull():
            return
        painter.drawImage(_target(self.rect), self.image)


@dataclass
class PainterOverlay:
    """Eigene Zeichenfunktion ``fn(painter, work_rect)`` in mm-Koordinaten."""

    fn: Callable[[QPainter, QRectF], None]
    opacity: float = 1.0
    visible: bool = True
    meta: dict = field(default_factory=dict)

    def paint(self, painter: QPainter, work: QRectF) -> None:
        self.fn(painter, work)
