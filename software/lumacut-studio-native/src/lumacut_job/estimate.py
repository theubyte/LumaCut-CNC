"""Job time estimate and framing G-code.

:func:`estimate_gcode` simulates Marlin's planner closely enough for a
useful preview: per-segment trapezoid profiles with the machine's
acceleration, junction-deviation corner speeds and forward/backward speed
passes (like LightBurn's "Total estimated time" in Preview). Limits not
passed explicitly come from :func:`lumacut_job.motion.active_motion`: the
Pi's motion calibration once a Pi was seen (``config.motion``, also the last
one stored), else the firmware values from docs/MASCHINE.md: XY 150 mm/s
per axis, 500 mm/s², Z 9 mm/s. Rapid F9000 when a G0 carries no F (set by
the Pi). The feed limit is per axis like Marlin's ``M203 X Y``: a diagonal
move whose F asks for more may run up to ``speed`` on each axis.

The Pi runs every Studio job from its park corner and parks again after it
(``park_safezone``: Z up to the travel height, ``G0 X0 Y0 F9000``, down to
the park height). With ``park=True`` (default) the estimate adds both like
LightBurn's travel back to the finish position: the *approach* – the head
rises from the park height (1 mm) to the travel height (20 mm) and the
job's first move runs from X0/Y0 – and the *return* – lift back to the
travel height if the job lowered Z, rapid to X0/Y0, down to the park height
(:class:`ParkRoutine`). The heights default to the connected Pi's
(``travel_z_mm`` = clearance or material + 20 mm, ``config.park_z_mm``;
:func:`~lumacut_job.park_routine.active_park`, stored for offline use), and
the approach starts at the head position with the job moved like the Pi
places it at „Aktuelle Position“ / „Benutzer-Ursprung“
(:class:`~lumacut_job.park_routine.JobStart`, ``active_start``); offline
the Pi defaults (park 1 mm, travel 20 mm) from X0/Y0, unshifted. Homing
(only when the Pi is not referenced) and probing of the automatic run are
*not* included.

:func:`frame_gcode` traces the job's bounding box (or its convex
"rubber band" hull) with the laser off, like LightBurn's Frame buttons and
xTool's Framing.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .motion import (EXPLICIT, FIRMWARE_ACCEL, FIRMWARE_SPEED, FIRMWARE_Z_SPEED, MotionProfile,
                     active_motion)
from lumacut_canvas.workarea import (WORK_HEIGHT_MM, WORK_WIDTH_MM, to_machine,
    MACHINE_X_MAX, MACHINE_X_MIN, MACHINE_Y_MAX, MACHINE_Y_MIN)

_WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")

ACCEL_XY = FIRMWARE_ACCEL  # mm/s² (firmware default; see lumacut_job.motion)
MAX_XY = FIRMWARE_SPEED    # mm/s per X/Y axis
MAX_Z = FIRMWARE_Z_SPEED   # mm/s
RAPID_FEED = 9000.0       # mm/min, Pi default for G0 without F
JUNCTION_DEVIATION = 0.013  # mm (Marlin default)
FRAME_FEED = 3000.0       # mm/min

# Park routine of the Pi around every job (pi400/marlin/transport.py
# park_safezone / _unpark_before_locked / _lower_to_park_locked; defaults of
# web.py config) and the job start – lumacut_job.park_routine; the heights
# follow the connected Pi's status. tests/test_estimate_park.py keeps the
# mirrors equal.
from .park_routine import (DEFAULT_PARK, PARK_FEED, PARK_Z_MM, TRAVEL_Z_MM,  # noqa: E402,F401
                           Z_ACCEL, JobStart, ParkRoutine, active_park, active_start)

# Erlaubter Bereich in Maschinen-mm (Nullpunkt oben rechts: to_machine(0, 0)
# ist jetzt die *größte* X-Koordinate, darum feste Grenzen statt Ecken).
_MIN_X, _MIN_Y, _MAX_X, _MAX_Y = MACHINE_X_MIN, MACHINE_Y_MIN, MACHINE_X_MAX, MACHINE_Y_MAX


@dataclass
class JobEstimate:
    cut_length_mm: float = 0.0
    travel_length_mm: float = 0.0
    cut_time_s: float = 0.0
    travel_time_s: float = 0.0
    dwell_time_s: float = 0.0
    moves: int = 0
    bounds: tuple[float, float, float, float] | None = None  # laser-on, machine mm
    # Zeit je Ebene (Reihenfolge wie im Auftrag) aus den Kommentaren
    # ``; LAYER <Name>`` bzw. ``; IMAGE <id> <MODUS>`` – wie LightBurns
    # Zeit pro Ebene in der Vorschau. Leer bei G-Code ohne solche Kommentare.
    layers: list[tuple[str, float]] = field(default_factory=list)
    # Bewegungsgrenzen, mit denen gerechnet wurde (Pi-Kalibrierung oder Firmware)
    motion: MotionProfile | None = None
    # Ablauf des Pi um den Auftrag (park=True): Anfahrt aus der Park-Ecke
    # (Z hoch + erste Fahrt ab X0/Y0) und Parken danach (Z hoch, X0/Y0, Z runter)
    approach_time_s: float = 0.0
    approach_length_mm: float = 0.0   # X/Y
    park_time_s: float = 0.0
    park_length_mm: float = 0.0       # X/Y
    park_included: bool = False
    # Heights and start the routine was planned with
    routine: ParkRoutine | None = None
    placement_offset: tuple[float, float] = (0.0, 0.0)   # (dx, dy) the Pi adds
    placement_origin: str = "absolute"
    start_xy: tuple[float, float] = (0.0, 0.0)         # head X/Y where the job starts

    def routine_note(self) -> str:
        """Heights / start / placement of the routine when they differ from
        the defaults (``Fahrhöhe 25 mm, Parkhöhe 1 mm (Pi) · am Ursprung
        „Benutzer-Ursprung“ versetzt um X+12 / Y-3 mm``), else ""."""
        if not self.park_included or self.routine is None:
            return ""
        parts = []
        if not self.routine.is_default or self.routine.source != "default":
            parts.append(self.routine.label())
        if self.placement_origin != "absolute":
            from .park_corner import ORIGIN_NAMES
            dx, dy = self.placement_offset
            parts.append("am Ursprung „%s“ versetzt um X%+.1f / Y%+.1f mm" % (
                ORIGIN_NAMES.get(self.placement_origin, self.placement_origin), dx, dy))
        return " · ".join(parts)

    def motion_note(self) -> str:
        """``Bewegung: Pi-Kalibrierung 2100 mm/s², 200 mm/s`` (leer ohne Angabe)."""
        return f"Bewegung: {self.motion.label()}" if self.motion is not None else ""

    @property
    def program_time_s(self) -> float:
        """Time of the G-code lines alone (what :attr:`layers` adds up)."""
        return self.cut_time_s + self.travel_time_s + self.dwell_time_s

    @property
    def routine_time_s(self) -> float:
        """Approach from the park corner plus parking after the job."""
        return self.approach_time_s + self.park_time_s

    @property
    def total_time_s(self) -> float:
        return self.program_time_s + self.routine_time_s

    def summary(self) -> str:
        text = (f"≈ {format_duration(self.total_time_s)} · Schnitt {self.cut_length_mm / 1000:.2f} m "
                f"· Leerfahrt {self.travel_length_mm / 1000:.2f} m")
        if self.routine_time_s > 0:
            text += f" · Anfahrt/Parken {format_duration(self.routine_time_s)}"
        return text

    def scope_note(self) -> str:
        """What the time covers besides the G-code (for tooltips / messages)."""
        if self.park_included:
            if self.start_xy != (0.0, 0.0):
                return "mit Anfahrt von der Kopfposition und Parken, ohne Referenzfahrt/Abtasten"
            return "mit Anfahrt aus der Park-Ecke und Parken, ohne Referenzfahrt/Abtasten"
        return "ohne Referenzfahrt/Fokus/Parken"

    def layer_summary(self) -> str:
        """``Schneiden 1 min 20 s · Gravur 3 min 05 s`` (leer bei < 2 Ebenen)."""
        if len(self.layers) < 2:
            return ""
        return " · ".join(f"{name} {format_duration(t)}" for name, t in self.layers)


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


def _move_time(length: float, vmax: float, accel: float) -> float:
    """One move from rest to rest (the Pi waits with M400 around park moves)."""
    return _seg_time(length, 0.0, 0.0, vmax, accel) if length > 1e-9 else 0.0


def _xy_speed(dx: float, dy: float, feed_mm_min: float, max_xy: float) -> float:
    L = math.hypot(dx, dy)
    v = feed_mm_min / 60.0
    frac = max(abs(dx), abs(dy)) / L if L > 1e-12 else 0.0
    return min(v, max_xy / frac) if frac > 1e-12 else v


def estimate_gcode(gcode: str, accel: float | None = None, max_xy: float | None = None,
                   max_z: float | None = None, rapid_feed: float = RAPID_FEED,
                   junction_deviation: float = JUNCTION_DEVIATION,
                   motion: MotionProfile | None = None,
                   park: bool | ParkRoutine = True,
                   start: JobStart | None = None) -> JobEstimate:
    """Estimate run time of Marlin laser G-code (G0/G1/G4, G90/G91, M3 I/M5 I).

    ``motion`` (default :func:`~lumacut_job.motion.active_motion`) supplies
    every limit not given as ``accel`` / ``max_xy`` / ``max_z``. ``park``
    (default the connected / last seen Pi's heights, ``active_park``) adds
    the approach and the parking after the job; ``False`` = the G-code lines
    only. ``start`` (default ``active_start``: head position and the Pi's
    placement at the chosen origin) sets where the approach begins and the
    offset the Pi adds to the job's X/Y – it changes only the routine, the
    G-code part is translation invariant.
    """
    base = motion if motion is not None else active_motion()
    if accel is None and max_xy is None and max_z is None:
        used = base
    else:
        used = MotionProfile(base.accel if accel is None else float(accel),
                             base.speed if max_xy is None else float(max_xy),
                             base.z_speed if max_z is None else float(max_z), EXPLICIT)
    accel, max_xy, max_z = used.accel, used.speed, used.z_speed
    est = JobEstimate(motion=used)
    pos = [0.0, 0.0, 0.0]
    have_xy = False
    absolute = True
    feed = None
    inline = False
    segs: list[_Seg] = []
    xs: list[float] = []
    ys: list[float] = []
    section = ""
    dwell: dict[str, float] = {}
    first_move = None     # (x, y, has_z, feed mm/min) of the move that leaves the park corner
    abs_z = False         # an absolute Z word: pos[2] is machine Z

    for raw in gcode.splitlines():
        if raw.startswith("; LAYER "):
            section = raw[8:].strip() or "Ebene"
            continue
        if raw.startswith("; IMAGE "):
            parts = raw.split()
            section = f"Bild {parts[3].capitalize()}" if len(parts) > 3 else "Bild"
            continue
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
            t = float(words.get("P", 0)) / 1000.0 + float(words.get("S", 0))
            est.dwell_time_s += t
            dwell[section] = dwell.get(section, 0.0) + t
            continue
        if g not in (0, 1):
            continue
        tgt = list(pos)
        for k, axis in enumerate("XYZ"):
            if axis in words:
                v = float(words[axis])
                tgt[k] = v if absolute else pos[k] + v
        if "Z" in words and absolute:
            abs_z = True
        if "F" in words and g == 1:
            feed = float(words["F"])
        if not have_xy:
            # First positioning move: in the G-code lines its start point is
            # unknown (0 length); the park routine plans it from X0/Y0.
            if "X" in words or "Y" in words:
                have_xy = True
                f0 = (float(words["F"]) if "F" in words else rapid_feed) if g == 0 else (feed or rapid_feed)
                first_move = (tgt[0], tgt[1], "Z" in words, f0)
            pos = tgt
            continue
        d = [t - p for t, p in zip(tgt, pos)]
        L = math.sqrt(sum(c * c for c in d))
        pos = tgt
        if L <= 1e-9:
            continue
        f = (float(words["F"]) if "F" in words else rapid_feed) if g == 0 else (feed or rapid_feed)
        vmax = f / 60.0
        # per-axis feed limit (M203 X Y): the larger XY component reaches max_xy first
        axis_frac = max(abs(d[0]), abs(d[1])) / L
        if axis_frac > 1e-12:
            vmax = min(vmax, max_xy / axis_frac)
        if abs(d[2]) > 1e-9:
            vmax = min(vmax, max_z * L / abs(d[2]))
        power = float(words.get("S", 0)) if g == 1 else 0.0
        cutting = g == 1 and inline and power > 0
        segs.append(_Seg(L, vmax, (d[0] / L, d[1] / L, d[2] / L), cutting,
                         extra={"section": section}))
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
    per: dict[str, float] = {}
    for i in range(n):
        s = segs[i]
        s.entry = min(s.entry, v)
        v_exit = min(exit_v[i], math.sqrt(s.entry ** 2 + 2 * accel * s.length))
        t = _seg_time(s.length, s.entry, v_exit, s.vmax, accel)
        per[s.extra["section"]] = per.get(s.extra["section"], 0.0) + t
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
    for name, t in dwell.items():
        per[name] = per.get(name, 0.0) + t
    # Leerfahrten vor der ersten Ebene zählen zur ersten Ebene
    if "" in per and len(per) > 1:
        head = per.pop("")
        first = next(iter(per))
        per[first] += head
    est.layers = [(name or "Auftrag", t) for name, t in per.items()]
    if xs:
        est.bounds = (min(xs), min(ys), max(xs), max(ys))
    routine = active_park() if park is True else (park or None)
    if routine is not None and first_move is not None:
        st = active_start() if start is None else start
        _add_park(est, routine, st, st.offset(gcode), first_move, pos, abs_z,
                  accel, max_xy, max_z)
    return est


def _add_park(est: JobEstimate, routine: ParkRoutine, start: JobStart,
              offset: tuple[float, float], first_move, end, abs_z: bool,
              accel: float, max_xy: float, max_z: float) -> None:
    """Approach from the head and parking after the job (rest to rest, like the Pi).

    Parked low (at X0/Y0, park height) the head first rises to the travel
    height; elsewhere it starts at its Z. After the job ``park_safezone``
    lifts to max(Z, travel height, probe minimum), rapids to X0/Y0 and lowers
    to the park height (none with park height 0).
    """
    z_v = max_z   # the Pi asks for at least F600 on Z, M203 Z caps it at the Z limit
    dx, dy = offset
    sx, sy = start.start_xy()
    parked = start.parked_low(routine)
    fx, fy, has_z, feed0 = first_move
    fx, fy = fx + dx, fy + dy
    ex, ey = end[0] + dx, end[1] + dy
    lift_t = _move_time(routine.lift_mm, z_v, routine.z_accel) if parked else 0.0
    est.approach_length_mm = math.hypot(fx - sx, fy - sy)
    est.approach_time_s = (0.0 if has_z else lift_t) + _move_time(
        est.approach_length_mm, _xy_speed(fx - sx, fy - sy, feed0, max_xy), accel)
    # Z where the program starts: travel height after the lift, else the head's
    z0 = (routine.travel_z if parked or start.head is None else start.head[2])
    end_z = end[2] if abs_z else z0 + end[2]
    top = max(end_z, routine.travel_z, routine.min_park_lift_z)
    up = max(0.0, top - end_z)
    down = max(0.0, top - routine.park_z) if routine.park_z > 0 else 0.0
    est.park_length_mm = math.hypot(ex, ey)
    est.park_time_s = (_move_time(up, z_v, routine.z_accel)
                       + _move_time(est.park_length_mm,
                                    _xy_speed(ex, ey, routine.feed, max_xy), accel)
                       + _move_time(down, z_v, routine.z_accel))
    est.park_included = True
    est.routine = routine
    est.placement_offset = (dx, dy)
    est.placement_origin = start.origin if (dx, dy) != (0.0, 0.0) or start.target else "absolute"
    est.start_xy = (sx, sy)


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
