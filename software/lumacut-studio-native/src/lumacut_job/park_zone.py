"""Park corner drawn on the canvas as a no-go zone.

The Pi never lasers inside the park corner X0..cx / Y0..cy (machine mm,
``park_corner.PARK_CORNER_MM`` or ``park_corner_mm`` from ``/api/status``);
the upload preflight (:mod:`lumacut_job.park_corner`) refuses such a job.
Until now the canvas did not show that corner, so a motif placed in the top
right of the work area was only refused at send time. This module draws the
part of the corner that lies inside the visible work area as a red hatched
background overlay (under the objects, never clickable, not exported).

With the origin "absolute" (canvas position = machine position) the zone is
the fixed corner strip. With "current position" (Kopfposition) or "user
origin" (Benutzer-Ursprung) the Pi moves the motif so that its anchor lands
on the head / user origin (``park_corner.placement_offset``); the zone is then
drawn where the corner falls *relative to the design* – the machine corner
shifted back by that offset (:func:`placed_zone_rect`). The design extent is
taken from the object boxes of the visible layers (or the selection with
„Nur Auswahl“); the send-time check uses the exact powered extent of the
G-code. Without a known head position / user origin the zone is hidden.

Live warning: after every document change (drag, nudge, paste, layer
visibility …) :class:`ParkZoneSync` applies the Pi's rule to the design box
of what would be sent (:func:`design_hits_zone`: the whole placed box
reaching into the corner is refused), lists the objects whose (rotated) box
lies in the zone, draws the zone stronger and reports once whenever that
changes – so a motif dragged into the corner is flagged at once instead of
being refused at send.

Qt glue only uses public APIs: ``editor.add_overlay`` / ``refresh_overlays``
/ ``documentChanged`` / ``selectionChanged`` / ``document`` / ``selection``
and the machine panel's ``status_changed`` signal, ``job_origin()``,
``origin_combo`` and ``anchor_combo`` (all optional).
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from PySide6.QtCore import QObject, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen

from lumacut_canvas.workarea import (WORK_HEIGHT_MM, WORK_WIDTH_MM, Rect, machine_rect_to_screen,
                                     screen_to_machine)

from .park_corner import (ORIGIN_NAMES, PARK_CORNER_MM, Box, corner_from_status, origin_target,
                          in_corner, placement_offset, visible_anchor)

#: Overlay key on the canvas and its z order (above scans / height maps).
OVERLAY_KEY = "park_corner"
OVERLAY_Z = 90.0
#: Hatch spacing in mm and colours (semi-transparent red like a keep-out zone).
HATCH_MM = 2.0
FILL = QColor(230, 60, 60, 60)
LINE = QColor(235, 80, 80, 190)
#: Stronger fill while objects reach into the zone (live warning).
FILL_HIT = QColor(230, 30, 30, 120)


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


def _clip_to_work(r: Rect) -> Rect | None:
    x0, y0 = max(r.x, 0.0), max(r.y, 0.0)
    x1, y1 = min(r.right, WORK_WIDTH_MM), min(r.bottom, WORK_HEIGHT_MM)
    if x1 - x0 <= 1e-6 or y1 - y0 <= 1e-6:
        return None
    return Rect(x0, y0, x1 - x0, y1 - y0)


def design_box(shapes: Iterable[Any]) -> Box | None:
    """Machine-mm box of the shapes' (rotated) object boxes, None if empty."""
    xs: list[float] = []
    ys: list[float] = []
    for sh in shapes:
        b = sh.bounds()
        for x, y in ((b.x, b.y), (b.right, b.bottom)):
            mx, my = screen_to_machine(x, y)
            xs.append(mx)
            ys.append(my)
    if not xs:
        return None
    return Box(min(xs), min(ys), max(xs), max(ys))


def placed_zone_rect(corner: tuple[float, float], origin: str, anchor: str,
                     target: tuple[float, float] | None, box: Box | None) -> Rect | None:
    """Screen-mm rectangle on the canvas that lands in the park corner when the
    design (machine box ``box``) is placed at ``origin`` / ``anchor`` (visible
    corner name) with the origin point ``target`` (machine mm).

    "absolute" = :func:`park_zone_rect`. Otherwise the Pi shifts the motif by
    ``placement_offset``; the corner X0..cx / Y0..cy shifted back by that
    offset is the canvas area that would end up in the corner. None if the
    target or the design is unknown or the area lies outside the work area.
    """
    if origin == "absolute":
        return park_zone_rect(corner)
    cx, cy = float(corner[0]), float(corner[1])
    if not (cx > 0 and cy > 0) or target is None or box is None:
        return None
    try:
        dx, dy = placement_offset(box, origin, anchor, target)
    except ValueError:
        return None
    return _clip_to_work(machine_rect_to_screen(-dx, -dy, cx - dx, cy - dy))


