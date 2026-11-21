"""Weiche Maskenkante (Runde 105): ein maskiertes Bild blendet innen an der Maskenkante weich
auf Weiß (= nicht lasern) aus – Rechnung, Bildansicht, Auftrag, Datei, Lösen / Zuschneiden,
Bedienung (Dialog, Menüs, Touch)."""

from __future__ import annotations

import math
import re
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage

from lumacut_canvas import imagemask, imagemask_ui
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.imagecrop import crop_image, decode_png
from lumacut_canvas.imagemask import (MaskError, apply_mask, feather_alpha, feather_mm,
                                      feather_preview, masked_png, release_mask, set_feather)
from lumacut_canvas.model import Document, Geometry, ImageSettings, Layer, RasterImage, Shape
from lumacut_canvas.workarea import to_machine
from lumacut_import.image import grayscale_png
from lumacut_job.images import image_job, render_inside


def _png(w=100, h=50, value=None):
    img = QImage(w, h, QImage.Format_RGB32)
    for x in range(w):
        v = value if value is not None else 20 + int(200 * x / max(1, w - 1))
        for y in range(h):
            img.setPixelColor(x, y, QColor(v, v, v))
    return grayscale_png(img)


def _image(geom=None, value=None, w=100, h=50, layer="L1", **settings):
    png, pw, ph = _png(w, h, value)
    return Shape("image", geom or Geometry(50, 50, 40, 20), layer,
                 image=RasterImage(png, pw, ph, ImageSettings(**settings)))


def _circle(cx=70, cy=60, r=8, layer="L1"):
    return Shape("ellipse", Geometry(cx - r, cy - r, 2 * r, 2 * r), layer)


def _rect(x, y, w, h, layer="L1"):
    return Shape("rect", Geometry(x, y, w, h), layer)


def _alpha(shape):
    g, a = decode_png(shape.image.view_png)
    return np.full(g.shape, 255, np.uint8) if a is None else a


def _px(x_mm, y_mm, ppm=2.5):
    return int((y_mm - 50) * ppm), int((x_mm - 50) * ppm)


def _burned_points(lines):
    pts, pos = [], None
    for ln in lines:
        m = re.match(r"G[01] X([\d.]+) Y([\d.]+)", ln)
        if not m:
            continue
        p = (float(m.group(1)), float(m.group(2)))
        s = re.search(r"S(\d+)", ln)
        if ln.startswith("G1") and s and int(s.group(1)) > 0 and pos is not None:
            pts += [pos, p]
        pos = p
    return pts


# --- Rechnung -----------------------------------------------------------------------------------

def test_feather_alpha_hard_for_small_widths():
    inside = np.zeros((20, 30), bool)
    inside[5:15, 5:25] = True
    for f in (0.0, 0.3, 0.5, -2.0, float("nan")):
        assert np.array_equal(feather_alpha(inside, f), inside.astype(np.float32))


def test_feather_alpha_rises_inward_along_an_s_curve():
    inside = np.zeros((41, 81), bool)
    inside[10:31, 10:71] = True
    a = feather_alpha(inside, 6.0)
    row = a[20, 10:41]
    assert a[20, 9] == 0 and 0 < row[0] < 0.05                 # first inside pixel barely visible
    assert np.all(np.diff(row[:7]) > 0)                         # rising over the fade
    assert row[6] == pytest.approx(1.0) and row[10] == 1.0      # full from the feather width on
    t = 2.5 / 6.0                                               # d = 3 → t = (3 − 0.5) / 6
    assert row[2] == pytest.approx(t * t * (3 - 2 * t), abs=1e-5)
    assert np.all(a[~inside] == 0)


def test_image_border_is_no_edge():
    inside = np.ones((10, 10), bool)
    assert np.array_equal(feather_alpha(inside, 4.0), np.ones((10, 10), np.float32))
    inside[:, 7:] = False                                       # only the right side is an edge
    a = feather_alpha(inside, 4.0)
    assert a[5, 0] == 1.0 and a[0, 2] == 1.0 and a[5, 6] < 0.2


