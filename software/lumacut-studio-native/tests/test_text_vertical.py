"""Senkrechter Text (xTool Studio „vertikales Layout“): Zeichen aufrecht untereinander, jede
Zeile eine Spalte – Modell, Datei, Umriss, Box, Folgefunktionen (G-Code, variabler Text,
Seriennummern, „In Pfade“, SVG), Bedienung."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas import text_ui  # noqa: E402
from lumacut_canvas.editor import CanvasEditor  # noqa: E402
from lumacut_canvas.linefont import LINE_FONT_SANS  # noqa: E402
from lumacut_canvas.model import (TEXT_VALIGN_LABELS, Document, Geometry, Shape,  # noqa: E402
                                  refit_geom, rotate_point, text_anchor, text_layout)
from lumacut_canvas.shape_paths import (shape_polygons, shape_text_path, text_aspect,  # noqa: E402
                                        text_bounds, text_em, text_path, text_size,
                                        vertical_text_path)

FAMILY = "DejaVu Sans"
NOW = dt.datetime(2026, 11, 18, 9, 0, 0)
ROW = 125.0                     # Grundlinien-Abstand 1,25 × 100 pt (Aufbau-Einheiten)


def _elements(path):
    return [(e.type, round(e.x, 9), round(e.y, 9)) for e in
            (path.elementAt(i) for i in range(path.elementCount()))]


def _text(text="LUMA", family=LINE_FONT_SANS, h=40.0, **kw):
    s = Shape("text", Geometry(20, 30, 10, h), "L1", text=text, font_family=family, **kw)
    s.geom.w = h * text_aspect(text, family, **text_layout(s))
    return s


def _doc_with(*shapes):
    doc = Document()
    for s in shapes:
        s.layer_id = doc.active_layer_id
        doc.add_shape(s)
    return doc


def _subpaths(path):
    """Teilpfade als Boxen (x-Mitte, y-oben), sortiert."""
    return [poly.boundingRect() for poly in path.toSubpathPolygons()]


# --- Modell und Datei ------------------------------------------------------------------------

def test_default_is_horizontal_and_not_saved():
    s = Shape("text", Geometry(0, 0, 10, 5), "L1", text="Abc")
    assert s.text_vertical is False and "vertical" not in s.to_dict()
    assert "vertical" not in text_layout(s)
    assert Shape.from_dict(s.to_dict()).text_vertical is False


def test_round_trip():
    s = Shape("text", Geometry(0, 0, 10, 5), "L1", text="Abc", text_vertical=True)
    d = json.loads(json.dumps(s.to_dict()))
    assert d["vertical"] is True
    back = Shape.from_dict(d)
    assert back.text_vertical is True and back.to_dict() == d
    assert text_layout(back) == {"vertical": True}
    assert s.copy(new_identity=True).text_vertical is True


@pytest.mark.parametrize("raw", ["true", 1, "yes", None, [True], {"a": 1}, False])
def test_only_true_reads_as_vertical(raw):
    d = Shape("text", Geometry(0, 0, 10, 5), "L1", text="A").to_dict()
    d["vertical"] = raw
    assert Shape.from_dict(d).text_vertical is False


def test_vertical_only_on_text_objects():
    d = Shape("rect", Geometry(0, 0, 10, 5), "L1").to_dict()
    d["vertical"] = True
    r = Shape.from_dict(d)
    assert r.text_vertical is False and "vertical" not in r.to_dict()


def test_old_project_file_unchanged(qapp):
    doc = _doc_with(_text("Hallo", FAMILY, text_align="center", text_case="upper"))
    d = doc.to_dict()
    assert "vertical" not in json.dumps(d)
    assert Document.from_dict(json.loads(json.dumps(d))).to_dict() == d


def test_anchor_and_refit_geom():
    h = Shape("text", Geometry(0, 0, 10, 5), "L1", text="A", text_align="right")
    v = Shape("text", Geometry(0, 0, 10, 5), "L1", text="A", text_align="right", text_vertical=True)
    assert text_anchor(h) == (1.0, 0.0) and text_anchor(v) == (0.0, 1.0)
    v.text_align = "center"
    assert text_anchor(v) == (0.0, 0.5)
    g = refit_geom(Geometry(10, 20, 30, 40), 6, 50, 0.0, 1.0)
    assert (g.x, g.y, g.w, g.h) == (10, 10, 6, 50)          # linke untere Ecke bleibt
    g0 = Geometry(10, 20, 30, 40, 30.0)
    g1 = refit_geom(g0, 8, 70, 0.0, 0.5)

    def pt(g, fx, fy):
        cx, cy = g.center()
        return rotate_point(g.x + fx * g.w, g.y + fy * g.h, cx, cy, g.rot)
    assert pt(g1, 0.0, 0.5) == pytest.approx(pt(g0, 0.0, 0.5), abs=1e-9) and g1.rot == 30.0
    assert TEXT_VALIGN_LABELS == {"left": "Oben", "center": "Mittig", "right": "Unten"}


# --- Umriss ----------------------------------------------------------------------------------

@pytest.mark.parametrize("family", [FAMILY, LINE_FONT_SANS])
def test_letters_stacked_and_centred(qapp, family):
    p = text_path("LIMA", family, vertical=True)
    assert _elements(p) == _elements(vertical_text_path("LIMA", family))
    # Grundlinien im Zeilenabstand: das letzte Zeichen endet wie allein, um 3 Zeilen tiefer
    r = text_bounds(p)
    assert r.center().x() == pytest.approx(0.0, abs=1.0)
    first, last = text_bounds(text_path("L", family)), text_bounds(text_path("A", family))
    assert r.top() == pytest.approx(min(first.top(), text_bounds(text_path("I", family)).top()), abs=1e-6)
    assert r.bottom() == pytest.approx(3 * ROW + last.bottom(), abs=1e-6)
    assert r.height() > 3 * r.width()                        # hoch statt breit
    assert text_aspect("LIMA", family, vertical=True) < 0.5 < text_aspect("LIMA", family)


def test_each_glyph_centred_on_the_column(qapp):
    # „I“ und „W“ stehen mit der Umrissmitte auf derselben Spaltenmitte
    p = text_path("WI", FAMILY, vertical=True)
    polys = sorted(_subpaths(p), key=lambda b: b.top())
    w, i = polys[0], polys[-1]
    assert w.center().x() == pytest.approx(0.0, abs=1e-6)
    assert i.center().x() == pytest.approx(0.0, abs=1e-6)
    assert i.top() > w.bottom()


def test_lines_become_columns_left_to_right(qapp):
    em = text_em(FAMILY)
    p = text_path("AB\nC", FAMILY, vertical=True)
    c_alone = text_bounds(text_path("C", FAMILY, vertical=True))
    cs = [b for b in _subpaths(p) if b.center().x() > 0.5 * em]
    assert cs and min(b.left() for b in cs) == pytest.approx(c_alone.left() + 1.25 * em, abs=1e-6)
    # Zeilenabstand 200 % = doppelter Spaltenabstand
    p2 = text_path("AB\nC", FAMILY, vertical=True, line_spacing=200.0)
    assert text_bounds(p2).right() == pytest.approx(c_alone.right() + 2.5 * em, abs=1e-6)


@pytest.mark.parametrize("align,rows", [("left", 0), ("center", 1), ("right", 2)])
def test_alignment_top_middle_bottom(qapp, align, rows):
    p = text_path("ABCD\nEF", LINE_FONT_SANS, vertical=True, align=align)
    em = text_em(LINE_FONT_SANS)
    second = [b for b in _subpaths(p) if b.center().x() > 0.6 * em]
    ref = text_bounds(text_path("E", LINE_FONT_SANS))
    assert min(b.top() for b in second) == pytest.approx(ref.top() + rows * ROW, abs=1e-6)


def test_letter_spacing_widens_the_rows(qapp):
    em = text_em(FAMILY)
    a = text_bounds(text_path("ABC", FAMILY, vertical=True))
    b = text_bounds(text_path("ABC", FAMILY, vertical=True, letter_spacing=20.0))
    assert b.height() - a.height() == pytest.approx(2 * 0.2 * em, abs=1e-6)
    assert b.width() == pytest.approx(a.width(), abs=1e-9)


def test_spaces_keep_a_row_and_empty_text(qapp):
    a = text_bounds(text_path("A B", FAMILY, vertical=True))
    b = text_bounds(text_path("AXB", FAMILY, vertical=True))
    assert a.height() == pytest.approx(b.height(), abs=1e-6)
    assert text_path(" ", FAMILY, vertical=True).isEmpty()
    assert text_path("", FAMILY, vertical=True).isEmpty()


@pytest.mark.parametrize("family", [FAMILY, LINE_FONT_SANS])
def test_upper_case_and_vertical_combine(qapp, family):
    a = text_path("köln", family, vertical=True, case="upper")
    b = text_path("KÖLN", family, vertical=True)
    assert _elements(a) == _elements(b)


def test_horizontal_path_unchanged(qapp):
    for fam in (FAMILY, LINE_FONT_SANS):
        assert _elements(text_path("ab\nc", fam, vertical=False)) == _elements(text_path("ab\nc", fam))


def test_line_font_stays_open_strokes(qapp):
    s = _text("LUMA", LINE_FONT_SANS, text_vertical=True)
    polys = shape_polygons(s)
    assert len(polys) >= 4 and any(p[0] != p[-1] for p in polys)
    xs = [x for p in polys for x, _ in p]
    ys = [y for p in polys for _, y in p]
    assert min(xs) >= s.geom.x - 1e-6 and max(xs) <= s.geom.x + s.geom.w + 1e-6
    assert min(ys) >= s.geom.y - 1e-6 and max(ys) <= s.geom.y + s.geom.h + 1e-6


def test_text_size(qapp):
    w, h = text_size("LIMA", FAMILY, vertical=True)
    r = text_bounds(text_path("LIMA", FAMILY, vertical=True))
    assert (w, h) == (r.width(), r.height())


# --- Box -------------------------------------------------------------------------------------

@pytest.mark.parametrize("family", [FAMILY, LINE_FONT_SANS])
def test_switch_keeps_font_size_and_top_left(qapp, family):
    s = _text("LUMA", family, h=10.0)
    pt0 = text_ui.size_pt(s)
    v = text_ui.with_layout(s, vertical=True)
    assert v.text_vertical and not s.text_vertical
    assert text_ui.size_pt(v) == pytest.approx(pt0, rel=1e-6)
    assert (v.geom.x, v.geom.y) == (s.geom.x, s.geom.y)
    assert v.geom.h > 2.5 * s.geom.h and v.geom.w < s.geom.w
    back = text_ui.with_layout(v, vertical=False)
    for a, b in ((back.geom.x, s.geom.x), (back.geom.y, s.geom.y),
                 (back.geom.w, s.geom.w), (back.geom.h, s.geom.h)):
        assert a == pytest.approx(b, abs=1e-9)


def test_bottom_aligned_vertical_keeps_the_bottom_left(qapp):
    s = _text("AB\nC", LINE_FONT_SANS, text_align="right", text_vertical=True)
    u = text_ui.with_layout(s, text="AB\nCDE")
    assert u.geom.x == pytest.approx(s.geom.x, abs=1e-9)
    assert u.geom.y + u.geom.h == pytest.approx(s.geom.y + s.geom.h, abs=1e-9)
    assert u.geom.h > s.geom.h


def test_rotated_switch_keeps_the_corner(qapp):
    s = _text("LUMA", LINE_FONT_SANS)
    s.geom.rot = 90.0
    v = text_ui.with_layout(s, vertical=True)

    def corner(g):
        cx, cy = g.center()
        return rotate_point(g.x, g.y, cx, cy, g.rot)
    assert corner(v.geom) == pytest.approx(corner(s.geom), abs=1e-9) and v.geom.rot == 90.0


def test_mirrored_stays_mirrored(qapp):
    s = _text("LUMA", LINE_FONT_SANS)
    s.geom.w = -s.geom.w
    v = text_ui.with_layout(s, vertical=True)
    assert v.geom.w < 0 and v.geom.h > 0


def test_font_size_edit_scales_vertical_text(qapp):
    s = _text("LUMA", FAMILY, text_vertical=True)
    big = text_ui.with_size_pt(s, 2 * text_ui.size_pt(s))
    assert big.geom.h == pytest.approx(2 * s.geom.h, rel=1e-9)
    assert big.geom.w == pytest.approx(2 * s.geom.w, rel=1e-9)


# --- Folgefunktionen -------------------------------------------------------------------------

@pytest.mark.parametrize("family", [FAMILY, LINE_FONT_SANS])
def test_job_and_gcode_pi_safe(qapp, family):
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.toolpath import parse_gcode
    from lumacut_job.planner import optimized_document_gcode
    v = _text("LUMA", family, h=60.0, text_vertical=True)
    doc = _doc_with(v)
    polys = [p for jl in job_layers(doc) for p in jl.polylines]
    assert polys
    ys = [y for p in polys for _, y in p]
    assert max(ys) - min(ys) == pytest.approx(60.0, abs=0.05)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    # gleiche Buchstabengröße: waagrechter Text mit derselben Schnittlänge (± Kurvenabflachung)
    hs = text_ui.with_layout(v, vertical=False)
    gh = optimized_document_gcode(_doc_with(hs), scan_offsets=None)
    assert parse_gcode(g).cut_length_mm == pytest.approx(parse_gcode(gh).cut_length_mm, rel=0.02)


def test_filled_vertical_text_is_hatched(qapp):
    from shapely.geometry import LineString
    from lumacut_canvas.hatch import hatch_lines
    s = _text("LO", FAMILY, h=30.0, text_vertical=True)
    rings = [p for p in shape_polygons(s) if len(p) >= 3]
    lines = hatch_lines(rings, 0.2)
    assert len(lines) > 50
    ys = [y for seg in lines for _, y in seg]
    assert max(ys) - min(ys) > 25.0                       # über beide Buchstaben
    assert sum(LineString(seg).length for seg in lines) > 100.0


def test_document_gcode_unchanged_without_key(qapp):
    from lumacut_canvas.gcode import document_to_gcode
    doc = _doc_with(_text("LUMA", FAMILY))
    g0 = document_to_gcode(doc)
    doc2 = Document.from_dict(json.loads(json.dumps(doc.to_dict())))
    assert document_to_gcode(doc2) == g0
    doc2.shapes[0].text_vertical = True
    assert document_to_gcode(doc2) != g0


def test_variable_text_height_follows_the_name(qapp, tmp_path):
    from lumacut_job import vartext as vt
    csv = tmp_path / "namen.csv"
    csv.write_text("Name\nANNA\nMAXIMILIAN\n", encoding="utf-8")
    s = _text("{Name}", LINE_FONT_SANS, text_vertical=True, text_align="center")
    s.generator = vt.make_meta(vt.VarTextSpec(csv_path=str(csv)))
    k0 = abs(s.geom.h) / text_size("{Name}", LINE_FONT_SANS, vertical=True)[1]
    out, _usage = vt.evaluate_document(_doc_with(s), None, NOW)
    t = out.shapes[0]
    assert t.text == "ANNA" and t.text_vertical
    k1 = abs(t.geom.h) / text_size("ANNA", LINE_FONT_SANS, vertical=True)[1]
    assert k1 == pytest.approx(k0, rel=1e-9)                 # Buchstaben gleich groß
    assert t.geom.h < s.geom.h                               # 4 statt 6 Zeichen
    # mittig: die Mitte der linken Kante bleibt
    assert t.geom.x == pytest.approx(s.geom.x, abs=1e-9)
    assert t.geom.y + t.geom.h / 2 == pytest.approx(s.geom.y + s.geom.h / 2, abs=1e-9)
    pi_check(__import__("lumacut_job.planner", fromlist=["x"]).optimized_document_gcode(
        out, scan_offsets=None))


def test_refit_vertical_rotated_and_horizontal_unchanged(qapp):
    from lumacut_job import vartext as vt
    s = _text("AB", LINE_FONT_SANS, text_vertical=True)
    s.geom.rot = 45.0
    t = vt.refit_text(s, "ABCD", text_aspect)

    def corner(g):
        cx, cy = g.center()
        return rotate_point(g.x, g.y, cx, cy, g.rot)
    assert corner(t.geom) == pytest.approx(corner(s.geom), abs=1e-9)
    assert t.geom.h > 1.8 * s.geom.h
    h = _text("AB", LINE_FONT_SANS)
    u = vt.refit_text(h, "ABCD", text_aspect)
    assert u.geom.h == h.geom.h and u.geom.w > h.geom.w


def test_serial_numbers_vertical(qapp):
    from lumacut_job.serial import SerialSpec, serial_shapes
    src = _text("N1", LINE_FONT_SANS, h=20.0, text_vertical=True)
    shapes = serial_shapes(src, SerialSpec("N{n}", start=9, count=4, columns=2, gap_x_mm=2.0,
                                           gap_y_mm=3.0), text_aspect)
    assert [sh.text for sh in shapes] == ["N9", "N10", "N11", "N12"]
    assert all(sh.text_vertical for sh in shapes)
    k = abs(src.geom.h) / text_size("N1", LINE_FONT_SANS, vertical=True)[1]
    for sh in shapes:
        assert abs(sh.geom.h) / text_size(sh.text, LINE_FONT_SANS, vertical=True)[1] == pytest.approx(k, rel=1e-9)
    assert shapes[1].geom.h > shapes[0].geom.h
    cell_h = max(abs(sh.geom.h) for sh in shapes)
    assert shapes[2].geom.y == pytest.approx(src.geom.y + cell_h + 3.0, abs=1e-9)
    boxes = [sh.bounds() for sh in shapes]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert a.x + a.w <= b.x + 1e-9 or b.x + b.w <= a.x + 1e-9 or \
                a.y + a.h <= b.y + 1e-9 or b.y + b.h <= a.y + 1e-9


def test_text_to_path_and_svg(qapp, tmp_path):
    from lumacut_canvas.export import export_svg
    from lumacut_canvas.pathops import text_to_outline
    s = _text("LO", FAMILY, text_vertical=True)
    o = text_to_outline(s)
    b = o.bounds()
    assert b.h > 1.5 * b.w and b.h == pytest.approx(s.geom.h, abs=0.05)
    a, c = tmp_path / "a.svg", tmp_path / "c.svg"
    export_svg(_doc_with(s), a)
    h = s.copy()
    h.text_vertical = False
    export_svg(_doc_with(h), c)
    assert a.read_text() != c.read_text()


def test_weld_works_on_vertical_text(qapp):
    from lumacut_canvas.pathops import shape_area
    s = _text("OO", FAMILY, text_vertical=True, letter_spacing=-60.0, text_weld=True)
    plain = s.copy()
    plain.text_weld = False
    assert shape_area(s).area > shape_area(plain).area       # Überlappung mitgefüllt


# --- Bedienung -------------------------------------------------------------------------------

@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1400, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, text="LUMA", **kw):
    s = _text(text, kw.pop("family", LINE_FONT_SANS), h=10.0, **kw)
    s.layer_id = ed.document.active_layer_id
    ed.document.add_shape(s)
    ed.set_selection([s.id])
    return ed.document.shape(s.id)


def test_button_toggles_in_one_undo_step(ed):
    bar = ed.property_bar.text_style
    t = _add(ed)
    bar.refresh()
    b = bar.vertical
    assert b.isCheckable() and not b.isChecked() and b.isEnabled()
    assert b.objectName() == "TextVertical" and b.text() == "A↓"
    n0 = ed.undo_stack.count()
    g0 = t.geom.copy()
    b.click()
    s = ed.document.shape(t.id)
    assert s.text_vertical and ed.undo_stack.count() == n0 + 1
    assert ed.undo_stack.undoText() == "Senkrechter Text"
    assert s.geom.h > 2.5 * g0.h and (s.geom.x, s.geom.y) == (g0.x, g0.y)
    bar.refresh()
    assert b.isChecked()
    b.click()
    assert not ed.document.shape(t.id).text_vertical
    assert ed.undo_stack.undoText() == "Waagrechter Text"
    assert ed.document.shape(t.id).geom.h == pytest.approx(g0.h, abs=1e-9)
    ed.undo_stack.undo()
    assert ed.document.shape(t.id).text_vertical
    ed.undo_stack.undo()
    assert not ed.document.shape(t.id).text_vertical
    assert ed.document.shape(t.id).geom.as_tuple() == g0.as_tuple()


def test_button_applies_to_the_whole_selection(ed):
    bar = ed.property_bar.text_style
    a = _add(ed, "AB")
    b = _add(ed, "CD", text_vertical=True)
    ed.set_selection([a.id, b.id])
    bar.refresh()
    assert not bar.vertical.isChecked()             # gemischt
    n0 = ed.undo_stack.count()
    bar.vertical.click()
    assert all(ed.document.shape(i).text_vertical for i in (a.id, b.id))
    assert ed.undo_stack.count() == n0 + 1
    c = _add(ed, "EF")
    ed.set_selection([a.id, b.id, c.id])
    bar.refresh()
    bar.vertical.click()
    assert all(ed.document.shape(i).text_vertical for i in (a.id, b.id, c.id))
    assert ed.undo_stack.count() == n0 + 2          # Makro, ein Schritt
    ed.undo_stack.undo()
    assert ed.document.shape(a.id).text_vertical and not ed.document.shape(c.id).text_vertical


def test_refresh_does_not_push_and_align_tooltips(ed):
    bar = ed.property_bar.text_style
    _add(ed, "AB\nC", text_vertical=True)
    n0 = ed.undo_stack.count()
    bar.refresh()
    assert bar.vertical.isChecked() and ed.undo_stack.count() == n0
    assert bar.align_buttons["left"].toolTip().startswith("Oben")
    assert bar.align_buttons["right"].toolTip().startswith("Unten")
    _add(ed, "AB\nC")
    bar.refresh()
    assert not bar.vertical.isChecked()
    assert bar.align_buttons["left"].toolTip().startswith("Linksbündig")


def test_align_button_on_vertical_text_keeps_the_left_edge(ed):
    bar = ed.property_bar.text_style
    t = _add(ed, "ABCD\nEF", text_vertical=True)
    bar.refresh()
    bar.align_buttons["right"].click()
    s = ed.document.shape(t.id)
    assert s.text_align == "right" and s.geom.x == pytest.approx(t.geom.x, abs=1e-9)
    assert s.geom.w == pytest.approx(t.geom.w, abs=1e-6)


def test_locked_layer_text_is_not_changed(ed):
    t = _add(ed)
    ed.document.layer(t.layer_id).locked = True
    bar = ed.property_bar.text_style
    n0 = ed.undo_stack.count()
    bar._vertical_toggled(True)
    assert ed.undo_stack.count() == n0 and not ed.document.shape(t.id).text_vertical


def test_editing_and_capitals_keep_vertical(ed):
    t = _add(ed, text_vertical=True)
    e = text_ui.with_layout(t, text="ab", case="upper")
    assert e.text_vertical and e.text == "ab"
    assert _elements(shape_text_path(e)) == _elements(text_path("AB", LINE_FONT_SANS, vertical=True))
    st = text_ui.with_style(t, italic=True)
    assert st.text_vertical


def test_canvas_item_is_vertical(ed, qapp):
    t = _add(ed)
    ed.property_bar.text_style.refresh()
    ed.property_bar.text_style.vertical.click()
    qapp.processEvents()
    item = next(i for i in ed.scene.items() if getattr(i, "shape_id", None) == t.id)
    r = item._path.boundingRect()
    assert r.height() > 2.5 * r.width()


def test_touch_mode_size(ed, qapp):
    bar = ed.property_bar.text_style
    _add(ed)
    bar.refresh()
    ed.set_touch_mode(True, persist=False)
    qapp.processEvents()
    try:
        assert bar.vertical.sizeHint().height() >= 40 and bar.vertical.sizeHint().width() >= 40
    finally:
        ed.set_touch_mode(False, persist=False)


def test_tooltip_names_xtool_and_the_layout():
    tip = text_ui.TIP_VERTICAL
    assert "xTool" in tip and "Spalte" in tip and "untereinander" in tip
    assert "oben / mittig / unten" in tip and "oben, mittig oder unten" in text_ui.TIP_ALIGN


def test_save_load_keeps_vertical(ed, tmp_path):
    from lumacut_canvas.document_io import load_into, save_document
    t = _add(ed, text_vertical=True)
    p = save_document(ed.document, tmp_path / "t.lcut")
    doc = Document()
    load_into(doc, p)
    assert doc.shape(t.id).text_vertical and doc.shape(t.id).geom.as_tuple() == t.geom.as_tuple()


def test_main_window_has_the_button(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    win = main.LumaCutStudio()
    ed = win.canvas
    t = _add(ed)
    bar = ed.property_bar.text_style
    bar.refresh()
    bar.vertical.click()
    assert ed.document.shape(t.id).text_vertical
    ed.undo_stack.setClean()
    win.close()
