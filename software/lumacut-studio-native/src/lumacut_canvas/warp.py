"""Verzerren (LightBurn *Warp Selection* / *Deform*, xTool „Verzerren“ / Bogen-Hülle).

Die Auswahl wird über ihre gemeinsame Hüllbox in ein beliebiges konvexes Viereck
abgebildet – für Gravuren auf schrägen oder sich verjüngenden Flächen (Becher,
Lampenschirm, Holzscheibe im Winkel fotografiert), für Text in einer Trapez- oder
Bogen-Hülle (Wappen, Banner, Schild) und zum Nachstellen einer Perspektive.

Zwei Arten:

* ``envelope`` – **Hülle** (bilinear wie LightBurn *Warp*): jede Seite der Box geht
  auf die entsprechende Seite des Vierecks; dazu optional eine **Wölbung** der Ober- und
  Unterkante (Parabel, + = nach oben), damit wird aus der Hülle ein Bogen / eine Tonne.
  Gerade Linien quer durch die Fläche werden dabei zu Kurven.
* ``perspective`` – **Perspektive** (projektiv): gerade Linien bleiben gerade, Abstände
  ziehen sich zur kurzen Seite hin zusammen (Fliese / Schild schräg von vorn gesehen).

Ergebnis: geschlossene Formen (Rechteck, Ellipse, Polygon, Umriss-Text) werden ein
``polygon`` mit allen Ringen, offene (Linie, Pfad, Einlinien-Text) ein ``path``. Jede
Strecke wird so fein unterteilt, dass das Ergebnis höchstens :data:`TOL_MM` von der
exakten Abbildung abweicht. Ebene, Gruppen, Priorität, Laufrichtung, manuelle Stege und
Startpunkt bleiben (auf das verzerrte Objekt übertragen). Bilder werden nicht verzerrt.
Qt-abhängig nur über :func:`shape_paths.shape_polygons` (Text braucht QGuiApplication).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from .model import Shape, is_closed_shape
from .shape_paths import shape_polygons
from .workarea import Rect, is_inside_work_area

MODES = ("envelope", "perspective")
MODE_LABELS = {"envelope": "Hülle (biegt Linien, wie LightBurn Warp)",
               "perspective": "Perspektive (Geraden bleiben gerade)"}
CORNERS = ("tl", "tr", "br", "bl")
CORNER_LABELS = {"tl": "Oben links", "tr": "Oben rechts", "br": "Unten rechts", "bl": "Unten links"}
TOL_MM = 0.01            # Sehnenfehler der Unterteilung
FLATTEN_MM = 0.005       # Abflachen der Kurven vor dem Verzerren
MAX_DEPTH = 14           # höchstens 2^14 Teilstücke je Strecke
OFFSET_RANGE = (-1000.0, 1000.0)
BULGE_RANGE = (-500.0, 500.0)
MIN_BOX_MM = 0.5         # schmalere Auswahl lässt sich nicht verzerren
_GRID = 12               # Prüfraster für Faltungen (Jacobi-Determinante)

Point = tuple[float, float]


class WarpError(ValueError):
    pass


def can_warp(shape: Shape) -> bool:
    return shape.kind != "image"


def selection_box(shapes: Iterable[Shape]) -> Rect | None:
    box = None
    for s in shapes:
        b = s.bounds()
        box = b if box is None else box.united(b)
    return box


def box_corners(box: Rect) -> tuple[Point, Point, Point, Point]:
    return ((box.x, box.y), (box.right, box.y), (box.right, box.bottom), (box.x, box.bottom))


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gauß mit Spaltenpivot (8×8, ohne numpy-Pflicht)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            raise WarpError("Perspektive: das Viereck ist entartet (Ecken auf einer Linie).")
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c and m[r][c]:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def _homography(quad) -> tuple[float, ...]:
    """Projektive Abbildung Einheitsquadrat (0,0),(1,0),(1,1),(0,1) -> ``quad``."""
    src = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    a, b = [], []
    for (u, v), (x, y) in zip(src, quad):
        a.append([u, v, 1, 0, 0, 0, -u * x, -v * x])
        b.append(x)
        a.append([0, 0, 0, u, v, 1, -u * y, -v * y])
        b.append(y)
    return tuple(_solve(a, b))


@dataclass
class Warp:
    """Abbildung der Box ``box`` auf das Viereck ``quad`` (oben links, oben rechts,
    unten rechts, unten links – Bildschirmrichtung, y nach unten)."""

    box: Rect
    quad: tuple[Point, Point, Point, Point]
    mode: str = "envelope"
    bulge_top: float = 0.0       # mm, + = Oberkante wölbt sich nach oben
    bulge_bottom: float = 0.0    # mm, + = Unterkante wölbt sich nach oben
    _h: tuple = field(default=(), repr=False)

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise WarpError(f"Unbekannte Art: {self.mode}")
        self.quad = tuple((float(x), float(y)) for x, y in self.quad)
        if self.mode == "perspective":
            self.bulge_top = self.bulge_bottom = 0.0

    @property
    def homography(self) -> tuple:
        if not self._h:
            self._h = _homography(self.quad)
        return self._h

    def uv(self, x: float, y: float) -> Point:
        b = self.box
        return ((x - b.x) / b.w if b.w > 0 else 0.5, (y - b.y) / b.h if b.h > 0 else 0.5)

    def map_uv(self, u: float, v: float) -> Point:
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = self.quad
        if self.mode == "perspective":
            a, b, c, d, e, f, g, h = self.homography
            w = g * u + h * v + 1.0
            return ((a * u + b * v + c) / w, (d * u + e * v + f) / w)
        x = (1 - u) * (1 - v) * x0 + u * (1 - v) * x1 + u * v * x2 + (1 - u) * v * x3
        y = (1 - u) * (1 - v) * y0 + u * (1 - v) * y1 + u * v * y2 + (1 - u) * v * y3
        if self.bulge_top or self.bulge_bottom:
            y -= ((1 - v) * self.bulge_top + v * self.bulge_bottom) * 4.0 * u * (1 - u)
        return (x, y)

    def map(self, p: Point) -> Point:
        return self.map_uv(*self.uv(*p))

    def is_identity(self, eps: float = 1e-9) -> bool:
        return (all(math.dist(a, b) <= eps for a, b in zip(self.quad, box_corners(self.box)))
                and abs(self.bulge_top) <= eps and abs(self.bulge_bottom) <= eps)

    def problem(self) -> str:
        """Leer, wenn die Abbildung umkehrbar ist; sonst der Grund (für den Dialog)."""
        if self.box.w < MIN_BOX_MM or self.box.h < MIN_BOX_MM:
            return ("Verzerren braucht eine Auswahl mit Breite und Höhe "
                    f"(mindestens {MIN_BOX_MM:g} mm) – eine einzelne waagrechte / senkrechte Linie "
                    "lässt sich nicht verzerren.")
        if not all(math.isfinite(c) for p in self.quad for c in p) or not (
                math.isfinite(self.bulge_top) and math.isfinite(self.bulge_bottom)):
            return "Ungültige Zahl in den Ecken."
        # Viereck konvex und im gleichen Drehsinn wie die Box (nicht gespiegelt / verdreht)
        q = self.quad
        for i in range(4):
            (ax, ay), (bx, by), (cx, cy) = q[i], q[(i + 1) % 4], q[(i + 2) % 4]
            if (bx - ax) * (cy - by) - (by - ay) * (cx - bx) <= 1e-9:
                return ("Das Viereck muss konvex bleiben und darf sich nicht überschlagen "
                        "(Ecken nicht über die gegenüberliegende Seite ziehen).")
        if self.mode == "perspective":
            try:
                self.homography
            except WarpError as e:
                return str(e)
        # Faltung durch die Wölbung: Jacobi-Determinante auf einem Raster prüfen
        if self.bulge_top or self.bulge_bottom:
            d = 1e-4
            for i in range(_GRID + 1):
                for j in range(_GRID + 1):
                    u, v = min(1 - d, max(d, i / _GRID)), min(1 - d, max(d, j / _GRID))
                    p = self.map_uv(u, v)
                    pu = self.map_uv(u + d, v)
                    pv = self.map_uv(u, v + d)
                    det = (pu[0] - p[0]) * (pv[1] - p[1]) - (pu[1] - p[1]) * (pv[0] - p[0])
                    if det <= 0:
                        return ("Die Wölbung ist zu stark – Ober- und Unterkante würden sich "
                                "kreuzen. Wölbung verringern oder das Viereck höher ziehen.")
        return ""


def warp_from_offsets(box: Rect, offsets, mode: str = "envelope", bulge_top: float = 0.0,
                      bulge_bottom: float = 0.0) -> Warp:
    """``offsets``: (dx, dy) je Ecke oben links, oben rechts, unten rechts, unten links
    in mm (Bildschirmrichtung: + nach rechts / unten)."""
    quad = tuple((cx + float(dx), cy + float(dy))
                 for (cx, cy), (dx, dy) in zip(box_corners(box), offsets))
    return Warp(box, quad, mode, float(bulge_top), float(bulge_bottom))


def _seg_dist(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 <= 1e-18:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def warp_polyline(pts: list[Point], warp: Warp, closed: bool, tol: float = TOL_MM) -> list[Point]:
    """Polylinie (Arbeitsflächen-mm) verzerren; jede Strecke adaptiv unterteilt, bis
    Viertel-, Mittel- und Dreiviertelpunkt höchstens ``tol`` von der Sehne liegen."""
    if not pts:
        return []
    uvs = [warp.uv(*p) for p in pts]
    if closed:
        uvs = uvs + uvs[:1]
    out = [warp.map_uv(*uvs[0])]

    def sub(ua, pa, ub, pb, depth):
        tests = []
        for t in (0.25, 0.5, 0.75):
            uv = (ua[0] + (ub[0] - ua[0]) * t, ua[1] + (ub[1] - ua[1]) * t)
            tests.append((uv, warp.map_uv(*uv)))
        if depth >= MAX_DEPTH or all(_seg_dist(p, pa, pb) <= tol for _uv, p in tests):
            out.append(pb)
            return
        um, pm = tests[1]
        sub(ua, pa, um, pm, depth + 1)
        sub(um, pm, ub, pb, depth + 1)

    for ua, ub in zip(uvs, uvs[1:]):
        sub(ua, out[-1], ub, warp.map_uv(*ub), 0)
    if closed:
        out.pop()
    clean = []
    for p in out:
        if not clean or math.dist(p, clean[-1]) > 1e-9:
            clean.append(p)
    if closed and len(clean) > 1 and math.dist(clean[0], clean[-1]) <= 1e-9:
        clean.pop()
    return clean


def _shape_rings(shape: Shape, closed: bool) -> list[list[Point]]:
    rings = []
    for poly in shape_polygons(shape, FLATTEN_MM):
        pts = list(poly)
        if closed and len(pts) > 1 and math.dist(pts[0], pts[-1]) < 1e-9:
            pts.pop()
        if len(pts) >= (3 if closed else 2):
            rings.append(pts)
    return rings


def warp_shape(shape: Shape, warp: Warp) -> Shape | None:
    """Ein Objekt verzerren -> neues ``polygon`` (geschlossen) oder ``path`` (offen)."""
    if not can_warp(shape):
        return None
    closed = is_closed_shape(shape)
    least = 3 if closed else 2
    pts: list[Point] = []
    starts: list[int] = []
    for ring in _shape_rings(shape, closed):
        w = warp_polyline(ring, warp, closed)
        if len(w) < least:
            continue
        if pts:
            starts.append(len(pts))
        pts.extend(w)
    if len(pts) < least:
        return None
    out = Shape.from_points("polygon" if closed else "path", pts, shape.layer_id, rings=starts)
    out.groups = shape.groups
    out.priority = shape.priority
    out.reverse = shape.reverse
    if shape.tabs and closed:
        from .tabs import carry_tabs
        out = carry_tabs(out, [warp.map(p) for p in shape.tab_points()], 0.1)
    sp = shape.start_point()
    if sp is not None and closed:
        from .startpoint import carry_start
        out = carry_start(out, warp.map(sp), 0.1)
    return out


@dataclass
class WarpResult:
    remove: list[str] = field(default_factory=list)
    add: list[Shape] = field(default_factory=list)
    images: int = 0
    problem: str = ""
    bounds: Rect | None = None

    @property
    def changed(self) -> int:
        return len(self.add)

    @property
    def inside(self) -> bool:
        return self.bounds is None or is_inside_work_area(self.bounds, eps=1e-3)

    def readout(self) -> str:
        if self.problem:
            return self.problem
        if not self.add:
            text = "Nichts zu verzerren – Formen, Linien oder Text auswählen."
        else:
            polys = sum(1 for s in self.add if s.kind == "polygon")
            paths = len(self.add) - polys
            parts = []
            if polys:
                parts.append(f"{polys} geschlossene Form(en)")
            if paths:
                parts.append(f"{paths} offene Linie(n)")
            text = f"{len(self.add)} Objekt(e) verzerrt ({', '.join(parts)})"
            if self.bounds is not None:
                text += f" · neue Größe {self.bounds.w:.1f} × {self.bounds.h:.1f} mm"
        if self.images:
            text += f" · {self.images} Bild(er) bleiben unverändert (Bilder werden nicht verzerrt)"
        if self.add and not self.inside:
            text += " · Ergebnis ragt über die Arbeitsfläche hinaus – Ecken nach innen ziehen"
        return text


def warp_shapes(shapes: Iterable[Shape], warp: Warp) -> WarpResult:
    shapes = list(shapes)
    res = WarpResult(images=sum(1 for s in shapes if not can_warp(s)))
    res.problem = warp.problem()
    if res.problem:
        return res
    box = None
    for s in shapes:
        out = warp_shape(s, warp)
        if out is None:
            continue
        res.remove.append(s.id)
        res.add.append(out)
        b = out.bounds()
        box = b if box is None else box.united(b)
    res.bounds = box
    return res


def preset_offsets(name: str, box: Rect) -> tuple[tuple[float, float], ...]:
    """Schnellwahl im Dialog (Bildschirmrichtung): Trapez oben / unten schmaler um je
    10 % der Breite, Schräge (rechte Seite 10 % der Höhe höher), Rücksetzen."""
    dx, dy = 0.1 * box.w, 0.1 * box.h
    if name == "top_narrow":
        return ((dx, 0.0), (-dx, 0.0), (0.0, 0.0), (0.0, 0.0))
    if name == "bottom_narrow":
        return ((0.0, 0.0), (0.0, 0.0), (-dx, 0.0), (dx, 0.0))
    if name == "rise_right":
        return ((0.0, 0.0), (0.0, -dy), (0.0, 0.0), (0.0, 0.0))
    return ((0.0, 0.0),) * 4
