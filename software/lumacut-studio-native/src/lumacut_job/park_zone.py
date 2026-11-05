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

Cut options and scan offset: kerf offset (outwards), lead-ins / lead-outs
and the fill scan offset burn *outside* the object boxes, so the Pi can
refuse a job whose boxes stay clear. :func:`cut_margin_mm` bounds how far a
layer's powered path can leave its objects (2 × kerf for mitred corners,
lead length – √2 × for a quarter-circle lead –, half the scan offset of a
fill). Only when that bound changes the verdict (boxes clear, boxes +
margin in the corner) the job is planned exactly like at send
(:func:`planned_powered_box`: planner, scan offset, G-code, powered extent;
images keep their object box, cached like the fill preview) – so the live
warning now matches the send-time check, without planning on every drag.
Fill overscan runs with the laser off (``S0``) and is not part of the
powered extent – neither for the Pi nor here.

Qt glue only uses public APIs: ``editor.add_overlay`` / ``refresh_overlays``
/ ``documentChanged`` / ``selectionChanged`` / ``document`` / ``selection``
and the machine panel's ``status_changed`` signal, ``job_origin()``,
``origin_combo`` and ``anchor_combo`` (all optional).
"""

from __future__ import annotations

import math
import threading
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


def cut_margin_mm(layer: Any, table: Any = None) -> float:
    """Upper bound (mm) for how far the powered path of ``layer`` can reach
    outside the object boxes of its shapes.

    * kerf offset ``|kerf_mm|``: mitred corners (limit 2) move up to 2 × kerf;
    * lead-in / lead-out: a straight 45° lead ends ``length`` from the start
      point, a quarter circle (``lead_in_arc``, also used for the lead-out)
      up to √2 × ``length``; leads start on the offset contour, so they add;
    * fill scan offset (``table``, :mod:`.scan_offset`): every hatch line
      moves by half the offset of the layer speed.

    Fill overscan is laser-off and never counts. 0 = the object boxes are exact.
    """
    def num(name: str) -> float:
        try:
            return float(getattr(layer, name, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    margin = 2.0 * abs(num("kerf_mm"))
    factor = math.sqrt(2.0) if getattr(layer, "lead_in_arc", False) else 1.0
    margin += factor * max(num("lead_in_mm"), num("lead_out_mm"), 0.0)
    if (table is not None and getattr(table, "active", False)
            and str(getattr(layer, "fill_mode", "none")) not in ("none", "offset")):
        try:
            margin += abs(float(table.offset_for(num("speed")))) / 2.0
        except Exception:  # noqa: BLE001 - malformed table: no shift
            pass
    return margin


def margin_box(items: Iterable[tuple[Any, Any]], table: Any = None) -> Box | None:
    """:func:`design_box` with every shape's box grown by its layer's
    :func:`cut_margin_mm` – a box the powered path never leaves."""
    out: Box | None = None
    for sh, layer in items:
        b = design_box((sh,))
        if b is None:
            continue
        m = cut_margin_mm(layer, table) if layer is not None else 0.0
        b = Box(b.xmin - m, b.ymin - m, b.xmax + m, b.ymax + m)
        out = b if out is None else Box(min(out.xmin, b.xmin), min(out.ymin, b.ymin),
                                        max(out.xmax, b.xmax), max(out.ymax, b.ymax))
    return out


_PLAN_LOCK = threading.Lock()
_PLAN_CACHE: dict = {}


def planned_powered_box(doc: Any, table: Any = None) -> Box | None:
    """Exact powered extent (machine mm) of the vector part of ``doc`` as sent:
    :func:`lumacut_job.planner.optimize_layers` (kerf, leads, tabs, start
    points, same defaults as send / save), the scan offset ``table`` and
    :func:`lumacut_canvas.gcode.layers_to_gcode`, measured with
    :func:`park_corner.powered_bounds` like the Pi. Images are not planned
    (their object box counts, see :func:`design_box`). The last result is
    cached on the job layers, so status ticks and edits that leave the job
    unchanged do not plan again. None if nothing is lasered."""
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import layers_to_gcode

    from .park_corner import powered_bounds
    from .planner import optimize_layers
    from .scan_offset import apply_to_layers
    if table is not None and not getattr(table, "active", False):
        table = None
    layers = job_layers(doc)
    if not layers:
        return None
    key = (repr(layers), repr(table))
    with _PLAN_LOCK:
        if _PLAN_CACHE.get("key") == key:
            return _PLAN_CACHE["value"]
    box = powered_bounds(layers_to_gcode(apply_to_layers(optimize_layers(layers), table)))
    with _PLAN_LOCK:
        _PLAN_CACHE.clear()
        _PLAN_CACHE.update(key=key, value=box)
    return box


def union_box(a: Box | None, b: Box | None) -> Box | None:
    """Smallest box containing both (None ignored)."""
    if a is None or b is None:
        return a if b is None else b
    return Box(min(a.xmin, b.xmin), min(a.ymin, b.ymin), max(a.xmax, b.xmax),
               max(a.ymax, b.ymax))


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
        #: True when only the cut options / scan offset (lead-ins, kerf …) reach in.
        self.by_cut = False

    @property
    def rect(self) -> Rect | None:
        return self.placed if self.placed is not None else park_zone_rect(self.corner)

    def label(self) -> str:
        text = "Park-Ecke" + (f" ({self.placed_label})" if self.placed_label else "")
        n = len(self.hits)
        if self.by_cut and self.refused:
            text += " – Anfahrt / Versatz reicht hinein!"
        elif n:
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

    def job_document(self) -> Any:
        """The document the job is built from (the selection with „Nur Auswahl“)."""
        doc = getattr(self.editor, "document", None)
        only = False
        if self.selection_only is not None:
            try:
                only = bool(self.selection_only())
            except Exception:  # noqa: BLE001
                only = False
        if not only or doc is None:
            return doc
        from .selection import selection_document
        try:
            return selection_document(doc, getattr(self.editor, "selection", ()) or ())
        except ValueError:
            return None

    def job_box(self, items: list[tuple[Any, Any]], corner: tuple[float, float],
                origin: str, anchor: str,
                target: tuple[float, float] | None) -> tuple[Box | None, bool]:
        """(design box the Pi rule is applied to, True if only the cut options
        / scan offset push it into the corner).

        The object boxes are used as long as the margin of the cut options
        (:func:`margin_box`) cannot change the verdict; otherwise the job is
        planned exactly (:func:`planned_powered_box`) and its powered extent
        is added to the object boxes."""
        plain = design_box(sh for sh, _l in items)
        if plain is None:
            return None, False
        from .scan_offset import active_table
        table = active_table()
        grown = margin_box(items, table)
        if grown is None or grown == plain:
            return plain, False
        if design_hits_zone(plain, corner, origin, anchor, target):
            return plain, False
        if not design_hits_zone(grown, corner, origin, anchor, target):
            return plain, False
        doc = self.job_document()
        try:
            exact = planned_powered_box(doc, table) if doc is not None else None
        except Exception:  # noqa: BLE001 - planning failed: the send check decides
            return plain, False
        box = union_box(plain, exact)
        return box, design_hits_zone(box, corner, origin, anchor, target)

    def update(self) -> bool:
        """Re-read corner, origin and document; redraw only on a change.
        Returns True if the overlay changed."""
        status = getattr(self.machine, "_status", None)
        corner = (lambda c: (float(c[0]), float(c[1])))(corner_from_status(status))
        origin, anchor = self.origin_and_anchor()
        items = self.job_shapes()
        placed = None
        label = ""
        target = None if origin == "absolute" else origin_target(status, origin)
        visible = origin == "absolute" or target is not None
        box, by_cut = (self.job_box(items, corner, origin, anchor, target) if visible
                       else (None, False))
        if origin == "absolute":
            zone = park_zone_rect(corner)
        else:
            placed = placed_zone_rect(corner, origin, anchor, target, box)
            zone = placed
            label = "am Ursprung „%s“" % ORIGIN_NAMES.get(origin, origin)
        hits: tuple[str, ...] = ()
        refused = False
        if visible and zone is not None:
            refused = design_hits_zone(box, corner, origin, anchor, target)
            if by_cut:
                from .scan_offset import active_table
                table = active_table()
                hits = tuple(sh.id for sh, layer in items
                             if object_hits_zone_rect(_grown(sh.bounds(),
                                                             cut_margin_mm(layer, table)), zone))
            elif refused:
                hits = tuple(sh.id for sh, _l in items if object_hits_zone_rect(sh.bounds(), zone))
        by_cut = by_cut and refused
        ov = self.overlay
        state = (corner, visible, placed, label, hits, refused, by_cut)
        if state == (ov.corner, ov.visible, ov.placed, ov.placed_label, ov.hits, ov.refused,
                     ov.by_cut):
            return False
        old = (ov.hits, ov.refused, ov.by_cut)
        (ov.corner, ov.visible, ov.placed, ov.placed_label, ov.hits, ov.refused,
         ov.by_cut) = state
        self.editor.refresh_overlays()
        if (hits, refused, by_cut) != old:
            self._warn(hits, refused, corner, origin, by_cut)
        return True

    def _warn(self, hits: tuple[str, ...], refused: bool, corner: tuple[float, float],
              origin: str, by_cut: bool = False) -> None:
        where = "" if origin == "absolute" else \
            " am Ursprung „%s“" % ORIGIN_NAMES.get(origin, origin)
        tail = ("in der Park-Ecke X0–%g / Y0–%g mm (rot schraffiert) – dort lasert der Pi "
                "nicht, der Auftrag würde abgelehnt." % (corner[0], corner[1]))
        if by_cut and refused:
            text = ("Achtung: An-/Abfahrt, Kerf- oder Scan-Versatz (Schnitt-Optionen der "
                    "Ebene) des Motivs%s reicht %s Motiv etwas weiter wegschieben oder "
                    "An-/Abfahrt kürzen." % (where, tail))
        elif hits:
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


def _grown(r: Rect, m: float) -> Rect:
    return r if m <= 0 else Rect(r.x - m, r.y - m, r.w + 2 * m, r.h + 2 * m)


def install_park_zone(editor: Any, machine_panel: Any = None, parent: QObject | None = None,
                      report: Callable[[str], None] | None = None,
                      selection_only: Callable[[], bool] | None = None) -> ParkZoneSync:
    """Draw the park corner on ``editor``'s canvas, following ``machine_panel``
    and the document; ``report`` gets the live warnings."""
    return ParkZoneSync(editor, machine_panel, parent, report, selection_only)
