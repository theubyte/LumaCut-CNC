"""Einlinien-Schriften (LightBurns *single-line fonts* / xTools Einlinien-Schrift): Text als
einzelne offene Striche – Glyphen, Satz, Umriss, Füllung, G-Code, Folgefunktionen, Datei,
Bedienung."""

from __future__ import annotations

import json
import math

import pytest
from _pi_guard import pi_check
from PySide6.QtGui import QPainterPath

from lumacut_canvas import linefont, linefont_data, text_ui
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.linefont import LINE_FONT_SANS, LINE_FONT_SCRIPT, LINE_FONTS
from lumacut_canvas.model import Document, Geometry, Shape, is_closed_shape
from lumacut_canvas.shape_paths import (local_path, shape_polygons, text_aspect, text_bounds, text_em,
                                        text_path)
from lumacut_canvas.toolpath import parse_gcode

FONTS = list(LINE_FONTS)


def _text(text="Hallo", family=LINE_FONT_SANS, layer="L1", h=10.0, **kw):
    w = h * text_aspect(text, family, **{k: v for k, v in kw.items() if k in ("bold", "italic")})
    return Shape("text", Geometry(20, 30, w, h), layer, text=text, font_family=family, **kw)


def _doc_with(*shapes, **layer):
    doc = Document()
    lid = doc.active_layer_id
    if layer:
        doc.update_layer(lid, **layer)
    for s in shapes:
        s.layer_id = lid
        doc.add_shape(s)
    return doc


def _elements(path: QPainterPath):
    return [path.elementAt(i) for i in range(path.elementCount())]


# --- Glyphen ---------------------------------------------------------------------------------

def test_parse_jhf_line():
    g = linefont.parse_jhf_line("12345  6J[MMX[ RXMM[")      # „x“ der Sans
    assert (g.left, g.right) == (-8.0, 9.0) and g.advance == 17.0
    assert g.strokes == [[(-5.0, -5.0), (6.0, 9.0)], [(6.0, -5.0), (-5.0, 9.0)]]
    assert linefont.parse_jhf_line("12345  1JZ").strokes == []


@pytest.mark.parametrize("family", FONTS)
def test_every_printable_ascii_char_has_a_glyph(family):
    data = getattr(linefont_data, LINE_FONTS[family].upper())
    assert len([line for line in data if not line.startswith("#")]) >= 95
    for code in range(33, 127):
        g = linefont.glyph(family, chr(code))
        assert g.advance > 0 and g.strokes, chr(code)
        assert all(len(s) >= 2 for s in g.strokes)
    assert linefont.glyph(family, " ").strokes == [] and linefont.glyph(family, " ").advance > 0


@pytest.mark.parametrize("family", FONTS)
def test_german_and_accented_letters_are_composed(family):
    for ch in "äöüÄÖÜéèêçñåÉ":
        g = linefont.glyph(family, ch)
        base = linefont.glyph(family, ch.encode("ascii", "ignore").decode() or
                              __import__("unicodedata").normalize("NFD", ch)[0])
        assert len(g.strokes) > len(base.strokes), ch
        assert g.advance == base.advance
    a, ae = linefont.glyph(family, "a"), linefont.glyph(family, "ä")
    top = min(y for s in a.strokes for _x, y in s)
    dots = ae.strokes[len(a.strokes):]
    assert len(dots) == 2 and all(max(y for _x, y in d) < top for d in dots)   # über dem „a“
    for ch in "ß€°":
        assert linefont.has_glyph(family, ch) and linefont.glyph(family, ch).strokes
    assert linefont.missing_chars("Grüße 20 € 5°", family) == ""


@pytest.mark.parametrize("family", FONTS)
def test_unknown_chars_fall_back_to_question_mark(family):
    assert linefont.glyph(family, "Ω") is linefont.glyph(family, "?")
    assert linefont.missing_chars("aΩb✓Ω", family) == "Ω✓"
    assert not linefont.has_glyph(family, "✓") and linefont.has_glyph(family, "\n")


