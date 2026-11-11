"""Zerlegen und Kombinieren (LightBurn *Break Apart* / *Combine*), Qt-frei bis auf
Kreise/Text.

Importierte SVG/PDF/DXF-Logos, „Text in Pfade“, Nachzeichnungen und Boole-Ergebnisse
sind oft *ein* Objekt mit vielen Teilpfaden (Ringen). Einzelne Teile lassen sich
dann weder verschieben noch löschen, auf eine andere Ebene legen oder eigens
anordnen. Umgekehrt sollen mehrere Konturen manchmal *ein* Objekt werden (ein
Ausschnitt als Loch in einer Platte, ohne die Konturen zu verschmelzen).

* :func:`break_apart` – Polygone und Pfade mit mehreren Ringen werden in einzelne
  Objekte zerlegt. Standard ``keep_holes=True``: Löcher bleiben bei ihrer
  Außenkontur (Verschachtelung nach der Gerade-Ungerade-Regel, wie die Füllung sie
  sieht – das „O“ bleibt ein Ring mit Loch, Inseln in Löchern werden eigene
  Teile), damit Füllung, Kerf und „innen zuerst“ unverändert bleiben. Mit
  ``keep_holes=False`` wird jeder Teilpfad ein eigenes Objekt (wie LightBurn).
  Offene Pfade zerfallen immer in ihre Teilpfade.
* :func:`combine` – ausgewählte Objekte derselben Ebene werden zu einem Objekt mit
  mehreren Ringen zusammengefasst: geschlossene (Rechteck, Ellipse, Polygon, Text)
  zu einem Polygon, offene (Pfad, Linie) zu einem Pfad. Die Konturen bleiben, wie
  sie sind (anders als „Vereinigen“); überlappende Flächen werden nach der
  Gerade-Ungerade-Regel zu Löchern – :class:`CombineResult` zählt sie, damit der
  Hinweis auf „Vereinigen“ zeigen kann.

Drehung bleibt erhalten (Teile behalten den Winkel des Objekts; beim Kombinieren
gleich gedrehter Objekte deren Winkel, sonst 0°), Kurvensegmente der
Knotenbearbeitung ebenfalls (Catmull-Rom ist affin invariant). Ebene und Gruppen
bleiben; erzeugte Objekte (Codes) und Bilder werden nie verändert.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from .model import FILLABLE_KINDS, Shape, rotate_point
from .pathjoin import _common_groups, nest_rings

Point = tuple[float, float]

SPLIT_KINDS = ("polygon", "path")
COMBINE_KINDS = ("rect", "ellipse", "polygon", "text", "path", "line")


def can_break(shape: Shape) -> bool:
    """Objekt mit mehr als einem Teilpfad, das zerlegt werden darf."""
    return shape.kind in SPLIT_KINDS and not shape.generator and len(shape.ring_ranges()) > 1


def can_combine(shape: Shape) -> bool:
    return shape.kind in COMBINE_KINDS and not shape.generator


def is_closed_kind(shape: Shape) -> bool:
    return shape.kind in FILLABLE_KINDS


def _world(pts: Iterable[Point], rot: float, center: Point) -> list[Point]:
    if not rot:
        return [(float(x), float(y)) for x, y in pts]
    cx, cy = center
    return [rotate_point(x, y, cx, cy, rot) for x, y in pts]


def shape_from_world(kind: str, pts: list[Point], layer_id: str, rings=(), curves=(),
                     rot: float = 0.0, groups: tuple[str, ...] = ()) -> Shape:
    """Objekt aus Punkten in Arbeitsflächen-mm, das mit Winkel ``rot`` genau diese
    Punkte zeigt: Punkte um die Mitte ihrer Box zurückdrehen, Objekt anlegen und
    die Boxmitte so verschieben, dass die Drehung um die *neue* Mitte wieder auf
    die Weltpunkte führt."""
    rot = float(rot or 0.0)
    if rot:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        c = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        local = [rotate_point(x, y, c[0], c[1], -rot) for x, y in pts]
    else:
        local = pts
    s = Shape.from_points(kind, local, layer_id, rings=rings, curves=curves)
    if rot:
        mx, my = s.geom.center()
        s.geom = s.geom.with_center(*rotate_point(mx, my, c[0], c[1], rot))
        s.geom.rot = rot
    s.groups = tuple(groups)
    return s


# ---------------------------------------------------------------- Zerlegen
@dataclass
class BreakResult:
    pairs: list[tuple[str, list[Shape]]] = field(default_factory=list)   # (alte ID, Teile)
    skipped: int = 0         # Objekte mit nur einem Teil (bzw. Teil mit Löchern)

    @property
    def remove(self) -> list[str]:
        return [old for old, _new in self.pairs]

    @property
    def add(self) -> list[Shape]:
        return [s for _old, new in self.pairs for s in new]

    @property
    def changed(self) -> bool:
        return bool(self.pairs)

    def summary(self) -> str:
        if not self.pairs:
            return "Zerlegen: nichts zu zerlegen – jedes Objekt besteht aus einem Teil"
        text = f"Zerlegen: {len(self.pairs)} Objekt(e) → {len(self.add)} Teil(e)"
        if self.skipped:
            text += f" · {self.skipped} Objekt(e) bestehen aus einem Teil"
        return text


def _rings_with_curves(shape: Shape) -> list[tuple[list[Point], list[int]]]:
    """(Punkte im ungedrehten Rahmen, Kurven-Indizes relativ zum Ring) je Ring."""
    pts = shape.abs_points()
    curves = set(shape.curves)
    return [(pts[a:b], [i - a for i in range(a, b) if i in curves]) for a, b in shape.ring_ranges()]


def _assemble(rings: list[tuple[list[Point], list[int]]]):
    pts: list[Point] = []
    starts: list[int] = []
    curves: list[int] = []
    for ring, cv in rings:
        if pts:
            starts.append(len(pts))
        curves += [len(pts) + k for k in cv]
        pts.extend(ring)
    return pts, starts, curves


def _nesting_rings(shape: Shape) -> list[list[Point]]:
    """Ringe für die Verschachtelung – mit Kurven abgeflacht (gleiche Reihenfolge)."""
    if shape.curves:
        from .shape_paths import local_path
        poly = [[(p.x(), p.y()) for p in sub] for sub in local_path(shape).toSubpathPolygons()]
        if len(poly) == len(shape.ring_ranges()):
            return [p[:-1] if len(p) > 3 and p[0] == p[-1] else p for p in poly]
    return [r for r, _c in _rings_with_curves(shape)]


def break_shape(shape: Shape, keep_holes: bool = True) -> list[Shape] | None:
    """Teile eines Objekts oder ``None``, wenn es nur aus einem Teil besteht."""
    if not can_break(shape):
        return None
    rings = _rings_with_curves(shape)
    if shape.kind == "polygon" and keep_holes:
        groups = nest_rings(_nesting_rings(shape))
    else:
        groups = [[i] for i in range(len(rings))]
    if len(groups) < 2:
        return None
    g = shape.geom
    center = g.center()
    out = []
    for grp in groups:
        sub = [rings[i] for i in grp]
        pts, starts, curves = _assemble(sub)
        if len(pts) < (3 if shape.kind == "polygon" else 2):
            continue
        out.append(shape_from_world(shape.kind, _world(pts, g.rot, center), shape.layer_id,
                                    starts, curves, g.rot, shape.groups))
    return out if len(out) >= 2 else None


def break_apart(shapes: Iterable[Shape], keep_holes: bool = True) -> BreakResult:
    """Alle zerlegbaren Objekte aus ``shapes`` zerlegen (siehe Moduldoku)."""
    res = BreakResult()
    for s in shapes:
        if s.kind not in SPLIT_KINDS or s.generator:
            continue
        parts = break_shape(s, keep_holes)
        if parts is None:
            res.skipped += 1
        else:
            res.pairs.append((s.id, parts))
    return res


def break_preview(shapes: Iterable[Shape]) -> tuple[int, int]:
    """(Teile mit Löchern zusammen, jeder Teilpfad einzeln) – für den Dialog."""
    shapes = list(shapes)
    return len(break_apart(shapes, True).add), len(break_apart(shapes, False).add)


# ---------------------------------------------------------------- Kombinieren
@dataclass
class CombineResult:
    groups: list[tuple[list[str], Shape]] = field(default_factory=list)   # (alte IDs, neues Objekt)
    skipped: int = 0          # Objekte ohne Partner (allein auf ihrer Ebene / Art)
    overlaps: int = 0         # sich kreuzende geschlossene Konturen (werden Löcher)
    text_converted: int = 0   # Texte, die dafür in Pfade umgewandelt wurden

    @property
    def remove(self) -> list[str]:
        return [i for ids, _s in self.groups for i in ids]

    @property
    def add(self) -> list[Shape]:
        return [s for _ids, s in self.groups]

    @property
    def changed(self) -> bool:
        return bool(self.groups)

    def summary(self) -> str:
        if not self.groups:
            return ("Kombinieren: nichts zu kombinieren – mindestens zwei Objekte derselben Ebene "
                    "(geschlossen oder offen) auswählen")
        text = f"Kombinieren: {len(self.remove)} Objekt(e) → {len(self.groups)} Objekt(e)"
        if self.text_converted:
            text += f" · {self.text_converted} Text(e) in Pfade umgewandelt"
        if self.skipped:
            text += f" · {self.skipped} ohne Partner übrig"
        if self.overlaps:
            text += (f" · Achtung: {self.overlaps} Überlappung(en) – überlappende Flächen werden "
                     "Löcher (Gerade-Ungerade); zum Verschmelzen „Vereinigen“ (Strg+Alt+U)")
        return text


def _world_rings(shape: Shape) -> tuple[list[tuple[list[Point], list[int]]], bool]:
    """(Ringe in Arbeitsflächen-mm mit Kurven, Text umgewandelt?)."""
    g = shape.geom
    if shape.kind == "line":
        return [(_world([(g.x, g.y), (g.x + g.w, g.y + g.h)], g.rot, g.center()), [])], False
    if shape.kind == "rect":
        pts = [(g.x, g.y), (g.x + g.w, g.y), (g.x + g.w, g.y + g.h), (g.x, g.y + g.h)]
        return [(_world(pts, g.rot, g.center()), [])], False
    if shape.kind == "ellipse":
        from .shape_paths import ellipse_polygon
        return [(ellipse_polygon(g)[:-1], [])], False
    if shape.kind == "text":
        from .pathops import text_to_outline
        out = text_to_outline(shape)
        return (_world_rings(out)[0] if out is not None else []), True
    center = g.center()
    return [(_world(r, g.rot, center), cv) for r, cv in _rings_with_curves(shape)], False


def _overlaps(rings: list[list[Point]], owners: list[int]) -> int:
    """Paare sich kreuzender Ringe verschiedener Quellobjekte (Ränder schneiden sich)."""
    from shapely.geometry import LineString
    from shapely.strtree import STRtree
    lines = [LineString(r + r[:1]) for r in rings if len(r) >= 3]
    own = [o for r, o in zip(rings, owners) if len(r) >= 3]
    if len(lines) < 2:
        return 0
    tree = STRtree(lines)
    pairs = set()
    for i, ln in enumerate(lines):
        for j in tree.query(ln):
            j = int(j)
            if j > i and own[i] != own[j] and ln.intersects(lines[j]):
                pairs.add((own[i], own[j]))
    return len(pairs)


def combine(shapes: Iterable[Shape]) -> CombineResult:
    """Objekte je Ebene und Art (geschlossen / offen) zu je einem Objekt kombinieren.
    ``shapes`` in Dokumentreihenfolge; Ringreihenfolge = Dokumentreihenfolge."""
    res = CombineResult()
    buckets: dict[tuple[str, bool], list[Shape]] = {}
    for s in shapes:
        if can_combine(s):
            buckets.setdefault((s.layer_id, is_closed_kind(s)), []).append(s)
    for (layer_id, closed), members in buckets.items():
        if len(members) < 2:
            res.skipped += len(members)
            continue
        rings: list[tuple[list[Point], list[int]]] = []
        owners: list[int] = []
        texts = 0
        for k, s in enumerate(members):
            rs, conv = _world_rings(s)
            texts += conv
            for r, cv in rs:
                if len(r) >= (3 if closed else 2):
                    rings.append((r, cv))
                    owners.append(k)
        if len({o for o in owners}) < 2:
            res.skipped += len(members)
            continue
        rots = {round(s.geom.rot or 0.0, 9) for s in members}
        rot = members[0].geom.rot if len(rots) == 1 else 0.0
        pts, starts, curves = _assemble(rings)
        new = shape_from_world("polygon" if closed else "path", pts, layer_id, starts, curves, rot,
                               _common_groups(members))
        res.groups.append(([s.id for s in members], new))
        res.text_converted += texts
        if closed:
            res.overlaps += _overlaps([r for r, _c in rings], owners)
    return res
