"""Mehrere Bildmasken (Runde 104): eine Maske auf ein schon maskiertes Bild verkleinert es auf
die Überschneidung, „Bereich im Bild ausblenden“ ist die umgekehrte Maske (Löcher), mehrere
Bilder bekommen dieselbe Form in einem Schritt – Rechnung, Auftrag, Datei, Lösen, Bedienung."""

from __future__ import annotations

import math
import re
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage

from lumacut_canvas import imagemask, imagemask_ui
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.imagecrop import decode_png, encode_png
from lumacut_canvas.imagemask import MaskError, apply_mask, combine_rings, release_mask
from lumacut_canvas.model import Document, Geometry, ImageSettings, Layer, RasterImage, Shape
from lumacut_canvas.workarea import to_machine
from lumacut_import.image import grayscale_png
from lumacut_job.images import image_job


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


def _circle(cx=70, cy=60, r=10, layer="L1"):
    return Shape("ellipse", Geometry(cx - r, cy - r, 2 * r, 2 * r), layer)


def _rect(x, y, w, h, layer="L1", rot=0.0):
    return Shape("rect", Geometry(x, y, w, h, rot), layer)


def _alpha(shape):
    _g, a = decode_png(shape.image.view_png)
    return np.ones(decode_png(shape.image.png)[0].shape, bool) if a is None else a > 0


def _px(x_mm, y_mm):
    """Pixel (row, col) of a canvas point on the default image 50..90 × 50..70 (2.5 px / mm)."""
    return int((y_mm - 50) * 2.5), int((x_mm - 50) * 2.5)


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

def test_first_mask_keeps_the_rings_unchanged(qapp):
    im = _image()
    rings = imagemask.mask_rings(im, [_circle()])
    assert combine_rings((), rings, "keep", 100, 50) == rings
    assert apply_mask(im, [_circle()]).shape.image.mask == rings      # round-100 masks identical


def test_unknown_mode(qapp):
    with pytest.raises(ValueError):
        apply_mask(_image(), [_circle()], "invert")
    with pytest.raises(ValueError):
        combine_rings((), (), "both", 10, 10)


def test_second_mask_narrows_to_the_overlap(qapp):
    first = apply_mask(_image(), [_circle()])
    second = apply_mask(first.shape, [_rect(50, 50, 20, 20)])     # left half of the circle
    a = _alpha(second.shape)
    assert a[_px(65, 60)] and not a[_px(75, 60)] and not a[_px(52, 52)]
    assert second.kept_share == pytest.approx(first.kept_share / 2, rel=0.06)
    assert second.shape.image.png == first.shape.image.png
    assert all(-1e-9 <= u <= 0.5 + 1e-6 for r in second.shape.image.mask for u, _v in r)


def test_keep_after_keep_is_symmetric(qapp):
    a = apply_mask(apply_mask(_image(), [_circle()]).shape, [_rect(50, 50, 20, 20)]).shape
    b = apply_mask(apply_mask(_image(), [_rect(50, 50, 20, 20)]).shape, [_circle()]).shape
    diff = int(np.count_nonzero(_alpha(a) != _alpha(b)))
    assert diff <= 4                                            # only rim pixels may flip


def test_hide_on_a_plain_image_is_the_inverse_mask(qapp):
    res = apply_mask(_image(), [_circle()], "hide")
    a = _alpha(res.shape)
    assert not a[_px(70, 60)] and a[_px(52, 52)] and a[_px(88, 68)]
    assert res.kept_share == pytest.approx(1 - math.pi * 100 / 800, abs=0.02)
    assert res.rings == 2                                      # image box + hole
    keep = _alpha(apply_mask(_image(), [_circle()]).shape)
    assert int(np.count_nonzero(a & keep)) <= 40               # complement up to the rim


def test_hide_punches_more_holes_into_a_mask(qapp):
    m = apply_mask(_image(), [_rect(52, 52, 36, 16)]).shape
    res = apply_mask(m, [_circle(r=4)], "hide")
    a = _alpha(res.shape)
    assert not a[_px(70, 60)] and a[_px(60, 60)] and not a[_px(51, 51)]
    two = apply_mask(res.shape, [_circle(58, 60, 2)], "hide")
    a2 = _alpha(two.shape)
    assert not a2[_px(58, 60)] and not a2[_px(70, 60)] and a2[_px(80, 60)]
    assert two.rings == 3 and two.kept_share < res.kept_share


