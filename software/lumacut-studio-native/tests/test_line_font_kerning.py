"""Kerning-Paare eigener Einlinien-Schriften (``<hkern>`` eines SVG-Fonts): Einlesen, Satz,
Blocksatz, Textbox, Bogentext, G-Code, Laden – eingebaute und ``.jhf``-Schriften unverändert."""

from __future__ import annotations

import math

import pytest
from _pi_guard import pi_check

from lumacut_canvas import linefont, text_ui
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.linefont import LINE_FONT_SANS, LINE_FONTS, USER_FONT_PREFIX
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.shape_paths import shape_polygons, text_aspect
from lumacut_canvas.toolpath import parse_gcode

K = linefont.EM_UNITS / 1000.0
FAMILY = USER_FONT_PREFIX + "Kern Test"
PLAIN = USER_FONT_PREFIX + "Kern Plain"

GLYPHS = """
<glyph unicode="A" glyph-name="A" horiz-adv-x="600" d="M 0 0 L 300 700 L 600 0" />
<glyph unicode="B" glyph-name="B" horiz-adv-x="600" d="M 0 0 L 0 700 L 600 350 L 0 0" />
<glyph unicode="V" glyph-name="V" horiz-adv-x="600" d="M 0 700 L 300 0 L 600 700" />
<glyph unicode="T" glyph-name="T" horiz-adv-x="500" d="M 0 700 L 500 700 M 250 700 L 250 0" />
<glyph unicode="o" glyph-name="o.alt,o" horiz-adv-x="500" d="M 0 200 L 250 0 L 500 200 L 250 400 Z" />
"""

KERNS = """
<hkern u1="A" u2="V" k="100" />
<hkern u1="A" u2="V" k="300" />
<hkern g1="T" g2="o" k="80" />
<hkern u1="U+0041-0042" u2="T" k="50" />
<hkern u1="V" g1="B" u2="A" k="-40" />
<hkern u1="Q" u2="A" k="70" />
<hkern u1="T" u2="A" k="0" />
<vkern u1="A" u2="V" k="999" />
"""


def _svg(name, kerns=KERNS, upm=1000, glyphs=GLYPHS):
    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<svg xmlns="http://www.w3.org/2000/svg" version="1.1"><defs>
