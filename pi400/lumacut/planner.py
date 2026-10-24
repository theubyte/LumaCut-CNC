"""Raspberry Pi-side G-code motion geometry and job preview.

The Pi understands the modal work-space path before commanding the STM32.
GRBL on the SKR still generates realtime steps and enforces hardware limits.

Preview is strictly advisory: work offsets, transformations, unsupported
commands and equipment calibration require live machine verification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, cos, hypot, isfinite, pi, sin
import re
from pathlib import Path

WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
COMMENT = re.compile(r"\([^()]*\)")
TAU = 2.0 * pi


@dataclass
class Program:
    segments: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    bounds: tuple | None = None
    total_lines: int = 0
    estimated_segments: int = 0

    def as_dict(self, limit=4000):
        return {
            "segments": self.segments[:limit],
            "truncated": len(self.segments) > limit,
            "errors": self.errors[:20],
            "bounds": list(self.bounds) if self.bounds is not None else None,
            "total_lines": self.total_lines,
            "estimated_segments": self.estimated_segments,
        }


def _arc_points(start, end, offsets, clockwise, scale, arc_center_absolute=False):
    if offsets.get("R") is not None:
        radius = abs(offsets["R"] * scale)
        dx, dy = end[0] - start[0], end[1] - start[1]
        chord = hypot(dx, dy)
        if chord == 0 or radius < chord / 2:
            raise ValueError("R-Kreis überbestimmt oder Vollkreis ohne I/J")
        mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
        h = max(0.0, radius * radius - chord * chord / 4) ** 0.5
        perp_x, perp_y = -dy / chord, dx / chord
        options = [(mx + perp_x * h, my + perp_y * h),
                   (mx - perp_x * h, my - perp_y * h)]
        def sweep(center):
            s = atan2(start[1] - center[1], start[0] - center[0])
            e = atan2(end[1] - center[1], end[0] - center[0])
            return (s - e) % TAU if clockwise else (e - s) % TAU
        major = offsets["R"] < 0
        centers = sorted(options, key=sweep, reverse=major)
        cx, cy = centers[0]
    else:
        if "I" not in offsets and "J" not in offsets:
            raise ValueError("Kreisbogen ohne I/J oder R")
        cx = (offsets.get("I", 0) * scale
              if arc_center_absolute else start[0] + offsets.get("I", 0) * scale)
        cy = (offsets.get("J", 0) * scale
              if arc_center_absolute else start[1] + offsets.get("J", 0) * scale)
    radius_start = hypot(start[0] - cx, start[1] - cy)
    radius_end = hypot(end[0] - cx, end[1] - cy)
    if radius_start < 1e-6 or abs(radius_end - radius_start) > max(.03, radius_start * .003):
        raise ValueError("Kreisradius an Start und Ende inkonsistent")
    a0 = atan2(start[1] - cy, start[0] - cx)
    a1 = atan2(end[1] - cy, end[0] - cx)
    sweep = (a0 - a1) % TAU if clockwise else (a1 - a0) % TAU
    if sweep < 1e-8:
        sweep = TAU
    samples = max(8, min(180, int(sweep * radius_start / 2) + 1))
    return [
        (cx + radius_start * cos(a0 + (-1 if clockwise else 1) * sweep * k / samples),
         cy + radius_start * sin(a0 + (-1 if clockwise else 1) * sweep * k / samples))
        for k in range(1, samples)
    ] + [end]


def analyze_text(text: str, max_points: int = 20000) -> Program:
    result = Program()
    x = y = z = 0.0
    absolute = True
    arc_center_absolute = False
    metric = True
    motion = 0
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    point_count = 0
    for number, line in enumerate(text.splitlines(), 1):
        result.total_lines += 1
        clean = COMMENT.sub("", line.upper().split(";", 1)[0]).strip()
        if not clean or clean == "%":
            continue
        if "#" in clean or "[" in clean:
            result.errors.append(f"Zeile {number}: Makrovariablen nicht visualisierbar")
            break
        words = WORD.findall(clean)
        if not words:
            # Unknown plain GRBL command, e.g. $H, does not produce geometry.
            if clean.startswith("$"):
                result.errors.append(f"Zeile {number}: Systemkommando im Auftrag")
                break
            continue
        args = {}
        line_motion = motion
        unsupported = False
        g53 = False
        for letter, value in words:
            v = float(value)
            if not isfinite(v):
                unsupported = True
            if letter == "G":
                if v in (0, 1, 2, 3):
                    line_motion = int(v)
                elif v == 90:
                    absolute = True
                elif v == 91:
                    absolute = False
                elif v == 90.1:
                    arc_center_absolute = True
                elif v == 91.1:
                    arc_center_absolute = False
                elif v == 20:
                    metric = False
                elif v == 21:
                    metric = True
                elif v == 17:
                    pass
                elif v == 53:
                    g53 = True
                elif v in (4, 54, 55, 56, 57, 58, 59, 80, 94):
                    pass
                else:
                    unsupported = True
            elif letter in "XYZIJR":
                args[letter] = v
        if g53 and any(a in args for a in "XYZ"):
            unsupported = True
        if unsupported:
            result.errors.append(f"Zeile {number}: Koordinatentransformation oder G-Code für sichere Vorschau nicht unterstützt")
            break
        motion = line_motion
        scale = 1.0 if metric else 25.4
        nx, ny, nz = x, y, z
        if "X" in args:
            nx = args["X"] * scale + (0 if absolute else x)
        if "Y" in args:
            ny = args["Y"] * scale + (0 if absolute else y)
        if "Z" in args:
            nz = args["Z"] * scale + (0 if absolute else z)
        if not all(isfinite(v) and abs(v) < 1000000 for v in (nx, ny, nz)):
            result.errors.append(f"Zeile {number}: Position außerhalb sinnvoller Grenzen")
            break
        has_move = any(a in args for a in "XYZ")
        has_arc = motion in (2, 3) and any(a in args for a in "IJR")
        if not (has_move or has_arc):
            continue
        start = (x, y)
        end = (nx, ny)
        try:
            points = (_arc_points(start, end, args, motion == 2,
                                  scale, arc_center_absolute)
                      if motion in (2, 3) else [end])
        except ValueError as exc:
            result.errors.append(f"Zeile {number}: {exc}")
            break
        points = [start] + points
        for a, b in zip(points, points[1:]):
            if a == b:
                continue
            if point_count >= max_points:
                result.errors.append("Begrenzung der Vorschau-Punktzahl erreicht")
                break
            xmin, ymin = min(xmin, *[a[0], b[0]]), min(ymin, *[a[1], b[1]])
            xmax, ymax = max(xmax, a[0], b[0]), max(ymax, a[1], b[1])
            result.segments.append([round(a[0], 4), round(a[1], 4),
                                    round(b[0], 4), round(b[1], 4),
                                    1 if motion == 0 else 0])
            point_count += 1
        if result.errors:
            break
        x, y, z = nx, ny, nz
        result.estimated_segments += 1
    if result.segments and not result.errors:
        result.bounds = (round(xmin, 3), round(ymin, 3),
                         round(xmax, 3), round(ymax, 3))
    return result


def analyze_file(path: Path) -> Program:
    return analyze_text(path.read_text(encoding="utf-8", errors="replace"))
