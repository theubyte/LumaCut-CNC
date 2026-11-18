"""Eigene Einlinien-Schriften (LightBurn lädt eigene Single-Line-Fonts): SVG-Fonts (Inkscape
„Hershey Text“ / EMS, Relief SingleLine) und Hershey-``.jhf`` – Einlesen, Schriftordner,
fehlende Schrift, Satz, Auftrag, G-Code, Bogentext, Datei, Bedienung."""

from __future__ import annotations

import json
import math

import pytest
from _pi_guard import pi_check

from lumacut_canvas import linefont, linefont_data, text_ui
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.linefont import LINE_FONT_SANS, LINE_FONTS, USER_FONT_PREFIX, FontFileError
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.shape_paths import (LINE_FONT_EM, local_path, shape_polygons, text_aspect,
                                        text_em, text_path)
from lumacut_canvas.toolpath import parse_gcode

K = linefont.EM_UNITS / 1000.0          # Hershey-Einheiten je SVG-Font-Einheit (units-per-em 1000)
FAMILY = USER_FONT_PREFIX + "Test Stroke"

SVG_FONT = """<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd" >
<svg xmlns="http://www.w3.org/2000/svg" version="1.1"><defs>
<font id="TestStroke" horiz-adv-x="400">
<font-face font-family="Test Stroke" units-per-em="1000" ascent="800" descent="-200" cap-height="500"/>
<missing-glyph horiz-adv-x="300" d="M 50 0 L 250 0 L 250 600 L 50 600 Z" />
<glyph unicode="H" glyph-name="H" horiz-adv-x="700" d="M 100 0 L 100 700 M 600 0 L 600 700 M 100 350 L 600 350" />
<glyph unicode="I" horiz-adv-x="200" d="M 100 0 L 100 700" />
<glyph unicode="H" horiz-adv-x="999" d="M 0 0 L 999 999" />
<glyph unicode="O" horiz-adv-x="700" d="M 50 350 A 300 300 0 1 1 650 350 A 300 300 0 1 1 50 350 Z" />
<glyph unicode="c" horiz-adv-x="500" d="M 450 100 Q 250 -100 50 200 Q 250 500 450 300" />
<glyph unicode="o" horiz-adv-x="500" d="M 250 0 L 450 200 L 250 400 L 50 200 Z" />
<glyph unicode="-" horiz-adv-x="400" d="m 50 250 l 300 0" />
<glyph unicode="fi" horiz-adv-x="600" d="M 0 0 L 600 600" />
<glyph unicode="." horiz-adv-x="150" />
</font></defs></svg>
"""


