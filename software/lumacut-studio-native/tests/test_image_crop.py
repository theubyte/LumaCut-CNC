"""Bild mit Form zuschneiden (LightBurn *Tools › Crop Image*, xTool „Zuschneiden“): Maske aus
geschlossenen Formen, Alpha-PNG, neue Box, Auftrag / Vorschau / Export / Datei, Bedienung."""

from __future__ import annotations

import json
import math
import re

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage

from _pi_guard import pi_check
from lumacut_canvas import imagecrop, imagecrop_ui
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.imagecrop import CropError, crop_image, decode_png, encode_png
from lumacut_canvas.model import Document, Geometry, ImageSettings, RasterImage, Shape
from lumacut_canvas.workarea import to_machine
from lumacut_import.image import grayscale_png
from lumacut_job.images import (alpha_qimage, image_job, raster_settings, render_gray,
                                render_gray_frame, render_inside, render_inside_frame,
                                scan_geometry)
from lumacut_job.raster import power_map

FAMILY = "DejaVu Sans"


def _png(w=100, h=50, value=None):
    """Grey test picture: gradient left → right (or a flat ``value``)."""
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


def _with_settings(shape, **settings):
    s = shape.copy()
    s.image = RasterImage(s.image.png, s.image.px_width, s.image.px_height,
                          ImageSettings(**settings))
    return s


# --- PNG ----------------------------------------------------------------------------------------

def test_encode_png_grey_round_trip(qapp):
    g = np.arange(60, dtype=np.uint8).reshape(6, 10) * 4
    png = encode_png(g)
    back, alpha = decode_png(png)
    assert alpha is None and np.array_equal(back, g)
    assert not QImage.fromData(png).hasAlphaChannel()


def test_encode_png_grey_alpha_round_trip(qapp):
    import cv2
    g = np.full((5, 7), 90, np.uint8)
    a = np.zeros((5, 7), np.uint8)
    a[1:4, 2:6] = 255
    png = encode_png(g, a)
    back, alpha = decode_png(png)
    assert np.array_equal(back, g) and np.array_equal(alpha, a)
    raw = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    assert raw.shape == (5, 7, 4) and np.array_equal(raw[..., 3], a)


def test_imported_images_have_no_alpha(qapp):
    assert alpha_qimage(_image()) is None
    assert decode_png(_image().image.png)[1] is None


# --- Zuschneiden --------------------------------------------------------------------------------

def test_rectangle_on_the_pixel_grid_gives_a_plain_crop(qapp):
    im = _image()                      # 100 × 50 px on 40 × 20 mm = 0.4 mm per pixel
    rect = Shape("rect", Geometry(54, 52, 12, 8), "L1")     # px 10..40 × 5..25
    res = crop_image(im, [rect])
    assert res.px == (30, 20) and not res.transparent
    g = res.shape.geom
    assert (g.x, g.y, g.w, g.h, g.rot) == pytest.approx((54, 52, 12, 8, 0))
    old, _ = decode_png(im.image.png)
    new, alpha = decode_png(res.shape.image.png)
    assert alpha is None and np.array_equal(new, old[5:25, 10:40])
    assert res.kept_share == pytest.approx(600 / 5000)
    assert res.shape.image.dpi(g.w) == pytest.approx(im.image.dpi(im.geom.w))


def test_ellipse_makes_the_outside_transparent_and_white(qapp):
    res = crop_image(_image(), [_circle()])
    assert res.transparent and res.px == (50, 50)
    assert (res.shape.geom.x, res.shape.geom.y, res.shape.geom.w, res.shape.geom.h) == \
        pytest.approx((60, 50, 20, 20))
    gray, alpha = decode_png(res.shape.image.png)
    assert set(np.unique(alpha)) == {0, 255}
    assert alpha[0, 0] == 0 and alpha[25, 25] == 255 and gray[0, 0] == 255
    old, _ = decode_png(_image().image.png)
    inside = alpha == 255
    assert np.array_equal(gray[inside], old[:, 25:75][inside])
    assert alpha.mean() / 255 == pytest.approx(math.pi / 4, abs=0.02)
    assert res.kept_share == pytest.approx(math.pi * 100 / 800, abs=0.01)


def test_crop_keeps_id_layer_groups_and_settings(qapp):
    im = _image(mode="jarvis", power=40, negative=True)
    im.groups = ("g1",)
    res = crop_image(im, [_circle()])
    s = res.shape
    assert (s.id, s.layer_id, s.groups) == (im.id, im.layer_id, im.groups)
    assert s.image.settings == im.image.settings
    assert im.image.px_width == 100      # original untouched


