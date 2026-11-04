"""Review round 30: manual levels (black / white point) for image objects – engine,
job, preview, histogram markers, rotated-image histogram and the dialog."""
from __future__ import annotations

import json

import numpy as np
import pytest

from lumacut_job.raster import RasterSettings, adjust_gray, auto_levels, gray_histogram

from test_image_levels import _doc_with_image, _job_power_map, _png, photo


# ------------------------------------------------------------- engine
def test_levels_map_black_and_white_point_linearly():
    g = np.array([[0, 50, 125, 200, 255]], np.uint8)
    out = adjust_gray(g, RasterSettings(black_point=50, white_point=200))
    assert out[0, 0] == 0 and out[0, 1] == 0
    assert abs(out[0, 2] - 127.5) < 0.6
    assert out[0, 3] == 255 and out[0, 4] == 255


def test_default_levels_leave_the_image_unchanged():
    g = photo()
    s = RasterSettings()
    assert not s.levels_set() and not s.adjusted()
    assert (adjust_gray(g, s) == g.astype(np.float32)).all()
    assert RasterSettings(black_point=1).adjusted()
    assert RasterSettings(white_point=254).adjusted()


def test_only_white_point_lightens_and_only_black_point_darkens():
    g = photo()
    light = adjust_gray(g, RasterSettings(white_point=150))
    dark = adjust_gray(g, RasterSettings(black_point=120))
    assert light.mean() > g.mean() > dark.mean()
    assert (light >= g - 0.5).all() and (dark <= g + 0.5).all()


def test_levels_run_after_sharpen_and_before_brightness_contrast_gamma():
    g = photo()
    lv = adjust_gray(g, RasterSettings(sharpen=80, black_point=60, white_point=190))
    full = adjust_gray(g, RasterSettings(sharpen=80, black_point=60, white_point=190,
                                         brightness=-10, contrast=20, gamma=1.5))
    # the rest of the chain applied to the levelled image gives the same result
    rest = adjust_gray(lv, RasterSettings(brightness=-10, contrast=20, gamma=1.5))
    assert np.abs(full - rest).max() < 1.0


@pytest.mark.parametrize("bp,wp", [(100, 100), (200, 100), (-1, 255), (0, 256)])
def test_levels_validation(bp, wp):
    with pytest.raises(ValueError):
        RasterSettings(black_point=bp, white_point=wp).validate()
    RasterSettings(black_point=0, white_point=1).validate()
    RasterSettings(black_point=254, white_point=255).validate()


def test_image_settings_normalize_and_roundtrip():
    from lumacut_canvas.model import ImageSettings
    st = ImageSettings(black_point=300, white_point=10).normalized()
    assert (st.black_point, st.white_point) == (254, 255)
    st = ImageSettings(black_point=120, white_point=80).normalized()
    assert (st.black_point, st.white_point) == (120, 121)
    st = ImageSettings(black_point=-5, white_point=999).normalized()
    assert (st.black_point, st.white_point) == (0, 255)
    st = ImageSettings(black_point=30, white_point=220)
    assert ImageSettings.from_dict(json.loads(json.dumps(st.to_dict()))) == st.normalized()
    old = ImageSettings().to_dict()
    old.pop("black_point"), old.pop("white_point")
    assert ImageSettings.from_dict(old) == ImageSettings().normalized()


def test_auto_levels_on_top_of_manual_levels():
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import auto_levels_for
    g = photo(lo=70, hi=180)
    b0, c0 = auto_levels_for(g, 8.0, 6.0, ImageSettings(line_interval_mm=0.1))
    assert c0 > 20
    b, c = auto_levels_for(g, 8.0, 6.0, ImageSettings(line_interval_mm=0.1,
                                                      black_point=72, white_point=178))
    assert abs(b) <= 3 and 0 <= c <= 5          # levels already stretch the range


# ------------------------------------------------------------- job / preview
def test_levels_change_the_job_and_old_documents_do_not(qapp):
    from lumacut_canvas.model import Document
    from lumacut_job.images import image_job
    d, sh = _doc_with_image(qapp, rot=0.0, mode="floyd", line_interval_mm=0.2)
    _d2, lv = _doc_with_image(qapp, rot=0.0, mode="floyd", line_interval_mm=0.2,
                              black_point=90, white_point=170)
    assert image_job(lv).lines != image_job(sh).lines
    data = d.to_dict()
    for s in data["objects"]:
        s["image"]["settings"].pop("black_point")
        s["image"]["settings"].pop("white_point")
    d_old = Document.from_dict(json.loads(json.dumps(data)))
    assert image_job(d_old.shapes[0]).lines == image_job(sh).lines


