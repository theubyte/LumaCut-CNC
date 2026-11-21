"""Live-Bildmaske (LightBurn *Apply Mask to Image* / *Remove Mask*): Maske normiert auf das
Bild, Original-Pixel bleiben, Auftrag / Vorschau / Export / Datei, Lösen, Bedienung."""

from __future__ import annotations

import json
import math
import re
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage

from _pi_guard import pi_check
from lumacut_canvas import imagemask, imagemask_ui
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.imagecrop import crop_image, decode_png
from lumacut_canvas.imagemask import MaskError, apply_mask, release_mask
from lumacut_canvas.model import Document, Geometry, ImageSettings, Layer, RasterImage, Shape
from lumacut_canvas.workarea import to_machine
from lumacut_import.image import grayscale_png
from lumacut_job.images import alpha_qimage, image_job, render_gray, render_inside

FAMILY = "DejaVu Sans"


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


def _settings(shape, **settings):
    return replace(shape, image=replace(shape.image, settings=ImageSettings(**settings)))


def _masked(im=None, mask=None):
    return apply_mask(im or _image(), [mask or _circle()]).shape


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


# --- Maske --------------------------------------------------------------------------------------

def test_plain_image_view_is_the_png(qapp):
    im = _image()
    assert im.image.mask == () and im.image.view_png is im.image.png


def test_apply_keeps_the_pixels_and_the_box(qapp):
    im = _image()
    res = apply_mask(im, [_circle()])
    out = res.shape
    assert out.id == im.id and out.geom.as_tuple() == im.geom.as_tuple()
    assert out.image.png == im.image.png and out.image.px_width == 100
    assert out.image.mask_layer == "L1" and res.rings == 1 and res.points >= 64
    assert res.kept_share == pytest.approx(math.pi * 100 / 800, abs=0.02)
    for u, v in out.image.mask[0]:          # circle 60..80 × 50..70 on the image 50..90 × 50..70
        assert 0.25 - 1e-6 <= u <= 0.75 + 1e-6 and -1e-6 <= v <= 1 + 1e-6


def test_view_matches_the_destructive_crop(qapp):
    im = _image()
    g, a = decode_png(_masked(im).image.view_png)
    assert g.shape == (50, 100) and a is not None
    cropped = crop_image(im, [_circle()])
    cg, ca = decode_png(cropped.shape.image.png)
    # same pixel-centre rule; the flattened outline may flip a few pixels sitting on the rim
    assert int(np.count_nonzero(a)) == pytest.approx(int(np.count_nonzero(ca)), rel=0.02)
    assert g[25, 50] == decode_png(im.image.png)[0][25, 50]
    assert g[0, 0] == 255 and a[0, 0] == 0


def test_even_odd_ring_and_text_counters(qapp):
    rect = Shape("rect", Geometry(55, 52, 30, 16), "L1")
    ring = apply_mask(_image(), [rect, _circle(r=5)]).shape
    _g, a = decode_png(ring.image.view_png)
    assert a[25, 50] == 0 and a[25, 20] == 255 and a[0, 0] == 0   # hole / ring / outside
    assert len(ring.image.mask) == 2
    text = Shape("text", Geometry(52, 50, 36, 20), "L1", text="O", font_family=FAMILY)
    o = apply_mask(_image(), [text]).shape
    _g, a = decode_png(o.image.view_png)
    assert len(o.image.mask) >= 2 and a[25, 50] == 0 and (a > 0).any()


def test_mask_moves_and_scales_with_the_image(qapp):
    m = _masked()
    moved = replace(m, geom=Geometry(150, 120, 80, 40))
    assert moved.image.view_png == m.image.view_png         # same pixels masked
    _whole, outline = release_mask(moved, "L1")
    b = outline.geom
    assert (b.x, b.y, b.w, b.h) == pytest.approx((170, 120, 40, 40), abs=1e-6)


def test_rotated_image_gives_the_shape_back_where_it_was(qapp):
    im = _image(Geometry(50, 50, 40, 20, 30))
    c = _circle(68, 61, 6)
    m = apply_mask(im, [c]).shape
    _whole, outline = release_mask(m, "L1")
    b = outline.bounds()
    assert (b.x, b.y, b.w, b.h) == pytest.approx((62, 55, 12, 12), abs=0.02)


def test_rotated_mask_shape(qapp):
    rect = Shape("rect", Geometry(60, 55, 20, 10, 45), "L1")
    m = apply_mask(_image(), [rect]).shape
    _w, outline = release_mask(m, "L1")
    ob, rb = outline.bounds(), rect.bounds()
    assert (ob.x, ob.y, ob.w, ob.h) == pytest.approx((rb.x, rb.y, rb.w, rb.h), abs=1e-6)


