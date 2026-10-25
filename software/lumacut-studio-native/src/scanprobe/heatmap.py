"""Qt-freie Heatmap-Vorschau der Höhenmeshes (PNG über OpenCV)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import cv2

from .geometry import Rect
from .heightmap import HeightMapSet, MEASURED, RETRIED, FAILED, OUTLIER


def render_heatmap(maps: HeightMapSet, path: Optional[str | Path] = None,
                   px_per_mm: float = 2.0, bounds: Optional[Rect] = None,
                   mosaic=None, alpha: float = 0.65, show_points: bool = True,
                   z_range: Optional[tuple[float, float]] = None) -> np.ndarray:
    """Farbige Höhenkarte aller Bereiche (blau = tief, rot = hoch).

    Mit ``mosaic`` wird über das Scanbild gelegt; Bildkonvention wie das
    Mosaik (Zeile 0 = kleinstes Y). Rückgabe BGR-Bild; optional als PNG.
    """
    if not maps.maps:
        raise ValueError("Keine Höhenmeshes")
    if bounds is None:
        bounds = mosaic.bounds if mosaic is not None else _union([m.polygon.bounds for m in maps.maps]).expand(10)
    W, H = max(1, int(bounds.width * px_per_mm)), max(1, int(bounds.height * px_per_mm))
    if mosaic is not None:
        base = cv2.resize(mosaic.image, (W, H), interpolation=cv2.INTER_AREA)
    else:
        base = np.full((H, W, 3), 32, np.uint8)
    zall, lo, hi = z_raster(maps, bounds, px_per_mm, z_range)
    span = max(hi - lo, 1e-3)
    to_px = lambda x, y: (int((x - bounds.xmin) * px_per_mm), int((y - bounds.ymin) * px_per_mm))
    valid = ~np.isnan(zall)
    norm = np.zeros((H, W), np.uint8)
    norm[valid] = np.clip((zall[valid] - lo) / span * 255, 0, 255).astype(np.uint8)
    colored = cv2.applyColorMap(norm, cv2.COLORMAP_TURBO)
    out = base.copy()
    out[valid] = (alpha * colored[valid] + (1 - alpha) * base[valid]).astype(np.uint8)
    for m in maps.maps:
        pts = np.array([to_px(x, y) for x, y in m.polygon.points], np.int32)
        cv2.polylines(out, [pts], True, (255, 255, 255), 1, cv2.LINE_AA)
        st = m.stats()
        label = f"{m.area_id}: {st.get('range', 0):.2f} mm"
        cx, cy = to_px(*m.polygon.bounds.center)
        cv2.putText(out, label, (cx - 40, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
        if show_points:
            for j, y in enumerate(m.ys):
                for i, x in enumerate(m.xs):
                    p = to_px(x, y)
                    s = m.status[j, i]
                    if s in (MEASURED, RETRIED):
                        cv2.circle(out, p, 2, (255, 255, 255), -1, cv2.LINE_AA)
                    elif s in (FAILED, OUTLIER):
                        cv2.drawMarker(out, p, (0, 0, 255), cv2.MARKER_TILTED_CROSS, 7, 2)
    out = _legend(out, lo, hi)
    if path is not None:
        if not cv2.imwrite(str(path), out):
            raise OSError(f"Konnte {path} nicht schreiben")
    return out


def _legend(img: np.ndarray, lo: float, hi: float) -> np.ndarray:
    H, W = img.shape[:2]
    bar = np.linspace(255, 0, max(H - 20, 10)).astype(np.uint8)[:, None].repeat(14, 1)
    bar = cv2.applyColorMap(bar, cv2.COLORMAP_TURBO)
    panel = np.full((H, 80, 3), 20, np.uint8)
    panel[10:10 + bar.shape[0], 8:22] = bar[: H - 20]
    cv2.putText(panel, f"{hi:.2f}", (26, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (230, 230, 230), 1, cv2.LINE_AA)
    cv2.putText(panel, f"{lo:.2f}", (26, H - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (230, 230, 230), 1, cv2.LINE_AA)
    cv2.putText(panel, "mm", (26, H // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (230, 230, 230), 1, cv2.LINE_AA)
    return np.hstack([img, panel])


def _union(rects) -> Rect:
    return Rect(min(r.xmin for r in rects), min(r.ymin for r in rects),
                max(r.xmax for r in rects), max(r.ymax for r in rects))


def z_raster(maps: HeightMapSet, bounds: Rect, px_per_mm: float,
             z_range: Optional[tuple[float, float]] = None) -> tuple[np.ndarray, float, float]:
    """Z je Pixel (NaN außerhalb der Bereiche) plus Farbskala (lo, hi)."""
    W, H = max(1, int(bounds.width * px_per_mm)), max(1, int(bounds.height * px_per_mm))
    zs = [m.filled() for m in maps.maps if m.measured_count]
    if not zs:
        raise ValueError("Keine gültigen Messungen")
    lo, hi = z_range or (min(float(np.nanmin(z)) for z in zs), max(float(np.nanmax(z)) for z in zs))
    to_px = lambda x, y: (int((x - bounds.xmin) * px_per_mm), int((y - bounds.ymin) * px_per_mm))
    zall = np.full((H, W), np.nan, np.float32)
    step = max(1, int(round(px_per_mm)))  # etwa 1 Abfrage pro mm, dann blockweise
    for m in maps.maps:
        if not m.measured_count:
            continue
        mask = np.zeros((H, W), np.uint8)
        pts = np.array([to_px(x, y) for x, y in m.polygon.points], np.int32)
        cv2.fillPoly(mask, [pts], 255)
        rows, cols = np.nonzero(mask)
        if rows.size == 0:
            continue
        for r0 in range(rows.min() - rows.min() % step, rows.max() + 1, step):
            y = bounds.ymin + (r0 + step / 2) / px_per_mm
            for c0 in range(cols.min() - cols.min() % step, cols.max() + 1, step):
                blk = mask[r0:r0 + step, c0:c0 + step] > 0
                if not blk.any():
                    continue
                x = bounds.xmin + (c0 + step / 2) / px_per_mm
                zv = m.z_at(x, y, maps.method)
                sub = zall[r0:r0 + step, c0:c0 + step]
                sub[blk] = zv
    return zall, lo, hi


def heatmap_rgba(maps: HeightMapSet, bounds: Rect, px_per_mm: float = 2.0,
                 alpha: float = 0.6, z_range: Optional[tuple[float, float]] = None
                 ) -> tuple[np.ndarray, float, float]:
    """Transparente Überlagerung (RGBA, Zeile 0 = kleinstes Y) für die Arbeitsfläche.

    Außerhalb der geprobten Bereiche ist Alpha 0. Rückgabe ``(bild, lo, hi)``.
    """
    if not maps.maps:
        raise ValueError("Keine Höhenmeshes")
    zall, lo, hi = z_raster(maps, bounds, px_per_mm, z_range)
    span = max(hi - lo, 1e-3)
    valid = ~np.isnan(zall)
    norm = np.zeros(zall.shape, np.uint8)
    norm[valid] = np.clip((zall[valid] - lo) / span * 255, 0, 255).astype(np.uint8)
    bgr = cv2.applyColorMap(norm, cv2.COLORMAP_TURBO)
    rgba = np.zeros(zall.shape + (4,), np.uint8)
    rgba[..., :3] = bgr[..., ::-1]
    rgba[..., 3] = np.where(valid, int(255 * alpha), 0).astype(np.uint8)
    return rgba, lo, hi
