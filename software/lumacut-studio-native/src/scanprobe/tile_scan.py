"""Kachel-Scan der Arbeitsfläche bei fester Höhe.

Statt eines einzelnen Weitwinkel-Snapshots (xTool) fährt der Kopf die Fläche
serpentinenförmig ab. Jede Kachel ist nah, scharf und maßgenau, weil die
Position aus der Maschine bekannt ist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Optional

import numpy as np

from .calibration import CameraCalibration
from .control import RunControl, Progress, EtaEstimator
from .geometry import Rect, MachineLimits, DEFAULT_LIMITS
from .interfaces import MachineInterface, CameraInterface


@dataclass(frozen=True)
class Tile:
    index: int
    row: int
    col: int
    view_center: tuple[float, float]   # Maschinenkoordinate der Bildmitte
    head: tuple[float, float]          # anzufahrende Laserpunkt-Position


@dataclass
class TilePlan:
    bounds: Rect
    scan_z: float
    overlap: float
    rows: int
    cols: int
    tiles: list[Tile]
    step_mm: tuple[float, float]
    warnings: list[str] = field(default_factory=list)
    uncovered: list[Rect] = field(default_factory=list)

    def estimate_seconds(self, xy_speed_mm_s: float = 150.0, z_speed_mm_s: float = 10.0,
                         settle_s: float = 0.35, capture_s: float = 0.25,
                         start: tuple[float, float] = (0.0, 0.0), start_z: float = 20.0) -> float:
        """Grobe Dauer inkl. Beschleunigungszuschlag (500 mm/s²)."""
        t = abs(self.scan_z - start_z) / z_speed_mm_s
        prev = start
        for tile in self.tiles:
            d = math.hypot(tile.head[0] - prev[0], tile.head[1] - prev[1])
            t += _move_time(d, xy_speed_mm_s, 500.0) + settle_s + capture_s
            prev = tile.head
        return t


def _move_time(d: float, vmax: float, acc: float) -> float:
    if d <= 0:
        return 0.0
    d_acc = vmax * vmax / acc
    if d < d_acc:
        return 2 * math.sqrt(d / acc)
    return 2 * vmax / acc + (d - d_acc) / vmax


def plan_tiles(bounds: Rect, calibration: CameraCalibration, overlap: float = 0.2,
               limits: MachineLimits = DEFAULT_LIMITS) -> TilePlan:
    """Serpentinen-Kachelraster, das ``bounds`` vollständig abdeckt.

    ``overlap`` ist der Anteil (0–0.8) der Überlappung benachbarter Kacheln.
    Bildmitten, deren Kopfposition außerhalb des Fahrbereichs läge, werden
    in den Fahrbereich geklemmt; die dadurch fehlende Fläche steht in
    ``uncovered`` und ``warnings``.
    """
    if not (0.0 <= overlap <= 0.8):
        raise ValueError("overlap must be between 0 and 0.8")
    fov_w, fov_h = calibration.usable_fov_mm
    step_w, step_h = fov_w * (1 - overlap), fov_h * (1 - overlap)
    cols = 1 if bounds.width <= fov_w else math.ceil((bounds.width - fov_w) / step_w) + 1
    rows = 1 if bounds.height <= fov_h else math.ceil((bounds.height - fov_h) / step_h) + 1
    xs = _centers(bounds.xmin, bounds.xmax, fov_w, cols)
    ys = _centers(bounds.ymin, bounds.ymax, fov_h, rows)
    tiles: list[Tile] = []
    warnings: list[str] = []
    clamped = 0
    for r, y in enumerate(ys):
        order = range(cols) if r % 2 == 0 else range(cols - 1, -1, -1)
        for c in order:
            x = xs[c]
            hx, hy = calibration.head_for_view_center(x, y)
            cx = min(max(hx, limits.x_min), limits.x_max)
            cy = min(max(hy, limits.y_min), limits.y_max)
            if (cx, cy) != (hx, hy):
                clamped += 1
            vc = (cx + calibration.offset_mm[0], cy + calibration.offset_mm[1])
            tiles.append(Tile(len(tiles), r, c, vc, (cx, cy)))
    uncovered = _uncovered(bounds, tiles, fov_w, fov_h)
    if clamped:
        warnings.append(f"{clamped} Kachel(n) an den Fahrbereich geklemmt (Kameraversatz).")
    if uncovered:
        miss = sum(u.area for u in uncovered)
        warnings.append(f"Nicht abgedeckt: ca. {miss:.0f} mm² am Rand (Kamera erreicht diesen Bereich nicht).")
    actual_step = (xs[1] - xs[0] if cols > 1 else 0.0, ys[1] - ys[0] if rows > 1 else 0.0)
    return TilePlan(bounds, calibration.scan_z, overlap, rows, cols, tiles, actual_step,
                    warnings, uncovered)


def _centers(lo: float, hi: float, fov: float, n: int) -> list[float]:
    if n == 1:
        return [(lo + hi) / 2]
    first, last = lo + fov / 2, hi - fov / 2
    return [first + (last - first) * i / (n - 1) for i in range(n)]


def _uncovered(bounds: Rect, tiles: list[Tile], fw: float, fh: float) -> list[Rect]:
    """Randstreifen, die keine Kachel abdeckt (Näherung über die Hülle)."""
    if not tiles:
        return [bounds]
    cover = Rect(min(t.view_center[0] for t in tiles) - fw / 2,
                 min(t.view_center[1] for t in tiles) - fh / 2,
                 max(t.view_center[0] for t in tiles) + fw / 2,
                 max(t.view_center[1] for t in tiles) + fh / 2)
    out = []
    eps = 0.05
    if cover.xmin > bounds.xmin + eps:
        out.append(Rect(bounds.xmin, bounds.ymin, cover.xmin, bounds.ymax))
    if cover.xmax < bounds.xmax - eps:
        out.append(Rect(cover.xmax, bounds.ymin, bounds.xmax, bounds.ymax))
    if cover.ymin > bounds.ymin + eps:
        out.append(Rect(max(bounds.xmin, cover.xmin), bounds.ymin, min(bounds.xmax, cover.xmax), cover.ymin))
    if cover.ymax < bounds.ymax - eps:
        out.append(Rect(max(bounds.xmin, cover.xmin), cover.ymax, min(bounds.xmax, cover.xmax), bounds.ymax))
    return out


@dataclass
class CapturedTile:
    tile: Tile
    image: np.ndarray            # bereits entzerrt
    timestamp: float


class TileScanner:
    """Fährt einen ``TilePlan`` ab und nimmt jede Kachel auf.

    ``settle_s`` wartet nach ``wait_idle`` auf das Ausschwingen des Kopfes
    (Bewegungsunschärfe ist der Hauptgrund für unscharfe Scans).
    """

    def __init__(self, machine: MachineInterface, camera: CameraInterface,
                 calibration: CameraCalibration, control: Optional[RunControl] = None,
                 settle_s: float = 0.15, travel_feed: float = 9000.0,
                 discard_frames: int = 0, sleep=time.sleep):
        self.machine = machine
        self.camera = camera
        self.calibration = calibration
        self.control = control or RunControl()
        self.settle_s = settle_s
        self.travel_feed = travel_feed
        self.discard_frames = discard_frames
        self._sleep = sleep

    def run(self, plan: TilePlan, start_index: int = 0) -> list[CapturedTile]:
        """Scan ausführen. ``start_index`` erlaubt Fortsetzen nach Abbruch."""
        ctl = self.control
        eta = EtaEstimator(len(plan.tiles), plan.estimate_seconds() / max(1, len(plan.tiles)))
        captured: list[CapturedTile] = []
        ctl.checkpoint()
        first = plan.tiles[start_index] if start_index < len(plan.tiles) else None
        if first is not None:
            # erst Z allein auf Scanhöhe, dann XY – nie schräg übers Material
            self.machine.move_to(None, None, plan.scan_z, None)
        for tile in plan.tiles[start_index:]:
            ctl.checkpoint()
            self.machine.move_to(tile.head[0], tile.head[1], None, self.travel_feed)
            self.machine.wait_idle()
            if self.settle_s:
                self._sleep(self.settle_s)
            for _ in range(self.discard_frames):
                self.camera.capture()  # alte Frames aus dem Kamerapuffer werfen
            raw = self.camera.capture()
            if raw is None or raw.size == 0:
                raise RuntimeError(f"Kamera lieferte kein Bild für Kachel {tile.index}")
            img = self.calibration.undistort(raw)
            captured.append(CapturedTile(tile, img, time.time()))
            done = tile.index + 1
            ctl.report(Progress("scan", done, len(plan.tiles),
                                f"Kachel {done}/{len(plan.tiles)}", eta.eta(done - start_index),
                                {"tile": tile, "image": img}))
        return captured