def test_release_restores_the_whole_image(qapp):
    im = _image()
    m = _masked(im)
    whole, outline = release_mask(m, "L2")
    assert whole.image == im.image and whole.image.view_png == im.image.png
    assert outline.kind == "polygon" and outline.layer_id == "L2" and outline.id != im.id
    b = outline.bounds()
    assert (b.x, b.y, b.w, b.h) == pytest.approx((60, 50, 20, 20), abs=1e-6)


def test_release_keeps_all_rings_and_groups(qapp):
    rect = Shape("rect", Geometry(55, 52, 30, 16), "L1")
    im = replace(_image(), groups=("g1",))
    m = apply_mask(im, [rect, _circle(r=5)]).shape
    _w, outline = release_mask(m, "L1")
    assert len(outline.rings) == 1 and outline.groups == ("g1",)


@pytest.mark.parametrize("case, text", [
    ("no_mask", "geschlossene Form"),
    ("outside", "überdeckt das Bild nicht"),
    ("covers", "ganze Bild"),
    ("twice", "ändert die Maske nicht"),
    ("open", "geschlossene Form"),
])
def test_errors(qapp, case, text):
    im = _image()
    shapes = [_circle()]
    if case == "no_mask":
        shapes = []
    elif case == "outside":
        shapes = [_circle(200, 200)]
    elif case == "covers":
        shapes = [Shape("rect", Geometry(40, 40, 60, 40), "L1")]
    elif case == "twice":
        im = _masked()
    elif case == "open":
        shapes = [Shape.from_points("path", [(55, 55), (85, 65)], "L1")]
    with pytest.raises(MaskError, match=text):
        apply_mask(im, shapes)
    with pytest.raises(MaskError):
        release_mask(_image(), "L1")


def test_crop_of_a_masked_image_bakes_the_mask(qapp):
    m = _masked()
    rect = Shape("rect", Geometry(50, 50, 20, 20), "L1")    # left half of the circle stays
    res = crop_image(m, [rect])
    assert res.shape.image.mask == () and res.px == (25, 50)
    _g, a = decode_png(res.shape.image.png)
    assert a[0, 24] == 255 and a[0, 0] == 0


# --- Auftrag / Vorschau / Export ----------------------------------------------------------------

@pytest.mark.parametrize("settings", [{"mode": "threshold"}, {"mode": "floyd"},
                                      {"mode": "grayscale"}, {"mode": "sketch"},
                                      {"mode": "jarvis", "brightness": -40, "contrast": 20}])
def test_masked_pixels_never_burn(qapp, settings):
    m = _settings(_masked(_image(value=40, w=400, h=200)), line_interval_mm=0.1, **settings)
    pts = _burned_points(image_job(m).lines)
    assert pts
    cx, cy = to_machine(70, 60)
    assert max(math.hypot(x - cx, y - cy) for x, y in pts) <= 10.3


def test_job_shrinks_and_plain_job_is_unchanged(qapp):
    im = _settings(_image(value=40), line_interval_mm=0.2)
    before = image_job(im).lines
    m = _masked(im)
    assert len(image_job(m).lines) < len(before)
    assert image_job(release_mask(m, "L1")[0]).lines == before


def test_inside_mask_and_render_follow_the_mask(qapp):
    m = _settings(_masked(_image(value=40)), line_interval_mm=0.2)
    ins = render_inside(m, 0.2)
    gray, _ = render_gray(m, 0.2)
    assert ins is not None and ins.shape == gray.shape
    assert not ins[0, 0] and ins[50, 100] and gray[0, 0] == 255 and gray[50, 100] < 128
    assert alpha_qimage(m) is not None and alpha_qimage(_image()) is None


def test_document_gcode_with_a_masked_image_is_pi_safe(qapp):
    from lumacut_job.planner import optimized_document_gcode
    doc = Document()
    lid = doc.active_layer_id
    im = _image(value=40, layer=lid, mode="jarvis", line_interval_mm=0.2, brightness=-20)
    doc.add_shape(apply_mask(im, [_circle(layer=lid)]).shape)
    pi_check(optimized_document_gcode(doc))


def test_png_export_and_dialog_preview(qapp, tmp_path):
    from lumacut_canvas.export import export_png
    from lumacut_import.image_preview import preview_shape
    doc = Document()
    m = _masked(_image(value=40, layer=doc.active_layer_id))
    doc.add_shape(m)
    img = export_png(doc, tmp_path / "a.png", px_per_mm=4)
    assert QColor(img.pixel(int(60.5 * 4), int(50.5 * 4))).red() == 255
    assert QColor(img.pixel(70 * 4, 60 * 4)).red() < 60
    pv = preview_shape(m, ImageSettings(mode="threshold", line_interval_mm=0.2))
    assert pv.pixels[0, 0] == 255 and pv.pixels[50, 100] < 128


