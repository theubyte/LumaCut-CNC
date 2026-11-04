"""Review round 32: tone curve (Gradationskurve) for image objects – engine, model,
job, preview, curve editor widget and the image settings dialog."""
from __future__ import annotations

import json

import numpy as np
import pytest

from lumacut_job.raster import RasterSettings, adjust_gray, apply_curve, curve_lut

from test_image_levels import _doc_with_image, _job_power_map, _png, photo

S_CURVE = ((0, 0), (64, 44), (192, 212), (255, 255))


# ------------------------------------------------------------- engine
def test_curve_passes_through_every_point_and_identity_is_linear():
    lut = curve_lut(S_CURVE, 256) * 255
    for x, y in S_CURVE:
        assert abs(lut[x] - y) < 1e-6
    ident = curve_lut(((0, 0), (255, 255)), 256)
    assert np.allclose(ident, np.linspace(0, 1, 256))
    assert np.allclose(curve_lut((), 256), np.linspace(0, 1, 256))


@pytest.mark.parametrize("pts", [
    S_CURVE,
    ((0, 0), (20, 200), (40, 210), (255, 255)),          # steep then flat: no overshoot
    ((0, 0), (128, 250), (255, 255)),
    ((0, 0), (10, 0), (12, 255), (255, 255)),
])
def test_rising_points_give_a_monotone_curve_without_overshoot(pts):
    lut = curve_lut(pts)
    assert (np.diff(lut) >= -1e-12).all()
    assert lut.min() >= 0 and lut.max() <= 1


def test_curve_is_flat_beyond_the_end_points_and_can_invert():
    lut = curve_lut(((40, 10), (200, 240)), 256) * 255
    assert np.allclose(lut[:41], 10) and np.allclose(lut[200:], 240)
    inv = curve_lut(((0, 255), (255, 0)), 256) * 255
    assert inv[0] == 255 and inv[255] == 0 and (np.diff(inv) <= 1e-9).all()


def test_flat_segment_between_equal_points_stays_flat():
    lut = curve_lut(((0, 0), (100, 128), (160, 128), (255, 255)), 256) * 255
    assert np.allclose(lut[100:161], 128, atol=1e-6)


def test_apply_curve_matches_the_table():
    v = np.linspace(0, 1, 1001, dtype=np.float32)
    out = apply_curve(v, S_CURVE)
    ref = np.interp(v, np.linspace(0, 1, 4096), curve_lut(S_CURVE))
    assert np.abs(out - ref).max() < 1e-5 and out.dtype == np.float32


def test_s_curve_darkens_shadows_and_lightens_highlights():
    g = np.array([[0, 64, 128, 192, 255]], np.uint8)
    out = adjust_gray(g, RasterSettings(curve=S_CURVE))
    assert out[0, 0] == 0 and out[0, 4] == 255
    assert abs(out[0, 1] - 44) < 0.6 and abs(out[0, 3] - 212) < 0.6
    assert abs(out[0, 2] - 128) < 3


def test_default_curve_leaves_the_image_unchanged():
    g = photo()
    s = RasterSettings()
    assert not s.curve and not s.adjusted()
    assert (adjust_gray(g, s) == g.astype(np.float32)).all()
    assert RasterSettings(curve=S_CURVE).adjusted()


def test_curve_runs_after_levels_and_before_brightness_contrast_gamma():
    g = photo()
    lv = adjust_gray(g, RasterSettings(sharpen=60, black_point=40, white_point=210))
    cv = adjust_gray(lv, RasterSettings(curve=S_CURVE))
    full = adjust_gray(g, RasterSettings(sharpen=60, black_point=40, white_point=210,
                                         curve=S_CURVE, brightness=-8, contrast=15,
                                         gamma=1.3))
    rest = adjust_gray(cv, RasterSettings(brightness=-8, contrast=15, gamma=1.3))
    assert np.abs(full - rest).max() < 1.0


@pytest.mark.parametrize("curve", [
    ((0, 0),),                                           # one point
    ((0, 0), (0, 10), (255, 255)),                       # inputs not rising
    ((0, 0), (300, 255)),                                # out of range
    tuple((i * 10, i * 10) for i in range(20)),          # too many points
])
def test_curve_validation(curve):
    with pytest.raises(ValueError):
        RasterSettings(curve=curve).validate()
    RasterSettings(curve=S_CURVE).validate()


# ------------------------------------------------------------- model
def test_normalize_curve():
    from lumacut_canvas.model import CURVE_MAX_POINTS, normalize_curve
    assert normalize_curve(()) == ()
    assert normalize_curve(None) == ()
    assert normalize_curve([[0, 0], [255, 255]]) == ()          # identity = linear
    assert normalize_curve([(0, 0), (128, 128), (255, 255)]) == ()
    assert normalize_curve([(5, 5)]) == ()
    assert normalize_curve("kaputt") == ()
    assert normalize_curve([[255, 260], [-3, 4.4], [128, 90]]) == ((0, 4), (128, 90), (255, 255))
    assert normalize_curve([(0, 0), (100, 50), (100, 70), (255, 255)]) == \
        ((0, 0), (100, 70), (255, 255))                          # same input: last wins
    many = normalize_curve([(i * 10, 255 - i * 10) for i in range(26)])
    assert len(many) == CURVE_MAX_POINTS and many[0] == (0, 255) and many[-1] == (250, 5)


