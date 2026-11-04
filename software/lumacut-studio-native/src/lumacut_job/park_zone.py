"""Park corner drawn on the canvas as a no-go zone.

The Pi never lasers inside the park corner X0..cx / Y0..cy (machine mm,
``park_corner.PARK_CORNER_MM`` or ``park_corner_mm`` from ``/api/status``);
the upload preflight (:mod:`lumacut_job.park_corner`) refuses such a job.
Until now the canvas did not show that corner, so a motif placed in the top
right of the work area was only refused at send time. This module draws the
part of the corner that lies inside the visible work area as a red hatched
background overlay (under the objects, never clickable, not exported).

The zone only applies to jobs sent as *absolute* (canvas position = machine
position). With the origin "current position" or "user origin" the Pi moves
the motif, so the canvas position says nothing about the corner and the
overlay is hidden; the send-time check still covers that case.

Qt glue only uses public APIs: ``editor.add_overlay`` / ``refresh_overlays``
and the machine panel's ``status_changed`` signal, ``job_origin()`` and
``origin_combo`` (all optional).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen

from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, Rect, machine_rect_to_screen

from .park_corner import PARK_CORNER_MM, corner_from_status

#: Overlay key on the canvas and its z order (above scans / height maps).
OVERLAY_KEY = "park_corner"
OVERLAY_Z = 90.0
#: Hatch spacing in mm and colours (semi-transparent red like a keep-out zone).
HATCH_MM = 2.0
FILL = QColor(230, 60, 60, 60)
LINE = QColor(235, 80, 80, 190)


def park_zone_rect(corner: tuple[float, float] = PARK_CORNER_MM) -> Rect | None:
    """Screen-mm rectangle of the park corner inside the work area (None if outside).

    The corner is X0..cx / Y0..cy in machine mm; the work area starts at the
    30 mm safe zone, so only the part beyond it is visible (head v6: 78 × 35 mm
    → a 48 × 5 mm strip at the top right of the canvas).
    """
    cx, cy = float(corner[0]), float(corner[1])
    if not (cx > 0 and cy > 0):
        return None
    r = machine_rect_to_screen(0.0, 0.0, cx, cy)
    x0, y0 = max(r.x, 0.0), max(r.y, 0.0)
    x1, y1 = min(r.right, WORK_WIDTH_MM), min(r.bottom, WORK_HEIGHT_MM)
    if x1 - x0 <= 1e-6 or y1 - y0 <= 1e-6:
        return None
    return Rect(x0, y0, x1 - x0, y1 - y0)


def hatch_lines(r: Rect, step: float = HATCH_MM) -> list[tuple[float, float, float, float]]:
    """45° hatch lines clipped to ``r`` (x0, y0, x1, y1 in mm), ``step`` apart."""
    out = []
    if r.w <= 0 or r.h <= 0 or step <= 0:
        return out
    # lines x + y = c for c in (x + y_min .. right + bottom)
    c = r.x + r.y + step
    end = r.right + r.bottom
    while c < end - 1e-9:
        xa = max(r.x, c - r.bottom)
        xb = min(r.right, c - r.y)
        if xb - xa > 1e-9:
            out.append((xa, c - xa, xb, c - xb))
        c += step
    return out


def object_hits_zone(bounds: Rect, corner: tuple[float, float] = PARK_CORNER_MM) -> bool:
    """True if a screen-mm box overlaps the visible park zone (edges touching = no)."""
    z = park_zone_rect(corner)
    if z is None:
        return False
    return (bounds.x < z.right - 1e-6 and bounds.right > z.x + 1e-6
            and bounds.y < z.bottom - 1e-6 and bounds.bottom > z.y + 1e-6)


class ParkZoneOverlay:
    """Canvas overlay (``paint(painter, work)``) for the park corner."""

    def __init__(self, corner: tuple[float, float] = PARK_CORNER_MM):
        self.corner = (float(corner[0]), float(corner[1]))
        self.visible = True
        self.opacity = 1.0

    @property
    def rect(self) -> Rect | None:
        return park_zone_rect(self.corner)

    def paint(self, p: QPainter, work: QRectF) -> None:
        r = self.rect
        if r is None:
            return
        q = QRectF(r.x, r.y, r.w, r.h)
        p.fillRect(q, FILL)
        pen = QPen(LINE, 1.0)
        pen.setCosmetic(True)
        p.setPen(pen)
        path = QPainterPath()
        for x0, y0, x1, y1 in hatch_lines(r):
            path.moveTo(x0, y0)
            path.lineTo(x1, y1)
        p.drawPath(path)
        border = QPen(LINE, 1.5, Qt.DashLine)
        border.setCosmetic(True)
        p.setPen(border)
        p.setBrush(Qt.NoBrush)
        p.drawRect(q)
        self._label(p, q)

    @staticmethod
    def _label(p: QPainter, q: QRectF) -> None:
        dev = p.transform().mapRect(q)
        if dev.width() < 40 or dev.height() < 12:
            return
        p.save()
        p.resetTransform()
        f = QFont(p.font())
        f.setPixelSize(max(9, min(13, int(dev.height()) - 3)))
        p.setFont(f)
        p.setPen(QColor(245, 110, 110))
        p.drawText(dev, Qt.AlignCenter, "Park-Ecke")
        p.restore()


class ParkZoneSync(QObject):
    """Keeps the overlay in sync with the Pi's park corner and the job origin."""

    def __init__(self, editor: Any, machine_panel: Any = None, parent: QObject | None = None):
        super().__init__(parent)
        self.editor = editor
        self.machine = machine_panel
        self.overlay = ParkZoneOverlay()
        editor.add_overlay(OVERLAY_KEY, self.overlay, z=OVERLAY_Z)
        sig = getattr(machine_panel, "status_changed", None)
        if sig is not None:
            sig.connect(lambda _s=None: self.update())
        combo = getattr(machine_panel, "origin_combo", None)
        if combo is not None and hasattr(combo, "currentIndexChanged"):
            combo.currentIndexChanged.connect(lambda _i=0: self.update())
        self.update()

    def origin(self) -> str:
        job_origin = getattr(self.machine, "job_origin", None)
        if callable(job_origin):
            try:
                return str(job_origin()[0])
            except Exception:  # noqa: BLE001 - panel without status
                return "absolute"
        return "absolute"

    def update(self) -> bool:
        """Re-read corner and origin; redraw only on a change. Returns True if changed."""
        status = getattr(self.machine, "_status", None)
        corner = corner_from_status(status)
        visible = self.origin() == "absolute"
        if (corner, visible) == (self.overlay.corner, self.overlay.visible):
            return False
        self.overlay.corner = (float(corner[0]), float(corner[1]))
        self.overlay.visible = visible
        self.editor.refresh_overlays()
        return True


def install_park_zone(editor: Any, machine_panel: Any = None, parent: QObject | None = None) -> ParkZoneSync:
    """Draw the park corner on ``editor``'s canvas, following ``machine_panel``."""
    return ParkZoneSync(editor, machine_panel, parent)