def _font_file(tmp_path, text=SVG_FONT, name="test.svg"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def font(tmp_path):
    return linefont.install_font_file(_font_file(tmp_path))


def _text(text="HI", family=FAMILY, h=10.0, **kw):
    w = h * text_aspect(text, family)
    return Shape("text", Geometry(20, 30, w, h), "L1", text=text, font_family=family, **kw)


def _doc_with(*shapes, **layer):
    doc = Document()
    lid = doc.active_layer_id
    if layer:
        doc.update_layer(lid, **layer)
    for s in shapes:
        s.layer_id = lid
        doc.add_shape(s)
    return doc


def _length(polys):
    return sum(math.dist(p[i], p[i + 1]) for p in polys for i in range(len(p) - 1))


def _jhf_text(family=LINE_FONT_SANS):
    return "\n".join(line for line in getattr(linefont_data, LINE_FONTS[family].upper())
                     if line and not line.startswith("#"))


# --- SVG-Font lesen ------------------------------------------------------------------------------

def test_svg_font_name_em_and_baseline():
    name, glyphs, cap = linefont.parse_svg_font(SVG_FONT)
    assert name == "Test Stroke"
    h = glyphs["H"]
    assert (h.left, h.right) == (0.0, pytest.approx(700 * K))      # erste Glyphe gilt, nicht die doppelte
    assert h.strokes == [[(pytest.approx(100 * K), pytest.approx(9.0)), (pytest.approx(100 * K), pytest.approx(9.0 - 700 * K))],
                         [(pytest.approx(600 * K), 9.0), (pytest.approx(600 * K), pytest.approx(9.0 - 700 * K))],
                         [(pytest.approx(100 * K), pytest.approx(9.0 - 350 * K)), (pytest.approx(600 * K), pytest.approx(9.0 - 350 * K))]]
    assert cap == pytest.approx(700 * K)             # gemessen am „H“, nicht cap-height="500"


def test_svg_font_relative_commands_and_default_advance():
    _name, glyphs, _cap = linefont.parse_svg_font(SVG_FONT)
    dash = glyphs["-"]
    assert dash.strokes == [[(pytest.approx(50 * K), pytest.approx(9 - 250 * K)),
                             (pytest.approx(350 * K), pytest.approx(9 - 250 * K))]]
    assert glyphs["."].strokes == [] and glyphs["."].advance == pytest.approx(150 * K)


def test_closed_glyph_ends_on_its_start():
    _name, glyphs, _cap = linefont.parse_svg_font(SVG_FONT)
    (o,) = glyphs["o"].strokes
    assert o[0] == o[-1] and len(o) == 5


def test_arcs_and_curves_are_flattened_finely():
    _name, glyphs, _cap = linefont.parse_svg_font(SVG_FONT)
    (ring,) = glyphs["O"].strokes
    cx, cy, r = 350 * K, 9 - 350 * K, 300 * K
    assert len(ring) > 30 and math.dist(ring[0], ring[-1]) < 1e-6
    assert all(abs(math.dist(p, (cx, cy)) - r) < 1e-3 for p in ring)
    assert max(math.dist(ring[i], ring[i + 1]) for i in range(len(ring) - 1)) <= linefont.CURVE_STEP_UNITS + 1e-6
    (c,) = glyphs["c"].strokes
    assert c[0] == (pytest.approx(450 * K), pytest.approx(9 - 100 * K))
    assert c[-1] == (pytest.approx(450 * K), pytest.approx(9 - 300 * K))
    # Mitte der ersten Quadratkurve: 0,25·P0 + 0,5·P1 + 0,25·P2
    mid = (0.25 * 450 + 0.5 * 250 + 0.25 * 50, 0.25 * 100 + 0.5 * -100 + 0.25 * 200)
    assert min(math.dist(p, (mid[0] * K, 9 - mid[1] * K)) for p in c) < 0.05


def test_ligatures_skipped_missing_glyph_and_space_added():
    _name, glyphs, _cap = linefont.parse_svg_font(SVG_FONT)
    assert "fi" not in glyphs
    assert glyphs["?"].strokes and glyphs["?"].advance == pytest.approx(300 * K)    # <missing-glyph>
    assert glyphs[" "].strokes == [] and glyphs[" "].advance == pytest.approx(400 * K)
    assert glyphs["\u2013"] is glyphs["-"]                                       # Halbgeviertstrich


def test_cap_height_fallbacks():
    no_h = SVG_FONT.replace('unicode="H"', 'unicode="h"').replace('unicode="I"', 'unicode="i"')
    assert linefont.parse_svg_font(no_h)[2] == pytest.approx(500 * K)            # cap-height
    bare = no_h.replace('cap-height="500"', "")
    assert linefont.parse_svg_font(bare)[2] == pytest.approx(0.7 * linefont.EM_UNITS)


def test_other_units_per_em_scale_to_the_same_em():
    big = SVG_FONT.replace('units-per-em="1000"', 'units-per-em="2000"')
    a, b = linefont.parse_svg_font(SVG_FONT)[1]["H"], linefont.parse_svg_font(big)[1]["H"]
    assert b.advance == pytest.approx(a.advance / 2)


@pytest.mark.parametrize("data, word", [
    ("kein xml <", "kein gültiges SVG"),
    ('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L1 1"/></svg>', "<font>"),
    ('<svg><font><glyph unicode="A"/></font></svg>', "keine Glyphen"),
    ('<!DOCTYPE svg [<!ENTITY a "x">]><svg><font/></svg>', "Entity"),
])
def test_bad_svg_fonts_are_refused_in_german(data, word):
    with pytest.raises(FontFileError, match=word):
        linefont.parse_svg_font(data)


# --- Hershey .jhf --------------------------------------------------------------------------------

def test_jhf_file_gives_the_builtin_glyphs():
    glyphs, cap = linefont.parse_jhf_font(_jhf_text())
    builtin = linefont._builtin_font(LINE_FONT_SANS)
    assert cap == pytest.approx(21.0)
    for ch in "AHgxz09?":
        assert glyphs[ch].strokes == builtin[ch].strokes and glyphs[ch].advance == builtin[ch].advance


def test_jhf_wrapped_lines_like_the_original_files():
    lines = []
    for line in _jhf_text().splitlines():
        lines += [line[i:i + 72] for i in range(0, len(line), 72)]
    glyphs, _cap = linefont.parse_jhf_font("\n".join(lines))
    assert glyphs["B"].strokes == linefont._builtin_font(LINE_FONT_SANS)["B"].strokes
    assert len([ch for ch in glyphs if len(ch) == 1 and 32 <= ord(ch) < 127]) == 95


def test_broken_jhf_is_refused():
    with pytest.raises(FontFileError):
        linefont.parse_jhf_font("das ist keine Schrift")
    with pytest.raises(FontFileError, match="mitten"):
        linefont.parse_jhf_font("12345 30JZ")


def test_read_font_file_names_and_suffixes(tmp_path):
    assert linefont.read_font_file(_font_file(tmp_path))[0] == FAMILY
    p = tmp_path / "Meine Schrift.jhf"
    p.write_text(_jhf_text(), encoding="latin-1")
    assert linefont.read_font_file(p)[0] == USER_FONT_PREFIX + "Meine Schrift"
    with pytest.raises(FontFileError, match="nur SVG"):
        linefont.read_font_file(_font_file(tmp_path, name="x.ttf"))
    with pytest.raises(FontFileError, match="nicht lesbar"):
        linefont.read_font_file(tmp_path / "fehlt.svg")


def test_too_big_file_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(linefont, "MAX_FONT_BYTES", 100)
    with pytest.raises(FontFileError, match="zu groß"):
        linefont.read_font_file(_font_file(tmp_path))


# --- Schriftordner und Register ------------------------------------------------------------------

def test_install_copies_into_the_font_folder_and_lists_the_font(tmp_path):
    fam = linefont.install_font_file(_font_file(tmp_path))
    assert fam == FAMILY and linefont.is_line_font(fam) and linefont.is_user_font(fam)
    assert (linefont.user_font_dir() / "Test_Stroke.svg").exists()
    assert linefont.user_fonts() == [FAMILY]
    assert linefont.line_fonts() == list(LINE_FONTS) + [FAMILY]
    assert linefont.font_label(fam) == "Einlinie: Test Stroke" and linefont.font_available(fam)
    assert linefont.cap_units(fam) == pytest.approx(700 * K)
    assert linefont.cap_units(LINE_FONT_SANS) == 21.0


def test_reinstall_replaces_without_duplicate(tmp_path):
    linefont.install_font_file(_font_file(tmp_path))
    wider = SVG_FONT.replace('horiz-adv-x="200" d="M 100 0', 'horiz-adv-x="300" d="M 100 0')
    linefont.install_font_file(_font_file(tmp_path, wider, "neu.svg"))
    assert linefont.user_fonts() == [FAMILY]
    assert [p.name for p in linefont.user_font_dir().iterdir()] == ["Test_Stroke.svg"]
    assert linefont.glyph(FAMILY, "I").advance == pytest.approx(300 * K)


def test_fonts_are_read_from_the_folder_on_next_start(tmp_path):
    linefont.install_font_file(_font_file(tmp_path))
    (linefont.user_font_dir() / "kaputt.svg").write_text("<svg/>")
    linefont.clear_user_fonts()          # wie ein Neustart
    assert linefont.user_fonts() == [FAMILY]
    assert "kaputt.svg" in linefont.USER_FONT_ERRORS
    assert linefont.glyph(FAMILY, "I").strokes


def test_builtin_names_and_bare_prefix_are_not_user_fonts():
    assert not linefont.is_user_font(LINE_FONT_SANS) and linefont.is_line_font(LINE_FONT_SANS)
    assert not linefont.is_line_font(USER_FONT_PREFIX) and not linefont.is_line_font("DejaVu Sans")
    with pytest.raises(ValueError):
        linefont.register_font("DejaVu Sans", {})


def test_missing_font_falls_back_to_the_sans_and_is_named(tmp_path):
    fam = USER_FONT_PREFIX + "Test Stroke"
    assert linefont.is_line_font(fam) and not linefont.font_available(fam)
    assert linefont.font_label(fam) == "Einlinie: Test Stroke (fehlt)"
    assert linefont.glyph(fam, "H").strokes == linefont.glyph(LINE_FONT_SANS, "H").strokes
    note = linefont.missing_fonts_note([fam, LINE_FONT_SANS, "DejaVu Sans", fam])
    assert "„Test Stroke“" in note and "Sans" in note and "laden" in note
    assert linefont.missing_fonts_note([LINE_FONT_SANS]) == ""
    linefont.install_font_file(_font_file(tmp_path))       # danach die echte Schrift (Cache geleert)
    assert linefont.glyph(fam, "H").strokes != linefont.glyph(LINE_FONT_SANS, "H").strokes
    assert linefont.missing_fonts_note([fam]) == ""


def test_umlauts_composed_and_unknown_chars_as_missing_glyph(font):
    assert linefont.has_glyph(font, "Ö") and len(linefont.glyph(font, "Ö").strokes) == 3
    assert linefont.missing_chars("HOX", font) == "X"
    assert linefont.glyph(font, "X") is linefont.glyph(font, "?")


# --- Satz, Auftrag, G-Code ----------------------------------------------------------------------

def test_text_path_is_open_strokes_in_the_text_em(font):
    p = text_path("HI", font)
    assert text_em(font) == LINE_FONT_EM
    assert p.elementCount() == 2 * 4
    assert [p.elementAt(i).isMoveTo() for i in range(8)] == [True, False] * 4      # offen, kein Schließen
    s = _text("HI", font)
    polys = shape_polygons(s)
    assert len(polys) == 4 and all(len(q) == 2 for q in polys)
    ys = [y for q in polys for _x, y in q]
    assert min(ys) == pytest.approx(s.geom.y, abs=1e-6) and max(ys) == pytest.approx(s.geom.y + 10, abs=1e-6)


def test_size_in_pt_matches_the_em(font):
    s = _text("HI", font)
    pt = text_ui.size_pt(s)
    # Versalhöhe 0,7 em: 10 mm hoch = 10 / 0,7 mm Geviert
    assert pt * text_ui.MM_PER_PT == pytest.approx(10.0 / 0.7, rel=1e-3)
    assert text_ui.with_size_pt(s, 2 * pt).geom.h == pytest.approx(20.0)


def test_layout_spacing_and_vertical_work(font):
    s = _text("HI", font)
    assert text_ui.with_layout(s, letter_spacing=50.0).geom.w > s.geom.w
    v = text_ui.with_layout(s, vertical=True)
    assert v.geom.h > v.geom.w and all(len(q) == 2 for q in shape_polygons(v))


def test_gcode_is_pi_safe_one_pass_per_stroke(font, qapp):
    from lumacut_job.planner import optimized_document_gcode
    s = _text("HOc-I", font, h=8.0)
    g = optimized_document_gcode(_doc_with(s, fill_mode="hatch", line_interval_mm=0.1), scan_offsets=None)
    pi_check(g)
    assert parse_gcode(g).cut_length_mm == pytest.approx(_length(shape_polygons(s)), abs=0.05)


def test_fill_layer_does_not_fill_user_line_text(font, qapp):
    from lumacut_canvas.export import job_layers, layer_fill_blocks
    s = _text("OO", font)
    doc = _doc_with(s, fill_mode="hatch", line_interval_mm=0.3)
    assert layer_fill_blocks(doc, doc.layers[0]) == []
    (jl,) = job_layers(doc)
    assert not jl.fills and len(jl.polylines) == 2


def test_builtin_text_gcode_unchanged_by_an_installed_font(tmp_path, qapp):
    from lumacut_job.planner import optimized_document_gcode
    doc = _doc_with(_text("Hallo 42", LINE_FONT_SANS))
    before = optimized_document_gcode(doc, scan_offsets=None)
    linefont.install_font_file(_font_file(tmp_path))
    assert optimized_document_gcode(doc, scan_offsets=None) == before


def test_text_to_path_keeps_the_user_strokes(font, qapp):
    from lumacut_canvas.pathops import text_to_outline
    s = _text("HI", font)
    out = text_to_outline(s)
    assert out.kind == "path" and len(out.ring_ranges()) == 4


def test_save_load_stores_only_the_name(font, tmp_path, qapp):
    from lumacut_canvas.document_io import load_into, save_document
    doc = _doc_with(_text("HI", font))
    p = save_document(doc, tmp_path / "t.lcut")
    raw = json.loads(p.read_text(encoding="utf-8"))
    entry = next(sh for sh in raw["objects"] if sh.get("kind") == "text")
    builtin = json.loads(save_document(_doc_with(_text("HI", LINE_FONT_SANS)), tmp_path / "b.lcut")
                         .read_text(encoding="utf-8"))
    bentry = next(sh for sh in builtin["objects"] if sh.get("kind") == "text")
    assert set(entry) - {"id", "layer"} == set(bentry) - {"id", "layer"} and entry["font"] == font
    back = Document()
    load_into(back, p)
    assert back.shapes[0].font_family == font
    assert shape_polygons(back.shapes[0]) == shape_polygons(doc.shapes[0])


# --- Bogentext ---------------------------------------------------------------------------------

def test_arc_glyphs_use_the_user_cap_height(font, qapp):
    from lumacut_job.arctext_qt import glyphs_for
    (h, i) = glyphs_for("HI", font, 10.0)
    ys = [p[1] for r in h.rings for p in r]
    assert min(ys) == pytest.approx(-10.0) and max(ys) == pytest.approx(0.0)
    assert h.open and h.advance == pytest.approx(700 / 700 * 10.0)


def test_arc_spec_from_a_user_text_keeps_the_cap_height(font, qapp):
    from lumacut_job.arctext_qt import spec_from_text
    spec = spec_from_text(_text("HI", font, h=10.0))
    assert spec.font_family == font and spec.height_mm == pytest.approx(10.0, abs=0.05)


def test_arc_font_box_lists_user_and_missing_fonts(font, qapp):
    from lumacut_job.arctext_qt import font_kind_box
    box = font_kind_box(font)
    assert [box.itemData(i) for i in range(box.count())] == ["", *LINE_FONTS, font]
    assert box.currentData() == font
    gone = USER_FONT_PREFIX + "Weg"
    box2 = font_kind_box(gone)
    assert box2.currentData() == gone and box2.currentText() == "Einlinie: Weg (fehlt)"


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


def _add(ed, text="HI", family="DejaVu Sans", **kw):
    s = Shape("text", Geometry(20, 20, 10 * text_aspect(text, family), 10), ed.document.active_layer_id,
              text=text, font_family=family, **kw)
    ed.document.add_shape(s)
    ed.set_selection([s.id])
    return ed.document.shape(s.id)


def _items(bar):
    return [bar.stroke.itemData(i) for i in range(bar.stroke.count())]


def test_load_button_applies_the_font_in_one_undo_step(ed, tmp_path):
    msgs = []
    ed.notify = msgs.append
    bar = ed.property_bar.text_style
    t = _add(ed)
    bar.refresh()
    n0 = ed.undo_stack.count()
    bar.ask_font_path = lambda: str(_font_file(tmp_path))
    bar.load_font.click()
    s = ed.document.shape(t.id)
    assert s.font_family == FAMILY and ed.undo_stack.count() == n0 + 1
    assert ed.undo_stack.undoText() == "Einlinie: Test Stroke"
    assert s.geom.h == pytest.approx(10.0) and s.geom.w == pytest.approx(10 * text_aspect("HI", FAMILY))
    assert _items(bar) == ["", *LINE_FONTS, FAMILY] and bar.stroke.currentData() == FAMILY
    assert any("Test Stroke" in m and "geladen" in m for m in msgs)
    ed.undo_stack.undo()
    assert ed.document.shape(t.id).font_family == "DejaVu Sans"
    assert _items(bar) == ["", *LINE_FONTS, FAMILY]                  # die Schrift bleibt geladen


def test_load_without_selection_sets_the_font_for_new_texts(ed, tmp_path):
    bar = ed.property_bar.text_style
    n0 = ed.undo_stack.count()
    assert bar.load_line_font(str(_font_file(tmp_path))) == FAMILY
    assert ed.text_font_family == FAMILY and ed.undo_stack.count() == n0


def test_cancel_and_bad_file_change_nothing(ed, tmp_path):
    msgs = []
    ed.notify = msgs.append
    bar = ed.property_bar.text_style
    t = _add(ed)
    bar.refresh()
    n0 = ed.undo_stack.count()
    bar.ask_font_path = lambda: ""
    bar.load_font.click()
    bad = tmp_path / "bild.svg"
    bad.write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="5" height="5"/></svg>')
    assert bar.load_line_font(str(bad)) == ""
    assert ed.undo_stack.count() == n0 and ed.document.shape(t.id).font_family == "DejaVu Sans"
    assert msgs and "nicht geladen" in msgs[-1] and "Importieren" in msgs[-1]
    assert _items(bar) == ["", *LINE_FONTS] and not list(linefont.user_font_dir().iterdir())


def test_missing_font_shown_in_the_combo(ed):
    bar = ed.property_bar.text_style
    gone = USER_FONT_PREFIX + "Weg"
    _add(ed, family=gone)
    bar.refresh()
    assert bar.stroke.currentData() == gone and bar.stroke.currentText() == "Einlinie: Weg (fehlt)"
    _add(ed)
    bar.refresh()
    assert _items(bar) == ["", *LINE_FONTS]


def test_installing_a_missing_font_redraws_its_texts(ed, qapp, tmp_path):
    t = _add(ed, family=FAMILY)
    qapp.processEvents()
    item = ed.scene.items_by_id[t.id]
    pts = lambda path: [(round(path.elementAt(i).x, 4), round(path.elementAt(i).y, 4))  # noqa: E731
                        for i in range(path.elementCount())]
    before = pts(item._path)
    bar = ed.property_bar.text_style
    bar.refresh()
    assert bar.stroke.currentText().endswith("(fehlt)")
    n0 = ed.undo_stack.count()
    bar.load_line_font(str(_font_file(tmp_path)))
    qapp.processEvents()
    assert ed.undo_stack.count() == n0                       # gleiche Schrift: kein Undo-Schritt
    assert pts(item._path) != before and bar.stroke.currentText() == "Einlinie: Test Stroke"


def test_choose_installed_font_from_the_combo(ed, font):
    bar = ed.property_bar.text_style
    t = _add(ed)
    bar.refresh()
    idx = bar.stroke.findData(font)
    assert idx == len(LINE_FONTS) + 1
    bar.stroke.setCurrentIndex(idx)
    bar.stroke.activated.emit(idx)
    assert ed.document.shape(t.id).font_family == font
    assert not bar.family.isEnabled() and not bar.bold.isEnabled()


def test_missing_chars_note_names_the_user_font(ed, font):
    msgs = []
    ed.notify = msgs.append
    bar = ed.property_bar.text_style
    _add(ed, "HX")
    bar.refresh()
    idx = bar.stroke.findData(font)
    bar.stroke.setCurrentIndex(idx)
    bar.stroke.activated.emit(idx)
    assert msgs and "Einlinie: Test Stroke" in msgs[-1] and "X" in msgs[-1]


def test_load_button_touch_size_and_tooltip(ed, qapp):
    bar = ed.property_bar.text_style
    _add(ed)
    bar.refresh()
    tip = bar.load_font.toolTip()
    assert "LightBurn" in tip and ".svg" in tip and ".jhf" in tip and "Inkscape" in tip
    ed.set_touch_mode(True, persist=False)
    qapp.processEvents()
    try:
        assert bar.load_font.sizeHint().height() >= 40 and bar.load_font.sizeHint().width() >= 40
    finally:
        ed.set_touch_mode(False, persist=False)


def test_open_project_with_missing_font_warns(ed, tmp_path):
    from lumacut_canvas.document_io import save_document
    msgs = []
    ed.notify = msgs.append
    p = save_document(_doc_with(_text("HI", USER_FONT_PREFIX + "Weg")), tmp_path / "w.lcut")
    ed.load_file(p)
    assert "Geöffnet" in msgs[-1] and "„Weg“ fehlt" in msgs[-1]
    p2 = save_document(_doc_with(_text("HI", LINE_FONT_SANS)), tmp_path / "s.lcut")
    ed.load_file(p2)
    assert msgs[-1] == "Geöffnet: s.lcut"


def test_main_window_job_note_and_button(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    win = main.LumaCutStudio()
    try:
        ed = win.canvas
        _add(ed, family=USER_FONT_PREFIX + "Weg")
        g, note = win.job_tools.job_gcode(ask_inputs=False)
        pi_check(g)
        assert "„Weg“ fehlt" in note
        bar = ed.property_bar.text_style
        assert bar.load_font.objectName() == "TextLineFontLoad"
        ed.set_selection([])
        bar.load_line_font(str(_font_file(tmp_path)))
        _add(ed, family=FAMILY)
        _g, note2 = win.job_tools.job_gcode(ask_inputs=False)
        assert "Test Stroke" not in note2 and "„Weg“ fehlt" in note2
    finally:
        win.canvas.undo_stack.setClean()
        win.close()