def test_keep_after_hide_and_hide_after_keep_agree(qapp):
    a = apply_mask(apply_mask(_image(), [_circle(r=4)], "hide").shape, [_rect(55, 52, 30, 16)])
    b = apply_mask(apply_mask(_image(), [_rect(55, 52, 30, 16)]).shape, [_circle(r=4)], "hide")
    assert int(np.count_nonzero(_alpha(a.shape) != _alpha(b.shape))) <= 4
    assert not _alpha(a.shape)[_px(70, 60)] and _alpha(a.shape)[_px(58, 60)]


def test_hide_with_even_odd_shapes_hides_the_ring(qapp):
    res = apply_mask(_image(), [_rect(55, 52, 30, 16), _circle(r=5)], "hide")
    a = _alpha(res.shape)
    assert a[_px(70, 60)] and not a[_px(58, 60)] and a[_px(52, 52)]


def test_hide_text_takes_the_letters_out(qapp):
    text = Shape("text", Geometry(52, 50, 36, 20), "L1", text="O", font_family="DejaVu Sans")
    res = apply_mask(_image(), [text], "hide")
    a = _alpha(res.shape)
    assert a[_px(51, 51)] and not a.all()


@pytest.mark.parametrize("case, mode, text", [
    ("outside", "hide", "überdeckt das Bild nicht"),
    ("covers", "hide", "bliebe nichts übrig"),
    ("hidden_part", "keep", "sichtbaren Teil"),
    ("hidden_part", "hide", "sichtbaren Teil"),
    ("covers_visible", "keep", "ändert die Maske nicht"),
    ("disjoint_keep", "keep", "sichtbaren Teil"),
])
def test_errors(qapp, case, mode, text):
    im = _image()
    shapes = [_circle()]
    if case == "outside":
        shapes = [_circle(200, 200)]
    elif case == "covers":
        shapes = [_rect(40, 40, 60, 40)]
    elif case == "hidden_part":                     # mask on the left, shape on the right
        im = apply_mask(im, [_rect(50, 50, 15, 20)]).shape
        shapes = [_circle(80, 60, 5)]
    elif case == "covers_visible":
        im = apply_mask(im, [_circle()]).shape
        shapes = [_rect(55, 45, 30, 30)]
    elif case == "disjoint_keep":
        im = apply_mask(im, [_rect(50, 50, 15, 20)]).shape
        shapes = [_rect(70, 50, 20, 20)]
    with pytest.raises(MaskError, match=text):
        apply_mask(im, shapes, mode)


def test_existing_transparency_counts_as_hidden(qapp):
    png, w, h = _png()
    gray, _ = decode_png(png)
    alpha = np.full(gray.shape, 255, np.uint8)
    alpha[:, 50:] = 0                                    # right half already transparent
    im = Shape("image", Geometry(50, 50, 40, 20), "L1",
               image=RasterImage(encode_png(gray, alpha), w, h, ImageSettings()))
    with pytest.raises(MaskError, match="überdeckt das Bild nicht"):
        apply_mask(im, [_circle(80, 60, 4)], "hide")
    res = apply_mask(im, [_circle(60, 60, 4)], "hide")
    assert res.kept_share == pytest.approx(1 - math.pi * 100 / 2500, abs=0.03)


def test_mask_layer_of_the_first_mask_stays(qapp):
    m = apply_mask(_image(), [_circle(layer="A")]).shape
    n = apply_mask(m, [_rect(50, 50, 20, 20, layer="B")]).shape
    assert n.image.mask_layer == "A"
    h = apply_mask(_image(), [_circle(layer="C")], "hide").shape
    assert h.image.mask_layer == "C"


def test_rotated_image_narrowing_follows_the_image(qapp):
    im = _image(Geometry(50, 50, 40, 20, 30))
    m = apply_mask(im, [_circle(70, 60, 8)]).shape
    n = apply_mask(m, [_circle(70, 60, 4)], "hide").shape
    _w, outline = release_mask(n, "L1")
    b = outline.bounds()
    assert (b.x, b.y, b.w, b.h) == pytest.approx((62, 52, 16, 16), abs=0.05)
    assert len(outline.rings) == 1                       # outer circle + one hole
    moved = replace(n, geom=Geometry(150, 120, 40, 20, 30))
    assert moved.image.view_png == n.image.view_png


def test_release_of_a_combined_mask_reapplies_to_the_same_view(qapp):
    n = apply_mask(apply_mask(_image(), [_rect(52, 52, 36, 16)]).shape, [_circle(r=4)], "hide")
    whole, outline = release_mask(n.shape, "L1")
    assert whole.image.mask == () and outline.kind == "polygon"
    again = apply_mask(whole, [outline]).shape
    assert int(np.count_nonzero(_alpha(again) != _alpha(n.shape))) <= 4