def design_hits_zone(box: Box | None, corner: tuple[float, float], origin: str = "absolute",
                     anchor: str = "tr", target: tuple[float, float] | None = None) -> bool:
    """Same rule as the Pi / :func:`park_corner.check_job`: the *whole* placed
    design box (machine mm) reaching into the corner is refused – even if no
    single object lies in it (e.g. one object far left, one far up)."""
    if box is None:
        return False
    try:
        dx, dy = placement_offset(box, origin, anchor, target)
    except ValueError:
        return False
    return in_corner(box.shifted(dx, dy), (float(corner[0]), float(corner[1])))


def object_hits_zone_rect(bounds: Rect, z: Rect) -> bool:
    """True if two screen-mm boxes overlap (edges touching = no)."""
    return (bounds.x < z.right - 1e-6 and bounds.right > z.x + 1e-6
            and bounds.y < z.bottom - 1e-6 and bounds.bottom > z.y + 1e-6)


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
    return object_hits_zone_rect(bounds, z)


class ParkZoneOverlay:
    """Canvas overlay (``paint(painter, work)``) for the park corner."""

    def __init__(self, corner: tuple[float, float] = PARK_CORNER_MM):
        self.corner = (float(corner[0]), float(corner[1]))
        self.visible = True
        self.opacity = 1.0
        #: Zone for a placed job (current position / user origin); None = absolute corner.
        self.placed: Rect | None = None
        self.placed_label = ""
        #: Ids of objects reaching into the zone (live warning).
        self.hits: tuple[str, ...] = ()
        #: True when the design as a whole would be refused (Pi rule: design box).
        self.refused = False

    @property
    def rect(self) -> Rect | None:
        return self.placed if self.placed is not None else park_zone_rect(self.corner)

    def label(self) -> str:
        text = "Park-Ecke" + (f" ({self.placed_label})" if self.placed_label else "")
        n = len(self.hits)
        if n:
            text += f" – {n} Objekt{'e' if n != 1 else ''} darin!"
        elif self.refused:
            text += " – Motiv-Umriss reicht hinein!"
        return text

    def paint(self, p: QPainter, work: QRectF) -> None:
        r = self.rect
        if r is None:
            return
        q = QRectF(r.x, r.y, r.w, r.h)
        p.fillRect(q, FILL_HIT if (self.hits or self.refused) else FILL)
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
        self._label(p, q, self.label())

    @staticmethod
    def _label(p: QPainter, q: QRectF, text: str = "Park-Ecke") -> None:
        dev = p.transform().mapRect(q)
        if dev.width() < 40 or dev.height() < 12:
            return
        p.save()
        p.resetTransform()
        f = QFont(p.font())
        f.setPixelSize(max(9, min(13, int(dev.height()) - 3)))
        p.setFont(f)
        p.setPen(QColor(245, 110, 110))
        p.drawText(dev, Qt.AlignCenter | Qt.TextWordWrap, text)
        p.restore()


