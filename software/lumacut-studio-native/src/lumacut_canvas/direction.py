"""Laufrichtung umkehren je Objekt (LightBurn *Edit › Reverse Shape Direction*).

``Shape.reverse`` kehrt die Laufrichtung aller Konturen eines Objekts um – die
Bahn, die der Laser beim Schneiden fährt. Die Geometrie bleibt unverändert
(Rechteck, Ellipse und Text haben keine Punktfolge, die man umdrehen könnte);
erst der Export (:func:`lumacut_canvas.export.job_layers`) dreht die Polylinien:

* geschlossene Konturen laufen in der Gegenrichtung und beginnen am selben
  Punkt – ein manueller Startpunkt (:mod:`startpoint`) bleibt also, wo er ist,
  nur der Pfeil zeigt in die andere Richtung (LightBurn: Umschalt-Klick im
  Werkzeug *Set Start Point*). Der Planer dreht geschlossene Konturen ohnehin
  nie um, er wählt höchstens einen anderen Startpunkt;
* offene Pfade und Linien beginnen am anderen Ende. Der Planer
  (:mod:`lumacut_job.planner`) behält ihre Richtung dann bei – auch mit
  „Beste Richtung wählen“ (die Umkehr ist eine ausdrückliche Wahl, wie ein
  gesetzter Startpunkt); ohne Umkehr wählt er wie bisher das nähere Ende.

Ohne Umkehr ändert sich nichts – Projekte und G-Code bleiben byte-gleich.
Hier nur die Rechnung; die Bedienung (Pfad › „Richtung umkehren“, Umschalt-Tippen
im Werkzeug „Startpunkt“, Pfeile auf der Arbeitsfläche) liegt in
:mod:`startpoint_ui`.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Iterable

from .model import REVERSE_KINDS, Shape

Point = tuple[float, float]


def can_reverse(shape: Shape | None) -> bool:
    """Lässt sich die Laufrichtung dieses Objekts umkehren (alle Vektorobjekte)?"""
    return shape is not None and shape.kind in REVERSE_KINDS


def reverse_polyline(poly: list[Point]) -> list[Point]:
    """Polylinie umdrehen: offen = vom anderen Ende, geschlossen (Anfang = Ende) =
    gleicher Startpunkt, Gegenrichtung."""
    return list(reversed(poly))


def with_reverse(shape: Shape, on: bool) -> Shape:
    """Kopie mit dieser Laufrichtung (``on`` = umgekehrt)."""
    return replace(shape, geom=shape.geom.copy(), reverse=bool(on) and can_reverse(shape))


def toggled(shape: Shape) -> Shape:
    """Kopie mit umgekehrter Laufrichtung (zweimal = wie gezeichnet)."""
    return with_reverse(shape, not shape.reverse)


def contours(shape: Shape) -> list[list[Point]]:
    """Konturen des Objekts in Arbeitsflächen-mm in Schnittrichtung (mit Umkehr),
    geschlossene beginnen an einem gesetzten Startpunkt – wie der Export sie sendet."""
    if not can_reverse(shape):
        return []
    if shape.kind == "line":
        from .shape_paths import shape_path
        path = shape_path(shape)
        a, b = path.elementAt(0), path.elementAt(1)
        polys = [[(a.x, a.y), (b.x, b.y)]]
    else:
        from .shape_paths import shape_polygons
        polys = [list(p) for p in shape_polygons(shape)]
        start = shape.start_point() if shape.start else None
        if start is not None:
            from .startpoint import START_SNAP_MM, apply_start_points
            polys, _placed, _dropped = apply_start_points(polys, [start], START_SNAP_MM)
    if shape.reverse:
        polys = [reverse_polyline(p) for p in polys]
    return polys


def first_direction(poly: list[Point]) -> Point | None:
    """Einheitsvektor vom ersten Punkt zum nächsten verschiedenen Punkt."""
    if not poly:
        return None
    nxt = next((q for q in poly[1:] if math.dist(q, poly[0]) > 1e-9), None)
    if nxt is None:
        return None
    ll = math.dist(poly[0], nxt)
    return ((nxt[0] - poly[0][0]) / ll, (nxt[1] - poly[0][1]) / ll)


def direction_marker(shape: Shape) -> tuple[Point, Point] | None:
    """``(Punkt, Richtung)`` für den Pfeil eines umgekehrten Objekts ohne Startpunkt:
    Anfang der ersten Kontur (offen: das neue Anfangsende) in Arbeitsflächen-mm."""
    for poly in contours(shape):
        d = first_direction(poly)
        if d is not None:
            return poly[0], d
    return None


def reverse_count(shapes: Iterable[Shape]) -> int:
    return sum(1 for s in shapes if s.reverse)


__all__ = ["can_reverse", "contours", "direction_marker", "first_direction", "reverse_count",
           "reverse_polyline", "toggled", "with_reverse"]
