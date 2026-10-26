"""G-Code für 3D-Relief (Graustufen-Tiefengravur in Schichten).

Verfahren (siehe docs/MATERIALS.md):

* Die Höhenkarte wird in ``layers`` gleich dicke Schichten zerlegt. In
  Schicht ``k`` bekommt jede Rasterzelle die Leistung
  ``clip((Tiefe − k·Schichtdicke) / Schichtdicke, 0, 1) · S_max`` – flache
  Zellen sind nach wenigen Schichten fertig, tiefe werden weiter abgetragen.
* Zeilen werden serpentinenartig gefahren, abwechselnd in X und Y
  (gleichmäßigerer Boden), mit Überlauf (``G1 … S0``) zum Beschleunigen.
* Zwischen den Schichten wird der Fokus relativ nachgeführt (``z_step``),
  am Ende wieder angehoben. Optional ein Schlichtdurchgang mit geringer,
  tiefenproportionaler Leistung zum Glätten.

Leistungsregelung: Der Pi (``pi400/marlin/transport.py``) erlaubt nur
Marlin-Inline-Laser ``M3 I`` mit ``S`` 0..255 je ``G1``; ``M4`` wird dort
abgelehnt. Das variable S pro Segment entspricht dem „dynamischen“ M4 von
GRBL. Für andere (GRBL-)Maschinen gibt es ``flavor="grbl_m4"`` (``M4``,
``S`` 0..1000) – **nicht** an den LumaCut-Pi senden.

Qt-frei: nutzt nur :mod:`lumacut_canvas.workarea` (Safezone-Versatz).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from lumacut_canvas.workarea import (WORK_HEIGHT_MM, WORK_WIDTH_MM, to_machine,
    MACHINE_X_MAX, MACHINE_X_MIN, MACHINE_Y_MAX, MACHINE_Y_MIN)

from .heightmap import Heightmap

MAX_FOCUS_DROP_MM = 3.0
# Erlaubter Bereich in Maschinen-mm (Nullpunkt oben rechts: to_machine(0, 0)
# ist jetzt die *größte* X-Koordinate, darum feste Grenzen statt Ecken).
_MIN_X, _MIN_Y, _MAX_X, _MAX_Y = MACHINE_X_MIN, MACHINE_Y_MIN, MACHINE_X_MAX, MACHINE_Y_MAX
_EPS = 1e-6
FLAVORS = ("marlin_inline", "grbl_m4")


def _xy(x: float, y: float) -> str:
    """Wie ``lumacut_canvas.gcode._xy`` (dort Qt-Import über export.py)."""
    if not (_MIN_X - _EPS <= x <= _MAX_X + _EPS and _MIN_Y - _EPS <= y <= _MAX_Y + _EPS):
        raise ValueError("Relief liegt außerhalb der Arbeitsfläche")
    x = min(max(x, _MIN_X), _MAX_X)
    y = min(max(y, _MIN_Y), _MAX_Y)
    return f"X{x:.3f} Y{y:.3f}"


@dataclass
class ReliefJob:
    heightmap: Heightmap
    x_mm: float                     # Arbeitsflächen-Position (oben links)
    y_mm: float
    layers: int
    speed_mm_min: float
    power_pct: float = 100.0        # Leistung bei voller Schichttiefe
    z_step_mm: float = 0.0          # Fokus-Absenkung je Schicht (ab Schicht 2)
    finish: bool = True
    finish_speed_mm_min: float = 0.0
    finish_power_pct: float = 30.0  # bei maximaler Tiefe, proportional
    overscan_mm: float = 2.0
    alternate_axes: bool = True
    power_levels: int = 16          # Quantisierung = weniger G-Code-Zeilen
    gap_rapid_mm: float = 1.0       # unbelichtete Lücken ab dieser Länge per G0
    flavor: str = "marlin_inline"
    name: str = "relief"

    def validate(self) -> None:
        if self.flavor not in FLAVORS:
            raise ValueError(f"Unbekannte G-Code-Variante: {self.flavor}")
        if not 1 <= self.layers <= 60:
            raise ValueError("Schichten 1..60")
        if not 1 <= self.speed_mm_min <= 6000 or not 0 < self.power_pct <= 100:
            raise ValueError("Ungültige Geschwindigkeit/Leistung")
        if self.finish and not 1 <= (self.finish_speed_mm_min or self.speed_mm_min) <= 6000:
            raise ValueError("Ungültige Schlicht-Geschwindigkeit")
        if not 2 <= self.power_levels <= 256:
            raise ValueError("power_levels 2..256")
        if self.z_step_mm < 0 or self.z_step_mm * (self.layers - 1) > MAX_FOCUS_DROP_MM + _EPS:
            raise ValueError(f"Fokus-Absenkung zu groß (max. {MAX_FOCUS_DROP_MM:g} mm gesamt)")
        hm = self.heightmap
        if not (0 <= self.x_mm and 0 <= self.y_mm and self.x_mm + hm.width_mm <= WORK_WIDTH_MM + _EPS
                and self.y_mm + hm.height_mm <= WORK_HEIGHT_MM + _EPS):
            raise ValueError("Relief liegt außerhalb der Arbeitsfläche")


@dataclass
class ReliefStats:
    lines: int = 0
    passes: int = 0
    burn_mm: float = 0.0
    travel_mm: float = 0.0
    est_seconds: float = 0.0
    pass_lengths: list[int] = field(default_factory=list)


def layer_fractions(depth: np.ndarray, layers: int, k: int) -> np.ndarray:
    """Leistungsanteil 0..1 je Zelle für Schicht ``k`` (0-basiert)."""
    dmax = float(depth.max()) if depth.size else 0.0
    if dmax <= 0:
        return np.zeros_like(depth)
    ld = dmax / layers
    return np.clip((depth - k * ld) / ld, 0.0, 1.0)


class _Writer:
    def __init__(self, job: ReliefJob, stats: ReliefStats) -> None:
        self.job = job
        self.out: list[str] = []
        self.stats = stats
        self.pos: tuple[float, float] | None = None
        self.smax = 1000 if job.flavor == "grbl_m4" else 255

    def _dist(self, x: float, y: float) -> float:
        if self.pos is None:
            return 0.0
        return math.hypot(x - self.pos[0], y - self.pos[1])

    def rapid(self, x: float, y: float) -> None:
        d = self._dist(x, y)
        self.stats.travel_mm += d
        self.stats.est_seconds += d / 3000 * 60  # grobe Annahme Eilgang
        self.out.append(f"G0 {_xy(*to_machine(x, y))}")
        self.pos = (x, y)

    def cut(self, x: float, y: float, s: int, feed: float) -> None:
        d = self._dist(x, y)
        if s > 0:
            self.stats.burn_mm += d
        self.stats.est_seconds += d / feed * 60
        self.out.append(f"G1 {_xy(*to_machine(x, y))} F{feed:g} S{s}")
        self.pos = (x, y)


def _runs(values: np.ndarray) -> list[tuple[int, int, int]]:
    """(start, end_exkl, wert) für Läufe gleicher Werte."""
    if values.size == 0:
        return []
    change = np.flatnonzero(np.diff(values)) + 1
    starts = np.concatenate([[0], change])
    ends = np.concatenate([change, [values.size]])
    return [(int(a), int(b), int(values[a])) for a, b in zip(starts, ends)]


def _raster_pass(w: _Writer, s_grid: np.ndarray, along_x: bool, feed: float) -> None:
    job, hm = w.job, w.job.heightmap
    px = hm.pixel_mm
    grid = s_grid if along_x else s_grid.T
    n_lines, n_cells = grid.shape
    hi_limit = (WORK_WIDTH_MM - job.x_mm) if along_x else (WORK_HEIGHT_MM - job.y_mm)
    lo_limit = -(job.x_mm if along_x else job.y_mm)
    gap_cells = max(1, int(math.ceil(job.gap_rapid_mm / px)))
    forward = True
    for li in range(n_lines):
        row = grid[li]
        if not row.any():
            continue
        nz = np.flatnonzero(row)
        first, last = int(nz[0]), int(nz[-1]) + 1
        across = (li + 0.5) * px
        runs = [(a + first, b + first, v) for a, b, v in _runs(row[first:last])]
        if not forward:
            runs = [(b, a, v) for a, b, v in reversed(runs)]  # Start/Ende vertauscht

        def pt(cell_edge: float):
            along = cell_edge * px
            return ((job.x_mm + along, job.y_mm + across) if along_x
                    else (job.x_mm + across, job.y_mm + along))

        sign = 1 if forward else -1
        start_edge = runs[0][0]
        over = min(job.overscan_mm, (start_edge * px - lo_limit) if forward
                   else (hi_limit - start_edge * px))
        over = max(0.0, over)
        w.rapid(*pt(start_edge - sign * over / px))
        if over > 0:
            w.cut(*pt(start_edge), 0, feed)
        for a, b, v in runs:
            if v == 0 and abs(b - a) >= gap_cells:
                w.rapid(*pt(b))
                continue
            w.cut(*pt(b), v, feed)
        end_edge = runs[-1][1]
        over = min(job.overscan_mm, (hi_limit - end_edge * px) if forward
                   else (end_edge * px - lo_limit))
        if over > 0:
            w.cut(*pt(end_edge + sign * over / px), 0, feed)
        forward = not forward


def relief_to_gcode(job: ReliefJob) -> tuple[str, ReliefStats]:
    """G-Code und Statistik für ein Relief."""
    job.validate()
    hm = job.heightmap
    stats = ReliefStats()
    w = _Writer(job, stats)
    levels = job.power_levels - 1
    if job.flavor == "grbl_m4":
        head = ["; LUMACUT RELIEF (GRBL M4 dynamic power - NOT for the LumaCut Pi)",
                "G21", "G90", "M5", "M4 S0"]
        tail = ["M5"]
    else:
        head = ["; LUMACUT RELIEF JOB (homing, focus and park run on the Pi)",
                "G21", "G90", "M5 I", "M3 I"]
        tail = ["M5 I", "M400"]
    w.out += head
    w.out.append(f"; {hm.cols}x{hm.rows} cells {hm.pixel_mm:g} mm, depth {hm.max_depth_mm:.2f} mm, "
                 f"{job.layers} layers")

    def quant(frac: np.ndarray, pct: float) -> np.ndarray:
        q = np.round(frac * levels) / levels
        return np.round(q * pct / 100.0 * w.smax).astype(np.int32)

    drop = 0.0
    n_pass = 0
    for k in range(job.layers):
        s_grid = quant(layer_fractions(hm.depth, job.layers, k), job.power_pct)
        if not s_grid.any():
            break
        if k and job.z_step_mm > 0:
            w.out += ["G91", f"G0 Z{-job.z_step_mm:.3f} F600", "G90"]
            drop += job.z_step_mm
        along_x = not (job.alternate_axes and k % 2)
        w.out.append(f"; PASS {k + 1} OF {job.layers} ({'X' if along_x else 'Y'})")
        before = len(w.out)
        _raster_pass(w, s_grid, along_x, job.speed_mm_min)
        stats.pass_lengths.append(len(w.out) - before)
        n_pass += 1
    if job.finish and hm.max_depth_mm > 0:
        frac = hm.depth / hm.max_depth_mm
        s_grid = quant(frac, job.finish_power_pct)
        if s_grid.any():
            along_x = not (job.alternate_axes and n_pass % 2)
            w.out.append(f"; FINISH ({'X' if along_x else 'Y'})")
            before = len(w.out)
            _raster_pass(w, s_grid, along_x, job.finish_speed_mm_min or job.speed_mm_min)
            stats.pass_lengths.append(len(w.out) - before)
            n_pass += 1
    if drop > 0:
        w.out += ["G91", f"G0 Z{drop:.3f} F600", "G90"]
    w.out += tail
    stats.passes = n_pass
    stats.lines = len(w.out)
    return "\n".join(w.out) + "\n", stats


def job_from_plan(plan, heightmap: Heightmap, x_mm: float, y_mm: float, **kw) -> ReliefJob:
    """ReliefJob aus einem :class:`~lumacut_materials.planner.ReliefPlan`."""
    return ReliefJob(heightmap=heightmap, x_mm=x_mm, y_mm=y_mm, layers=plan.passes,
                     speed_mm_min=plan.speed_mm_min, power_pct=plan.power_pct,
                     z_step_mm=plan.z_step_mm, finish_speed_mm_min=plan.finish_speed_mm_min,
                     finish_power_pct=plan.finish_power_pct, **kw)