def test_hard_mask_is_byte_identical():
    im = apply_mask(_image(), [_circle()]).shape
    assert im.image.mask_feather == 0.0
    png = im.image.png
    hard = masked_png(png, 100, 50, im.image.mask)
    assert im.image.view_png == hard == masked_png(png, 100, 50, im.image.mask, 0.0)
    assert masked_png(png, 100, 50, im.image.mask, float("nan")) == hard
    assert set(np.unique(_alpha(im))) <= {0, 255}


def test_soft_view_fades_inside_the_edge(qapp):
    im = apply_mask(_image(value=60), [_circle()]).shape
    soft = set_feather(im, 2.0).shape                           # 5 px at 2.5 px / mm
    a, hard = _alpha(soft), _alpha(im)
    assert soft.image.mask_feather == pytest.approx(5.0)
    assert a[_px(70, 60)] == 255                                # centre stays full
    assert 0 < a[_px(77.6, 60)] < 80                            # 0.4 mm inside the edge: faint
    assert np.all(a[hard == 0] == 0)                            # outside stays outside
    g, _a = decode_png(soft.image.view_png)
    assert np.all(g[a == 0] == 255) and g[_px(70, 60)] == 60    # pixels kept, never burned outside
    assert soft.image.png == im.image.png


def test_hide_hole_gets_a_soft_rim_but_the_image_border_not(qapp):
    h = apply_mask(_image(), [_circle(r=5)], "hide").shape
    a = _alpha(set_feather(h, 2.0).shape)
    assert a[0, 0] == 255 and a[49, 99] == 255 and a[_px(52, 60)] == 255
    assert a[_px(70, 60)] == 0 and 0 < a[_px(75.4, 60)] < 255


def test_mm_and_pixels(qapp):
    im = apply_mask(_image(), [_circle()]).shape
    res = set_feather(im, 3.0)
    assert res.feather_px == pytest.approx(7.5) and feather_mm(res.shape) == pytest.approx(3.0)
    bigger = replace(res.shape, geom=Geometry(50, 50, 80, 40))   # scaled ×2: fade grows along
    assert feather_mm(bigger) == pytest.approx(6.0)
    assert bigger.image.view_png == res.shape.image.view_png
    assert 0 < res.soft_share < 1
    assert feather_mm(_image()) == 0.0


def test_feather_follows_move_and_rotation(qapp):
    im = set_feather(apply_mask(_image(Geometry(50, 50, 40, 20, 30)), [_circle()]).shape, 2).shape
    moved = replace(im, geom=Geometry(120, 90, 40, 20, -15))
    assert moved.image.view_png == im.image.view_png


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"), "x", None])
def test_invalid_widths(qapp, bad):
    im = apply_mask(_image(), [_circle()]).shape
    with pytest.raises(MaskError):
        set_feather(im, bad)


def test_errors_without_mask_or_image(qapp):
    with pytest.raises(MaskError, match="keine Maske"):
        set_feather(_image(), 2.0)
    with pytest.raises(MaskError):
        set_feather(_circle(), 2.0)
    im = apply_mask(_image(), [_circle()]).shape
    with pytest.raises(MaskError, match="schon hart"):
        set_feather(im, 0.0)
    soft = set_feather(im, 2.0).shape
    with pytest.raises(MaskError, match="schon diese Breite"):
        set_feather(soft, 2.0)


def test_width_clamped_and_zero_makes_it_hard_again(qapp):
    im = apply_mask(_image(), [_circle()]).shape
    big = set_feather(im, 500.0).shape
    assert feather_mm(big) == pytest.approx(imagemask.FEATHER_RANGE_MM[1])
    hard = set_feather(big, 0.0).shape
    assert hard.image.mask_feather == 0.0 and hard.image.view_png == im.image.view_png
    tiny = set_feather(big, 0.1)                                # 0.25 px: no visible fade
    assert tiny.feather_px == 0.0


def test_narrowing_keeps_the_soft_edge_and_release_or_crop_drop_it(qapp):
    soft = set_feather(apply_mask(_image(), [_circle()]).shape, 2.0).shape
    n = apply_mask(soft, [_rect(50, 50, 20, 20)]).shape
    assert n.image.mask_feather == soft.image.mask_feather
    whole, _outline = release_mask(soft, "L1")
    assert whole.image.mask == () and whole.image.mask_feather == 0.0
    assert whole.image.view_png == whole.image.png
    cropped = crop_image(soft, [_rect(50, 50, 20, 20)]).shape   # bakes the fade into the pixels
    assert cropped.image.mask == () and cropped.image.mask_feather == 0.0
    _g, a = decode_png(cropped.image.png)
    assert a is not None and np.any((a > 0) & (a < 255))


