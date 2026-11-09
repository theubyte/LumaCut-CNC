"""Review round 45: the image settings preview shows every pass of a scan
angle increment (single pass or all passes on top of each other) – before,
only pass 1 was previewed."""
from __future__ import annotations

import numpy as np
import pytest

from test_image_scan_angle import _half_image, _shape


def _stripes(qapp, w=60, h=60):
    """Diagonal-free test image: a black square in the top-left quarter."""
    from PySide6.QtGui import QColor, QImage
    from lumacut_import.image import grayscale_png
    img = QImage(w, h, QImage.Format_RGB32)
    for x in range(w):
        for y in range(h):
            v = 0 if (x < w // 2 and y < h // 2) else 255
            img.setPixelColor(x, y, QColor(v, v, v))
    return grayscale_png(img)


# ------------------------------------------------------------- engine
def test_pass_angle_and_distinct_passes():
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import distinct_pass_indices, pass_angle
    st = ImageSettings(passes=4, scan_angle=30, angle_increment=90)
    assert [pass_angle(st, k) for k in range(4)] == [30, -60, 30, -60]
    assert pass_angle(st, 99) == -60 and pass_angle(st, -3) == 30     # clamped
    assert distinct_pass_indices(st) == [0, 1]
    assert distinct_pass_indices(ImageSettings(passes=3, angle_increment=30)) == [0, 1, 2]
    assert distinct_pass_indices(ImageSettings(passes=3)) == [0]      # no increment


def test_pass_index_zero_is_the_old_preview(qapp):
    from lumacut_import.image_preview import preview_shape, render_for_preview
    sh = _shape(qapp, mode="floyd", line_interval_mm=0.1, scan_angle=30, passes=3,
                angle_increment=45)
    a = preview_shape(sh, sh.image.settings)
    b = preview_shape(sh, sh.image.settings, pass_index=0)
    assert (a.pixels == b.pixels).all() and a.burn_share == b.burn_share
    g0, _ = render_for_preview(sh, sh.image.settings)
    g1, _ = render_for_preview(sh, sh.image.settings, 0)
    assert (g0 == g1).all()


def test_later_pass_is_rendered_at_its_own_angle(qapp):
    """Pass 2 of 0° + 90° equals a plain 90° preview; pass 1 equals 0°."""
    from lumacut_import.image_preview import preview_shape
    sh = _shape(qapp, mode="floyd", line_interval_mm=0.1, passes=2, angle_increment=90)
    st = sh.image.settings
    p1 = preview_shape(sh, st, pass_index=0)
    p2 = preview_shape(sh, st, pass_index=1)
    s0 = _shape(qapp, mode="floyd", line_interval_mm=0.1)
    s90 = _shape(qapp, mode="floyd", line_interval_mm=0.1, scan_angle=90)
    assert (p1.pixels == preview_shape(s0, s0.image.settings).pixels).all()
    assert (p2.pixels == preview_shape(s90, s90.image.settings).pixels).all()
    assert not np.array_equal(p1.pixels, p2.pixels) or p1.pixels.shape != p2.pixels.shape
    # dark half stays on the left like on the canvas in every pass
    for pv in (p1, p2):
        _ys, xs = np.nonzero(pv.pixels < 128)
        assert xs.mean() < pv.pixels.shape[1] / 2


def test_overlay_takes_the_darkest_dot_and_centres_sizes():
    from lumacut_import.image_preview import Preview, overlay_previews
    a = Preview(np.full((4, 6), 255, np.uint8), False, 0.2)
    a.pixels[0, 0] = 0
    b = Preview(np.full((2, 2), 100, np.uint8), True, 0.6)
    o = overlay_previews([a, b])
    assert o.pixels.shape == (4, 6) and o.cropped
    assert o.pixels[0, 0] == 0
    assert (o.pixels[1:3, 2:4] == 100).all()                  # centred
    assert int((o.pixels == 255).sum()) == 4 * 6 - 1 - 4
    assert o.burn_share == pytest.approx(0.4)
    single = overlay_previews([a])
    assert (single.pixels == a.pixels).all() and single.pixels is not a.pixels
    with pytest.raises(ValueError):
        overlay_previews([])


def test_all_passes_overlay_covers_each_pass(qapp):
    from lumacut_import.image_preview import preview_shape, preview_shape_passes
    png = _stripes(qapp)
    sh = _shape(qapp, geom=(80.0, 80.0, 6.0, 6.0, 0.0), png=png, mode="threshold",
                line_interval_mm=0.1, passes=3, angle_increment=45)
    st = sh.image.settings
    allp = preview_shape_passes(sh, st)
    singles = [preview_shape(sh, st, pass_index=k) for k in range(3)]
    assert allp.pixels.shape == tuple(max(p.pixels.shape[i] for p in singles) for i in (0, 1))
    dark_all = int((allp.pixels < 128).sum())
    for p in singles:
        assert dark_all >= int((p.pixels < 128).sum())
    assert allp.burn_share == pytest.approx(np.mean([p.burn_share for p in singles]))
    # dark square stays in the top-left quarter
    ys, xs = np.nonzero(allp.pixels < 128)
    h, w = allp.pixels.shape
    assert xs.mean() < w / 2 and ys.mean() < h / 2
    # cross raster 0/90/0: pass 3 is not rendered again
    renders = []
    cross = _shape(qapp, mode="floyd", line_interval_mm=0.1, passes=3, angle_increment=90)

    def rendered_for(k):
        from lumacut_import.image_preview import render_for_preview
        renders.append(k)
        return render_for_preview(cross, cross.image.settings, k)
    preview_shape_passes(cross, cross.image.settings, rendered_for=rendered_for)
    assert renders == [0, 1]


# ------------------------------------------------------------- dialog
def _dialog(qapp, **settings):
    from lumacut_import.qt import ImageSettingsDialog
    sh = _shape(qapp, **settings)
    return ImageSettingsDialog(sh.image.settings, sh.geom.w, sh.image.px_width, shape=sh), sh


def test_dialog_pass_choice_lists_every_pass_and_all(qapp):
    dlg, _sh = _dialog(qapp, mode="floyd", line_interval_mm=0.2, scan_angle=30, passes=3,
                       angle_increment=45)
    assert dlg.preview_pass_row.isVisibleTo(dlg)
    labels = [dlg.preview_pass.itemText(i) for i in range(dlg.preview_pass.count())]
    assert labels == ["1. Durchgang (30°)", "2. Durchgang (75°)", "3. Durchgang (-60°)",
                      "Alle 3 Durchgänge übereinander"]
    assert dlg.preview_pass_index() == 0
    assert "(Vorschau: 1. Durchgang, 30°)" in dlg.preview_label.text()
    # changing the increment relabels and keeps the chosen pass
    dlg.preview_pass.setCurrentIndex(1)
    dlg.angle_increment.setValue(90)
    assert dlg.preview_pass.itemText(1) == "2. Durchgang (-60°)"
    assert dlg.preview_pass_index() == 1
    # fewer passes: a vanished choice falls back to pass 1
    dlg.preview_pass.setCurrentIndex(2)
    dlg.passes.setValue(2)
    assert dlg.preview_pass.count() == 3 and dlg.preview_pass_index() == 0
    dlg.passes.setValue(1)
    assert not dlg.preview_pass_row.isVisibleTo(dlg) and dlg.preview_pass_index() == 0
    dlg.passes.setValue(3)
    dlg.angle_increment.setValue(0)
    assert not dlg.preview_pass_row.isVisibleTo(dlg)
    # the choice is preview only – the settings stay the same
    assert "preview" not in str(dlg.settings().to_dict())


def test_dialog_previews_the_chosen_pass_and_all_passes(qapp, monkeypatch):
    from lumacut_import import image_preview
    from lumacut_import.image_preview import preview_shape, preview_shape_passes
    sh = _shape(qapp, mode="floyd", line_interval_mm=0.1, passes=3, angle_increment=90)
    st = sh.image.settings
    ref1, ref0 = preview_shape(sh, st, pass_index=1), preview_shape(sh, st)
    ref_all = preview_shape_passes(sh, st)
    renders = []
    real = image_preview.render_for_preview
    monkeypatch.setattr(image_preview, "render_for_preview",
                        lambda *a, **k: renders.append(a[2] if len(a) > 2 else 0)
                        or real(*a, **k))
    dlg, sh = _dialog(qapp, mode="floyd", line_interval_mm=0.1, passes=3, angle_increment=90)
    assert renders == [0]
    dlg.preview_pass.setCurrentIndex(1)
    dlg.update_preview()
    assert (dlg.last_preview.pixels == ref1.pixels).all()
    assert "(Vorschau: 2. Durchgang, 90°)" in dlg.preview_label.text()
    dlg.preview_pass.setCurrentIndex(2)            # pass 3 = 0° again: cached
    dlg.update_preview()
    assert (dlg.last_preview.pixels == ref0.pixels).all()
    dlg.preview_pass.setCurrentIndex(3)            # all passes
    dlg.update_preview()
    assert (dlg.last_preview.pixels == ref_all.pixels).all()
    assert "alle 3 Durchgänge übereinander" in dlg.preview_label.text()
    assert renders.count(0) == 1 and renders.count(1) == 1     # each angle rendered once
    # histogram stays on pass 1 and power changes reuse the renders
    n = len(renders)
    dlg.power.setValue(40)
    dlg.update_preview()
    assert len(renders) == n
    # a new line interval drops the cached angles
    dlg.interval.setValue(0.2)
    dlg.update_preview()
    assert len(renders) == n + 2


def test_dialog_choice_schedules_a_preview(qapp):
    dlg, _sh = _dialog(qapp, mode="threshold", line_interval_mm=0.2, passes=2,
                       angle_increment=90)
    dlg._preview_timer.stop()
    dlg.preview_pass.setCurrentIndex(1)
    assert dlg._preview_timer.isActive()


def test_dialog_without_shape_keeps_the_old_hint(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    png, pw, _ph = _half_image(qapp)
    dlg = ImageSettingsDialog(ImageSettings(mode="floyd", line_interval_mm=0.2, passes=2,
                                            angle_increment=90), 12.0, pw, png=png,
                              height_mm=6.0)
    assert not dlg.preview_pass_row.isVisibleTo(dlg) and dlg.preview_pass.count() == 0
    dlg.update_preview()
    assert "(Vorschau: 1. Durchgang)" in dlg.preview_label.text()
