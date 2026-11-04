"""Vorschau der Bildgravur im Dialog „Bildeinstellungen“ (wie LightBurn „Adjust Image“).

:func:`preview_array` rechnet das Bild mit genau der Engine der Ausgabe
(:func:`lumacut_job.raster.power_map` bzw. :func:`~lumacut_job.raster.depth_slices`)
im eingestellten Linienabstand um: ein Vorschaupixel = ein Laserpunkt.
Gelasert = dunkel (Graustufen nach Leistung, 3D nach Anzahl Durchgänge).
Größere Bilder werden auf einen mittigen Ausschnitt von höchstens
``MAX_PREVIEW_PIXELS`` Punkten begrenzt, damit der Dialog flüssig bleibt –
so bleibt die echte Punktstruktur sichtbar statt einer verkleinerten.
Drehung des Objekts bleibt unberücksichtigt (die Ausgabe dreht das Bild vorher).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lumacut_canvas.model import ImageSettings
from lumacut_job.raster import PWM_MAX, RasterSettings, depth_slices, power_map, resample

MAX_PREVIEW_PIXELS = 360_000      # z. B. 600 × 600 Punkte


@dataclass
class Preview:
    pixels: np.ndarray            # uint8, 0 = volle Leistung / tiefste Stufe, 255 = nicht lasern
    cropped: bool                 # nur ein mittiger Ausschnitt
    burn_share: float             # Anteil gelaserter Punkte (0..1)


def preview_settings(st: ImageSettings) -> RasterSettings:
    st = st.normalized()
    return RasterSettings(line_interval_mm=st.line_interval_mm, power=st.power,
                          min_power=min(st.min_power, st.power), speed_mm_min=st.speed_mm_min,
                          mode="floyd" if st.mode == "depth3d" else st.mode,
                          threshold=st.threshold, overscan_mm=0.0, negative=st.negative,
                          halftone_cpi=st.halftone_cpi, halftone_angle=st.halftone_angle,
                          dot_width_mm=st.dot_width_mm)


def preview_array(gray: np.ndarray, width_mm: float, height_mm: float,
                  settings: ImageSettings, max_pixels: int = MAX_PREVIEW_PIXELS) -> Preview:
    """Gravurbild (Laserpunkte) für ``gray`` (uint8, 0 = schwarz) in ``width_mm × height_mm``."""
    st = settings.normalized()
    s = preview_settings(st)
    g = resample(gray, width_mm, height_mm, st.line_interval_mm)
    rows, cols = g.shape
    cropped = rows * cols > max_pixels
    if cropped:
        ch = min(rows, max(1, int(max_pixels ** 0.5)))
        cw = min(cols, max(1, max_pixels // ch))
        y0, x0 = (rows - ch) // 2, (cols - cw) // 2
        g = g[y0:y0 + ch, x0:x0 + cw]
    if st.mode == "depth3d":
        masks = depth_slices(g, st.depth_levels, st.negative)
        level = np.sum(masks, axis=0).astype(np.float64) / st.depth_levels
        out = 255.0 - level * 255.0
        share = float(np.mean(level > 0)) if level.size else 0.0
    else:
        pm = power_map(g, s)
        out = 255.0 - pm.astype(np.float64) * 255.0 / max(1, round(st.power / 100 * PWM_MAX))
        share = float(np.mean(pm > 0)) if pm.size else 0.0
    return Preview(np.clip(np.rint(out), 0, 255).astype(np.uint8), cropped, share)


def gray_from_png(png: bytes) -> np.ndarray:
    """PNG-Bytes → 8-bit-Graustufen-Array (über den QImage-Cache)."""
    from PySide6.QtGui import QImage

    from lumacut_canvas.image_cache import qimage_for

    img = qimage_for(png)
    if img.isNull():
        raise ValueError("Bilddaten beschädigt")
    g = img.convertToFormat(QImage.Format_Grayscale8)
    stride = g.bytesPerLine()
    arr = np.frombuffer(g.constBits(), dtype=np.uint8, count=stride * g.height())
    return arr.reshape(g.height(), stride)[:, :g.width()].copy()


def to_qimage(pixels: np.ndarray):
    """uint8-Array → QImage (Grayscale8, eigene Kopie)."""
    from PySide6.QtGui import QImage

    a = np.ascontiguousarray(pixels, dtype=np.uint8)
    h, w = a.shape
    return QImage(a.data, w, h, w, QImage.Format_Grayscale8).copy()