def test_trace_sees_the_masked_part_as_white(qapp):
    from lumacut_import.trace import decode_gray
    g = decode_gray(_masked(_image(value=40)).image.view_png)
    assert g[0, 0] == 255 and g[25, 50] == 40


def test_save_load_round_trip(qapp, tmp_path):
    from lumacut_canvas.document_io import load_into, save_document
    doc = Document()
    plain = _image(layer=doc.active_layer_id)
    assert "mask" not in plain.image.to_dict() and "mask_layer" not in plain.image.to_dict()
    m = _masked(plain, _circle(layer=plain.layer_id))
    doc.add_shape(m)
    d = json.loads(json.dumps(doc.to_dict()))
    img = next(s for s in d["objects"] if s["id"] == m.id)["image"]
    assert img["mask_layer"] == plain.layer_id and len(img["mask"]) == 1
    p = save_document(doc, tmp_path / "m.lcut")
    back = Document()
    load_into(back, p)
    b = back.shape(m.id).image
    assert b.mask == m.image.mask and b.png == plain.image.png
    assert b.view_png == m.image.view_png


def test_from_dict_ignores_broken_rings(qapp):
    d = _image().image.to_dict()
    d["mask"] = [[[0, 0], [1, 1]]]
    d["mask_layer"] = "x"
    r = RasterImage.from_dict(d)
    assert r.mask == () and r.mask_layer == ""


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


def _setup(ed, mask=None):
    lid = ed.document.active_layer_id
    im = _image(layer=lid)
    m = mask or _circle(layer=lid)
    m.layer_id = lid
    ed.document.add_shape(im)
    ed.document.add_shape(m)
    ed.set_selection([im.id, m.id])
    return im, m


def test_apply_in_one_undo_step(ed):
    im, m = _setup(ed)
    msgs = []
    ed.statusMessage.connect(msgs.append)
    n = ed.undo_stack.count()
    assert ed.path_ops.image_mask.apply() is True
    assert ed.undo_stack.count() == n + 1
    assert not ed.document.has_shape(m.id) and ed.document.shape(im.id).image.mask
    assert ed.selection == [im.id] and msgs[-1].startswith("Maske angewandt: 4")
    ed.undo_stack.undo()
    assert ed.document.has_shape(m.id) and ed.document.shape(im.id).image.mask == ()
    ed.undo_stack.redo()
    assert not ed.document.has_shape(m.id) and ed.document.shape(im.id).image.mask


def test_release_in_one_undo_step_on_the_mask_layer(ed):
    top = Layer("Maske")
    ed.document.add_layer(top)
    im, m = _setup(ed)
    ed.document.shape(m.id).layer_id = top.id
    ed.set_selection([im.id, m.id])
    assert ed.path_ops.image_mask.apply()
    n = ed.undo_stack.count()
    assert ed.path_ops.image_mask.release() is True
    assert ed.undo_stack.count() == n + 1
    assert ed.document.shape(im.id).image.mask == ()
    new = [ed.document.shape(i) for i in ed.selection if i != im.id]
    assert len(new) == 1 and new[0].kind == "polygon" and new[0].layer_id == top.id
    b = new[0].bounds()
    assert (b.x, b.y, b.w, b.h) == pytest.approx((60, 50, 20, 20), abs=1e-6)
    ed.undo_stack.undo()
    assert ed.document.shape(im.id).image.mask and not ed.document.has_shape(new[0].id)


def test_release_falls_back_to_the_image_layer(ed):
    im, _m = _setup(ed)
    assert ed.path_ops.image_mask.apply()
    s = ed.document.shape(im.id)
    ed.document.shapes[ed.document.shapes.index(s)] = replace(
        s, image=replace(s.image, mask_layer="gone"))
    ed.set_selection([im.id])
    assert ed.path_ops.image_mask.release()
    new = [ed.document.shape(i) for i in ed.selection if i != im.id]
    assert new[0].layer_id == im.layer_id