def test_mask_part_outside_the_image_is_clipped(qapp):
    big = Shape("rect", Geometry(30, 40, 30, 50), "L1")     # covers the left quarter
    res = crop_image(_image(), [big])
    assert res.px == (25, 50) and not res.transparent
    assert res.shape.geom.as_tuple() == pytest.approx((50, 50, 10, 20))


def test_nested_shapes_combine_even_odd_to_a_ring(qapp):
    outer = Shape("rect", Geometry(55, 50, 30, 20), "L1")
    hole = _circle(70, 60, 5)
    res = crop_image(_image(), [outer, hole])
    gray, alpha = decode_png(res.shape.image.png)
    cy, cx = alpha.shape[0] // 2, alpha.shape[1] // 2
    assert alpha[cy, cx] == 0 and gray[cy, cx] == 255 and alpha[2, 2] == 255


def test_text_mask_keeps_letters_and_counters(qapp):
    from lumacut_canvas.shape_paths import text_path
    if text_path("WW", FAMILY).boundingRect().width() <= text_path("Il", FAMILY).boundingRect().width() * 1.05:
        pytest.skip("Keine echten Schriften auf diesem System")
    txt = Shape("text", Geometry(52, 51, 36, 18), "L1", text="O", font_family=FAMILY)
    res = crop_image(_image(), [txt])
    gray, alpha = decode_png(res.shape.image.png)
    h, w = alpha.shape
    assert alpha[h // 2, w // 2] == 0            # counter of the O
    assert 0.1 < (alpha > 0).mean() < 0.8


def test_rotated_image_with_an_aligned_rotated_rectangle(qapp):
    im = _image(Geometry(50, 50, 40, 20, 30.0))
    rect = Shape("rect", Geometry(54, 52, 12, 8, 0.0), "L1")
    # Same rectangle in the image's own (rotated) frame: rotate it about the image centre.
    from lumacut_canvas.model import rotate_point
    cx, cy = im.geom.center()
    rcx, rcy = rotate_point(60, 56, cx, cy, 30.0)
    rect.geom = Geometry(rcx - 6, rcy - 4, 12, 8, 30.0)
    res = crop_image(im, [rect])
    assert res.px == (30, 20) and not res.transparent
    got = res.shape.geom.corner_points()
    want = rect.geom.corner_points()
    assert np.allclose(got, want, atol=1e-6)


def test_rotated_mask_on_unrotated_image(qapp):
    diamond = Shape("rect", Geometry(63, 53, 14, 14, 45.0), "L1")
    res = crop_image(_image(), [diamond])
    _g, alpha = decode_png(res.shape.image.png)
    assert res.transparent and alpha[0, 0] == 0 and alpha[alpha.shape[0] // 2, alpha.shape[1] // 2] == 255


def test_second_crop_combines_with_the_first(qapp):
    first = crop_image(_image(), [_circle()]).shape
    half = Shape("rect", Geometry(60, 50, 10, 20), "L1")     # left half of the circle
    res = crop_image(first, [half])
    gray, alpha = decode_png(res.shape.image.png)
    assert res.px == (25, 50) and alpha[0, 0] == 0 and alpha[25, 20] == 255
    assert res.kept_share == pytest.approx(0.5, abs=0.03)


@pytest.mark.parametrize("shapes, text", [
    ([], "geschlossene Form"),
    ([Shape("line", Geometry(50, 50, 10, 10), "L1")], "geschlossene Form"),
    ([Shape("rect", Geometry(200, 200, 10, 10), "L1")], "überdeckt das Bild nicht"),
    ([Shape("rect", Geometry(40, 40, 60, 40), "L1")], "ganze Bild"),
])
def test_errors(qapp, shapes, text):
    with pytest.raises(CropError, match=text):
        crop_image(_image(), shapes)


def test_error_for_cropped_image_already_inside_the_mask(qapp):
    first = crop_image(_image(), [_circle()]).shape
    with pytest.raises(CropError, match="sichtbaren Teil"):
        crop_image(first, [_circle(r=12)])


def test_error_for_non_image(qapp):
    with pytest.raises(CropError, match="Bild"):
        crop_image(_circle(), [_circle()])


def test_mask_kinds():
    assert set(imagecrop.MASK_KINDS) == {"rect", "ellipse", "polygon", "text"}
    shapes = [_circle(), Shape("line", Geometry(0, 0, 5, 5), "L1"), _image()]
    assert [s.kind for s in imagecrop.mask_shapes(shapes)] == ["ellipse"]


# --- Auftrag ------------------------------------------------------------------------------------

def _burned_points(lines):
    """End points of the burning ``G1`` moves (S > 0) and the start of each."""
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


@pytest.mark.parametrize("value, settings", [
    (40, {"mode": "threshold"}),
    (40, {"mode": "floyd"}),
    (40, {"mode": "grayscale"}),
    (220, {"mode": "threshold", "negative": True}),
    (220, {"mode": "grayscale", "negative": True}),
    (40, {"mode": "jarvis", "brightness": -40, "contrast": 20}),
    (40, {"mode": "sketch"}),
    (120, {"mode": "halftone"}),
])
def test_transparent_pixels_never_burn(qapp, value, settings):
    # 0.1 mm source pixels: the smooth resampling may blend at most about one pixel at the rim.
    cropped = crop_image(_image(value=value, w=400, h=200), [_circle()]).shape
    s = _with_settings(cropped, line_interval_mm=0.1, **settings)
    lines = image_job(s).lines
    pts = _burned_points(lines)
    assert pts, "the circle itself is engraved"
    cx, cy = to_machine(70, 60)
    # Halftone dots sit in the centre of their screen cell, so a cell cut by the rim may
    # place its dot up to about half a cell outside (same at the box edge of any image).
    tol = 0.6 if settings["mode"] == "halftone" else 0.3
    assert max(math.hypot(x - cx, y - cy) for x, y in pts) <= 10 + tol


def test_document_gcode_with_a_cropped_image_is_pi_safe(qapp):
    from lumacut_job.planner import optimized_document_gcode
    doc = Document()
    im = _image(value=40, layer=doc.active_layer_id, mode="jarvis", line_interval_mm=0.2,
                brightness=-20)
    doc.add_shape(crop_image(im, [_circle(layer=doc.active_layer_id)]).shape)
    pi_check(optimized_document_gcode(doc))


def test_inside_mask_follows_the_alpha(qapp):
    cropped = _with_settings(crop_image(_image(), [_circle()]).shape, line_interval_mm=0.2)
    ins = render_inside(cropped, 0.2)
    gray, _ = render_gray(cropped, 0.2)
    assert ins is not None and ins.shape == gray.shape
    assert not ins[0, 0] and ins[50, 50]
    assert ins.mean() == pytest.approx(math.pi / 4, abs=0.03)
    assert render_inside(_image(), 0.2) is None         # unchanged for plain images


def test_render_gray_outside_is_the_no_burn_value(qapp):
    cropped = crop_image(_image(value=40), [_circle()]).shape
    for neg, outside in ((False, 255), (True, 0)):
        gray, _ = render_gray(_with_settings(cropped, negative=neg), 0.1)
        assert gray[0, 0] == outside and gray[100, 100] == 40


def test_scan_angle_keeps_transparent_pixels_unburned(qapp):
    cropped = _with_settings(crop_image(_image(value=40, w=400, h=200), [_circle()]).shape,
                             line_interval_mm=0.1, mode="threshold", scan_angle=45.0, brightness=-10)
    geo = scan_geometry(cropped, 45.0, 0.1)
    gray = render_gray_frame(cropped, geo)
    inside = render_inside_frame(cropped, geo)
    pm = power_map(gray, raster_settings(cropped), inside=inside)
    assert pm[inside].any() and not pm[~inside].any()
    pts = _burned_points(image_job(cropped).lines)
    cx, cy = to_machine(70, 60)
    assert pts and max(math.hypot(x - cx, y - cy) for x, y in pts) <= 10 + 0.3


def test_rotated_cropped_image_burns_only_inside(qapp):
    im = _image(Geometry(50, 50, 40, 20, 25.0), value=40, w=400, h=200)
    cropped = _with_settings(crop_image(im, [_circle()]).shape, line_interval_mm=0.1,
                             mode="threshold", contrast=10)
    pts = _burned_points(image_job(cropped).lines)
    cx, cy = to_machine(70, 60)
    assert pts and max(math.hypot(x - cx, y - cy) for x, y in pts) <= 10 + 0.3


def test_depth3d_keeps_transparent_pixels_unburned(qapp):
    cropped = _with_settings(crop_image(_image(value=40, w=400, h=200), [_circle()]).shape,
                             line_interval_mm=0.2, mode="depth3d", depth_levels=4)
    pts = _burned_points(image_job(cropped).lines)
    cx, cy = to_machine(70, 60)
    assert pts and max(math.hypot(x - cx, y - cy) for x, y in pts) <= 10 + 0.4


def test_job_gets_shorter(qapp):
    im = _with_settings(_image(value=40), line_interval_mm=0.2, mode="threshold")
    cropped = crop_image(im, [_circle()]).shape
    from lumacut_job.estimate import estimate_gcode
    t_full = estimate_gcode("\n".join(image_job(im).lines)).total_time_s
    t_crop = estimate_gcode("\n".join(image_job(cropped).lines)).total_time_s
    assert t_crop < t_full * 0.7


def test_frame_outline_is_the_cropped_box(qapp):
    from lumacut_job.images import image_outline_layers
    doc = Document()
    cropped = crop_image(_image(layer=doc.active_layer_id), [_circle()]).shape
    doc.add_shape(cropped)
    (layer,) = image_outline_layers(doc)
    xs = [p[0] for p in layer.polylines[0]]
    assert (min(xs), max(xs)) == pytest.approx(sorted(to_machine(60, 0)[0:1] + to_machine(80, 0)[0:1]))


# --- Vorschau, Export, Datei, Nachzeichnen ------------------------------------------------------

def test_dialog_preview_keeps_the_outside_white(qapp):
    from lumacut_import.image_preview import preview_shape
    cropped = crop_image(_image(value=40), [_circle()]).shape
    st = ImageSettings(mode="threshold", line_interval_mm=0.2)
    pv = preview_shape(cropped, st)
    assert pv.pixels[0, 0] == 255 and pv.pixels[50, 50] < 128


def test_png_export_shows_the_background_outside(qapp, tmp_path):
    from lumacut_canvas.export import export_png
    doc = Document()
    doc.add_shape(crop_image(_image(value=40, layer=doc.active_layer_id), [_circle()]).shape)
    img = export_png(doc, tmp_path / "a.png", px_per_mm=4)
    assert QColor(img.pixel(int(60.5 * 4), int(50.5 * 4))).red() == 255
    assert QColor(img.pixel(70 * 4, 60 * 4)).red() < 60


def test_save_load_round_trip_without_new_keys(qapp, tmp_path):
    doc = Document()
    plain = _image(layer=doc.active_layer_id)
    keys = set(plain.to_dict()) | {"image"}
    doc.add_shape(crop_image(plain, [_circle()]).shape)
    d = json.loads(json.dumps(doc.to_dict()))
    (sd,) = d["objects"]
    assert set(sd) <= keys and set(sd["image"]) == {"png", "px", "settings"}
    back = Document.from_dict(d)
    assert back.shapes[0].image.png == doc.shapes[0].image.png
    assert back.to_dict() == doc.to_dict()


def test_trace_sees_the_transparent_part_as_white(qapp):
    from lumacut_import.trace import decode_gray
    cropped = crop_image(_image(value=40), [_circle()]).shape
    g = decode_gray(cropped.image.png)
    assert g[0, 0] == 255 and g[25, 25] == 40


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


def test_action_crops_in_one_undo_step(ed):
    im, m = _setup(ed)
    msgs = []
    ed.statusMessage.connect(msgs.append)
    n = ed.undo_stack.count()
    ed.actions_by_name["image_crop"].trigger()
    s = ed.document.shape(im.id)
    assert ed.undo_stack.count() == n + 1 and ed.undo_stack.undoText() == "Bild zuschneiden"
    assert s.image.px_width == 50 and s.geom.as_tuple() == pytest.approx((60, 50, 20, 20))
    assert ed.document.has_shape(m.id) and ed.selection == [im.id]
    assert msgs[-1].startswith("Bild zugeschnitten: 50 × 50 Pixel, 39 % des Bildes bleiben")
    order = [x.id for x in ed.document.shapes]
    ed.undo_stack.undo()
    back = ed.document.shape(im.id)
    assert back.image.png == im.image.png and back.geom.as_tuple() == im.geom.as_tuple()
    assert [x.id for x in ed.document.shapes] == order
    ed.undo_stack.redo()
    assert ed.document.shape(im.id).image.px_width == 50


@pytest.mark.parametrize("what", ["no_image", "no_mask", "two_images"])
def test_wrong_selection_only_notifies(ed, what):
    im, m = _setup(ed)
    if what == "no_image":
        ed.set_selection([m.id])
    elif what == "no_mask":
        ed.set_selection([im.id])
    else:
        other = _image(Geometry(150, 150, 40, 20), layer=ed.document.active_layer_id)
        ed.document.add_shape(other)
        ed.set_selection([im.id, other.id, m.id])
    msgs = []
    ed.statusMessage.connect(msgs.append)
    n = ed.undo_stack.count()
    assert ed.path_ops.image_crop.crop() is False
    assert ed.undo_stack.count() == n and msgs and msgs[-1].startswith("Bild zuschneiden:")


def test_locked_image_layer_is_left_alone(ed):
    from lumacut_canvas.model import Layer
    im, m = _setup(ed)
    top = Layer("Maske")
    ed.document.add_layer(top)
    ed.document.shape(m.id).layer_id = top.id
    ed.document.update_layer(im.layer_id, locked=True)
    ed.selection = [im.id, m.id]
    msgs = []
    ed.statusMessage.connect(msgs.append)
    assert ed.path_ops.image_crop.crop() is False
    assert "gesperrt" in msgs[-1] and ed.document.shape(im.id).image.px_width == 100


def test_mask_on_a_locked_layer_still_masks(ed):
    from lumacut_canvas.model import Layer
    im, m = _setup(ed)
    top = Layer("Maske")
    ed.document.add_layer(top)
    ed.document.shape(m.id).layer_id = top.id
    ed.document.update_layer(top.id, locked=True)
    ed.selection = [im.id, m.id]
    assert ed.path_ops.image_crop.crop() is True
    assert ed.document.shape(im.id).image.px_width == 50


def test_canvas_item_shows_the_cropped_image(ed, qapp):
    im, _m = _setup(ed)
    ed.actions_by_name["image_crop"].trigger()
    qapp.processEvents()
    item = next(i for i in ed.scene.items() if getattr(i, "shape_id", None) == im.id)
    assert item._png == ed.document.shape(im.id).image.png
    assert item.boundingRect().width() < 30          # was 40 mm wide


def test_action_in_path_menu_and_context_menu(ed):
    from PySide6.QtCore import QPointF
    _setup(ed)
    texts = [a.text() for a in ed.path_ops_button.menu().actions() if a.text()]
    assert texts.index(imagecrop_ui.TEXT) == texts.index("Text in Pfade umwandeln") + 1
    menu = ed.build_context_menu(QPointF(70, 60))
    sub = next(a.menu() for a in menu.actions() if a.menu() is not None
               and a.menu().objectName() == "PathOpsMenu")
    assert imagecrop_ui.TEXT in [a.text() for a in sub.actions()]


def test_tooltip_and_shortcut(ed):
    a = ed.actions_by_name["image_crop"]
    assert a.shortcut().toString() == "Ctrl+Alt+M"
    assert "Crop Image" in a.toolTip() and "Zuschneiden" in a.toolTip()
    assert "zuschneiden" in ed.path_ops_button.toolTip()


def test_touch_mode_context_menu_rows(ed, qapp):
    from PySide6.QtCore import QPointF
    _setup(ed)
    ed.set_touch_mode(True, persist=False)
    try:
        menu = ed.build_context_menu(QPointF(70, 60))
        sub = next(a.menu() for a in menu.actions() if a.menu() is not None
                   and a.menu().objectName() == "PathOpsMenu")
        act = next(a for a in sub.actions() if a.text() == imagecrop_ui.TEXT)
        sub.popup(ed.mapToGlobal(ed.rect().center()))
        qapp.processEvents()
        assert sub.actionGeometry(act).height() >= 44
        sub.close()
    finally:
        ed.set_touch_mode(False, persist=False)


def test_save_load_keeps_the_crop(ed, tmp_path):
    from lumacut_canvas.document_io import load_into, save_document
    im, _m = _setup(ed)
    ed.actions_by_name["image_crop"].trigger()
    p = save_document(ed.document, tmp_path / "c.lcut")
    doc = Document()
    load_into(doc, p)
    assert doc.shape(im.id).image.png == ed.document.shape(im.id).image.png
    assert alpha_qimage(doc.shape(im.id)) is not None


def test_main_window_shortcut_is_unique_and_in_the_file_menu(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    try:
        owners = {a.text() for a in w.findChildren(QAction) if a.shortcut() == QKeySequence("Ctrl+Alt+M")}
        assert owners == {imagecrop_ui.TEXT}
        texts = [a.text() for a in w.import_tools.menu.actions()]
        assert texts.index(imagecrop_ui.TEXT) == texts.index("Bild nachzeichnen …") + 1
        ed = w.canvas
        im, _m = _setup(ed)
        ed.actions_by_name["image_crop"].trigger()
        assert ed.document.shape(im.id).image.px_width == 50
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
