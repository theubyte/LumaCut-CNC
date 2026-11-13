"""Pfade aufräumen: verbinden, schließen, Duplikate löschen (Qt-frei bis auf Kurven).

Wie LightBurn *Auto-Join Selected Shapes* (Alt+J), *Close Selected Paths With
Tolerance* und *Delete Duplicates*: DXF/SVG aus CAD-Programmen kommen oft als
lose Einzelstrecken („Segmentsuppe“) oder als fast geschlossene Pfade mit einer
winzigen Lücke an. Solche offenen Pfade werden nicht gefüllt (Schraffur braucht
geschlossene Formen), bekommen keinen Kerf-Versatz, keine Haltestege und keine
An-/Abfahrt, und die Schnittreihenfolge „innen zuerst“ erkennt sie nicht als
Löcher – ein Teil fällt dann womöglich vor seinen Ausschnitten heraus. Doppelt
übereinander liegende Konturen werden doppelt gelasert (Brandränder, auf einem
Diodenlaser die häufigste Ursache für verkohlte Kanten nach einem DXF-Import).

* :func:`auto_join` – offene Pfade/Linien einer Ebene, deren Endpunkte höchstens
  ``tolerance_mm`` (Standard 0,05 mm wie LightBurn) auseinander liegen, werden zu
  Ketten verbunden. Eine Kette, deren Enden sich treffen, wird ein geschlossenes
  Polygon; ineinander liegende geschlossene Ketten werden zu *einem* Polygon mit
  Löchern zusammengefasst (Gerade-Ungerade-Regel wie „Text in Pfade“), damit die
  Füllung das Loch frei lässt. Verschiedene Ebenen werden nie verbunden.
* :func:`close_paths` – einzelne offene Pfade, deren Anfang und Ende höchstens
  ``tolerance_mm`` auseinander liegen, werden geschlossen: ``"move"`` führt die
  Enden in ihrer Mitte zusammen, ``"line"`` ergänzt eine Verbindungsstrecke.
  Kurvensegmente der Knotenbearbeitung bleiben erhalten.
* :func:`find_duplicates` – Objekte derselben Ebene mit gleicher Kontur (auf
  0,01 mm, unabhängig von Startpunkt, Richtung und Objektart – ein Rechteck und
  ein gleich großes Polygon sind gleich). Das unterste bleibt, die anderen
  werden gelöscht. Bilder und Teile erzeugter Objekte (QR-Code …) bleiben.

Erzeugte Objekte (``generator``) und Bilder werden nie verändert.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from .model import FILLABLE_KINDS, Shape, rotate_point

Point = tuple[float, float]

JOIN_TOLERANCE_MM = 0.05          # LightBurn Auto-Join
CLOSE_TOLERANCE_MM = 0.5          # LightBurn „Close Path“
CLOSE_TOLERANCE_RANGE = (0.01, 20.0)
CLOSE_MODES = ("move", "line")
CLOSE_MODE_LABELS = {"move": "Enden zusammenführen", "line": "Mit Linie verbinden"}
DUPLICATE_GRID_MM = 0.01
OPEN_KINDS = ("path", "line")
_EPS = 1e-9


def is_open(shape: Shape) -> bool:
    """Offene Form (Pfad oder Linie), die das Aufräumen verändern darf."""
    return shape.kind in OPEN_KINDS and not shape.generator


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _dedupe(pts: Iterable[Point]) -> list[Point]:
    out: list[Point] = []
    for p in pts:
        p = (float(p[0]), float(p[1]))
        if not out or _dist(p, out[-1]) > _EPS:
            out.append(p)
    return out


def _world(shape: Shape, pts: Iterable[Point]) -> list[Point]:
    g = shape.geom
    if not g.rot:
        return [(float(x), float(y)) for x, y in pts]
    cx, cy = g.center()
    return [rotate_point(x, y, cx, cy, g.rot) for x, y in pts]


def open_pieces(shape: Shape) -> list[list[Point]]:
    """Teilpfade einer offenen Form in Arbeitsflächen-mm (inkl. Drehung).

    Gerade Pfade liefern genau ihre Stützpunkte; Pfade mit Kurvensegmenten werden
    wie im G-Code abgeflacht (Sehnenfehler ≤ 0,02 mm)."""
    if shape.kind == "line":
        g = shape.geom
        return [_dedupe(_world(shape, [(g.x, g.y), (g.x + g.w, g.y + g.h)]))]
    if shape.kind != "path":
        return []
    if shape.curves:
        from .shape_paths import shape_polygons   # Qt nur für Kurven
        return [_dedupe(p) for p in shape_polygons(shape)]
    pts = shape.abs_points()
    return [_dedupe(_world(shape, pts[a:b])) for a, b in shape.ring_ranges()]


def _common_groups(shapes: Iterable[Shape]) -> tuple[str, ...]:
    groups: tuple[str, ...] | None = None
    for s in shapes:
        if groups is None:
            groups = tuple(s.groups)
            continue
        n = 0
        while n < len(groups) and n < len(s.groups) and groups[n] == s.groups[n]:
            n += 1
        groups = groups[:n]
    return groups or ()


# ---------------------------------------------------------------- Verbinden
@dataclass
class JoinResult:
    remove: list[str] = field(default_factory=list)     # IDs der verbrauchten Formen
    add: list[Shape] = field(default_factory=list)      # neue Formen (Dokumentreihenfolge)
    pieces: int = 0          # verbundene Teilstücke (Ein-Stück-Ketten nicht mitgezählt)
    closed: int = 0          # entstandene geschlossene Konturen
    open_chains: int = 0     # verbundene, aber offen gebliebene Ketten
    open_left: int = 0       # offene Formen der Auswahl, die offen bleiben

    @property
    def changed(self) -> bool:
        return bool(self.remove)

    def summary(self) -> str:
        if not self.changed:
            return ("Pfade verbinden: nichts zu verbinden – keine Endpunkte näher als "
                    f"{JOIN_TOLERANCE_MM:g} mm")
        parts = []
        if self.closed:
            parts.append(f"{self.closed} geschlossene Kontur(en)")
        if self.open_chains:
            parts.append(f"{self.open_chains} offene(r) Pfad(e)")
        text = f"Pfade verbinden: {len(self.remove)} Form(en) → " + ", ".join(parts)
        if self.open_left:
            text += f" · {self.open_left} offene Form(en) übrig"
        return text


class _EndIndex:
    """Endpunkte im Raster der Toleranz – Nachbarsuche in O(1)."""

    def __init__(self, cell: float) -> None:
        self.cell = max(cell, 1e-6)
        self.cells: dict[tuple[int, int], list[tuple[int, int]]] = {}

    def _key(self, p: Point) -> tuple[int, int]:
        return (math.floor(p[0] / self.cell), math.floor(p[1] / self.cell))

    def add(self, p: Point, item: tuple[int, int]) -> None:
        self.cells.setdefault(self._key(p), []).append(item)

    def near(self, p: Point):
        kx, ky = self._key(p)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                yield from self.cells.get((kx + dx, ky + dy), ())


def _chains(pieces: list[list[Point]], tol: float) -> list[tuple[list[int], list[Point], bool]]:
    """Gierige Verkettung: (Stück-Indizes, Punkte, geschlossen) je Kette."""
    index = _EndIndex(tol)
    for i, p in enumerate(pieces):
        index.add(p[0], (i, 0))
        index.add(p[-1], (i, 1))
    used = [False] * len(pieces)

    def nearest(pt: Point) -> tuple[float, int, int] | None:
        best = None
        for i, end in index.near(pt):
            if used[i]:
                continue
            d = _dist(pt, pieces[i][-1 if end else 0])
            if d <= tol and (best is None or d < best[0]):
                best = (d, i, end)
        return best

    out = []
    for start in range(len(pieces)):
        if used[start]:
            continue
        used[start] = True
        members = [start]
        chain = list(pieces[start])
        closed = False
        for grow_at_end in (True, False):
            while True:
                tip = chain[-1] if grow_at_end else chain[0]
                other = chain[0] if grow_at_end else chain[-1]
                ring_gap = _dist(tip, other) if len(chain) >= 3 else None
                cand = nearest(tip)
                if ring_gap is not None and ring_gap <= tol and (cand is None or ring_gap <= cand[0]):
                    closed = True
                    break
                if cand is None:
                    break
                _, i, end = cand
                used[i] = True
                members.append(i)
                q = pieces[i]
                if grow_at_end:
                    q = q if end == 0 else q[::-1]       # Anschluss am Kettenende
                    chain.extend(q[1:])
                else:
                    q = q if end == 1 else q[::-1]       # Anschluss am Kettenanfang
                    chain[:0] = q[:-1]
            if closed:
                break
        if closed:
            gap = _dist(chain[0], chain[-1])
            if gap > _EPS:       # Enden in der Mitte zusammenführen
                chain[0] = ((chain[0][0] + chain[-1][0]) / 2, (chain[0][1] + chain[-1][1]) / 2)
            chain.pop()
            chain = _dedupe(chain)
            if len(chain) < 3:
                closed = False
        out.append((members, chain, closed))
    return out


def _signed_area(ring: list[Point]) -> float:
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))


def _inside(pt: Point, ring: list[Point]) -> bool:
    x, y = pt
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def nest_rings(rings: list[list[Point]]) -> list[list[int]]:
    """Ringe nach Verschachtelung gruppieren: je Gruppe [Außenring, Löcher …].

    Gerade Tiefe = Außenkontur, ungerade = Loch ihres direkten Elternrings;
    Inseln in Löchern werden eigene Gruppen (wie die Füllung sie sieht)."""
    n = len(rings)
    areas = [abs(_signed_area(r)) for r in rings]
    # Test-Punkt: Mitte der ersten Kante (liegt nie auf einer Ecke einer anderen Kontur)
    probes = [((r[0][0] + r[1][0]) / 2, (r[0][1] + r[1][1]) / 2) for r in rings]
    boxes = [(min(x for x, _ in r), min(y for _, y in r), max(x for x, _ in r), max(y for _, y in r))
             for r in rings]
    parents: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        px, py = probes[i]
        for j in range(n):
            b = boxes[j]
            if i == j or areas[j] <= areas[i] or not (b[0] <= px <= b[2] and b[1] <= py <= b[3]):
                continue
            if _inside(probes[i], rings[j]):
                parents[i].append(j)
    depth = [len(p) for p in parents]
    groups: dict[int, list[int]] = {}
    order = sorted(range(n), key=lambda i: depth[i])
    for i in order:
        if depth[i] % 2 == 0:
            groups[i] = [i]
    for i in order:
        if depth[i] % 2 == 1:
            direct = min(parents[i], key=lambda j: areas[j])
            groups.setdefault(direct, [direct]).append(i)
    return [groups[k] for k in sorted(groups, key=lambda k: min(groups[k]))]


def _polygon(rings: list[list[Point]], layer_id: str, groups: tuple[str, ...]) -> Shape:
    pts: list[Point] = []
    starts: list[int] = []
    for r in rings:
        if pts:
            starts.append(len(pts))
        pts.extend(r)
    s = Shape.from_points("polygon", pts, layer_id, rings=starts)
    s.groups = groups
    return s


def _path(chain: list[Point], layer_id: str, groups: tuple[str, ...]) -> Shape:
    s = Shape.from_points("path", chain, layer_id)
    s.groups = groups
    return s


def auto_join(shapes: Iterable[Shape], tolerance_mm: float = JOIN_TOLERANCE_MM) -> JoinResult:
    """Offene Formen verbinden (siehe Moduldoku). ``shapes`` in Dokumentreihenfolge;
    geschlossene Formen, Bilder und erzeugte Objekte werden übergangen."""
    tol = max(float(tolerance_mm), 1e-6)
    res = JoinResult()
    by_layer: dict[str, list[Shape]] = {}
    for s in shapes:
        if is_open(s):
            by_layer.setdefault(s.layer_id, []).append(s)
    for layer_id, layer_shapes in by_layer.items():
        pieces: list[list[Point]] = []
        owner: list[int] = []
        for k, s in enumerate(layer_shapes):
            for p in open_pieces(s):
                if len(p) >= 2:
                    pieces.append(p)
                    owner.append(k)
        chains = _chains(pieces, tol)
        changed = [len(m) > 1 or closed for m, _c, closed in chains]
        affected = {owner[i] for (m, _c, _cl), ch in zip(chains, changed) if ch for i in m}
        if not affected:
            res.open_left += len(layer_shapes)
            continue
        rings, ring_groups, opens = [], [], []
        for (members, chain, closed), ch in zip(chains, changed):
            srcs = {owner[i] for i in members}
            if not srcs & affected:
                continue
            groups = _common_groups(layer_shapes[k] for k in sorted(srcs))
            if closed:
                rings.append(chain)
                ring_groups.append(groups)
            else:
                opens.append((min(srcs), chain, groups, ch, len(members)))
            if ch:
                res.pieces += len(members) if len(members) > 1 else 0
        new: list[tuple[int, Shape]] = []
        for grp in nest_rings(rings):
            gs = [ring_groups[i] for i in grp]
            common = gs[0] if all(g == gs[0] for g in gs) else ()
            first = min(grp)
            new.append((first, _polygon([rings[i] for i in grp], layer_id, common)))
            res.closed += 1
        for first, chain, groups, ch, _n in opens:
            new.append((len(rings) + first, _path(chain, layer_id, groups)))
            if ch:
                res.open_chains += 1
        res.remove += [layer_shapes[k].id for k in sorted(affected)]
        res.add += [s for _k, s in sorted(new, key=lambda t: t[0])]
        res.open_left += sum(1 for _f, _c, _g, ch, _n in opens if not ch) + \
            sum(1 for k in range(len(layer_shapes)) if k not in affected)
    return res


def join_preview(shapes: Iterable[Shape], tolerance_mm: float = JOIN_TOLERANCE_MM) -> tuple[int, int]:
    """(offene Formen, davon verbindbar/schließbar) – für Hinweise nach dem Import."""
    shapes = list(shapes)
    n_open = sum(1 for s in shapes if is_open(s))
    if not n_open:
        return 0, 0
    res = auto_join(shapes, tolerance_mm)
    return n_open, len(res.remove)


# ---------------------------------------------------------------- Schließen
@dataclass
class CloseResult:
    remove: list[str] = field(default_factory=list)
    add: list[Shape] = field(default_factory=list)
    open_found: int = 0
    left_open: int = 0

    @property
    def closed(self) -> int:
        return len(self.add)

    def summary(self) -> str:
        return (f"Offene Formen: {self.open_found} · geschlossen: {self.closed} · "
                f"bleiben offen: {self.left_open}")


def _close_one(shape: Shape, tol: float, mode: str) -> Shape | None:
    if shape.kind != "path" or shape.generator:
        return None
    g = shape.geom
    pts = shape.abs_points()
    curves = set(shape.curves)
    new_pts: list[Point] = []
    new_rings: list[int] = []
    new_curves: list[int] = []
    for a, b in shape.ring_ranges():
        ring = pts[a:b]
        if len(ring) < 2 or _dist(ring[0], ring[-1]) > tol:
            return None
        keep = list(ring)
        idx = list(range(a, b))
        if mode == "move" or _dist(ring[0], ring[-1]) <= _EPS:
            keep[0] = ((ring[0][0] + ring[-1][0]) / 2, (ring[0][1] + ring[-1][1]) / 2)
            keep.pop()
            idx.pop()
        if len(_dedupe(keep)) < 3:
            return None
        if new_pts:
            new_rings.append(len(new_pts))
        base = len(new_pts)
        last_open = idx[-1] if mode == "line" else None   # neue Schließstrecke bleibt gerade
        new_curves += [base + k for k, i in enumerate(idx) if i in curves and i != last_open]
        new_pts.extend(keep)
    if g.rot:      # Kurven (Catmull-Rom) sind affin invariant: Punkte drehen genügt
        new_pts = _world(shape, new_pts)
    out = Shape.from_points("polygon", new_pts, shape.layer_id, rings=new_rings, curves=new_curves)
    out.groups = shape.groups
    out.priority = shape.priority   # Schnitt-Priorität („Nach Priorität“) bleibt
    return out


def close_paths(shapes: Iterable[Shape], tolerance_mm: float = CLOSE_TOLERANCE_MM,
                mode: str = "move") -> CloseResult:
    """Offene Pfade mit Endlücke ≤ ``tolerance_mm`` schließen (``mode`` „move“/„line“)."""
    if mode not in CLOSE_MODES:
        raise ValueError(f"Unbekannte Schließart: {mode}")
    tol = max(float(tolerance_mm), 0.0)
    res = CloseResult()
    for s in shapes:
        if not is_open(s):
            continue
        res.open_found += 1
        out = _close_one(s, tol, mode)
        if out is None:
            res.left_open += 1
            continue
        res.remove.append(s.id)
        res.add.append(out)
    return res


# ---------------------------------------------------------------- Duplikate
def _canon_ring(ring: list[Point], closed: bool) -> tuple:
    q = DUPLICATE_GRID_MM
    r = [(round(x / q), round(y / q)) for x, y in ring]
    r = [p for i, p in enumerate(r) if i == 0 or p != r[i - 1]]
    if closed:
        if len(r) > 1 and r[0] == r[-1]:
            r.pop()
        if not r:
            return ()
        cands = []
        for seq in (r, r[::-1]):
            k = seq.index(min(seq))
            cands.append(tuple(seq[k:] + seq[:k]))
        return min(cands)
    return min(tuple(r), tuple(r[::-1]))


def duplicate_key(shape: Shape):
    """Vergleichsschlüssel (Ebene, geschlossen, Ringe) oder None (nicht vergleichbar)."""
    if shape.kind == "image" or shape.generator:
        return None
    closed = shape.kind in FILLABLE_KINDS
    if shape.kind in OPEN_KINDS and not shape.curves:
        rings = open_pieces(shape)
    else:
        from .shape_paths import shape_polygons
        rings = [_dedupe(p) for p in shape_polygons(shape)]
    canon = tuple(sorted(c for c in (_canon_ring(r, closed) for r in rings) if c))
    if not canon:
        return None
    return (shape.layer_id, closed, canon)


def find_duplicates(shapes: Iterable[Shape]) -> list[str]:
    """IDs der Doppelten (das jeweils erste Objekt in ``shapes`` bleibt)."""
    seen: set = set()
    dupes: list[str] = []
    for s in shapes:
        key = duplicate_key(s)
        if key is None:
            continue
        if key in seen:
            dupes.append(s.id)
        else:
            seen.add(key)
    return dupes
