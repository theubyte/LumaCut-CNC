"""Raster and sliced-depth (2.5D) engraving planner.

Turns a grayscale image (numpy ``uint8``, 0 = black = most burn / deepest)
into Pi-safe Marlin laser G-code:

* modes ``threshold``, ``floyd`` (Floyd-Steinberg), ``atkinson``,
  ``ordered`` (Bayer 4x4) -> on/off dots at full layer power;
* mode ``grayscale`` -> per-pixel ``S`` between ``min_power`` and ``power``;
* :func:`depth_slices` + :func:`sliced_depth_gcode` -> multi-pass depth
  engraving from a height map: pass *k* burns every pixel whose darkness is
  at least *k*/N, so dark areas get more passes and end up deeper (the same
  idea as LightBurn's "3D Sliced" image mode, which LightBurn offers for
  Galvo only, and xTool's 3D engraving from depth maps). Optional
  ``z_step_mm`` lowers the focus between slices (relative ``G91`` Z moves;
  the Pi enforces its Z floor).

Scanlines run along X with optional bidirectional scanning, ``overscan_mm``
lead-in/lead-out at ``S0`` and ``scan_offset_mm`` compensation for the
reverse direction (LightBurn "Scanning Offset Adjustment"). Runs of equal
power are merged into one ``G1`` to keep the serial stream small.

Coordinates: ``origin`` is the machine-mm position of the image's top-left
pixel; image rows go towards +Y (same as the canvas).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, to_machine

PWM_MAX = 255
MODES = ("threshold", "floyd", "atkinson", "ordered", "grayscale")
MAX_DEPTH_DROP_MM = 3.0  # same budget as the canvas focus drop limit

_MIN_X, _MIN_Y = to_machine(0.0, 0.0)
_MAX_X, _MAX_Y = to_machine(WORK_WIDTH_MM, WORK_HEIGHT_MM)

_BAYER4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
                   dtype=np.float32)


@dataclass
class RasterSettings:
    line_interval_mm: float = 0.1     # 254 DPI
    power: float = 60.0               # % at black
    min_power: float = 0.0            # % at white (grayscale mode)
    speed_mm_min: float = 3000.0
    mode: str = "floyd"
    threshold: int = 128
    bidirectional: bool = True
    overscan_mm: float = 3.0
    scan_offset_mm: float = 0.0       # shift of reverse lines (+X)
    negative: bool = False

    def validate(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"Unbekannter Rastermodus: {self.mode}")
        if not 0.03 <= self.line_interval_mm <= 2.0:
            raise ValueError("Linienabstand 0.03..2 mm")
        if not 1 <= self.power <= 100 or not 0 <= self.min_power <= self.power:
            raise ValueError("Leistung 1..100 %, Minimum <= Maximum")
        if not 1 <= self.speed_mm_min <= 6000:
            raise ValueError("Geschwindigkeit 1..6000 mm/min")
        if not 0 <= self.overscan_mm <= 20 or abs(self.scan_offset_mm) > 2:
            raise ValueError("Overscan 0..20 mm, Scan-Versatz -2..2 mm")


def resample(gray: np.ndarray, width_mm: float, height_mm: float, interval_mm: float) -> np.ndarray:
    """Nearest-neighbour resample so that one pixel = ``interval_mm`` square."""
    gray = np.asarray(gray)
    if gray.ndim != 2:
        raise ValueError("Graustufenbild (2D) erwartet")
    cols = max(1, int(round(width_mm / interval_mm)))
    rows = max(1, int(round(height_mm / interval_mm)))
    yi = np.minimum((np.arange(rows) + 0.5) * gray.shape[0] / rows, gray.shape[0] - 1).astype(int)
    xi = np.minimum((np.arange(cols) + 0.5) * gray.shape[1] / cols, gray.shape[1] - 1).astype(int)
    return gray[yi][:, xi].astype(np.uint8)


def _error_diffuse(darkness: np.ndarray, kernel: list[tuple[int, int, float]]) -> np.ndarray:
    img = darkness.astype(np.float32).copy()
    h, w = img.shape
    out = np.zeros((h, w), dtype=bool)
    for y in range(h):
        for x in range(w):
            old = img[y, x]
            on = old >= 0.5
            out[y, x] = on
            err = old - (1.0 if on else 0.0)
            for dx, dy, f in kernel:
                xx, yy = x + dx, y + dy
                if 0 <= xx < w and yy < h:
                    img[yy, xx] += err * f
    return out


_FLOYD = [(1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16)]
_ATKINSON = [(1, 0, 1 / 8), (2, 0, 1 / 8), (-1, 1, 1 / 8), (0, 1, 1 / 8), (1, 1, 1 / 8), (0, 2, 1 / 8)]


def power_map(gray: np.ndarray, s: RasterSettings) -> np.ndarray:
    """Per-pixel ``S`` (0..255, int) for the given mode."""
    s.validate()
    g = np.asarray(gray, dtype=np.float32)
    darkness = (g if s.negative else 255.0 - g) / 255.0
    full = round(s.power / 100 * PWM_MAX)
    if s.mode == "grayscale":
        lo = s.min_power / 100 * PWM_MAX
        sval = np.where(darkness > 1e-3, lo + darkness * (full - lo), 0.0)
        return np.rint(sval).astype(int)
    if s.mode == "threshold":
        on = darkness >= (255 - s.threshold) / 255.0
    elif s.mode == "ordered":
        h, w = darkness.shape
        tile = np.tile((_BAYER4 + 0.5) / 16.0, (h // 4 + 1, w // 4 + 1))[:h, :w]
        on = darkness > tile
    elif s.mode == "floyd":
        on = _error_diffuse(darkness, _FLOYD)
    else:
        on = _error_diffuse(darkness, _ATKINSON)
    return np.where(on, full, 0).astype(int)


def _fmt(x: float, y: float) -> str:
    if not (_MIN_X - 1e-6 <= x <= _MAX_X + 1e-6 and _MIN_Y - 1e-6 <= y <= _MAX_Y + 1e-6):
        raise ValueError("Raster (inkl. Overscan) außerhalb der Arbeitsfläche")
    return f"X{x:.3f} Y{y:.3f}"


def scanlines(spower: np.ndarray, origin: tuple[float, float], s: RasterSettings,
              speed: float | None = None) -> list[str]:
    """G-code lines (no header) for one raster pass of a power map."""
    f = f"{(speed or s.speed_mm_min):g}"
    px = s.line_interval_mm
    ox, oy = origin
    out: list[str] = []
    forward = True
    for r in range(spower.shape[0]):
        row = spower[r]
        nz = np.nonzero(row)[0]
        if nz.size == 0:
            continue
        c0, c1 = int(nz[0]), int(nz[-1]) + 1
        y = oy + (r + 0.5) * px
        shift = 0.0 if forward else s.scan_offset_mm
        # Runs of equal power between c0 and c1.
        runs: list[tuple[int, int, int]] = []
        start = c0
        for c in range(c0 + 1, c1 + 1):
            if c == c1 or row[c] != row[start]:
                runs.append((start, c, int(row[start])))
                start = c
        if not forward:
            runs = [(b, a, v) for a, b, v in reversed(runs)]
        sign = 1 if forward else -1
        first_x = ox + runs[0][0] * px + shift
        out.append(f"G0 {_fmt(first_x - sign * s.overscan_mm, y)}")
        if s.overscan_mm:
            out.append(f"G1 {_fmt(first_x, y)} F{f} S0")
        for a, b, v in runs:
            out.append(f"G1 {_fmt(ox + b * px + shift, y)} F{f} S{v}")
        if s.overscan_mm:
            last_x = ox + runs[-1][1] * px + shift
            out.append(f"G1 {_fmt(last_x + sign * s.overscan_mm, y)} F{f} S0")
        if s.bidirectional:
            forward = not forward
    return out


def _header(title: str) -> list[str]:
    return [f"; LUMACUT {title} (homing, focus and park run on the Pi)",
            "G21", "G90", "M5 I", "M3 I"]


def raster_gcode(gray: np.ndarray, origin: tuple[float, float], width_mm: float,
                 height_mm: float, s: RasterSettings, passes: int = 1) -> str:
    """Complete job for one raster image (``origin`` = top-left, machine mm)."""
    if not 1 <= passes <= 30:
        raise ValueError("Durchgänge 1..30")
    pm = power_map(resample(gray, width_mm, height_mm, s.line_interval_mm), s)
    body = scanlines(pm, origin, s)
    if not body:
        raise ValueError("Bild enthält nichts zu gravieren")
    out = _header("RASTER JOB")
    for p in range(passes):
        out.append(f"; PASS {p + 1} OF {passes}")
        out += body
    out += ["M5 I", "M400"]
    return "\n".join(out) + "\n"


def depth_slices(height: np.ndarray, levels: int, negative: bool = False) -> list[np.ndarray]:
    """Boolean masks for sliced depth engraving (pass 1 = widest area).

    ``height``: 0 = black = deepest (like LightBurn's 3D Sliced convention),
    255 = white = untouched. Pixel darkness d in 0..1 is burned in every
    slice k (1..levels) with d >= k / levels - 1/(2*levels).
    """
    if not 2 <= levels <= 64:
        raise ValueError("2..64 Tiefenstufen")
    g = np.asarray(height, dtype=np.float32)
    d = (g if negative else 255.0 - g) / 255.0
    q = np.rint(d * levels).astype(int)  # 0..levels passes per pixel
    return [q >= k for k in range(1, levels + 1)]


def sliced_depth_gcode(height: np.ndarray, origin: tuple[float, float], width_mm: float,
                       height_mm: float, s: RasterSettings, levels: int = 8,
                       z_step_mm: float = 0.0) -> str:
    """Multi-pass depth engraving: one constant-power raster pass per slice.

    Deeper areas are engraved more often. With ``z_step_mm`` the focus is
    lowered by that amount after each slice (relative ``G91``/``G0 Z``) and
    restored at the end; the total drop is limited to
    ``MAX_DEPTH_DROP_MM``. Slice direction alternates by 90° is *not* done
    (Marlin raster only along X); instead odd slices start bottom-up to
    spread heat.
    """
    s.validate()
    if not 0 <= z_step_mm <= 2:
        raise ValueError("Z-Schritt 0..2 mm")
    drop = z_step_mm * (levels - 1)
    if drop > MAX_DEPTH_DROP_MM + 1e-9:
        raise ValueError(f"Fokus-Absenkung zu groß ({drop:.2f} mm > {MAX_DEPTH_DROP_MM:g} mm)")
    g = resample(height, width_mm, height_mm, s.line_interval_mm)
    full = round(s.power / 100 * PWM_MAX)
    masks = depth_slices(g, levels, s.negative)
    out = _header(f"SLICED DEPTH JOB {levels} LEVELS")
    any_work = False
    for k, mask in enumerate(masks):
        if not mask.any():
            continue
        if k and z_step_mm and any_work:
            out += ["G91", f"G0 Z{-z_step_mm:.3f} F600", "G90"]
        pm = np.where(mask, full, 0).astype(int)
        if k % 2:
            # Engrave bottom-up: flip rows and mirror the origin.
            lines = scanlines(pm[::-1], origin, s)
            rows = pm.shape[0]
            lines = [_flip_y(line, origin[1], rows * s.line_interval_mm) for line in lines]
        else:
            lines = scanlines(pm, origin, s)
        out.append(f"; SLICE {k + 1} OF {levels}")
        out += lines
        any_work = True
    if not any_work:
        raise ValueError("Höhenkarte enthält nichts zu gravieren")
    used = sum(1 for m in masks if m.any())
    if z_step_mm and used > 1:
        out += ["G91", f"G0 Z{z_step_mm * (used - 1):.3f} F600", "G90"]
    out += ["M5 I", "M400"]
    return "\n".join(out) + "\n"


def _flip_y(line: str, oy: float, h: float) -> str:
    head, _, rest = line.partition(" Y")
    yval, _, tail = rest.partition(" ")
    y = oy + h - (float(yval) - oy)
    return f"{head} Y{y:.3f}" + (f" {tail}" if tail else "")
