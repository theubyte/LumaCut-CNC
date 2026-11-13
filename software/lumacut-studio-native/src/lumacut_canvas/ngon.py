"""Regelmäßige Vielecke und Sterne (LightBurn *Polygon*-Werkzeug, xTool „Polygon“ /
„Stern“).

Ein Vieleck / Stern ist ein gewöhnliches ``polygon``-Objekt – Punkte normiert auf die
Objektbox wie jedes Polygon –, das zusätzlich ``Shape.regular = (Seiten, Innenradius)``
trägt. Dadurch laufen G-Code, Planer, Kerf / Stege / An- und Abfahrt, Füllung,
Boole / Versatz, Knoten, Export und Pfadvorschau ohne Sonderfall (nur ``G1``). Das Feld
„Seiten“ der Eigenschaftsleiste wird nur angeboten, solange die Punkte noch zur
gespeicherten Vorgabe passen (:func:`spec_of`) – wer Knoten verschiebt, vereinfacht oder
verrechnet, hat danach ein gewöhnliches Polygon (wie LightBurns *Convert to Path*).

Geometrie: Außenradius 1 um den Mittelpunkt, erste Spitze oben (Y nach unten),
Punkte im Uhrzeigersinn auf dem Bildschirm. Ein Stern hat ``2 × Seiten`` Punkte, die
Innenecken liegen auf ``Innenradius × Außenradius`` genau zwischen zwei Spitzen.

Reines Python, kein Qt.
"""

from __future__ import annotations

import math
from dataclasses import replace

from .model import REGULAR_MAX_SIDES, Geometry, Shape, rotate_point

MIN_SIDES = 3
MAX_SIDES = REGULAR_MAX_SIDES
INNER_MIN = 0.05
INNER_MAX = 0.95
DEFAULT_SIDES = 6          # LightBurn legt ein Sechseck an
DEFAULT_STAR_INNER = 0.5   # Innenradius beim Einschalten von „Stern“
MATCH_TOL = 1e-5           # normierte Punkte, die noch als „unverändert“ gelten


def normalize(sides, inner) -> tuple[int, float]:
    """(Seiten, Innenradius) in den gültigen Bereich; Innenradius 0 = Vieleck."""
    try:
        n = int(round(float(sides)))
    except (TypeError, ValueError):
        n = DEFAULT_SIDES
    n = min(max(n, MIN_SIDES), MAX_SIDES)
    try:
        r = float(inner or 0.0)
    except (TypeError, ValueError):
        r = 0.0
    if not math.isfinite(r) or r <= 0.0:
        return n, 0.0
    return n, round(min(max(r, INNER_MIN), INNER_MAX), 6)


def is_star(spec) -> bool:
    return bool(spec) and spec[1] > 0.0


def unit_outline(sides: int, inner: float = 0.0) -> list[tuple[float, float]]:
    """Umriss mit Außenradius 1 um (0, 0): erste Spitze oben, im Uhrzeigersinn."""
    n, r = normalize(sides, inner)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        pts.append((round(math.sin(a), 12), round(-math.cos(a), 12)))
        if r:
            b = a + math.pi / n
            pts.append((round(r * math.sin(b), 12), round(-r * math.cos(b), 12)))
    return pts


def unit_box(sides: int, inner: float = 0.0) -> tuple[float, float, float, float]:
    """(x0, y0, w, h) des Umrisses mit Außenradius 1 (Mittelpunkt bei 0, 0)."""
    pts = unit_outline(sides, inner)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def normalized_points(sides: int, inner: float = 0.0) -> tuple[tuple[float, float], ...]:
    """Punkte normiert auf die Box des Umrisses (0..1) wie ``Shape.points``."""
    x0, y0, w, h = unit_box(sides, inner)
    return tuple(((px - x0) / w, (py - y0) / h) for px, py in unit_outline(sides, inner))


def _place(cx: float, cy: float, sx: float, sy: float, rot: float, n: int, r: float) -> Geometry:
    """Box für Mittelpunkt (cx, cy), Maßstab sx / sy (Außenradius in mm je Achse), Drehung."""
    x0, y0, w, h = unit_box(n, r)
    # Mitte der Box relativ zum Mittelpunkt des Vielecks (ungleich 0 bei ungerader Seitenzahl)
    bx, by = (x0 + w / 2) * sx, (y0 + h / 2) * sy
    if rot:
        bx, by = rotate_point(bx, by, 0.0, 0.0, rot)
    g = Geometry(0.0, 0.0, w * sx, h * sy, rot)
    return g.with_center(cx + bx, cy + by)


