"""Job time estimate and framing G-code.

:func:`estimate_gcode` simulates Marlin's planner closely enough for a
useful preview: per-segment trapezoid profiles with the machine's
acceleration, junction-deviation corner speeds and forward/backward speed
passes (like LightBurn's "Total estimated time" in Preview). Defaults are
the LumaCut values from docs/MASCHINE.md: XY 150 mm/s max, 500 mm/s²,
Z 9 mm/s, rapid F9000 when a G0 carries no F (set by the Pi).

Homing, probing/focus and parking run on the Pi before/after the job and
are *not* included.

:func:`frame_gcode` traces the job's bounding box (or its convex
"rubber band" hull) with the laser off, like LightBurn's Frame buttons and
xTool's Framing.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, to_machine

_WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")

ACCEL_XY = 500.0          # mm/s²
MAX_XY = 150.0            # mm/s
MAX_Z = 9.0               # mm/s
RAPID_FEED = 9000.0       # mm/min, Pi default for G0 without F
JUNCTION_DEVIATION = 0.013  # mm (Marlin default)
FRAME_FEED = 3000.0       # mm/min

_MIN_X, _MIN_Y = to_machine(0.0, 0.0)
_MAX_X, _MAX_Y = to_machine(WORK_WIDTH_MM, WORK_HEIGHT_MM)


@dataclass
class JobEstimate:
    cut_length_mm: float = 0.0
    travel_length_mm: float = 0.0
    cut_time_s: float = 0.0
    travel_time_s: float = 0.0
    dwell_time_s: float = 0.0
    moves: int = 0
    bounds: tuple[float, float, float, float] | None = None  # laser-on, machine mm

    @property
    def total_time_s(self) -> float:
        return self.cut_time_s + self.travel_time_s + self.dwell_time_s

    def summary(self) -> str:
        return (f"≈ {format_duration(self.total_time_s)} · Schnitt {self.cut_length_mm / 1000:.2f} m "
                f"· Leerfahrt {self.travel_length_mm / 1000:.2f} m")


def format_duration(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min {sec:02d} s"
    return f"{sec} s"


@dataclass
class _Seg:
    length: float
    vmax: float          # mm/s
    unit: tuple[float, float, float]
    cutting: bool
    entry: float = 0.0
    entry_max: float = 0.0
    extra: dict = field(default_factory=dict)


def _junction_speed(prev: _Seg, nxt: _Seg, accel: float, jd: float) -> float:
    cos_theta = -sum(a * b for a, b in zip(prev.unit, nxt.unit))
    cos_theta = max(-1.0, min(1.0, cos_theta))
    if cos_theta > 0.999999:  # full reversal
        return 0.0
    sin_d2 = math.sqrt(max(0.0, 0.5 * (1.0 - cos_theta)))
    if sin_d2 > 0.999999:      # straight line
        return min(prev.vmax, nxt.vmax)
    v = math.sqrt(accel * jd * sin_d2 / (1.0 - sin_d2))
    return min(v, prev.vmax, nxt.vmax)


def _seg_time(L: float, v0: float, v1: float, vmax: float, a: float) -> float:
    if L <= 0:
        return 0.0
    vp2 = (2 * a * L + v0 * v0 + v1 * v1) / 2
    vp = math.sqrt(max(vp2, 0.0))
    if vp <= vmax:
        return max(0.0, (vp - v0) / a) + max(0.0, (vp - v1) / a)
    d_acc = (vmax * vmax - v0 * v0) / (2 * a)
    d_dec = (vmax * vmax - v1 * v1) / (2 * a)
    return (vmax - v0) / a + (vmax - v1) / a + (L - d_acc - d_dec) / vmax


def estimate_gcode(gcode: str, accel: float = ACCEL_XY, max_xy: float = MAX_XY,
                   max_z: float = MAX_Z, rapid_feed: float = RAPID_FEED,
                   junction_deviation: float = JUNCTION_DEVIATION) -> JobEstimate:
    """Estimate run time of Marlin laser G-code (G0/G1/G4, G90/G91, M3 I/M5 I)."""
    est = JobEstimate()
    pos = [0.0, 0.0, 0.0]
    have_xy = False
    absolute = True
    feed = None
    inline = False
    segs: list[_Seg] = []
    xs: list[float] = []
    ys: list[float] = []

    for raw in gcode.splitlines():
        line = raw.split(";", 1)[0].strip().upper()
        if not line:
            continue
        if line in ("G90",):
            absolute = True
            continue
        if line in ("G91",):
            absolute = False
            continue
        if line.startswith("M3"):
            inline = True
            continue
        if line.startswith("M5"):
            inline = False
            continue
        words = dict(_WORD.findall(line.replace("M3 I", "M3")))
        g = words.get("G")
        if g is None:
            continue
        g = int(float(g))
        if g == 4:
            est.dwell_time_s += float(words.get("P", 0)) / 1000.0 + float(words.get("S", 0))
            continue
        if g not in (0, 1):
            continue
        tgt = list(pos)
        for k, axis in enumerate("XYZ"):
            if axis in words:
                v = float(words[axis])
                tgt[k] = v if absolute else pos[k] + v
        if "F" in words and g == 1:
            feed = float(words["F"])
        if not have_xy:
            # First positioning move: start point unknown, count as 0 length.
            if "X" in words or "Y" in words:
                have_xy = True
            pos = tgt
            continue
        d = [t - p for t, p in zip(tgt, pos)]
        L = math.sqrt(sum(c * c for c in d))
        pos = tgt
        if L <= 1e-9:
            continue
        f = (float(words["F"]) if "F" in words else rapid_feed) if g == 0 else (feed or rapid_feed)
        vmax = min(f / 60.0, max_xy)
        if abs(d[2]) > 1e-9:
            vmax = min(vmax, max_z * L / abs(d[2]))
        power = float(words.get("S", 0)) if g == 1 else 0.0
        cutting = g == 1 and inline and power > 0
        segs.append(_Seg(L, vmax, (d[0] / L, d[1] / L, d[2] / L), cutting))
        if cutting:
            xs += [tgt[0] - d[0], tgt[0]]
            ys += [tgt[1] - d[1], tgt[1]]

    # Junction limits, then backward and forward passes (Marlin planner style).
    n = len(segs)
    for i in range(n):
        segs[i].entry_max = 0.0 if i == 0 else _junction_speed(
            segs[i - 1], segs[i], accel, junction_deviation)
    exit_v = [0.0] * n
    nxt_entry = 0.0
    for i in range(n - 1, -1, -1):
        s = segs[i]
        exit_v[i] = nxt_entry
        s.entry = min(s.entry_max, math.sqrt(nxt_entry ** 2 + 2 * accel * s.length))
        nxt_entry = s.entry
    v = 0.0
    for i in range(n):
        s = segs[i]
        s.entry = min(s.entry, v)
        v_exit = min(exit_v[i], math.sqrt(s.entry ** 2 + 2 * accel * s.length))
        t = _seg_time(s.length, s.entry, v_exit, s.vmax, accel)
        if s.cutting:
            est.cut_length_mm += s.length
            est.cut_time_s += t
        else:
            est.travel_length_mm += s.length
            est.travel_time_s += t
        v = v_exit
        if i + 1 < n:
            exit_v[i] = v_exit
    est.moves = n
    if xs:
        est.bounds = (min(xs), min(ys), max(xs), max(ys))
    return est


# --- Framing -------------------------------------------------------------

def job_bounds(layers) -> tuple[float, float, float, float] | None:
    """Bounding box (machine mm) of all polylines of the given ``JobLayer`` list."""
    pts = [p for layer in layers for poly in layer.polylines for p in poly]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def convex_hull(points) -> list[tuple[float, float]]:
    pts = sorted(set((round(x, 4), round(y, 4)) for x, y in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _clamp_xy(x: float, y: float) -> tuple[float, float]:
    return min(max(x, _MIN_X), _MAX_X), min(max(y, _MIN_Y), _MAX_Y)


def frame_gcode(layers, mode: str = "box", feed_mm_min: float = FRAME_FEED,
                margin_mm: float = 0.0, loops: int = 1) -> str:
    """Laser-off G-code that traces the job outline.

    ``mode``: ``"box"`` (bounding box) or ``"hull"`` (rubber band).
    Only G0/G1 with ``S0`` and no ``M3 I`` – the laser cannot fire.
    """
    if mode not in ("box", "hull"):
        raise ValueError("mode must be 'box' or 'hull'")
    if not 1 <= loops <= 10:
        raise ValueError("loops must be 1..10")
    if not 60 <= feed_mm_min <= 9000:
        raise ValueError("feed must be 60..9000 mm/min")
    b = job_bounds(layers)
    if b is None:
        raise ValueError("Keine sichtbaren Objekte zum Umfahren")
    if mode == "box":
        x0, y0, x1, y1 = b[0] - margin_mm, b[1] - margin_mm, b[2] + margin_mm, b[3] + margin_mm
        ring = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    else:
        ring = convex_hull(p for layer in layers for poly in layer.polylines for p in poly)
        if margin_mm and len(ring) >= 3:
            cx = sum(p[0] for p in ring) / len(ring)
            cy = sum(p[1] for p in ring) / len(ring)
            ring = [(x + math.copysign(margin_mm, x - cx) if x != cx else x,
                     y + math.copysign(margin_mm, y - cy) if y != cy else y) for x, y in ring]
    ring = [_clamp_xy(*p) for p in ring]
    out = ["; LUMACUT FRAME (laser off)", "G21", "G90", "M5 I",
           f"G0 X{ring[0][0]:.3f} Y{ring[0][1]:.3f}"]
    for _ in range(loops):
        for x, y in ring[1:] + ring[:1]:
            out.append(f"G1 X{x:.3f} Y{y:.3f} F{feed_mm_min:g} S0")
    out += ["M5 I", "M400"]
    return "\n".join(out) + "\n"