def test_save_load_round_trip_and_hard_files_unchanged(qapp):
    hard = apply_mask(_image(), [_circle()]).shape
    d = hard.image.to_dict()
    assert "mask_feather" not in d and "mask_feather" not in _image().image.to_dict()
    soft = set_feather(hard, 2.0).shape
    d = soft.image.to_dict()
    assert d["mask_feather"] == pytest.approx(5.0)
    back = RasterImage.from_dict(d)
    assert back.mask_feather == pytest.approx(5.0) and back.view_png == soft.image.view_png


@pytest.mark.parametrize("bad", [-3, "x", None, float("nan"), [1]])
def test_broken_feather_values_load_as_hard(qapp, bad):
    d = set_feather(apply_mask(_image(), [_circle()]).shape, 2.0).shape.image.to_dict()
    d["mask_feather"] = bad
    assert RasterImage.from_dict(d).mask_feather == 0.0


def test_feather_without_mask_is_ignored_on_loading(qapp):
    d = _image().image.to_dict()
    d["mask_feather"] = 5
    assert RasterImage.from_dict(d).mask_feather == 0.0


def test_document_round_trip(qapp, tmp_path):
    from lumacut_canvas.document_io import load_into, save_document
    doc = Document()
    lid = doc.active_layer_id
    soft = set_feather(apply_mask(_image(layer=lid), [_circle(layer=lid)]).shape, 1.5).shape
    doc.add_shape(soft)
    back = Document()
    load_into(back, save_document(doc, tmp_path / "f.lcut"))
    b = back.shape(soft.id).image
    assert b.mask_feather == pytest.approx(3.75) and b.view_png == soft.image.view_png


def test_preview(qapp):
    im = apply_mask(_image(value=30, w=400, h=200), [_circle()]).shape
    hard = feather_preview(im, 0.0)
    soft = feather_preview(im, 3.0)
    assert soft.shape == hard.shape == (110, 220)
    c = (55, 110)
    assert hard[c] == soft[c] < 40 and soft[0, 0] == 255 and hard[0, 0] == 255
    edge = (55, 110 + int(7.5 * 5.5))                           # 0.5 mm inside the edge
    assert hard[edge] < 50 and soft[edge] > 200
    assert np.all(soft >= hard - 1)                             # the fade only gets lighter
    plain = feather_preview(_image(value=30), 3.0)
    assert plain.max() < 40                                     # no mask: no fade


# --- Auftrag ------------------------------------------------------------------------------------

def _radial_density(shape, cx_mm, cy_mm, bands):
    cx, cy = to_machine(cx_mm, cy_mm)
    pts = _burned_points(image_job(shape).lines)
    out = []
    for lo, hi in bands:
        length = 0.0
        for (x0, y0), (x1, y1) in zip(pts[::2], pts[1::2]):
            for k in range(11):                                 # sample along the burned segment
                x, y = x0 + (x1 - x0) * k / 10, y0 + (y1 - y0) * k / 10
                if lo <= math.hypot(x - cx, y - cy) < hi:
                    length += math.hypot(x1 - x0, y1 - y0) / 11
        out.append(length / (math.pi * (hi * hi - lo * lo)))
    return out, pts, (cx, cy)


def test_dithered_job_thins_out_towards_the_edge(qapp):
    im = apply_mask(_image(value=60, w=400, h=200, mode="jarvis", line_interval_mm=0.1),
                    [_circle()]).shape
    soft = set_feather(im, 4.0).shape
    (inner, mid, rim), pts, (cx, cy) = _radial_density(soft, 70, 60,
                                                       [(0, 3.5), (4.5, 6), (7, 7.9)])
    assert inner > mid > rim > 0
    assert rim < 0.3 * inner
    assert max(math.hypot(x - cx, y - cy) for x, y in pts) <= 8.15     # never outside the mask
    (h_inner, _hm, h_rim), _p, _c = _radial_density(im, 70, 60, [(0, 3.5), (4.5, 6), (7, 7.9)])
    assert h_rim > 0.7 * h_inner                                       # hard edge: no fade