@pytest.mark.parametrize("family", FONTS)
def test_typographic_chars_use_ascii_glyphs(family):
    g = lambda ch: linefont.glyph(family, ch)    # noqa: E731
    assert g("–") is g("-") and g("—") is g("-") and g("„") is g('"') and g("’") is g("'")
    assert g("\u00a0") is g(" ") and g("×") is g("x")
    assert len(g("…").strokes) == 3 * len(g(".").strokes) and g("…").advance == 3 * g(".").advance
    assert linefont.missing_chars("„Preis“ – 3×4 … 5 €", family) == ""


def test_i_with_accent_replaces_the_dot():
    i, ii = linefont.glyph(LINE_FONT_SANS, "i"), linefont.glyph(LINE_FONT_SANS, "í")
    assert len(ii.strokes) == len(i.strokes)          # Punkt raus, Akut rein


def test_is_line_font():
    assert linefont.is_line_font(LINE_FONT_SANS) and linefont.is_line_font(LINE_FONT_SCRIPT)
    for other in ("Segoe UI", "DejaVu Sans", "", None, 3):
        assert not linefont.is_line_font(other)


# --- Satz und Umriss --------------------------------------------------------------------------

@pytest.mark.parametrize("family", FONTS)
def test_path_is_open_strokes_without_curves(qapp, family):
    p = text_path("Hallo o", family)
    types = {e.type for e in _elements(p)}
    assert types <= {QPainterPath.MoveToElement, QPainterPath.LineToElement}
    polys = p.toSubpathPolygons()
    n = sum(len(linefont.glyph(family, ch).strokes) for ch in "Hallo o")
    assert len(polys) == n
    opened = [q for q in polys if q.first() != q.last()]
    assert opened                                    # „H“, „l“ … sind offene Striche


def test_o_is_a_stroke_ending_on_its_start(qapp):
    (poly,) = text_path("o", LINE_FONT_SANS).toSubpathPolygons()
    assert poly.first() == poly.last() and poly.size() > 10


def test_em_and_size_match_a_system_font(qapp):
    assert text_em(LINE_FONT_SANS) == pytest.approx(100.0 * 96.0 / 72.0)
    r = text_path("H", LINE_FONT_SANS).boundingRect()
    assert r.height() == pytest.approx(21.0 / linefont.EM_UNITS * text_em(LINE_FONT_SANS))


def test_letter_spacing_alignment_and_line_spacing(qapp):
    f = LINE_FONT_SANS
    w0 = text_path("AAAA", f).boundingRect().width()
    w1 = text_path("AAAA", f, letter_spacing=50.0).boundingRect().width()
    assert w1 - w0 == pytest.approx(3 * 0.5 * text_em(f), rel=1e-6)
    left = text_path("WWWW\nI", f).boundingRect()
    xs = lambda p: [q.boundingRect().center().x() for q in p.toSubpathPolygons()][-1]   # noqa: E731
    i_left = xs(text_path("WWWW\nI", f))
    i_mid = xs(text_path("WWWW\nI", f, align="center"))
    i_right = xs(text_path("WWWW\nI", f, align="right"))
    assert i_left < i_mid < i_right and i_mid == pytest.approx(left.center().x(), abs=2.0)
    h1 = text_path("A\nA", f).boundingRect().height()
    h2 = text_path("A\nA", f, line_spacing=200.0).boundingRect().height()
    assert h2 - h1 == pytest.approx(125.0, rel=1e-6)    # 1,25 × 100 pt wie bei Systemschriften


def test_italic_slants_and_bold_is_ignored(qapp):
    f = LINE_FONT_SANS
    up, it = text_path("I", f), text_path("I", f, italic=True)
    (a,), (b,) = up.toSubpathPolygons(), it.toSubpathPolygons()
    assert a.first().x() == pytest.approx(a.last().x())
    assert b.first().x() - b.last().x() == pytest.approx(0.2 * 21 * text_em(f) / 32.0)   # oben rechts
    assert _elements(text_path("Ab", f, bold=True)) == _elements(text_path("Ab", f)) or \
        [(e.x, e.y) for e in _elements(text_path("Ab", f, bold=True))] == \
        [(e.x, e.y) for e in _elements(text_path("Ab", f))]