@pytest.mark.parametrize("rot", [0.0, 30.0])
@pytest.mark.parametrize("mode", ["floyd", "threshold", "sketch", "halftone"])
def test_shape_preview_with_levels_is_the_job(qapp, monkeypatch, rot, mode):
    from lumacut_import.image_preview import preview_shape
    _d, sh = _doc_with_image(qapp, rot=rot, mode=mode, line_interval_mm=0.1, power=50,
                             black_point=80, white_point=190)
    pm = _job_power_map(monkeypatch, sh)
    pv = preview_shape(sh, sh.image.settings)
    assert pv.pixels.shape == pm.shape
    assert ((pv.pixels < 255) == (pm > 0)).all()


def test_grayscale_preview_with_levels_is_the_job(qapp, monkeypatch):
    from lumacut_import.image_preview import preview_shape
    _d, sh = _doc_with_image(qapp, rot=20.0, mode="grayscale", line_interval_mm=0.1,
                             power=80, min_power=10, black_point=70, white_point=200)
    pm = _job_power_map(monkeypatch, sh)
    pv = preview_shape(sh, sh.image.settings)
    ref = np.clip(np.rint(255 - pm * 255 / round(0.8 * 255)), 0, 255).astype(np.uint8)
    assert (pv.pixels == ref).all()


def test_rotated_levels_keep_the_box_corners_white(qapp):
    from lumacut_import.image_preview import preview_shape
    from lumacut_job.images import render_inside
    _d, sh = _doc_with_image(qapp, rot=30.0, mode="threshold", line_interval_mm=0.1,
                             black_point=0, white_point=60)        # everything ≈ white
    pv = preview_shape(sh, sh.image.settings)
    inside = render_inside(sh, 0.1)
    assert (pv.pixels[~inside] == 255).all()
    _d, sh = _doc_with_image(qapp, rot=30.0, mode="threshold", line_interval_mm=0.1,
                             black_point=230, white_point=255)     # everything ≈ black
    pv = preview_shape(sh, sh.image.settings)
    assert (pv.pixels[~inside] == 255).all() and (pv.pixels[inside] < 255).mean() > 0.95


def test_depth3d_preview_follows_the_black_point(qapp):
    from lumacut_import.image_preview import preview_shape
    _d, a = _doc_with_image(qapp, mode="depth3d", line_interval_mm=0.1, depth_levels=4)
    _d, b = _doc_with_image(qapp, mode="depth3d", line_interval_mm=0.1, depth_levels=4,
                            black_point=150)
    pa, pb = preview_shape(a, a.image.settings), preview_shape(b, b.image.settings)
    assert pb.pixels.mean() < pa.pixels.mean()


# ------------------------------------------------------------- histograms
def test_histograms_carry_the_points_and_clip_more_with_levels():
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import histograms
    g = photo(lo=70, hi=180)
    h0 = histograms(g, 8.0, 6.0, ImageSettings(line_interval_mm=0.1))
    assert h0.points == (0, 255) and h0.black_share == 0 and h0.white_share == 0
    h = histograms(g, 8.0, 6.0, ImageSettings(line_interval_mm=0.1,
                                               black_point=100, white_point=150))
    assert h.points == (100, 150)
    assert h.black_share > 0.1 and h.white_share > 0.1
    assert (h.source == h0.source).all()


def test_rotated_histogram_counts_only_the_image(qapp):
    from lumacut_import.image_preview import histograms_rendered, render_for_preview
    _d, sh = _doc_with_image(qapp, rot=30.0, mode="floyd", line_interval_mm=0.1)
    gray, inside = render_for_preview(sh, sh.image.settings)
    assert inside is not None and not inside.all()
    h = histograms_rendered(gray, inside, sh.image.settings)
    assert h.source.sum() == inside.sum() == h.adjusted.sum()
    # the white box corners are not counted as pure white
    assert h.source[255] < (~inside).sum()
    full = gray_histogram(gray)
    assert full[255] - h.source[255] == pytest.approx((~inside).sum(), abs=2)


