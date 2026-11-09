"""Review round 47: the image settings preview adds up the burn of every pass
(„Alle N Durchgänge aufaddiert (Brennsumme)“) – before, the all-passes preview
only showed the darkest dot per position, so greyscale dots and cross-raster
dots hit by several passes looked like a single pass."""
from __future__ import annotations

import numpy as np
import pytest

from test_image_scan_angle import _shape
from test_image_scan_angle_pass_preview import _dialog, _stripes


def _grey_png(qapp, value=128, w=40, h=40):
    from PySide6.QtGui import QColor, QImage
    from lumacut_import.image import grayscale_png
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(value, value, value))
    return grayscale_png(img)


# ------------------------------------------------------------- engine
def test_sum_adds_the_burn_and_divides_by_the_passes():
    from lumacut_import.image_preview import Preview, sum_previews
    a = Preview(np.full((2, 2), 255, np.uint8), False, 0.5)
    a.pixels[0, 0] = 0            # full power
    a.pixels[0, 1] = 128          # half power
    b = Preview(np.full((2, 2), 255, np.uint8), False, 0.25)
    b.pixels[0, 0] = 0
    b.pixels[1, 1] = 0
    s = sum_previews([a, b])
    assert s.pixels[0, 0] == 0                       # both passes full power = black
    assert s.pixels[1, 1] == 128                     # one of two passes full = half grey
    assert s.pixels[0, 1] == 192                     # 255 - (255 - 128) / 2, rounded
    assert s.pixels[1, 0] == 255
    assert s.burn_share == pytest.approx(0.375)
    assert s.multi_share == pytest.approx(1 / 3)     # 3 dots lasered, 1 by both passes
    # darker than one pass alone where both passes burn, never darker than black
    assert s.pixels.dtype == np.uint8


def test_sum_counts_repeated_angles_and_centres_sizes():
    from lumacut_import.image_preview import Preview, sum_previews
    a = Preview(np.full((4, 6), 255, np.uint8), False, 0.2)
    a.pixels[1:3, 2:4] = 0
    b = Preview(np.full((2, 2), 0, np.uint8), True, 1.0)
    s = sum_previews([a, b], counts=[2, 1])
    assert s.pixels.shape == (4, 6) and s.cropped
    assert (s.pixels[1:3, 2:4] == 0).all()           # all three passes full
    a.pixels[1:3, 2:4] = 255
    s = sum_previews([a, b], counts=[2, 1])
    assert (s.pixels[1:3, 2:4] == 170).all()         # 1 of 3 passes: 255 - 85, centred
    assert s.burn_share == pytest.approx((0.2 * 2 + 1.0) / 3)
    assert s.multi_share == 0.0
    single = sum_previews([a])
    assert (single.pixels == a.pixels).all() and single.multi_share == 0.0
    with pytest.raises(ValueError):
        sum_previews([])
    with pytest.raises(ValueError):
        sum_previews([a, b], counts=[1])
    with pytest.raises(ValueError):
        sum_previews([a], counts=[0])


def test_cross_raster_sum_is_darker_where_both_passes_burn(qapp):
    from lumacut_import.image_preview import (overlay_previews, preview_shape,
                                              preview_shape_passes)
    png = _stripes(qapp)
    sh = _shape(qapp, geom=(80.0, 80.0, 6.0, 6.0, 0.0), png=png, mode="threshold",
                line_interval_mm=0.1, passes=2, angle_increment=90)
    st = sh.image.settings
    total = preview_shape_passes(sh, st, burn_sum=True)
    over = preview_shape_passes(sh, st)
    singles = [preview_shape(sh, st, pass_index=k) for k in range(2)]
    assert total.pixels.shape == over.pixels.shape
    # never darker than the darkest-dot overlay, lasered exactly where it lasers
    assert (total.pixels >= over.pixels).all()
    assert ((total.pixels < 255) == (over.pixels < 255)).all()
    # dots of both passes black, dots of one pass half grey
    vals = set(np.unique(total.pixels).tolist())
    assert vals <= {0, 128, 255} and 0 in vals
    assert total.multi_share > 0.5
    assert total.burn_share == pytest.approx(np.mean([p.burn_share for p in singles]))
    # the old overlay is unchanged
    assert (over.pixels == overlay_previews(singles).pixels).all()
    assert over.multi_share is None


