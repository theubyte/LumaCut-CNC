"""Review round 101: the image settings preview simulates the laser spot
(„Laserpunkt simulieren“) – before, one preview pixel was one laser dot, as if
the beam burned a square exactly one line interval wide, so a line interval
far from the real spot size (white stripes between the rows, or overlapping
tracks that make a photo dark and muddy) could not be seen before lasering."""
from __future__ import annotations


import numpy as np
import pytest

from test_image_scan_angle import _shape


def _solid(rows=20, cols=20, value=0):
    return np.full((rows, cols), value, dtype=np.uint8)


def _sim(pixels, interval=0.1, spot=0.08, dw=0.0, **kw):
    from lumacut_import.spot_preview import simulate_spot
    return simulate_spot(pixels, interval, spot, dw, **kw)


def _square_png(qapp, w=60, h=60):
    """A black square in the middle of a white image."""
    from PySide6.QtGui import QColor, QImage
    from lumacut_import.image import grayscale_png
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    for x in range(w // 4, 3 * w // 4):
        for y in range(h // 4, 3 * h // 4):
            img.setPixelColor(x, y, QColor(0, 0, 0))
    return grayscale_png(img)


# ------------------------------------------------------------- engine
def test_single_line_is_as_wide_as_the_spot_with_a_black_centre():
    from lumacut_import.spot_preview import EDGE_DARKNESS
    px = np.full((7, 40), 255, np.uint8)
    px[3, :] = 0                                       # one long full-power row
    out, info = _sim(px, 0.1, 0.08)
    sub = info.sub
    col = out[:, out.shape[1] // 2].astype(float)
    centre = 3 * sub + sub // 2
    assert col[centre] == 0                            # black on the track
    # dark (≥ 50 %) exactly over the spot width: 0.08 mm = 0.8 dots = 4 of 5 sub-pixels
    dark = int((col < 255 * (1 - EDGE_DARKNESS) + 1).sum())
    assert abs(dark * 0.1 / sub - 0.08) <= 0.1 / sub + 1e-9
    assert col[0] == 255 and col[-1] == 255            # far away: untouched


def test_wider_spot_gives_a_wider_line_and_lower_power_a_lighter_one():
    px = np.full((9, 40), 255, np.uint8)
    px[4, :] = 0
    widths = []
    for spot in (0.05, 0.1, 0.2):
        out, info = _sim(px, 0.1, spot)
        col = out[:, out.shape[1] // 2]
        widths.append((col < 128).sum() * 0.1 / info.sub)
    assert widths[0] < widths[1] < widths[2]
    assert widths[2] == pytest.approx(0.2, abs=0.04)
    weak = px.copy()
    weak[4, :] = 200                                    # about 22 % power
    full, info = _sim(px, 0.1, 0.1)
    low, _ = _sim(weak, 0.1, 0.1)
    c = 4 * info.sub + info.sub // 2
    assert low[c].mean() > full[c].mean() + 50          # lighter track


def test_line_interval_against_spot_gaps_dense_and_overlap():
    px = _solid(12, 12)                                 # all dots full power
    gaps, info = _sim(px, 0.1, 0.05)                    # spot half the interval
    sub = info.sub
    mid = gaps.shape[1] // 2
    between = gaps[6 * sub, mid]                        # sub-row between two tracks
    assert between > 200                                # white stripe
    dense, info = _sim(px, 0.1, 0.1)
    inner = dense[2 * info.sub:-2 * info.sub, 2 * info.sub:-2 * info.sub]
    assert inner.max() < 80                             # tracks touch: nearly closed
    over, info = _sim(px, 0.1, 0.2)
    inner = over[2 * info.sub:-2 * info.sub, 2 * info.sub:-2 * info.sub]
    assert inner.max() == 0                             # fully black


def test_overlapping_tracks_darken_a_dithered_area():
    rng = np.random.default_rng(1)
    px = np.where(rng.random((60, 60)) < 0.5, 0, 255).astype(np.uint8)
    means = [_sim(px, 0.1, spot)[0].mean() for spot in (0.06, 0.1, 0.2)]
    assert means[0] > means[1] > means[2]               # bigger spot = darker photo
    assert means[2] < 40


def test_nothing_burned_stays_white():
    out, info = _sim(_solid(10, 10, 255), 0.1, 0.08)
    assert (out == 255).all() and out.shape == (10 * info.sub, 10 * info.sub)
    assert out.dtype == np.uint8


def test_dot_width_correction_shortens_runs_like_the_gcode():
    from lumacut_job.raster import _dot_width
    px = np.full((3, 15), 255, np.uint8)
    px[1, 5:10] = 0                                     # one run of 5 dots
    lengths = []
    for dw in (0.0, 0.05, 0.1):
        out, info = _sim(px, 0.1, 0.02, dw)            # tiny spot: track ≈ the run
        row = out[1 * info.sub + info.sub // 2]
        lengths.append((row < 128).sum() * 0.1 / info.sub)
    assert lengths[0] == pytest.approx(0.5, abs=0.03)
    runs = _dot_width([(5, 10, 255)], 0.1 / 0.1)       # 0.1 mm at 0.1 mm interval
    assert runs[0][1] - runs[0][0] == pytest.approx(4.0)
    assert lengths[2] == pytest.approx(0.4, abs=0.03)  # 0.05 mm off each end
    assert lengths[0] > lengths[1] > lengths[2]


def test_dot_width_keeps_single_dots_and_greyscale_edges():
    px = np.full((3, 9), 255, np.uint8)
    px[1, 4] = 0                                        # a single dot
    out, info = _sim(px, 0.1, 0.05, 0.1)               # correction = interval
    assert out.min() < 128                              # still burns (MIN_DOT_PX)
    grey = np.full((3, 12), 255, np.uint8)
    grey[1, 3:6] = 0
    grey[1, 6:9] = 100                                  # touching run of other power
    out, info = _sim(grey, 0.1, 0.1, 0.05)
    row = out[1 * info.sub + info.sub // 2]
    seam = 6 * info.sub
    assert row[seam - 1] < 200 and row[seam] < 200     # no gap at the common edge
    plain, _ = _sim(grey, 0.1, 0.1, 0.0)
    left = 3 * info.sub
    assert out[1 * info.sub + info.sub // 2, left] > plain[1 * info.sub + info.sub // 2, left]


def test_subsamples_are_odd_and_bounded():
    from lumacut_import.spot_preview import MAX_SUB, subsamples
    assert subsamples(0.1, 0.08) == 5
    assert subsamples(0.1, 0.1) == 5
    assert subsamples(0.05, 0.2) == 1
    assert subsamples(2.0, 0.01) == MAX_SUB
    for interval in (0.03, 0.05, 0.1, 0.2, 0.5):
        for spot in (0.01, 0.05, 0.08, 0.15, 1.0):
            n = subsamples(interval, spot)
            assert n % 2 == 1 and 1 <= n <= MAX_SUB


def test_big_previews_are_a_centred_magnifier():
    rng = np.random.default_rng(3)
    px = np.where(rng.random((300, 400)) < 0.4, 0, 255).astype(np.uint8)
    out, info = _sim(px, 0.1, 0.08, max_pixels=90_000)
    assert out.size <= 90_000 and info.cropped
    assert out.shape == (info.dots[1] * info.sub, info.dots[0] * info.sub)
    assert info.size_mm == pytest.approx((info.dots[0] * 0.1, info.dots[1] * 0.1))
    small, sinfo = _sim(px[:20, :20], 0.1, 0.08)
    assert not sinfo.cropped and small.shape == (20 * sinfo.sub, 20 * sinfo.sub)


def test_magnifier_includes_tracks_just_outside_the_crop():
    rng = np.random.default_rng(5)
    px = np.where(rng.random((60, 60)) < 0.5, 0, 255).astype(np.uint8)
    whole, info = _sim(px, 0.1, 0.3)
    part, pinfo = _sim(px, 0.1, 0.3, max_pixels=30 * 30 * info.sub ** 2)
    assert pinfo.dots == (30, 30) and pinfo.sub == info.sub
    sub = info.sub
    y0 = x0 = 15
    ref = whole[y0 * sub:(y0 + 30) * sub, x0 * sub:(x0 + 30) * sub]
    assert np.abs(ref.astype(int) - part.astype(int)).max() <= 1   # same edge pixels


def test_invalid_input_and_spot_clamping():
    from lumacut_import.spot_preview import DEFAULT_SPOT_MM, SPOT_RANGE_MM, clamp_spot
    with pytest.raises(ValueError):
        _sim(_solid(), 0.0, 0.08)
    with pytest.raises(ValueError):
        _sim(np.zeros((0, 0), np.uint8), 0.1, 0.08)
    assert clamp_spot(5) == SPOT_RANGE_MM[1]
    assert clamp_spot(-1) == SPOT_RANGE_MM[0]
    assert clamp_spot("x") == DEFAULT_SPOT_MM
    assert clamp_spot(float("nan")) == DEFAULT_SPOT_MM
    assert clamp_spot(None) == DEFAULT_SPOT_MM
    _out, info = _sim(_solid(), 0.1, 9.0)
    assert info.spot_mm == SPOT_RANGE_MM[1]


def test_verdict_and_hint_text():
    from lumacut_import.spot_preview import spot_verdict, verdict_text
    assert spot_verdict(0.1, 0.05) == "gaps"
    assert spot_verdict(0.1, 0.1) == "ok"
    assert spot_verdict(0.08, 0.1) == "ok"
    assert spot_verdict(0.05, 0.1) == "overlap"
    assert "helle Streifen" in verdict_text(0.1, 0.05) and "508 DPI" in verdict_text(0.1, 0.05)
    assert "überlappen" in verdict_text(0.05, 0.1) and "2.0 ×" in verdict_text(0.05, 0.1)
    assert "passt" in verdict_text(0.1, 0.1)


def test_prefs_round_trip(tmp_path):
    from PySide6.QtCore import QSettings
    from lumacut_import.spot_preview import (DEFAULT_SPOT_MM, SETTINGS_SIMULATE, load_prefs,
                                             save_prefs)
    assert load_prefs(None) == (False, DEFAULT_SPOT_MM)
    save_prefs(None, True, 0.1)                         # no settings: nothing happens
    s = QSettings(str(tmp_path / "p.ini"), QSettings.IniFormat)
    assert load_prefs(s) == (False, DEFAULT_SPOT_MM)
    save_prefs(s, True, 0.12)
    again = QSettings(str(tmp_path / "p.ini"), QSettings.IniFormat)
    assert load_prefs(again) == (True, pytest.approx(0.12))
    again.setValue(SETTINGS_SIMULATE, "nonsense")
    assert load_prefs(again)[0] is False


# ------------------------------------------------------------- preview
def test_preview_without_spot_is_unchanged(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import gray_from_png, preview_array
    png, _w, _h = _square_png(qapp)
    gray = gray_from_png(png)
    st = ImageSettings(mode="floyd", line_interval_mm=0.1)
    a = preview_array(gray, 6.0, 6.0, st)
    b = preview_array(gray, 6.0, 6.0, st, spot_mm=None)
    assert (a.pixels == b.pixels).all() and a.spot is None and b.spot is None
    c = preview_array(gray, 6.0, 6.0, st, spot_mm=0.08)
    assert c.spot is not None and c.spot.sub == 5
    assert c.pixels.shape == (a.pixels.shape[0] * 5, a.pixels.shape[1] * 5)
    assert c.burn_share == a.burn_share                 # share of lasered dots stays


def test_shape_preview_simulates_along_the_scan_direction(qapp):
    from lumacut_import.image_preview import preview_shape
    png = _square_png(qapp)
    sh0 = _shape(qapp, geom=(80.0, 80.0, 6.0, 6.0, 0.0), png=png, mode="threshold",
                 line_interval_mm=0.2)
    sh90 = _shape(qapp, geom=(80.0, 80.0, 6.0, 6.0, 0.0), png=png, mode="threshold",
                  line_interval_mm=0.2, scan_angle=90)
    p0 = preview_shape(sh0, sh0.image.settings, spot_mm=0.08)      # gaps between rows
    p90 = preview_shape(sh90, sh90.image.settings, spot_mm=0.08)
    assert p0.spot is not None and p90.spot is not None
    h, w = p0.pixels.shape
    sq0 = p0.pixels[h // 3:2 * h // 3, w // 3:2 * w // 3]
    # 0°: white stripes are whole rows inside the square, columns stay dark somewhere
    assert (sq0.min(axis=1) > 200).any() and not (sq0.min(axis=0) > 200).any()
    h, w = p90.pixels.shape
    sq90 = p90.pixels[h // 3:2 * h // 3, w // 3:2 * w // 3]
    assert (sq90.min(axis=0) > 200).any() and not (sq90.min(axis=1) > 200).any()


def test_dot_width_of_the_settings_is_used(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import gray_from_png, preview_array
    png, _w, _h = _square_png(qapp)
    gray = gray_from_png(png)
    a = preview_array(gray, 6.0, 6.0, ImageSettings(mode="threshold", line_interval_mm=0.1),
                      spot_mm=0.05)
    b = preview_array(gray, 6.0, 6.0, ImageSettings(mode="threshold", line_interval_mm=0.1,
                                                    dot_width_mm=0.1), spot_mm=0.05)
    assert b.spot.dot_width_mm == pytest.approx(0.1)
    assert b.pixels.mean() > a.pixels.mean()           # shorter runs burn less


def test_all_passes_and_burn_sum_with_spot(qapp):
    from lumacut_import.image_preview import preview_shape_passes
    png = _square_png(qapp)
    sh = _shape(qapp, geom=(80.0, 80.0, 6.0, 6.0, 0.0), png=png, mode="threshold",
                line_interval_mm=0.2, passes=2, angle_increment=90)
    st = sh.image.settings
    over = preview_shape_passes(sh, st, spot_mm=0.08)
    total = preview_shape_passes(sh, st, burn_sum=True, spot_mm=0.08)
    plain = preview_shape_passes(sh, st)
    assert over.spot is not None and total.spot is not None and plain.spot is None
    assert over.pixels.shape == total.pixels.shape
    assert over.pixels.shape[0] > plain.pixels.shape[0]
    # the cross raster closes the stripes of a single pass: the square is darker
    single = preview_shape_passes(_shape(qapp, geom=(80.0, 80.0, 6.0, 6.0, 0.0), png=png,
                                         mode="threshold", line_interval_mm=0.2),
                                  st.__class__(mode="threshold", line_interval_mm=0.2),
                                  spot_mm=0.08)
    h, w = over.pixels.shape
    assert over.pixels[h // 3:2 * h // 3, w // 3:2 * w // 3].mean() < \
        single.pixels[h // 3:2 * h // 3, w // 3:2 * w // 3].mean()


def test_job_and_settings_are_untouched(qapp):
    """The simulation is preview only: no new image setting, same G-code."""
    from dataclasses import fields
    from lumacut_canvas.model import ImageSettings
    from lumacut_job.images import image_job
    names = {f.name for f in fields(ImageSettings)}
    assert not any("spot" in n for n in names)
    sh = _shape(qapp, mode="jarvis", line_interval_mm=0.2)
    before = image_job(sh)
    from lumacut_import.image_preview import preview_shape
    preview_shape(sh, sh.image.settings, spot_mm=0.08)
    assert image_job(sh) == before


# ------------------------------------------------------------- dialog
def _dialog(qapp, prefs=None, parent=None, **settings):
    from lumacut_import.qt import ImageSettingsDialog
    settings.setdefault("mode", "floyd")
    settings.setdefault("line_interval_mm", 0.1)
    sh = _shape(qapp, geom=(80.0, 80.0, 6.0, 6.0, 0.0), png=_square_png(qapp), **settings)
    return ImageSettingsDialog(sh.image.settings, sh.geom.w, sh.image.px_width, parent,
                               shape=sh, prefs=prefs)


def test_dialog_default_off_shows_the_old_preview(qapp):
    dlg = _dialog(qapp)
    assert dlg.spot_row.isVisibleTo(dlg)
    assert not dlg.spot_sim.isChecked() and not dlg.spot_size.isEnabled()
    assert dlg.spot_size.value() == pytest.approx(0.08)
    assert dlg.spot_mm() is None
    assert dlg.last_preview.spot is None
    assert "simuliert" not in dlg.preview_label.text()
    assert "Lupe" not in dlg.preview_label.text()
    for w in (dlg.spot_sim, dlg.spot_size, dlg.spot_to_interval):
        assert w.toolTip()
    assert "nur vorschau" in dlg.spot_sim.toolTip().lower()


def test_dialog_simulates_and_names_gaps_or_overlap(qapp):
    dlg = _dialog(qapp)
    dlg.spot_sim.setChecked(True)
    dlg.update_preview()
    pv = dlg.last_preview
    assert pv.spot is not None and dlg.spot_size.isEnabled()
    text = dlg.preview_label.text()
    assert "Laserpunkt 0.08 mm simuliert" in text and "helle Streifen" in text
    assert f"{pv.spot.dots[0]} × {pv.spot.dots[1]} Laserpunkte" in text
    dlg.spot_size.setValue(0.25)
    dlg.update_preview()
    assert "überlappen" in dlg.preview_label.text()
    assert dlg.last_preview.spot.spot_mm == pytest.approx(0.25)


def test_spot_as_line_interval(qapp):
    dlg = _dialog(qapp)
    dlg.spot_sim.setChecked(True)
    dlg.spot_size.setValue(0.12)
    dlg.spot_to_interval.click()
    assert dlg.interval.value() == pytest.approx(0.12)
    assert dlg.settings().line_interval_mm == pytest.approx(0.12)
    dlg.update_preview()
    assert "passt" in dlg.preview_label.text()
    dlg.spot_size.setValue(0.01)                        # below the interval minimum
    dlg.spot_to_interval.click()
    assert dlg.interval.value() == pytest.approx(dlg.interval.minimum())


def test_dialog_settings_do_not_depend_on_the_simulation(qapp):
    dlg = _dialog(qapp, mode="jarvis", dot_width_mm=0.03)
    off = dlg.settings()
    dlg.spot_sim.setChecked(True)
    dlg.spot_size.setValue(0.2)
    assert dlg.settings() == off


def test_dialog_remembers_the_choice(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    prefs = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    dlg = _dialog(qapp, prefs=prefs)
    dlg.spot_sim.setChecked(True)
    dlg.spot_size.setValue(0.15)
    again = _dialog(qapp, prefs=QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    assert again.spot_sim.isChecked() and again.spot_size.value() == pytest.approx(0.15)
    assert again.last_preview.spot is not None          # opens with the simulation
    no_prefs = _dialog(qapp)
    assert not no_prefs.spot_sim.isChecked()


def test_dialog_without_image_data_hides_the_row(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    dlg = ImageSettingsDialog(ImageSettings(), 10.0, 100)
    assert not dlg.spot_row.isVisibleTo(dlg)
    dlg.spot_sim.setChecked(True)                       # no crash without preview
    assert dlg.last_preview is None


def test_touch_mode_rows_are_44_px(qapp):
    from PySide6.QtWidgets import QWidget

    class Canvas:
        touch_mode = True

    parent = QWidget()
    parent.canvas = Canvas()
    dlg = _dialog(qapp, parent=parent)
    for w in (dlg.spot_sim, dlg.spot_size, dlg.spot_to_interval):
        assert w.minimumHeight() >= 44
    mouse = _dialog(qapp)
    assert mouse.spot_size.minimumHeight() < 44
    parent.deleteLater()


def test_main_window_passes_its_settings_to_the_dialog(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QDialog
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    from lumacut_import import qt as import_qt
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    seen = {}
    try:
        img = QImage(30, 20, QImage.Format_RGB32)
        img.fill(QColor(90, 90, 90))
        p = tmp_path / "foto.png"
        img.save(str(p))
        ids = w.import_tools.import_path(p)

        class FakeDialog(import_qt.ImageSettingsDialog):
            def exec(self):  # noqa: A003
                seen["prefs"] = self._prefs
                seen["row"] = self.spot_row.isVisibleTo(self)
                self.spot_sim.setChecked(True)
                return QDialog.Rejected

        monkeypatch.setattr(import_qt, "ImageSettingsDialog", FakeDialog)
        old = w.canvas.document.shape(ids[0]).image.settings
        steps = w.canvas.undo_stack.count()
        assert not w.import_tools.edit_image_settings(ids[0])
        assert seen["prefs"] is w.import_tools.settings and seen["row"]
        # turning the simulation on never changes the document
        assert w.canvas.document.shape(ids[0]).image.settings == old
        assert w.canvas.undo_stack.count() == steps
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