<font id="k" horiz-adv-x="400">
<font-face font-family="{name}" units-per-em="{upm}" cap-height="700"/>
{glyphs}{kerns}
</font></defs></svg>
"""


def _install(tmp_path, name="Kern Test", kerns=KERNS, file="kern.svg"):
    p = tmp_path / file
    p.write_text(_svg(name, kerns), encoding="utf-8")
    return linefont.install_font_file(p)


@pytest.fixture
def font(tmp_path):
    return _install(tmp_path)


@pytest.fixture
def plain(tmp_path):
    return _install(tmp_path, "Kern Plain", "", "plain.svg")


def _text(text, family, h=10.0, **kw):
    return Shape("text", Geometry(20, 30, h * text_aspect(text, family), h), "L1",
                 text=text, font_family=family, **kw)


def _xs(strokes):
    return [x for s in strokes for x, _y in s]


# --- Einlesen ------------------------------------------------------------------------------------

def test_hkern_pairs_are_read_in_hershey_units():
    _name, glyphs, _cap = linefont.parse_svg_font(_svg("X"))
    assert isinstance(glyphs, dict) and isinstance(glyphs, linefont.KernedGlyphs)
    assert glyphs.kerning == pytest.approx({
        ("A", "V"): -100 * K,                       # erstes Paar gilt, das zweite nicht
        ("T", "o"): -80 * K,                        # über glyph-name (Liste „o.alt,o“)
        ("A", "T"): -50 * K, ("B", "T"): -50 * K,   # Unicode-Bereich U+0041-0042
        ("V", "A"): 40 * K, ("B", "A"): 40 * K,     # u1 und g1 zusammen, negatives k = weiter
    })


def test_pairs_with_unknown_chars_zero_k_and_vkern_are_skipped():
    _name, glyphs, _cap = linefont.parse_svg_font(_svg("X"))
    assert ("Q", "A") not in glyphs.kerning and ("T", "A") not in glyphs.kerning
    assert glyphs.kerning[("A", "V")] != pytest.approx(-999 * K)


def test_units_per_em_scale_the_pairs():
    _n, glyphs, _c = linefont.parse_svg_font(_svg("X", upm=2000))
    assert glyphs.kerning[("A", "V")] == pytest.approx(-100 * linefont.EM_UNITS / 2000.0)


def test_comma_list_and_space_in_u1():
    kerns = '<hkern u1="A,B" u2=" " k="60" /><hkern u1="U+0054" u2="A, V" k="20" />'
    _n, glyphs, _c = linefont.parse_svg_font(_svg("X", kerns, glyphs=GLYPHS + '<glyph unicode=" " horiz-adv-x="300" />'))
    assert glyphs.kerning == pytest.approx({("A", " "): -60 * K, ("B", " "): -60 * K,
                                            ("T", "A"): -20 * K, ("T", "V"): -20 * K})


def test_pair_count_is_limited(monkeypatch):
    monkeypatch.setattr(linefont, "MAX_KERN_PAIRS", 2)
    _n, glyphs, _c = linefont.parse_svg_font(_svg("X"))
    assert len(glyphs.kerning) == 2


def test_fonts_without_hkern_and_jhf_have_no_pairs(plain, tmp_path):
    assert linefont.kerning_pairs(plain) == 0 and linefont.kerning(plain, "A", "V") == 0.0
    jhf = "\n".join(line for line in getattr(linefont.linefont_data, LINE_FONTS[LINE_FONT_SANS].upper())
                    if line and not line.startswith("#"))
    p = tmp_path / "hand.jhf"
    p.write_text(jhf, encoding="latin-1")
    fam = linefont.install_font_file(p)
    assert linefont.kerning_pairs(fam) == 0 and linefont.kerning(fam, "A", "V") == 0.0


# --- Satz ----------------------------------------------------------------------------------------

def test_kerning_lookup(font):
    assert linefont.kerning_pairs(font) == 6
    assert linefont.kerning(font, "A", "V") == pytest.approx(-100 * K)
    assert linefont.kerning(font, "V", "A") == pytest.approx(40 * K)
    assert linefont.kerning(font, "V", "V") == 0.0
    assert linefont.kerning(font, "A", "\n") == 0.0


@pytest.mark.parametrize("family", list(LINE_FONTS))
def test_builtin_fonts_have_no_kerning(family, font):
    assert linefont.kerning(family, "A", "V") == 0.0 and linefont.kerning_pairs(family) == 0
    assert linefont.line_advance("AV", family) == pytest.approx(
        linefont.glyph(family, "A").advance + linefont.glyph(family, "V").advance)


def test_missing_font_has_no_kerning():
    gone = USER_FONT_PREFIX + "Weg"
    assert linefont.kerning(gone, "A", "V") == 0.0 and linefont.kerning_pairs(gone) == 0


def test_line_advance_includes_the_pairs(font, plain):
    assert linefont.line_advance("AV", plain) == pytest.approx(1200 * K)
    assert linefont.line_advance("AV", font) == pytest.approx(1100 * K)
    assert linefont.line_advance("AVA", font) == pytest.approx(1740 * K)
    assert linefont.line_advance("To", font) == pytest.approx(920 * K)
    # Zeichenabstand kommt zu jedem Zeichen dazu, das Kerning bleibt
    assert linefont.line_advance("AV", font, 10.0) == pytest.approx(1100 * K + 20.0)
    assert linefont.advances("AVA", font) == pytest.approx([500 * K, 640 * K, 600 * K])


def test_strokes_move_by_the_pair(font, plain):
    a = linefont.text_strokes("AV", font)
    b = linefont.text_strokes("AV", plain)
    assert len(a) == len(b) == 2
    assert _xs(a[:1]) == pytest.approx(_xs(b[:1]))                       # „A“ bleibt
    assert _xs(a[1:]) == pytest.approx([x - 100 * K for x in _xs(b[1:])])  # „V“ rückt heran


def test_composed_umlaut_and_tab_use_the_base_letter(font):
    assert linefont.kerning(font, "\u00c4", "V") == pytest.approx(-100 * K)   # „Ä“ wie „A“
    assert linefont.line_advance("\u00c4V", font) == pytest.approx(linefont.line_advance("AV", font))
    assert linefont.kerning(font, "A", "\t") == linefont.kerning(font, "A", " ")


def test_right_and_center_alignment_use_the_kerned_width(font):
    s = linefont.text_strokes("AV\nVV", font, align="right")
    right0 = max(_xs(s[:2]))
    right1 = max(_xs(s[2:]))
    assert right0 == pytest.approx(right1)


def test_justified_lines_end_flush_with_kerning(font):
    lines = linefont.text_strokes("AV A\nVVV V\nA", font, align="justify")
    assert len(lines) == 3 + 4 + 1
    first, second = lines[:3], lines[3:7]
    assert max(_xs(first)) == pytest.approx(max(_xs(second)))


def test_text_box_narrower_with_kerning(font, plain):
    assert text_aspect("AV", font) < text_aspect("AV", plain)
    assert text_aspect("AV", font) / text_aspect("AV", plain) == pytest.approx(1100 / 1200, rel=1e-3)
    assert text_aspect("VV", font) == pytest.approx(text_aspect("VV", plain))


def test_vertical_text_is_not_kerned(font, plain):
    v1 = text_ui.with_layout(_text("AV", font), vertical=True)
    v2 = text_ui.with_layout(_text("AV", plain), vertical=True)
    assert v1.geom.w == pytest.approx(v2.geom.w) and v1.geom.h == pytest.approx(v2.geom.h)


def test_letter_spacing_keeps_the_pair(font):
    s = _text("AV", font)
    wider = text_ui.with_layout(s, letter_spacing=50.0)
    assert wider.geom.w > s.geom.w


# --- Auftrag, Bogentext, Datei -------------------------------------------------------------------

def test_gcode_is_pi_safe_with_the_kerned_strokes(font, qapp):
    from lumacut_job.planner import optimized_document_gcode
    doc = Document()
    s = _text("AVTo", font, h=8.0)
    s.layer_id = doc.active_layer_id
    doc.add_shape(s)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    polys = shape_polygons(doc.shape(s.id))
    length = sum(math.dist(p[i], p[i + 1]) for p in polys for i in range(len(p) - 1))
    assert parse_gcode(g).cut_length_mm == pytest.approx(length, abs=0.05)


def test_shape_strokes_end_inside_the_box(font):
    s = _text("AVTo", font)
    xs = [x for q in shape_polygons(s) for x, _y in q]
    assert min(xs) >= s.geom.x - 1e-6 and max(xs) <= s.geom.x + s.geom.w + 1e-6


def test_arc_glyph_advances_are_kerned(font, plain, qapp):
    from lumacut_job.arctext_qt import glyphs_for
    a, v, last = glyphs_for("AVA", font, 10.0)
    pa, pv, plast = glyphs_for("AVA", plain, 10.0)
    assert a.advance == pytest.approx(pa.advance * 500 / 600)
    assert v.advance == pytest.approx(pv.advance * 640 / 600)
    assert last.advance == pytest.approx(plast.advance)


def _flat(polys):
    return [c for q in polys for p in q for c in p]


def test_save_load_keeps_only_the_name(font, tmp_path):
    from lumacut_canvas.document_io import load_into, save_document
    doc = Document()
    s = _text("AV", font)
    s.layer_id = doc.active_layer_id
    doc.add_shape(s)
    raw = save_document(doc, tmp_path / "k.lcut").read_text(encoding="utf-8")
    assert "hkern" not in raw and "kern" not in raw.replace(font, "")
    back = Document()
    load_into(back, tmp_path / "k.lcut")
    assert back.shapes[0].font_family == font
    assert _flat(shape_polygons(back.shapes[0])) == pytest.approx(_flat(shape_polygons(doc.shapes[0])))


def test_reinstall_without_pairs_drops_them(font, tmp_path):
    assert linefont.kerning_pairs(font) == 6
    _install(tmp_path, kerns="")
    assert linefont.kerning_pairs(font) == 0 and linefont.kerning(font, "A", "V") == 0.0


def test_pairs_come_back_after_a_restart(font):
    linefont.clear_user_fonts()
    assert linefont.kerning_pairs(font) == 6                     # Schriftordner neu gelesen
    assert linefont.kerning(font, "A", "V") == pytest.approx(-100 * K)


def test_builtin_text_unchanged_by_a_kerned_font(font, qapp):
    s = _text("AV To", LINE_FONT_SANS)
    before = shape_polygons(s)
    linefont.clear_user_fonts()
    assert _flat(shape_polygons(s)) == pytest.approx(_flat(before))


# --- Bedienung -----------------------------------------------------------------------------------

@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1200, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def test_load_message_names_the_pairs(ed, tmp_path):
    msgs = []
    ed.notify = msgs.append
    p = tmp_path / "kern.svg"
    p.write_text(_svg("Kern Test"), encoding="utf-8")
    assert ed.property_bar.text_style.load_line_font(str(p)) == FAMILY
    assert any("Kerning-Paare" in m and "6" in m for m in msgs)
    msgs.clear()
    q = tmp_path / "plain.svg"
    q.write_text(_svg("Kern Plain", ""), encoding="utf-8")
    assert ed.property_bar.text_style.load_line_font(str(q)) == PLAIN
    assert msgs and not any("Kerning" in m for m in msgs)