def test_image_settings_roundtrip_and_old_files():
    from lumacut_canvas.model import ImageSettings
    st = ImageSettings(curve=[[0, 0], [64, 44], [192, 212], [255, 255]]).normalized()
    assert st.curve == S_CURVE
    d = json.loads(json.dumps(st.to_dict()))
    assert d["curve"] == [list(p) for p in S_CURVE]
    assert ImageSettings.from_dict(d) == st
    assert "curve" not in ImageSettings().to_dict()            # linear: file unchanged
    hash(st)                                                    # frozen + hashable


# ------------------------------------------------------------- job / preview
def test_curve_changes_the_job_and_old_documents_do_not(qapp):
    from lumacut_canvas.model import Document
    from lumacut_job.images import image_job
    d, sh = _doc_with_image(qapp, rot=0.0, mode="floyd", line_interval_mm=0.2)
    _d2, cv = _doc_with_image(qapp, rot=0.0, mode="floyd", line_interval_mm=0.2,
                              curve=((0, 0), (128, 60), (255, 255)))
    assert image_job(cv).lines != image_job(sh).lines
    data = json.loads(json.dumps(d.to_dict()))
    assert all("curve" not in s["image"]["settings"] for s in data["objects"])
    d_old = Document.from_dict(data)
    assert image_job(d_old.shapes[0]).lines == image_job(sh).lines


@pytest.mark.parametrize("rot", [0.0, 30.0])
@pytest.mark.parametrize("mode", ["floyd", "threshold", "halftone"])
def test_shape_preview_with_curve_is_the_job(qapp, monkeypatch, rot, mode):
    from lumacut_import.image_preview import preview_shape
    _d, sh = _doc_with_image(qapp, rot=rot, mode=mode, line_interval_mm=0.1, power=50,
                             curve=S_CURVE)
    pm = _job_power_map(monkeypatch, sh)
    pv = preview_shape(sh, sh.image.settings)
    assert pv.pixels.shape == pm.shape
    assert ((pv.pixels < 255) == (pm > 0)).all()


def test_grayscale_preview_with_curve_is_the_job(qapp, monkeypatch):
    from lumacut_import.image_preview import preview_shape
    _d, sh = _doc_with_image(qapp, rot=20.0, mode="grayscale", line_interval_mm=0.1,
                             power=80, min_power=10, curve=((0, 0), (128, 170), (255, 255)))
    pm = _job_power_map(monkeypatch, sh)
    pv = preview_shape(sh, sh.image.settings)
    ref = np.clip(np.rint(255 - pm * 255 / round(0.8 * 255)), 0, 255).astype(np.uint8)
    assert (pv.pixels == ref).all()


def test_auto_levels_ignore_the_curve():
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import auto_points_for
    g = photo(lo=70, hi=180)
    a = auto_points_for(g, 8.0, 6.0, ImageSettings(line_interval_mm=0.1))
    b = auto_points_for(g, 8.0, 6.0, ImageSettings(line_interval_mm=0.1, curve=S_CURVE))
    assert a == b


def test_curve_input_histogram_follows_the_levels():
    from lumacut_import.image_preview import curve_input_histogram
    src = np.zeros(256)
    src[[50, 100, 150]] = (3, 4, 5)
    assert (curve_input_histogram(src) == src).all()
    out = curve_input_histogram(src, 50, 150)
    assert out.sum() == src.sum()
    assert out[0] == 3 and out[128] == 4 and out[255] == 5


# ------------------------------------------------------------- widget
def test_curve_widget_edit_by_mouse(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from lumacut_import.curve_widget import CurveWidget
    w = CurveWidget()
    w.resize(262, 262)
    seen = []
    w.curve_changed.connect(seen.append)
    assert w.curve() == () and w.points() == [(0, 0), (255, 255)]
    mid = w.to_widget(128, 128).toPoint()
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, mid)       # new point on the curve
    assert len(w.points()) == 3 and w.curve() == ()              # still the diagonal
    target = w.to_widget(128, 190).toPoint()
    QTest.mouseMove(w, target)
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, target)
    x, y = w.points()[1]
    assert abs(x - 128) <= 1 and abs(y - 190) <= 1
    assert seen and seen[-1] == w.curve() and len(w.curve()) == 3
    # drag stays between the neighbours
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, w.to_widget(*w.points()[1]).toPoint())
    QTest.mouseMove(w, w.to_widget(255, 255).toPoint() + QPoint(30, 0))
    QTest.mouseRelease(w, Qt.LeftButton)
    assert w.points()[1][0] == 254
    # right click removes the inner point
    QTest.mouseClick(w, Qt.RightButton, Qt.NoModifier, w.to_widget(*w.points()[1]).toPoint())
    assert w.points() == [(0, 0), (255, 255)] and w.curve() == ()
    w.grab()