def test_rendered_histogram_of_big_images_is_sampled(qapp):
    from lumacut_import.image_preview import histograms_rendered
    g = np.tile(np.arange(256, dtype=np.uint8), (800, 4))        # 800 × 1024
    from lumacut_canvas.model import ImageSettings
    st = ImageSettings(line_interval_mm=0.1, sharpen=50)
    h = histograms_rendered(g, None, st, max_pixels=50_000)
    assert h.source.sum() <= 60_000 and h.source.sum() > 30_000
    assert (h.source > 0).sum() > 100


# ------------------------------------------------------------- dialog
def test_dialog_black_and_white_point(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    png, pw = _png(qapp)
    dlg = ImageSettingsDialog(ImageSettings(mode="jarvis", line_interval_mm=0.2,
                                            black_point=20, white_point=230),
                              12.0, pw, png=png, height_mm=6.0)
    assert (dlg.black_point.value(), dlg.white_point.value()) == (20, 230)
    runs = dlg.preview_runs
    dlg.black_point.setValue(90)
    dlg.white_point.setValue(160)
    dlg.update_preview()
    assert dlg.preview_runs > runs
    assert dlg.last_histograms.points == (90, 160)
    assert "Schwarz-/Weißpunkt 90 / 160" in dlg.histogram_label.text()
    out = dlg.settings()
    assert (out.black_point, out.white_point) == (90, 160)
    dlg.histogram.grab()                                # markers paint without errors
    # the points push each other instead of crossing
    dlg.black_point.setValue(200)
    assert dlg.white_point.value() == 201
    dlg.white_point.setValue(50)
    assert dlg.black_point.value() == 49
    dlg.reset_adjustments()
    assert (dlg.black_point.value(), dlg.white_point.value()) == (0, 255)
    assert dlg.settings() == ImageSettings(mode="jarvis", line_interval_mm=0.2).normalized()


def test_dialog_levels_darken_the_preview(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    png, pw = _png(qapp)
    dlg = ImageSettingsDialog(ImageSettings(mode="floyd", line_interval_mm=0.2),
                              12.0, pw, png=png, height_mm=6.0)
    before = dlg.last_preview.burn_share
    dlg.black_point.setValue(150)
    dlg.update_preview()
    assert dlg.last_preview.burn_share > before + 0.2


def test_rotated_dialog_histogram_uses_the_rendered_image(qapp, monkeypatch):
    from lumacut_import import image_preview
    from lumacut_import.qt import ImageSettingsDialog
    from lumacut_job.images import render_inside
    _d, sh = _doc_with_image(qapp, rot=30.0, mode="floyd", line_interval_mm=0.1)
    renders = []
    real = image_preview.render_for_preview
    monkeypatch.setattr(image_preview, "render_for_preview",
                        lambda *a, **k: renders.append(1) or real(*a, **k))
    dlg = ImageSettingsDialog(sh.image.settings, sh.geom.w, sh.image.px_width, shape=sh)
    assert len(renders) == 1                       # histogram and preview share the render
    assert dlg.last_histograms.source.sum() == render_inside(sh, 0.1).sum()
    _d, flat = _doc_with_image(qapp, rot=0.0, mode="floyd", line_interval_mm=0.1)
    dlg2 = ImageSettingsDialog(flat.image.settings, flat.geom.w, flat.image.px_width,
                               shape=flat)
    assert dlg2.last_histograms.source.sum() == 120 * 60     # whole image, line interval


def test_edit_image_settings_stores_levels_with_undo(qapp, tmp_path, monkeypatch):
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

        class FakeDialog(import_qt.ImageSettingsDialog):
            def exec(self):  # noqa: A003
                self.black_point.setValue(95)
                self.white_point.setValue(135)
                return QDialog.Accepted

        monkeypatch.setattr(import_qt, "ImageSettingsDialog", FakeDialog)
        assert w.import_tools.edit_image_settings(ids[0])
        st = w.canvas.document.shape(ids[0]).image.settings
        assert (st.black_point, st.white_point) == (95, 135)
        w.canvas.undo_stack.undo()
        st = w.canvas.document.shape(ids[0]).image.settings
        assert (st.black_point, st.white_point) == (0, 255)
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
