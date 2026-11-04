"""Review round 29: image histogram / auto-levels and a preview that renders the
image object like the job (rotation, smoothing, origin-top-right mirroring)."""
from __future__ import annotations

import json

import numpy as np
import pytest

from lumacut_job import raster
from lumacut_job.raster import (AUTO_LEVELS_CLIP, RasterSettings, adjust_gray, auto_levels,
                                gray_histogram, levels_points)


def photo(w=80, h=60, lo=70, hi=180, seed=5):
    """Low-contrast 'photo' with grey values roughly in lo..hi."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w]
    g = lo + (hi - lo) * (x / (w - 1) * 0.7 + y / (h - 1) * 0.3)
    g = g + rng.normal(0, 3, (h, w))
    return np.clip(g, lo, hi).astype(np.uint8)


# ------------------------------------------------------------- engine
def test_gray_histogram_counts_and_mask():
    g = np.array([[0, 0, 255], [10, 10, 10]], np.uint8)
    h = gray_histogram(g)
    assert h.shape == (256,) and h.sum() == 6
    assert (h[0], h[10], h[255]) == (2, 3, 1)
    m = np.array([[True, False, False], [True, True, False]])
    hm = gray_histogram(g, m)
    assert hm.sum() == 3 and (hm[0], hm[10]) == (1, 2)
    # float input (adjusted image) is rounded
    hf = gray_histogram(np.array([[0.4, 254.6, 300.0]], np.float32))
    assert (hf[0], hf[255]) == (1, 2)


def test_levels_points_ignore_the_clip_share():
    h = np.zeros(256, np.int64)
    h[50:201] = 100
    assert levels_points(h, 0.0) == (50, 200)
    h[0] = 1          # a few outliers ...
    h[255] = 1
    assert levels_points(h, AUTO_LEVELS_CLIP) == (50, 200)   # ... are ignored
    assert levels_points(h, 0.0) == (0, 255)
    assert levels_points(np.zeros(256)) is None


def test_auto_levels_stretches_the_range_to_black_and_white():
    g = photo()
    b, c = auto_levels(gray_histogram(g))
    assert b == float(round(b)) and c == float(round(c))
    assert c > 0
    lo, hi = levels_points(gray_histogram(g))
    out = adjust_gray(np.array([[lo, hi, (lo + hi) / 2]], np.float32),
                      RasterSettings(brightness=b, contrast=c))
    assert out[0, 0] <= 6 and out[0, 1] >= 249           # ≈ black / white (whole-% steps)
    assert abs(out[0, 2] - 127.5) < 6                   # mid of the range ≈ mid grey
    adj = adjust_gray(g, RasterSettings(brightness=b, contrast=c))
    assert adj.max() - adj.min() > 240 and g.max() - g.min() < 120


def test_auto_levels_formula_exact_without_rounding():
    # range 64..191: k = 255/127 -> contrast = 100*log10(255/127), b = 0.5 - 255/510
    h = np.zeros(256)
    h[64:192] = 1
    b, c = auto_levels(h, 0.0)
    assert c == round(100 * np.log10(255 / 127))
    assert b == round(100 * (0.5 - (64 + 191) / 510))


def test_auto_levels_dark_and_light_images_shift_brightness():
    dark = photo(lo=10, hi=90)
    light = photo(lo=160, hi=245)
    bd, _ = auto_levels(gray_histogram(dark))
    bl, _ = auto_levels(gray_histogram(light))
    assert bd > 0 > bl


def test_auto_levels_flat_full_range_and_extreme():
    assert auto_levels(gray_histogram(np.full((10, 10), 128, np.uint8))) == (0.0, 0.0)
    assert auto_levels(np.zeros(256)) == (0.0, 0.0)
    full = np.tile(np.arange(256, dtype=np.uint8), (4, 1))
    b, c = auto_levels(gray_histogram(full), 0.0)
    assert (b, c) == (0.0, 0.0)                        # already full range
    narrow = np.zeros(256)
    narrow[100:106] = 1                                 # < 10 % of the scale
    b, c = auto_levels(narrow, 0.0)
    assert c == 100.0 and -100 <= b <= 100
    s = RasterSettings(brightness=b, contrast=c)
    s.validate()


# ------------------------------------------------------------- preview helpers
def test_histograms_before_and_after_adjustment():
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import histograms
    g = photo()
    plain = histograms(g, 16, 12, ImageSettings(line_interval_mm=0.2))
    assert plain.source.sum() == 80 * 60 and (plain.source == plain.adjusted).all()
    assert plain.black_share == 0 and plain.white_share == 0
    assert plain.levels == levels_points(gray_histogram(raster.resample(g, 16, 12, 0.2)))
    dark = histograms(g, 16, 12, ImageSettings(line_interval_mm=0.2, brightness=-60,
                                               contrast=50))
    assert (dark.source == plain.source).all()
    assert dark.black_share > 0.2 and dark.white_share == 0
    mean = lambda h: float((h * np.arange(256)).sum() / h.sum())  # noqa: E731
    assert mean(dark.adjusted) < mean(plain.adjusted)


def test_histograms_of_big_images_are_sampled():
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import histograms
    g = photo(400, 400)
    h = histograms(g, 100, 100, ImageSettings(line_interval_mm=0.05, sharpen=100),
                   max_pixels=10_000)
    assert 9_000 <= h.source.sum() <= 10_000 and h.adjusted.sum() == h.source.sum()


def test_auto_levels_for_uses_the_job_sample_and_keeps_gamma():
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import auto_levels_for
    g = photo()
    st = ImageSettings(line_interval_mm=0.2, gamma=1.5, brightness=30, contrast=-40)
    b, c = auto_levels_for(g, 16, 12, st)
    # existing brightness / contrast are replaced, not stacked
    assert (b, c) == auto_levels(gray_histogram(raster.resample(g, 16, 12, 0.2)))
    # sharpen runs before the stretch, so it is taken into account
    bs, cs = auto_levels_for(g, 16, 12, ImageSettings(line_interval_mm=0.2, sharpen=300,
                                                      sharpen_radius=2))
    assert cs <= c


# ------------------------------------------------------------- job-like preview
def _doc_with_image(qapp, rot=0.0, w=60, h=30, **settings):
    from lumacut_canvas.model import Document, Geometry, ImageSettings, Layer, RasterImage, Shape
    from lumacut_import.image import grayscale_png
    from PySide6.QtGui import QColor, QImage
    d = Document()
    d.add_layer(Layer("Ebene 1"))
    img = QImage(w, h, QImage.Format_RGB32)
    for x in range(w):
        for y in range(h):
            v = 60 + int(150 * x / (w - 1)) - (40 if (x - w / 3) ** 2 + (y - h / 2) ** 2 < 36 else 0)
            img.setPixelColor(x, y, QColor(v, v, v))
    png, pw, ph = grayscale_png(img)
    sh = Shape("image", Geometry(80, 80, 12, 6, rot), d.active_layer_id,
               image=RasterImage(png, pw, ph, ImageSettings(**settings)))
    d.add_shape(sh)
    return d, sh


def _job_power_map(monkeypatch, sh):
    from lumacut_job import images
    seen = {}
    real = images.power_map

    def spy(gray, s, inside=None, **kw):
        pm = real(gray, s, inside=inside, **kw)
        seen["pm"] = pm
        return pm

    monkeypatch.setattr(images, "power_map", spy)
    images.image_job(sh)
    monkeypatch.setattr(images, "power_map", real)
    pm = seen["pm"]
    from lumacut_canvas.workarea import IMAGE_FLIP_X
    return pm[:, ::-1] if IMAGE_FLIP_X else pm


@pytest.mark.parametrize("rot", [0.0, 30.0])
@pytest.mark.parametrize("extra", [{}, {"brightness": -40, "contrast": 30}])
@pytest.mark.parametrize("mode", ["floyd", "jarvis", "halftone", "threshold", "sketch"])
def test_shape_preview_is_the_job(qapp, monkeypatch, rot, extra, mode):
    from lumacut_import.image_preview import preview_shape
    _d, sh = _doc_with_image(qapp, rot=rot, mode=mode, line_interval_mm=0.1, power=50, **extra)
    pm = _job_power_map(monkeypatch, sh)
    pv = preview_shape(sh, sh.image.settings)
    assert not pv.cropped and pv.pixels.shape == pm.shape
    assert ((pv.pixels < 255) == (pm > 0)).all()


def test_shape_preview_grayscale_values_are_the_job(qapp, monkeypatch):
    from lumacut_import.image_preview import preview_shape
    _d, sh = _doc_with_image(qapp, rot=20.0, mode="grayscale", line_interval_mm=0.1,
                             power=80, min_power=10, gamma=1.3)
    pm = _job_power_map(monkeypatch, sh)
    pv = preview_shape(sh, sh.image.settings)
    ref = np.clip(np.rint(255 - pm * 255 / round(0.8 * 255)), 0, 255).astype(np.uint8)
    assert (pv.pixels == ref).all()


def test_rotated_preview_keeps_the_box_corners_white(qapp):
    from lumacut_import.image_preview import preview_shape
    from lumacut_job.images import render_inside
    for extra in ({}, {"brightness": -100}, {"negative": True}):
        _d, sh = _doc_with_image(qapp, rot=30.0, mode="threshold", line_interval_mm=0.1,
                                 **extra)
        pv = preview_shape(sh, sh.image.settings)
        inside = render_inside(sh, 0.1)
        assert pv.pixels.shape == inside.shape
        assert (pv.pixels[~inside] == 255).all()
        assert (pv.pixels[inside] < 255).any()


def test_rotated_preview_differs_from_the_unrotated_one(qapp):
    from lumacut_import.image_preview import preview_array, preview_shape
    from lumacut_import.image_preview import gray_from_png
    _d, sh = _doc_with_image(qapp, rot=45.0, mode="floyd", line_interval_mm=0.1)
    pv = preview_shape(sh, sh.image.settings)
    flat = preview_array(gray_from_png(sh.image.png), 12, 6, sh.image.settings)
    assert pv.pixels.shape != flat.pixels.shape
    b = sh.geom.bounds()
    assert pv.pixels.shape == (round(b.h / 0.1), round(b.w / 0.1))


def test_shape_preview_uses_dialog_settings_not_the_stored_ones(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import preview_shape
    _d, sh = _doc_with_image(qapp, rot=10.0, mode="floyd", line_interval_mm=0.1)
    a = preview_shape(sh, sh.image.settings)
    b = preview_shape(sh, ImageSettings(mode="floyd", line_interval_mm=0.2))
    assert b.pixels.shape[0] < a.pixels.shape[0]
    assert sh.image.settings.line_interval_mm == 0.1          # object untouched


def test_shape_preview_crops_big_images(qapp):
    from lumacut_import.image_preview import preview_shape
    _d, sh = _doc_with_image(qapp, rot=15.0, mode="jarvis", line_interval_mm=0.03,
                             sharpen=100)
    pv = preview_shape(sh, sh.image.settings, max_pixels=20_000)
    assert pv.cropped and pv.pixels.size <= 20_000


def test_shape_preview_depth3d(qapp):
    from lumacut_import.image_preview import preview_shape
    _d, sh = _doc_with_image(qapp, rot=30.0, mode="depth3d", line_interval_mm=0.1,
                             depth_levels=4)
    a = preview_shape(sh, sh.image.settings)
    _d, sh2 = _doc_with_image(qapp, rot=30.0, mode="depth3d", line_interval_mm=0.1,
                              depth_levels=4, brightness=-40)
    b = preview_shape(sh2, sh2.image.settings)
    assert a.pixels.shape == b.pixels.shape and b.pixels.mean() < a.pixels.mean()


def test_old_documents_still_give_the_same_gcode(qapp):
    """Nothing in the job changed: auto-levels only fills the existing fields."""
    from lumacut_canvas.model import Document
    from lumacut_job.images import image_job
    for mode in ("floyd", "halftone", "grayscale", "depth3d"):
        d, sh = _doc_with_image(qapp, rot=30.0, mode=mode, line_interval_mm=0.2, depth_levels=3)
        d2 = Document.from_dict(json.loads(json.dumps(d.to_dict())))
        assert image_job(d2.shapes[0]).lines == image_job(sh).lines


# ------------------------------------------------------------- dialog
def _png(qapp, lo=70, hi=180):
    from PySide6.QtGui import QColor, QImage
    from lumacut_import.image import grayscale_png
    img = QImage(60, 30, QImage.Format_RGB32)
    for x in range(60):
        for y in range(30):
            v = int(lo + (hi - lo) * x / 59)
            img.setPixelColor(x, y, QColor(v, v, v))
    png, pw, _ph = grayscale_png(img)
    return png, pw


def test_dialog_histogram_and_auto_levels(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    png, pw = _png(qapp)
    dlg = ImageSettingsDialog(ImageSettings(mode="jarvis", line_interval_mm=0.2, gamma=1.4),
                              12.0, pw, png=png, height_mm=6.0)
    assert dlg.histogram_runs == 1 and dlg.histogram.isVisibleTo(dlg)
    h = dlg.last_histograms
    lo, hi = h.levels
    assert 65 <= lo <= 80 and 170 <= hi <= 185
    assert "Tonwertumfang" in dlg.histogram_label.text()
    before = dlg.last_preview.pixels.copy()
    assert dlg.apply_auto_levels()
    b, c = dlg.brightness.value(), dlg.contrast.value()
    assert c > 20 and dlg.gamma.value() == 1.4
    assert not dlg.apply_auto_levels()                 # idempotent
    dlg.update_preview()
    assert dlg.last_histograms.adjusted.nonzero()[0].min() < lo
    assert (dlg.last_preview.pixels != before).any()
    out = dlg.settings()
    assert (out.brightness, out.contrast) == (b, c)
    dlg.histogram.grab()                               # paints without errors


def test_dialog_without_image_data_has_no_auto_levels(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    dlg = ImageSettingsDialog(ImageSettings(), 10.0, 100)
    assert not dlg.auto_levels.isEnabled() and not dlg.apply_auto_levels()
    assert dlg.histogram_runs == 0
    assert dlg.settings() == ImageSettings().normalized()


def test_dialog_with_shape_previews_the_rotated_job(qapp, monkeypatch):
    from lumacut_import.image_preview import preview_shape
    from lumacut_import.qt import ImageSettingsDialog
    from lumacut_import import image_preview
    _d, sh = _doc_with_image(qapp, rot=30.0, mode="floyd", line_interval_mm=0.1)
    ref = preview_shape(sh, sh.image.settings)
    renders = []
    real = image_preview.render_for_preview
    monkeypatch.setattr(image_preview, "render_for_preview",
                        lambda *a, **k: renders.append(1) or real(*a, **k))
    dlg = ImageSettingsDialog(sh.image.settings, sh.geom.w, sh.image.px_width, shape=sh)
    assert dlg.preview.isVisibleTo(dlg)
    assert (dlg.last_preview.pixels == ref.pixels).all()
    assert "gedreht um 30°" in dlg.preview_label.text()
    # power / mode changes reuse the rendered image, interval changes re-render
    dlg.power.setValue(30)
    dlg.update_preview()
    assert len(renders) == 1
    dlg.interval.setValue(0.2)
    dlg.update_preview()
    assert len(renders) == 2
    assert dlg.settings() != sh.image.settings


def test_edit_image_settings_passes_the_shape_and_stores_auto_levels(qapp, tmp_path,
                                                                     monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QDialog
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    from lumacut_import import qt as import_qt
    from PySide6.QtGui import QColor, QImage
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    try:
        img = QImage(50, 20, QImage.Format_RGB32)
        for x in range(50):
            for y in range(20):
                v = 90 + x
                img.setPixelColor(x, y, QColor(v, v, v))
        p = tmp_path / "foto.png"
        img.save(str(p))
        ids = w.import_tools.import_path(p)
        seen = {}

        class FakeDialog(import_qt.ImageSettingsDialog):
            def exec(self):  # noqa: A003
                seen["shape"] = self._shape
                self.apply_auto_levels()
                return QDialog.Accepted

        monkeypatch.setattr(import_qt, "ImageSettingsDialog", FakeDialog)
        assert w.import_tools.edit_image_settings(ids[0])
        assert seen["shape"].id == ids[0]
        st = w.canvas.document.shape(ids[0]).image.settings
        assert st.contrast > 20
        w.canvas.undo_stack.undo()
        st = w.canvas.document.shape(ids[0]).image.settings
        assert (st.brightness, st.contrast) == (0.0, 0.0)
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