def test_flat_text_gets_a_box(qapp):
    p = text_path("-", LINE_FONT_SANS)
    assert p.boundingRect().height() == 0
    r = text_bounds(p)
    assert r.height() == 1.0 and r.width() == p.boundingRect().width()
    s = _text("-")
    assert s.geom.w > 0 and len(shape_polygons(s)) == 1
    (line,) = shape_polygons(s)
    assert line[0][1] == pytest.approx(line[-1][1]) == pytest.approx(30 + s.geom.h / 2)


def test_system_font_bounds_unchanged(qapp):
    p = text_path("Hallo", "DejaVu Sans")
    assert text_bounds(p) == p.boundingRect()


@pytest.mark.parametrize("family", FONTS)
def test_shape_fills_its_box_and_rotates(qapp, family):
    s = _text("Name 12", family)
    r = local_path(s).boundingRect()
    assert (r.x(), r.y()) == pytest.approx((20, 30)) and (r.width(), r.height()) == pytest.approx((s.geom.w, 10))
    s.geom.rot = 90.0
    polys = shape_polygons(s)
    xs = [x for p in polys for x, _y in p]
    assert max(xs) - min(xs) == pytest.approx(10, abs=1e-6)


def test_weld_is_ignored_for_line_fonts(qapp):
    s = _text("oo", letter_spacing=-30.0)
    w = s.copy()
    w.text_weld = True
    assert [list(p) for p in shape_polygons(w)] == [list(p) for p in shape_polygons(s)]


def test_is_closed_shape():
    assert is_closed_shape(Shape("text", Geometry(0, 0, 5, 5), "L", text="a"))
    assert not is_closed_shape(Shape("text", Geometry(0, 0, 5, 5), "L", text="a", font_family=LINE_FONT_SANS))
    for kind, closed in (("rect", True), ("ellipse", True), ("line", False), ("image", False)):
        assert is_closed_shape(Shape(kind, Geometry(0, 0, 5, 5), "L")) is closed


# --- Datei -------------------------------------------------------------------------------------

def test_saved_as_font_name_without_new_key():
    s = Shape("text", Geometry(1, 2, 30, 8), "L1", text="Anna", font_family=LINE_FONT_SCRIPT)
    d = s.to_dict()
    assert d["font"] == LINE_FONT_SCRIPT
    assert set(d) == {"id", "kind", "layer", "x", "y", "w", "h", "text", "font"}
    back = Shape.from_dict(json.loads(json.dumps(d)))
    assert back.font_family == LINE_FONT_SCRIPT and back.to_dict() == d


def test_old_text_file_and_gcode_unchanged(qapp):
    from lumacut_canvas.gcode import document_to_gcode
    d = {"id": "t1", "kind": "text", "layer": "L1", "x": 1.0, "y": 2.0, "w": 30.0, "h": 8.0,
         "text": "Anna", "font": "DejaVu Sans"}
    s = Shape.from_dict(d)
    assert s.to_dict() == d and is_closed_shape(s)
    doc = _doc_with(s, fill_mode="hatch", line_interval_mm=0.5)
    g = document_to_gcode(doc)
    assert document_to_gcode(Document.from_dict(json.loads(json.dumps(doc.to_dict())))) == g


def test_save_load_document(tmp_path, qapp):
    from lumacut_canvas.document_io import load_into, save_document
    doc = _doc_with(_text("Grüße"))
    p = save_document(doc, tmp_path / "t.lcut")
    back = Document()
    load_into(back, p)
    assert back.shapes[0].font_family == LINE_FONT_SANS
    assert [list(q) for q in shape_polygons(back.shapes[0])] == [list(q) for q in shape_polygons(doc.shapes[0])]


# --- Auftrag ------------------------------------------------------------------------------------

def test_cut_layer_lasers_every_stroke_once(qapp):
    from lumacut_canvas.export import job_layers
    s = _text("Hallo")
    (jl,) = job_layers(_doc_with(s))
    strokes = sum(len(linefont.glyph(LINE_FONT_SANS, ch).strokes) for ch in "Hallo")
    assert len(jl.polylines) == strokes and not jl.fills


