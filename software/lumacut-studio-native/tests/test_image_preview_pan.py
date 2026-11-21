"""Review round 103: movable preview window and magnifier – the image preview
of large images was a fixed crop of the image centre (at most 600 × 600 dots,
e.g. 60 × 60 mm at 0.1 mm) and the laser spot magnifier of rounds 101 / 102
always showed the centre too, so eyes, text or fine edges away from the
middle could not be checked before burning. Now the shown window follows a
focus point (mm next to the image centre, canvas orientation): drag the
preview with mouse or finger (like a map), double-click / „Mitte“ = centre.
Like the zoom / pan of LightBurn's Adjust Image preview; preview only."""
from __future__ import annotations

import math

import numpy as np
import pytest

from test_image_scan_angle import _shape
from test_image_spot_preview import _dialog

W = H = 200
BLOCK = (30, 50, 60, 80)          # x0, x1, y0, y1 in image pixels (black)


def _block_png(qapp, w=W, h=H, block=BLOCK):
    """White image with one black block away from the centre."""
    from PySide6.QtGui import QColor, QImage
    from lumacut_import.image import grayscale_png
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    x0, x1, y0, y1 = block
    for x in range(x0, x1):
        for y in range(y0, y1):
            img.setPixelColor(x, y, QColor(0, 0, 0))
    return grayscale_png(img)


def _block_focus(size_mm=40.0, rot=0.0):
    """Canvas offset of the block centre from the image centre (mm)."""
    x0, x1, y0, y1 = BLOCK
    dx = ((x0 + x1) / 2 / W - 0.5) * size_mm
    dy = ((y0 + y1) / 2 / H - 0.5) * size_mm
    t = math.radians(rot)
    return dx * math.cos(t) - dy * math.sin(t), dx * math.sin(t) + dy * math.cos(t)


