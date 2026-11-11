"""Manuelle Haltestege je Objekt (LightBurn *Tab tool* / *Add Tabs*).

Ein Steg ist ein Punkt auf dem Umriss einer geschlossenen Kontur des Objekts
(``Shape.tabs``, normiert auf die ungedrehte Objektbox – Verschieben,
Skalieren, Drehen, Duplizieren und Arrays nehmen ihn mit). Beim Senden legt
der Planer (:mod:`lumacut_job.cutpath`) an jedem Punkt einen Steg der
Stegbreite der Ebene (``tab_width_mm``) – an dieser Kontur *statt* der
automatischen Stege der Ebene (wie LightBurn: eine Form mit eigenen Stegen
bekommt keine automatischen). Konturen ohne eigene Stege behalten die
automatischen Stege der Ebene; Stegbreite 0 schaltet alle Stege der Ebene ab.

Hier nur die Rechnung (Qt nur über :func:`shape_paths.shape_polygons`); die
Bedienung (Werkzeug „Stege“, Markierungen, Menü) liegt in :mod:`tabs_ui`.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Iterable

from .model import Shape, tabs_from_world

Point = tuple[float, float]

#: Objektarten, die Stege tragen können (geschlossene Konturen; Bilder und Linien nicht).
TAB_KINDS = ("rect", "ellipse", "polygon", "path", "text")
#: Zwei Stege näher als das (mm) auf derselben Kontur gelten als ein Steg.
MIN_TAB_DISTANCE_MM = 0.5


def closed_rings(shape: Shape) -> list[list[Point]]:
    """Geschlossene Ringe des Objekts in Arbeitsflächen-mm (Anfang = Ende)."""
    if shape is None or shape.kind not in TAB_KINDS:
        return []
    from .shape_paths import shape_polygons
    out = []
    for poly in shape_polygons(shape):
        if len(poly) >= 4 and math.dist(poly[0], poly[-1]) < 1e-6:
            out.append(poly)
    return out


def can_have_tabs(shape: Shape) -> bool:
    return bool(closed_rings(shape))


def project(p: Point, a: Point, b: Point) -> tuple[float, Point]:
    """Abstand von ``p`` zur Strecke ``a``–``b`` und der nächste Punkt darauf."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    ll = dx * dx + dy * dy
    t = 0.0 if ll <= 1e-18 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ll))
    q = (a[0] + dx * t, a[1] + dy * t)
    return math.dist(p, q), q


def nearest_on_rings(rings: Iterable[list[Point]], p: Point) -> tuple[float, Point | None, int]:
    """``(Abstand, Punkt, Ring-Index)`` des nächsten Umrisspunkts (``inf, None, -1`` ohne Ringe)."""
    best = (math.inf, None, -1)
    for k, ring in enumerate(rings):
        for a, b in zip(ring, ring[1:]):
            d, q = project(p, a, b)
            if d < best[0]:
                best = (d, q, k)
    return best


def with_tab_points(shape: Shape, pts: Iterable[Point]) -> Shape:
    """Kopie mit genau diesen Steg-Punkten (Arbeitsflächen-mm)."""
    return replace(shape, geom=shape.geom.copy(), tabs=tabs_from_world(shape.geom, list(pts)))


def tab_at(shape: Shape, p: Point, tol_mm: float) -> int | None:
    """Index des Stegs, der ``p`` am nächsten liegt (höchstens ``tol_mm`` entfernt)."""
    best, best_d = None, tol_mm
    for i, q in enumerate(shape.tab_points()):
        d = math.dist(p, q)
        if d <= best_d:
            best, best_d = i, d
    return best


def add_tab(shape: Shape, p: Point, tol_mm: float) -> tuple[Shape | None, str]:
    """Steg am nächsten Umrisspunkt zu ``p`` einfügen: ``(neue Form | None, Grund)``."""
    rings = closed_rings(shape)
    if not rings:
        return None, "Nur geschlossene Konturen bekommen Stege."
    d, q, _k = nearest_on_rings(rings, p)
    if q is None or d > tol_mm:
        return None, "Kein Umriss unter dem Zeiger – auf die Kontur tippen."
    pts = shape.tab_points()
    if any(math.dist(q, t) < MIN_TAB_DISTANCE_MM for t in pts):
        return None, "Dort sitzt schon ein Steg."
    return with_tab_points(shape, pts + [q]), ""


def remove_tab(shape: Shape, index: int) -> Shape:
    pts = shape.tab_points()
    return with_tab_points(shape, [q for i, q in enumerate(pts) if i != index])


def move_tab(shape: Shape, index: int, p: Point) -> Shape | None:
    """Steg ``index`` auf den Umrisspunkt nächst ``p`` schieben (``None`` ohne Umriss)."""
    d, q, _k = nearest_on_rings(closed_rings(shape), p)
    if q is None:
        return None
    pts = shape.tab_points()
    pts[index] = q
    return with_tab_points(shape, pts)


def clear_tabs(shape: Shape) -> Shape:
    return replace(shape, geom=shape.geom.copy(), tabs=())


def carry_tabs(new: Shape, pts: Iterable[Point], tol_mm: float = 1.5) -> Shape:
    """Steg-Punkte (Arbeitsflächen-mm) auf ``new`` übertragen: jeder Punkt, der
    höchstens ``tol_mm`` neben einer geschlossenen Kontur von ``new`` liegt,
    wird auf sie gesetzt, die übrigen entfallen (für Knoten bearbeiten,
    Vereinfachen, Zerlegen, Kombinieren)."""
    pts = list(pts)
    if not pts:
        return new if not new.tabs else clear_tabs(new)
    rings = closed_rings(new)
    keep = []
    for p in pts:
        d, q, _k = nearest_on_rings(rings, p)
        if q is not None and d <= tol_mm and all(math.dist(q, t) >= MIN_TAB_DISTANCE_MM for t in keep):
            keep.append(q)
    return with_tab_points(new, keep)


def tab_count(shapes: Iterable[Shape]) -> int:
    return sum(len(s.tabs) for s in shapes)
