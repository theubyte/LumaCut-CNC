"""Job placement relative to an origin (Studio "Ursprung", gap analysis #16).

A job file holds absolute machine coordinates. Placing it means moving the
whole job by (dx, dy) so that an anchor point of its motif (a corner or the
centre of the powered bounds) lands on a chosen origin:

* ``absolute`` – unchanged, the job runs where it was drawn (default);
* ``current``  – the anchor lands on the current head position;
* ``user``     – the anchor lands on a stored user origin (op=origin_set,
  e.g. a point the camera scan found).

The translation rewrites only the X/Y words of absolute G0..G3 moves. It
never emits G92 (the guard forbids it) and never touches S, F, Z, I or J,
so every rewritten line still has to pass MarlinLaserGuard and the live
transport guards. :func:`check_extent` rejects a placement in which any
move would leave the machine travel or any powered move would enter the
30 mm safe zone. Pure functions, no machine access.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .transport import normalize

ORIGIN_MODES = ("absolute", "current", "user")
#: Anchor names in Studio canvas terms: "oben" = small Y, "links" = small X
#: (lumacut_canvas.workarea.to_machine maps the canvas without mirroring).
ANCHORS = ("tl", "tr", "bl", "br", "center")

_WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
_XY = re.compile(r"([XY])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
_MOTION = re.compile(r"^G0?([0-3])(?=\s|[A-Z]|$)")


@dataclass(frozen=True)
class Box:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    def as_dict(self) -> dict:
        return {"xmin": round(self.xmin, 3), "ymin": round(self.ymin, 3),
                "xmax": round(self.xmax, 3), "ymax": round(self.ymax, 3)}


class _Acc:
    def __init__(self):
        self.xmin = self.ymin = math.inf
        self.xmax = self.ymax = -math.inf

    def add(self, x: float, y: float) -> None:
        self.xmin = min(self.xmin, x); self.xmax = max(self.xmax, x)
        self.ymin = min(self.ymin, y); self.ymax = max(self.ymax, y)

    def box(self) -> Box | None:
        return None if self.xmin == math.inf else Box(self.xmin, self.ymin, self.xmax, self.ymax)


def _arc_points(x0, y0, x1, y1, words, clockwise):
    """Start, end and every axis extreme the arc sweeps over."""
    points = [(x0, y0), (x1, y1)]
    if "R" in words:
        # Conservative: every point of such an arc lies within 2R of the chord midpoint.
        r = abs(words["R"])
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        return points + [(mx - 2 * r, my - 2 * r), (mx + 2 * r, my + 2 * r)]
    cx, cy = x0 + words.get("I", 0.0), y0 + words.get("J", 0.0)
    r = math.hypot(x0 - cx, y0 - cy)
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    if clockwise:
        a0, a1 = a1, a0          # sweep counter-clockwise from a0 to a1
    sweep = (a1 - a0) % (2 * math.pi) or 2 * math.pi
    for k in range(4):
        angle = k * math.pi / 2
        if (angle - a0) % (2 * math.pi) <= sweep + 1e-9:
            points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return points


def scan(lines, start=None):
    """(motion box, powered box) of a job; either may be None.

    ``start`` is the head XY before the job (needed for leading relative
    moves). Powered = G1..G3 while S > 0 after M3 I, like smart_cam.
    """
    x, y = (start[0], start[1]) if start is not None else (None, None)
    absolute = True
    cutting = False
    motion, powered = _Acc(), _Acc()
    for raw in lines:
        cmd = normalize(raw)
        if not cmd:
            continue
        if cmd.startswith("M5"):
            cutting = False
            continue
        if cmd == "G90":
            absolute = True
            continue
        if cmd == "G91":
            absolute = False
            continue
        if cmd in ("G28",) or cmd.startswith("G28 "):
            x, y = 0.0, 0.0
            continue
        m = _MOTION.match(cmd)
        if not m:
            continue
        code = int(m.group(1))
        words = {k: float(v) for k, v in _WORD.findall(cmd[m.end():])}
        if absolute:
            nx = words.get("X", x)
            ny = words.get("Y", y)
        else:
            nx = None if x is None else x + words.get("X", 0.0)
            ny = None if y is None else y + words.get("Y", 0.0)
        if code == 0:
            cutting = False
        elif "S" in words:
            cutting = words["S"] > 0
        if nx is None or ny is None:
            # Position not known yet (relative move without a start point).
            x, y = nx, ny
            continue
        if code in (2, 3) and x is not None and y is not None:
            pts = _arc_points(x, y, nx, ny, words, clockwise=code == 2)
        else:
            pts = [(nx, ny)] + ([(x, y)] if x is not None and y is not None else [])
        for px, py in pts:
            motion.add(px, py)
            if cutting and code != 0:
                powered.add(px, py)
        x, y = nx, ny
    return motion.box(), powered.box()


def has_relative_xy(lines) -> bool:
    """True if any G0..G3 moves X/Y relative (G91): such a job cannot be placed."""
    absolute = True
    for raw in lines:
        cmd = normalize(raw)
        if cmd == "G90":
            absolute = True
        elif cmd == "G91":
            absolute = False
        elif not absolute:
            m = _MOTION.match(cmd)
            if m and _XY.search(cmd, m.end()):
                return True
    return False


def anchor_point(box: Box, anchor: str) -> tuple[float, float]:
    if anchor not in ANCHORS:
        raise ValueError("Bezugspunkt muss einer von %s sein" % ", ".join(ANCHORS))
    if anchor == "center":
        return (box.xmin + box.xmax) / 2, (box.ymin + box.ymax) / 2
    return (box.xmin if anchor[1] == "l" else box.xmax,
            box.ymin if anchor[0] == "t" else box.ymax)


def _fmt(value: float) -> str:
    text = ("%.3f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def translate(lines, dx: float, dy: float) -> list[str]:
    """Shift every absolute G0..G3 X/Y target by (dx, dy).

    Rewritten lines are returned in normalized form (upper case, comments
    removed); all other lines are returned unchanged. Relative moves (G91)
    and arc centre offsets I/J are relative already and stay as they are.
    """
    if not dx and not dy:
        return list(lines)
    out = []
    absolute = True
    for raw in lines:
        cmd = normalize(raw)
        if cmd == "G90":
            absolute = True
        elif cmd == "G91":
            absolute = False
        m = _MOTION.match(cmd) if cmd else None
        if m and absolute and _XY.search(cmd, m.end()):
            def shift(match):
                axis, value = match.group(1), float(match.group(2))
                return axis + _fmt(value + (dx if axis == "X" else dy))
            out.append(cmd[:m.end()] + _XY.sub(shift, cmd[m.end():]))
        else:
            out.append(raw)
    return out


def check_extent(lines, travels: dict, safe_zone: float, start=None):
    """Raise ValueError unless the (placed) job stays inside the machine.

    Every move must stay inside X0..travel / Y0..travel; every powered
    move inside the cutting area safe_zone..travel. Returns (motion, powered).
    """
    motion, powered = scan(lines, start)
    tx, ty = float(travels["x"]), float(travels["y"])
    eps = 1e-6
    if motion is not None and (motion.xmin < -eps or motion.ymin < -eps or
                               motion.xmax > tx + eps or motion.ymax > ty + eps):
        raise ValueError(
            "Platzierter Auftrag fährt außerhalb des Arbeitsbereichs: X%.1f..%.1f / Y%.1f..%.1f "
            "(erlaubt X0..%g / Y0..%g)" % (motion.xmin, motion.xmax, motion.ymin, motion.ymax, tx, ty))
    if powered is not None and (powered.xmin < safe_zone - eps or powered.ymin < safe_zone - eps or
                                powered.xmax > tx + eps or powered.ymax > ty + eps):
        raise ValueError(
            "Platziertes Motiv X%.1f..%.1f / Y%.1f..%.1f liegt außerhalb des Schneidbereichs "
            "X%g..%g / Y%g..%g (30-mm-Safezone)" % (powered.xmin, powered.xmax, powered.ymin,
                                                    powered.ymax, safe_zone, tx, safe_zone, ty))
    return motion, powered
