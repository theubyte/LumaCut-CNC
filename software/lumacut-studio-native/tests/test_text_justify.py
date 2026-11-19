"""Blocksatz für mehrzeiligen Text (wie der Blocksatz einer Textverarbeitung; LightBurns
*Align X* kennt nur links / mittig / rechts): jede Zeile außer der letzten wird an den
Wortlücken bis zur Laufweite der breitesten Zeile gedehnt – Wortlücken, Modell, Datei, Umriss
(Umriss- und Einlinien-Schrift, senkrecht), Box, Folgefunktionen, Bedienung."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PySide6.QtGui import QFontMetricsF

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas import icons, text_ui  # noqa: E402
from lumacut_canvas.editor import CanvasEditor  # noqa: E402
from lumacut_canvas.linefont import (LINE_FONT_SANS, justified, justify_shifts,  # noqa: E402
                                     line_advance, text_strokes, word_starts)
from lumacut_canvas.linefont import EM_UNITS  # noqa: E402
from lumacut_canvas.model import (TEXT_ALIGN_LABELS, TEXT_ALIGNS, TEXT_VALIGN_LABELS,  # noqa: E402
                                  Document, Geometry, Shape, read_text_align,
                                  read_text_layout, text_anchor, text_layout)
from lumacut_canvas.shape_paths import (shape_text_path, text_aspect, text_font,  # noqa: E402
                                        text_path)

FAMILY = "DejaVu Sans"
PITCH = 125.0                   # Zeilenabstand 1,25 × 100 pt (Aufbau-Einheiten)
TEXT = "Ein Satz mit Wörtern\nkurze Zeile da\nSchluss hier"


def _real_fonts(qapp):
    r = text_path("Il", FAMILY).boundingRect()
    w = text_path("WW", FAMILY).boundingRect()
    if w.width() <= r.width() * 1.05:
        pytest.skip("Keine echten Schriften auf diesem System (Ersatzkästen statt Glyphen)")


def _elements(path):
    return [(e.type, round(e.x, 9), round(e.y, 9)) for e in
            (path.elementAt(i) for i in range(path.elementCount()))]


def _subs(path):
    """Teilpfade als (Zeile, Box) in Zeichenreihenfolge."""
    out = []
    for poly in path.toSubpathPolygons():
        r = poly.boundingRect()
        out.append((round((r.center().y() + 35.0) / PITCH), r))
    return out


def _rows(path):
    """(links, rechts) der Tinte je Zeile."""
    rows: dict[int, list[float]] = {}
    for row, r in _subs(path):
        lo, hi = rows.get(row, [1e18, -1e18])
        rows[row] = [min(lo, r.left()), max(hi, r.right())]
    return rows


def _text(text=TEXT, family=FAMILY, h=30.0, **kw):
    s = Shape("text", Geometry(20, 30, 10, h), "L1", text=text, font_family=family, **kw)
    s.geom.w = h * text_aspect(text, family, **text_layout(s))
    return s


def _doc_with(*shapes):
    doc = Document()
    for s in shapes:
        s.layer_id = doc.active_layer_id
        doc.add_shape(s)
    return doc


# --- Wortlücken ------------------------------------------------------------------------------

def test_word_starts_only_inner_gaps():
    assert word_starts("ab cd ef") == [3, 6]
    assert word_starts("ab   cd") == [5]                  # ein Lauf von Leerzeichen = eine Lücke
    assert word_starts("  ab cd  ") == [5]                 # Einzug und Ende sind keine Lücke
    assert word_starts("Wort") == [] and word_starts("") == [] and word_starts("   ") == []


def test_justified_lines_all_but_the_last_with_a_gap():
    lines = ["ab cd", "einwort", "x y", "letzte zeile"]
    assert [justified(lines, i) for i in range(4)] == [True, False, True, False]
    assert not justified(["ab cd"], 0)


def test_shifts_share_the_extra_evenly():
    assert justify_shifts("ab cd e", 6.0) == [0, 0, 0, 3, 3, 3, 6]
    assert justify_shifts("ab", 5.0) == [0, 0]
    assert justify_shifts("ab cd", 0.0) == [0, 0, 0, 0, 0]
    s = justify_shifts("  a  b c  ", 4.0)
    assert s[:5] == [0] * 5 and s[5:7] == [2, 2] and s[7:] == [4, 4, 4]


# --- Modell und Datei ------------------------------------------------------------------------

def test_model_values_and_labels():
    assert TEXT_ALIGNS == ("left", "center", "right", "justify")
    assert TEXT_ALIGN_LABELS["justify"] == "Blocksatz"
    assert TEXT_VALIGN_LABELS["justify"].startswith("Blocksatz")
    assert read_text_align("justify") == "justify" and read_text_align("Justify") == "left"


def test_round_trip_in_the_existing_align_field(qapp):
    s = _text(text_align="justify")
    d = json.loads(json.dumps(s.to_dict()))
    assert d["align"] == "justify" and "justify" not in d
    back = Shape.from_dict(d)
    assert back.text_align == "justify" and text_layout(back)["align"] == "justify"
    assert read_text_layout({"align": "justify"})["text_align"] == "justify"


def test_old_project_file_unchanged(qapp):
    doc = _doc_with(_text(), _text("A\nB", text_align="right"))
    d = doc.to_dict()
    assert Document.from_dict(json.loads(json.dumps(d))).to_dict() == d
    assert "justify" not in json.dumps(d)


def test_anchor_top_left_like_left():
    assert text_anchor(_text(text_align="justify")) == (0.0, 0.0)
    assert text_anchor(_text(text_align="justify", text_vertical=True)) == (0.0, 0.0)


# --- Umriss (Umrissschrift) ------------------------------------------------------------------

def test_lines_end_at_the_widest_advance(qapp):
    _real_fonts(qapp)
    text = "aa bb ca\nkurz a\nlange Zeile hier a\nletzte a"
    font = text_font(FAMILY)
    fm = QFontMetricsF(font)
    left, just = _rows(text_path(text, FAMILY)), _rows(text_path(text, FAMILY, align="justify"))
    widest_row = 2
    assert just[widest_row] == pytest.approx(left[widest_row])          # breiteste Zeile bleibt
    assert just[3] == pytest.approx(left[3])                            # letzte Zeile bleibt links
    for row in (0, 1):                                                 # alle enden auf „a“
        assert just[row][0] == pytest.approx(left[row][0])              # Anfang bleibt
        assert just[row][1] == pytest.approx(just[widest_row][1], abs=0.5)
        assert just[row][1] > left[row][1] + 50
    lines = text.split("\n")
    assert max(fm.horizontalAdvance(x) for x in lines) == pytest.approx(
        fm.horizontalAdvance(lines[widest_row]))


def test_words_only_move_sideways_by_equal_steps(qapp):
    _real_fonts(qapp)
    text = "Ein Satz mit vier\nWörter und noch viel mehr Text"
    left = _subs(text_path(text, FAMILY))
    just = _subs(text_path(text, FAMILY, align="justify"))
    assert len(left) == len(just)
    shifts = []
    for (ra, a), (rb, b) in zip(left, just):
        assert ra == rb
        assert (b.top(), b.width(), b.height()) == pytest.approx((a.top(), a.width(), a.height()), abs=1e-6)
        if ra == 0:
            shifts.append(round(b.left() - a.left(), 4))
        else:
            assert b.left() == pytest.approx(a.left(), abs=1e-9)    # letzte Zeile unverändert
    steps = sorted(set(shifts))
    assert len(steps) == 4 and steps[0] == pytest.approx(0.0, abs=1e-6)  # vier Wörter, drei Lücken
    gaps = [steps[k + 1] - steps[k] for k in range(3)]
    assert gaps == pytest.approx([gaps[0]] * 3, abs=0.05) and gaps[0] > 10


def test_single_line_lines_without_gap_and_indent(qapp):
    _real_fonts(qapp)
    assert _elements(text_path("Hallo Welt", FAMILY, align="justify")) == \
        _elements(text_path("Hallo Welt", FAMILY))                       # eine Zeile: wie links
    t = "Einwort\nzwei Worte und mehr"
    assert _rows(text_path(t, FAMILY, align="justify"))[0] == pytest.approx(_rows(text_path(t, FAMILY))[0])
    ind = "   ab cd\nlange lange Zeile"
    li, ju = _rows(text_path(ind, FAMILY)), _rows(text_path(ind, FAMILY, align="justify"))
    assert ju[0][0] == pytest.approx(li[0][0]) and li[0][0] > 50        # Einzug bleibt
    assert ju[0][1] > li[0][1] + 50


def test_trailing_spaces_do_not_count(qapp):
    _real_fonts(qapp)
    a = text_path("ab ca   \nlange Zeile a\nx", FAMILY, align="justify")
    b = text_path("ab ca\nlange Zeile a\nx", FAMILY, align="justify")
    assert _rows(a)[0] == pytest.approx(_rows(b)[0], abs=1e-6)
    assert _rows(b)[0][1] == pytest.approx(_rows(b)[1][1], abs=0.5)      # beide enden auf „a“


def test_letter_spacing_and_line_spacing_combine(qapp):
    _real_fonts(qapp)
    text = "aa ba\nlang lang a"
    for ls in (-20.0, 40.0):
        r = _rows(text_path(text, FAMILY, align="justify", letter_spacing=ls))
        assert r[0][1] == pytest.approx(r[1][1], abs=0.5)
    p = text_path(text, FAMILY, align="justify", line_spacing=200)
    ys = sorted({round(b.bottom()) for _, b in _subs(p)})
    assert ys[-1] - ys[0] > 1.5 * PITCH


def test_box_and_aspect_follow_the_widest_line(qapp):
    _real_fonts(qapp)
    assert text_aspect(TEXT, FAMILY, align="justify") == pytest.approx(text_aspect(TEXT, FAMILY), rel=0.02)


# --- Einlinien-Schrift -----------------------------------------------------------------------

def _stroke_rows(strokes, pitch):
    rows: dict[int, list[float]] = {}
    for s in strokes:
        y = sum(p[1] for p in s) / len(s)
        row = round(y / pitch)
        xs = [p[0] for p in s]
        lo, hi = rows.get(row, [1e18, -1e18])
        rows[row] = [min(lo, min(xs)), max(hi, max(xs))]
    return rows


def test_line_font_strokes_justified():
    text = "aa ba\nkurz und klein a\nlange Zeile mit a\nende a"
    pitch = 1.25 * EM_UNITS * 0.75
    left = text_strokes(text, LINE_FONT_SANS)
    just = text_strokes(text, LINE_FONT_SANS, align="justify")
    assert len(left) == len(just)
    for a, b in zip(left, just):                                      # nur seitlich verschoben
        dx = b[0][0] - a[0][0]
        assert all(q[1] == p[1] and q[0] - p[0] == pytest.approx(dx, abs=1e-9) for p, q in zip(a, b))
    lines = text.split("\n")
    ink = [line_advance(x.rstrip(), LINE_FONT_SANS) for x in lines]
    w = max(ink)
    jr = _stroke_rows(just, pitch)
    lr = _stroke_rows(left, pitch)
    widest = ink.index(w)
    for row in range(3):
        assert jr[row][1] == pytest.approx(jr[widest][1], abs=1e-6)     # alle enden auf „a“
    assert jr[3] == pytest.approx(lr[3])


def test_line_font_text_path_and_italic(qapp):
    p = text_path("ab cd\nlange Zeile", LINE_FONT_SANS, align="justify", italic=True)
    q = text_path("ab cd\nlange Zeile", LINE_FONT_SANS, italic=True)
    assert p.elementCount() == q.elementCount()
    assert _elements(text_path("ab cd", LINE_FONT_SANS, align="justify")) == \
        _elements(text_path("ab cd", LINE_FONT_SANS))


def _old_text_strokes(text, family, italic=False, *, letter_spacing=0.0, line_spacing=100.0,
                      align="left", pitch_units=1.25 * EM_UNITS * 0.75):
    """text_strokes vor dem Blocksatz (Referenz für unveränderte Ausgabe)."""
    from lumacut_canvas.linefont import BASE_LINE, ITALIC_SLANT, glyph
    extra = letter_spacing / 100.0 * EM_UNITS
    pitch = pitch_units * (line_spacing / 100.0 if line_spacing != 100.0 else 1.0)
    lines = (text or "").split("\n")
    adv = [line_advance(line, family, extra) for line in lines]
    widest = max(adv) if adv else 0.0
    share = {"center": 0.5, "right": 1.0}.get(align, 0.0) if len(lines) > 1 else 0.0
    out = []
    for i, line in enumerate(lines):
        x = (widest - adv[i]) * share
        dy = i * pitch
        for ch in line:
            g = glyph(family, ch)
            for st in g.strokes:
                pts = []
                for gx, gy in st:
                    px = x + gx - g.left
                    if italic:
                        px += ITALIC_SLANT * (BASE_LINE - gy)
                    pts.append((px, gy + dy))
                out.append(pts)
            x += g.advance + extra
    return out


@pytest.mark.parametrize("align", ["left", "center", "right", "bogus"])
def test_left_center_right_strokes_unchanged(align):
    text = "ab cd\nlange Zeile\n  x"
    for kw in ({}, {"italic": True, "letter_spacing": 12.5, "line_spacing": 150.0}):
        assert text_strokes(text, LINE_FONT_SANS, align=align, **kw) == \
            _old_text_strokes(text, LINE_FONT_SANS, align=align, **kw)


def test_outline_paths_unchanged_for_the_old_alignments(qapp):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath
    font = text_font(FAMILY)
    path = QPainterPath()
    for i, line in enumerate("ab cd\nlange Zeile".split("\n")):
        path.addText(QPointF(0, i * PITCH), font, line)
    assert _elements(text_path("ab cd\nlange Zeile", FAMILY)) == _elements(path)


# --- Senkrecht -------------------------------------------------------------------------------

def test_vertical_columns_stretched_to_the_longest(qapp):
    text = "a b\nlangeSpalte\nc d"
    left = text_path(text, LINE_FONT_SANS, vertical=True)
    just = text_path(text, LINE_FONT_SANS, vertical=True, align="justify")
    cols: dict[int, list[float]] = {}
    colsl: dict[int, list[float]] = {}
    for target, path in ((cols, just), (colsl, left)):
        for poly in path.toSubpathPolygons():
            r = poly.boundingRect()
            c = round(r.center().x() / (1.25 * 133.333))
            lo, hi = target.get(c, [1e18, -1e18])
            target[c] = [min(lo, r.top()), max(hi, r.bottom())]
    # Spalte 0 („a b“, 3 Zeichen) reicht bis zur Höhe des letzten Zeichens der langen Spalte
    assert cols[0][0] == pytest.approx(colsl[0][0])
    assert cols[0][1] > colsl[0][1] + 7 * PITCH
    assert cols[2] == pytest.approx(colsl[2])                       # letzte Spalte bleibt
    assert cols[1] == pytest.approx(colsl[1])                       # längste Spalte bleibt


# --- Folgefunktionen -------------------------------------------------------------------------

@pytest.mark.parametrize("family", [FAMILY, LINE_FONT_SANS])
def test_job_and_gcode_pi_safe(qapp, family):
    from lumacut_canvas.toolpath import parse_gcode
    from lumacut_job.planner import optimized_document_gcode
    j = _text("aa bb cc\nlange lange Zeile", family, text_align="justify")
    left = j.copy()
    left.text_align = "left"
    g = optimized_document_gcode(_doc_with(j), scan_offsets=None)
    pi_check(g)
    gl = optimized_document_gcode(_doc_with(left), scan_offsets=None)
    assert g != gl
    assert parse_gcode(g).cut_length_mm == pytest.approx(parse_gcode(gl).cut_length_mm, rel=0.01)


def test_document_gcode_unchanged_without_justify(qapp):
    from lumacut_canvas.gcode import document_to_gcode
    doc = _doc_with(_text("aa bb\nlange Zeile", text_align="right"))
    g0 = document_to_gcode(doc)
    doc2 = Document.from_dict(json.loads(json.dumps(doc.to_dict())))
    assert document_to_gcode(doc2) == g0
    doc2.shapes[0].text_align = "justify"
    assert document_to_gcode(doc2) != g0


def test_text_to_path_svg_weld_and_serials(qapp, tmp_path):
    _real_fonts(qapp)
    from lumacut_canvas.export import export_svg
    from lumacut_canvas.pathops import shape_area, text_to_outline
    from lumacut_job.serial import SerialSpec, serial_shapes
    s = _text("aa bb\nlange Zeile", text_align="justify")
    o = text_to_outline(s)
    assert o is not None and o.bounds().w == pytest.approx(s.geom.w, rel=0.01)
    a = tmp_path / "a.svg"
    export_svg(_doc_with(s), a)
    assert a.stat().st_size > 0
    w = s.copy()
    w.text_weld = True
    assert shape_area(w).area == pytest.approx(shape_area(s).area, rel=0.01)
    shapes = serial_shapes(_text("Nr {n} a\nlang lang", text_align="justify"),
                           SerialSpec("Nr {n} a\nlang lang", start=1, count=2), text_aspect)
    assert all(sh.text_align == "justify" for sh in shapes)


def test_variable_text_keeps_justify(qapp, tmp_path):
    from lumacut_job import vartext as vt
    s = _text("ab cd\nlange Zeile")
    s.text_align = "justify"
    out = vt.refit_text(s, "x y\nlängere Zeile hier", text_aspect)
    assert out.text_align == "justify" and out.geom.x == pytest.approx(s.geom.x)


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


def _add(ed, text="ab cd\nlange Zeile", **kw):
    s = _text(text, kw.pop("family", FAMILY), h=14.0, **kw)
    s.layer_id = ed.document.active_layer_id
    ed.document.add_shape(s)
    ed.set_selection([s.id])
    return ed.document.shape(s.id)


def test_button_exists_with_icon_and_tooltip(ed):
    bar = ed.property_bar.text_style
    b = bar.align_buttons["justify"]
    assert b.objectName() == "TextAlignJustify" and b.isCheckable()
    assert b.toolTip().startswith("Blocksatz") and "Wortlücken" in b.toolTip()
    assert "align_justify" in icons.available() and not icons.icon("align_justify").isNull()
    assert list(bar.align_buttons) == ["left", "center", "right", "justify"]


def test_click_justifies_in_one_undo_step_keeping_the_top_left(ed):
    bar = ed.property_bar.text_style
    t = _add(ed)
    bar.refresh()
    assert bar.align_buttons["justify"].isEnabled()
    n0 = ed.undo_stack.count()
    g0 = t.geom.copy()
    bar.align_buttons["justify"].click()
    s = ed.document.shape(t.id)
    assert s.text_align == "justify" and ed.undo_stack.count() == n0 + 1
    assert "Blocksatz" in ed.undo_stack.undoText()
    assert (s.geom.x, s.geom.y) == pytest.approx((g0.x, g0.y), abs=1e-9)
    assert s.geom.h == pytest.approx(g0.h, abs=1e-6)
    bar.refresh()
    assert bar.align_buttons["justify"].isChecked() and not bar.align_buttons["left"].isChecked()
    ed.undo_stack.undo()
    assert ed.document.shape(t.id).text_align == "left"


def test_single_line_disables_and_vertical_tooltip(ed):
    bar = ed.property_bar.text_style
    _add(ed, "nur eine Zeile")
    bar.refresh()
    assert not bar.align_buttons["justify"].isEnabled()
    _add(ed, "a b\nlang", text_vertical=True)
    bar.refresh()
    assert bar.align_buttons["justify"].isEnabled()
    assert bar.align_buttons["justify"].toolTip().startswith("Blocksatz (Spalten")


def test_canvas_item_shows_justified_text(ed, qapp):
    _real_fonts(qapp)
    t = _add(ed, "aa bb\nlange lange Zeile")
    ed.property_bar.text_style.refresh()
    ed.property_bar.text_style.align_buttons["justify"].click()
    qapp.processEvents()
    from lumacut_canvas.shape_paths import shape_path
    item = next(i for i in ed.scene.items() if getattr(i, "shape_id", None) == t.id)
    s = ed.document.shape(t.id)
    assert _elements(item._path) == _elements(shape_path(s))
    left = s.copy()
    left.text_align = "left"
    assert _elements(item._path) != _elements(shape_path(left))


def test_touch_mode_size(ed, qapp):
    bar = ed.property_bar.text_style
    _add(ed)
    bar.refresh()
    ed.set_touch_mode(True, persist=False)
    qapp.processEvents()
    try:
        b = bar.align_buttons["justify"]
        assert b.sizeHint().height() >= 40 and b.sizeHint().width() >= 40
    finally:
        ed.set_touch_mode(False, persist=False)


def test_save_load_keeps_justify(ed, tmp_path):
    from lumacut_canvas.document_io import load_into, save_document
    t = _add(ed, text_align="justify")
    p = save_document(ed.document, tmp_path / "t.lcut")
    doc = Document()
    load_into(doc, p)
    assert doc.shape(t.id).text_align == "justify"
    assert _elements(shape_text_path(doc.shape(t.id))) == _elements(shape_text_path(t))


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
    bar.align_buttons["justify"].click()
    assert ed.document.shape(t.id).text_align == "justify"
    ed.undo_stack.setClean()
    win.close()
