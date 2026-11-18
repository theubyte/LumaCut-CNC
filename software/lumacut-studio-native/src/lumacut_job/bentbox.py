"""Bent box generator (flex box with rounded corners, boxes.py „FlexBox“) – pure Python.

A box of outer (or inner) size W × D × H whose four walls are one strip of
sheet material (or two, ``split``) bent around rounded corners: in each corner
the strip carries a living hinge (:mod:`lumacut_job.hinge`) exactly as wide as
the 90° arc of its neutral fibre, so the strip wraps around the inner corner
radius ``radius_mm``. Bottom and lid are rounded rectangles that sit inside
the strip; along the straight sides they interlock with it by finger joints,
derived from the same ownership rule as the finger box (:mod:`lumacut_job.boxgen`):

* every straight side (length ``W − 2 R`` or ``D − 2 R``, R the outer corner
  radius) is split into an odd number of segments, the strip owns the even
  ones (both ends, so it stays whole where it starts to bend), bottom / lid the
  odd ones – tabs ``t`` deep that pass through notches of the strip;
* in the corners the strip owns the edge all the way (the plate's rounded
  corner touches its inner face).

The strip starts and ends in the middle of the back side (a butt joint held by
the bottom and the lid; with ``split`` also in the middle of the front). Every
part is grown by half the kerf (mitred) like the finger box, so tabs fit their
notches; the hinge slits are open lines / holes and are not offset.

Parts are laid out flat (shelf packing, long parts turned when that fits
better); :func:`bentbox_shapes` returns the outlines as closed ``polygon``
objects and the hinge cuts as ``path`` / ``polygon`` objects in one group,
ready for a cut layer. Pure Python (shapely), no Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from shapely.geometry import Polygon, box as sbox
from shapely.ops import unary_union

from lumacut_canvas.model import Shape, new_id
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from . import boxgen, hinge

SIZE_RANGE = boxgen.SIZE_RANGE
THICKNESS_RANGE = boxgen.THICKNESS_RANGE
FINGER_RANGE = boxgen.FINGER_RANGE
KERF_RANGE = boxgen.KERF_RANGE
SPACING_RANGE = boxgen.SPACING_RANGE
DEFAULT_KERF = boxgen.DEFAULT_KERF
RADIUS_RANGE = (3.0, 300.0)       # mm inner corner radius (the arc stays ≥ 5 mm wide)
CUT_RANGE = hinge.CUT_RANGE
BRIDGE_RANGE = hinge.BRIDGE_RANGE
PITCH_RANGE = hinge.PITCH_RANGE
PATTERNS = hinge.PATTERNS
PATTERN_LABELS = hinge.PATTERN_LABELS
ARC_STEP_MM = 0.5                 # chord length of the rounded plate corners

PART_NAMES = ("Wand", "Wand 1", "Wand 2", "Boden", "Deckel")


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


@dataclass(frozen=True)
class BentBoxSpec:
    width_mm: float = 100.0       # X (front side)
    depth_mm: float = 80.0        # Y (left / right side)
    height_mm: float = 50.0       # Z
    radius_mm: float = 10.0       # inner corner radius (inside face of the bent wall)
    thickness_mm: float = 3.0
    finger_mm: float = 10.0
    kerf_mm: float = DEFAULT_KERF
    lid: bool = True              # False: open box, straight top edge of the wall
    inner: bool = False           # W / D / H are inside sizes
    pattern: str = "lines"        # hinge pattern in the corners
    cut_mm: float = 20.0          # wished hinge slit length
    bridge_mm: float = 3.0
    pitch_mm: float = 2.0
    split: bool = False           # wall in two parts (seams in the middle of back and front)
    spacing_mm: float = 4.0
    x: float = 0.0                # top left corner of the layout
    y: float = 0.0

    def normalized(self) -> "BentBoxSpec":
        def f(v, rng, default):
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = default
            if not math.isfinite(v):
                v = default
            return round(_clamp(v, *rng), 3)
        pattern = self.pattern if self.pattern in PATTERNS else "lines"
        return BentBoxSpec(width_mm=f(self.width_mm, SIZE_RANGE, 100.0),
                           depth_mm=f(self.depth_mm, SIZE_RANGE, 80.0),
                           height_mm=f(self.height_mm, SIZE_RANGE, 50.0),
                           radius_mm=f(self.radius_mm, RADIUS_RANGE, 10.0),
                           thickness_mm=f(self.thickness_mm, THICKNESS_RANGE, 3.0),
                           finger_mm=f(self.finger_mm, FINGER_RANGE, 10.0),
                           kerf_mm=f(self.kerf_mm, KERF_RANGE, DEFAULT_KERF),
                           lid=bool(self.lid), inner=bool(self.inner), pattern=pattern,
                           cut_mm=f(self.cut_mm, CUT_RANGE, 20.0),
                           bridge_mm=f(self.bridge_mm, BRIDGE_RANGE, 3.0),
                           pitch_mm=f(self.pitch_mm, PITCH_RANGE, 2.0),
                           split=bool(self.split),
                           spacing_mm=f(self.spacing_mm, SPACING_RANGE, 4.0),
                           x=float(self.x), y=float(self.y))

    def outer(self) -> tuple[float, float, float]:
        """Outer size (W, D, H) of the assembled box."""
        s = self.normalized()
        if not s.inner:
            return s.width_mm, s.depth_mm, s.height_mm
        t = s.thickness_mm
        return (s.width_mm + 2 * t, s.depth_mm + 2 * t,
                s.height_mm + (2 * t if s.lid else t))

    def inside(self) -> tuple[float, float, float]:
        """Inner (usable) size of the assembled box."""
        s = self.normalized()
        w, d, h = s.outer()
        t = s.thickness_mm
        return w - 2 * t, d - 2 * t, h - (2 * t if s.lid else t)

    def outer_radius(self) -> float:
        s = self.normalized()
        return s.radius_mm + s.thickness_mm

    def arc_mm(self) -> float:
        """Length of one 90° corner on the neutral fibre = width of its hinge field."""
        s = self.normalized()
        return hinge.width_for(s.radius_mm, 90.0, s.thickness_mm)

    def straights(self) -> tuple[float, float]:
        """Straight lengths of the front / back and of the left / right sides."""
        s = self.normalized()
        W, D, _H = s.outer()
        R = s.outer_radius()
        return max(0.0, W - 2 * R), max(0.0, D - 2 * R)

    def wall_length(self) -> float:
        """Developed length of the whole wall strip (before kerf)."""
        s = self.normalized()
        sw, sd = s.straights()
        return 2 * sw + 2 * sd + 4 * s.arc_mm()

    def corner_hinge(self) -> hinge.HingeSpec:
        """The living hinge of one corner (field = arc × wall height, edges closed)."""
        s = self.normalized()
        _W, _D, H = s.outer()
        return hinge.HingeSpec(width_mm=s.arc_mm(), height_mm=H, pattern=s.pattern,
                               cut_mm=s.cut_mm, bridge_mm=s.bridge_mm, pitch_mm=s.pitch_mm,
                               thickness_mm=s.thickness_mm, open_edges=False,
                               frame=False).normalized()


@dataclass(frozen=True)
class Part:
    name: str
    size: tuple[float, float]                  # (a, b) before kerf
    outline: tuple[tuple[float, float], ...]   # closed ring in part mm, y down, kerf applied
    cuts: tuple                                # inner cuts: ((points, closed), ...)


def check(spec: BentBoxSpec) -> None:
    """``ValueError`` (German) when the box cannot be built."""
    s = spec.normalized()
    W, D, H = s.outer()
    t = s.thickness_mm
    R = s.outer_radius()
    if H < 3 * t + 2.0:
        raise ValueError(f"Höhe {H:.1f} mm ist für {t:.1f} mm Material zu klein "
                         f"(mindestens {3 * t + 2.0:.1f} mm)")
    if 2 * R > min(W, D) + 1e-9:
        raise ValueError(f"Eckradius {s.radius_mm:.1f} mm + Material {t:.1f} mm passt nicht in "
                         f"{min(W, D):.1f} mm – Radius höchstens "
                         f"{max(0.0, min(W, D) / 2.0 - t):.1f} mm")
    if len(hinge.columns(s.corner_hinge())) < 2:
        raise ValueError(f"Ecke ({s.arc_mm():.1f} mm Biegestrecke) zu klein für "
                         f"{s.pitch_mm:.1f} mm Linienabstand – Radius größer oder "
                         "Linienabstand kleiner")
    hinge.slit_plan(s.corner_hinge())


def side_counts(spec: BentBoxSpec) -> tuple[int, int]:
    """Finger segment counts of the front / back and the left / right sides
    (1 = no tabs on that side)."""
    s = spec.normalized()
    sw, sd = s.straights()
    t = s.thickness_mm
    return (boxgen.finger_count(sw, s.finger_mm, t) if sw > 0 else 1,
            boxgen.finger_count(sd, s.finger_mm, t) if sd > 0 else 1)


def wall_layout(spec: BentBoxSpec):
    """Walk around the box from the middle of the back side: list of
    (kind, x0, x1) with kind "back" / "right" / "front" / "left" for the straight
    parts and "corner" for the arcs, in strip coordinates (one strip)."""
    s = spec.normalized()
    sw, sd = s.straights()
    a = s.arc_mm()
    out = []
    x = 0.0
    for kind, length in (("back", sw / 2.0), ("corner", a), ("right", sd), ("corner", a),
                         ("front", sw), ("corner", a), ("left", sd), ("corner", a),
                         ("back", sw / 2.0)):
        out.append((kind, x, x + length))
        x += length
    return out


def notches(spec: BentBoxSpec) -> list[tuple[float, float]]:
    """x intervals of the strip where the bottom / lid tabs pass (odd segments of
    every straight side; the back side is split by the seam at x = 0)."""
    s = spec.normalized()
    sw, sd = s.straights()
    nx, ny = side_counts(s)
    L = s.wall_length()
    lay = wall_layout(s)
    out: list[tuple[float, float]] = []
    for kind, x0, x1 in lay:
        if kind in ("right", "left", "front"):
            n = ny if kind != "front" else nx
            if n > 1:
                out += [(p, q) for p, q in boxgen._segments(x0, x1, n, "odd")]
    if nx > 1:
        for p, q in boxgen._segments(-sw / 2.0, sw / 2.0, nx, "odd"):
            if q <= 1e-9:
                out.append((L + p, L + q))
            elif p >= -1e-9:
                out.append((p, q))
            else:
                out.append((0.0, q))
                out.append((L + p, L))
    return sorted(out)


def _rounded_rect(x0: float, y0: float, x1: float, y1: float, r: float) -> Polygon:
    pts = []
    steps = max(8, int(math.ceil(r * math.pi / 2.0 / ARC_STEP_MM)))
    for cx, cy, a0 in ((x1 - r, y1 - r, 0.0), (x0 + r, y1 - r, 90.0), (x0 + r, y0 + r, 180.0),
                       (x1 - r, y0 + r, 270.0)):
        for i in range(steps + 1):
            ang = math.radians(a0 + 90.0 * i / steps)
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return Polygon(pts).buffer(0)


def _grow(poly: Polygon, k: float) -> Polygon:
    if k > 0:
        poly = poly.buffer(k, join_style=2, mitre_limit=10.0).simplify(0.0)
    return Polygon([(x + k, y + k) for x, y in poly.exterior.coords])


def _plate(s: BentBoxSpec, name: str) -> Part:
    W, D, _H = s.outer()
    t, R = s.thickness_mm, s.outer_radius()
    nx, ny = side_counts(s)
    parts = [_rounded_rect(t, t, W - t, D - t, s.radius_mm)]
    if nx > 1:
        for p, q in boxgen._segments(R, W - R, nx, "odd"):
            parts += [sbox(p, 0.0, q, t), sbox(p, D - t, q, D)]
    if ny > 1:
        for p, q in boxgen._segments(R, D - R, ny, "odd"):
            parts += [sbox(0.0, p, t, q), sbox(W - t, p, W, q)]
    poly = unary_union(parts)
    if poly.geom_type != "Polygon":
        raise ValueError("Boden zerfällt – Fingerbreite oder Materialdicke prüfen")
    k = s.kerf_mm / 2.0
    poly = _grow(poly, k)
    return Part(name, (W, D), boxgen._ring(poly, D + 2 * k), ())


def _hinge_cuts(s: BentBoxSpec, x0: float, k: float):
    """Slits of the corner starting at strip x0, y down from the top edge."""
    hs = s.corner_hinge()
    out = []
    for sl in hinge.slits(hs):
        out.append((tuple((round(x0 + u + k, 6), round(v + k, 6)) for u, v in sl.points),
                    sl.closed))
    return out


def parts(spec: BentBoxSpec) -> list[Part]:
    """Flat parts: the wall strip (or its two halves), bottom[, lid]."""
    s = spec.normalized()
    check(s)
    _W, _D, H = s.outer()
    t = s.thickness_mm
    L = s.wall_length()
    k = s.kerf_mm / 2.0
    corners = [x0 for kind, x0, _x1 in wall_layout(s) if kind == "corner"]
    strip = sbox(0.0, 0.0, L, H)
    holes = []
    for p, q in notches(s):
        holes.append(sbox(p, -1.0, q, t))              # z up: bottom edge at z = 0
        if s.lid:
            holes.append(sbox(p, H - t, q, H + 1.0))
    if holes:
        strip = strip.difference(unary_union(holes))
    pieces = [("Wand", 0.0, L)] if not s.split else [("Wand 1", 0.0, L / 2.0),
                                                       ("Wand 2", L / 2.0, L)]
    out = []
    for name, a, b in pieces:
        piece = strip.intersection(sbox(a, -1.0, b, H + 1.0))
        if piece.geom_type != "Polygon":
            raise ValueError("Wand zerfällt – Fingerbreite oder Materialdicke prüfen")
        piece = Polygon([(x - a, y) for x, y in piece.exterior.coords])
        piece = _grow(piece, k)
        cuts = []
        for x0 in corners:
            if a - 1e-9 <= x0 and x0 + s.arc_mm() <= b + 1e-9:
                cuts += _hinge_cuts(s, x0 - a, k)
        out.append(Part(name, (b - a, H), boxgen._ring(piece, H + 2 * k), tuple(cuts)))
    out.append(_plate(s, "Boden"))
    if s.lid:
        out.append(_plate(s, "Deckel"))
    return out


def _extent(pts) -> tuple[float, float]:
    return max(p[0] for p in pts), max(p[1] for p in pts)


def _turn(part_pts, w: float):
    return tuple((y, w - x) for x, y in part_pts)


def layout(spec: BentBoxSpec, width_limit: float = WORK_WIDTH_MM,
           height_limit: float = WORK_HEIGHT_MM):
    """Parts placed on the sheet: list of (name, outline, cuts) in layout mm and the
    layout size (w, h), and whether it fits. Tries the parts as drawn and with long
    parts turned by 90°; the smallest layout that fits wins."""
    s = spec.normalized()
    ps = parts(s)
    best = None
    for turn in (False, True):
        items = []
        for p in ps:
            ring, cuts = p.outline, p.cuts
            w, h = _extent(ring)
            if turn and w > h:
                ring = _turn(ring, w)
                cuts = tuple((_turn(pts, w), closed) for pts, closed in cuts)
            items.append((p.name, ring, cuts))
        order = sorted(range(len(items)), key=lambda i: -_extent(items[i][1])[1])
        sizes = [_extent(items[i][1]) for i in order]
        pos, lw, lh = boxgen._shelf(sizes, width_limit, s.spacing_mm)
        placed = [None] * len(items)
        for (px, py), i in zip(pos, order):
            name, ring, cuts = items[i]
            placed[i] = (name, tuple((x + px, y + py) for x, y in ring),
                         tuple((tuple((x + px, y + py) for x, y in pts), closed)
                               for pts, closed in cuts))
        fits = lw <= width_limit + 1e-6 and lh <= height_limit + 1e-6
        key = (not fits, lw * lh)
        if best is None or key < best[0]:
            best = (key, placed, (lw, lh), fits)
    return best[1], best[2], best[3]


def bentbox_shapes(spec: BentBoxSpec, layer_id: str) -> list[Shape]:
    """Hinge cuts (``path`` / ``polygon``) and the part outlines (closed ``polygon``) in
    one group, the layout's top left corner at (spec.x, spec.y). ``ValueError``
    (German) when the box cannot be built or the layout does not fit."""
    s = spec.normalized()
    placed, (lw, lh), fits = layout(s)
    eps = 1e-6
    if (not fits or s.x < -eps or s.y < -eps or s.x + lw > WORK_WIDTH_MM + eps
            or s.y + lh > WORK_HEIGHT_MM + eps):
        hint = "" if s.split else ", „Wand zweiteilig“ wählen"
        raise ValueError(f"Die Teile brauchen {lw:.0f} × {lh:.0f} mm und passen nicht auf die "
                         f"Arbeitsfläche ({WORK_WIDTH_MM:.0f} × {WORK_HEIGHT_MM:.0f} mm) – Box "
                         f"kleiner machen{hint} oder Abstand verringern")
    group = new_id()
    out: list[Shape] = []
    for _name, ring, cuts in placed:
        for pts, closed in cuts:
            sh = Shape.from_points("polygon" if closed else "path",
                                   [(round(x + s.x, 6), round(y + s.y, 6)) for x, y in pts],
                                   layer_id)
            sh.groups = (group,)
            out.append(sh)
        sh = Shape.from_points("polygon", [(round(x + s.x, 6), round(y + s.y, 6)) for x, y in ring],
                               layer_id)
        sh.groups = (group,)
        out.append(sh)
    return out


def centered(spec: BentBoxSpec, center: tuple[float, float] | None = None) -> BentBoxSpec:
    """Spec with X / Y so that the layout is centred on ``center`` (work area centre)."""
    s = spec.normalized()
    _placed, (lw, lh), _fits = layout(s)
    cx, cy = center or (WORK_WIDTH_MM / 2.0, WORK_HEIGHT_MM / 2.0)
    x = min(max(0.0, cx - lw / 2.0), max(0.0, WORK_WIDTH_MM - lw))
    y = min(max(0.0, cy - lh / 2.0), max(0.0, WORK_HEIGHT_MM - lh))
    return replace(s, x=x, y=y)


def describe(spec: BentBoxSpec) -> str:
    """German one-line readout: sizes, wall, corners, fingers, layout size."""
    s = spec.normalized()
    W, D, H = s.outer()
    iw, id_, ih = s.inside()
    ps = parts(s)
    nx, ny = side_counts(s)
    hs = s.corner_hinge()
    n_cuts = sum(len(p.cuts) for p in ps)
    _placed, (lw, lh), _fits = layout(s)
    walls = 2 if s.split else 1
    return (f"Außen {W:.1f} × {D:.1f} × {H:.1f} mm, innen {iw:.1f} × {id_:.1f} × {ih:.1f} mm, "
            f"Ecken innen R {s.radius_mm:.1f} mm · Wand {s.wall_length():.1f} mm lang "
            f"({walls} {'Teil' if walls == 1 else 'Teile'}) · 4 Ecken "
            f"({PATTERN_LABELS[s.pattern]}), je {len(hinge.columns(hs))} Linien auf "
            f"{s.arc_mm():.1f} mm, {n_cuts} Schnitte · Zinken {nx} / {ny} (Breite / Tiefe) · "
            f"{len(ps)} Teile ({'mit Deckel' if s.lid else 'offen'}) · Platz auf dem Material "
            f"{lw:.0f} × {lh:.0f} mm")


def warnings(spec: BentBoxSpec) -> list[str]:
    """German hints: the corner hinge's warnings and plates without tabs."""
    s = spec.normalized()
    out = hinge.warnings(s.corner_hinge())
    if side_counts(s) == (1, 1):
        out.append("Seiten zu kurz für Zinken – Boden und Deckel einkleben")
    if s.finger_mm < s.thickness_mm:
        out.append("Zinken schmaler als die Materialdicke brechen leicht")
    return out


__all__ = ["BRIDGE_RANGE", "BentBoxSpec", "CUT_RANGE", "DEFAULT_KERF", "FINGER_RANGE",
           "KERF_RANGE", "PART_NAMES", "PATTERNS", "PATTERN_LABELS", "PITCH_RANGE", "Part",
           "RADIUS_RANGE", "SIZE_RANGE", "SPACING_RANGE", "THICKNESS_RANGE", "bentbox_shapes",
           "centered", "check", "describe", "layout", "notches", "parts", "side_counts",
           "wall_layout", "warnings"]