@pytest.mark.parametrize("what", ["no_image", "no_mask", "two_images_untouched"])
def test_wrong_selection_only_notifies(ed, what):
    im, m = _setup(ed)
    if what == "no_image":
        ed.set_selection([m.id])
    elif what == "no_mask":
        ed.set_selection([im.id])
    else:       # since round 104 several images are fine – but the shape touches neither
        other = _image(Geometry(150, 150, 40, 20), layer=ed.document.active_layer_id)
        ed.document.add_shape(other)
        ed.document.shape(m.id).geom = Geometry(300, 300, 20, 20)
        ed.set_selection([im.id, other.id, m.id])
    msgs = []
    ed.statusMessage.connect(msgs.append)
    n = ed.undo_stack.count()
    assert ed.path_ops.image_mask.apply() is False
    assert ed.undo_stack.count() == n and msgs[-1].startswith("Bildmaske:")
    assert ed.path_ops.image_mask.release() is False
    assert msgs[-1].startswith("Bildmaske lösen:")


def test_locked_layers_are_left_alone(ed):
    top = Layer("Maske")
    ed.document.add_layer(top)
    im, m = _setup(ed)
    ed.document.shape(m.id).layer_id = top.id
    ed.document.update_layer(top.id, locked=True)
    ed.selection = [im.id, m.id]
    msgs = []
    ed.statusMessage.connect(msgs.append)
    assert ed.path_ops.image_mask.apply() is False and "gesperrt" in msgs[-1]
    ed.document.update_layer(top.id, locked=False)
    ed.document.update_layer(im.layer_id, locked=True)
    ed.selection = [im.id, m.id]
    assert ed.path_ops.image_mask.apply() is False and "gesperrt" in msgs[-1]
    assert ed.document.shape(im.id).image.mask == ()


def test_canvas_item_shows_the_masked_image(ed, qapp):
    im, _m = _setup(ed)
    ed.actions_by_name["image_mask"].trigger()
    qapp.processEvents()
    item = next(i for i in ed.scene.items() if getattr(i, "shape_id", None) == im.id)
    assert item._png == ed.document.shape(im.id).image.view_png != im.image.png
    assert item.boundingRect().width() >= 40          # the box stays
    ed.actions_by_name["image_mask_release"].trigger()
    qapp.processEvents()
    assert item._png == im.image.png


def test_actions_in_path_menu_and_context_menu(ed):
    from PySide6.QtCore import QPointF
    from lumacut_canvas import imagecrop_ui
    _setup(ed)
    texts = [a.text() for a in ed.path_ops_button.menu().actions() if a.text()]
    i = texts.index(imagecrop_ui.TEXT)
    assert texts[i + 1:i + 4] == [imagemask_ui.APPLY_TEXT, imagemask_ui.HIDE_TEXT,
                                  imagemask_ui.RELEASE_TEXT]
    menu = ed.build_context_menu(QPointF(70, 60))
    sub = next(a.menu() for a in menu.actions() if a.menu() is not None
               and a.menu().objectName() == "PathOpsMenu")
    names = [a.text() for a in sub.actions()]
    assert imagemask_ui.APPLY_TEXT in names and imagemask_ui.RELEASE_TEXT in names


def test_tooltip_and_shortcut(ed):
    a = ed.actions_by_name["image_mask"]
    assert a.shortcut().toString() == "Ctrl+Alt+Shift+M"
    assert "Apply Mask to Image" in a.toolTip()
    assert "Remove Mask" in ed.actions_by_name["image_mask_release"].toolTip()
    assert "Maske auf Bild" in ed.path_ops_button.toolTip()


def test_touch_mode_context_menu_rows(ed, qapp):
    from PySide6.QtCore import QPointF
    _setup(ed)
    ed.set_touch_mode(True, persist=False)
    try:
        menu = ed.build_context_menu(QPointF(70, 60))
        sub = next(a.menu() for a in menu.actions() if a.menu() is not None
                   and a.menu().objectName() == "PathOpsMenu")
        act = next(a for a in sub.actions() if a.text() == imagemask_ui.APPLY_TEXT)
        sub.popup(ed.mapToGlobal(ed.rect().center()))
        qapp.processEvents()
        assert sub.actionGeometry(act).height() >= 44
        sub.close()
    finally:
        ed.set_touch_mode(False, persist=False)


def test_main_window_shortcut_is_unique_and_in_the_file_menu(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    from lumacut_canvas import imagecrop_ui
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    try:
        owners = {a.text() for a in w.findChildren(QAction)
                  if a.shortcut() == QKeySequence(imagemask_ui.SHORTCUT)}
        assert owners == {imagemask_ui.APPLY_TEXT}
        texts = [a.text() for a in w.import_tools.menu.actions()]
        i = texts.index(imagecrop_ui.TEXT)
        assert texts[i + 1:i + 4] == [imagemask_ui.APPLY_TEXT, imagemask_ui.HIDE_TEXT,
                                      imagemask_ui.RELEASE_TEXT]
        ed = w.canvas
        im, _m = _setup(ed)
        ed.actions_by_name["image_mask"].trigger()
        assert ed.document.shape(im.id).image.mask
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
