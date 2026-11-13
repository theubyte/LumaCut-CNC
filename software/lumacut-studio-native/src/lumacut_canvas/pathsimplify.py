"""Pfade vereinfachen: Knoten reduzieren (Qt-frei bis auf „Kurven in Linien“).

Wie LightBurn *Optimize Selected Shapes* (Teil „Reduce nodes“ / „Fit to lines“):
importierte SVG/DXF/PDF-Kurven, Nachzeichnungen und Freihandstriche bestehen oft
aus Tausenden winziger Strecken. Jeder Knoten wird im G-Code ein eigenes ``G1``;
auf dem Pi/SKR bremst der Planer an jeder Mini-Strecke, die Dateien werden
groß, und die Knotenbearbeitung wird unhandlich. Die Vereinfachung entfernt
Knoten, die höchstens ``tolerance_mm`` von der verbleibenden Kontur abweichen
(Ramer-Douglas-Peucker, :func:`model.simplify_polyline`).

* Offene Pfade behalten Anfangs- und Endpunkt, geschlossene Ringe (Polygone,
  Löcher) bleiben geschlossen – der Ring wird an seinem Startpunkt und dem dazu
  entferntesten Punkt geteilt, beide Hälften vereinfacht, danach fällt auch der
  Startpunkt weg, wenn er auf einer Geraden liegt. Ein Ring, der unter drei
  Punkte schrumpfen würde, bleibt unverändert (kleine Löcher gehen nie verloren).
* Objektart (Polygon/Pfad), Ebene, Gruppen und Drehung bleiben; die Objektbox
  wird um die verbliebenen Punkte neu gelegt, ohne die Lage zu verändern.
* Pfade mit Kurvensegmenten der Knotenbearbeitung bleiben unverändert –
  außer mit ``fit_lines``: dann werden sie wie im G-Code abgeflacht (≤ 0,02 mm)
  und als gerade Strecken vereinfacht („Kurven in Linien umwandeln“). Bögen
  (G2/G3) sind keine Option – der Pi lehnt sie ab.
* Rechteck, Ellipse, Text, Linie, Bilder und erzeugte Objekte (Codes,
  Bogentext) werden nie verändert.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from .model import Geometry, Shape, rotate_point, simplify_polyline

Point = tuple[float, float]

SIMPLIFY_TOLERANCE_MM = 0.05            # unter der Strahlbreite eines Diodenlasers
SIMPLIFY_TOLERANCE_RANGE = (0.005, 5.0)
SIMPLIFY_KINDS = ("polygon", "path")
_EPS = 1e-9


def can_simplify(shape: Shape) -> bool:
    """Objekt mit Stützpunkten, das die Vereinfachung verändern darf."""
    return shape.kind in SIMPLIFY_KINDS and not shape.generator


def node_count(shape: Shape) -> int:
    return len(shape.points)


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _line_dist(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    seg = math.hypot(dx, dy)
    if seg < 1e-12:
        return _dist(p, a)
    return abs(dy * (p[0] - a[0]) - dx * (p[1] - a[1])) / seg


def simplify_ring(ring: list[Point], tolerance_mm: float) -> list[Point]:
    """Geschlossenen Ring (ohne wiederholten Startpunkt) vereinfachen.

    Liefert den Ring unverändert (bis auf doppelte Punkte), wenn weniger als drei
    Punkte übrig blieben."""
    pts = simplify_polyline(ring, 0.0)          # nur direkt doppelte Punkte entfernen
    while len(pts) > 1 and _dist(pts[0], pts[-1]) <= _EPS:
        pts.pop()
    if len(pts) <= 3 or tolerance_mm <= 0:
        return pts
    far = max(range(1, len(pts)), key=lambda k: _dist(pts[0], pts[k]))
    a = simplify_polyline(pts[:far + 1], tolerance_mm)
    b = simplify_polyline(pts[far:] + [pts[0]], tolerance_mm)
    out = a[:-1] + b[:-1]
    # Startpunkt selbst entbehrlich (liegt mitten auf einer Kante)?
    if len(out) > 3 and _line_dist(out[0], out[-1], out[1]) <= tolerance_mm:
        out = out[1:]
    return out if len(out) >= 3 else pts


def simplify_open(pts: list[Point], tolerance_mm: float) -> list[Point]:
    out = simplify_polyline(pts, tolerance_mm)
    return out if len(out) >= 2 else list(pts)


def _rebuild(shape: Shape, local: list[Point], rings: list[int], kind: str | None = None,
             rot: float | None = None, center: Point | None = None) -> Shape:
    """Neue Form aus Punkten im ungedrehten Objektrahmen; Drehung und Lage bleiben."""
    kind = kind or shape.kind
    out = Shape.from_points(kind, local, shape.layer_id, rings=rings)
    rot = shape.geom.rot if rot is None else rot
    if rot:
        cx, cy = center if center is not None else shape.geom.center()
        g = out.geom
        wcx, wcy = rotate_point(g.x + g.w / 2, g.y + g.h / 2, cx, cy, rot)
        out.geom = Geometry(wcx - g.w / 2, wcy - g.h / 2, g.w, g.h, rot)
    out.groups = tuple(shape.groups)
    out.priority = shape.priority   # Schnitt-Priorität („Nach Priorität“) bleibt
    out.reverse = shape.reverse     # umgekehrte Laufrichtung bleibt
    return out


def simplify_shape(shape: Shape, tolerance_mm: float = SIMPLIFY_TOLERANCE_MM,
                   fit_lines: bool = False) -> Shape | None:
    """Vereinfachte Kopie (neue ID) oder ``None`` (nicht vereinfachbar / unverändert)."""
    if not can_simplify(shape):
        return None
    tol = max(float(tolerance_mm), 0.0)
    closed = shape.kind == "polygon"
    if shape.curves:
        if not fit_lines:
            return None
        from .shape_paths import shape_polygons      # Qt nur für Kurven
        rings_src = []
        for poly in shape_polygons(shape):
            p = simplify_polyline(poly, 0.0)
            if closed and len(p) > 1 and _dist(p[0], p[-1]) <= _EPS:
                p.pop()
            rings_src.append(p)
        rot = 0.0           # abgeflacht in Arbeitsflächen-mm (Drehung eingerechnet)
    else:
        pts = shape.abs_points()
        rings_src = [pts[a:b] for a, b in shape.ring_ranges()]
        rot = None
    new_pts: list[Point] = []
    starts: list[int] = []
    for ring in rings_src:
        if closed:
            r = simplify_ring(ring, tol) if len(ring) >= 3 else list(ring)
        else:
            r = simplify_open(ring, tol) if len(ring) >= 2 else list(ring)
        if not r:
            continue
        if new_pts:
            starts.append(len(new_pts))
        new_pts.extend(r)
    if len(new_pts) < (3 if closed else 2):
        return None
    if not shape.curves and len(new_pts) == len(shape.points):
        return None                                   # nichts entfernt
    out = _rebuild(shape, new_pts, starts, rot=rot)
    if shape.tabs:   # manuelle Stege auf den vereinfachten Umriss übertragen
        from .tabs import carry_tabs
        out = carry_tabs(out, shape.tab_points(), 1.5 + tol)
    if shape.start:  # Startpunkt auf den vereinfachten Umriss übertragen
        from .startpoint import carry_start
        out = carry_start(out, shape.start_point(), 1.5 + tol)
    return out


@dataclass
class SimplifyResult:
    remove: list[str] = field(default_factory=list)
    add: list[Shape] = field(default_factory=list)
    shapes: int = 0               # vereinfachbare Formen im Bereich
    nodes_before: int = 0         # Knoten dieser Formen vorher
    nodes_after: int = 0          # … und nachher
    curves_skipped: int = 0       # Formen mit Kurvensegmenten (ohne „Kurven in Linien“)
    curves_fitted: int = 0        # Formen mit Kurvensegmenten, in Linien umgewandelt

    @property
    def changed(self) -> int:
        return len(self.add)

    @property
    def removed_nodes(self) -> int:
        return self.nodes_before - self.nodes_after

    def readout(self) -> str:
        if not self.shapes:
            return "Keine Pfade oder Polygone zum Vereinfachen"
        pct = 100.0 * self.removed_nodes / self.nodes_before if self.nodes_before else 0.0
        sign = "−" if pct >= 0 else "+"
        text = (f"Knoten: {self.nodes_before} → {self.nodes_after} ({sign}{abs(pct):.0f} %) · "
                f"{self.changed} von {self.shapes} Form(en) vereinfacht")
        if self.curves_fitted:
            text += f" · {self.curves_fitted} mit Kurven in Linien umgewandelt"
        if self.curves_skipped:
            text += f" · {self.curves_skipped} mit Kurven übersprungen"
        return text


def simplify_shapes(shapes: Iterable[Shape], tolerance_mm: float = SIMPLIFY_TOLERANCE_MM,
                    fit_lines: bool = False) -> SimplifyResult:
    """Alle vereinfachbaren Formen von ``shapes`` vereinfachen (siehe Moduldoku).

    Die Knotenzahl „vorher“ zählt die Stützpunkte; abgeflachte Kurven zählen
    vorher mit ihren Knoten, nachher mit den verbliebenen geraden Punkten."""
    res = SimplifyResult()
    for s in shapes:
        if not can_simplify(s):
            continue
        res.shapes += 1
        n = node_count(s)
        res.nodes_before += n
        if s.curves and not fit_lines:
            res.curves_skipped += 1
            res.nodes_after += n
            continue
        out = simplify_shape(s, tolerance_mm, fit_lines)
        if out is None:
            res.nodes_after += n
            continue
        if s.curves:
            res.curves_fitted += 1
        res.remove.append(s.id)
        res.add.append(out)
        res.nodes_after += node_count(out)
    return res
