"""Raster and sliced-depth (2.5D) engraving planner.

Turns a grayscale image (numpy ``uint8``, 0 = black = most burn / deepest)
into Pi-safe Marlin laser G-code:

* modes ``threshold``, ``floyd`` (Floyd-Steinberg), ``atkinson``,
  ``ordered`` (Bayer 4x4), ``jarvis`` (Jarvis-Judice-Ninke), ``stucki``,
  ``sierra`` (three-row Sierra), ``halftone`` (round dots in rotated cells,
  ``halftone_cpi`` cells per inch at ``halftone_angle``) and ``newsprint``
  (45° clustered-dot screen with a fixed cell of a few pixels) -> on/off dots
  at full layer power (the LightBurn / xTool image modes);
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
``dot_width_mm`` (LightBurn "Dot Width Correction") shortens every burning run
by half the value at each end where it borders an unburned pixel, so the beam
width does not make dots and lines wider than the pixels; 0 = unchanged.

Coordinates: ``origin`` is the machine-mm position of the image's top-left
pixel; image rows go towards +Y (same as the canvas).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lumacut_canvas.workarea import (WORK_HEIGHT_MM, WORK_WIDTH_MM, to_machine,
    MACHINE_X_MAX, MACHINE_X_MIN, MACHINE_Y_MAX, MACHINE_Y_MIN)

PWM_MAX = 255
MODES = ("threshold", "floyd", "atkinson", "ordered", "grayscale",
         "jarvis", "stucki", "sierra", "halftone", "newsprint")
#: On/off modes based on error diffusion (the slow, sequential ones).
DIFFUSION_MODES = ("floyd", "atkinson", "jarvis", "stucki", "sierra")
HALFTONE_CPI_RANGE = (5.0, 150.0)     # cells per inch (LightBurn "Cells per Inch")
HALFTONE_ANGLE_RANGE = (-90.0, 90.0)  # degrees
NEWSPRINT_CELL_PX = 6 * 2 ** 0.5      # 45° screen: 6 px along the image axes
MAX_DEPTH_DROP_MM = 3.0  # same budget as the canvas focus drop limit

# Erlaubter Bereich in Maschinen-mm (Nullpunkt oben rechts: to_machine(0, 0)
# ist jetzt die *größte* X-Koordinate, darum feste Grenzen statt Ecken).
_MIN_X, _MIN_Y, _MAX_X, _MAX_Y = MACHINE_X_MIN, MACHINE_Y_MIN, MACHINE_X_MAX, MACHINE_Y_MAX

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
    halftone_cpi: float = 30.0        # halftone: cells per inch
    halftone_angle: float = 45.0      # halftone: screen angle in degrees
    dot_width_mm: float = 0.0         # dot width correction (0 = off)

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
        lo, hi = HALFTONE_CPI_RANGE
        if not lo <= self.halftone_cpi <= hi:
            raise ValueError(f"Raster-Zellen {lo:g}..{hi:g} je Zoll")
        lo, hi = HALFTONE_ANGLE_RANGE
        if not lo <= self.halftone_angle <= hi:
            raise ValueError(f"Raster-Winkel {lo:g}..{hi:g}°")
        if not 0 <= self.dot_width_mm <= self.line_interval_mm + 1e-9:
            raise ValueError("Punktbreitenkorrektur 0..Linienabstand")


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


def _kernel(rows: list[list[int]], divisor: int) -> list[tuple[int, int, float]]:
    """Diffusion weights from a 5-wide table; row 0 holds only the two right taps."""
    out = []
    for dy, row in enumerate(rows):
        offs = (1, 2) if dy == 0 else (-2, -1, 0, 1, 2)
        out += [(dx, dy, w / divisor) for dx, w in zip(offs, row) if w]
    return out


_JARVIS = _kernel([[7, 5], [3, 5, 7, 5, 3], [1, 3, 5, 3, 1]], 48)
_STUCKI = _kernel([[8, 4], [2, 4, 8, 4, 2], [1, 2, 4, 2, 1]], 42)
_SIERRA = _kernel([[5, 3], [2, 4, 5, 4, 2], [0, 2, 3, 2, 0]], 32)
_KERNELS = {"floyd": _FLOYD, "atkinson": _ATKINSON, "jarvis": _JARVIS, "stucki": _STUCKI,
            "sierra": _SIERRA}


def _error_diffuse_rows(darkness: np.ndarray, kernel: list[tuple[int, int, float]]) -> np.ndarray:
    """Error diffusion, one row at a time.

    Same algorithm as :func:`_error_diffuse` (left to right, error clipped at
    the image edges), but only the taps in the current row run in a Python
    loop; the taps into the rows below are added with one numpy operation per
    tap and row. About 3-6x faster for the wide Jarvis / Stucki / Sierra
    kernels. Used for the newer modes only, so Floyd-Steinberg and Atkinson
    stay bit-identical to older releases.
    """
    img = darkness.astype(np.float64).copy()
    h, w = img.shape
    out = np.zeros((h, w), dtype=bool)
    same = [(dx, f) for dx, dy, f in kernel if dy == 0]
    below = [(dx, dy, f) for dx, dy, f in kernel if dy > 0]
    for y in range(h):
        row = img[y].tolist()
        on_row = [False] * w
        err = [0.0] * w
        for x in range(w):
            v = row[x]
            on = v >= 0.5
            on_row[x] = on
            e = v - 1.0 if on else v
            err[x] = e
            for dx, f in same:
                if x + dx < w:
                    row[x + dx] += e * f
        out[y] = on_row
        ev = np.asarray(err)
        for dx, dy, f in below:
            yy = y + dy
            if yy >= h:
                continue
            if dx >= 0:
                img[yy, dx:] += ev[:w - dx] * f
            else:
                img[yy, :w + dx] += ev[-dx:] * f
    return out


def _cell_coverage(d: np.ndarray) -> np.ndarray:
    """Share of a unit cell within distance ``d`` of its centre (0..1).

    A round dot of radius ``d`` covers ``pi d²`` up to ``d = 0.5``; beyond that
    the four parts outside the cell are subtracted until the dot fills the cell
    at ``d = sqrt(0.5)``. Comparing it with the darkness turns darkness 0.3 into
    a dot covering 30 % of the cell.
    """
    d = np.minimum(d, 0.5 ** 0.5)
    area = np.pi * d * d
    big = d > 0.5
    if np.any(big):
        db = d[big]
        seg = db * db * np.arccos(0.5 / db) - 0.5 * np.sqrt(db * db - 0.25)
        area[big] -= 4 * seg
    return np.clip(area, 0.0, 1.0)


def _screen(shape: tuple[int, int], cell_px: float, angle_deg: float):
    """Cell coordinates of every pixel centre in a screen rotated by ``angle_deg``.

    Returns (cell index u, cell index v, distance to the cell centre in cell units).
    """
    h, w = shape
    a = np.radians(angle_deg)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    xx += 0.5
    yy += 0.5
    u = (xx * np.cos(a) + yy * np.sin(a)) / cell_px
    v = (-xx * np.sin(a) + yy * np.cos(a)) / cell_px
    iu, iv = np.floor(u), np.floor(v)
    d = np.hypot(u - iu - 0.5, v - iv - 0.5)
    return iu.astype(np.int64), iv.astype(np.int64), d


def _halftone(darkness: np.ndarray, cell_px: float, angle_deg: float) -> np.ndarray:
    """Amplitude-modulated halftone: one round dot per cell, area = mean darkness of the cell."""
    if darkness.size == 0:
        return np.zeros(darkness.shape, dtype=bool)
    iu, iv, dist = _screen(darkness.shape, max(cell_px, 1.0), angle_deg)
    iu -= iu.min()
    iv -= iv.min()
    key = (iu * (int(iv.max()) + 1) + iv).ravel()
    flat = darkness.astype(np.float64).ravel()
    sums = np.bincount(key, weights=flat)
    counts = np.bincount(key)
    mean = (sums / np.maximum(counts, 1))[key].reshape(darkness.shape)
    cov = _cell_coverage(dist)
    return (mean > 1e-6) & ((cov < mean) | (mean >= 1.0 - 1e-6))


def _newsprint_tile() -> np.ndarray:
    """12×12 threshold tile of the newsprint screen (two 45° cells of 72 pixels).

    Pixels are ranked by their distance to the cell centre (ties by angle), so
    darkness k/72 burns exactly k pixels per cell: the dot grows from the
    centre and the tone stays exact.
    """
    h = w = 12
    a = np.radians(45.0)
    yy, xx = np.mgrid[0:h, 0:w] + 0.5
    # u = (x + y + 1) / 12 lands pixel centres on cell borders; half a step
    # more puts them symmetric inside the cells (72 pixels per cell exactly).
    u = (xx * np.cos(a) + yy * np.sin(a)) / NEWSPRINT_CELL_PX + 0.5 / 12
    v = (-xx * np.sin(a) + yy * np.cos(a)) / NEWSPRINT_CELL_PX + 0.5 / 12
    fu, fv = u - np.floor(u) - 0.5, v - np.floor(v) - 0.5
    d = np.hypot(fu, fv)
    # Shifting by 12 px moves the cell index by (1, ±1): two cell classes per tile.
    key = ((np.floor(u) + np.floor(v)).astype(int) % 2).ravel()
    ang = np.arctan2(fv, fu).ravel()
    thr = np.zeros(144)
    for k in np.unique(key):
        idx = np.nonzero(key == k)[0]
        idx = idx[np.lexsort((ang[idx], np.round(d.ravel()[idx], 9)))]
        thr[idx] = (np.arange(idx.size) + 0.5) / 72.0
    return thr.reshape(12, 12)


_NEWSPRINT = None


def _newsprint(darkness: np.ndarray) -> np.ndarray:
    """Clustered-dot screen (45°, 72-pixel cells): each pixel against its dot threshold."""
    global _NEWSPRINT
    if _NEWSPRINT is None:
        _NEWSPRINT = _newsprint_tile()
    h, w = darkness.shape
    tile = np.tile(_NEWSPRINT, (h // 12 + 1, w // 12 + 1))[:h, :w]
    return (darkness > tile) | (darkness >= 1.0 - 1e-6)


def halftone_cell_px(s: "RasterSettings") -> float:
    """Halftone cell edge in pixels (= line intervals)."""
    return 25.4 / s.halftone_cpi / s.line_interval_mm


def dot_mask(darkness: np.ndarray, s: "RasterSettings") -> np.ndarray:
    """On/off pattern for the binary modes (``darkness`` 0..1, 1 = black)."""
    if s.mode == "threshold":
        return darkness >= (255 - s.threshold) / 255.0
    if s.mode == "ordered":
        h, w = darkness.shape
        tile = np.tile((_BAYER4 + 0.5) / 16.0, (h // 4 + 1, w // 4 + 1))[:h, :w]
        return darkness > tile
    if s.mode in ("floyd", "atkinson"):
        return _error_diffuse(darkness, _KERNELS[s.mode])
    if s.mode in _KERNELS:
        return _error_diffuse_rows(darkness, _KERNELS[s.mode])
    if s.mode == "halftone":
        return _halftone(darkness, halftone_cell_px(s), s.halftone_angle)
    if s.mode == "newsprint":
        return _newsprint(darkness)
    raise ValueError(f"Kein Punktmodus: {s.mode}")


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
    on = dot_mask(darkness, s)
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
        runs = _dot_width(runs, s.dot_width_mm / px) if s.dot_width_mm > 0 else runs
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


MIN_DOT_PX = 0.1   # a burning run never gets shorter than this (in pixels)


def _dot_width(runs: list, dw_px: float) -> list:
    """Shorten burning runs by ``dw_px / 2`` at every edge next to an unburned pixel.

    ``runs`` = ``(start, end, power)`` in pixel units, ascending. The unburned
    neighbour grows by the same amount (the head keeps moving at ``S0``), the
    row ends move inward. A run keeps at least ``MIN_DOT_PX`` so single dots
    still burn. Neighbouring runs with different power (grayscale) keep their
    common edge.
    """
    n = len(runs)
    edges = [float(runs[0][0])] + [float(b) for _a, b, _v in runs]
    half = dw_px / 2
    starts = list(edges[:-1])
    ends = list(edges[1:])
    for i, (_a, _b, v) in enumerate(runs):
        if not v:
            continue
        cut_l = i == 0 or runs[i - 1][2] == 0
        cut_r = i == n - 1 or runs[i + 1][2] == 0
        k = int(cut_l) + int(cut_r)
        if not k:
            continue
        length = ends[i] - starts[i]
        cut = min(half, max(0.0, (length - MIN_DOT_PX) / k))
        if cut_l:
            starts[i] += cut
        if cut_r:
            ends[i] -= cut
    out = []
    prev = starts[0]
    for i, (_a, _b, v) in enumerate(runs):
        if v:
            if starts[i] > prev + 1e-9:
                out.append((prev, starts[i], 0))
            out.append((starts[i], ends[i], v))
            prev = ends[i]
        else:
            nxt = starts[i + 1] if i + 1 < n else ends[i]
            # a zero run is never first or last (rows are trimmed to burning pixels)
            out.append((prev, nxt, 0))
            prev = nxt
    # merge zero runs that touch (a dropped empty gap) and drop zero-length ones
    merged: list = []
    for a, b, v in out:
        if b - a <= 1e-9 and not v:
            continue
        if merged and merged[-1][2] == v == 0:
            merged[-1] = (merged[-1][0], b, 0)
        else:
            merged.append((a, b, v))
    return merged


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
