"""Entlang eines Pfads: Bogenlängen-Parametrisierung und „Entlang Pfad kopieren“
(LightBurn *Copy Along Path*, xTool Creative Space „Entlang Pfad anordnen“), Qt-frei.

:class:`PathCurve` beschreibt eine Polylinie in Arbeitsflächen-mm über ihre
Bogenlänge ``s`` (0 … ``length``): Punkt, Tangente und Sehnenwinkel. Geschlossene
Pfade laufen über den Anfang hinaus weiter (``s`` modulo Länge), offene werden
an beiden Enden geradlinig verlängert. Die gleiche Kurve nutzt „Text auf Pfad“
(:mod:`lumacut_job.pathtext`).

Für geschlossene Umrisse ist der Bezug unabhängig davon, wo der Umriss
gezeichnet wurde: :func:`normalize_closed` legt den Anfang auf den obersten
Schnittpunkt mit der senkrechten Mittellinie der Box (Kreis/Ellipse: 12 Uhr,
Rechteck: Mitte der Oberkante, Stern: obere Spitze) und lässt ihn auf dem
Bildschirm im Uhrzeigersinn laufen – wie beim Bogentext (0° = oben).

Winkel in Grad im Uhrzeigersinn auf dem Bildschirm (Y nach unten), wie
``Geometry.rot``: 0 = nach rechts, 90 = nach unten.

Die Umrisse der Objekte liefert :func:`lumacut_canvas.shape_paths.shape_polygons`
(Qt) – :func:`shape_curve` importiert es erst beim Aufruf, Tests können eigene
Polylinien übergeben.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .model import Document, Shape, new_id
from .workarea import is_inside_work_area

Point = tuple[float, float]

# Objektarten, die als Pfad dienen können (Text, Bild und Codes nicht).
PATH_KINDS = ("line", "path", "polygon", "ellipse", "rect")
COUNT_RANGE = (2, 500)
START_RANGE = (0.0, 100.0)      # % der Pfadlänge (nur geschlossene Pfade)
MIN_LENGTH_MM = 1.0
_EPS = 1e-9


def _dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _dedupe(pts: Iterable[Point]) -> list[Point]:
    out: list[Point] = []
    for p in pts:
        p = (float(p[0]), float(p[1]))
        if not out or _dist(out[-1], p) > 1e-7:
            out.append(p)
    return out


def signed_area(ring: list[Point]) -> float:
    """Shoelace-Fläche; > 0 = auf dem Bildschirm (Y nach unten) im Uhrzeigersinn."""
    a = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return a / 2.0


def normalize_closed(ring: list[Point]) -> list[Point]:
    """Geschlossenen Ring (ohne doppelten Endpunkt) im Uhrzeigersinn ab „oben Mitte“.

    Anfang = oberster Schnittpunkt des Rings mit der senkrechten Linie durch
    die Mitte seiner Box (wird als Punkt eingefügt); gibt es keinen (entartet),
    der oberste Punkt.
    """
    pts = _dedupe(ring)
    if len(pts) > 1 and _dist(pts[0], pts[-1]) <= 1e-7:
        pts.pop()
    if len(pts) < 3:
        return pts
    if signed_area(pts) < 0:
        pts.reverse()
    xs = [p[0] for p in pts]
    cx = (min(xs) + max(xs)) / 2.0
    best: tuple[float, int, Point] | None = None   # (y, Segment-Index, Punkt)
    n = len(pts)
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        if not (min(x0, x1) - 1e-9 <= cx <= max(x0, x1) + 1e-9):
            continue
        if abs(x1 - x0) < _EPS:      # senkrechtes Segment auf der Mittellinie
            cand = [(y0, (x0, y0)), (y1, (x1, y1))]
        else:
            t = (cx - x0) / (x1 - x0)
            y = y0 + t * (y1 - y0)
            cand = [(y, (cx, y))]
        for y, p in cand:
            if best is None or y < best[0] - 1e-9:
                best = (y, i, p)
    if best is None:
        k = min(range(n), key=lambda j: (pts[j][1], pts[j][0]))
        return pts[k:] + pts[:k]
    _y, i, p = best
    rest = pts[i + 1:] + pts[:i + 1]          # ab dem Endpunkt des Schnitt-Segments
    out = [p] + rest
    if _dist(out[-1], p) <= 1e-7:
        out.pop()
    if len(out) > 1 and _dist(out[1], p) <= 1e-7:
        out.pop(1)
    return out


@dataclass
class PathCurve:
    """Polylinie über ihre Bogenlänge; ``closed``: letzter Punkt läuft zum ersten."""

    points: list[Point]
    closed: bool = False
    cum: list[float] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        pts = _dedupe(self.points)
        if self.closed and len(pts) > 1 and _dist(pts[0], pts[-1]) <= 1e-7:
            pts.pop()
        if len(pts) < 2:
            raise ValueError("Der Pfad braucht mindestens zwei verschiedene Punkte")
        if self.closed:
            if len(pts) < 3:
                self.closed = False
            else:
                pts = pts + [pts[0]]
        self.points = pts
        cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            cum.append(cum[-1] + _dist(a, b))
        self.cum = cum

    @property
    def length(self) -> float:
        return self.cum[-1]

    def _wrap(self, s: float) -> float:
        L = self.length
        if self.closed and L > 0:
            s = s % L
        return s

    def _segment(self, s: float) -> int:
        """Index des Segments, auf dem ``s`` liegt (0 … n-2; außerhalb: Endsegment)."""
        i = bisect.bisect_right(self.cum, s) - 1
        return max(0, min(len(self.points) - 2, i))

    def point_at(self, s: float) -> Point:
        s = self._wrap(float(s))
        i = self._segment(s)
        a, b = self.points[i], self.points[i + 1]
        seg = self.cum[i + 1] - self.cum[i]
        t = (s - self.cum[i]) / seg if seg > 0 else 0.0
        return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])

    def tangent_at(self, s: float) -> Point:
        """Einheitsvektor der Laufrichtung bei ``s``."""
        s = self._wrap(float(s))
        i = self._segment(s)
        a, b = self.points[i], self.points[i + 1]
        d = _dist(a, b) or 1.0
        return (b[0] - a[0]) / d, (b[1] - a[1]) / d

    def angle_at(self, s: float) -> float:
        tx, ty = self.tangent_at(s)
        return math.degrees(math.atan2(ty, tx))

    def chord_angle(self, s0: float, s1: float) -> float:
        """Winkel der Sehne von ``s0`` nach ``s1`` (Tangente, wenn sie entartet)."""
        p, q = self.point_at(s0), self.point_at(s1)
        if _dist(p, q) < 1e-6:
            return self.angle_at((s0 + s1) / 2.0)
        return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))

    def reversed(self) -> "PathCurve":
        """Gleiche Kurve in Gegenrichtung (geschlossen: gleicher Anfang)."""
        if self.closed:
            ring = self.points[:-1]
            return PathCurve([ring[0]] + ring[1:][::-1], True)
        return PathCurve(self.points[::-1], False)


def is_open_shape(shape: Shape) -> bool:
    return shape.kind in ("line", "path")


def can_be_path(shape: Shape) -> bool:
    if shape.kind not in PATH_KINDS or shape.generator:
        return False
    if shape.kind == "line":
        return abs(shape.geom.w) + abs(shape.geom.h) > _EPS
    return True


def shape_curve(shape: Shape, polylines: list[list[Point]] | None = None) -> PathCurve:
    """Pfad eines Objekts: längster Teilpfad seines Umrisses (inkl. Drehung).

    Linien und offene Pfade bleiben offen (Richtung wie gezeichnet),
    Rechtecke / Ellipsen / Polygone werden mit :func:`normalize_closed`
    geschlossen. ``polylines``: Umriss in mm (Standard: ``shape_polygons``).
    """
    if not can_be_path(shape):
        raise ValueError("Als Pfad eignen sich Linien, Pfade, Polygone, Rechtecke und Ellipsen")
    if polylines is None:
        from .shape_paths import shape_polygons
        polylines = shape_polygons(shape)
    best: PathCurve | None = None
    closed_kind = not is_open_shape(shape)
    for poly in polylines:
        pts = _dedupe(poly)
        if len(pts) < 2:
            continue
        closed = closed_kind or (len(pts) > 2 and _dist(pts[0], pts[-1]) <= 1e-6)
        try:
            c = PathCurve(normalize_closed(pts) if closed else pts, closed)
        except ValueError:
            continue
        if best is None or c.length > best.length + 1e-9:
            best = c
    if best is None or best.length < MIN_LENGTH_MM:
        raise ValueError("Der Pfad ist zu kurz")
    return best


def pick_path(doc: Document, ids: Iterable[str], exclude_text: bool = False) -> str | None:
    """Welches ausgewählte Objekt der Pfad ist.

    Kandidaten sind ungruppierte Linien / Pfade / Polygone / Rechtecke /
    Ellipsen. Ein einziger Kandidat ist der Pfad; sonst gewinnt ein offener
    Pfad (Linie, offener Pfad), dann der mit der größten Box-Diagonale
    (der Pfad ist meist größer als das, was darauf soll).
    """
    cands = []
    for i in ids:
        if not doc.has_shape(i):
            continue
        s = doc.shape(i)
        if s.groups or not can_be_path(s):
            continue
        cands.append(s)
    if not cands:
        return None
    def key(s: Shape):
        b = s.bounds()
        return (1 if is_open_shape(s) else 0, math.hypot(b.w, b.h))
    return max(cands, key=key).id


@dataclass
class CopyResult:
    shapes: list[Shape]
    count: int
    length_mm: float
    step_mm: float
    closed: bool

    def readout(self) -> str:
        kind = "geschlossen" if self.closed else "offen"
        return (f"{self.count} Kopie(n) im Abstand {self.step_mm:.1f} mm auf "
                f"{self.length_mm:.1f} mm Pfad ({kind})")


def stations(curve: PathCurve, count: int, start_pct: float = 0.0) -> list[float]:
    """Bogenlängen von ``count`` gleichmäßig verteilten Stellen.

    Offener Pfad: erste am Anfang, letzte am Ende. Geschlossener Pfad:
    ``count`` gleiche Abstände ab ``start_pct`` % der Länge (Anfang = oben Mitte).
    """
    count = int(max(COUNT_RANGE[0], min(COUNT_RANGE[1], count)))
    L = curve.length
    if curve.closed:
        s0 = L * max(START_RANGE[0], min(START_RANGE[1], float(start_pct))) / 100.0
        return [(s0 + L * k / count) % L for k in range(count)]
    return [L * k / (count - 1) for k in range(count)]


def copy_along(doc: Document, ids: Iterable[str], curve: PathCurve, count: int,
               rotate: bool = True, start_pct: float = 0.0) -> CopyResult:
    """``count`` Kopien der Auswahl ``ids`` gleichmäßig entlang ``curve``.

    Die Auswahl zählt als eine Einheit (ihre Gruppen bleiben, jede Kopie bekommt
    neue Gruppen-IDs): die Mitte ihrer Box kommt auf die Stelle des Pfads,
    ``rotate`` dreht die Kopie mit der Pfadrichtung (die Auswahl gilt als nach
    rechts zeigend, wie die Speichen beim Kreis-Array). Das Original bleibt.
    """
    sel = [i for i in ids if doc.has_shape(i)]
    if not sel:
        raise ValueError("Keine Objekte zum Kopieren ausgewählt")
    if curve.length < MIN_LENGTH_MM:
        raise ValueError("Der Pfad ist zu kurz")
    b = doc.selection_bounds(sel)
    ux, uy = b.x + b.w / 2.0, b.y + b.h / 2.0
    out: list[Shape] = []
    places = stations(curve, count, start_pct)
    for s in places:
        px, py = curve.point_at(s)
        ang = curve.angle_at(s) if rotate else 0.0
        remap: dict[str, str] = {}
        for i in sel:
            src = doc.shape(i)
            c = src.copy(new_identity=True)
            c.groups = tuple(remap.setdefault(g, new_id()) for g in src.groups)
            g = src.geom.rotated(ang, ux, uy) if ang else src.geom.copy()
            c.geom = g.translated(px - ux, py - uy)
            out.append(c)
    n = len(places)
    step = curve.length / (n if curve.closed else n - 1)
    return CopyResult(out, n, curve.length, step, curve.closed)


def outside_count(shapes: Iterable[Shape]) -> int:
    return sum(0 if is_inside_work_area(s.bounds(), 1e-3) else 1 for s in shapes)


def copy_selection(doc: Document, ids: Iterable[str], count: int, rotate: bool = True,
                   start_pct: float = 0.0,
                   outline: Callable[[Shape], list[list[Point]]] | None = None) -> CopyResult:
    """Auswahl in Pfad (:func:`pick_path`) und Objekte teilen und kopieren."""
    sel = doc.expand_to_groups(ids)
    pid = pick_path(doc, sel)
    if pid is None:
        raise ValueError("Bitte zusätzlich einen Pfad auswählen (Linie, Pfad, Polygon, Rechteck "
                         "oder Ellipse)")
    rest = [i for i in sel if i != pid]
    if not rest:
        raise ValueError("Bitte außer dem Pfad die Objekte auswählen, die kopiert werden sollen")
    path = doc.shape(pid)
    curve = shape_curve(path, outline(path) if outline else None)
    return copy_along(doc, rest, curve, count, rotate, start_pct)


__all__ = ["COUNT_RANGE", "CopyResult", "PathCurve", "START_RANGE", "can_be_path", "copy_along",
           "copy_selection", "normalize_closed", "pick_path", "shape_curve", "stations"]
