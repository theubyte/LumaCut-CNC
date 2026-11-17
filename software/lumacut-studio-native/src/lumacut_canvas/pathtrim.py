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

Für das Werkzeug „Trimmen“ (:mod:`trim_ui`, LightBurns Klick-Trimmen) liefert
:class:`TrimIndex` das Stück einer Form zwischen den zwei nächsten Kreuzungen
unter einem Punkt (auch innere Stücke und Stücke geschlossener Formen) und mit
:meth:`TrimIndex.sweep` alle Stücke, die eine gezogene Linie kreuzt.
"""

from __future__ import annotations

import math
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


# ------------------------------------------------- Trimmen je Stück (Werkzeug)
#
# LightBurn *Trim Shapes* per Klick: Das Werkzeug „Trimmen“ (:mod:`trim_ui`) entfernt
# das Stück einer Form zwischen den zwei nächsten Kreuzungen mit anderen Formen
# (oder zwischen einer Kreuzung und dem freien Ende) – auch innere Stücke, die
# :func:`trim_stubs` nie anfasst, und Stücke geschlossener Formen (Rechteck,
# Ellipse, Polygon / Stern), die dabei zum offenen Pfad werden.

TRIM_TARGET_KINDS = ("path", "line", "rect", "ellipse", "polygon")
_FLATTEN_MM = 0.01


def can_trim(shape: Shape) -> bool:
    """Form, deren Stücke das Werkzeug entfernen darf (Text / Bilder / erzeugte Objekte nie)."""
    return shape.kind in TRIM_TARGET_KINDS and not shape.generator


def _close(ring: list[Point]) -> list[Point]:
    if len(ring) >= 2 and math.hypot(ring[0][0] - ring[-1][0], ring[0][1] - ring[-1][1]) > 1e-9:
        return ring + [ring[0]]
    return ring


def shape_rings(shape: Shape) -> list[tuple[list[Point], bool]]:
    """(Linienzug in Arbeitsflächen-mm, geschlossen) je Teilpfad einer Form.

    Geschlossene Ringe enden auf ihrem Startpunkt. Bilder liefern nichts."""
    if shape.kind in ("path", "line"):
        return [(p, False) for p in open_pieces(shape) if len(p) >= 2]
    if shape.kind == "image":
        return []
    if shape.kind == "polygon" and not shape.curves:
        pts = _world_points(shape)
        return [(_close(pts[a:b]), True) for a, b in shape.ring_ranges() if b - a >= 2]
    from .shape_paths import shape_polygons
    return [(_close(r), True) for r in shape_polygons(shape, _FLATTEN_MM) if len(r) >= 2]


def _world_points(shape: Shape) -> list[Point]:
    from .model import rotate_point
    g = shape.geom
    pts = shape.abs_points()
    if not g.rot:
        return [(float(x), float(y)) for x, y in pts]
    cx, cy = g.center()
    return [rotate_point(x, y, cx, cy, g.rot) for x, y in pts]


def _coords(g) -> list[Point]:
    if g.is_empty or g.geom_type != "LineString":
        return []
    return [(float(x), float(y)) for x, y in g.coords]


def _merge(ds: list[float], tol: float) -> list[float]:
    out: list[float] = []
    for d in sorted(ds):
        if not out or d - out[-1] > tol:
            out.append(d)
    return out


@dataclass
class TrimPick:
    """Ergebnis von :meth:`TrimIndex.pick`: welches Stück fiele weg und was bliebe."""
    shape: Shape
    ring: int
    removed: list[Point]                 # das entfernte Stück (für Vorschau / Länge)
    remove: list[str] = field(default_factory=list)
    add: list[Shape] = field(default_factory=list)
    reason: str = ""                     # gesetzt = nicht trimmbar (Hinweistext)

    @property
    def ok(self) -> bool:
        return not self.reason

    @property
    def length_mm(self) -> float:
        return LineString(self.removed).length if len(self.removed) >= 2 else 0.0


@dataclass
class TrimSweep:
    """Ergebnis von :meth:`TrimIndex.sweep`: alle Stücke, die eine Zuglinie kreuzt."""
    fence: list[Point]
    pieces: list[list[Point]] = field(default_factory=list)            # entfernte Stücke
    replace: list[tuple[str, list[Shape]]] = field(default_factory=list)  # (ID, Ersatz) je Form
    skipped: int = 0                     # gekreuzte Umrisse ohne Kreuzung mit anderen Formen

    @property
    def ok(self) -> bool:
        return bool(self.pieces)

    @property
    def length_mm(self) -> float:
        return sum(LineString(p).length for p in self.pieces if len(p) >= 2)


class TrimIndex:
    """Räumlicher Index aller Umrisse für das Trimmwerkzeug.

    ``shapes``: alle Formen sichtbarer Ebenen (sie schneiden); ``editable``: IDs der
    Formen, deren Stücke entfernt werden dürfen (sichtbar, nicht gesperrt)."""

    def __init__(self, shapes: Iterable[Shape], editable: Iterable[str] | None = None) -> None:
        self.shapes = [s for s in shapes if s.kind != "image"]
        ok = None if editable is None else set(editable)
        self.rings: dict[str, list[tuple[list[Point], bool]]] = {}
        self.lines: list[LineString] = []
        self.owner: list[tuple[str, int]] = []
        self.targets: set[str] = set()
        for s in self.shapes:
            rings = shape_rings(s)
            self.rings[s.id] = rings
            if can_trim(s) and (ok is None or s.id in ok):
                self.targets.add(s.id)
            for k, (pts, _closed) in enumerate(rings):
                self.lines.append(LineString(pts))
                self.owner.append((s.id, k))
        self.by_id = {s.id: s for s in self.shapes}
        self.tree = STRtree(self.lines) if self.lines else None

    def _nearest(self, p: SPoint, tol: float) -> int | None:
        if self.tree is None:
            return None
        best, best_d = None, None
        order = {s.id: i for i, s in enumerate(self.shapes)}
        for j in self.tree.query(p.buffer(tol)):
            sid, _k = self.owner[j]
            if sid not in self.targets:
                continue
            d = self.lines[j].distance(p)
            if d > tol:
                continue
            # Nächster Umriss; bei Gleichstand die oberste Form.
            key = (round(d, 6), -order[sid])
            if best_d is None or key < best_d:
                best, best_d = j, key
        return best

    def _bounds(self, j: int) -> tuple[list[float], str]:
        """Grenzen der Stücke entlang Umriss ``j`` (Abstände ab Linienstart).

        Offen: ``[0, Kreuzungen…, Länge]`` – Stück ``i`` reicht von ``b[i]`` bis
        ``b[i + 1]``. Geschlossen: die Kreuzungen ``c`` (mindestens zwei) – Stück
        ``i`` reicht von ``c[i]`` bis ``c[i + 1]``, das letzte über den Ringstart
        bis ``c[0]``. Zweiter Wert: Hinweistext, wenn nichts zu trimmen ist."""
        line = self.lines[j]
        closed = self.rings[self.owner[j][0]][self.owner[j][1]][1]
        total = line.length
        near = [i for i in self.tree.query(line.buffer(JOIN_TOLERANCE_MM)) if i != j]
        cutters = unary_union([self.lines[i] for i in near]) if near else None
        cuts = [] if cutters is None or cutters.is_empty else _cut_distances(line, cutters)
        tol_c = JOIN_TOLERANCE_MM
        if closed:
            cuts = _merge([d % total if total - d > tol_c else 0.0 for d in cuts], tol_c)
            if len(cuts) >= 2 and total - cuts[-1] <= tol_c and cuts[0] <= tol_c:
                cuts.pop()
            if len(cuts) < 2:
                return [], "die Kontur kreuzt keine andere Form zweimal – Entf löscht das ganze Objekt"
            return cuts, ""
        inner = _merge([d for d in cuts if tol_c < d < total - tol_c], tol_c)
        if not inner:
            return [], "das Stück kreuzt keine andere Form – Entf löscht das ganze Objekt"
        return [0.0, *inner, total], ""

    def _piece_at(self, j: int, bounds: list[float], t: float) -> int:
        """Nummer des Stücks von Umriss ``j``, in dem der Abstand ``t`` liegt."""
        if self.rings[self.owner[j][0]][self.owner[j][1]][1]:
            if t < bounds[0] or t >= bounds[-1]:
                return len(bounds) - 1
            return max(n for n, c in enumerate(bounds) if c <= t)
        return max(n for n in range(len(bounds) - 1) if bounds[n] <= t)

    def _split(self, j: int, bounds: list[float], gone: set[int]) -> tuple[list[list[Point]], list[list[Point]]]:
        """(entfernte Stücke, verbleibende Stücke) von Umriss ``j`` ohne die Stücke ``gone``.

        Benachbarte Stücke gleicher Art werden zu einem Linienzug zusammengefasst."""
        line = self.lines[j]
        total = line.length
        closed = self.rings[self.owner[j][0]][self.owner[j][1]][1]

        def run(a: float, b: float) -> list[Point]:
            if a < b:
                return _coords(substring(line, a, b))
            return _coords(substring(line, a, total)) + _coords(substring(line, 0.0, b))[1:]

        removed: list[list[Point]] = []
        rest: list[list[Point]] = []
        if closed:
            n = len(bounds)
            if len(gone) >= n:
                return [run(bounds[0], bounds[0])], []
            # Beginn am ersten bleibenden Stück hinter einem entfernten – so hängen
            # benachbarte Stücke auch über den Ringstart hinweg zusammen.
            first = min(k for k in gone if (k + 1) % n not in gone)
            order = [(first + 1 + m) % n for m in range(n)]
            m = 0
            while m < n:
                k = order[m]
                is_gone = k in gone
                e = m
                while e + 1 < n and (order[e + 1] in gone) == is_gone:
                    e += 1
                a, b = bounds[k], bounds[(order[e] + 1) % n]
                (removed if is_gone else rest).append(run(a, b))
                m = e + 1
        else:
            n = len(bounds) - 1
            m = 0
            while m < n:
                is_gone = m in gone
                e = m
                while e + 1 < n and ((e + 1) in gone) == is_gone:
                    e += 1
                a, b = bounds[m], bounds[e + 1]
                if is_gone:
                    removed.append(run(a, b))
                elif b - a > _MIN_REST_MM:
                    rest.append(run(a, b))
                m = e + 1
        rest = [r for r in rest if len(r) >= 2 and LineString(r).length > _MIN_REST_MM]
        return [r for r in removed if len(r) >= 2], rest

    def pick(self, point: Point, tol: float) -> TrimPick | None:
        """Stück unter ``point`` (Fangabstand ``tol`` mm) oder ``None``."""
        p = SPoint(point)
        j = self._nearest(p, tol)
        if j is None:
            return None
        sid, k = self.owner[j]
        shape = self.by_id[sid]
        pts, _closed = self.rings[sid][k]
        bounds, reason = self._bounds(j)
        if reason:
            return TrimPick(shape, k, pts, reason=reason)
        removed, rest = self._split(j, bounds, {self._piece_at(j, bounds, self.lines[j].project(p))})
        pick = TrimPick(shape, k, removed[0] if removed else [])
        pick.remove = [sid]
        pick.add = self._rebuild(shape, {k: rest})
        return pick

    def sweep(self, a: Point, b: Point) -> TrimSweep:
        """Alle Stücke, die die Strecke ``a``–``b`` kreuzt (Ziehen über mehrere Stücke).

        Die Stücke werden gegen den Zustand *vor* dem Zug bestimmt – genau das, was
        die Vorschau zeigt –, je Form entsteht ein Ersatz (ein Undo-Schritt für alle)."""
        out = TrimSweep([tuple(map(float, a)), tuple(map(float, b))])
        if self.tree is None or math.dist(a, b) < 1e-6:
            return out
        fence = LineString([a, b])
        hits: dict[str, dict[int, set[int]]] = {}
        bounds_of: dict[int, list[float]] = {}
        for j in sorted(int(i) for i in self.tree.query(fence)):
            sid, k = self.owner[j]
            if sid not in self.targets:
                continue
            ts = [self.lines[j].project(q) for q in _hit_points(fence.intersection(self.lines[j]))]
            if not ts:
                continue
            bounds, reason = self._bounds(j)
            if reason:
                out.skipped += 1
                continue
            bounds_of[j] = bounds
            hits.setdefault(sid, {}).setdefault(j, set()).update(self._piece_at(j, bounds, t) for t in ts)
        order = {s.id: i for i, s in enumerate(self.shapes)}
        for sid in sorted(hits, key=order.__getitem__):
            shape = self.by_id[sid]
            rests: dict[int, list[list[Point]]] = {}
            for j, gone in hits[sid].items():
                removed, rest = self._split(j, bounds_of[j], gone)
                out.pieces.extend(removed)
                rests[self.owner[j][1]] = rest
            out.replace.append((sid, self._rebuild(shape, rests)))
        return out

    def _rebuild(self, shape: Shape, rests: dict[int, list[list[Point]]]) -> list[Shape]:
        rings = self.rings[shape.id]
        open_parts: list[list[Point]] = []
        closed_parts: list[list[Point]] = []
        for n, (pts, closed) in enumerate(rings):
            if n in rests:
                open_parts.extend(rests[n])
            elif closed and shape.kind == "polygon":
                closed_parts.append(pts[:-1] if len(pts) > 3 else pts)
            else:
                open_parts.append(pts)
        out: list[Shape] = []
        for kind, parts in (("polygon", closed_parts), ("path", open_parts)):
            parts = [p for p in parts if len(p) >= POINT_KINDS_MIN[kind]]
            if not parts:
                continue
            pts: list[Point] = []
            starts: list[int] = []
            for p in parts:
                if pts:
                    starts.append(len(pts))
                pts.extend(p)
            s = Shape.from_points(kind, pts, shape.layer_id, rings=starts)
            s.groups = tuple(shape.groups)
            s.priority = shape.priority
            s.reverse = shape.reverse
            out.append(s)
        return out


def _hit_points(g) -> list[SPoint]:
    """Kreuzungspunkte der Zuglinie mit einem Umriss (bei Überdeckung die Mitte)."""
    if g.is_empty:
        return []
    if g.geom_type == "Point":
        return [g]
    if g.geom_type in ("LineString", "LinearRing"):
        return [g.interpolate(0.5, normalized=True)]
    if hasattr(g, "geoms"):
        return [q for part in g.geoms for q in _hit_points(part)]
    return []


POINT_KINDS_MIN = {"polygon": 3, "path": 2}
