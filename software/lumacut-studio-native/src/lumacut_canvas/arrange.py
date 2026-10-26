"""Ausrichten, Verteilen und Anordnungen (Raster- und Kreis-Array), Qt-frei.

Gruppen bleiben zusammen: Eine äußerste Gruppe zählt als eine Einheit (wie
beim Gruppieren). Alle Funktionen liefern nur neue Geometrien bzw. neue
Objekte; das Anwenden (ein Undo-Schritt) macht der Editor.
"""

from __future__ import annotations

from typing import Iterable

from .model import Document, Geometry, Shape, new_id, rotate_point
from .workarea import WORK_RECT, Rect, is_inside_work_area

ALIGN_MODES = ("left", "hcenter", "right", "top", "vcenter", "bottom")
ALIGN_LABELS = {
    "left": "Links ausrichten", "hcenter": "Waagerecht mittig ausrichten",
    "right": "Rechts ausrichten", "top": "Oben ausrichten",
    "vcenter": "Senkrecht mittig ausrichten", "bottom": "Unten ausrichten",
}
MAX_ARRAY_COPIES = 500


def units_of(doc: Document, ids: Iterable[str]) -> list[list[str]]:
    """Auswahl in Einheiten (äußerste Gruppe oder Einzelobjekt), Reihenfolge stabil."""
    units: dict[str, list[str]] = {}
    for i in ids:
        if not doc.has_shape(i):
            continue
        s = doc.shape(i)
        units.setdefault(s.groups[0] if s.groups else i, []).append(i)
    return list(units.values())


def _bounds(doc: Document, ids: list[str]) -> Rect:
    r = doc.selection_bounds(ids)
    assert r is not None
    return r


def _move_unit(doc: Document, unit: list[str], dx: float, dy: float, out: dict[str, Geometry]) -> None:
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return
    for i in unit:
        out[i] = doc.shape(i).geom.translated(dx, dy)


def align(doc: Document, ids: Iterable[str], mode: str, ref: Rect | None = None) -> dict[str, Geometry]:
    """Einheiten an einer Kante/Mitte ausrichten. Bezug: die Auswahl (≥ 2
    Einheiten) bzw. die Arbeitsfläche (eine Einheit) oder ``ref``."""
    if mode not in ALIGN_MODES:
        raise ValueError(f"Unbekannte Ausrichtung: {mode}")
    units = units_of(doc, ids)
    if not units:
        return {}
    if ref is None:
        ref = WORK_RECT if len(units) == 1 else _bounds(doc, [i for u in units for i in u])
    out: dict[str, Geometry] = {}
    for u in units:
        b = _bounds(doc, u)
        dx = dy = 0.0
        if mode == "left":
            dx = ref.x - b.x
        elif mode == "right":
            dx = ref.right - b.right
        elif mode == "hcenter":
            dx = (ref.x + ref.w / 2) - (b.x + b.w / 2)
        elif mode == "top":
            dy = ref.y - b.y
        elif mode == "bottom":
            dy = ref.bottom - b.bottom
        else:
            dy = (ref.y + ref.h / 2) - (b.y + b.h / 2)
        _move_unit(doc, u, dx, dy, out)
    return out


def distribute(doc: Document, ids: Iterable[str], axis: str) -> dict[str, Geometry]:
    """Gleiche Abstände zwischen den Einheiten (``axis`` "h" oder "v"); die
    äußeren beiden bleiben stehen. Braucht ≥ 3 Einheiten."""
    if axis not in ("h", "v"):
        raise ValueError("axis muss 'h' oder 'v' sein")
    units = units_of(doc, ids)
    if len(units) < 3:
        return {}
    boxes = [(u, _bounds(doc, u)) for u in units]
    pos = (lambda r: r.x + r.w / 2) if axis == "h" else (lambda r: r.y + r.h / 2)
    size = (lambda r: r.w) if axis == "h" else (lambda r: r.h)
    start = (lambda r: r.x) if axis == "h" else (lambda r: r.y)
    boxes.sort(key=lambda ub: pos(ub[1]))
    first, last = boxes[0][1], boxes[-1][1]
    span = (start(last) + size(last)) - start(first)
    gap = (span - sum(size(b) for _, b in boxes)) / (len(boxes) - 1)
    out: dict[str, Geometry] = {}
    cursor = start(first) + size(first) + gap
    for u, b in boxes[1:-1]:
        d = cursor - start(b)
        _move_unit(doc, u, d if axis == "h" else 0.0, d if axis == "v" else 0.0, out)
        cursor += size(b) + gap
    return out


def _copy_units(doc: Document, ids: list[str], place) -> list[Shape]:
    """Je Aufruf von ``place(shape)`` eine Kopie der Auswahl mit neuen Gruppen-IDs."""
    remap: dict[str, str] = {}
    copies = []
    for i in ids:
        s = doc.shape(i)
        c = s.copy(new_identity=True)
        c.groups = tuple(remap.setdefault(g, new_id()) for g in s.groups)
        c.geom = place(s)
        copies.append(c)
    return copies


def grid_array(doc: Document, ids: Iterable[str], cols: int, rows: int,
               gap_x: float = 5.0, gap_y: float = 5.0) -> list[Shape]:
    """Raster-Array: ``cols`` × ``rows`` Exemplare der Auswahl (das Original ist
    das Feld oben links). Abstand = Auswahlbreite/-höhe + Lücke."""
    sel = [i for u in units_of(doc, ids) for i in u]
    if not sel or cols < 1 or rows < 1:
        return []
    b = _bounds(doc, sel)
    sx, sy = b.w + gap_x, b.h + gap_y
    out: list[Shape] = []
    for r in range(rows):
        for c in range(cols):
            if r == 0 and c == 0:
                continue
            out += _copy_units(doc, sel, lambda s, c=c, r=r: s.geom.translated(c * sx, r * sy))
    return out


def circular_array(doc: Document, ids: Iterable[str], count: int, cx: float, cy: float,
                   angle_deg: float = 360.0, rotate: bool = True) -> list[Shape]:
    """Kreis-Array: ``count`` Exemplare (inkl. Original) um (cx, cy) über
    ``angle_deg`` verteilt (360° = geschlossener Kreis). ``rotate``: Kopien
    drehen mit (wie Speichen), sonst bleiben sie aufrecht."""
    units = units_of(doc, ids)
    if not units or count < 2:
        return []
    closed = abs(abs(angle_deg) - 360.0) < 1e-6
    step = angle_deg / (count if closed else count - 1)
    out: list[Shape] = []
    for k in range(1, count):
        a = step * k
        for u in units:
            if rotate:
                out += _copy_units(doc, u, lambda s, a=a: s.geom.rotated(a, cx, cy))
            else:
                b = _bounds(doc, u)
                ux, uy = b.x + b.w / 2, b.y + b.h / 2
                nx, ny = rotate_point(ux, uy, cx, cy, a)
                out += _copy_units(doc, u, lambda s, dx=nx - ux, dy=ny - uy: s.geom.translated(dx, dy))
    return out


def outside_count(shapes: Iterable[Shape]) -> int:
    """Wie viele Objekte nicht vollständig in der Arbeitsfläche liegen."""
    return sum(0 if is_inside_work_area(s.bounds(), 1e-3) else 1 for s in shapes)