@pytest.mark.parametrize("outline", [False, True])
def test_fill_layer_lasers_the_strokes_and_no_fill(qapp, outline):
    from lumacut_canvas.export import job_layers, layer_fill_blocks
    s = _text("Hallo")
    doc = _doc_with(s, fill_mode="hatch", line_interval_mm=0.3, hatch_outline=outline)
    assert layer_fill_blocks(doc, doc.layers[0]) == []
    (jl,) = job_layers(doc)
    assert not jl.fills and len(jl.polylines) == sum(
        len(linefont.glyph(LINE_FONT_SANS, ch).strokes) for ch in "Hallo")


def test_mixed_layer_fills_only_the_outline_text(qapp):
    from lumacut_canvas.export import layer_fill_blocks
    a = Shape("text", Geometry(20, 60, 40, 12), "L", text="AB", font_family="DejaVu Sans")
    b = _text("AB")
    doc = _doc_with(a, b, fill_mode="hatch", line_interval_mm=0.5, fill_grouping="together")
    ((ids, segs),) = layer_fill_blocks(doc, doc.layers[0])
    assert ids == [a.id] and segs


@pytest.mark.parametrize("family", FONTS)
def test_gcode_is_pi_safe_and_much_shorter_than_a_filled_text(qapp, family):
    from lumacut_job.planner import optimized_document_gcode
    s = _text("LumaCut 2026", family, h=8.0)
    g = optimized_document_gcode(_doc_with(s, fill_mode="hatch", line_interval_mm=0.1),
                                 scan_offsets=None)
    pi_check(g)
    tp = parse_gcode(g)
    strokes = shape_polygons(s)
    total = sum(math.dist(p[i], p[i + 1]) for p in strokes for i in range(len(p) - 1))
    assert tp.cut_length_mm == pytest.approx(total, abs=0.05)     # G-Code auf 0,001 mm gerundet
    plain = Shape("text", Geometry(20, 30, s.geom.w, 8.0), "L", text="LumaCut 2026", font_family="DejaVu Sans")
    g2 = optimized_document_gcode(_doc_with(plain, fill_mode="hatch", line_interval_mm=0.1),
                                  scan_offsets=None)
    assert parse_gcode(g2).cut_length_mm > 3 * tp.cut_length_mm


def test_estimate_of_a_line_text(qapp):
    from lumacut_job.estimate import estimate_gcode
    from lumacut_job.planner import optimized_document_gcode
    est = estimate_gcode(optimized_document_gcode(_doc_with(_text("Nr 17")), scan_offsets=None))
    assert est is not None


# --- Folgefunktionen ----------------------------------------------------------------------------

def test_text_to_path_gives_an_open_path_with_the_same_strokes(qapp):
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.pathops import text_to_outline
    s = _text("Hallo ä")
    out = text_to_outline(s)
    assert out.kind == "path" and len(out.ring_ranges()) == len(shape_polygons(s))
    key = lambda polys: sorted(tuple((round(x, 6), round(y, 6)) for x, y in p) for p in polys)  # noqa: E731
    a, b = key(shape_polygons(s)), key(shape_polygons(out))
    assert len(a) == len(b)
    for pa, pb in zip(a, b):
        assert len(pa) == len(pb)
        assert all(math.dist(p, q) < 1e-6 for p, q in zip(pa, pb))
    assert sum(len(j.polylines) for j in job_layers(_doc_with(out))) == len(a)


def test_text_to_path_of_outline_text_unchanged(qapp):
    from lumacut_canvas.pathops import text_to_outline
    out = text_to_outline(Shape("text", Geometry(0, 0, 30, 10), "L", text="AB", font_family="DejaVu Sans"))
    assert out.kind == "polygon"


def test_boolean_area_refused_offset_as_lines(qapp):
    from lumacut_canvas import pathops
    s = _text("I")
    with pytest.raises(pathops.PathOpError):
        pathops.shape_area(s)
    out = pathops.offset([s], 0.5)
    assert out and all(o.kind == "polygon" for o in out)


