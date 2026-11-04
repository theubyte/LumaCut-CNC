"""Review round 28: per-image adjustments (brightness, contrast, gamma, sharpen)
and the Sketch image mode – engine, model, job builder, preview and dialog."""
from __future__ import annotations

import json

import numpy as np
import pytest

from _pi_guard import pi_check
from lumacut_job import raster
from lumacut_job.raster import (MODES, RasterSettings, adjust_gray, adjusted_height,
                                filter_margin, gaussian_blur, power_map, raster_gcode,
                                sketch_darkness, sliced_depth_gcode)


def gradient(w=60, h=12):
    return np.tile(np.linspace(0, 255, w).astype(np.uint8), (h, 1))


def photo(w=80, h=60, seed=3):
    """Deterministic 'photo': smooth gradient, a dark disc and some noise."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w]
    g = 40 + 180 * x / (w - 1)
    g = np.where((x - w / 2) ** 2 + (y - h / 2) ** 2 < (h / 4) ** 2, 30, g)
    g = g + rng.normal(0, 8, (h, w))
    return np.clip(g, 0, 255).astype(np.uint8)


def step(w=40, h=20, at=20):
    g = np.full((h, w), 255, np.uint8)
    g[:, :at] = 0
    return g


# ------------------------------------------------------------- adjust_gray
def test_defaults_are_a_bit_identical_no_op():
    s = RasterSettings()
    assert not s.adjusted()
    g = photo()
    out = adjust_gray(g, s)
    assert out.dtype == np.float32 and (out == g.astype(np.float32)).all()
    for mode in ("floyd", "jarvis", "grayscale", "threshold", "halftone"):
        a = power_map(g, RasterSettings(mode=mode))
        b = power_map(g, RasterSettings(mode=mode), inside=np.zeros(g.shape, bool))
        assert (a == b).all()          # mask ignored without adjustments


@pytest.mark.parametrize("field,value", [("brightness", 10), ("contrast", -5), ("gamma", 1.2),
                                         ("sharpen", 50)])
def test_any_adjustment_counts(field, value):
    assert RasterSettings(**{field: value}).adjusted()


def test_brightness_shifts_and_clips():
    g = gradient()
    up = adjust_gray(g, RasterSettings(brightness=20))
    assert up[0, 0] == pytest.approx(0.2 * 255, abs=1e-3)
    assert up.max() == pytest.approx(255) and (up >= g - 1e-3).all()
    down = adjust_gray(g, RasterSettings(brightness=-100))
    assert (down == 0).all()
    # brighter image -> less burned in every mode
    for mode in ("floyd", "jarvis", "grayscale"):
        assert power_map(g, RasterSettings(mode=mode, brightness=30)).sum() < \
            power_map(g, RasterSettings(mode=mode)).sum()


def test_contrast_slope_around_mid_grey():
    g = np.array([[0, 64, 128, 191, 255]], np.uint8)
    hi = adjust_gray(g, RasterSettings(contrast=100))     # slope 10
    assert hi[0, 0] == 0 and hi[0, 4] == 255
    assert hi[0, 2] == pytest.approx(((128 / 255 - 0.5) * 10 + 0.5) * 255, abs=1e-2)
    lo = adjust_gray(g, RasterSettings(contrast=-100))    # slope 0.1
    assert lo.min() > 110 and lo.max() < 145
    assert np.all(np.diff(lo[0]) > 0)                    # order kept
    mid = adjust_gray(g, RasterSettings(contrast=50))
    assert mid[0, 1] < 64 and mid[0, 3] > 191


def test_gamma_keeps_black_and_white_and_bends_mid_tones():
    g = np.array([[0, 64, 128, 255]], np.uint8)
    light = adjust_gray(g, RasterSettings(gamma=2.0))
    dark = adjust_gray(g, RasterSettings(gamma=0.5))
    assert light[0, 0] == 0 and light[0, 3] == pytest.approx(255)
    assert dark[0, 0] == 0 and dark[0, 3] == pytest.approx(255)
    assert light[0, 2] == pytest.approx((128 / 255) ** 0.5 * 255, abs=1e-2)
    assert light[0, 1] > 64 > dark[0, 1]


def test_gaussian_blur_preserves_flat_areas_and_mean():
    flat = np.full((20, 30), 0.4, np.float32)
    assert np.allclose(gaussian_blur(flat, 2.0), 0.4)
    k = raster._gauss_kernel(1.5)
    assert k.sum() == pytest.approx(1.0) and len(k) == 2 * 5 + 1
    b = gaussian_blur(step().astype(np.float32), 1.0)
    assert 0 < b[5, 20] < 255 and b[5, 0] == 0 and b[5, -1] == 255


def test_sharpen_is_an_unsharp_mask():
    g = np.full((20, 40), 128, np.uint8)
    g[:, 20:] = 160
    out = adjust_gray(g, RasterSettings(sharpen=200, sharpen_radius=1.5))
    assert out[10, 19] < 128 and out[10, 20] > 160       # overshoot at the edge
    assert out[10, 2] == pytest.approx(128, abs=1e-3)    # flat areas unchanged
    assert out[10, -3] == pytest.approx(160, abs=1e-3)
    wide = adjust_gray(g, RasterSettings(sharpen=200, sharpen_radius=4))
    assert wide[10, 16] < out[10, 16] - 1e-3            # bigger radius reaches further


def test_order_sharpen_then_tone_then_gamma():
    g = photo()
    s = RasterSettings(brightness=10, contrast=20, gamma=1.3, sharpen=80, sharpen_radius=1)
    v = g.astype(np.float32) / 255
    v = np.clip(v + 0.8 * (v - gaussian_blur(v, 1)), 0, 1)
    v = np.clip((v + 0.1 - 0.5) * 10 ** 0.2 + 0.5, 0, 1) ** (1 / 1.3)
    assert np.allclose(adjust_gray(g, s), v * 255, atol=1e-3)


@pytest.mark.parametrize("kw", [{"brightness": 101}, {"contrast": -101}, {"gamma": 0.1},
                                {"gamma": 6}, {"sharpen": -1}, {"sharpen": 501},
                                {"sharpen_radius": 0.2}, {"sharpen_radius": 11}])
def test_validation(kw):
    with pytest.raises(ValueError):
        power_map(gradient(), RasterSettings(**kw))


def test_adjusted_image_still_gives_pi_safe_gcode():
    s = RasterSettings(mode="jarvis", brightness=-10, contrast=30, gamma=0.8, sharpen=100,
                       line_interval_mm=0.2)
    gc = raster_gcode(photo(), (60, 60), 16, 12, s)
    pi_check(gc)
    assert gc != raster_gcode(photo(), (60, 60), 16, 12, RasterSettings(mode="jarvis",
                                                                       line_interval_mm=0.2))


def test_inside_mask_keeps_bounding_box_corners_unburned():
    g = np.full((20, 20), 255, np.uint8)           # white background ...
    inside = np.zeros_like(g, bool)
    inside[5:15, 5:15] = True
    g[5:15, 5:15] = 200                            # ... around a light image
    s = RasterSettings(mode="threshold", brightness=-100)   # everything black
    pm = power_map(g, s, inside=inside)
    assert (pm[inside] > 0).all() and (pm[~inside] == 0).all()
    assert (power_map(g, s) > 0).all()             # without mask the corners would burn


def test_negative_with_adjustments():
    g = gradient()
    s = RasterSettings(mode="grayscale", negative=True, brightness=20)
    pm = power_map(g, s)
    # brighter -> burns more in negative
    assert pm.sum() > power_map(g, RasterSettings(mode="grayscale", negative=True)).sum()


def test_depth_height_map_uses_adjustments():
    g = gradient(40, 10)
    base = RasterSettings(line_interval_mm=0.2, power=50)
    a = sliced_depth_gcode(g, (60, 60), 8, 2, base, levels=4)
    s = RasterSettings(line_interval_mm=0.2, power=50, brightness=-30)
    b = sliced_depth_gcode(g, (60, 60), 8, 2, s, levels=4)
    pi_check(b)
    assert a != b and b.count("G1 ") >= a.count("G1 ")
    assert adjusted_height(g, base) is not None and (adjusted_height(g, base) == g).all()
    inside = np.zeros(g.shape, bool)
    h = adjusted_height(g, s, inside)
    assert (h == g).all()                          # outside keeps the background value


# ------------------------------------------------------------- sketch
def test_sketch_is_listed_everywhere():
    from lumacut_canvas.model import IMAGE_MODES
    from lumacut_import.qt import MODE_LABELS
    assert "sketch" in MODES and "sketch" in IMAGE_MODES and "sketch" in MODE_LABELS
    assert IMAGE_MODES[:6] == ("threshold", "floyd", "atkinson", "ordered", "grayscale", "depth3d")


def test_sketch_darkness_marks_edges_only():
    d = 1.0 - step().astype(np.float32) / 255
    e = sketch_darkness(d)
    assert e.shape == d.shape and e.min() >= 0 and e.max() <= 1
    assert e[10, 19] == pytest.approx(1.0) and e[10, 20] == pytest.approx(1.0)
    assert e[10, 2] == 0 and e[10, -3] == 0       # flat black and flat white: nothing
    assert np.allclose(sketch_darkness(np.full((10, 10), 0.6, np.float32)), 0)


@pytest.mark.parametrize("negative", [False, True])
def test_sketch_mode_burns_the_outline_of_a_disc(negative):
    y, x = np.mgrid[0:60, 0:60]
    r = np.hypot(x - 30, y - 30)
    g = np.where(r < 15, 0, 255).astype(np.uint8)
    pm = power_map(g, RasterSettings(mode="sketch", power=40, negative=negative))
    full = round(40 / 100 * 255)
    assert set(np.unique(pm)) <= {0, full}
    ring = (r > 13) & (r < 17)
    assert (pm[ring] > 0).mean() > 0.5
    assert (pm[r < 9] == 0).all() and (pm[r > 22] == 0).all()   # filled areas stay free


def test_sketch_gcode_is_pi_safe_and_shorter_than_dithering():
    from lumacut_job.estimate import estimate_gcode
    s = RasterSettings(mode="sketch", line_interval_mm=0.2, overscan_mm=0)
    gc = raster_gcode(photo(), (60, 60), 16, 12, s)
    pi_check(gc)
    dith = raster_gcode(photo(), (60, 60), 16, 12,
                        RasterSettings(mode="jarvis", line_interval_mm=0.2, overscan_mm=0))
    assert estimate_gcode(gc).cut_length_mm < estimate_gcode(dith).cut_length_mm


def test_sketch_with_dot_width_and_contrast():
    g = photo()
    a = power_map(g, RasterSettings(mode="sketch"))
    b = power_map(g, RasterSettings(mode="sketch", contrast=60, sharpen=100))
    assert (b > 0).sum() > (a > 0).sum()           # contrast / sharpen strengthen the lines
    s = RasterSettings(mode="sketch", line_interval_mm=0.2, overscan_mm=0, dot_width_mm=0.1)
    pi_check(raster_gcode(g, (60, 60), 16, 12, s))


def test_filter_margin_and_power_map_margin_equal_full_image():
    s = RasterSettings(mode="sketch", sharpen=100, sharpen_radius=2)
    m = filter_margin(s)
    assert m == 6 + 4
    assert filter_margin(RasterSettings()) == 0
    g = photo(90, 70)
    # filters on a margin crop = filters on the whole image for the inner pixels
    full_d = sketch_darkness(1 - adjust_gray(g, s) / 255)
    y0, x0, h, w = 25, 30, 20, 25
    crop = g[y0 - m:y0 + h + m, x0 - m:x0 + w + m]
    part = sketch_darkness(1 - adjust_gray(crop, s) / 255)[m:m + h, m:m + w]
    assert np.allclose(part, full_d[y0:y0 + h, x0:x0 + w], atol=1e-5)
    pm = power_map(crop, s, margin=m)
    assert pm.shape == (h, w)
    pm2 = power_map(crop, s, margin=(m, m, m, m))
    assert (pm == pm2).all()


# ------------------------------------------------------------- model / images
def test_image_settings_adjustments_roundtrip_and_clamp():
    from lumacut_canvas.model import ImageSettings
    st = ImageSettings.from_dict({"mode": "sketch", "brightness": 300, "contrast": -300,
                                  "gamma": 0.01, "sharpen": 9999, "sharpen_radius": 0})
    assert st.mode == "sketch"
    assert (st.brightness, st.contrast, st.gamma, st.sharpen, st.sharpen_radius) == \
        (100.0, -100.0, 0.2, 500.0, 0.5)
    assert ImageSettings.from_dict(json.loads(json.dumps(st.to_dict()))) == st
    old = ImageSettings.from_dict({"mode": "floyd"})
    assert (old.brightness, old.contrast, old.gamma, old.sharpen, old.sharpen_radius) == \
        (0.0, 0.0, 1.0, 0.0, 1.0)


def _doc_with_image(qapp, rot=0.0, **settings):
    from lumacut_canvas.model import Document, Geometry, ImageSettings, Layer, RasterImage, Shape
    from lumacut_import.image import grayscale_png
    from PySide6.QtGui import QColor, QImage
    d = Document()
    d.add_layer(Layer("Ebene 1"))
    img = QImage(60, 30, QImage.Format_RGB32)
    for x in range(60):
        for y in range(30):
            v = 60 + int(150 * x / 59)
            img.setPixelColor(x, y, QColor(v, v, v))
    png, pw, ph = grayscale_png(img)
    geom = Geometry(80, 80, 12, 6)
    if rot:
        geom = Geometry(80, 80, 12, 6, rot)
    sh = Shape("image", geom, d.active_layer_id,
               image=RasterImage(png, pw, ph, ImageSettings(**settings)))
    d.add_shape(sh)
    return d, sh


def test_raster_settings_carry_the_adjustments(qapp):
    from lumacut_job.images import raster_settings
    _d, sh = _doc_with_image(qapp, mode="sketch", brightness=5, contrast=10, gamma=1.5,
                             sharpen=40, sharpen_radius=2)
    rs = raster_settings(sh)
    assert (rs.mode, rs.brightness, rs.contrast, rs.gamma, rs.sharpen, rs.sharpen_radius) == \
        ("sketch", 5, 10, 1.5, 40, 2)


@pytest.mark.parametrize("mode", ["jarvis", "sketch", "grayscale", "depth3d"])
def test_adjusted_image_objects_send_pi_safe(qapp, mode):
    from lumacut_job.images import image_job
    _d, a = _doc_with_image(qapp, mode=mode, line_interval_mm=0.2, depth_levels=3)
    _d, b = _doc_with_image(qapp, mode=mode, line_interval_mm=0.2, depth_levels=3,
                            brightness=-20, contrast=40, gamma=0.8, sharpen=100)
    job = image_job(b)
    pi_check("\n".join(["G21", "G90", "M5 I", "M3 I"] + job.lines + ["M5 I", "M400"]))
    if mode != "sketch":
        assert job.lines != image_job(a).lines


def test_old_image_document_gcode_is_unchanged(qapp):
    """A document saved before round 28 (no adjustment keys) gives the same G-code."""
    from lumacut_canvas.model import Document
    from lumacut_job.images import image_job
    for mode in ("floyd", "jarvis", "halftone", "grayscale", "depth3d"):
        d, sh = _doc_with_image(qapp, rot=30.0, mode=mode, line_interval_mm=0.2,
                                depth_levels=3)
        data = json.loads(json.dumps(d.to_dict()))
        for s in data["objects"]:
            for k in ("brightness", "contrast", "gamma", "sharpen", "sharpen_radius"):
                s["image"]["settings"].pop(k)
        d2 = Document.from_dict(data)
        assert image_job(d2.shapes[0]).lines == image_job(sh).lines


def test_render_inside_mask_for_rotated_images(qapp):
    from lumacut_job.images import render_gray, render_inside
    _d, flat = _doc_with_image(qapp, mode="floyd", line_interval_mm=0.2)
    assert render_inside(flat, 0.2) is None
    _d, sh = _doc_with_image(qapp, rot=30.0, mode="floyd", line_interval_mm=0.2)
    inside = render_inside(sh, 0.2)
    gray, _ = render_gray(sh, 0.2)
    assert inside.shape == gray.shape and inside.dtype == bool
    assert inside[inside.shape[0] // 2, inside.shape[1] // 2]
    assert not inside[0, 0] and not inside[-1, -1]
    assert 0.4 < inside.mean() < 0.95


def test_rotated_dark_adjusted_image_never_burns_the_box_corners(qapp, monkeypatch):
    from lumacut_job import images
    _d, sh = _doc_with_image(qapp, rot=30.0, mode="threshold", line_interval_mm=0.2,
                             brightness=-100)
    seen = {}
    real = images.power_map

    def spy(gray, s, inside=None, **kw):
        pm = real(gray, s, inside=inside, **kw)
        seen["pm"], seen["inside"] = pm, inside
        return pm

    monkeypatch.setattr(images, "power_map", spy)
    images.image_job(sh)
    pm, inside = seen["pm"], seen["inside"]
    assert inside is not None
    assert (pm[~inside] == 0).all() and (pm[inside] > 0).all()


# ------------------------------------------------------------- preview
def test_preview_matches_the_engine_with_adjustments():
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import preview_array
    g = photo()
    for mode in ("jarvis", "sketch", "grayscale"):
        st = ImageSettings(mode=mode, line_interval_mm=0.2, power=50, brightness=10,
                           contrast=25, gamma=1.4, sharpen=120, sharpen_radius=1.5)
        pv = preview_array(g, 16, 12, st)
        rs = RasterSettings(mode=mode, power=50, line_interval_mm=0.2, brightness=10,
                            contrast=25, gamma=1.4, sharpen=120, sharpen_radius=1.5)
        pm = power_map(raster.resample(g, 16, 12, 0.2), rs)
        assert not pv.cropped and pv.pixels.shape == pm.shape
        assert ((pv.pixels < 255) == (pm > 0)).all()


def test_preview_depth_uses_adjustments():
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import preview_array
    g = gradient(60, 30)
    a = preview_array(g, 12, 6, ImageSettings(mode="depth3d", line_interval_mm=0.2,
                                              depth_levels=4))
    b = preview_array(g, 12, 6, ImageSettings(mode="depth3d", line_interval_mm=0.2,
                                              depth_levels=4, brightness=-30))
    assert b.pixels.mean() < a.pixels.mean()


def test_cropped_preview_filters_see_the_crop_margin():
    """Sharpen / sketch near the crop edge = the same pixels as on the whole image."""
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import preview_array
    g = photo(200, 200)
    st = ImageSettings(mode="grayscale", line_interval_mm=0.1, sharpen=200, sharpen_radius=2)
    pv = preview_array(g, 20, 20, st, max_pixels=10_000)
    assert pv.cropped and pv.pixels.shape == (100, 100)
    rs = RasterSettings(mode="grayscale", line_interval_mm=0.1, sharpen=200, sharpen_radius=2)
    whole = power_map(raster.resample(g, 20, 20, 0.1), rs)[50:150, 50:150]
    ref = np.clip(np.rint(255 - whole * 255 / round(0.6 * 255)), 0, 255).astype(np.uint8)
    assert (pv.pixels == ref).all()
    # sketch crop at the image border (asymmetric margin) still works
    pv = preview_array(g, 20, 10, ImageSettings(mode="sketch", line_interval_mm=0.1),
                       max_pixels=5_000)
    assert pv.cropped and pv.pixels.size <= 5_000


def test_preview_without_adjustments_unchanged():
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import preview_array
    g = photo(200, 200)
    st = ImageSettings(mode="floyd", line_interval_mm=0.1)
    pv = preview_array(g, 20, 20, st, max_pixels=10_000)
    pm = power_map(raster.resample(g, 20, 20, 0.1)[50:150, 50:150],
                   RasterSettings(mode="floyd", line_interval_mm=0.1))
    assert ((pv.pixels == 0) == (pm > 0)).all()


# ------------------------------------------------------------- dialog
def _png(qapp):
    from PySide6.QtGui import QColor, QImage
    from lumacut_import.image import grayscale_png
    img = QImage(60, 30, QImage.Format_RGB32)
    for x in range(60):
        for y in range(30):
            v = int(255 * x / 59)
            img.setPixelColor(x, y, QColor(v, v, v))
    png, pw, _ph = grayscale_png(img)
    return png, pw


def _select(dlg, mode):
    dlg.mode.setCurrentIndex([dlg.mode.itemData(i) for i in range(dlg.mode.count())].index(mode))


def test_dialog_adjustment_fields_roundtrip(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    st = ImageSettings(mode="jarvis", brightness=15, contrast=-20, gamma=1.6, sharpen=80,
                       sharpen_radius=2.5)
    dlg = ImageSettingsDialog(st, 10.0, 100)
    assert dlg.settings() == st.normalized()
    assert dlg.adjust_box.title() == "Bildanpassung" and dlg.sharpen_radius.isEnabled()
    dlg.sharpen.setValue(0)
    assert not dlg.sharpen_radius.isEnabled()
    dlg.reset_adjust.click()
    out = dlg.settings()
    assert (out.brightness, out.contrast, out.gamma, out.sharpen, out.sharpen_radius) == \
        (0.0, 0.0, 1.0, 0.0, 1.0)
    assert out.mode == "jarvis"


def test_dialog_keeps_old_settings_unchanged(qapp):
    """Opening and accepting an old image must not count as a change."""
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    for st in (ImageSettings(), ImageSettings(mode="halftone", halftone_cpi=40),
               ImageSettings(mode="depth3d", depth_levels=5)):
        assert ImageSettingsDialog(st, 10.0, 100).settings() == st.normalized()


def test_dialog_sketch_hint_and_preview(qapp):
    from PySide6.QtCore import QCoreApplication, QElapsedTimer
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    png, pw = _png(qapp)
    dlg = ImageSettingsDialog(ImageSettings(mode="floyd", line_interval_mm=0.2), 12.0, pw,
                              png=png, height_mm=6.0)
    assert dlg.preview_runs == 1
    first = dlg.last_preview.pixels.copy()
    _select(dlg, "sketch")
    assert "Kanten" in dlg.hint.text()
    dlg.update_preview()
    assert dlg.preview_runs == 2 and (dlg.last_preview.pixels != first).any()
    # adjustments trigger a debounced preview
    _select(dlg, "jarvis")
    dlg.update_preview()
    before = dlg.last_preview.burn_share
    dlg.brightness.setValue(40)
    dlg.gamma.setValue(1.5)
    runs = dlg.preview_runs
    t = QElapsedTimer()
    t.start()
    while dlg.preview_runs == runs and t.elapsed() < 3000:
        QCoreApplication.processEvents()
    assert dlg.preview_runs == runs + 1
    assert dlg.last_preview.burn_share < before


def test_edit_image_settings_stores_the_adjustments(qapp, tmp_path, monkeypatch):
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
        img.fill(QColor(90, 90, 90))
        p = tmp_path / "foto.png"
        img.save(str(p))
        ids = w.import_tools.import_path(p)

        class FakeDialog(import_qt.ImageSettingsDialog):
            def exec(self):  # noqa: A003
                _select(self, "sketch")
                self.contrast.setValue(30)
                self.sharpen.setValue(150)
                return QDialog.Accepted

        monkeypatch.setattr(import_qt, "ImageSettingsDialog", FakeDialog)
        assert w.import_tools.edit_image_settings(ids[0])
        st = w.canvas.document.shape(ids[0]).image.settings
        assert (st.mode, st.contrast, st.sharpen) == ("sketch", 30.0, 150.0)
        w.canvas.undo_stack.undo()
        st = w.canvas.document.shape(ids[0]).image.settings
        assert (st.contrast, st.sharpen) == (0.0, 0.0)
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