def test_hidden_area_never_burns(qapp):
    im = _image(value=40, w=400, h=200, mode="jarvis", line_interval_mm=0.1)
    res = apply_mask(im, [_circle(r=6)], "hide").shape
    pts = _burned_points(image_job(res).lines)
    assert pts
    cx, cy = to_machine(70, 60)
    # burned segments may cross the hole only as travel – no burned point inside it
    assert min(math.hypot(x - cx, y - cy) for x, y in pts) >= 5.7
    assert len(image_job(res).lines) > 0


def test_document_gcode_with_hidden_area_is_pi_safe(qapp):
    from _pi_guard import pi_check
    from lumacut_job.planner import optimized_document_gcode
    doc = Document()
    lid = doc.active_layer_id
    im = _image(value=40, layer=lid, mode="floyd", line_interval_mm=0.2)
    m = apply_mask(im, [_rect(52, 52, 36, 16, layer=lid)]).shape
    doc.add_shape(apply_mask(m, [_circle(layer=lid, r=4)], "hide").shape)
    pi_check(optimized_document_gcode(doc))


def test_save_load_round_trip(qapp, tmp_path):
    from lumacut_canvas.document_io import load_into, save_document
    doc = Document()
    lid = doc.active_layer_id
    m = apply_mask(_image(layer=lid), [_rect(52, 52, 36, 16, layer=lid)]).shape
    n = apply_mask(m, [_circle(layer=lid, r=4)], "hide").shape
    doc.add_shape(n)
    p = save_document(doc, tmp_path / "h.lcut")
    back = Document()
    load_into(back, p)
    b = back.shape(n.id).image
    assert len(b.mask) == 2 and b.view_png == n.image.view_png


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


def test_hide_in_one_undo_step(ed):
    im, c = _add(ed, _image(), _circle(r=4))
    msgs = []
    ed.statusMessage.connect(msgs.append)
    n = ed.undo_stack.count()
    ed.actions_by_name[imagemask_ui.HIDE].trigger()
    assert ed.undo_stack.count() == n + 1
    assert not ed.document.has_shape(c.id) and len(ed.document.shape(im.id).image.mask) == 2
    assert ed.selection == [im.id] and msgs[-1].startswith("Bereich ausgeblendet: 9")
    ed.undo_stack.undo()
    assert ed.document.has_shape(c.id) and ed.document.shape(im.id).image.mask == ()


def test_second_apply_narrows_in_the_editor(ed):
    im, c = _add(ed, _image(), _circle())
    assert ed.path_ops.image_mask.apply()
    r = _rect(50, 50, 20, 20)
    r.layer_id = ed.document.active_layer_id
    ed.document.add_shape(r)
    ed.set_selection([im.id, r.id])
    first = ed.document.shape(im.id).image.mask
    n = ed.undo_stack.count()
    assert ed.path_ops.image_mask.apply() is True
    assert ed.undo_stack.count() == n + 1
    a = _alpha(ed.document.shape(im.id))
    assert a[_px(65, 60)] and not a[_px(75, 60)]
    ed.undo_stack.undo()
    assert ed.document.shape(im.id).image.mask == first and ed.document.has_shape(r.id)


@pytest.mark.parametrize("mode", ["keep", "hide"])
def test_several_images_in_one_step(ed, mode):
    a = _image(Geometry(50, 50, 40, 20))
    b = _image(Geometry(90, 50, 40, 20))
    c = _circle(90, 60, 8)                         # over the edge between both images
    _add(ed, a, b, c)
    msgs = []
    ed.statusMessage.connect(msgs.append)
    n = ed.undo_stack.count()
    assert ed.path_ops.image_mask.apply(mode) is True
    assert ed.undo_stack.count() == n + 1
    assert ed.document.shape(a.id).image.mask and ed.document.shape(b.id).image.mask
    assert set(ed.selection) == {a.id, b.id} and not ed.document.has_shape(c.id)
    verb = "ausgeblendet" if mode == "hide" else "maskiert"
    assert msgs[-1].startswith(f"2 Bilder {verb}")
    ed.undo_stack.undo()
    assert ed.document.shape(a.id).image.mask == () and ed.document.shape(b.id).image.mask == ()
    assert ed.document.has_shape(c.id)


