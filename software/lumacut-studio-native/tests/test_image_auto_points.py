"""Review round 31: „Auto-Tonwert“ sets the black / white point (exact linear
stretch like an image editor's auto levels) instead of approximating it with
brightness / contrast (docs/REVIEW_GAP_ANALYSIS_2026-10-25.md §38)."""
from __future__ import annotations

import numpy as np
import pytest

from lumacut_job import raster
from lumacut_job.raster import RasterSettings, adjust_gray, gray_histogram, levels_points


def photo(w=80, h=60, lo=70, hi=180, seed=5):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w]
    g = lo + (hi - lo) * (x / (w - 1) * 0.7 + y / (h - 1) * 0.3)
    g = g + rng.normal(0, 3, (h, w))
    return np.clip(g, lo, hi).astype(np.uint8)


def _st(**kw):
    from lumacut_canvas.model import ImageSettings
    kw.setdefault("line_interval_mm", 0.1)
    return ImageSettings(**kw)


def test_points_are_the_tonal_range_of_the_job_sample():
    from lumacut_import.image_preview import auto_points_for
    g = photo()
    pts = auto_points_for(g, 8.0, 6.0, _st())
    assert pts == levels_points(gray_histogram(raster.resample(g, 8.0, 6.0, 0.1)))
    lo, hi = pts
    assert 68 <= lo <= 80 and 170 <= hi <= 182
    assert isinstance(lo, int) and isinstance(hi, int)


def test_points_stretch_exactly_to_black_and_white():
    """With the points the clipped range spans 0..255 – the brightness /
    contrast approximation (rounded percent, log contrast) does not."""
    from lumacut_import.image_preview import auto_levels_for, auto_points_for
    g = raster.resample(photo(), 8.0, 6.0, 0.1)
    lo, hi = auto_points_for(g, 8.0, 6.0, _st())
    out = adjust_gray(g, RasterSettings(black_point=lo, white_point=hi))
    assert out[g <= lo].max() == 0 and out[g >= hi].min() == 255
    inner = (g > lo) & (g < hi)
    exp = (g[inner].astype(np.float32) - lo) / (hi - lo) * 255
    assert np.abs(out[inner] - exp).max() < 1.0
    b, c = auto_levels_for(g, 8.0, 6.0, _st())
    approx = adjust_gray(g, RasterSettings(brightness=b, contrast=c))
    assert np.abs(approx[inner] - exp).max() > np.abs(out[inner] - exp).max()


def test_points_ignore_current_points_brightness_contrast_and_gamma():
    from lumacut_import.image_preview import auto_points_for
    g = photo()
    ref = auto_points_for(g, 8.0, 6.0, _st())
    for kw in ({"black_point": 100, "white_point": 120}, {"brightness": 40, "contrast": -30},
               {"gamma": 2.5}, {"mode": "jarvis"}, {"negative": True}):
        assert auto_points_for(g, 8.0, 6.0, _st(**kw)) == ref, kw


def test_points_follow_sharpen():
    from lumacut_import.image_preview import auto_points_for
    g = np.full((60, 80), 120, np.uint8)
    g[:, 40:] = 140                                     # soft step: sharpen overshoots
    plain = auto_points_for(g, 8.0, 6.0, _st())
    sharp = auto_points_for(g, 8.0, 6.0, _st(sharpen=300, sharpen_radius=2.0))
    assert sharp[0] < plain[0] or sharp[1] > plain[1]


def test_flat_and_full_range_images_keep_the_defaults():
    from lumacut_import.image_preview import auto_points_for
    assert auto_points_for(np.full((20, 20), 128, np.uint8), 2, 2, _st()) == (0, 255)
    assert auto_points_for(np.zeros((20, 20), np.uint8), 2, 2, _st()) == (0, 255)
    full = np.tile(np.arange(256, dtype=np.uint8), (8, 1))
    lo, hi = auto_points_for(full, 25.6, 0.8, _st(), clip=0.0)
    assert (lo, hi) == (0, 255)


def test_big_images_are_sampled():
    from lumacut_import.image_preview import auto_points_for
    g = photo(w=400, h=300)
    lo, hi = auto_points_for(g, 40.0, 30.0, _st(), max_pixels=10_000)
    ref = auto_points_for(g, 40.0, 30.0, _st())
    assert abs(lo - ref[0]) <= 3 and abs(hi - ref[1]) <= 3


# ------------------------------------------------------------- dialog
def _png(lo=70, hi=180):
    from PySide6.QtGui import QColor, QImage
    from lumacut_import.image import grayscale_png
    img = QImage(60, 30, QImage.Format_RGB32)
    for x in range(60):
        for y in range(30):
            v = int(lo + (hi - lo) * x / 59)
            img.setPixelColor(x, y, QColor(v, v, v))
    png, pw, _ph = grayscale_png(img)
    return png, pw


@pytest.mark.parametrize("start", [(0, 255), (200, 230), (10, 40), (150, 160)])
def test_dialog_auto_levels_sets_points_and_resets_brightness_contrast(qapp, start):
    from lumacut_import.qt import ImageSettingsDialog
    png, pw = _png()
    dlg = ImageSettingsDialog(_st(mode="floyd", line_interval_mm=0.2, brightness=25,
                                  contrast=-15, gamma=1.3, black_point=start[0],
                                  white_point=start[1]),
                              12.0, pw, png=png, height_mm=6.0)
    lo, hi = dlg.last_histograms.levels
    assert dlg.apply_auto_levels()
    # whatever the old points were, the spin boxes did not push each other off
    assert (dlg.black_point.value(), dlg.white_point.value()) == (lo, hi)
    assert (dlg.brightness.value(), dlg.contrast.value(), dlg.gamma.value()) == (0, 0, 1.3)
    assert not dlg.apply_auto_levels()
    dlg.update_preview()
    assert dlg.last_histograms.points == (lo, hi)
    assert "Schwarz-/Weißpunkt" in dlg.histogram_label.text()
    st = dlg.settings()
    assert (st.black_point, st.white_point, st.brightness, st.contrast) == (lo, hi, 0.0, 0.0)


def test_dialog_auto_levels_preview_spans_black_to_white(qapp):
    from lumacut_import.qt import ImageSettingsDialog
    png, pw = _png()
    dlg = ImageSettingsDialog(_st(mode="grayscale", line_interval_mm=0.2), 12.0, pw,
                              png=png, height_mm=6.0)
    dlg.apply_auto_levels()
    dlg.update_preview()
    adj = dlg.last_histograms.adjusted
    nz = adj.nonzero()[0]
    assert nz.min() == 0 and nz.max() == 255
    assert "Schwarz- und Weißpunkt" in dlg.auto_levels.toolTip()


def test_dialog_auto_levels_on_a_flat_image_resets_to_defaults(qapp):
    from lumacut_import.qt import ImageSettingsDialog
    png, pw = _png(lo=128, hi=128)
    dlg = ImageSettingsDialog(_st(line_interval_mm=0.2, black_point=30, white_point=200,
                                  brightness=10), 12.0, pw, png=png, height_mm=6.0)
    assert dlg.apply_auto_levels()
    assert (dlg.black_point.value(), dlg.white_point.value(), dlg.brightness.value()) == (0, 255, 0)
    assert not dlg.apply_auto_levels()
