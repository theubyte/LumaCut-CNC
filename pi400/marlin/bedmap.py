"""Bed map: the empty bed probed once on a grid and kept on the Pi.

Z0 is where the switch homes, not the bed itself: on the machine the empty
bed sat 0.7 to 1.2 mm below Z0 (2026-10-29). With the map the Pi knows the
bed height at any X/Y, so a probed surface also gives the workpiece
thickness above the bed (``above_bed``) and a warped bed shows up.

The grid is a plain ``heightmap.HeightGrid`` in machine mm (laser X/Y), the
points the switch cannot reach are probed next to them as for the automatic
job. Stored as JSON next to the Pi config; pure functions, no machine access.
"""
from __future__ import annotations

import calendar
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from . import heightmap
from .heightmap import Box, HeightGrid

FILENAME = "bed_map.json"
FORMAT = "lumacut-bed-map/1"
COLS, ROWS = 6, 6
INSET_MM = 10.0
# Y beyond this is not probed until the real Y travel is measured: on
# 2026-10-29 the head stalled at about Y350 although 370 is configured.
Y_LIMIT_MM = 330.0
# Between points the head rises this far above the highest contact: higher
# than for a workpiece, a forgotten clamp or stop on the bed must not be hit.
HOP_MM = 10.0


def plan(bounds: Box, reachable, cols=COLS, rows=ROWS) -> HeightGrid:
    """Grid over ``bounds`` (inset by INSET_MM), unreachable points substituted."""
    ymax = min(bounds.ymax, Y_LIMIT_MM)
    region = Box(bounds.xmin + INSET_MM, bounds.ymin + INSET_MM,
                 bounds.xmax - INSET_MM, ymax - INSET_MM)
    if region.width <= 0 or region.height <= 0:
        raise ValueError("Arbeitsbereich zu klein für eine Bettkarte")
    grid = HeightGrid(region, region.xmin, region.ymin,
                      region.width / (cols - 1), region.height / (rows - 1),
                      cols, rows, [None] * (cols * rows))
    return heightmap._mark_reachable([grid], reachable)[0]


@dataclass
class BedMap:
    grid: HeightGrid          # filled: every z set
    measured_at: float
    # Points where the switch found no bed (deeper than the firmware probes):
    # their height is filled in from the neighbours.
    missing: tuple = ()

    def at(self, x, y):
        """Bed Z (relative to Z0) at machine X/Y, bilinear, clamped to the grid."""
        return self.grid.at(x, y)

    def above_bed(self, z, x, y):
        """Height of a probed contact ``z`` above the bed at X/Y."""
        return z - self.at(x, y)

    def summary(self):
        z = self.grid.z
        return {"measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.measured_at)),
                "cols": self.grid.cols, "rows": self.grid.rows,
                "lowest": round(min(z), 3), "highest": round(max(z), 3),
                "range": round(max(z) - min(z), 3),
                "mean": round(sum(z) / len(z), 3), "missing": len(self.missing)}

    def as_dict(self):
        return {"format": FORMAT, **self.summary(), **self.grid.as_dict(),
                "missing_points": list(self.missing),
                "x0": self.grid.x0, "y0": self.grid.y0,
                "step_x": self.grid.step_x, "step_y": self.grid.step_y}

    @classmethod
    def from_measured(cls, grid: HeightGrid, measured_at=None):
        if not grid.measured:
            raise ValueError("Bettkarte ohne Messpunkt")
        missing = tuple(i for i, z in enumerate(grid.z) if z is None)
        return cls(grid.filled(), time.time() if measured_at is None else measured_at, missing)

    @classmethod
    def from_dict(cls, d):
        if d.get("format") != FORMAT:
            raise ValueError("Unbekanntes Bettkarten-Format")
        r = d["region"]
        grid = HeightGrid(Box(r["xmin"], r["ymin"], r["xmax"], r["ymax"]),
                          float(d["x0"]), float(d["y0"]), float(d["step_x"]), float(d["step_y"]),
                          int(d["cols"]), int(d["rows"]), [float(v) for v in d["z"]],
                          list(d.get("reachable") or []), [None] * len(d["z"]))
        if len(grid.z) != grid.cols * grid.rows:
            raise ValueError("Bettkarte unvollständig")
        stamp = calendar.timegm(time.strptime(d["measured_at"], "%Y-%m-%dT%H:%M:%SZ"))
        return cls(grid, stamp, tuple(int(i) for i in d.get("missing_points") or ()))


def load(path: Path):
    """The stored map, or None (none measured yet or unreadable)."""
    try:
        return BedMap.from_dict(json.loads(Path(path).read_text("utf-8")))
    except FileNotFoundError:
        return None
    except Exception:
        logging.exception("Bettkarte %s nicht lesbar", path)
        return None


def save(path: Path, bed: BedMap):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(bed.as_dict(), indent=1), "utf-8")
    os.replace(tmp, path)


def delete(path: Path):
    Path(path).unlink(missing_ok=True)
