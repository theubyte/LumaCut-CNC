"""LumaCut Smart CAM job geometry analysis.

Preflight only: NEVER authorizes laser power or changes machine coordinates.
Requires full G-code before operation; unknown geometry aborts analysis.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

_WORDS = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")

@dataclass(frozen=True)
class Bounds:
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    segments: int

    @property
    def center(self) -> tuple[float, float]:
        return ((self.xmin + self.xmax) / 2, (self.ymin + self.ymax) / 2)

    def probe_grid(self, spacing: float = 20.0, margin: float = 5.0,
                   max_points: int = 100) -> list[tuple[float, float]]:
        """Candidate points only. Real workpiece occupancy must be verified independently."""
        if not (0 < spacing <= 100 and margin >= 0):
            raise ValueError("Invalid probe grid settings")
        x0, x1 = self.xmin + margin, self.xmax - margin
        y0, y1 = self.ymin + margin, self.ymax - margin
        if x1 < x0 or y1 < y0:
            return [self.center]
        nx = max(1, math.ceil((x1-x0) / spacing)+1)
        ny = max(1, math.ceil((y1-y0) / spacing)+1)
        if nx * ny > max_points:
            raise ValueError("Too many sampling points; choose coarser grid")
        return [(x0 + (x1-x0)*i/max(1,nx-1),
                 y0 + (y1-y0)*j/max(1,ny-1))
                for j in range(ny) for i in range(nx)]

def analyze_job(gcode: str, *, origin=(0.0, 0.0)) -> Bounds:
    """Compute bounds of powered linear traces; reject unmodeled arcs.

    The first milestone accepts G0/G1, G90/G91, G20/G21,
    and non-geometric M commands. Arcs need extrema evaluation before
    they can be eligible for automatic probing.
    """
    x, y = origin
    absolute = True
    scale = 1.0
    cutting = False
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    count = 0
    for number, raw in enumerate(gcode.splitlines(), 1):
        line = raw.split(";", 1)[0].upper()
        line = re.sub(r"\([^)]*\)", "", line).strip()
        if not line:
            continue
        if line.startswith("G00 G17 G40 G21"):
            scale = 1.0
            continue
        words = _WORDS.findall(line)
        if not words:
            continue
        modes = [int(float(v)) for k, v in words if k == "G" and float(v).is_integer()]
        if 20 in modes: scale = 25.4
        if 21 in modes: scale = 1.0
        if 90 in modes: absolute = True
        if 91 in modes: absolute = False
        if any(v in (2,3) for v in modes):
            raise ValueError(f"Line {number}: G2/G3 arc geometry needs dedicated analyzer")
        if line.startswith("M5"):
            cutting = False
        if 0 not in modes and 1 not in modes:
            continue
        vals = {k: float(v) for k, v in words if k in ("X","Y","S")}
        nx = (vals["X"]*scale if absolute else x+vals["X"]*scale) if "X" in vals else x
        ny = (vals["Y"]*scale if absolute else y+vals["Y"]*scale) if "Y" in vals else y
        # A G1 without S can continue a previous laser power, while
        # G0 always means no cutting; M5 resets, M3 I arms inline.
        if 0 in modes:
            cutting = False
        if 1 in modes:
            if "S" in vals: cutting = vals["S"] > 0
            if cutting:
                minx=min(minx,x,nx);miny=min(miny,y,ny)
                maxx=max(maxx,x,nx);maxy=max(maxy,y,ny)
                count += 1
        x,y=nx,ny
    if not count:
        raise ValueError("No powered vector/raster motion found; cannot infer motif bounds")
    return Bounds(minx,miny,maxx,maxy,count)