def test_grayscale_power_falls_off(qapp):
    im = apply_mask(_image(value=0, w=200, h=100, mode="grayscale", line_interval_mm=0.2),
                    [_circle()]).shape
    soft = set_feather(im, 4.0).shape
    cx, cy = to_machine(70, 60)
    powers = {}
    pos = None
    for ln in image_job(soft).lines:
        m = re.match(r"G[01] X([\d.]+) Y([\d.]+)", ln)
        if not m:
            continue
        p = (float(m.group(1)), float(m.group(2)))
        s = re.search(r"S(\d+)", ln)
        if ln.startswith("G1") and s and pos is not None:
            for k in range(21):                                 # sample along the segment
                x = pos[0] + (p[0] - pos[0]) * k / 20
                y = pos[1] + (p[1] - pos[1]) * k / 20
                r = math.hypot(x - cx, y - cy)
                powers.setdefault(min(int(r), 9), []).append(int(s.group(1)))
        pos = p
    assert min(powers[1]) > max(powers[6]) > 0                 # full inside, fading at the rim
    assert max(powers.get(9, [0])) == 0                        # nothing beyond the mask


def test_adjusted_image_keeps_the_outer_half_of_the_fade(qapp):
    im = apply_mask(_image(value=60, w=400, h=200, contrast=20.0, line_interval_mm=0.1),
                    [_circle()]).shape
    soft = set_feather(im, 4.0).shape
    hard_in = render_inside(im, 0.1)
    soft_in = render_inside(soft, 0.1)
    assert hard_in is not None and soft_in is not None
    a = _alpha(soft)                                            # 1 px = 0.1 mm = raster dot
    assert a.shape == soft_in.shape
    # every faded pixel counts as inside – a 50 % threshold would lose the outer half
    assert np.count_nonzero((a > 0) != soft_in) <= 20
    outer_half = (a > 0) & (a < 128)
    assert np.count_nonzero(outer_half) > 1000 and soft_in[outer_half].all()
    assert np.count_nonzero(hard_in & ~soft_in) <= 2000         # only the invisible rim


def test_hard_masked_job_unchanged_by_the_field(qapp):
    im = apply_mask(_image(value=60, w=200, h=100, mode="floyd", line_interval_mm=0.2),
                    [_circle()]).shape
    same = replace(im, image=replace(im.image, mask_feather=0.0))
    assert image_job(same).lines == image_job(im).lines


def test_document_gcode_with_soft_edge_is_pi_safe(qapp):
    from _pi_guard import pi_check
    from lumacut_job.planner import optimized_document_gcode
    doc = Document()
    lid = doc.active_layer_id
    im = _image(value=40, layer=lid, mode="floyd", line_interval_mm=0.2)
    doc.add_shape(set_feather(apply_mask(im, [_circle(layer=lid)]).shape, 2.0).shape)
    pi_check(optimized_document_gcode(doc))


# --- Bedienung ----------------------------------------------------------------------------------

@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1400, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, *shapes):
    lid = ed.document.active_layer_id
    for s in shapes:
        s.layer_id = lid
        ed.document.add_shape(s)
    ed.set_selection([s.id for s in shapes])
    return shapes


def _masked(ed, geom=None):
    im, _c = _add(ed, _image(geom), _circle(cx=(geom.x + 20) if geom else 70))
    assert ed.path_ops.image_mask.apply()
    return ed.document.shape(im.id)


def _answer(ed, mm, seen=None):
    def ask(image, value, count):
        if seen is not None:
            seen.append((image.id, value, count))
        return mm
    ed.path_ops.image_mask.ask_feather = ask


