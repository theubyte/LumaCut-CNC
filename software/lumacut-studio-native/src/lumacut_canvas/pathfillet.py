"""Ecken abrunden / abschrägen (LightBurn *Radius tool*, xTool Creative Space
„Eckenradius“ für Polygone und Sterne) – Qt-frei bis auf das Übertragen
manueller Stege (:mod:`tabs`).

Scharfe Ecken sind auf einem Diodenlaser ungünstig: der Kopf bremst an jeder
Ecke ab, die Leistung bleibt (ohne Eckenleistung, siehe §14) gleich, darum
brennen Spitzen von Sternen, Zacken und Schablonen dunkler und dünne Spitzen
verkohlen oder brechen ab. Abgerundete Ecken sehen auch an Untersetzern,
Schildern und Schablonen besser aus.

* **Abrunden**: jede Ecke wird durch einen Kreisbogen mit Radius ``radius_mm``
  ersetzt, der beide Kanten tangential berührt (Rückversatz
  ``t = r / tan(φ / 2)``, φ = Innenwinkel). Der Bogen wird wie im G-Code auf
  ≤ 0,02 mm abgeflacht (nur ``G1`` – der Pi lehnt G2/G3 ab).
* **Abschrägen**: dieselben Berührpunkte werden mit einer Geraden verbunden
  (Fase) – eine Kante pro Ecke, kein Bogen.
* Nur echte Ecken: Knicke unter ``min_angle_deg`` (Richtungsänderung) bleiben –
  so werden abgeflachte Kreise und Kurven aus Importen nicht „angeknabbert“.
* „Nur Außenecken“ / „Nur Innenecken“ (konvex / konkav bezogen auf den
  jeweiligen Ring) – bei einem Stern die Spitzen bzw. die Einbuchtungen.
  Offene Pfade haben kein Innen: dort zählt jede Ecke.
* Ist eine Kante zu kurz für den Radius, wird der Radius an dieser Ecke
  verkleinert (je Ecke höchstens die halbe Kante, wenn die Nachbarecke auch
  abgerundet wird, sonst die ganze) und als „begrenzt“ gezählt – wie LightBurn.
* Polygone (auch Vielecke / Sterne – sie werden zu gewöhnlichen Polygonen, wie
  LightBurns *Convert to Path*), Pfade (Anfang und Ende bleiben, ein Pfad mit
  gleichem Anfang und Ende auch dort) und alle Ringe (Löcher) eines Objekts.
  Drehung, Ebene und Gruppen bleiben, manuelle Stege wandern auf den neuen
  Umriss.
* Rechtecke bleiben Rechtecke: „Abrunden“ setzt ihren Eckenradius
  (:mod:`corners`, Feld „Ecken“ – im mm-Maß beim Skalieren erhalten),
  „Abschrägen“ macht ein scharfes Rechteck zu einem Polygon mit Fasen.
* Pfade mit Kurvensegmenten der Knotenbearbeitung, Ellipsen, Text, Linien,
  Bilder und erzeugte Objekte (Codes, Bogentext) werden nicht verändert.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from .model import Shape

Point = tuple[float, float]

MODES = ("round", "chamfer")
MODE_LABELS = {"round": "Abrunden", "chamfer": "Abschrägen"}
CORNERS = ("all", "outer", "inner")
CORNER_LABELS = {"all": "Alle Ecken", "outer": "Nur Außenecken (Spitzen)",
                 "inner": "Nur Innenecken"}
RADIUS_MM = 2.0
RADIUS_RANGE = (0.05, 100.0)
MIN_ANGLE_DEG = 10.0                 # Richtungsänderung, ab der ein Knick als Ecke zählt
MIN_ANGLE_RANGE = (1.0, 170.0)
FLATTEN_TOL_MM = 0.02                # wie shape_paths / G-Code
MAX_TURN_DEG = 179.5                 # fast umkehrende Spitze: wie 179.5° behandeln
FILLET_KINDS = ("polygon", "path", "rect")
_EPS = 1e-9


def can_fillet(shape: Shape) -> bool:
    """Objekt, dessen Ecken abgerundet / abgeschrägt werden dürfen."""
    return shape.kind in FILLET_KINDS and not shape.generator


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _dedupe(pts: list[Point], closed: bool) -> list[Point]:
    out: list[Point] = []
    for p in pts:
        if not out or _dist(out[-1], p) > 1e-7:
            out.append(p)
    while closed and len(out) > 1 and _dist(out[0], out[-1]) <= 1e-7:
        out.pop()
    return out


def _signed_area(ring: list[Point]) -> float:
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))


def arc_segments(radius: float, sweep: float, tol: float = FLATTEN_TOL_MM) -> int:
    """Strecken für einen Bogen, deren Sehnenabweichung höchstens ``tol`` ist."""
    if radius <= tol:
        return max(1, math.ceil(sweep / (math.pi / 4)))
    step = 2.0 * math.acos(1.0 - tol / radius)
    return max(1, math.ceil(sweep / step - 1e-9))


@dataclass
class _Corner:
    turn: float                  # Richtungsänderung (rad, 0 = gerade)
    convex: bool | None          # None = offener Pfad (kein Innen)


@dataclass
class RingResult:
    points: list[Point]
    corners: int = 0
    clamped: int = 0


def _corner_info(pts: list[Point], i: int, ring_sign: float | None) -> tuple[_Corner, Point, Point, float, float]:
    n = len(pts)
    a, p, b = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
    ux, uy = a[0] - p[0], a[1] - p[1]
    vx, vy = b[0] - p[0], b[1] - p[1]
    la, lb = math.hypot(ux, uy), math.hypot(vx, vy)
    ux, uy, vx, vy = ux / la, uy / la, vx / lb, vy / lb
    cosphi = max(-1.0, min(1.0, ux * vx + uy * vy))
    phi = math.acos(cosphi)                       # Innenwinkel 0..π
    turn = math.pi - phi
    cross = (p[0] - a[0]) * (b[1] - p[1]) - (p[1] - a[1]) * (b[0] - p[0])
    convex = None if ring_sign is None else (cross * ring_sign > 0)
    return _Corner(turn, convex), (ux, uy), (vx, vy), la, lb


def fillet_points(pts: list[Point], radius_mm: float, closed: bool, mode: str = "round",
                  corners: str = "all", min_angle_deg: float = MIN_ANGLE_DEG) -> RingResult:
    """Ecken eines Rings (``closed``, ohne wiederholten Startpunkt) oder offenen
    Pfads abrunden / abschrägen. Liefert die neuen Punkte und die Zähler."""
    src = _dedupe(list(pts), closed)
    n = len(src)
    if n < 3 or radius_mm <= 0:
        return RingResult(list(pts))
    sign = None
    if closed:
        area = _signed_area(src)
        if abs(area) < _EPS:
            return RingResult(list(pts))
        sign = 1.0 if area > 0 else -1.0
    min_turn = math.radians(max(0.0, min_angle_deg))
    idx = range(n) if closed else range(1, n - 1)
    info = {}
    for i in idx:
        c, u, v, la, lb = _corner_info(src, i, sign)
        if c.turn < min_turn - 1e-12 or c.turn < 1e-6:
            continue
        if corners == "outer" and c.convex is False:
            continue
        if corners == "inner" and c.convex is True:
            continue
        info[i] = (c, u, v, la, lb)
    if not info:
        return RingResult(list(pts))
    out: list[Point] = []
    res = RingResult(out)
    max_turn = math.radians(MAX_TURN_DEG)
    for i in range(n):
        p = src[i]
        if i not in info:
            out.append(p)
            continue
        c, u, v, la, lb = info[i]
        turn = min(c.turn, max_turn)
        half_phi = (math.pi - turn) / 2.0          # halber Innenwinkel
        t = radius_mm / math.tan(half_phi)
        share_a = 0.5 if ((i - 1) % n) in info else 1.0
        share_b = 0.5 if ((i + 1) % n) in info else 1.0
        t_max = min(la * share_a, lb * share_b)
        r = radius_mm
        if t > t_max + 1e-9:
            t = t_max
            r = t * math.tan(half_phi)
            res.clamped += 1
        if t <= 1e-6:
            out.append(p)
            continue
        res.corners += 1
        t1 = (p[0] + u[0] * t, p[1] + u[1] * t)
        t2 = (p[0] + v[0] * t, p[1] + v[1] * t)
        if mode == "chamfer":
            out.extend([t1, t2])
            continue
        bx, by = u[0] + v[0], u[1] + v[1]
        bl = math.hypot(bx, by)
        if bl < 1e-12:
            out.extend([t1, t2])
            continue
        d = r / math.sin(half_phi)
        cx, cy = p[0] + bx / bl * d, p[1] + by / bl * d
        a0 = math.atan2(t1[1] - cy, t1[0] - cx)
        a1 = math.atan2(t2[1] - cy, t2[0] - cx)
        sweep = a1 - a0
        while sweep <= -math.pi:
            sweep += 2 * math.pi
        while sweep > math.pi:
            sweep -= 2 * math.pi
        k = arc_segments(r, abs(sweep))
        out.append(t1)
        for j in range(1, k):
            a = a0 + sweep * j / k
            out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        out.append(t2)
    res.points = _dedupe(out, closed)
    return res


@dataclass
class FilletShapeResult:
    shape: Shape | None
    corners: int = 0
    clamped: int = 0


def _rect_points(shape: Shape) -> list[Point]:
    g = shape.geom
    x, y, w, h = g.x, g.y, abs(g.w), abs(g.h)
    x = min(g.x, g.x + g.w)
    y = min(g.y, g.y + g.h)
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def fillet_shape(shape: Shape, radius_mm: float = RADIUS_MM, mode: str = "round",
                 corners: str = "all", min_angle_deg: float = MIN_ANGLE_DEG) -> FilletShapeResult:
    """Abgerundete / abgeschrägte Kopie (Polygon / Pfad: neue ID, Rechteck mit
    Radius: gleiche ID) oder ``shape=None`` (nichts zu tun)."""
    none = FilletShapeResult(None)
    if not can_fillet(shape) or shape.curves or radius_mm <= 0:
        return none
    if mode not in MODES:
        raise ValueError(f"unbekannte Art {mode!r}")
    if shape.kind == "rect":
        from . import corners as rc
        if corners == "inner" or rc.is_rounded(shape):
            return none                  # keine Innenecken / schon gerundet (Feld „Ecken“)
        if min(abs(shape.geom.w), abs(shape.geom.h)) <= _EPS:
            return none
        if mode == "round":
            new = rc.with_corner_radius(shape, radius_mm)
            r = rc.effective_radius(new)
            if r <= 0:
                return none
            return FilletShapeResult(new, 4, 4 if r < radius_mm - 1e-6 else 0)
        rr = fillet_points(_rect_points(shape), radius_mm, True, mode, "all", 0.0)
        if not rr.corners:
            return none
        return FilletShapeResult(_rebuild(shape, rr.points, [], "polygon"), rr.corners, rr.clamped)
    closed = shape.kind == "polygon"
    pts = shape.abs_points()
    new_pts: list[Point] = []
    starts: list[int] = []
    total = clamped = 0
    for a, b in shape.ring_ranges():
        ring = pts[a:b]
        loop = closed
        if not closed and len(ring) >= 4 and _dist(ring[0], ring[-1]) <= 1e-6:
            loop = True                      # Pfad mit gleichem Anfang und Ende
            ring = ring[:-1]
        if len(ring) >= 3:
            rr = fillet_points(ring, radius_mm, loop, mode, corners, min_angle_deg)
            r_pts = rr.points
            total += rr.corners
            clamped += rr.clamped
        else:
            r_pts = list(ring)
        if loop and not closed and r_pts:
            r_pts = r_pts + [r_pts[0]]
        if new_pts:
            starts.append(len(new_pts))
        new_pts.extend(r_pts)
    if not total:
        return none
    return FilletShapeResult(_rebuild(shape, new_pts, starts, shape.kind), total, clamped)


def _rebuild(shape: Shape, local: list[Point], starts: list[int], kind: str) -> Shape:
    from .pathsimplify import _rebuild as rebuild
    out = rebuild(shape, local, starts, kind=kind)
    if shape.tabs:          # manuelle Stege auf den neuen Umriss übertragen
        from .tabs import carry_tabs
        out = carry_tabs(out, shape.tab_points(), 1.5 + _tab_slack(shape))
    return out


def _tab_slack(shape: Shape) -> float:
    g = shape.geom
    return max(abs(g.w), abs(g.h), 1.0)    # Stege an einer Ecke wandern auf den Bogen / die Fase


@dataclass
class FilletResult:
    remove: list[str] = field(default_factory=list)
    add: list[Shape] = field(default_factory=list)
    shapes: int = 0               # passende Formen im Bereich
    corners: int = 0              # abgerundete / abgeschrägte Ecken
    clamped: int = 0              # Ecken mit verkleinertem Radius (Kante zu kurz)
    curves_skipped: int = 0       # Formen mit Kurvensegmenten
    mode: str = "round"

    @property
    def changed(self) -> int:
        return len(self.add)

    def readout(self) -> str:
        if not self.shapes:
            return "Keine Polygone, Pfade oder Rechtecke mit Ecken"
        verb = "abgerundet" if self.mode == "round" else "abgeschrägt"
        if not self.corners:
            text = f"Keine passenden Ecken in {self.shapes} Form(en)"
        else:
            text = f"{self.corners} Ecke(n) {verb} in {self.changed} von {self.shapes} Form(en)"
        if self.clamped:
            text += f" · {self.clamped} mit kleinerem Radius (Kante zu kurz)"
        if self.curves_skipped:
            text += f" · {self.curves_skipped} mit Kurven übersprungen"
        return text


def fillet_shapes(shapes: Iterable[Shape], radius_mm: float = RADIUS_MM, mode: str = "round",
                  corners: str = "all", min_angle_deg: float = MIN_ANGLE_DEG) -> FilletResult:
    """Ecken aller passenden Formen von ``shapes`` abrunden / abschrägen (siehe Moduldoku)."""
    res = FilletResult(mode=mode)
    for s in shapes:
        if not can_fillet(s):
            continue
        res.shapes += 1
        if s.curves:
            res.curves_skipped += 1
            continue
        out = fillet_shape(s, radius_mm, mode, corners, min_angle_deg)
        if out.shape is None:
            continue
        res.remove.append(s.id)
        res.add.append(out.shape)
        res.corners += out.corners
        res.clamped += out.clamped
    return res
