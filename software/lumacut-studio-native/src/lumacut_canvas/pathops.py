"""Boole-Operationen, Verschweißen und Versatz für Vektorobjekte (shapely).

Objekte werden über :func:`shape_paths.shape_path` (inkl. Drehung, Kurven,
Text) in Flächen umgewandelt – Teilpfade nach der Gerade-Ungerade-Regel, also
genau so, wie sie gefüllt werden. Ergebnisse sind neue ``polygon``-Objekte mit
mehreren Ringen (Außenkontur + Löcher), die Füllung, G-Code und Export ohne
Sonderfall verarbeiten. Benötigt QtGui (Text braucht eine QGuiApplication).
"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtGui import QTransform
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .model import FILLABLE_KINDS, Document, Shape
from .shape_paths import shape_path

OPS = ("union", "subtract", "intersect", "xor", "weld")
OP_LABELS = {
    "union": "Vereinigen", "subtract": "Abziehen", "intersect": "Schnittmenge",
    "xor": "Ausschluss", "weld": "Verschweißen",
}
JOIN_STYLES = {"round": 1, "miter": 2, "bevel": 3}
OFFSET_RANGE = (-50.0, 50.0)   # mm
SIMPLIFY_MM = 0.005            # winzige Zwischenpunkte entfernen (unter Laserauflösung)
MIN_AREA_MM2 = 1e-4


class PathOpError(ValueError):
    pass


# Qt flacht Kurven abhängig von der Größe in Geräteeinheiten ab; in mm wäre
# das grob (Kreis Ø 20 mm ≈ 0,2 mm Sehnenfehler). Vergrößert abflachen, dann
# zurückrechnen: Fehler ≈ 0,01 mm, gut unter der Strahlbreite.
_FLATTEN_SCALE = 20.0


def _rings(shape: Shape) -> list[list[tuple[float, float]]]:
    out = []
    k = _FLATTEN_SCALE
    for poly in shape_path(shape).toSubpathPolygons(QTransform.fromScale(k, k)):
        pts = [(p.x() / k, p.y() / k) for p in poly]
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts.pop()
        if len(pts) >= 2:
            out.append(pts)
    return out


def is_closed(shape: Shape) -> bool:
    return shape.kind in FILLABLE_KINDS


def shape_area(shape: Shape) -> BaseGeometry:
    """Fläche eines geschlossenen Objekts (Gerade-Ungerade über alle Teilpfade)."""
    if not is_closed(shape):
        raise PathOpError("Offene Linien haben keine Fläche – erst schließen oder versetzen.")
    area: BaseGeometry = Polygon()
    for ring in _rings(shape):
        if len(ring) < 3:
            continue
        p = Polygon(ring).buffer(0)
        area = area.symmetric_difference(p)
    return area


def shape_lines(shape: Shape) -> BaseGeometry:
    """Offene Objekte als Linienzug (für den Versatz)."""
    rings = _rings(shape)
    lines = [LineString(r) for r in rings if len(r) >= 2]
    return unary_union(lines)


def _polygons(g: BaseGeometry) -> list[Polygon]:
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g] if g.area > MIN_AREA_MM2 else []
    if isinstance(g, MultiPolygon):
        return [p for p in g.geoms if p.area > MIN_AREA_MM2]
    if hasattr(g, "geoms"):
        return [p for sub in g.geoms for p in _polygons(sub)]
    return []


def _ring_points(ring) -> list[tuple[float, float]]:
    pts = [(float(x), float(y)) for x, y in ring.coords]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    return pts


def area_to_shape(g: BaseGeometry, template: Shape) -> Shape | None:
    """Fläche -> ein ``polygon`` mit allen Ringen (None bei leerer Fläche)."""
    polys = _polygons(g.simplify(SIMPLIFY_MM, preserve_topology=True) if not g.is_empty else g)
    pts: list[tuple[float, float]] = []
    rings: list[int] = []
    for p in polys:
        for ring in (p.exterior, *p.interiors):
            rp = _ring_points(ring)
            if len(rp) < 3:
                continue
            if pts:
                rings.append(len(pts))
            pts.extend(rp)
    if len(pts) < 3:
        return None
    s = Shape.from_points("polygon", pts, template.layer_id, rings=rings)
    s.groups = template.groups
    return s


def boolean(shapes: list[Shape], op: str) -> list[Shape]:
    """Boole-Operation über ``shapes`` (Dokumentreihenfolge, unterstes zuerst).

    union/weld: alles vereinigen (weld: jede zusammenhängende Fläche ein Objekt),
    subtract: unterstes minus alle anderen, intersect: gemeinsame Fläche aller,
    xor: Flächen, die genau einmal (ungerade oft) überdeckt sind.
    """
    if op not in OPS:
        raise PathOpError(f"Unbekannte Operation: {op}")
    if len(shapes) < 2:
        raise PathOpError("Für Boole-Operationen mindestens zwei Objekte auswählen.")
    open_ = [s for s in shapes if not is_closed(s)]
    if open_:
        raise PathOpError("Boole-Operationen gehen nur mit geschlossenen Formen "
                          "(Rechteck, Ellipse, Polygon, Text).")
    areas = [shape_area(s) for s in shapes]
    if op in ("union", "weld"):
        result = unary_union(areas)
    elif op == "subtract":
        result = areas[0].difference(unary_union(areas[1:]))
    elif op == "intersect":
        result = areas[0]
        for a in areas[1:]:
            result = result.intersection(a)
    else:
        result = areas[0]
        for a in areas[1:]:
            result = result.symmetric_difference(a)
    base = shapes[0]
    if op == "weld":
        out = [area_to_shape(p, base) for p in _polygons(result)]
        return [s for s in out if s is not None]
    s = area_to_shape(result, base)
    return [s] if s is not None else []


def offset(shapes: Iterable[Shape], distance_mm: float, join: str = "round") -> list[Shape]:
    """Versatz: + nach außen, − nach innen. Offene Linien bekommen eine
    geschlossene Kontur im Abstand |d| (Umriss um die Linie)."""
    if not OFFSET_RANGE[0] <= distance_mm <= OFFSET_RANGE[1] or distance_mm == 0:
        raise PathOpError("Versatz muss zwischen −50 und 50 mm liegen und ≠ 0 sein.")
    js = JOIN_STYLES.get(join, 1)
    out: list[Shape] = []
    for s in shapes:
        if s.kind == "image":
            continue
        if is_closed(s):
            g = shape_area(s).buffer(distance_mm, join_style=js, mitre_limit=4.0)
        else:
            g = shape_lines(s).buffer(abs(distance_mm), join_style=js, mitre_limit=4.0)
        r = area_to_shape(g, s)
        if r is not None:
            out.append(r)
    return out


def text_to_outline(shape: Shape) -> Shape | None:
    """Text als Pfad (ein Polygon mit allen Buchstaben-Ringen); Füllung und
    G-Code bleiben identisch, der Text hängt danach nicht mehr von Schriften ab."""
    if shape.kind != "text":
        raise PathOpError("Nur Textobjekte lassen sich in Pfade umwandeln.")
    rings = _rings(shape)
    pts: list[tuple[float, float]] = []
    starts: list[int] = []
    for r in rings:
        if len(r) < 3:
            continue
        if pts:
            starts.append(len(pts))
        pts.extend(r)
    if len(pts) < 3:
        return None
    out = Shape.from_points("polygon", pts, shape.layer_id, rings=starts)
    out.groups = shape.groups
    return out


def document_order(doc: Document, ids: Iterable[str]) -> list[Shape]:
    want = set(ids)
    return [s for s in doc.shapes if s.id in want]
