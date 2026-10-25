"""Höhenkarte für 3D-Relief aus einem Bild.

Konvention: **weiß = hoch (Oberfläche, nicht gelasert), schwarz = tief**.
``invert`` dreht das um (z. B. für Tiefenkarten aus 3D-Programmen, in denen
weiß = nah/tief bedeutet).

Reines numpy; OpenCV wird nur zum Laden von Bilddateien (lazy) benutzt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class HeightmapOptions:
    width_mm: float
    height_mm: float | None = None   # None = Seitenverhältnis des Bildes
    line_interval_mm: float = 0.1    # Rasterabstand = Pixelgröße in mm
    depth_mm: float = 1.0            # maximale Tiefe (schwarz)
    gamma: float = 1.0               # >1 hebt Mitteltöne an (flacher), <1 vertieft
    contrast: float = 1.0            # um 0,5 gespreizt
    brightness: float = 0.0          # -1..1, addiert
    invert: bool = False
    blur_mm: float = 0.0             # Gauß-Glättung (Sigma in mm) gegen Treppen/Rauschen

    def validate(self) -> None:
        if self.width_mm <= 0 or (self.height_mm is not None and self.height_mm <= 0):
            raise ValueError("Breite/Höhe müssen > 0 sein")
        if not 0.02 <= self.line_interval_mm <= 2.0:
            raise ValueError("Zeilenabstand muss zwischen 0,02 und 2 mm liegen")
        if not 0 < self.depth_mm <= 20:
            raise ValueError("Tiefe muss zwischen 0 und 20 mm liegen")
        if self.gamma <= 0 or self.contrast < 0:
            raise ValueError("Gamma muss > 0, Kontrast ≥ 0 sein")


@dataclass
class Heightmap:
    """Tiefe je Rasterzelle in mm (0 = Oberfläche), Zeilen = Y, Spalten = X."""

    depth: np.ndarray
    pixel_mm: float

    @property
    def rows(self) -> int:
        return int(self.depth.shape[0])

    @property
    def cols(self) -> int:
        return int(self.depth.shape[1])

    @property
    def width_mm(self) -> float:
        return self.cols * self.pixel_mm

    @property
    def height_mm(self) -> float:
        return self.rows * self.pixel_mm

    @property
    def max_depth_mm(self) -> float:
        return float(self.depth.max()) if self.depth.size else 0.0


def load_gray(path: str | Path) -> np.ndarray:
    """Bilddatei → Graustufen float 0..1 (Transparenz zählt als weiß)."""
    import cv2  # lazy: nur für Dateien nötig

    data = np.fromfile(str(path), dtype=np.uint8)  # Windows-Pfade mit Umlauten
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"Bild nicht lesbar: {path}")
    return to_gray(img)


def to_gray(img: np.ndarray) -> np.ndarray:
    """uint8/uint16/float-Bild (Gray, BGR, BGRA) → float 0..1."""
    a = np.asarray(img)
    if a.dtype == np.uint8:
        f = a.astype(np.float64) / 255.0
    elif a.dtype == np.uint16:
        f = a.astype(np.float64) / 65535.0
    else:
        f = np.clip(a.astype(np.float64), 0.0, 1.0)
    alpha = None
    if f.ndim == 3:
        if f.shape[2] == 4:
            alpha = f[:, :, 3]
            f = f[:, :, :3]
        if f.shape[2] >= 3:  # BGR (OpenCV) – Luma nach Rec. 601
            f = 0.114 * f[:, :, 0] + 0.587 * f[:, :, 1] + 0.299 * f[:, :, 2]
        else:
            f = f[:, :, 0]
    if alpha is not None:
        f = f * alpha + (1.0 - alpha)
    return f


def _resample_axis(a: np.ndarray, n: int, axis: int) -> np.ndarray:
    """Auf ``n`` Zellen entlang ``axis`` (Flächenmittel beim Verkleinern, linear beim Vergrößern)."""
    m = a.shape[axis]
    if m == n:
        return a
    a = np.moveaxis(a, axis, 0)
    if n < m:
        edges = np.linspace(0, m, n + 1)
        c = np.concatenate([np.zeros((1,) + a.shape[1:]), np.cumsum(a, axis=0)])
        idx = np.arange(m + 1)
        lo = np.stack([np.interp(edges, idx, c[:, j]) for j in range(c.shape[1])], axis=1) \
            if c.ndim == 2 else np.interp(edges, idx, c)
        out = np.diff(lo, axis=0) / np.diff(edges)[:, None] if lo.ndim == 2 else np.diff(lo) / np.diff(edges)
    else:
        src = (np.arange(n) + 0.5) * m / n - 0.5
        src = np.clip(src, 0, m - 1)
        i0 = np.floor(src).astype(int)
        i1 = np.minimum(i0 + 1, m - 1)
        w = (src - i0).reshape((-1,) + (1,) * (a.ndim - 1))
        out = a[i0] * (1 - w) + a[i1] * w
    return np.moveaxis(out, 0, axis)


def resample(gray: np.ndarray, rows: int, cols: int) -> np.ndarray:
    return _resample_axis(_resample_axis(gray, rows, 0), cols, 1)


def gaussian_blur(a: np.ndarray, sigma_px: float) -> np.ndarray:
    if sigma_px <= 0.05:
        return a
    r = max(1, int(math.ceil(3 * sigma_px)))
    x = np.arange(-r, r + 1)
    k = np.exp(-(x ** 2) / (2 * sigma_px ** 2))
    k /= k.sum()
    out = a
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        p = np.pad(out, pad, mode="edge")
        out = np.apply_along_axis(lambda v: np.convolve(v, k, mode="valid"), axis, p)
    return out


def adjust(gray: np.ndarray, opts: HeightmapOptions) -> np.ndarray:
    """Invertieren, Helligkeit, Kontrast, Gamma (Werte 0..1)."""
    g = np.clip(np.asarray(gray, dtype=np.float64), 0.0, 1.0)
    if opts.invert:
        g = 1.0 - g
    g = np.clip((g - 0.5) * opts.contrast + 0.5 + opts.brightness, 0.0, 1.0)
    if opts.gamma != 1.0:
        g = g ** (1.0 / opts.gamma)
    return g


def heightmap_from_gray(gray: np.ndarray, opts: HeightmapOptions) -> Heightmap:
    opts.validate()
    g = np.asarray(gray, dtype=np.float64)
    if g.ndim != 2 or min(g.shape) < 1:
        raise ValueError("Graustufenbild (2D) erwartet")
    li = opts.line_interval_mm
    height = opts.height_mm if opts.height_mm is not None else opts.width_mm * g.shape[0] / g.shape[1]
    cols = max(1, int(round(opts.width_mm / li)))
    rows = max(1, int(round(height / li)))
    if rows * cols > 40_000_000:
        raise ValueError("Höhenkarte zu groß – Zeilenabstand vergrößern")
    g = adjust(g, opts)
    g = resample(g, rows, cols)
    g = gaussian_blur(g, opts.blur_mm / li)
    depth = (1.0 - np.clip(g, 0.0, 1.0)) * opts.depth_mm
    return Heightmap(depth=depth, pixel_mm=li)


def heightmap_from_image(path: str | Path, opts: HeightmapOptions) -> Heightmap:
    return heightmap_from_gray(load_gray(path), opts)