def test_untouched_image_stays_and_is_named(ed):
    a = _image(Geometry(50, 50, 40, 20))
    far = _image(Geometry(200, 200, 40, 20))
    _add(ed, a, far, _circle())
    msgs = []
    ed.statusMessage.connect(msgs.append)
    assert ed.path_ops.image_mask.apply() is True
    assert ed.document.shape(a.id).image.mask and ed.document.shape(far.id).image.mask == ()
    assert msgs[-1].startswith("Maske angewandt:") and "1 Bild nicht berührt" in msgs[-1]
    assert ed.selection == [a.id]


def test_one_locked_image_refuses_all(ed):
    top = Layer("Foto")
    ed.document.add_layer(top)
    a, b, c = _add(ed, _image(Geometry(50, 50, 40, 20)), _image(Geometry(90, 50, 40, 20)),
                   _circle(90, 60, 8))
    ed.document.shape(b.id).layer_id = top.id
    ed.document.update_layer(top.id, locked=True)
    ed.selection = [a.id, b.id, c.id]
    msgs = []
    ed.statusMessage.connect(msgs.append)
    assert ed.path_ops.image_mask.hide() is False
    assert msgs[-1].startswith("Bereich ausblenden:") and "gesperrt" in msgs[-1]
    assert ed.document.shape(a.id).image.mask == ()


def test_hide_wrong_selection_only_notifies(ed):
    _im, c = _add(ed, _image(), _circle())
    ed.set_selection([c.id])
    msgs = []
    ed.statusMessage.connect(msgs.append)
    n = ed.undo_stack.count()
    assert ed.path_ops.image_mask.hide() is False
    assert ed.undo_stack.count() == n and msgs[-1].startswith("Bereich ausblenden:")


def test_release_after_hide_gives_box_with_hole(ed):
    im, _c = _add(ed, _image(), _circle(r=4))
    assert ed.path_ops.image_mask.hide()
    assert ed.path_ops.image_mask.release()
    out = [ed.document.shape(i) for i in ed.selection if i != im.id]
    assert len(out) == 1 and len(out[0].rings) == 1
    b = out[0].bounds()
    assert (b.x, b.y, b.w, b.h) == pytest.approx((50, 50, 40, 20), abs=1e-6)
    assert ed.document.shape(im.id).image.mask == ()


def test_hide_tooltip_shortcut_and_menus(ed):
    from PySide6.QtCore import QPointF
    a = ed.actions_by_name[imagemask_ui.HIDE]
    assert a.text() == imagemask_ui.HIDE_TEXT
    assert a.shortcut().toString() == imagemask_ui.HIDE_SHORTCUT == "Ctrl+Alt+Shift+H"
    assert "Umgekehrte Maske" in a.toolTip() and "Überschneidung" in \
        ed.actions_by_name[imagemask_ui.APPLY].toolTip()
    assert "Bereich ausblenden" in ed.path_ops_button.toolTip()
    _add(ed, _image(), _circle())
    menu = ed.build_context_menu(QPointF(70, 60))
    sub = next(x.menu() for x in menu.actions() if x.menu() is not None
               and x.menu().objectName() == "PathOpsMenu")
    names = [x.text() for x in sub.actions()]
    i = names.index(imagemask_ui.APPLY_TEXT)
    assert names[i:i + 3] == [imagemask_ui.APPLY_TEXT, imagemask_ui.HIDE_TEXT,
                              imagemask_ui.RELEASE_TEXT]


def test_touch_mode_hide_row(ed, qapp):
    from PySide6.QtCore import QPointF
    _add(ed, _image(), _circle())
    ed.set_touch_mode(True, persist=False)
    try:
        menu = ed.build_context_menu(QPointF(70, 60))
        sub = next(x.menu() for x in menu.actions() if x.menu() is not None
                   and x.menu().objectName() == "PathOpsMenu")
        act = next(x for x in sub.actions() if x.text() == imagemask_ui.HIDE_TEXT)
        sub.popup(ed.mapToGlobal(ed.rect().center()))
        qapp.processEvents()
        assert sub.actionGeometry(act).height() >= 44
        sub.close()
    finally:
        ed.set_touch_mode(False, persist=False)


def test_main_window_hide_shortcut_is_unique(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    try:
        owners = {a.text() for a in w.findChildren(QAction)
                  if a.shortcut() == QKeySequence(imagemask_ui.HIDE_SHORTCUT)}
        assert owners == {imagemask_ui.HIDE_TEXT}
        assert imagemask_ui.HIDE_TEXT in [a.text() for a in w.import_tools.menu.actions()]
        ed = w.canvas
        im, _c = _add(ed, _image(), _circle(r=4))
        ed.actions_by_name[imagemask_ui.HIDE].trigger()
        assert len(ed.document.shape(im.id).image.mask) == 2
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
