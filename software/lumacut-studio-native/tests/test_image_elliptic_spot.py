"""Review round 102: elliptic diode spot in the laser spot simulation – most
diode lasers burn an oblong spot (e.g. 0.08 × 0.06 mm, the emitter is a
stripe), so the track across the scan direction is as wide as the spot in
that direction: at 0° (rows along X) the Y size, at 90° the X size. Round 101
only knew one round spot size, so the stripes / overlap verdict and „Als
Linienabstand“ were wrong for an oblong spot and did not change with the scan
angle."""
from __future__ import annotations

import math

import numpy as np
import pytest

from test_image_scan_angle import _shape
from test_image_spot_preview import _dialog, _square_png


def _sim(pixels, interval=0.1, spot=0.08, spot_y=None, angle=0.0, dw=0.0, **kw):
    from lumacut_import.spot_preview import simulate_spot
    return simulate_spot(pixels, interval, spot, dw, spot_y_mm=spot_y, angle=angle, **kw)


def _line(rows=9, cols=40):
    px = np.full((rows, cols), 255, np.uint8)
    px[rows // 2, :] = 0
    return px


def _dark_width(out, info, interval):
    col = out[:, out.shape[1] // 2]
    return int((col < 128).sum()) * interval / info.sub


def _moments(img):
    d = 255.0 - img.astype(np.float64)
    ys, xs = np.mgrid[:img.shape[0], :img.shape[1]]
    s = d.sum()
    mx, my = (d * xs).sum() / s, (d * ys).sum() / s
    return ((d * (xs - mx) ** 2).sum() / s, (d * (ys - my) ** 2).sum() / s,
            (d * (xs - mx) * (ys - my)).sum() / s)


# ------------------------------------------------------------- geometry
def test_track_width_across_the_scan_direction():
    from lumacut_import.spot_preview import track_width
    assert track_width(0.08) == pytest.approx(0.08)
    assert track_width(0.08, 0.08, 37) == pytest.approx(0.08)      # round: any angle
    assert track_width(0.08, 0.06, 0) == pytest.approx(0.06)       # rows along X: Y size
    assert track_width(0.08, 0.06, 90) == pytest.approx(0.08)      # rows along Y: X size
    assert track_width(0.08, 0.06, -90) == pytest.approx(0.08)
    assert track_width(0.08, 0.06, 45) == pytest.approx(math.sqrt((0.08 ** 2 + 0.06 ** 2) / 2))
    assert track_width(0.08, 0.06, 30) == pytest.approx(track_width(0.08, 0.06, -30))
    assert track_width(0.0, 5.0, 0) == pytest.approx(1.0)           # clamped like the spot


def test_raster_covariance_turns_with_the_scan_angle():
    from lumacut_import.spot_preview import SIGMA_PER_SPOT, raster_sigmas
    sx, sy = 0.08 * SIGMA_PER_SPOT, 0.04 * SIGMA_PER_SPOT
    cxx, cyy, cxy = raster_sigmas(0.08, 0.04, 0)
    assert (cxx, cyy, cxy) == pytest.approx((sx * sx, sy * sy, 0.0))
    cxx, cyy, cxy = raster_sigmas(0.08, 0.04, 90)
    assert (cxx, cyy) == pytest.approx((sy * sy, sx * sx)) and abs(cxy) < 1e-12
    cxx, cyy, cxy = raster_sigmas(0.08, 0.04, 45)
    assert cxx == pytest.approx(cyy) and cxy > 0
    assert raster_sigmas(0.08, 0.04, -45)[2] == pytest.approx(-cxy)
    assert raster_sigmas(0.08, None, 45) == pytest.approx(raster_sigmas(0.08, 0.08, 0))


def test_label_and_info():
    from lumacut_import.spot_preview import spot_label
    assert spot_label(0.08) == "0.08 mm" and spot_label(0.08, 0.08) == "0.08 mm"
    assert spot_label(0.08, 0.06) == "0.08 × 0.06 mm"
    _out, info = _sim(_line(), 0.1, 0.08, 0.05, angle=90)
    assert not info.round and info.spot_y_mm == pytest.approx(0.05) and info.angle == 90
    assert info.label == "0.08 × 0.05 mm"
    assert info.track_mm == pytest.approx(0.08) and info.ratio == pytest.approx(0.8)
    assert info.verdict == "gaps"
    _out, info = _sim(_line(), 0.1, 0.08, 0.08)                     # equal: round
    assert info.round and info.spot_y_mm is None and info.label == "0.08 mm"


# ------------------------------------------------------------- engine
def test_round_spot_is_byte_identical_to_round_101():
    rng = np.random.default_rng(3)
    px = rng.integers(0, 256, (30, 40)).astype(np.uint8)
    a, ia = _sim(px, 0.1, 0.08)
    b, ib = _sim(px, 0.1, 0.08, 0.08, angle=33)                    # same size: round
    c, _ = _sim(px, 0.1, 0.08, None, angle=33)
    assert (a == b).all() and (a == c).all() and ia.sub == ib.sub


def test_line_width_follows_the_spot_size_across_the_rows():
    px = _line()
    out0, i0 = _sim(px, 0.1, 0.16, 0.06, angle=0)                  # across = Y = 0.06
    out90, i90 = _sim(px, 0.1, 0.16, 0.06, angle=90)               # across = X = 0.16
    w0, w90 = _dark_width(out0, i0, 0.1), _dark_width(out90, i90, 0.1)
    assert abs(w0 - 0.06) <= 0.1 / i0.sub + 1e-9
    assert abs(w90 - 0.16) <= 0.1 / i90.sub + 1e-9
    centre = out0[:, out0.shape[1] // 2]
    assert centre.min() == 0                                       # still black on the track


def test_single_dot_is_oblong_along_the_longer_axis():
    px = np.full((21, 21), 255, np.uint8)
    px[10, 10] = 0
    wide, _ = _sim(px, 0.05, 0.3, 0.1, angle=0)                    # long in X
    tall, _ = _sim(px, 0.05, 0.1, 0.3, angle=0)                    # long in Y
    vx, vy, cxy = _moments(wide)
    assert vx > 3 * vy and abs(cxy) < 0.05 * vx
    vx, vy, _ = _moments(tall)
    assert vy > 3 * vx


@pytest.mark.parametrize("angle", [30, 45, 60, -30])
def test_oblique_scan_keeps_the_spot_in_machine_axes(qapp, angle):
    """Simulated in the raster of the pass and turned back like the preview:
    an X-long spot stays X-long and axis aligned on the canvas."""
    from lumacut_import.image_preview import rotate_pixels
    px = np.full((21, 21), 255, np.uint8)
    px[10, 10] = 0
    out, _ = _sim(px, 0.05, 0.3, 0.1, angle=angle)
    vx, vy, cxy = _moments(rotate_pixels(out, angle))
    assert vx > 3 * vy and abs(cxy) < 0.1 * vx
    wrong, _ = _sim(px, 0.05, 0.3, 0.1, angle=-angle)              # opposite turn: not aligned
    wx, wy, wxy = _moments(rotate_pixels(wrong, angle))
    assert not (wx > 3 * wy and abs(wxy) < 0.1 * wx)


def test_gaps_depend_on_the_scan_direction():
    """Interval 0.08 mm, spot 0.08 × 0.05 mm: at 0° the 0.05 mm tracks leave
    white stripes, at 90° the 0.08 mm tracks close the area."""
    from lumacut_import.spot_preview import spot_verdict
    px = np.zeros((20, 20), np.uint8)
    out0, i0 = _sim(px, 0.08, 0.08, 0.05, angle=0)
    out90, i90 = _sim(px, 0.08, 0.08, 0.05, angle=90)
    assert i0.verdict == "gaps" and i90.verdict == "ok"
    assert spot_verdict(0.08, i0.track_mm) == "gaps"
    inner0 = out0[out0.shape[0] // 4:-out0.shape[0] // 4, out0.shape[1] // 4:-out0.shape[1] // 4]
    inner90 = out90[out90.shape[0] // 4:-out90.shape[0] // 4,
                    out90.shape[1] // 4:-out90.shape[1] // 4]
    assert (inner0.min(axis=1) > 150).any()                        # light stripes between rows
    assert inner90.max() < 128                                     # closed


def test_overlap_against_the_track_not_the_bigger_size():
    px = np.zeros((20, 20), np.uint8)
    _o, info = _sim(px, 0.05, 0.2, 0.06, angle=0)                  # track 0.06 – fine
    assert info.verdict == "ok"
    _o, info = _sim(px, 0.05, 0.2, 0.06, angle=90)                 # track 0.2 – overlap
    assert info.verdict == "overlap"


def test_very_thin_oblique_spot_stays_finite():
    px = np.full((15, 15), 255, np.uint8)
    px[7, :] = 0
    out, info = _sim(px, 1.0, 0.01, 1.0, angle=30)                 # 0.01 mm against 1 mm rows
    assert out.dtype == np.uint8 and out.shape == (15 * info.sub, 15 * info.sub)
    assert out.min() < 255 and info.track_mm == pytest.approx(
        math.sqrt((0.01 * 0.5) ** 2 + (1.0 * math.cos(math.radians(30))) ** 2))


def test_magnifier_margin_uses_the_bigger_size():
    """A track just outside the crop bleeds in along the long axis."""
    px = np.full((200, 200), 255, np.uint8)
    out, info = _sim(px, 0.1, 0.05, 0.5, angle=0, max_pixels=40 * 40 * 9)
    assert info.cropped
    rows = info.dots[1]
    y0 = (200 - rows) // 2
    px[y0 - 3, :] = 0                                              # three rows above the crop
    out, info = _sim(px, 0.1, 0.05, 0.5, angle=0, max_pixels=40 * 40 * 9)
    assert out[0].min() < 230                                      # round margin: 2 rows only


def test_oblique_big_preview_is_bounded_and_fast():
    import time
    rng = np.random.default_rng(1)
    px = rng.integers(0, 256, (900, 900)).astype(np.uint8)
    t = time.perf_counter()
    out, info = _sim(px, 0.05, 0.08, 0.06, angle=30)
    assert out.size <= 360_000 and info.cropped
    assert time.perf_counter() - t < 5.0


# ------------------------------------------------------------- texts and prefs
def test_verdict_text_names_the_track_and_the_other_direction():
    from lumacut_import.spot_preview import verdict_text
    round_text = verdict_text(0.1, 0.08)
    assert verdict_text(0.1, 0.08, 0.08, 45) == round_text                  # round: as before
    assert verdict_text(0.1, 0.08, None, 45) == round_text
    t = verdict_text(0.08, 0.08, 0.05, 0)
    assert "0.08 × 0.05 mm" in t and "Spur quer zur Scan-Richtung 0.050 mm" in t
    assert "helle Streifen" in t and f"{25.4 / 0.05:.0f} DPI" in t
    assert "Bei Scan-Winkel 90° wäre die Spur 0.080 mm breiter" in t
    t = verdict_text(0.08, 0.08, 0.05, 90)
    assert "Linienabstand passt" in t and "Bei Scan-Winkel 0° wäre die Spur 0.050 mm schmaler" in t
    t = verdict_text(0.03, 0.2, 0.06, 90)
    assert "überlappen" in t
    t = verdict_text(0.08, 0.08, 0.075, 0)                         # nearly round: no other hint
    assert "Bei Scan-Winkel" not in t


def test_prefs_keep_the_y_size(tmp_path):
    from PySide6.QtCore import QSettings
    from lumacut_import.spot_preview import (SETTINGS_SPOT_Y, load_prefs, load_spot_y,
                                             save_prefs)
    assert load_spot_y(None, 0.1) == pytest.approx(0.1)
    s = QSettings(str(tmp_path / "p.ini"), QSettings.IniFormat)
    save_prefs(s, True, 0.12)                                      # round-101 call: no Y key
    assert not s.contains(SETTINGS_SPOT_Y)
    assert load_spot_y(s, 0.12) == pytest.approx(0.12)             # missing: round
    save_prefs(s, True, 0.12, 0.07)
    again = QSettings(str(tmp_path / "p.ini"), QSettings.IniFormat)
    assert load_prefs(again) == (True, pytest.approx(0.12))
    assert load_spot_y(again, 0.12) == pytest.approx(0.07)
    again.setValue(SETTINGS_SPOT_Y, "nonsense")
    assert load_spot_y(again, 0.12) == pytest.approx(0.08)         # default spot


# ------------------------------------------------------------- preview
def test_split_spot():
    from lumacut_import.image_preview import split_spot
    assert split_spot(0.08) == (0.08, None)
    assert split_spot((0.08, 0.06)) == (0.08, 0.06)
    assert split_spot([0.08, None]) == (0.08, None)


def test_shape_preview_uses_the_track_of_each_scan_angle(qapp):
    from lumacut_import.image_preview import preview_shape
    png = _square_png(qapp)
    sh0 = _shape(qapp, geom=(80.0, 80.0, 6.0, 6.0, 0.0), png=png, mode="threshold",
                 line_interval_mm=0.2)
    sh90 = _shape(qapp, geom=(80.0, 80.0, 6.0, 6.0, 0.0), png=png, mode="threshold",
                  line_interval_mm=0.2, scan_angle=90)
    spot = (0.2, 0.08)                                             # long in X
    p0 = preview_shape(sh0, sh0.image.settings, spot_mm=spot)
    p90 = preview_shape(sh90, sh90.image.settings, spot_mm=spot)
    assert p0.spot.angle == 0 and p90.spot.angle == 90
    assert p0.spot.verdict == "gaps" and p90.spot.verdict == "ok"
    h, w = p0.pixels.shape
    sq0 = p0.pixels[h // 3:2 * h // 3, w // 3:2 * w // 3]
    assert (sq0.min(axis=1) > 200).any()                           # white rows at 0°
    h, w = p90.pixels.shape
    sq90 = p90.pixels[h // 3:2 * h // 3, w // 3:2 * w // 3]
    assert not (sq90.min(axis=0) > 200).any() and not (sq90.min(axis=1) > 200).any()


def test_rotated_scan_preview_with_elliptic_spot(qapp):
    from lumacut_import.image_preview import preview_shape
    png = _square_png(qapp)
    sh = _shape(qapp, geom=(80.0, 80.0, 6.0, 6.0, 0.0), png=png, mode="threshold",
                line_interval_mm=0.1, scan_angle=30)
    pv = preview_shape(sh, sh.image.settings, spot_mm=(0.08, 0.06))
    assert pv.spot.angle == pytest.approx(30)
    assert pv.spot.track_mm == pytest.approx(math.sqrt((0.08 * 0.5) ** 2
                                                       + (0.06 * math.cos(math.radians(30))) ** 2))
    assert pv.pixels.min() == 0 and pv.pixels.max() == 255


def test_array_preview_lays_the_spot_like_the_first_pass(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import gray_from_png, preview_array
    png, _w, _h = _square_png(qapp)
    gray = gray_from_png(png)
    a = preview_array(gray, 6.0, 6.0, ImageSettings(mode="floyd", line_interval_mm=0.1),
                      spot_mm=(0.12, 0.06))
    b = preview_array(gray, 6.0, 6.0, ImageSettings(mode="floyd", line_interval_mm=0.1,
                                                    scan_angle=90), spot_mm=(0.12, 0.06))
    assert a.spot.track_mm == pytest.approx(0.06) and b.spot.track_mm == pytest.approx(0.12)
    assert a.pixels.mean() > b.pixels.mean()                       # wider tracks burn darker


def test_all_passes_each_with_its_own_track(qapp):
    from lumacut_import.image_preview import preview_shape, preview_shape_passes
    png = _square_png(qapp)
    sh = _shape(qapp, geom=(80.0, 80.0, 6.0, 6.0, 0.0), png=png, mode="threshold",
                line_interval_mm=0.2, passes=2, angle_increment=90)
    st = sh.image.settings
    spot = (0.2, 0.08)
    p1 = preview_shape(sh, st, pass_index=1, spot_mm=spot)
    assert p1.spot.angle == pytest.approx(90) and p1.spot.verdict == "ok"
    both = preview_shape_passes(sh, st, spot_mm=spot)
    summed = preview_shape_passes(sh, st, burn_sum=True, spot_mm=spot)
    assert both.spot is not None and summed.spot is not None
    single = preview_shape(sh, st, spot_mm=spot)
    assert both.pixels.mean() <= single.pixels.mean()


def test_job_is_untouched_by_an_elliptic_spot(qapp):
    from lumacut_import.image_preview import preview_shape
    from lumacut_job.images import image_job
    sh = _shape(qapp, mode="jarvis", line_interval_mm=0.2, scan_angle=30)
    before = image_job(sh)
    st = sh.image.settings
    preview_shape(sh, st, spot_mm=(0.08, 0.06))
    assert image_job(sh) == before and sh.image.settings == st


# ------------------------------------------------------------- dialog
def test_dialog_y_size_follows_x_while_round(qapp):
    dlg = _dialog(qapp)
    assert dlg.spot_size_y.value() == pytest.approx(0.08)
    assert dlg.spot_size.prefix() == "X " and dlg.spot_size_y.prefix() == "Y "
    assert not dlg.spot_size_y.isEnabled()                         # off: like the X size
    dlg.spot_sim.setChecked(True)
    assert dlg.spot_size_y.isEnabled()
    dlg.spot_size.setValue(0.1)
    assert dlg.spot_size_y.value() == pytest.approx(0.1)           # round: Y follows
    assert dlg.spot_mm() == pytest.approx(0.1)
    dlg.spot_size_y.setValue(0.06)
    assert dlg.spot_mm() == pytest.approx((0.1, 0.06))
    dlg.spot_size.setValue(0.12)
    assert dlg.spot_size_y.value() == pytest.approx(0.06)          # oblong: Y stays
    dlg.spot_size_y.setValue(0.12)
    assert dlg.spot_mm() == pytest.approx(0.12)                    # equal again: round
    dlg.spot_sim.setChecked(False)
    assert dlg.spot_mm() is None


def test_dialog_names_the_oblong_spot_and_its_track(qapp):
    dlg = _dialog(qapp, line_interval_mm=0.08)
    dlg.spot_sim.setChecked(True)
    dlg.spot_size.setValue(0.08)
    dlg.spot_size_y.setValue(0.05)
    dlg.update_preview()
    text = dlg.preview_label.text()
    assert "Laserpunkt 0.08 × 0.05 mm simuliert" in text
    assert "Spur quer zur Scan-Richtung 0.050 mm" in text and "helle Streifen" in text
    assert dlg.last_preview.spot.spot_y_mm == pytest.approx(0.05)
    assert "Y " in dlg.spot_size_y.text() and dlg.spot_size_y.toolTip()
    assert "länglich" in dlg.spot_size_y.toolTip()


def test_spot_as_line_interval_uses_the_track_width(qapp):
    dlg = _dialog(qapp, line_interval_mm=0.1)
    dlg.spot_sim.setChecked(True)
    dlg.spot_size.setValue(0.12)
    dlg.spot_size_y.setValue(0.06)
    dlg.spot_to_interval.click()
    assert dlg.interval.value() == pytest.approx(0.06)             # 0°: across = Y
    dlg.update_preview()
    assert "Linienabstand passt" in dlg.preview_label.text()
    dlg90 = _dialog(qapp, line_interval_mm=0.1, scan_angle=90)
    dlg90.spot_sim.setChecked(True)
    dlg90.spot_size.setValue(0.12)
    dlg90.spot_size_y.setValue(0.06)
    assert dlg90.spot_track_mm() == pytest.approx(0.12)
    dlg90.spot_to_interval.click()
    assert dlg90.interval.value() == pytest.approx(0.12)           # 90°: across = X
    dlg45 = _dialog(qapp, line_interval_mm=0.1, scan_angle=45)
    dlg45.spot_sim.setChecked(True)
    dlg45.spot_size.setValue(0.12)
    dlg45.spot_size_y.setValue(0.06)
    dlg45.spot_to_interval.click()
    assert dlg45.interval.value() == pytest.approx(round(math.sqrt((0.12 ** 2 + 0.06 ** 2) / 2), 3))


def test_spot_as_line_interval_follows_the_shown_pass(qapp):
    dlg = _dialog(qapp, line_interval_mm=0.1, passes=2, angle_increment=90)
    dlg.spot_sim.setChecked(True)
    dlg.spot_size.setValue(0.12)
    dlg.spot_size_y.setValue(0.06)
    combo = dlg.preview_pass
    idx = [combo.itemData(i) for i in range(combo.count())]
    combo.setCurrentIndex(idx.index(1))                            # second pass: 90°
    assert dlg.spot_track_mm() == pytest.approx(0.12)
    combo.setCurrentIndex(idx.index(dlg.ALL_PASSES))               # all passes: the first
    assert dlg.spot_track_mm() == pytest.approx(0.06)


def test_dialog_remembers_the_y_size(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from lumacut_import.spot_preview import SETTINGS_SPOT_Y
    path = str(tmp_path / "s.ini")
    dlg = _dialog(qapp, prefs=QSettings(path, QSettings.IniFormat))
    dlg.spot_sim.setChecked(True)
    dlg.spot_size.setValue(0.1)
    dlg.spot_size_y.setValue(0.07)
    again = _dialog(qapp, prefs=QSettings(path, QSettings.IniFormat))
    assert again.spot_size.value() == pytest.approx(0.1)
    assert again.spot_size_y.value() == pytest.approx(0.07)
    assert again.last_preview.spot.label == "0.1 × 0.07 mm"
    old = QSettings(str(tmp_path / "old.ini"), QSettings.IniFormat)   # round-101 prefs
    old.setValue("image_preview/spot_mm", 0.11)
    old.sync()
    assert not old.contains(SETTINGS_SPOT_Y)
    legacy = _dialog(qapp, prefs=QSettings(str(tmp_path / "old.ini"), QSettings.IniFormat))
    assert legacy.spot_size_y.value() == pytest.approx(0.11)       # round as before


def test_dialog_settings_do_not_depend_on_the_spot_shape(qapp):
    dlg = _dialog(qapp, mode="jarvis", dot_width_mm=0.03, scan_angle=30)
    off = dlg.settings()
    dlg.spot_sim.setChecked(True)
    dlg.spot_size_y.setValue(0.2)
    assert dlg.settings() == off


def test_touch_mode_y_size_is_44_px(qapp):
    from PySide6.QtWidgets import QWidget

    class Canvas:
        touch_mode = True

    parent = QWidget()
    parent.canvas = Canvas()
    dlg = _dialog(qapp, parent=parent)
    assert dlg.spot_size_y.minimumHeight() >= 44
    assert dlg.spot_size_y.parent() is dlg.spot_row
    assert _dialog(qapp).spot_size_y.minimumHeight() < 44
    parent.deleteLater()
