"""Finger-joint box generator (xTool Studio „Box Generator“, boxes.py / MakerCase) – pure Python.

A closed or open-top box of outer (or inner) size W × D × H from sheet material
of thickness ``t`` is cut as six (five) flat panels whose edges interlock with
finger joints. The joints are derived from one ownership rule of the box shell,
so every finger of one panel meets a slot of the other and nothing overlaps:

* the 4 vertical edges (``t × t`` prisms over the full height, corners
  included) are split into an odd number of segments, front / back own the
  even ones (both ends, so the corners), left / right the odd ones;
* the 8 horizontal edges between a wall and the bottom / lid (length without
  the two corners) are split into an odd number of segments, the wall owns the
  even ones, bottom / lid the odd ones (inner tabs); without lid the top edges
  of the walls are straight;
* the inner face of every panel (``t`` from each edge) always belongs to it.

Each panel is the union of its inner rectangle and its owned edge segments,
grown by half the kerf (mitred, corners stay square) so that the burnt-away
material is added back: fingers come out ``kerf`` wider, slots ``kerf``
narrower and the parts fit as designed. The finger count of an edge is the
odd number closest to ``length / finger_mm`` (at least 3 when the edge is long
enough), so every edge of a length gets the same pattern on both panels.

Optional dividers (egg-crate inserts like boxes.py's *TrayInsert*): ``dividers_x``
walls parallel to the front (across the depth) and ``dividers_y`` walls parallel
to the sides (across the width) split the inside into equal compartments. Each
divider is the full inner length × inner height; where two cross they interlock
with half-lap slots of the material thickness (front-parallel dividers slotted
from the top, side-parallel ones from the bottom). They stand on the bottom and
press against the inner faces of the walls (no slots in walls or bottom, so the
box panels stay exactly as without dividers); the kerf is added back the same
way, so slots fit and the dividers press in.

The panels are laid out flat (shelf packing, tallest first, optionally turned
by 90°) with ``spacing_mm`` between them; :func:`box_shapes` returns them as
closed ``polygon`` objects in one group, ready for a cut layer. Pure Python
(shapely), no Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from shapely.geometry import Polygon, box as sbox
from shapely.ops import unary_union

from lumacut_canvas.model import Shape, new_id
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

SIZE_RANGE = (10.0, 1000.0)       # mm per axis (outer or inner)
THICKNESS_RANGE = (0.5, 12.0)     # mm sheet thickness
FINGER_RANGE = (2.0, 100.0)       # mm desired finger width
KERF_RANGE = (0.0, 1.0)           # mm burnt-away width of the cut line
SPACING_RANGE = (0.5, 50.0)       # mm between the panels on the sheet
DIVIDER_RANGE = (0, 20)           # dividers per direction
MIN_COMPARTMENT_MM = 5.0          # a compartment is at least this wide (and ≥ material)
DEFAULT_KERF = 0.1                # typical 5–20 W diode laser in 3 mm plywood

PANEL_NAMES = ("Vorne", "Hinten", "Links", "Rechts", "Boden", "Deckel")
DIVIDER_X_NAME = "Trennwand quer"     # parallel to the front (X), splits the depth
DIVIDER_Y_NAME = "Trennwand längs"    # parallel to the sides (Y), splits the width


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _count(v) -> int:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(v):
        return 0
    return int(_clamp(round(v), *DIVIDER_RANGE))


@dataclass(frozen=True)
class BoxSpec:
    width_mm: float = 100.0       # X (front edge)
    depth_mm: float = 80.0        # Y (side edge)
    height_mm: float = 50.0       # Z
    thickness_mm: float = 3.0
    finger_mm: float = 10.0
    kerf_mm: float = DEFAULT_KERF
    lid: bool = True              # False: open box (no top panel, straight top edges)
    inner: bool = False           # sizes are inside sizes (outer = inner + material)
    spacing_mm: float = 4.0
    x: float = 0.0                # top left corner of the layout
    y: float = 0.0
    dividers_x: int = 0           # dividers parallel to the front (split the depth)
    dividers_y: int = 0           # dividers parallel to the sides (split the width)

    def normalized(self) -> "BoxSpec":
        def f(v, rng, default):
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = default
            if not math.isfinite(v):
                v = default
            return round(_clamp(v, *rng), 3)
        return BoxSpec(width_mm=f(self.width_mm, SIZE_RANGE, 100.0),
                       depth_mm=f(self.depth_mm, SIZE_RANGE, 80.0),
                       height_mm=f(self.height_mm, SIZE_RANGE, 50.0),
                       thickness_mm=f(self.thickness_mm, THICKNESS_RANGE, 3.0),
                       finger_mm=f(self.finger_mm, FINGER_RANGE, 10.0),
                       kerf_mm=f(self.kerf_mm, KERF_RANGE, DEFAULT_KERF),
                       lid=bool(self.lid), inner=bool(self.inner),
                       spacing_mm=f(self.spacing_mm, SPACING_RANGE, 4.0),
                       x=float(self.x), y=float(self.y),
                       dividers_x=_count(self.dividers_x), dividers_y=_count(self.dividers_y))

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

    def compartments(self) -> tuple[float, float]:
        """Inner width and depth of one compartment between the dividers."""
        s = self.normalized()
        iw, id_, _ih = s.inside()
        t = s.thickness_mm
        return ((iw - s.dividers_y * t) / (s.dividers_y + 1),
                (id_ - s.dividers_x * t) / (s.dividers_x + 1))


def finger_count(length: float, finger: float, thickness: float) -> int:
    """Odd number of segments for an edge of ``length``: closest to
    ``length / finger``, at least 3 when each segment stays ≥ ``thickness``
    (and ≥ 1 mm), 1 (plain edge) when not even that fits."""
    if length <= 0:
        return 1
    n = max(1, int(round(length / max(finger, 1e-9))))
    if n % 2 == 0:
        lo, hi = n - 1, n + 1
        n = lo if abs(length / lo - finger) <= abs(length / hi - finger) else hi
    least = max(thickness, 1.0)
    while n > 1 and length / n < least - 1e-9:
        n -= 2
    if n < 3 and length / 3 >= least - 1e-9:
        n = 3
    return n


def _segments(a: float, b: float, n: int, owned: str) -> list[tuple[float, float]]:
    """Owned intervals of [a, b] split into ``n`` parts ("even", "odd" or "all")."""
    if owned == "all":
        return [(a, b)]
    step = (b - a) / n
    want = 0 if owned == "even" else 1
    return [(a + i * step, b if i == n - 1 else a + (i + 1) * step)
            for i in range(n) if i % 2 == want]


@dataclass(frozen=True)
class Panel:
    name: str
    size: tuple[float, float]          # (a, b) outer size of the panel before kerf
    outline: tuple[tuple[float, float], ...]   # closed ring in panel mm, y down, kerf applied
    fingers: dict                      # edge name -> segment count (for the readout / tests)


def _panel_polygon(a: float, b: float, t: float, edges: dict) -> Polygon:
    """Union of the inner rectangle and the owned strips.

    ``edges`` maps "bottom" / "top" (strips along u in v∈[0,t] / [b-t,b],
    u∈[t, a-t]) and "left" / "right" (strips along v in u∈[0,t] / [a-t,a],
    full height incl. corners or v∈[t, b-t]) to (start, end, n, owned).
    v grows upwards here (z of the box)."""
    parts = [sbox(t, t, a - t, b - t)]
    for name, (s0, s1, n, owned) in edges.items():
        for p, q in _segments(s0, s1, n, owned):
            if name == "bottom":
                parts.append(sbox(p, 0.0, q, t))
            elif name == "top":
                parts.append(sbox(p, b - t, q, b))
            elif name == "left":
                parts.append(sbox(0.0, p, t, q))
            else:
                parts.append(sbox(a - t, p, a, q))
    poly = unary_union(parts)
    if poly.geom_type != "Polygon":
        raise ValueError("Box-Teil zerfällt – Fingerbreite oder Materialdicke prüfen")
    return poly


def _ring(poly: Polygon, b: float) -> tuple[tuple[float, float], ...]:
    """Exterior ring, y flipped (screen: y down), collinear points removed, CCW on screen."""
    pts = [(round(x, 6), round(b - y, 6)) for x, y in poly.exterior.coords[:-1]]
    out: list[tuple[float, float]] = []
    n = len(pts)
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        cross = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])
        if abs(cross) > 1e-9 and math.dist(p0, p1) > 1e-9:
            out.append(p1)
    return tuple(out)


def divider_positions(spec: BoxSpec) -> tuple[list[float], list[float]]:
    """Centre lines of the dividers measured from the inner faces of the walls:
    (positions along X of the side-parallel dividers, positions along Y of the
    front-parallel dividers) – equal compartments."""
    s = spec.normalized()
    t = s.thickness_mm
    cw, cd = s.compartments()
    xs = [(i + 1) * cw + i * t + t / 2.0 for i in range(s.dividers_y)]
    ys = [(i + 1) * cd + i * t + t / 2.0 for i in range(s.dividers_x)]
    return xs, ys


def _divider_polygon(length: float, height: float, t: float, slots, from_top: bool) -> Polygon:
    """Divider rectangle (v up) with half-lap slots of width ``t`` at the centres ``slots``."""
    poly = sbox(0.0, 0.0, length, height)
    half = height / 2.0
    cuts = [sbox(c - t / 2.0, half if from_top else -1.0, c + t / 2.0,
                 height + 1.0 if from_top else half) for c in slots]
    if cuts:
        poly = poly.difference(unary_union(cuts))
    if poly.geom_type != "Polygon":
        raise ValueError("Trennwand zerfällt – weniger Trennwände oder dünneres Material")
    return poly


def _divider_specs(s: BoxSpec):
    iw, id_, ih = s.inside()
    t = s.thickness_mm
    if s.dividers_x == 0 and s.dividers_y == 0:
        return []
    cw, cd = s.compartments()
    least = max(MIN_COMPARTMENT_MM, t)
    if min(cw, cd) < least - 1e-9:
        raise ValueError(f"Zu viele Trennwände: die Fächer wären {cw:.1f} × {cd:.1f} mm "
                         f"(jedes Fach mindestens {least:.1f} mm)")
    xs, ys = divider_positions(s)
    out = []
    for i in range(s.dividers_x):
        out.append((f"{DIVIDER_X_NAME} {i + 1}", iw, ih, _divider_polygon(iw, ih, t, xs, True)))
    for i in range(s.dividers_y):
        out.append((f"{DIVIDER_Y_NAME} {i + 1}", id_, ih, _divider_polygon(id_, ih, t, ys, False)))
    return out


def panels(spec: BoxSpec) -> list[Panel]:
    """The flat panels of the box (front, back, left, right, bottom[, lid]) followed by
    the dividers (front-parallel first)."""
    s = spec.normalized()
    W, D, H = s.outer()
    t = s.thickness_mm
    if min(W, D, H) < 3 * t + 2.0:
        raise ValueError(f"Box {W:.1f} × {D:.1f} × {H:.1f} mm ist für {t:.1f} mm Material zu klein "
                         f"(jede Seite mindestens {3 * t + 2.0:.1f} mm)")
    f = s.finger_mm
    nx = finger_count(W - 2 * t, f, t)
    ny = finger_count(D - 2 * t, f, t)
    nz = finger_count(H, f, t)
    top_wall = "even" if s.lid else "all"
    out: list[tuple[str, float, float, dict]] = []
    wall_x = {"bottom": (t, W - t, nx, "even"), "top": (t, W - t, nx, top_wall),
              "left": (0.0, H, nz, "even"), "right": (0.0, H, nz, "even")}
    wall_y = {"bottom": (t, D - t, ny, "even"), "top": (t, D - t, ny, top_wall),
              "left": (0.0, H, nz, "odd"), "right": (0.0, H, nz, "odd")}
    plate = {"bottom": (t, W - t, nx, "odd"), "top": (t, W - t, nx, "odd"),
             "left": (t, D - t, ny, "odd"), "right": (t, D - t, ny, "odd")}
    out.append(("Vorne", W, H, wall_x))
    out.append(("Hinten", W, H, wall_x))
    out.append(("Links", D, H, wall_y))
    out.append(("Rechts", D, H, wall_y))
    out.append(("Boden", W, D, plate))
    if s.lid:
        out.append(("Deckel", W, D, plate))
    res = []
    k = s.kerf_mm / 2.0
    for name, a, b, edges in out:
        poly = _panel_polygon(a, b, t, edges)
        if k > 0:
            poly = poly.buffer(k, join_style=2, mitre_limit=10.0)
            poly = poly.simplify(0.0)
        poly = Polygon([(x + k, y + k) for x, y in poly.exterior.coords])
        res.append(Panel(name, (a, b), _ring(poly, b + 2 * k),
                         {e: v[2] if v[3] != "all" else 1 for e, v in edges.items()}))
    for name, a, b, poly in _divider_specs(s):
        if k > 0:
            poly = poly.buffer(k, join_style=2, mitre_limit=10.0).simplify(0.0)
        poly = Polygon([(x + k, y + k) for x, y in poly.exterior.coords])
        slots = s.dividers_y if name.startswith(DIVIDER_X_NAME) else s.dividers_x
        res.append(Panel(name, (a, b), _ring(poly, b + 2 * k), {"slots": slots}))
    return res


def _extent(pts) -> tuple[float, float]:
    return max(p[0] for p in pts), max(p[1] for p in pts)


def _shelf(items, width_limit: float, gap: float):
    """Shelf packing of (w, h) items in the given order; returns positions and size."""
    pos = []
    x = y = row_h = 0.0
    used_w = 0.0
    for w, h in items:
        if x > 0 and x + w > width_limit + 1e-9:
            y += row_h + gap
            x = row_h = 0.0
        pos.append((x, y))
        x += w + gap
        row_h = max(row_h, h)
        used_w = max(used_w, x - gap)
    return pos, used_w, y + row_h


def layout(spec: BoxSpec, width_limit: float = WORK_WIDTH_MM,
           height_limit: float = WORK_HEIGHT_MM):
    """Panels placed on the sheet: list of (panel name, ring in layout mm) and the
    layout size (w, h). Tries the panels as drawn and turned so their long side
    lies along X, tallest first; takes the smallest layout that fits (else the
    smallest one, for the error message)."""
    s = spec.normalized()
    ps = panels(s)
    best = None
    for turn in (False, True):
        rings = []
        for p in ps:
            ring = p.outline
            w, h = _extent(ring)
            if turn and h > w:
                ring = tuple((y, w - x) for x, y in ring)     # 90° on the sheet
            rings.append((p.name, ring))
        order = sorted(range(len(rings)), key=lambda i: -_extent(rings[i][1])[1])
        sizes = [_extent(rings[i][1]) for i in order]
        pos, lw, lh = _shelf(sizes, width_limit, s.spacing_mm)
        placed = [None] * len(rings)
        for (px, py), i in zip(pos, order):
            name, ring = rings[i]
            placed[i] = (name, tuple((x + px, y + py) for x, y in ring))
        fits = lw <= width_limit + 1e-6 and lh <= height_limit + 1e-6
        key = (not fits, lw * lh)
        if best is None or key < best[0]:
            best = (key, placed, (lw, lh), fits)
    return best[1], best[2], best[3]


def box_shapes(spec: BoxSpec, layer_id: str) -> list[Shape]:
    """The panels as closed ``polygon`` objects in one group, the layout's top left
    corner at (spec.x, spec.y). ``ValueError`` (German) when the box is too small
    or the layout does not fit on the work area."""
    s = spec.normalized()
    placed, (lw, lh), fits = layout(s)
    eps = 1e-6
    if (not fits or s.x < -eps or s.y < -eps or s.x + lw > WORK_WIDTH_MM + eps
            or s.y + lh > WORK_HEIGHT_MM + eps):
        raise ValueError(f"Die Box-Teile brauchen {lw:.0f} × {lh:.0f} mm und passen nicht auf die "
                         f"Arbeitsfläche ({WORK_WIDTH_MM:.0f} × {WORK_HEIGHT_MM:.0f} mm) – Box "
                         "kleiner machen oder Abstand verringern")
    group = new_id()
    out = []
    for _name, ring in placed:
        sh = Shape.from_points("polygon", [(x + s.x, y + s.y) for x, y in ring], layer_id)
        sh.groups = (group,)
        out.append(sh)
    return out


def centered(spec: BoxSpec, center: tuple[float, float] | None = None) -> BoxSpec:
    """Spec with X / Y so that the layout is centred on ``center`` (work area centre)."""
    s = spec.normalized()
    _placed, (lw, lh), _fits = layout(s)
    cx, cy = center or (WORK_WIDTH_MM / 2.0, WORK_HEIGHT_MM / 2.0)
    x = min(max(0.0, cx - lw / 2.0), max(0.0, WORK_WIDTH_MM - lw))
    y = min(max(0.0, cy - lh / 2.0), max(0.0, WORK_HEIGHT_MM - lh))
    return replace(s, x=x, y=y)


def describe(spec: BoxSpec) -> str:
    """German one-line readout: outer / inner size, panels, fingers, layout size."""
    s = spec.normalized()
    W, D, H = s.outer()
    iw, id_, ih = s.inside()
    ps = panels(s)
    t = s.thickness_mm
    nx = finger_count(W - 2 * t, s.finger_mm, t)
    ny = finger_count(D - 2 * t, s.finger_mm, t)
    nz = finger_count(H, s.finger_mm, t)
    _placed, (lw, lh), _fits = layout(s)
    text = (f"Außen {W:.1f} × {D:.1f} × {H:.1f} mm, innen {iw:.1f} × {id_:.1f} × {ih:.1f} mm · "
            f"{len(ps)} Teile ({'mit Deckel' if s.lid else 'offen'}) · Zinken {nx} / {ny} / {nz} "
            f"(Breite / Tiefe / Höhe) · Platz auf dem Material {lw:.0f} × {lh:.0f} mm")
    if s.dividers_x or s.dividers_y:
        cw, cd = s.compartments()
        n = (s.dividers_x + 1) * (s.dividers_y + 1)
        text += (f" · Trennwände {s.dividers_x} quer / {s.dividers_y} längs (gesteckt): {n} Fächer "
                 f"je {cw:.1f} × {cd:.1f} mm")
    return text


__all__ = ["BoxSpec", "DEFAULT_KERF", "DIVIDER_RANGE", "DIVIDER_X_NAME", "DIVIDER_Y_NAME",
           "FINGER_RANGE", "MIN_COMPARTMENT_MM", "KERF_RANGE", "PANEL_NAMES", "Panel",
           "SIZE_RANGE", "SPACING_RANGE", "THICKNESS_RANGE", "box_shapes", "centered", "describe",
           "divider_positions", "finger_count", "layout", "panels"]