def test_feather_in_one_undo_step(ed):
    im = _masked(ed)
    msgs = []
    ed.statusMessage.connect(msgs.append)
    seen = []
    _answer(ed, 2.0, seen)
    n = ed.undo_stack.count()
    ed.actions_by_name[imagemask_ui.FEATHER].trigger()
    assert ed.undo_stack.count() == n + 1
    assert seen == [(im.id, imagemask_ui.FEATHER_DEFAULT_MM, 1)]
    assert ed.document.shape(im.id).image.mask_feather == pytest.approx(5.0)
    assert ed.selection == [im.id] and msgs[-1].startswith("Weiche Maskenkante 2 mm (1 Bild)")
    ed.undo_stack.undo()
    assert ed.document.shape(im.id).image.mask_feather == 0.0


def test_dialog_value_from_the_image_or_the_last_width(ed):
    im = _masked(ed)
    seen = []
    _answer(ed, 4.0, seen)
    assert ed.path_ops.image_mask.feather()
    _answer(ed, 1.0, seen)
    assert ed.path_ops.image_mask.feather()               # current width of the image is offered
    assert seen[1][1] == pytest.approx(4.0)
    _answer(ed, 0.0, seen)
    msgs = []
    ed.statusMessage.connect(msgs.append)
    assert ed.path_ops.image_mask.feather()
    assert msgs[-1].startswith("Maskenkante wieder hart")
    _answer(ed, None, seen)
    assert ed.path_ops.image_mask.feather() is False      # cancel
    assert seen[-1][1] == pytest.approx(1.0)              # hard image: last soft width offered
    assert ed.document.shape(im.id).image.mask_feather == 0.0


def test_several_images_and_the_unmasked_one_named(ed):
    a = _masked(ed, Geometry(50, 50, 40, 20))
    b = _masked(ed, Geometry(100, 50, 40, 20))
    plain, = _add(ed, _image(Geometry(150, 50, 40, 20)))
    ed.set_selection([a.id, b.id, plain.id])
    msgs = []
    ed.statusMessage.connect(msgs.append)
    seen = []
    _answer(ed, 2.0, seen)
    n = ed.undo_stack.count()
    assert ed.path_ops.image_mask.feather()
    assert ed.undo_stack.count() == n + 1 and seen[0][2] == 2
    assert ed.document.shape(a.id).image.mask_feather > 0
    assert ed.document.shape(b.id).image.mask_feather > 0
    assert ed.document.shape(plain.id).image.mask_feather == 0.0
    assert "2 Bilder" in msgs[-1] and "1 Bild ohne Maske oder unverändert" in msgs[-1]
    assert set(ed.selection) == {a.id, b.id}


def test_wrong_selection_and_locked_layer(ed):
    plain, c = _add(ed, _image(), _circle())
    msgs = []
    ed.statusMessage.connect(msgs.append)
    _answer(ed, 2.0)
    n = ed.undo_stack.count()
    assert ed.path_ops.image_mask.feather() is False
    assert "erst „Maske auf Bild anwenden“" in msgs[-1]
    ed.set_selection([c.id])
    assert ed.path_ops.image_mask.feather() is False and msgs[-1].endswith("auswählen.")
    assert ed.undo_stack.count() == n
    ed.set_selection([plain.id, c.id])
    assert ed.path_ops.image_mask.apply()
    top = Layer("Foto")
    ed.document.add_layer(top)
    ed.document.shape(plain.id).layer_id = top.id
    ed.document.update_layer(top.id, locked=True)
    ed.selection = [plain.id]
    assert ed.path_ops.image_mask.feather() is False and "gesperrt" in msgs[-1]


def test_unchanged_width_only_notifies(ed):
    im = _masked(ed)
    _answer(ed, 2.0)
    assert ed.path_ops.image_mask.feather()
    msgs = []
    ed.statusMessage.connect(msgs.append)
    n = ed.undo_stack.count()
    assert ed.path_ops.image_mask.feather() is False
    assert ed.undo_stack.count() == n and "schon diese Breite" in msgs[-1]
    assert ed.document.shape(im.id).image.mask_feather == pytest.approx(5.0)


def test_release_after_feather_gives_a_hard_whole_image(ed):
    im = _masked(ed)
    _answer(ed, 2.0)
    assert ed.path_ops.image_mask.feather()
    assert ed.path_ops.image_mask.release()
    whole = ed.document.shape(im.id).image
    assert whole.mask == () and whole.mask_feather == 0.0