def test_repeated_angle_counts_twice_but_renders_once(qapp):
    from lumacut_import.image_preview import (preview_shape, preview_shape_passes,
                                              render_for_preview, sum_previews)
    png = _grey_png(qapp, 128)
    sh = _shape(qapp, geom=(80.0, 80.0, 4.0, 4.0, 0.0), png=png, mode="grayscale",
                line_interval_mm=0.1, passes=3, angle_increment=90, power=100, min_power=0)
    st = sh.image.settings
    renders = []

    def rendered_for(k):
        renders.append(k)
        return render_for_preview(sh, st, k)
    total = preview_shape_passes(sh, st, rendered_for=rendered_for, burn_sum=True)
    assert renders == [0, 1]
    p0, p1 = preview_shape(sh, st, pass_index=0), preview_shape(sh, st, pass_index=1)
    ref = sum_previews([p0, p1], counts=[2, 1])
    assert (total.pixels == ref.pixels).all()
    assert total.multi_share == pytest.approx(1.0)   # every grey dot is hit by 3 passes


def test_grayscale_sum_matches_the_mean_burn(qapp):
    """Mid-grey greyscale image, 0° + 90°: every dot gets half power twice –
    the sum shows the mean darkness (a single pass of two at 50 %)."""
    from lumacut_import.image_preview import preview_shape, preview_shape_passes
    png = _grey_png(qapp, 128)
    sh = _shape(qapp, geom=(80.0, 80.0, 4.0, 4.0, 0.0), png=png, mode="grayscale",
                line_interval_mm=0.1, passes=2, angle_increment=90, power=100, min_power=0)
    st = sh.image.settings
    p0 = preview_shape(sh, st)
    total = preview_shape_passes(sh, st, burn_sum=True)
    inner = total.pixels[5:-5, 5:-5]
    single = p0.pixels[5:-5, 5:-5]
    assert np.abs(inner.astype(int) - int(np.median(single))).max() <= 1


# ------------------------------------------------------------- dialog
def test_dialog_offers_and_shows_the_burn_sum(qapp, monkeypatch):
    from lumacut_import import image_preview
    from lumacut_import.image_preview import preview_shape_passes
    dlg, sh = _dialog(qapp, mode="floyd", line_interval_mm=0.1, passes=3, angle_increment=90)
    ref = preview_shape_passes(sh, sh.image.settings, burn_sum=True)
    idx = dlg.preview_pass.findData(dlg.ALL_PASSES_SUM)
    assert dlg.preview_pass.itemText(idx) == "Alle 3 Durchgänge aufaddiert (Brennsumme)"
    assert idx == dlg.preview_pass.count() - 1
    dlg.update_preview()                       # pass 1 rendered and cached
    renders = []
    real = image_preview.render_for_preview
    monkeypatch.setattr(image_preview, "render_for_preview",
                        lambda *a, **k: renders.append(a[2] if len(a) > 2 else 0)
                        or real(*a, **k))
    dlg.preview_pass.setCurrentIndex(idx)
    assert dlg.preview_pass_index() == dlg.ALL_PASSES_SUM
    dlg.update_preview()
    assert (dlg.last_preview.pixels == ref.pixels).all()
    text = dlg.preview_label.text()
    assert "Brennsumme aller 3 Durchgänge" in text and "mehrfach gelasert" in text
    assert f"{ref.multi_share * 100:.0f} %" in text
    assert renders == [1]                      # 0° came from the cache
    # switching to the darkest-dot overlay reuses both renders
    dlg.preview_pass.setCurrentIndex(dlg.preview_pass.findData(dlg.ALL_PASSES))
    dlg.update_preview()
    assert renders == [1] and "übereinander" in dlg.preview_label.text()
    # the choice survives a new increment and is preview only
    dlg.preview_pass.setCurrentIndex(idx)
    dlg.angle_increment.setValue(45)
    assert dlg.preview_pass_index() == dlg.ALL_PASSES_SUM
    assert "Brennsumme" not in str(dlg.settings().to_dict())
    dlg.passes.setValue(1)
    assert not dlg.preview_pass_row.isVisibleTo(dlg) and dlg.preview_pass_index() == 0
