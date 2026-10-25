"""Zusammensetzen der Kacheln zu einem maßgenauen Gesamtbild.

* Platzierung über die bekannte Kopfposition (Schrittmotoren, ±0,1 mm)
* optionale Feinkorrektur per Phasenkorrelation gegen das bisherige Mosaik
  (begrenzt auf ``max_refine_mm``, damit Texturen wie Wabenbett nie zu großen
  Fehlsprüngen führen)
* Belichtungsangleich pro Kachel
* Mitten-gewichtete Überblendung (Gewicht ~ Randabstand^p): in Überlappungen
  zählt fast nur die Kachel, deren Bildmitte näher ist -> keine Doppelkonturen,
  das Mosaik bleibt so scharf wie die Einzelbilder.

Pixelkonvention des Mosaiks: Pixel (col, row) Mitte = Maschine
``(origin_x + (col + 0.5)·mm_per_px, origin_y + (row + 0.5)·mm_per_px)``.
Zeile 0 ist also die Seite mit dem kleinsten Y (Homing-Ecke oben links).
Der Canvas dreht bei Bedarf über ``Mosaic.pixel_to_machine_affine``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import cv2

from .calibration import CameraCalibration
from .control import RunControl, Progress
from .geometry import Rect
from .tile_scan import CapturedTile


@dataclass
class Mosaic:
    image: np.ndarray                 # H×W×3 BGR uint8
    mm_per_px: float
    origin_mm: tuple[float, float]    # Maschinenkoordinate der linken oberen Pixel-Ecke
    coverage: np.ndarray              # H×W bool, wo Bilddaten liegen
    scan_z: float = 0.0
    tile_shifts_mm: list[tuple[float, float]] = field(default_factory=list)

    @property
    def bounds(self) -> Rect:
        h, w = self.image.shape[:2]
        return Rect(self.origin_mm[0], self.origin_mm[1],
                    self.origin_mm[0] + w * self.mm_per_px, self.origin_mm[1] + h * self.mm_per_px)

    def machine_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        return ((x - self.origin_mm[0]) / self.mm_per_px - 0.5,
                (y - self.origin_mm[1]) / self.mm_per_px - 0.5)

    def pixel_to_machine(self, col: float, row: float) -> tuple[float, float]:
        return (self.origin_mm[0] + (col + 0.5) * self.mm_per_px,
                self.origin_mm[1] + (row + 0.5) * self.mm_per_px)

    @property
    def pixel_to_machine_affine(self) -> list[list[float]]:
        """2×3-Matrix für Pixel-Ecken-Koordinaten (QTransform-tauglich)."""
        s = self.mm_per_px
        return [[s, 0.0, self.origin_mm[0]], [0.0, s, self.origin_mm[1]]]

    def metadata(self) -> dict:
        h, w = self.image.shape[:2]
        return {
            "format": "lumacut-scan-mosaic/1",
            "width_px": w, "height_px": h,
            "mm_per_px": self.mm_per_px,
            "origin_mm": list(self.origin_mm),
            "bounds_mm": self.bounds.to_list(),
            "row0_is_min_y": True,
            "pixel_to_machine_affine": self.pixel_to_machine_affine,
            "scan_z": self.scan_z,
            "coverage_fraction": float(self.coverage.mean()) if self.coverage.size else 0.0,
        }

    def save(self, png_path: str | Path) -> Path:
        """Speichert PNG + ``<name>.json`` (Metadaten für den Canvas)."""
        png_path = Path(png_path)
        if not cv2.imwrite(str(png_path), self.image):
            raise OSError(f"Konnte {png_path} nicht schreiben")
        meta = png_path.with_suffix(".json")
        meta.write_text(json.dumps(self.metadata(), indent=2), encoding="utf-8")
        return meta

    @classmethod
    def load(cls, png_path: str | Path) -> "Mosaic":
        png_path = Path(png_path)
        img = cv2.imread(str(png_path), cv2.IMREAD_COLOR)
        if img is None:
            raise OSError(f"Konnte {png_path} nicht lesen")
        meta = json.loads(png_path.with_suffix(".json").read_text(encoding="utf-8"))
        cov = img.any(axis=2)
        return cls(img, float(meta["mm_per_px"]), tuple(meta["origin_mm"]), cov, meta.get("scan_z", 0.0))


def _to_bgr(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img


def _weight_mask(h: int, w: int, crop: tuple[int, int], power: float) -> np.ndarray:
    cx, cy = crop
    xs = np.arange(w, dtype=np.float32)
    ys = np.arange(h, dtype=np.float32)
    dx = np.minimum(xs - cx + 1, (w - cx) - xs).clip(0) / max(1.0, (w - 2 * cx) / 2)
    dy = np.minimum(ys - cy + 1, (h - cy) - ys).clip(0) / max(1.0, (h - 2 * cy) / 2)
    m = np.minimum(dy[:, None], dx[None, :])
    return np.power(m, power).astype(np.float32)


def stitch_mosaic(tiles: Sequence[CapturedTile], calibration: CameraCalibration,
                  bounds: Rect, mm_per_px: Optional[float] = None, refine: bool = True,
                  max_refine_mm: float = 1.5, min_response: float = 0.15,
                  blend_power: float = 4.0, exposure_match: bool = True,
                  control: Optional[RunControl] = None) -> Mosaic:
    """Kacheln in ein Mosaik über ``bounds`` (Maschinen-mm) setzen."""
    if not tiles:
        raise ValueError("Keine Kacheln")
    s = mm_per_px or calibration.mm_per_px
    W = int(np.ceil(bounds.width / s))
    H = int(np.ceil(bounds.height / s))
    if W * H > 60_000_000:
        raise ValueError("Mosaik zu groß; mm_per_px erhöhen")
    acc = np.zeros((H, W, 3), np.float32)
    wsum = np.zeros((H, W), np.float32)
    ih, iw = calibration.image_height, calibration.image_width
    base_w = _weight_mask(ih, iw, calibration.crop_px, blend_power)
    L = calibration.linear_matrix()  # px -> mm
    cu, cv_ = (iw - 1) / 2, (ih - 1) / 2
    shifts: list[tuple[float, float]] = []
    for n, ct in enumerate(tiles):
        if control:
            control.checkpoint()
        img = _to_bgr(ct.image)
        if img.shape[:2] != (ih, iw):
            raise ValueError("Kachelgröße passt nicht zur Kalibrierung")
        head = ct.tile.head
        # Tile-Pixel (u,v) -> Mosaik-Pixel: M·(u,v) + t
        A = L / s
        ox = (head[0] + calibration.offset_mm[0] - bounds.xmin) / s - 0.5
        oy = (head[1] + calibration.offset_mm[1] - bounds.ymin) / s - 0.5
        t = np.array([ox, oy]) - A @ np.array([cu, cv_])
        M = np.hstack([A, t[:, None]])
        # Ziel-ROI
        corners = np.array([[0, 0], [iw, 0], [0, ih], [iw, ih]], np.float64)
        pts = corners @ A.T + t
        x0 = max(0, int(np.floor(pts[:, 0].min())) - 2)
        y0 = max(0, int(np.floor(pts[:, 1].min())) - 2)
        x1 = min(W, int(np.ceil(pts[:, 0].max())) + 2)
        y1 = min(H, int(np.ceil(pts[:, 1].max())) + 2)
        if x1 <= x0 or y1 <= y0:
            shifts.append((0.0, 0.0))
            continue
        rw, rh = x1 - x0, y1 - y0

        def warp(Mx):
            Ml = Mx.copy()
            Ml[:, 2] -= (x0, y0)
            interp = cv2.INTER_AREA if s > calibration.mm_per_px * 1.5 else cv2.INTER_LANCZOS4
            wi = cv2.warpAffine(img, Ml, (rw, rh), flags=interp, borderMode=cv2.BORDER_CONSTANT)
            ww = cv2.warpAffine(base_w, Ml, (rw, rh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            return wi.astype(np.float32), ww

        wimg, wmask = warp(M)
        dx_mm = dy_mm = 0.0
        existing = wsum[y0:y1, x0:x1]
        overlap = (existing > 1e-6) & (wmask > 1e-6)
        if refine and n > 0 and overlap.sum() > 400:
            shift = _phase_shift(acc[y0:y1, x0:x1], existing, wimg, overlap)
            if shift is not None:
                (sx, sy), resp = shift
                if resp >= min_response and np.hypot(sx, sy) * s <= max_refine_mm:
                    M2 = M.copy()
                    M2[:, 2] += (sx, sy)
                    wimg, wmask = warp(M2)
                    dx_mm, dy_mm = sx * s, sy * s
                    overlap = (existing > 1e-6) & (wmask > 1e-6)
        if exposure_match and n > 0 and overlap.sum() > 400:
            ref = (acc[y0:y1, x0:x1][overlap] / existing[overlap][:, None]).mean()
            cur = wimg[overlap].mean()
            if cur > 1:
                g = float(np.clip(ref / cur, 0.8, 1.25))
                wimg *= g
        acc[y0:y1, x0:x1] += wimg * wmask[:, :, None]
        wsum[y0:y1, x0:x1] += wmask
        shifts.append((dx_mm, dy_mm))
        if control:
            control.report(Progress("stitch", n + 1, len(tiles), f"Zusammensetzen {n + 1}/{len(tiles)}"))
    cov = wsum > 1e-6
    out = np.zeros_like(acc)
    out[cov] = acc[cov] / wsum[cov][:, None]
    image = np.clip(out + 0.5, 0, 255).astype(np.uint8)
    return Mosaic(image, s, (bounds.xmin, bounds.ymin), cov, calibration.scan_z, shifts)


def _phase_shift(acc_roi, wsum_roi, wimg, overlap):
    """Verschiebung (dx, dy) in Mosaik-Pixeln, die die neue Kachel ans Mosaik anpasst."""
    ys, xs = np.nonzero(overlap)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    if (y1 - y0) < 16 or (x1 - x0) < 16:
        return None
    ov = overlap[y0:y1, x0:x1]
    ref = (acc_roi[y0:y1, x0:x1] / np.maximum(wsum_roi[y0:y1, x0:x1], 1e-6)[:, :, None]).mean(axis=2)
    cur = wimg[y0:y1, x0:x1].mean(axis=2)
    ref = np.where(ov, ref, 0).astype(np.float32)
    cur = np.where(ov, cur, 0).astype(np.float32)
    m = ov.astype(bool)
    ref[m] -= ref[m].mean()
    cur[m] -= cur[m].mean()
    if ref[m].std() < 2 or cur[m].std() < 2:
        return None  # strukturlos (leeres Bett) -> bekannte Position gilt
    win = cv2.createHanningWindow((x1 - x0, y1 - y0), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(cur, ref, win)
    return (dx, dy), resp