def test_dialog_preview_presets_and_readout(qapp):
    im = apply_mask(_image(value=30, w=400, h=200), [_circle()]).shape
    dlg = imagemask_ui.FeatherDialog(im, None, 3.0, count=2)
    try:
        assert dlg.value() == 3.0 and not dlg.preview.pixmap().isNull()
        assert "3 mm" in dlg.readout.text() and "30 Bildpunkte" in dlg.readout.text()
        assert "alle 2 ausgewählten Bilder" in dlg.readout.text()
        first = dlg.preview.pixmap().toImage()
        dlg.preset_buttons[0].click()
        assert dlg.value() == 0.0 and dlg.readout.text().startswith("Harte Kante")
        assert dlg.preview.pixmap().toImage() != first
        dlg.preset_buttons[-1].click()
        assert dlg.value() == 10.0
        assert [b.text() for b in dlg.preset_buttons] == ["hart", "2 mm", "5 mm", "10 mm"]
        assert dlg.width.maximum() == imagemask.FEATHER_RANGE_MM[1]
    finally:
        dlg.close()


def test_dialog_touch_targets(qapp):
    im = apply_mask(_image(), [_circle()]).shape
    dlg = imagemask_ui.FeatherDialog(im, None, 2.0, touch=True)
    try:
        dlg.show()
        qapp.processEvents()
        assert dlg.width.height() >= 44
        assert all(b.height() >= 44 for b in dlg.preset_buttons)
        assert all(b.height() >= 44 for b in dlg.buttons.buttons())
    finally:
        dlg.close()


def test_menus_tooltip_and_shortcut(ed):
    from PySide6.QtCore import QPointF
    a = ed.actions_by_name[imagemask_ui.FEATHER]
    assert a.text() == imagemask_ui.FEATHER_TEXT
    assert a.shortcut().toString() == imagemask_ui.FEATHER_SHORTCUT == "Ctrl+Alt+Shift+F"
    assert "Vignette" in a.toolTip() and "weiche Kante" in ed.path_ops_button.toolTip()
    texts = [x.text() for x in ed.path_ops_button.menu().actions() if x.text()]
    i = texts.index(imagemask_ui.APPLY_TEXT)
    assert texts[i:i + 4] == [imagemask_ui.APPLY_TEXT, imagemask_ui.HIDE_TEXT,
                              imagemask_ui.RELEASE_TEXT, imagemask_ui.FEATHER_TEXT]
    _add(ed, _image(), _circle())
    menu = ed.build_context_menu(QPointF(70, 60))
    sub = next(x.menu() for x in menu.actions() if x.menu() is not None
               and x.menu().objectName() == "PathOpsMenu")
    assert imagemask_ui.FEATHER_TEXT in [x.text() for x in sub.actions()]


def test_touch_mode_feather_row(ed, qapp):
    from PySide6.QtCore import QPointF
    _add(ed, _image(), _circle())
    ed.set_touch_mode(True, persist=False)
    try:
        menu = ed.build_context_menu(QPointF(70, 60))
        sub = next(x.menu() for x in menu.actions() if x.menu() is not None
                   and x.menu().objectName() == "PathOpsMenu")
        act = next(x for x in sub.actions() if x.text() == imagemask_ui.FEATHER_TEXT)
        sub.popup(ed.mapToGlobal(ed.rect().center()))
        qapp.processEvents()
        assert sub.actionGeometry(act).height() >= 44
        sub.close()
    finally:
        ed.set_touch_mode(False, persist=False)


def test_main_window_feather_shortcut_is_unique(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    try:
        owners = {a.text() for a in w.findChildren(QAction)
                  if a.shortcut() == QKeySequence(imagemask_ui.FEATHER_SHORTCUT)}
        assert owners == {imagemask_ui.FEATHER_TEXT}
        texts = [a.text() for a in w.import_tools.menu.actions()]
        i = texts.index(imagemask_ui.RELEASE_TEXT)
        assert texts[i + 1] == imagemask_ui.FEATHER_TEXT
        ed = w.canvas
        im = _masked(ed)
        _answer(ed, 1.0)
        ed.actions_by_name[imagemask_ui.FEATHER].trigger()
        assert ed.document.shape(im.id).image.mask_feather == pytest.approx(2.5)
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