def _centre(p, r=3):
    h, w = p.shape
    return float(p[h // 2 - r:h // 2 + r, w // 2 - r:w // 2 + r].mean())


def _block_shape(qapp, size=40.0, rot=0.0, **settings):
    settings.setdefault("mode", "threshold")
    settings.setdefault("line_interval_mm", 0.1)
    return _shape(qapp, geom=(80.0, 80.0, size, size, rot), png=_block_png(qapp), **settings)


def _big_dialog(qapp, size=100.0, rot=0.0, **settings):
    from lumacut_import.qt import ImageSettingsDialog
    sh = _block_shape(qapp, size, rot, **settings)
    return ImageSettingsDialog(sh.image.settings, sh.geom.w, sh.image.px_width, None, shape=sh)


# ------------------------------------------------------------- crop window
def test_centred_crop_is_the_old_formula():
    from lumacut_import.spot_preview import offset_crop
    for rows, cols, ch, cw in ((10, 10, 4, 4), (11, 9, 4, 3), (601, 1000, 600, 600)):
        old = ((rows - ch) // 2, (cols - cw) // 2)
        assert offset_crop(rows, cols, ch, cw) == old
        assert offset_crop(rows, cols, ch, cw, (0, 0)) == old
        assert offset_crop(rows, cols, ch, cw, (math.nan, 1.0)) == old     # invalid: centred
        assert offset_crop(rows, cols, ch, cw, "xy") == old


def test_crop_window_follows_the_offset_and_stops_at_the_edges():
    from lumacut_import.spot_preview import crop_center, offset_crop
    assert offset_crop(100, 100, 20, 20, (10, -5)) == (35, 50)
    assert crop_center(100, 100, 35, 50, 20, 20) == (10.0, -5.0)
    assert offset_crop(100, 100, 20, 20, (1000, 1000)) == (80, 80)
    assert offset_crop(100, 100, 20, 20, (-1000, -1000)) == (0, 0)
    assert crop_center(100, 100, 0, 0, 20, 20) == (-40.0, -40.0)
    assert offset_crop(100, 100, 100, 20, (7, 50)) == (0, 47)              # no room in y


def test_magnifier_moves_to_the_offset(qapp):
    from lumacut_import.spot_preview import simulate_spot
    px = np.full((200, 200), 255, np.uint8)
    px[20:40, 150:170] = 0                         # block 60 dots right, 70 above the centre
    out0, info0 = simulate_spot(px, 0.1, 0.1, max_pixels=40 * 40 * 9)
    assert info0.cropped and _centre(out0) == 255
    assert info0.center == pytest.approx((0.0, 0.0))
    out, info = simulate_spot(px, 0.1, 0.1, max_pixels=40 * 40 * 9, offset=(60, -70))
    assert _centre(out) < 30 and info.center == pytest.approx((60.0, -70.0))
    assert out.shape == out0.shape
    out, info = simulate_spot(px, 0.1, 0.1, max_pixels=40 * 40 * 9, offset=(500, -500))
    cw, ch = info.dots                                                        # clamped
    assert info.center == pytest.approx((100 - cw / 2, -(100 - ch / 2)))
    same, _ = simulate_spot(px, 0.1, 0.1, max_pixels=40 * 40 * 9, offset=(0, 0))
    assert np.array_equal(same, out0)


def test_whole_magnifier_ignores_the_offset():
    from lumacut_import.spot_preview import simulate_spot
    px = np.full((20, 20), 255, np.uint8)
    px[5, :] = 0
    a, ia = simulate_spot(px, 0.1, 0.1)
    b, ib = simulate_spot(px, 0.1, 0.1, offset=(5, 5))
    assert np.array_equal(a, b) and not ib.cropped and ib.center == (0.0, 0.0)


def test_preview_window_equals_the_same_part_of_the_whole_image():
    """Threshold / sharpen (neighbourhood filter): the moved window shows the
    same dots as the whole image there (filter margin travels along)."""
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import preview_pixels
    rng = np.random.default_rng(3)
    g = (rng.random((120, 150)) * 255).astype(np.uint8)
    st = ImageSettings(mode="threshold", line_interval_mm=0.1, sharpen=60, sharpen_radius=2)
    full = preview_pixels(g, st, max_pixels=10 ** 6)
    for off in ((20, -15), (-1000, 1000), (3.4, 0.6)):
        pv = preview_pixels(g, st, max_pixels=40 * 40, offset=off)
        h, w = pv.pixels.shape
        cx, cy = pv.center
        x0, y0 = int(round(cx + 75 - w / 2)), int(round(cy + 60 - h / 2))
        assert np.array_equal(pv.pixels, full.pixels[y0:y0 + h, x0:x0 + w])
    assert preview_pixels(g, st, max_pixels=40 * 40, offset=(20, -15)).center == (20.0, -15.0)
    assert np.array_equal(preview_pixels(g, st, max_pixels=40 * 40).pixels,
                          preview_pixels(g, st, max_pixels=40 * 40, offset=None).pixels)


# ------------------------------------------------------------- coordinates
@pytest.mark.parametrize("angle", [0.0, 30.0, 90.0, -45.0])
@pytest.mark.parametrize("flip", [False, True])
def test_focus_dots_round_trip(angle, flip):
    from lumacut_import.image_preview import dots_to_focus, focus_dots
    d = focus_dots((3.0, -1.5), 0.1, angle, flip)
    assert math.hypot(*d) == pytest.approx(math.hypot(30, 15))
    assert dots_to_focus(d, 0.1, angle, flip) == pytest.approx((3.0, -1.5))
    assert focus_dots(None, 0.1, angle, flip) is None
    assert focus_dots((0, 0), 0.1, angle, flip) is None


def test_clamp_focus_keeps_the_point_on_the_image():
    from lumacut_import.image_preview import clamp_focus
    assert clamp_focus(None, 40, 20) is None and clamp_focus((0, 0), 40, 20) is None
    assert clamp_focus((5, 3), 40, 20) == pytest.approx((5, 3))
    assert clamp_focus((100, -100), 40, 20) == pytest.approx((20, -10))
    # turned by 90°: the 40 mm side now runs along canvas y
    assert clamp_focus((100, 100), 40, 20, 90) == pytest.approx((10, 20))
    x, y = clamp_focus((100, 0), 40, 20, 30)
    lx, ly = x * math.cos(math.radians(30)) + y * math.sin(math.radians(30)), \
        -x * math.sin(math.radians(30)) + y * math.cos(math.radians(30))
    assert abs(lx) <= 20 + 1e-9 and abs(ly) <= 10 + 1e-9


# ------------------------------------------------------------- previews
@pytest.mark.parametrize("angle", [0.0, 30.0, 90.0, -45.0])
def test_shape_preview_window_finds_the_block_for_every_scan_angle(qapp, angle):
    from lumacut_import.image_preview import preview_shape
    sh = _block_shape(qapp, scan_angle=angle)
    st = sh.image.settings
    centred = preview_shape(sh, st, max_pixels=40 * 40)
    assert centred.cropped and _centre(centred.pixels) == 255
    pv = preview_shape(sh, st, max_pixels=40 * 40, focus_mm=_block_focus())
    assert _centre(pv.pixels) < 30
    assert pv.focus_mm == pytest.approx(_block_focus(), abs=0.1)
    assert pv.pixels.shape == centred.pixels.shape


@pytest.mark.parametrize("flip", [False, True])
def test_window_follows_the_canvas_with_either_origin(qapp, monkeypatch, flip):
    import lumacut_canvas.workarea as wa
    from lumacut_import.image_preview import preview_shape
    monkeypatch.setattr(wa, "IMAGE_FLIP_X", flip)
    sh = _block_shape(qapp)
    pv = preview_shape(sh, sh.image.settings, max_pixels=40 * 40, focus_mm=_block_focus())
    assert _centre(pv.pixels) < 30
    fx, fy = _block_focus()
    mirror = preview_shape(sh, sh.image.settings, max_pixels=40 * 40, focus_mm=(-fx, fy))
    assert _centre(mirror.pixels) == 255


@pytest.mark.parametrize("angle", [0.0, 45.0])
def test_window_on_a_rotated_image(qapp, angle):
    from lumacut_import.image_preview import preview_shape
    sh = _block_shape(qapp, rot=30.0, scan_angle=angle)
    pv = preview_shape(sh, sh.image.settings, max_pixels=40 * 40,
                       focus_mm=_block_focus(rot=30.0))
    assert _centre(pv.pixels) < 30
    wrong = preview_shape(sh, sh.image.settings, max_pixels=40 * 40,
                          focus_mm=_block_focus(rot=-30.0))
    assert _centre(wrong.pixels) == 255


def test_without_focus_previews_are_byte_identical(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import (gray_from_png, preview_array, preview_shape,
                                              preview_shape_passes)
    for kw in ({}, {"spot_mm": 0.08}, {"spot_mm": (0.1, 0.06)}):
        for angle in (0.0, 30.0):
            sh = _block_shape(qapp, mode="jarvis", scan_angle=angle)
            st = sh.image.settings
            a = preview_shape(sh, st, max_pixels=50 * 50, **kw)
            for focus in (None, (0, 0), (0.0, -0.0)):
                b = preview_shape(sh, st, max_pixels=50 * 50, focus_mm=focus, **kw)
                assert np.array_equal(a.pixels, b.pixels) and a.burn_share == b.burn_share
        sh = _block_shape(qapp, passes=2, angle_increment=90)
        a = preview_shape_passes(sh, sh.image.settings, max_pixels=50 * 50, **kw)
        b = preview_shape_passes(sh, sh.image.settings, max_pixels=50 * 50, focus_mm=(0, 0), **kw)
        assert np.array_equal(a.pixels, b.pixels)
    g = gray_from_png(_block_png(qapp)[0])
    st = ImageSettings(mode="floyd", line_interval_mm=0.1)
    assert np.array_equal(preview_array(g, 40, 40, st, max_pixels=40 * 40).pixels,
                          preview_array(g, 40, 40, st, max_pixels=40 * 40, focus_mm=None).pixels)


def test_array_preview_window(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import gray_from_png, preview_array
    g = gray_from_png(_block_png(qapp)[0])
    st = ImageSettings(mode="threshold", line_interval_mm=0.1)
    pv = preview_array(g, 40, 40, st, max_pixels=40 * 40, focus_mm=_block_focus())
    assert _centre(pv.pixels) < 30 and pv.focus_mm == pytest.approx(_block_focus())
    edge = preview_array(g, 40, 40, st, max_pixels=40 * 40, focus_mm=(-100, -100))
    assert edge.focus_mm == pytest.approx((-18.0, -18.0))      # 4 mm window inside 40 mm
    whole = preview_array(g, 40, 40, st, focus_mm=(5, 5))
    assert not whole.pannable and whole.focus_mm is None


@pytest.mark.parametrize("angle", [0.0, 30.0])
def test_spot_magnifier_moves_to_the_block(qapp, angle):
    from lumacut_import.image_preview import preview_shape
    sh = _block_shape(qapp, scan_angle=angle)
    st = sh.image.settings
    centred = preview_shape(sh, st, max_pixels=60 * 60, spot_mm=(0.1, 0.08))
    assert centred.spot.cropped and _centre(centred.pixels, 5) == 255
    pv = preview_shape(sh, st, max_pixels=60 * 60, spot_mm=(0.1, 0.08), focus_mm=_block_focus())
    assert _centre(pv.pixels, 5) < 80
    assert pv.focus_mm == pytest.approx(_block_focus(), abs=0.1)
    assert pv.spot.center != (0.0, 0.0) or pv.center != (0.0, 0.0)


def test_spot_magnifier_inside_a_moved_preview_window(qapp):
    """Big image: the preview window and the magnifier inside it both move."""
    from lumacut_import.image_preview import preview_shape
    sh = _block_shape(qapp, size=200.0)
    st = sh.image.settings                       # 2000 × 2000 dots: preview cropped
    focus = _block_focus(200.0)
    pv = preview_shape(sh, st, spot_mm=0.1, focus_mm=focus)
    assert pv.cropped and pv.spot.cropped
    assert _centre(pv.pixels, 5) < 80 and pv.focus_mm == pytest.approx(focus, abs=0.1)
    plain = preview_shape(sh, st, focus_mm=focus)
    assert plain.focus_mm == pytest.approx(focus, abs=0.1)


@pytest.mark.parametrize("burn_sum", [False, True])
def test_all_passes_share_one_window(qapp, burn_sum):
    from lumacut_import.image_preview import preview_shape, preview_shape_passes
    sh = _shape(qapp, geom=(80.0, 80.0, 60.0, 20.0, 0.0), png=_block_png(qapp),
                mode="threshold", line_interval_mm=0.1, passes=2, angle_increment=45)
    st = sh.image.settings
    pv = preview_shape_passes(sh, st, max_pixels=60 * 60, burn_sum=burn_sum, focus_mm=(-12, -3))
    assert pv.focus_mm == pytest.approx((-12, -3), abs=0.1)
    edge = preview_shape_passes(sh, st, max_pixels=60 * 60, burn_sum=burn_sum,
                                focus_mm=(100, 100))
    # each pass computed with the tightest common centre: windows lie on top of each other
    one = preview_shape(sh, st, max_pixels=60 * 60, pass_index=0, focus_mm=edge.focus_mm)
    two = preview_shape(sh, st, max_pixels=60 * 60, pass_index=1, focus_mm=edge.focus_mm)
    assert one.focus_mm == pytest.approx(two.focus_mm, abs=0.1)
    assert edge.focus_mm[1] == pytest.approx(7.0, abs=0.1)      # 20 mm high, 6 mm window


def test_common_focus_rule():
    from lumacut_import.image_preview import Preview, _common_focus

    def pv(f):
        return Preview(np.zeros((2, 2), np.uint8), True, 0.0, focus_mm=f)

    assert _common_focus([pv((1, 1)), pv((1.01, 1))], (1, 1), 0.1) is None
    assert _common_focus([pv((27, 7)), pv((18, 9))], (100, 100), 0.1) == (18, 7)
    assert _common_focus([pv((-27, 7)), pv((-18, 9))], (-100, 100), 0.1) == (-18, 7)
    assert _common_focus([pv((5, 5))], (5, 5), 0.1) is None
    assert _common_focus([pv((5, 5)), pv((1, 1))], None, 0.1) is None


def test_job_is_untouched_by_the_window(qapp):
    from lumacut_job.images import image_job
    sh = _block_shape(qapp, size=100.0, mode="jarvis")
    before = image_job(sh)
    from lumacut_import.image_preview import preview_shape
    preview_shape(sh, sh.image.settings, focus_mm=(20, 20), spot_mm=0.08)
    assert image_job(sh) == before


# ------------------------------------------------------------- dialog
def test_dialog_starts_centred_and_says_how_to_move(qapp):
    from PySide6.QtCore import Qt
    dlg = _big_dialog(qapp)
    assert dlg.preview_focus_mm() is None and not dlg.preview_center.isEnabled()
    assert dlg.last_preview.pannable
    assert "Ausschnitt aus der Bildmitte – ziehen verschiebt" in dlg.preview_label.text()
    assert dlg.preview.cursor().shape() == Qt.OpenHandCursor
    assert dlg.preview_center.toolTip() and "Doppelklick" in dlg.preview_center.toolTip()


def test_small_image_has_nothing_to_move(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    dlg = _dialog(qapp)                    # 6 × 6 mm: whole image visible
    runs = dlg.preview_runs
    QTest.mousePress(dlg.preview, Qt.LeftButton, Qt.NoModifier, QPoint(150, 150))
    QTest.mouseMove(dlg.preview, QPoint(100, 100))
    QTest.mouseRelease(dlg.preview, Qt.LeftButton, Qt.NoModifier, QPoint(100, 100))
    assert dlg.preview_focus_mm() is None and dlg.preview_runs == runs
    assert "ziehen" not in dlg.preview_label.text()


def test_drag_with_the_mouse_moves_the_window_like_a_map(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    dlg = _big_dialog(qapp)                # 100 mm at 0.1 mm: 600 dots shown in 300 px
    dlg.show()
    QTest.mousePress(dlg.preview, Qt.LeftButton, Qt.NoModifier, QPoint(100, 100))
    QTest.mouseMove(dlg.preview, QPoint(150, 125))
    QTest.mouseRelease(dlg.preview, Qt.LeftButton, Qt.NoModifier, QPoint(200, 150))
    # content follows the pointer: the centre moves left / up, 0.2 mm per screen pixel
    assert dlg.preview_focus_mm() == pytest.approx((-20.0, -10.0), abs=0.11)
    assert dlg.last_preview.focus_mm == pytest.approx((-20.0, -10.0), abs=0.11)
    assert "20.0 mm links, 10.0 mm über der Bildmitte" in dlg.preview_label.text()
    assert dlg.preview_center.isEnabled()
    dlg.close()


def test_double_click_and_centre_button_go_back(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    dlg = _big_dialog(qapp)
    dlg.drag_preview(100, 50, update=True)
    assert dlg.preview_focus_mm() is not None
    QTest.mouseDClick(dlg.preview, Qt.LeftButton, Qt.NoModifier, QPoint(10, 10))
    assert dlg.preview_focus_mm() is None and not dlg.preview_center.isEnabled()
    assert "Bildmitte – ziehen verschiebt" in dlg.preview_label.text()
    dlg.drag_preview(-30, 0, update=True)
    assert dlg.preview_focus_mm() == pytest.approx((6.0, 0.0), abs=0.11)
    assert "6.0 mm rechts der Bildmitte" in dlg.preview_label.text()
    dlg.preview_center.click()
    assert dlg.preview_focus_mm() is None


def test_drag_finds_the_block(qapp):
    dlg = _big_dialog(qapp, size=200.0)
    fx, fy = _block_focus(200.0)
    per = 0.1 / (300 / 600)
    dlg.drag_preview(-fx / per, -fy / per, update=True)
    assert dlg.preview_focus_mm() == pytest.approx((fx, fy), abs=0.11)
    assert _centre(dlg.last_preview.pixels) < 30


def test_window_stops_at_the_image_edge(qapp):
    dlg = _big_dialog(qapp)
    dlg.drag_preview(-10_000, 10_000, update=True)
    assert dlg.preview_focus_mm() == pytest.approx((20.0, -20.0), abs=0.11)   # 60 mm window
    dlg.drag_preview(100, 0, update=True)               # no dead way back from the edge
    assert dlg.preview_focus_mm()[0] == pytest.approx(0.0, abs=0.11)


def test_rotated_image_keeps_the_focus_on_the_image(qapp):
    dlg = _big_dialog(qapp, rot=45.0)
    dlg.set_preview_focus((1000, 0))
    fx, fy = dlg.preview_focus_mm()
    t = math.radians(45.0)
    lx, ly = fx * math.cos(t) + fy * math.sin(t), -fx * math.sin(t) + fy * math.cos(t)
    assert abs(lx) <= 50 + 0.11 and abs(ly) <= 50 + 0.11
    assert fx > 0


def test_magnifier_drag_uses_the_magnified_scale(qapp):
    dlg = _big_dialog(qapp)
    dlg.spot_sim.setChecked(True)
    dlg.update_preview()
    info = dlg.last_preview.spot
    h, w = dlg.last_preview.pixels.shape
    per = 0.1 / info.sub / min(300 / w, 300 / h)
    dlg.drag_preview(-50, 0, update=True)
    assert dlg.preview_focus_mm() == pytest.approx((50 * per, 0.0), abs=0.11)
    assert "Lupe" in dlg.preview_label.text() and "rechts der Bildmitte" in dlg.preview_label.text()


def test_focus_survives_other_settings_and_does_not_touch_them(qapp):
    dlg = _big_dialog(qapp)
    before = dlg.settings()
    dlg.set_preview_focus((-12.0, 8.0))
    assert dlg.settings() == before
    dlg.interval.setValue(0.12)
    dlg.update_preview()
    assert dlg.preview_focus_mm() == pytest.approx((-12.0, 8.0), abs=0.13)
    dlg.mode.setCurrentIndex(dlg.mode.findData("jarvis"))
    dlg.update_preview()
    assert dlg.last_preview.focus_mm == pytest.approx((-12.0, 8.0), abs=0.13)


def test_all_passes_in_the_dialog_follow_the_focus(qapp):
    dlg = _big_dialog(qapp, size=200.0, passes=2, angle_increment=90)
    dlg.preview_pass.setCurrentIndex(dlg.preview_pass.findData(dlg.ALL_PASSES_SUM))
    dlg.set_preview_focus(_block_focus(200.0))
    assert _centre(dlg.last_preview.pixels) < 30
    assert dlg.last_preview.focus_mm == pytest.approx(_block_focus(200.0), abs=0.11)


def test_focus_text():
    from lumacut_import.qt import focus_text
    assert focus_text("Lupe", None) == "Lupe auf die Bildmitte – ziehen verschiebt"
    assert focus_text("Ausschnitt", (0.01, -0.02)) == \
        "Ausschnitt aus der Bildmitte – ziehen verschiebt"
    assert focus_text("Lupe", (-12, 6)) == \
        "Lupe 12.0 mm links, 6.0 mm unter der Bildmitte – ziehen verschiebt, Doppelklick = Mitte"
    assert focus_text("Ausschnitt", (0, -3.25)).startswith("Ausschnitt 3.2 mm über der Bildmitte")


def test_touch_mode_centre_button_is_44_px(qapp):
    from PySide6.QtWidgets import QWidget

    class Canvas:
        touch_mode = True

    parent = QWidget()
    parent.canvas = Canvas()
    dlg = _dialog(qapp, parent=parent)
    assert dlg.preview_center.minimumHeight() >= 44
    assert dlg.preview_center.parent() is dlg.spot_row
    assert _dialog(qapp).preview_center.minimumHeight() < 44
    parent.deleteLater()


def test_dialog_without_image_data_has_no_window(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    dlg = ImageSettingsDialog(ImageSettings(), 40.0, 400)
    assert dlg.last_preview is None
    dlg.drag_preview(10, 10)
    assert dlg.preview_focus_mm() is None