def test_image_crop_ignores_line_text(qapp):
    from lumacut_canvas import imagecrop
    a = Shape("text", Geometry(0, 0, 30, 10), "L", text="O", font_family="DejaVu Sans")
    assert imagecrop.mask_shapes([a, _text("O")]) == [a]


def test_trim_uses_the_strokes_as_open_cutters(qapp):
    from lumacut_canvas import pathtrim
    rings = pathtrim.shape_rings(_text("I"))
    assert len(rings) == 1 and rings[0][1] is False and len(rings[0][0]) == 2
    o = pathtrim.shape_rings(_text("o"))
    assert o[0][1] is True


def test_nesting_footprint_of_open_strokes(qapp):
    from lumacut_canvas.nesting import shape_footprint
    g = shape_footprint(_text("I"))
    assert g.area == 0 and g.length == pytest.approx(10.0, rel=1e-6)


def test_serial_numbers_keep_the_line_font(qapp):
    from lumacut_job.serial import SerialSpec, serial_shapes
    src = _text("Nr 1")
    shapes = serial_shapes(src, SerialSpec("Nr {n}", start=1, count=3, columns=3), text_aspect)
    assert shapes and all(sh.font_family == LINE_FONT_SANS for sh in shapes)


def test_png_and_svg_export_draw_lines_not_fills(qapp, tmp_path):
    from lumacut_canvas.export import export_png, export_svg
    doc = _doc_with(_text("o", h=30.0))
    img = export_png(doc, tmp_path / "a.png", px_per_mm=4.0)
    s = doc.shapes[0]
    cx, cy = (s.geom.x + s.geom.w / 2) * 4, (s.geom.y + s.geom.h * 0.62) * 4
    assert img.pixelColor(int(cx), int(cy)).lightness() > 200      # Innenraum des „o“ frei
    export_svg(doc, tmp_path / "a.svg")
    assert (tmp_path / "a.svg").read_text().count("<path") >= 1


# --- Bedienung -----------------------------------------------------------------------------------

@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1500, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, text="Hallo", family="DejaVu Sans", **kw):
    s = Shape("text", Geometry(20, 20, 10 * text_aspect(text, family), 10), ed.document.active_layer_id,
              text=text, font_family=family, **kw)
    ed.document.add_shape(s)
    ed.set_selection([s.id])
    return ed.document.shape(s.id)


def test_combo_lists_outline_and_line_fonts(ed):
    bar = ed.property_bar.text_style
    items = [bar.stroke.itemData(i) for i in range(bar.stroke.count())]
    assert items == ["", LINE_FONT_SANS, LINE_FONT_SCRIPT]
    assert bar.stroke.itemText(0) == "Umrissschrift"
    assert "Single-Line" in bar.stroke.toolTip() and "Einlinien" in bar.stroke.toolTip()


def test_choose_line_font_in_one_undo_step_keeps_height(ed):
    bar = ed.property_bar.text_style
    t = _add(ed)
    bar.refresh()
    assert bar.stroke.currentIndex() == 0 and bar.family.isEnabled()
    n0 = ed.undo_stack.count()
    bar.stroke.setCurrentIndex(1)
    bar.stroke.activated.emit(1)
    s = ed.document.shape(t.id)
    assert s.font_family == LINE_FONT_SANS and ed.undo_stack.count() == n0 + 1
    assert ed.undo_stack.undoText() == "Einlinie (Sans)"
    assert s.geom.h == pytest.approx(10.0) and s.geom.w == pytest.approx(10 * text_aspect("Hallo", LINE_FONT_SANS))
    assert ed.text_font_family == LINE_FONT_SANS
    assert not bar.family.isEnabled() and not bar.bold.isEnabled() and not bar.weld.isEnabled()
    assert bar.italic.isEnabled()
    bar.stroke.setCurrentIndex(0)
    bar.stroke.activated.emit(0)
    s = ed.document.shape(t.id)
    assert not linefont.is_line_font(s.font_family) and bar.family.isEnabled()
    assert ed.undo_stack.undoText() == "Umrissschrift"
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert ed.document.shape(t.id).font_family == "DejaVu Sans"


