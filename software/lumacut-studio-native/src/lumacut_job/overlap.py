"""Überlappende Linien nur einmal schneiden (Qt-frei).

Wie LightBurn *Optimization Settings › Remove overlapping lines*: grenzen zwei
Teile mit einer gemeinsamen Kante aneinander (CAD-Export: jedes Teil bringt
seine eigene Kontur mit) oder liegen Strecken teilweise übereinander, würde
der Laser dieselbe Linie zweimal fahren – auf einem Diodenlaser verkohlt die
Kante, und das schon freigeschnittene Teil wird ein zweites Mal beschossen.

:func:`remove_overlaps` geht die Polylinien einer Ebene in **Schnittreihenfolge**
durch (nach dem Planer, also „innen zuerst“ bleibt erhalten) und entfernt aus
jeder Strecke die Abschnitte, die schon von einer früher geschnittenen Strecke
(auch derselben Polylinie) abgedeckt sind: nahezu parallel (≤ ~11,5°) und
höchstens ``tolerance_mm`` entfernt. Bloße Kreuzungen und Berührungen an
Endpunkten bleiben unverändert; abgedeckte Abschnitte kürzer als
2 × Toleranz (bei kürzeren Strecken: weniger als 90 % der Strecke) werden
nicht entfernt, Reststücke kürzer als die Toleranz
entfallen. Eine geschlossene Kontur, aus der ein Stück entfernt wurde, wird
zu einem offenen Linienzug (beide Reste an ihrem Startpunkt verbunden).

Nur Konturen/Linien – Füllungen und Bilder sind nie betroffen. Der Planer
überspringt Ebenen mit Kerf-Versatz, Haltestegen, An-/Abfahrt oder Überschnitt
(diese Optionen brauchen die vollständige geschlossene Kontur); Perforation
wird danach auf die verbleibenden Stücke angewandt.

Alle Koordinaten in Maschinen-mm. Unveränderte Polylinien werden als dasselbe
Objekt zurückgegeben (G-Code ohne Überlappung bleibt Byte für Byte gleich).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Point = tuple[float, float]
Poly = list[Point]

MAX_SIN = 0.2              # ≈ 11,5°: steiler gilt als Kreuzung, nicht als Überlappung
MIN_TOLERANCE_MM = 0.001
_EPS = 1e-9


@dataclass
class OverlapResult:
    polylines: list[Poly] = field(default_factory=list)
    removed_mm: float = 0.0     # nicht mehr geschnittene Länge
    changed: int = 0            # Polylinien, aus denen etwas entfernt wurde


class _SegmentIndex:
    """Gitter über bereits geschnittene Strecken (jede Zelle: Streckennummern)."""

    def __init__(self, cell: float) -> None:
        self.cell = cell
        self.cells: dict[tuple[int, int], list[int]] = {}
        self.segments: list[tuple[Point, Point]] = []

    def _cells_along(self, a: Point, b: Point):
        c = self.cell
        n = max(1, int(math.ceil(math.dist(a, b) / (c * 0.5))))
        seen = set()
        for k in range(n + 1):
            t = k / n
            x = a[0] + (b[0] - a[0]) * t
            y = a[1] + (b[1] - a[1]) * t
            ix, iy = int(math.floor(x / c)), int(math.floor(y / c))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    key = (ix + dx, iy + dy)
                    if key not in seen:
                        seen.add(key)
                        yield key

    def add(self, a: Point, b: Point) -> None:
        i = len(self.segments)
        self.segments.append((a, b))
        for key in self._cells_along(a, b):
            self.cells.setdefault(key, []).append(i)

    def near(self, a: Point, b: Point):
        found = set()
        for key in self._cells_along(a, b):
            for i in self.cells.get(key, ()):
                if i not in found:
                    found.add(i)
                    yield self.segments[i]


def covered_interval(a: Point, b: Point, c: Point, d: Point, tol: float):
    """Abschnitt ``(t0, t1)`` (mm entlang ``a → b``), den die Strecke ``c → d``
    innerhalb ``tol`` und nahezu parallel abdeckt, sonst ``None``."""
    length = math.dist(a, b)
    lk = math.dist(c, d)
    if length < _EPS or lk < _EPS:
        return None
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    vx, vy = (d[0] - c[0]) / lk, (d[1] - c[1]) / lk
    if abs(ux * vy - uy * vx) > MAX_SIN:
        return None
    # Querabstand von c bzw. d zur Geraden a-b (vorzeichenbehaftet), linear entlang c-d.
    hc = ux * (c[1] - a[1]) - uy * (c[0] - a[0])
    hd = ux * (d[1] - a[1]) - uy * (d[0] - a[0])
    s0, s1 = 0.0, 1.0
    if abs(hd - hc) < _EPS:
        if abs(hc) > tol:
            return None
    else:
        ta, tb = (-tol - hc) / (hd - hc), (tol - hc) / (hd - hc)
        s0, s1 = max(s0, min(ta, tb)), min(s1, max(ta, tb))
        if s1 <= s0:
            return None
    p0 = (c[0] + (d[0] - c[0]) * s0, c[1] + (d[1] - c[1]) * s0)
    p1 = (c[0] + (d[0] - c[0]) * s1, c[1] + (d[1] - c[1]) * s1)
    t0 = (p0[0] - a[0]) * ux + (p0[1] - a[1]) * uy
    t1 = (p1[0] - a[0]) * ux + (p1[1] - a[1]) * uy
    t0, t1 = max(0.0, min(t0, t1)), min(length, max(t0, t1))
    if t1 - t0 < 1e-6:
        return None
    # Auch die Enden des Abschnitts auf a-b müssen nah an c-d liegen.
    for t in (t0, t1):
        q = (a[0] + ux * t, a[1] + uy * t)
        if _point_segment_distance(q, c, d) > tol * 1.5 + 1e-6:
            return None
    return t0, t1


def _point_segment_distance(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    if l2 < _EPS:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
    return math.dist(p, (a[0] + dx * t, a[1] + dy * t))


def _merge(intervals: list[tuple[float, float]], gap: float) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for t0, t1 in sorted(intervals):
        if out and t0 <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], t1)
        else:
            out.append([t0, t1])
    return [(a, b) for a, b in out]


def _length(poly: Poly) -> float:
    return sum(math.dist(p, q) for p, q in zip(poly, poly[1:]))


def _is_closed(poly: Poly) -> bool:
    return len(poly) >= 4 and math.dist(poly[0], poly[-1]) <= 0.01


def remove_overlaps(polys: list[Poly], tolerance_mm: float) -> OverlapResult:
    """Polylinien (Schnittreihenfolge) ohne bereits geschnittene Abschnitte."""
    res = OverlapResult()
    tol = float(tolerance_mm)
    if tol < MIN_TOLERANCE_MM:
        res.polylines = list(polys)
        return res
    index = _SegmentIndex(max(2.0, 4 * tol))
    for poly in polys:
        if len(poly) < 2:
            res.polylines.append(poly)
            continue
        runs: list[Poly] = []
        cur: Poly | None = None
        removed = 0.0
        for a, b in zip(poly, poly[1:]):
            a, b = (float(a[0]), float(a[1])), (float(b[0]), float(b[1]))
            length = math.dist(a, b)
            if length < _EPS:
                continue
            cov = [iv for c, d in index.near(a, b)
                   if (iv := covered_interval(a, b, c, d, tol)) is not None]
            # Nur echte Überdeckung: mindestens 2 × Toleranz (kurze Strecken: fast ganz) –
            # bloßes Anstoßen an einem Endpunkt ergibt eine Länge von 0.
            cov = [iv for iv in _merge(cov, tol)
                   if iv[1] - iv[0] >= min(2 * tol, 0.9 * length)]
            # Abdeckung bis auf < tol an die Streckenenden heranziehen (keine Krümel).
            cov = [(0.0 if t0 < tol else t0, length if length - t1 < tol else t1)
                   for t0, t1 in cov]
            kept: list[tuple[float, float]] = []
            t = 0.0
            for t0, t1 in cov:
                if t0 > t:
                    kept.append((t, t0))
                removed += t1 - t0
                t = max(t, t1)
            if t < length:
                kept.append((t, length))
            ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length

            def at(s: float) -> Point:
                if s <= 0:
                    return a
                if s >= length:
                    return b
                return (a[0] + ux * s, a[1] + uy * s)

            for k, (t0, t1) in enumerate(kept):
                p0, p1 = at(t0), at(t1)
                if cur is not None and t0 <= 0.0:
                    cur.append(p1)
                else:
                    if cur is not None:
                        runs.append(cur)
                    cur = [p0, p1]
            if not kept or kept[-1][1] < length:
                if cur is not None:
                    runs.append(cur)
                cur = None
            for t0, t1 in kept:
                index.add(at(t0), at(t1))
        if cur is not None:
            runs.append(cur)
        if removed <= _EPS:
            res.polylines.append(poly)
            continue
        res.changed += 1
        res.removed_mm += removed
        if (_is_closed(poly) and len(runs) >= 2 and math.dist(runs[0][0], poly[0]) < 1e-9
                and math.dist(runs[-1][-1], poly[-1]) < 1e-9):
            runs = [runs[-1] + runs[0][1:]] + runs[1:-1]
        for r in runs:
            if _length(r) >= tol:
                res.polylines.append(r)
            else:
                res.removed_mm += _length(r)
    return res