def test_curve_widget_end_points_and_keyboard(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from lumacut_import.curve_widget import CurveWidget
    w = CurveWidget(((0, 30), (255, 255)))
    w.resize(262, 262)
    w.set_histogram(np.arange(256))
    w.grab()
    w.remove_point(0)                                # end point back to its corner
    assert w.curve() == ()
    i = w.add_point(100, 50)
    assert i == 1 and w.points()[1] == (100, 50)
    assert w.add_point(100) is None                  # input already used
    w.setFocus()
    QTest.keyClick(w, Qt.Key_Delete)
    assert w.points() == [(0, 0), (255, 255)]
    w.set_curve(S_CURVE)
    QTest.mouseDClick(w, Qt.LeftButton, Qt.NoModifier, w.to_widget(64, 44).toPoint())
    assert w.curve() == ((0, 0), (192, 212), (255, 255))


def test_curve_widget_point_limit(qapp):
    from lumacut_canvas.model import CURVE_MAX_POINTS
    from lumacut_import.curve_widget import CurveWidget
    w = CurveWidget()
    for k in range(1, 40):
        w.add_point(k * 6)
    assert len(w.points()) == CURVE_MAX_POINTS


def test_presets_are_valid_and_named():
    from lumacut_canvas.model import normalize_curve
    from lumacut_import.curve_widget import CURVE_PRESETS, CUSTOM_LABEL, preset_name
    for name, pts in CURVE_PRESETS.items():
        assert normalize_curve(pts) == tuple(pts)
        if pts:
            RasterSettings(curve=pts).validate()
        assert preset_name(pts) == name
    assert preset_name(((0, 0), (10, 90), (255, 255))) == CUSTOM_LABEL


# ------------------------------------------------------------- dialog
def test_dialog_curve_presets_preview_and_reset(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.curve_widget import CURVE_PRESETS
    from lumacut_import.qt import ImageSettingsDialog
    png, pw = _png(qapp)
    dlg = ImageSettingsDialog(ImageSettings(mode="floyd", line_interval_mm=0.2, curve=S_CURVE),
                              12.0, pw, png=png, height_mm=6.0)
    assert dlg.curve.curve() == S_CURVE
    assert dlg.curve_preset.currentText() == "Kontrast verstärken (S-Kurve)"
    assert "Kurve: Kontrast verstärken" in dlg.histogram_label.text()
    before = dlg.last_preview.burn_share
    idx = dlg.curve_preset.findText("Mitteltöne abdunkeln")
    dlg.curve_preset.setCurrentIndex(idx)
    dlg.curve_preset.activated.emit(idx)
    assert dlg.settings().curve == CURVE_PRESETS["Mitteltöne abdunkeln"]
    dlg.update_preview()
    assert dlg.last_preview.burn_share > before
    dlg.curve.add_point(200, 150)                    # edit → "Benutzerdefiniert"
    assert dlg.curve_preset.currentText() == "Benutzerdefiniert"
    dlg.reset_adjustments()
    assert dlg.settings().curve == () and dlg.curve_preset.currentText() == "Linear"
    assert dlg.settings() == ImageSettings(mode="floyd", line_interval_mm=0.2).normalized()


def test_dialog_without_image_data_still_edits_the_curve(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    dlg = ImageSettingsDialog(ImageSettings(), 10.0, 100)
    dlg.curve.add_point(128, 200)
    assert dlg.settings().curve == ((0, 0), (128, 200), (255, 255))


def test_edit_image_settings_stores_the_curve_with_undo(qapp, tmp_path, monkeypatch):
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
        img = QImage(40, 20, QImage.Format_RGB32)
        for x in range(40):
            for y in range(20):
                v = 60 + 3 * x
                img.setPixelColor(x, y, QColor(v, v, v))
        p = tmp_path / "foto.png"
        img.save(str(p))
        ids = w.import_tools.import_path(p)

        class FakeDialog(import_qt.ImageSettingsDialog):
            def exec(self):  # noqa: A003
                self.curve.set_curve(S_CURVE, emit=True)
                return QDialog.Accepted

        monkeypatch.setattr(import_qt, "ImageSettingsDialog", FakeDialog)
        assert w.import_tools.edit_image_settings(ids[0])
        assert w.canvas.document.shape(ids[0]).image.settings.curve == S_CURVE
        w.canvas.undo_stack.undo()
        assert w.canvas.document.shape(ids[0]).image.settings.curve == ()
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