def make_shape(layer_id: str, cx: float, cy: float, radius: float, sides: int = DEFAULT_SIDES,
               inner: float = 0.0, rot: float = 0.0) -> Shape:
    """Vieleck / Stern mit Mittelpunkt (cx, cy) und Außenradius ``radius`` mm."""
    n, r = normalize(sides, inner)
    radius = abs(float(radius))
    return Shape("polygon", _place(cx, cy, radius, radius, rot, n, r), layer_id,
                 points=normalized_points(n, r), regular=(n, r))


def _same_points(a, b) -> bool:
    if len(a) != len(b):
        return False
    # Als Menge vergleichen: waagerecht gespiegelt (u → 1 − u, umgekehrte Reihenfolge)
    # bleibt ein symmetrisches Vieleck dasselbe Vieleck.
    rest = list(b)
    for p in a:
        best = min(range(len(rest)), key=lambda i: abs(rest[i][0] - p[0]) + abs(rest[i][1] - p[1]))
        q = rest.pop(best)
        if abs(q[0] - p[0]) > MATCH_TOL or abs(q[1] - p[1]) > MATCH_TOL:
            return False
    return True


def spec_of(shape: Shape) -> tuple[int, float] | None:
    """(Seiten, Innenradius), solange ``shape`` noch das gespeicherte Vieleck / der Stern ist."""
    if shape.kind != "polygon" or not shape.regular or shape.rings or shape.curves:
        return None
    try:
        n, r = normalize(*shape.regular)
    except TypeError:
        return None
    if (n, r) != tuple(shape.regular):
        return None
    return (n, r) if _same_points(shape.points, normalized_points(n, r)) else None


def centre_of(shape: Shape) -> tuple[float, float]:
    """Mittelpunkt (Umkreismitte) eines Vielecks / Sterns in Arbeitsflächen-mm."""
    n, r = spec_of(shape) or (DEFAULT_SIDES, 0.0)
    g = shape.geom
    x0, y0, w, h = unit_box(n, r)
    sx, sy = g.w / w, g.h / h
    bx, by = (x0 + w / 2) * sx, (y0 + h / 2) * sy
    if g.rot:
        bx, by = rotate_point(bx, by, 0.0, 0.0, g.rot)
    gcx, gcy = g.center()
    return gcx - bx, gcy - by


def with_spec(shape: Shape, sides=None, inner=None) -> Shape:
    """Kopie mit anderer Seitenzahl / anderem Innenradius (``None`` = unverändert).

    Mittelpunkt, Drehung und Maßstab (Außenradius je Achse) bleiben, die Box passt sich
    dem neuen Umriss an. Manuelle Stege entfallen (der Umriss ist ein anderer)."""
    old = spec_of(shape)
    if old is None:
        return shape
    n, r = normalize(old[0] if sides is None else sides, old[1] if inner is None else inner)
    if (n, r) == old:
        return shape
    g = shape.geom
    _, _, w0, h0 = unit_box(*old)
    sx, sy = g.w / w0, g.h / h0
    cx, cy = centre_of(shape)
    geom = _place(cx, cy, sx, sy, g.rot, n, r)
    return replace(shape, geom=geom, points=normalized_points(n, r), regular=(n, r), tabs=(),
                   start=())


def outer_radius(shape: Shape) -> float:
    """Außenradius in mm (bei gestrecktem Vieleck der größere der beiden Achsen)."""
    spec = spec_of(shape)
    if spec is None:
        return 0.0
    _, _, w, h = unit_box(*spec)
    return max(shape.geom.w / w, shape.geom.h / h)


def label(spec) -> str:
    n, r = spec
    if r:
        return f"Stern {n} Zacken · innen {round(r * 100)} %"
    return f"Vieleck {n} Ecken"


def describe(shapes) -> str:
    specs = [spec_of(s) for s in shapes]
    specs = [s for s in specs if s]
    if not specs:
        return ""
    text = label(specs[0])
    if len(set(specs)) > 1:
        text += " …"
    if len(specs) > 1:
        text += f" · {len(specs)} Objekte"
    return text
