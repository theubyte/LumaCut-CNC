"""Überstände abschneiden (LightBurn *Trim Shapes* / xTool „Zuschneiden“ von Linien).

Wer Rahmen, Raster oder Beschriftungslinien aus Linien zeichnet oder aus einem
CAD-/SVG-Import bekommt, hat an jeder Kreuzung kleine Überstände: die Linie ragt
ein paar Millimeter über die Gegenlinie hinaus. Auf einem Diodenlaser brennt
jeder Überstand sichtbar mit (und eine Ecke aus zwei Linien wird nie zu einer
geschlossenen Kontur, die sich füllen oder mit Kerf versetzen ließe).

:func:`trim_stubs` schneidet solche Überstände automatisch ab, ohne Klickwerkzeug
(touch-tauglich): Ein Überstand ist das freie Ende eines offenen Pfads / einer
Linie hinter einer Kreuzung mit einem anderen offenen Pfad oder der Kontur einer
geschlossenen Form der Auswahl, mit höchstens ``max_mm`` Länge. Er wird nur
entfernt, wenn der Rest des Pfads länger ist als der Überstand (zwei gleich lange
Arme eines Kreuzes bleiben also stehen – das ist keine Entscheidung, die man
raten sollte). Enden, die eine andere Kontur berühren (Ecken, T-Stöße), sind
nie Überstände. Formen ohne Überstand bleiben unverändert (gleiche Objekte).
Erzeugte Objekte werden übergangen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from shapely.geometry import LineString, Point as SPoint
from shapely.ops import substring, unary_union
from shapely.strtree import STRtree

from .model import FILLABLE_KINDS, Shape
from .pathjoin import JOIN_TOLERANCE_MM, is_open, open_pieces

TRIM_MAX_MM = 3.0
TRIM_RANGE_MM = (0.1, 50.0)
_MIN_REST_MM = 0.01
Point = tuple[float, float]


@dataclass
class TrimResult:
    remove: list[str] = field(default_factory=list)
    add: list[Shape] = field(default_factory=list)
    stubs: int = 0
    length_mm: float = 0.0
    open_found: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.remove)

    def summary(self) -> str:
        if not self.stubs:
            return "keine Überstände gefunden"
        return (f"{self.stubs} Überstand/Überstände ({self.length_mm:.1f} mm) von "
                f"{len(self.remove)} Form(en) abgeschnitten")


def _cut_distances(line: LineString, cutters) -> list[float]:
    inter = line.intersection(cutters)
    pts: list[SPoint] = []

    def collect(g) -> None:
        if g.is_empty:
            return
        if g.geom_type == "Point":
            pts.append(g)
        elif g.geom_type == "LineString":
            pts.append(SPoint(g.coords[0]))
            pts.append(SPoint(g.coords[-1]))
        else:
            for sub in g.geoms:
                collect(sub)
    collect(inter)
    return sorted(line.project(p) for p in pts)


def _trim_piece(piece: list[Point], cutters, max_mm: float) -> tuple[list[Point], list[float]]:
    """(neuer Linienzug, Längen der abgeschnittenen Überstände)."""
    line = LineString(piece)
    total = line.length
    if cutters is None or total <= 0 or cutters.is_empty:
        return piece, []
    cuts = _cut_distances(line, cutters)
    if not cuts:
        return piece, []
    tol = JOIN_TOLERANCE_MM
    start_free = cutters.distance(SPoint(line.coords[0])) > tol
    end_free = cutters.distance(SPoint(line.coords[-1])) > tol
    inner = [d for d in cuts if tol < d < total - tol]
    if not inner:
        return piece, []
    first, last = inner[0], inner[-1]
    cut_a = cut_b = None
    gone: list[float] = []
    if start_free and first <= max_mm and total - first > first:
        cut_a = first
    if end_free and total - last <= max_mm and last > total - last:
        cut_b = last
    a = cut_a or 0.0
    b = cut_b if cut_b is not None else total
    if cut_a is None and cut_b is None:
        return piece, []
    if b - a < _MIN_REST_MM:
        return piece, []
    if cut_a is not None:
        gone.append(cut_a)
    if cut_b is not None:
        gone.append(total - cut_b)
    rest = substring(line, a, b)
    return [(float(x), float(y)) for x, y in rest.coords], gone


def _closed_outlines(shapes: Iterable[Shape]) -> list[LineString]:
    out: list[LineString] = []
    for s in shapes:
        if s.kind not in FILLABLE_KINDS or s.generator:
            continue
        from .shape_paths import shape_polygons
        for ring in shape_polygons(s, 0.01):
            if len(ring) >= 2:
                out.append(LineString(ring))
    return out


def trim_stubs(shapes: Iterable[Shape], max_mm: float = TRIM_MAX_MM) -> TrimResult:
    """Überstände von offenen Formen der ``shapes`` abschneiden (siehe Moduldoku)."""
    max_mm = min(max(float(max_mm), TRIM_RANGE_MM[0]), TRIM_RANGE_MM[1])
    shapes = list(shapes)
    res = TrimResult()
    owners: list[int] = []
    pieces: list[list[Point]] = []
    open_shapes = [s for s in shapes if is_open(s)]
    res.open_found = len(open_shapes)
    for k, s in enumerate(open_shapes):
        for p in open_pieces(s):
            if len(p) >= 2:
                pieces.append(p)
                owners.append(k)
    if not pieces:
        return res
    lines = [LineString(p) for p in pieces]
    lines += _closed_outlines(shapes)
    tree = STRtree(lines)
    new_pieces: list[list[Point]] = []
    per_owner: dict[int, list[float]] = {}
    for i, piece in enumerate(pieces):
        near = [j for j in tree.query(lines[i].buffer(JOIN_TOLERANCE_MM)) if j != i]
        cutters = unary_union([lines[j] for j in near]) if near else None
        new, gone = _trim_piece(piece, cutters, max_mm)
        new_pieces.append(new)
        if gone:
            per_owner.setdefault(owners[i], []).extend(gone)
    for k, gone in sorted(per_owner.items()):
        src = open_shapes[k]
        pts: list[Point] = []
        starts: list[int] = []
        for i, o in enumerate(owners):
            if o != k:
                continue
            if pts:
                starts.append(len(pts))
            pts.extend(new_pieces[i])
        out = Shape.from_points("path", pts, src.layer_id, rings=starts)
        out.groups = tuple(src.groups)
        out.priority = src.priority
        out.reverse = src.reverse
        res.remove.append(src.id)
        res.add.append(out)
        res.stubs += len(gone)
        res.length_mm += sum(gone)
    return res
