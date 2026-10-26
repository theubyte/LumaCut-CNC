"""Automatic probe plan and surface height maps (machine mm, pure Python).

Used by the automatic job (op=autorun, docs/ZUSAMMENARBEIT_CLAUDE_GROK.md §4):

* ``motif_regions`` finds the areas that are lasered: every powered G1 is
  sampled into a coarse cell grid, neighbouring cells (gap below
  ``REGION_GAP_MM``) form one region, each region is the bounding box of its
  laser paths plus a small margin.
* ``plan_probe`` puts a small grid on every region (point count from the size,
  1 x 1 up to 4 x 4, at most ``MAX_TOTAL_POINTS`` over the job) and marks the
  points the switch cannot reach; those are filled from their neighbours.
* ``HeightMapSet.surface`` gives the bilinear surface Z at any XY; outside
  every region the highest measured surface applies (never too low).

Same model as Android ``HeightMap``/``HeightMapSet``, but in machine
coordinates, because the Pi only works in those.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

CELL_MM = 5.0
REGION_GAP_MM = 10.0
REGION_MARGIN_MM = 2.0
GRID_INSET_MM = 5.0         # probe points this far inside a region box
GRID_SPACING_MM = 90.0      # about one point per 90 mm, 2..4 per side
MAX_PER_SIDE = 4
MAX_REGIONS = 12
MAX_TOTAL_POINTS = 36
# A grid point the switch cannot reach (it sits beside the laser, so a strip
# along one edge of the bed is out of its reach) is probed at the nearest
# reachable spot at most this far away; its height stands for the point.
SUBSTITUTE_MAX_MM = 40.0
SUBSTITUTE_STEP_MM = 1.0

_WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")


@dataclass(frozen=True)
class Box:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def width(self):
        return self.xmax - self.xmin

    @property
    def height(self):
        return self.ymax - self.ymin

    @property
    def center(self):
        return ((self.xmin + self.xmax) / 2, (self.ymin + self.ymax) / 2)

    def contains(self, x, y, margin=0.0):
        return (self.xmin - margin <= x <= self.xmax + margin and
                self.ymin - margin <= y <= self.ymax + margin)

    def as_dict(self):
        return {"xmin": round(self.xmin, 3), "ymin": round(self.ymin, 3),
                "xmax": round(self.xmax, 3), "ymax": round(self.ymax, 3)}


@dataclass
class HeightGrid:
    """Probe grid over one region; z[r * cols + c] is the contact Z or None."""
    region: Box
    x0: float
    y0: float
    step_x: float
    step_y: float
    cols: int
    rows: int
    z: list = field(default_factory=list)
    reachable: list = field(default_factory=list)
    # Where each point is actually probed (None = at the point itself).
    probe_at: list = field(default_factory=list)

    def point(self, index):
        r, c = divmod(index, self.cols)
        return (self.x0 + c * self.step_x, self.y0 + r * self.step_y)

    def probe_point(self, index):
        """Laser X/Y the switch probes for grid point ``index``."""
        if index < len(self.probe_at) and self.probe_at[index] is not None:
            return self.probe_at[index]
        return self.point(index)

    @property
    def substituted(self):
        return sum(1 for p in self.probe_at if p is not None)

    def order(self):
        """Point indices in serpentine order (short travel between points)."""
        result = []
        for r in range(self.rows):
            cols = range(self.cols) if r % 2 == 0 else range(self.cols - 1, -1, -1)
            result += [r * self.cols + c for c in cols]
        return result

    @property
    def measured(self):
        return [v for v in self.z if v is not None]

    def filled(self):
        """Copy with missing points set to the mean of measured neighbours."""
        values = list(self.z)
        for _ in range(self.cols + self.rows):
            missing = False
            for r in range(self.rows):
                for c in range(self.cols):
                    if values[r * self.cols + c] is not None:
                        continue
                    near = [values[rr * self.cols + cc]
                            for cc, rr in ((c - 1, r), (c + 1, r), (c, r - 1), (c, r + 1))
                            if 0 <= cc < self.cols and 0 <= rr < self.rows
                            and values[rr * self.cols + cc] is not None]
                    if near:
                        values[r * self.cols + c] = sum(near) / len(near)
                    else:
                        missing = True
            if not missing:
                break
        if any(v is None for v in values):
            raise ValueError("Höhenraster ohne Messpunkt")
        return HeightGrid(self.region, self.x0, self.y0, self.step_x, self.step_y,
                          self.cols, self.rows, values, list(self.reachable), list(self.probe_at))

    def at(self, x, y):
        """Bilinear surface Z (clamped to the grid); grid must be filled."""
        fx = min(max((x - self.x0) / self.step_x, 0.0), self.cols - 1.0) if self.cols > 1 else 0.0
        fy = min(max((y - self.y0) / self.step_y, 0.0), self.rows - 1.0) if self.rows > 1 else 0.0
        c0, r0 = min(int(fx), self.cols - 1), min(int(fy), self.rows - 1)
        c1, r1 = min(c0 + 1, self.cols - 1), min(r0 + 1, self.rows - 1)
        tx, ty = fx - c0, fy - r0
        v = lambda c, r: self.z[r * self.cols + c]
        top = v(c0, r0) * (1 - tx) + v(c1, r0) * tx
        bottom = v(c0, r1) * (1 - tx) + v(c1, r1) * tx
        return top * (1 - ty) + bottom * ty

    def as_dict(self):
        return {"region": self.region.as_dict(), "cols": self.cols, "rows": self.rows,
                "points": [[round(p, 3) for p in self.point(i)] for i in range(len(self.z))],
                "z": [None if v is None else round(v, 3) for v in self.z],
                "reachable": list(self.reachable),
                "probe_at": [None if p is None else [round(v, 3) for v in p] for p in self.probe_at]}


class HeightMapSet:
    """All filled grids of one job."""

    def __init__(self, grids):
        self.grids = [g.filled() for g in grids if g.measured]
        if not self.grids:
            raise ValueError("Keine Oberflächenmessung vorhanden")
        values = [v for g in self.grids for v in g.z]
        self.lowest, self.highest = min(values), max(values)

    def surface(self, x, y):
        """(surface Z, inside a probed region) at machine XY."""
        inside = [g for g in self.grids if g.region.contains(x, y, 1.0)]
        if not inside:
            return self.highest, False
        best = min(inside, key=lambda g: math.hypot(g.region.center[0] - x,
                                                    g.region.center[1] - y))
        return best.at(x, y), True


def _powered_points(lines):
    """Sampled XY points (<= CELL_MM/2 apart) along every powered G1."""
    x = y = 0.0
    absolute, cutting = True, False
    step = CELL_MM / 2
    for raw in lines:
        line = re.sub(r"\([^)]*\)", "", raw.split(";", 1)[0]).strip().upper()
        if not line:
            continue
        words = _WORD.findall(line)
        modes = [int(float(v)) for k, v in words if k == "G" and float(v).is_integer()]
        if 90 in modes:
            absolute = True
        if 91 in modes:
            absolute = False
        if any(m in (2, 3) for m in modes):
            raise ValueError("Bögen (G2/G3) im Auftrag: in der App als Linien ausgeben")
        if line.startswith("M5"):
            cutting = False
        if 0 not in modes and 1 not in modes:
            continue
        vals = {k: float(v) for k, v in words if k in "XYS"}
        nx = (vals["X"] if absolute else x + vals["X"]) if "X" in vals else x
        ny = (vals["Y"] if absolute else y + vals["Y"]) if "Y" in vals else y
        if 0 in modes:
            cutting = False
        if 1 in modes:
            if "S" in vals:
                cutting = vals["S"] > 0
            if cutting and (nx, ny) != (x, y):
                n = max(1, math.ceil(math.hypot(nx - x, ny - y) / step))
                for k in range(n + 1):
                    yield x + (nx - x) * k / n, y + (ny - y) * k / n
        x, y = nx, ny


def motif_regions(lines, bounds: Box):
    """Bounding boxes of the separate laser areas, clamped to ``bounds``."""
    cells = {}
    for px, py in _powered_points(lines):
        key = (int(px // CELL_MM), int(py // CELL_MM))
        box = cells.get(key)
        cells[key] = (px, py, px, py) if box is None else (
            min(box[0], px), min(box[1], py), max(box[2], px), max(box[3], py))
    if not cells:
        raise ValueError("Auftrag ohne Laserbahnen: nichts abzutasten")
    reach = int(math.ceil(REGION_GAP_MM / CELL_MM))
    seen, regions = set(), []
    for start in cells:
        if start in seen:
            continue
        seen.add(start)
        stack, extent = [start], list(cells[start])
        while stack:
            cx, cy = stack.pop()
            for dx in range(-reach, reach + 1):
                for dy in range(-reach, reach + 1):
                    key = (cx + dx, cy + dy)
                    if key in cells and key not in seen:
                        seen.add(key)
                        stack.append(key)
                        b = cells[key]
                        extent = [min(extent[0], b[0]), min(extent[1], b[1]),
                                  max(extent[2], b[2]), max(extent[3], b[3])]
        regions.append(extent)
    if len(regions) > MAX_REGIONS:
        regions = [[min(r[0] for r in regions), min(r[1] for r in regions),
                    max(r[2] for r in regions), max(r[3] for r in regions)]]
    m = REGION_MARGIN_MM
    result = [Box(max(bounds.xmin, r[0] - m), max(bounds.ymin, r[1] - m),
                  min(bounds.xmax, r[2] + m), min(bounds.ymax, r[3] + m)) for r in regions]
    return sorted(result, key=lambda b: (b.ymin, b.xmin))


def _per_side(length):
    if length < 4 * GRID_INSET_MM:
        return 1
    return min(MAX_PER_SIDE, max(2, math.ceil(length / GRID_SPACING_MM) + 1))


def _grid(region, cols, rows):
    def axis(lo, hi, n):
        if n == 1:
            return (lo + hi) / 2, 0.0
        inset = min(GRID_INSET_MM, (hi - lo) / 4)
        return lo + inset, (hi - lo - 2 * inset) / (n - 1)
    x0, sx = axis(region.xmin, region.xmax, cols)
    y0, sy = axis(region.ymin, region.ymax, rows)
    return HeightGrid(region, x0, y0, sx, sy, cols, rows, [None] * (cols * rows))


def plan_probe(lines, bounds: Box, reachable):
    """Probe grids for a job; ``reachable(x, y)`` says if the switch gets there.

    Raises ValueError when no point at all can be probed.
    """
    regions = motif_regions(lines, bounds)
    sizes = [[_per_side(r.width), _per_side(r.height)] for r in regions]
    while sum(c * r for c, r in sizes) > MAX_TOTAL_POINTS:
        largest = max(range(len(sizes)), key=lambda i: (max(sizes[i]), sizes[i][0] * sizes[i][1]))
        c, r = sizes[largest]
        if c == r == 1:
            break
        sizes[largest] = [c - 1, r] if c >= r else [c, r - 1]
        sizes[largest] = [max(1, v) for v in sizes[largest]]
    grids = [_grid(region, c, r) for region, (c, r) in zip(regions, sizes)]
    return _mark_reachable(grids, reachable)


def single_point_plan(x, y, reachable):
    """Plan with exactly one probe point (explicit x/y from the request)."""
    grid = HeightGrid(Box(x, y, x, y), x, y, 0.0, 0.0, 1, 1, [None])
    return _mark_reachable([grid], reachable)


def nearest_reachable(x, y, reachable, max_mm=SUBSTITUTE_MAX_MM, step=SUBSTITUTE_STEP_MM):
    """Closest point to (x, y) the switch can probe, within ``max_mm``; else None."""
    n = int(max_mm / step)
    best = None
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            d = math.hypot(i * step, j * step)
            if d > max_mm or (best is not None and d >= best[0]):
                continue
            px, py = x + i * step, y + j * step
            if reachable(px, py):
                best = (d, (px, py))
    return None if best is None else best[1]


def _mark_reachable(grids, reachable):
    for g in grids:
        g.reachable, g.probe_at = [], []
        for i in range(len(g.z)):
            px, py = g.point(i)
            if reachable(px, py):
                g.reachable.append(True)
                g.probe_at.append(None)
                continue
            # Edge strip out of the switch's reach: measure next to it instead.
            near = nearest_reachable(px, py, reachable)
            g.reachable.append(near is not None)
            g.probe_at.append(near)
    grids = [g for g in grids if any(g.reachable)] or grids
    if not any(any(g.reachable) for g in grids):
        raise ValueError("Kein Abtastpunkt erreichbar: der Taster kommt an keine Stelle "
                         "des Motivs – Motiv weiter in die Mitte schieben, dann neu starten.")
    return grids
