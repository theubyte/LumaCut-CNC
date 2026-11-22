"""Living hinge (flex / kerf-bend pattern) generator – pure Python.

A field of staggered slits lets stiff sheet material (3 mm plywood, MDF,
acrylic with care) bend like a hinge – the rounded corners of a box, a
bracelet, a book cover. LightBurn users draw the pattern by hand or import it
from boxes.py / online generators; xTool Creative Space users import it too.

The field is ``width_mm × height_mm``. The slits run along the bend axis
(vertical by default – the sheet bends around a vertical axis; ``horizontal``
turns them by 90°). Seen across the bend there are ``columns`` slit lines
``pitch_mm`` apart, centred in the field. Lines alternate:

* even lines: ``n`` slits of the same length with a bridge of ``bridge_mm``
  between them and at both ends (the slit length is stretched so that the
  line fills the field exactly – nearest count to the wished ``cut_mm``);
* odd lines: the same slits shifted by half a period – their bridges lie in
  the middle of the neighbours' slits, and at both ends half slits run to the
  edge of the field (``open_edges``; otherwise they stop one bridge before it).

Patterns: ``lines`` (straight slits, open paths), ``wave`` (each slit an
S-curve, more twist, still open paths) and ``diamond`` (closed rhombus holes,
the most flexible; the half holes at the edges are open paths ending on the
edge). An optional ``frame`` (closed rectangle) cuts the part out, with
``margin_mm`` of plain material on both sides across the bend.

Free shapes: ``outline`` holds closed rings (even-odd, like an image mask) in
coordinates normalised to the field box (0…1 in X and Y, y down). With an
outline the pattern is clipped to that shape instead of the rectangle – a
circle, an oval bracelet end, a lamp-shade arc, letters. ``open_edges``: the
cuts run out to the outline (open half slits / half holes ending on it);
otherwise every cut keeps one ``bridge_mm`` from the outline (closed holes are
cut back to a closed hole). Pieces shorter than ``MIN_SLIT`` are left out. The
outline itself is not cut (the selected shape stays the part's contour), so
``frame`` / ``margin_mm`` do not apply; stretching the field stretches the
outline with it.

Readout: number of slits, cut length and the bend the field allows –
a hinge of width ``b`` across the bend wraps an angle θ around the neutral
radius ``b / θ`` (inner radius ``b / θ − t / 2``); :func:`width_for` is the
inverse (field width for a radius and an angle).

Pure Python, no Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from shapely.geometry import GeometryCollection, LineString, MultiLineString, Polygon
from shapely.ops import linemerge

from lumacut_canvas.model import Shape, new_id
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

SIZE_RANGE = (5.0, 1000.0)        # mm field width / height
CUT_RANGE = (2.0, 500.0)          # mm wished slit length
BRIDGE_RANGE = (0.5, 50.0)        # mm material left between two slits of one line
PITCH_RANGE = (0.5, 20.0)         # mm distance between neighbouring slit lines
THICKNESS_RANGE = (0.5, 12.0)     # mm sheet thickness (readout / bend helper only)
MARGIN_RANGE = (0.0, 500.0)       # mm plain material beside the field (frame only)
PATTERNS = ("lines", "wave", "diamond")
PATTERN_LABELS = {"lines": "Gerade Schlitze", "wave": "Wellen", "diamond": "Rauten"}
MAX_SLITS = 6000                  # more objects make the canvas slow – refuse
MIN_SLIT = 0.8                    # mm: shorter edge slits are left out
WAVE_AMPLITUDE = 0.3              # × pitch, so neighbouring waves stay ≥ 0.4 × pitch apart
DIAMOND_HALF = 0.35               # × pitch half width of a diamond hole
STEP_MM = 0.5                     # chord length of the wave polylines
MAX_OUTLINE_POINTS = 4000         # points of a free outline (kept in the project file)
FULL_BOX = 0.999                  # outline area ≥ this × field box: a plain rectangle


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


@dataclass(frozen=True)
class HingeSpec:
    width_mm: float = 60.0        # X size of the field
    height_mm: float = 50.0       # Y size of the field
    pattern: str = "lines"
    horizontal: bool = False      # False: slits along Y (bend around a vertical axis)
    cut_mm: float = 20.0          # wished slit length
    bridge_mm: float = 3.0        # bridge between slits
    pitch_mm: float = 2.0         # distance between slit lines
    thickness_mm: float = 3.0
    open_edges: bool = True       # half slits of the odd lines run out to the edge
    frame: bool = False           # cut the part out (closed rectangle)
    margin_mm: float = 10.0       # plain material on both sides across the bend (frame only)
    x: float = 0.0                # top left corner of the part (frame or field)
    y: float = 0.0
    outline: tuple = ()           # free shape: rings normalised to the field box (even-odd)

    def normalized(self) -> "HingeSpec":
        def f(v, rng, default):
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = default
            if not math.isfinite(v):
                v = default
            return round(_clamp(v, *rng), 3)
        pattern = self.pattern if self.pattern in PATTERNS else "lines"
        return HingeSpec(width_mm=f(self.width_mm, SIZE_RANGE, 60.0),
                         height_mm=f(self.height_mm, SIZE_RANGE, 50.0),
                         pattern=pattern, horizontal=bool(self.horizontal),
                         cut_mm=f(self.cut_mm, CUT_RANGE, 20.0),
                         bridge_mm=f(self.bridge_mm, BRIDGE_RANGE, 3.0),
                         pitch_mm=f(self.pitch_mm, PITCH_RANGE, 2.0),
                         thickness_mm=f(self.thickness_mm, THICKNESS_RANGE, 3.0),
                         open_edges=bool(self.open_edges), frame=bool(self.frame),
                         margin_mm=f(self.margin_mm, MARGIN_RANGE, 10.0),
                         x=float(self.x), y=float(self.y),
                         outline=normalize_outline(self.outline))

    @property
    def clipped(self) -> bool:
        """True: the pattern is clipped to a free outline (no rectangle frame)."""
        return bool(self.outline)

    def across(self) -> float:
        """Field size across the bend (perpendicular to the slits)."""
        s = self.normalized()
        return s.height_mm if s.horizontal else s.width_mm

    def along(self) -> float:
        """Field size along the slits (the bend axis)."""
        s = self.normalized()
        return s.width_mm if s.horizontal else s.height_mm

    def part_size(self) -> tuple[float, float]:
        """(w, h) of the inserted part: the frame with its margins, else the field."""
        s = self.normalized()
        m = s.margin_mm if s.frame and not s.outline else 0.0
        if s.horizontal:
            return s.width_mm, s.height_mm + 2 * m
        return s.width_mm + 2 * m, s.height_mm


@dataclass(frozen=True)
class Slit:
    """One cut in field coordinates (u across the bend, v along the slits)."""

    points: tuple[tuple[float, float], ...]
    closed: bool


def normalize_outline(raw) -> tuple:
    """Clean outline: tuple of rings (≥ 3 finite points, 0…1, rounded), empty when unusable."""
    rings = []
    try:
        items = list(raw or ())
    except TypeError:
        return ()
    for ring in items:
        pts = []
        try:
            for p in ring:
                x, y = float(p[0]), float(p[1])
                if not (math.isfinite(x) and math.isfinite(y)):
                    raise ValueError
                pts.append((round(_clamp(x, 0.0, 1.0), 6), round(_clamp(y, 0.0, 1.0), 6)))
        except (TypeError, ValueError, IndexError):
            continue
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts.pop()
        if len(pts) >= 3:
            rings.append(tuple(pts))
    return tuple(rings)


def _even_odd(rings) -> Polygon:
    area = Polygon()
    for ring in rings:
        if len(ring) >= 3:
            area = area.symmetric_difference(Polygon(ring).buffer(0))
    return area


def outline_area(spec: HingeSpec):
    """Even-odd area of the outline in part coordinates (top left 0 / 0), None without."""
    s = spec.normalized()
    if not s.outline:
        return None
    w, h = s.width_mm, s.height_mm
    return _even_odd([[(u * w, v * h) for u, v in ring] for ring in s.outline])


def outline_from_rings(rings) -> tuple[tuple[float, float, float, float], tuple]:
    """World rings (mm, closed shapes, even-odd) → ((x0, y0, w, h), normalised outline).

    The outline is empty when the rings fill their bounding box (a plain rectangle –
    the old rectangular field is exact) or have no area. Very detailed outlines are
    simplified until they have at most ``MAX_OUTLINE_POINTS`` points."""
    rings = [[(float(x), float(y)) for x, y in r] for r in rings if len(r) >= 3]
    area = _even_odd(rings)
    if area.is_empty or area.area <= 1e-9:
        return (0.0, 0.0, 0.0, 0.0), ()
    x0, y0, x1, y1 = area.bounds
    w, h = x1 - x0, y1 - y0
    if w <= 1e-9 or h <= 1e-9 or area.area >= FULL_BOX * w * h:
        return (x0, y0, w, h), ()
    tol = 0.0
    while True:
        geo = area.simplify(tol, preserve_topology=True) if tol else area
        polys = [geo] if isinstance(geo, Polygon) else [g for g in getattr(geo, "geoms", ())
                                                      if isinstance(g, Polygon)]
        out = []
        for p in polys:
            for ring in (p.exterior, *p.interiors):
                pts = [((px - x0) / w, (py - y0) / h) for px, py in ring.coords]
                out.append(pts)
        if sum(len(r) for r in out) <= MAX_OUTLINE_POINTS or tol > 5.0:
            return (x0, y0, w, h), normalize_outline(out)
        tol = 0.02 if not tol else tol * 2.0


def columns(spec: HingeSpec) -> list[float]:
    """u positions of the slit lines, ``pitch`` apart and centred in the field
    (at least half a pitch from the field edges)."""
    s = spec.normalized()
    U, p = s.across(), s.pitch_mm
    m = max(1, int(U / p + 1e-9))
    u0 = (U - (m - 1) * p) / 2.0
    return [round(u0 + i * p, 6) for i in range(m)]


def slit_plan(spec: HingeSpec) -> tuple[int, float]:
    """(slits per even line, stretched slit length) – the count nearest to the
    wished length so the line with its bridges fills the field exactly."""
    s = spec.normalized()
    V, G, L = s.along(), s.bridge_mm, s.cut_mm
    n = max(1, int(round((V - G) / (L + G))))
    while n > 1 and (V - (n + 1) * G) / n < 1.0:
        n -= 1
    la = (V - (n + 1) * G) / n
    if la < 1.0:
        raise ValueError(f"Feld {V:.1f} mm ist für Steg {G:.1f} mm zu kurz – Feld länger oder Steg "
                         "kürzer machen")
    return n, la


def _intervals(spec: HingeSpec, odd: bool) -> list[tuple[float, float, int]]:
    """Slit intervals [a, b] along v of one line; third item: -1 runs out at v=0,
    +1 runs out at v=V, 0 inside."""
    s = spec.normalized()
    V, G = s.along(), s.bridge_mm
    n, la = slit_plan(s)
    if not odd:
        return [(G + k * (la + G), G + k * (la + G) + la, 0) for k in range(n)]
    centres = [G + la / 2.0 + k * (la + G) for k in range(n)]
    out = []
    first_end = centres[0] - G / 2.0
    last_start = centres[-1] + G / 2.0
    if s.open_edges:
        out.append((0.0, first_end, -1))
    elif first_end - G >= MIN_SLIT:
        out.append((G, first_end, 0))
    for k in range(n - 1):
        out.append((centres[k] + G / 2.0, centres[k + 1] - G / 2.0, 0))
    if s.open_edges:
        out.append((last_start, V, 1))
    elif V - G - last_start >= MIN_SLIT:
        out.append((last_start, V - G, 0))
    return out


def _wave(u: float, a: float, b: float, amp: float, la: float) -> tuple[tuple[float, float], ...]:
    halves = max(1, int(round(2.0 * (b - a) / max(la, 1e-9))))
    n = max(8 * halves, int(math.ceil((b - a) / STEP_MM)))
    pts = []
    for i in range(n + 1):
        t = i / n
        pts.append((round(u + amp * math.sin(math.pi * halves * t), 6), round(a + (b - a) * t, 6)))
    return tuple(pts)


def _diamond(u: float, a: float, b: float, edge: int, hw: float, la: float, V: float):
    """Rhombus over [a, b]; at an open edge the half hole as an open path ending on the edge."""
    if edge == 0:
        mid = (a + b) / 2.0
        return Slit(((u, a), (u + hw, mid), (u, b), (u - hw, mid)), True)
    # virtual full hole of length la that the edge cuts off
    if edge < 0:
        lo, hi = b - la, b
    else:
        lo, hi = a, a + la
    mid = (lo + hi) / 2.0
    e = 0.0 if edge < 0 else V
    tip = hi if edge < 0 else lo
    # half width where the rhombus meets the edge
    w_edge = hw * max(0.0, 1.0 - abs(e - mid) / (la / 2.0))
    if abs(mid - e) < 1e-9 or w_edge <= 1e-9:
        pts = ((u - hw, e), (u, tip), (u + hw, e)) if w_edge > 1e-9 else ((u, e), (u, tip))
    else:
        side = mid if (edge < 0 and mid > 0) or (edge > 0 and mid < V) else e
        if side == e:
            pts = ((u - w_edge, e), (u, tip), (u + w_edge, e))
        else:
            pts = ((u - w_edge, e), (u - hw, mid), (u, tip), (u + hw, mid), (u + w_edge, e))
    return Slit(tuple((round(x, 6), round(y, 6)) for x, y in pts), False)


def slits(spec: HingeSpec) -> list[Slit]:
    """All cuts of the field in field coordinates (u across, v along)."""
    s = spec.normalized()
    n, la = slit_plan(s)
    V, p = s.along(), s.pitch_mm
    cols = columns(s)
    out: list[Slit] = []
    for i, u in enumerate(cols):
        for a, b, edge in _intervals(s, odd=bool(i % 2)):
            if b - a < MIN_SLIT - 1e-9:
                continue
            if s.pattern == "wave":
                out.append(Slit(_wave(u, a, b, WAVE_AMPLITUDE * p, la), False))
            elif s.pattern == "diamond":
                out.append(_diamond(u, a, b, edge, DIAMOND_HALF * p, la, V))
            else:
                out.append(Slit(((u, round(a, 6)), (u, round(b, 6))), False))
        if len(out) > MAX_SLITS:
            raise ValueError(f"Mehr als {MAX_SLITS} Schlitze – Feld kleiner, Linienabstand oder "
                             "Schlitzlänge größer machen")
    return out


def cut_length(spec: HingeSpec) -> float:
    """Total length of all hinge cuts (without the frame, clipped to an outline), mm."""
    total = 0.0
    for pts, closed in _field_cuts(spec):
        pts = list(pts) + ([pts[0]] if closed else [])
        total += sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
    return total


def _to_xy(s: HingeSpec, u: float, v: float) -> tuple[float, float]:
    """Field (u, v) to part coordinates (frame margin included), y down."""
    m = s.margin_mm if s.frame else 0.0
    if s.horizontal:
        return s.x + v, s.y + m + u
    return s.x + m + u, s.y + v


def fits(spec: HingeSpec) -> bool:
    s = spec.normalized()
    w, h = s.part_size()
    return w <= WORK_WIDTH_MM + 1e-6 and h <= WORK_HEIGHT_MM + 1e-6


def _lines(geo) -> list:
    if geo.is_empty:
        return []
    if isinstance(geo, LineString):
        return [geo]
    if isinstance(geo, MultiLineString):
        merged = linemerge(geo)
        return [merged] if isinstance(merged, LineString) else list(merged.geoms)
    if isinstance(geo, GeometryCollection):
        return [g for part in geo.geoms for g in _lines(part)]
    return []


def _polys(geo) -> list:
    if geo.is_empty:
        return []
    if isinstance(geo, Polygon):
        return [geo]
    return [g for part in getattr(geo, "geoms", ()) for g in _polys(part)]


def _pts(coords) -> tuple:
    return tuple((round(float(x), 6), round(float(y), 6)) for x, y in coords)


def clip_cuts(spec: HingeSpec, cuts) -> list:
    """Cuts (part coordinates, top left 0 / 0) clipped to the spec's outline – see the
    module doc. Without an outline the cuts are returned unchanged."""
    s = spec.normalized()
    area = outline_area(s)
    if area is None:
        return list(cuts)
    region = area if s.open_edges else area.buffer(-s.bridge_mm, join_style=2)
    if region.is_empty:
        return []
    prepared = region.buffer(0)
    out = []
    for pts, closed in cuts:
        if closed:
            hole = Polygon(pts)
            if prepared.contains(hole):
                out.append((tuple(pts), True))
                continue
            if not prepared.intersects(hole):
                continue
            if s.open_edges:
                ring = LineString(list(pts) + [pts[0]])
                for ln in _lines(ring.intersection(prepared)):
                    if ln.length >= MIN_SLIT - 1e-9:
                        out.append((_pts(ln.coords), False))
            else:
                for poly in _polys(hole.intersection(prepared)):
                    if poly.length >= 2 * MIN_SLIT and poly.area > 1e-4:
                        c = list(poly.exterior.coords)[:-1]
                        out.append((_pts(c), True))
            continue
        line = LineString(pts)
        if prepared.contains(line):
            out.append((tuple(pts), False))
            continue
        for ln in _lines(line.intersection(prepared)):
            if ln.length >= MIN_SLIT - 1e-9:
                out.append((_pts(ln.coords), False))
    return out


def _field_cuts(spec: HingeSpec) -> list:
    """Hinge cuts (no frame) in part coordinates with the top left at 0 / 0, clipped to
    the outline when there is one."""
    s = replace(spec.normalized(), x=0.0, y=0.0)
    cuts = [(tuple(_to_xy(s, u, v) for u, v in sl.points), sl.closed) for sl in slits(s)]
    return clip_cuts(s, cuts) if s.outline else cuts


def cut_center_offset(spec: HingeSpec) -> tuple[float, float]:
    """Centre of the cuts' bounding box minus the centre of the part box (mm). Zero for
    rectangular fields; with a free outline the clipped cuts may sit off-centre."""
    s = spec.normalized()
    w, h = s.part_size()
    cuts = part_cuts(replace(s, x=0.0, y=0.0))
    xs = [x for pts, _c in cuts for x, _y in pts]
    ys = [y for pts, _c in cuts for _x, y in pts]
    if not xs:
        return 0.0, 0.0
    return (min(xs) + max(xs)) / 2.0 - w / 2.0, (min(ys) + max(ys)) / 2.0 - h / 2.0


def part_cuts(spec: HingeSpec):
    """All cuts in part coordinates (top left at spec.x / spec.y): list of
    (points, closed) – the slits (clipped to a free outline), then the frame (when on;
    never with an outline)."""
    s = spec.normalized()
    if s.outline:
        return [(tuple((x + s.x, y + s.y) for x, y in pts), closed)
                for pts, closed in _field_cuts(s)]
    out = [(tuple(_to_xy(s, u, v) for u, v in sl.points), sl.closed) for sl in slits(s)]
    if s.frame:
        w, h = s.part_size()
        out.append((((s.x, s.y), (s.x + w, s.y), (s.x + w, s.y + h), (s.x, s.y + h)), True))
    return out


def hinge_shapes(spec: HingeSpec, layer_id: str) -> list[Shape]:
    """Slits (open ``path`` / closed ``polygon`` objects) and the optional frame
    (closed ``polygon``) in one group, the part's top left corner at
    (spec.x, spec.y). ``ValueError`` (German) when the field is too short, has
    too many slits or does not fit on the work area."""
    s = spec.normalized()
    w, h = s.part_size()
    eps = 1e-6
    if (not fits(s) or s.x < -eps or s.y < -eps or s.x + w > WORK_WIDTH_MM + eps
            or s.y + h > WORK_HEIGHT_MM + eps):
        raise ValueError(f"Das Scharnier braucht {w:.0f} × {h:.0f} mm und passt nicht auf die "
                         f"Arbeitsfläche ({WORK_WIDTH_MM:.0f} × {WORK_HEIGHT_MM:.0f} mm)")
    cuts = part_cuts(s)
    if not cuts:
        raise ValueError("Die Form ist für dieses Muster zu klein oder zu schmal – Steg / "
                         "Linienabstand kleiner machen")
    group = new_id()
    out: list[Shape] = []
    for pts, closed in cuts:
        sh = Shape.from_points("polygon" if closed else "path", list(pts), layer_id)
        sh.groups = (group,)
        out.append(sh)
    return out


def centered(spec: HingeSpec, center: tuple[float, float] | None = None) -> HingeSpec:
    """Spec with X / Y so that the part is centred on ``center`` (work area centre),
    kept inside the work area."""
    s = spec.normalized()
    w, h = s.part_size()
    cx, cy = center or (WORK_WIDTH_MM / 2.0, WORK_HEIGHT_MM / 2.0)
    x = min(max(0.0, cx - w / 2.0), max(0.0, WORK_WIDTH_MM - w))
    y = min(max(0.0, cy - h / 2.0), max(0.0, WORK_HEIGHT_MM - h))
    return replace(s, x=x, y=y)


def bend_radius(across_mm: float, angle_deg: float, thickness_mm: float) -> float:
    """Inner bend radius when a field ``across_mm`` wide wraps ``angle_deg``
    (neutral fibre in the middle of the sheet); 0 when it does not reach."""
    theta = math.radians(max(angle_deg, 1e-9))
    return max(0.0, across_mm / theta - thickness_mm / 2.0)


def width_for(radius_mm: float, angle_deg: float, thickness_mm: float) -> float:
    """Field width across the bend for an inner radius and an angle (arc of the
    neutral fibre)."""
    return (max(radius_mm, 0.0) + thickness_mm / 2.0) * math.radians(max(angle_deg, 0.0))


def describe(spec: HingeSpec) -> str:
    """German one-line readout: lines, slits, cut length, bend, part size."""
    s = spec.normalized()
    n, la = slit_plan(s)
    cols = columns(s)
    cuts = _field_cuts(s)
    if s.outline and not cuts:
        raise ValueError("Die Form ist für dieses Muster zu klein oder zu schmal – Steg / "
                         "Linienabstand kleiner machen")
    w, h = s.part_size()
    U, t = s.across(), s.thickness_mm
    text = (f"{PATTERN_LABELS[s.pattern]}: {len(cols)} Linien, {len(cuts)} Schnitte "
            f"(Schlitz {la:.1f} mm, Steg {s.bridge_mm:.1f} mm) · Schnittlänge "
            f"{cut_length(s) / 1000.0:.2f} m · Biegung 90° um Innenradius ≈ "
            f"{bend_radius(U, 90, t):.1f} mm, 180° um ≈ {bend_radius(U, 180, t):.1f} mm · "
            f"Teil {w:.1f} × {h:.1f} mm")
    if s.outline:
        text += " · auf die Form zugeschnitten" + (
            " (Schnitte bis an den Umriss)" if s.open_edges else
            f" ({s.bridge_mm:.1f} mm Steg zum Umriss)")
    return text


def warnings(spec: HingeSpec) -> list[str]:
    """German hints for fragile or stiff settings."""
    s = spec.normalized()
    out = []
    # narrowest material between two lines: waves bulge towards each other, a diamond is
    # widest where the neighbour line has its bridge
    gap = s.pitch_mm - (2 * WAVE_AMPLITUDE * s.pitch_mm if s.pattern == "wave" else
                        DIAMOND_HALF * s.pitch_mm if s.pattern == "diamond" else 0.0)
    if gap < 0.8:
        out.append(f"Stege zwischen den Linien nur {gap:.1f} mm – können verbrennen oder brechen "
                   "(Linienabstand größer)")
    if s.bridge_mm < 1.5:
        out.append("Brücken unter 1,5 mm reißen leicht")
    try:
        _n, la = slit_plan(s)
    except ValueError:
        return out
    if la < 3 * s.bridge_mm:
        out.append("Schlitze kurz im Vergleich zum Steg – das Scharnier wird steif "
                   "(Schlitz länger oder Steg kürzer)")
    if s.pitch_mm > 2 * s.thickness_mm:
        out.append("Linienabstand größer als die doppelte Materialdicke – biegt sich schwer")
    return out


__all__ = ["BRIDGE_RANGE", "CUT_RANGE", "HingeSpec", "MARGIN_RANGE", "MAX_OUTLINE_POINTS",
           "MAX_SLITS", "PATTERNS", "PATTERN_LABELS", "PITCH_RANGE", "SIZE_RANGE", "Slit",
           "THICKNESS_RANGE", "bend_radius", "centered", "clip_cuts", "columns",
           "cut_center_offset", "cut_length", "describe", "fits", "hinge_shapes",
           "normalize_outline", "outline_area", "outline_from_rings", "part_cuts", "slit_plan",
           "slits", "warnings", "width_for"]