class ParkZoneSync(QObject):
    """Keeps the overlay in sync with the Pi's park corner, the job origin and
    the document, and warns live when objects reach into the zone.

    ``report(text)``: called once whenever the set of objects inside the zone
    changes (e.g. the status bar). ``selection_only()``: True while only the
    selection is sent („Nur Auswahl“) – then only selected objects count.
    """

    def __init__(self, editor: Any, machine_panel: Any = None, parent: QObject | None = None,
                 report: Callable[[str], None] | None = None,
                 selection_only: Callable[[], bool] | None = None):
        super().__init__(parent)
        self.editor = editor
        self.machine = machine_panel
        self.report = report
        self.selection_only = selection_only
        self.overlay = ParkZoneOverlay()
        self.last_warning = ""
        editor.add_overlay(OVERLAY_KEY, self.overlay, z=OVERLAY_Z)
        sig = getattr(machine_panel, "status_changed", None)
        if sig is not None:
            sig.connect(lambda _s=None: self.update())
        for name in ("origin_combo", "anchor_combo"):
            combo = getattr(machine_panel, name, None)
            if combo is not None and hasattr(combo, "currentIndexChanged"):
                combo.currentIndexChanged.connect(lambda _i=0: self.update())
        for name in ("documentChanged", "selectionChanged"):
            sig = getattr(editor, name, None)
            if sig is not None and hasattr(sig, "connect"):
                sig.connect(lambda *_a: self.update())
        self.update()

    def origin(self) -> str:
        return self.origin_and_anchor()[0]

    def origin_and_anchor(self) -> tuple[str, str]:
        """(origin, visible anchor) chosen in the panel; absolute without one."""
        job_origin = getattr(self.machine, "job_origin", None)
        if callable(job_origin):
            try:
                origin, wire = job_origin()
            except Exception:  # noqa: BLE001 - panel without status
                return "absolute", "tr"
            status = getattr(self.machine, "_status", None)
            return str(origin), visible_anchor(str(wire), getattr(status, "coord_convention", None))
        return "absolute", "tr"

    def job_shapes(self) -> list[tuple[Any, Any]]:
        """(shape, layer) of everything the job would laser: visible layers,
        only the selection with „Nur Auswahl“."""
        doc = getattr(self.editor, "document", None)
        if doc is None or not hasattr(doc, "layers"):
            return []
        only = None
        if self.selection_only is not None:
            try:
                if self.selection_only():
                    only = set(getattr(self.editor, "selection", ()) or ())
            except Exception:  # noqa: BLE001
                only = None
        out = []
        for layer in doc.layers:
            if not getattr(layer, "visible", True):
                continue
            for sh in doc.shapes_in_layer(layer.id):
                if only is None or sh.id in only:
                    out.append((sh, layer))
        return out

    def update(self) -> bool:
        """Re-read corner, origin and document; redraw only on a change.
        Returns True if the overlay changed."""
        status = getattr(self.machine, "_status", None)
        corner = (lambda c: (float(c[0]), float(c[1])))(corner_from_status(status))
        origin, anchor = self.origin_and_anchor()
        items = self.job_shapes()
        placed = None
        label = ""
        if origin == "absolute":
            zone = park_zone_rect(corner)
            visible = True
        else:
            target = origin_target(status, origin)
            placed = placed_zone_rect(corner, origin, anchor, target,
                                      design_box(sh for sh, _l in items))
            zone = placed
            visible = target is not None
            label = "am Ursprung „%s“" % ORIGIN_NAMES.get(origin, origin)
        hits: tuple[str, ...] = ()
        refused = False
        if visible and zone is not None:
            box = design_box(sh for sh, _l in items)
            target = None if origin == "absolute" else origin_target(status, origin)
            refused = design_hits_zone(box, corner, origin, anchor, target)
            if refused:
                hits = tuple(sh.id for sh, _l in items if object_hits_zone_rect(sh.bounds(), zone))
        ov = self.overlay
        state = (corner, visible, placed, label, hits, refused)
        if state == (ov.corner, ov.visible, ov.placed, ov.placed_label, ov.hits, ov.refused):
            return False
        old = (ov.hits, ov.refused)
        ov.corner, ov.visible, ov.placed, ov.placed_label, ov.hits, ov.refused = state
        self.editor.refresh_overlays()
        if (hits, refused) != old:
            self._warn(hits, refused, corner, origin)
        return True

    def _warn(self, hits: tuple[str, ...], refused: bool, corner: tuple[float, float],
              origin: str) -> None:
        where = "" if origin == "absolute" else \
            " am Ursprung „%s“" % ORIGIN_NAMES.get(origin, origin)
        tail = ("in der Park-Ecke X0–%g / Y0–%g mm (rot schraffiert) – dort lasert der Pi "
                "nicht, der Auftrag würde abgelehnt." % (corner[0], corner[1]))
        if hits:
            n = len(hits)
            text = ("Achtung: %d Objekt%s %s%s %s Bitte aus dem Bereich schieben."
                    % (n, "e" if n != 1 else "", "liegen" if n != 1 else "liegt", where, tail))
        elif refused:
            text = ("Achtung: der Umriss des Motivs%s (umschließendes Rechteck) liegt %s "
                    "Motiv kompakter anordnen oder verschieben." % (where, tail))
        elif self.last_warning:
            text = "Park-Ecke wieder frei."
        else:
            return
        self.last_warning = text if (hits or refused) else ""
        if self.report is not None:
            try:
                self.report(text)
            except Exception:  # noqa: BLE001 - message only
                pass


def install_park_zone(editor: Any, machine_panel: Any = None, parent: QObject | None = None,
                      report: Callable[[str], None] | None = None,
                      selection_only: Callable[[], bool] | None = None) -> ParkZoneSync:
    """Draw the park corner on ``editor``'s canvas, following ``machine_panel``
    and the document; ``report`` gets the live warnings."""
    return ParkZoneSync(editor, machine_panel, parent, report, selection_only)