def test_back_to_the_last_outline_font(ed):
    bar = ed.property_bar.text_style
    ed.text_outline_family = "DejaVu Serif"
    t = _add(ed, family=LINE_FONT_SCRIPT)
    bar.refresh()
    assert bar.stroke.currentIndex() == 2
    bar.stroke.setCurrentIndex(0)
    bar.stroke.activated.emit(0)
    assert ed.document.shape(t.id).font_family == "DejaVu Serif"


def test_mixed_selection_and_refresh_does_not_push(ed):
    bar = ed.property_bar.text_style
    a = _add(ed, "AB")
    b = _add(ed, "CD", family=LINE_FONT_SANS)
    ed.set_selection([a.id, b.id])
    n0 = ed.undo_stack.count()
    bar.refresh()
    assert bar.stroke.currentIndex() == -1 and ed.undo_stack.count() == n0
    bar.stroke.setCurrentIndex(2)
    bar.stroke.activated.emit(2)
    assert {ed.document.shape(i).font_family for i in (a.id, b.id)} == {LINE_FONT_SCRIPT}
    assert ed.undo_stack.count() == n0 + 1


def test_missing_chars_are_named(ed):
    msgs = []
    ed.notify = msgs.append
    bar = ed.property_bar.text_style
    _add(ed, "Ω-Wert")
    bar.refresh()
    bar.stroke.setCurrentIndex(1)
    bar.stroke.activated.emit(1)
    assert msgs and "Ω" in msgs[-1] and "?" in msgs[-1]


def test_locked_layer_text_is_not_changed(ed):
    t = _add(ed)
    ed.document.layer(t.layer_id).locked = True
    bar = ed.property_bar.text_style
    n0 = ed.undo_stack.count()
    bar._stroke_chosen(1)
    assert ed.undo_stack.count() == n0 and ed.document.shape(t.id).font_family == "DejaVu Sans"


def test_new_text_uses_the_line_font(ed):
    ed.text_font_family = LINE_FONT_SANS
    s = ed.tools.add_text("Neu", __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(50, 50))
    assert s.font_family == LINE_FONT_SANS
    assert s.geom.w / s.geom.h == pytest.approx(text_aspect("Neu", LINE_FONT_SANS))


def test_size_and_layout_on_a_line_text(ed):
    t = _add(ed, family=LINE_FONT_SANS)
    pt = text_ui.size_pt(t)
    big = text_ui.with_size_pt(t, pt * 2)
    assert big.geom.h == pytest.approx(2 * t.geom.h)
    wide = text_ui.with_layout(t, letter_spacing=40.0)
    assert wide.geom.w > t.geom.w and wide.geom.h == pytest.approx(t.geom.h)


def test_canvas_item_is_not_filled(ed, qapp):
    t = _add(ed, family=LINE_FONT_SANS)
    qapp.processEvents()
    item = next(i for i in ed.scene.items() if getattr(i, "shape_id", None) == t.id)
    assert item._filled is False and item.outline_hit(item._path.boundingRect().center())
    u = _add(ed, "AB")
    qapp.processEvents()
    item2 = next(i for i in ed.scene.items() if getattr(i, "shape_id", None) == u.id)
    assert item2._filled is True


def test_touch_mode_size(ed, qapp):
    bar = ed.property_bar.text_style
    _add(ed)
    bar.refresh()
    ed.set_touch_mode(True, persist=False)
    qapp.processEvents()
    try:
        assert bar.stroke.sizeHint().height() >= 40
    finally:
        ed.set_touch_mode(False, persist=False)


def test_main_window_has_the_switch(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    win = main.LumaCutStudio()
    ed = win.canvas
    t = _add(ed)
    bar = ed.property_bar.text_style
    bar.refresh()
    bar.stroke.setCurrentIndex(1)
    bar.stroke.activated.emit(1)
    assert ed.document.shape(t.id).font_family == LINE_FONT_SANS
    ed.undo_stack.setClean()
    win.close()
