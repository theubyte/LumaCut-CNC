"""Text-Satz (LightBurn *Text › H-Space / V-Space / Align X*, xTool „Zeichenabstand“ /
„Zeilenabstand“ / „Ausrichtung“): Zeichenabstand, Zeilenabstand und Ausrichtung je
Textobjekt, mehrzeilig bearbeiten – Modell, Datei, Umriss, Box, Bedienung, G-Code."""

from __future__ import annotations

import json
import math

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QFontMetricsF, QPainterPath
from PySide6.QtWidgets import QInputDialog

from lumacut_canvas import text_ui
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import (LETTER_SPACING_RANGE, LINE_SPACING_RANGE, TEXT_ALIGNS, Document,
                                  Geometry, Shape, read_letter_spacing, read_line_spacing,
                                  read_text_align, read_text_layout, rotate_point, text_layout)
from lumacut_canvas.pathops import shape_area, text_to_outline
from lumacut_canvas.shape_paths import (_TEXT_BUILD_PT, em_units, local_path, shape_path, shape_text_path,
                                        text_aspect, text_font, text_path)

FAMILY = "DejaVu Sans"


def _old_text_path(text, family, bold=False, italic=False):
    """Umriss wie vor dem Text-Satz (Referenz für unveränderte Ausgabe)."""
    path = QPainterPath()
    font = text_font(family, bold, italic)
    for i, line in enumerate((text or " ").split("\n")):
        path.addText(QPointF(0, i * _TEXT_BUILD_PT * 1.25), font, line or " ")
    return path


def _elements(path):
    return [(e.type, round(e.x, 9), round(e.y, 9)) for e in
            (path.elementAt(i) for i in range(path.elementCount()))]


def _lines(path, pitch=_TEXT_BUILD_PT * 1.25):
    """Teilpfade nach Zeile (Grundlinie bei i · pitch) – (minx, maxx) je Zeile."""
    out: dict[int, list[float]] = {}
    for poly in path.toSubpathPolygons():
        ys = [p.y() for p in poly]
        xs = [p.x() for p in poly]
        row = round((sum(ys) / len(ys) + _TEXT_BUILD_PT * 0.35) / pitch)
        lo, hi = out.get(row, [math.inf, -math.inf])
        out[row] = [min(lo, min(xs)), max(hi, max(xs))]
    return out


def _real_fonts(qapp):
    r = text_path("Il", FAMILY).boundingRect()
    w = text_path("WW", FAMILY).boundingRect()
    if w.width() <= r.width() * 1.05:
        pytest.skip("Keine echten Schriften auf diesem System (Ersatzkästen statt Glyphen)")


def _text(text="AB\nABCDEF", **kw):
    return Shape("text", Geometry(20, 30, 40, 12), "L1", text=text, font_family=FAMILY, **kw)


@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1400, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, text="Hallo\nWelt", **kw):
    s = Shape("text", Geometry(20, 20, 40, 14), ed.document.active_layer_id, text=text,
              font_family=FAMILY, **kw)
    ed.document.add_shape(s)
    ed.set_selection([s.id])
    return ed.document.shape(s.id)


# --- Modell / Datei --------------------------------------------------------------------------

def test_defaults_and_file_keys_only_when_set():
    s = _text()
    assert (s.letter_spacing, s.line_spacing, s.text_align) == (0.0, 100.0, "left")
    d = s.to_dict()
    assert not {"letter_spacing", "line_spacing", "align"} & set(d)
    assert text_layout(s) == {}
    t = _text(letter_spacing=12.5, line_spacing=150, text_align="center")
    d = json.loads(json.dumps(t.to_dict()))
    assert (d["letter_spacing"], d["line_spacing"], d["align"]) == (12.5, 150, "center")
    back = Shape.from_dict(d)
    assert (back.letter_spacing, back.line_spacing, back.text_align) == (12.5, 150.0, "center")
    assert text_layout(back) == {"letter_spacing": 12.5, "line_spacing": 150.0, "align": "center"}
    assert back.to_dict() == t.to_dict()


def test_old_file_loads_with_defaults_and_saves_identically():
    d = {"id": "t1", "kind": "text", "layer": "L1", "x": 1, "y": 2, "w": 30, "h": 8,
         "text": "Alt", "font": FAMILY}
    s = Shape.from_dict(d)
    assert (s.letter_spacing, s.line_spacing, s.text_align) == (0.0, 100.0, "left")
    assert s.to_dict() == {**d, "x": 1, "y": 2}


@pytest.mark.parametrize("raw, want", [
    (None, 0.0), ("x", 0.0), (True, 0.0), (float("nan"), 0.0), (float("inf"), 0.0), ([1], 0.0),
    ("15", 15.0), (-500, LETTER_SPACING_RANGE[0]), (900, LETTER_SPACING_RANGE[1]), (3.14159, 3.142)])
def test_broken_letter_spacing(raw, want):
    assert read_letter_spacing(raw) == want


@pytest.mark.parametrize("raw, want", [
    (None, 100.0), ("x", 100.0), (False, 100.0), (float("nan"), 100.0), (float("-inf"), 100.0),
    ("120", 120.0), (1, LINE_SPACING_RANGE[0]), (10_000, LINE_SPACING_RANGE[1])])
def test_broken_line_spacing(raw, want):
    assert read_line_spacing(raw) == want


@pytest.mark.parametrize("raw", [None, "", "LEFT", "middle", 1, ["center"], True])
def test_broken_align_is_left(raw):
    assert read_text_align(raw) == "left"


def test_known_aligns_and_layout_only_for_text():
    assert all(read_text_align(a) == a for a in TEXT_ALIGNS)
    d = {"kind": "rect", "layer": "L1", "x": 0, "y": 0, "w": 5, "h": 5,
         "letter_spacing": 20, "line_spacing": 200, "align": "right"}
    r = Shape.from_dict(d)
    assert (r.letter_spacing, r.line_spacing, r.text_align) == (0.0, 100.0, "left")
    assert not {"letter_spacing", "line_spacing", "align"} & set(r.to_dict())
    assert read_text_layout({}) == {"letter_spacing": 0.0, "line_spacing": 100.0, "text_align": "left"}


# --- Umriss ----------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["LumaCut", "AB\nABCDEF", "", "a\n\nb", "Ä g\n  x"])
def test_default_outline_unchanged(qapp, text):
    assert _elements(text_path(text, FAMILY)) == _elements(_old_text_path(text, FAMILY))
    assert _elements(text_path(text, FAMILY, True, True)) == _elements(
        _old_text_path(text, FAMILY, True, True))
    s = _text(text)
    assert _elements(shape_text_path(s)) == _elements(_old_text_path(text, FAMILY))


def test_letter_spacing_adds_per_gap(qapp):
    _real_fonts(qapp)
    base = text_path("ABCD", FAMILY).boundingRect()
    wide = text_path("ABCD", FAMILY, letter_spacing=10).boundingRect()
    em = em_units(text_font(FAMILY))
    assert wide.width() - base.width() == pytest.approx(3 * 0.1 * em, abs=0.6)   # 3 Lücken
    assert wide.height() == pytest.approx(base.height())
    tight = text_path("ABCD", FAMILY, letter_spacing=-10).boundingRect()
    assert tight.width() < base.width()
    assert text_aspect("ABCD", FAMILY, letter_spacing=10) > text_aspect("ABCD", FAMILY)


def test_line_spacing_scales_the_pitch(qapp):
    _real_fonts(qapp)
    one = text_path("A\nA", FAMILY).boundingRect()
    two = text_path("A\nA", FAMILY, line_spacing=200).boundingRect()
    pitch = _TEXT_BUILD_PT * 1.25
    assert two.height() - one.height() == pytest.approx(pitch, abs=1e-6)
    half = text_path("A\nA", FAMILY, line_spacing=50).boundingRect()
    assert one.height() - half.height() == pytest.approx(pitch / 2, abs=1e-6)
    # eine Zeile: Zeilenabstand ohne Wirkung
    assert _elements(text_path("A", FAMILY, line_spacing=300)) == _elements(text_path("A", FAMILY))


def test_alignment_by_advance(qapp):
    _real_fonts(qapp)
    fm = QFontMetricsF(text_font(FAMILY))
    left = _lines(text_path("AB\nXXAB", FAMILY))
    right = _lines(text_path("AB\nXXAB", FAMILY, align="right"))
    assert right[0][1] == pytest.approx(right[1][1], abs=0.5)        # gleiche rechte Kante
    shift = fm.horizontalAdvance("XXAB") - fm.horizontalAdvance("AB")
    assert right[0][0] - left[0][0] == pytest.approx(shift, abs=1e-6)
    centre = _lines(text_path("AB\nXXAB", FAMILY, align="center"))
    assert centre[0][0] - left[0][0] == pytest.approx(shift / 2, abs=1e-6)
    assert centre[1] == pytest.approx(left[1])                       # breiteste Zeile bleibt
    # eine Zeile: Ausrichtung ohne Wirkung
    for a in TEXT_ALIGNS:
        assert _elements(text_path("AB", FAMILY, align=a)) == _elements(text_path("AB", FAMILY))


def test_alignment_with_letter_spacing_keeps_right_edges(qapp):
    _real_fonts(qapp)
    right = _lines(text_path("AB\nXXAB", FAMILY, align="right", letter_spacing=30))
    assert right[0][1] == pytest.approx(right[1][1], abs=0.5)


def test_shape_outline_fills_the_box(qapp):
    s = _text(letter_spacing=25, line_spacing=180, text_align="right")
    r = local_path(s).boundingRect()
    assert (r.x(), r.y(), r.width(), r.height()) == pytest.approx((20, 30, 40, 12))
    assert _elements(local_path(s)) != _elements(local_path(_text()))


# --- Box anpassen (with_layout) --------------------------------------------------------------

def _scale(s):
    r = shape_text_path(s).boundingRect()
    return abs(s.geom.w) / r.width(), abs(s.geom.h) / r.height()


def test_with_layout_keeps_letter_size_and_left_top(qapp):
    _real_fonts(qapp)
    s = _text()
    o = text_ui.with_layout(s, letter_spacing=20)
    assert o.letter_spacing == 20 and o.geom.w > s.geom.w and o.geom.h == pytest.approx(s.geom.h)
    assert _scale(o) == pytest.approx(_scale(s))
    assert (o.geom.x, o.geom.y) == (s.geom.x, s.geom.y)
    o2 = text_ui.with_layout(s, line_spacing=200)
    assert o2.geom.h > s.geom.h and o2.geom.w == pytest.approx(s.geom.w)
    assert _scale(o2) == pytest.approx(_scale(s))
    assert (o2.geom.x, o2.geom.y) == (s.geom.x, s.geom.y)
    assert s.letter_spacing == 0 and s.geom.w == 40       # Original unverändert


def test_with_layout_anchor_by_alignment(qapp):
    _real_fonts(qapp)
    s = _text(text_align="center")
    o = text_ui.with_layout(s, letter_spacing=30)
    assert o.geom.x + o.geom.w / 2 == pytest.approx(s.geom.x + s.geom.w / 2)
    r = _text(text_align="right")
    o = text_ui.with_layout(r, letter_spacing=30)
    assert o.geom.x + o.geom.w == pytest.approx(r.geom.x + r.geom.w)
    assert o.geom.y == r.geom.y


def test_with_layout_rotated_keeps_the_anchor(qapp):
    _real_fonts(qapp)
    s = _text()
    s.geom.rot = 30.0
    g = s.geom
    before = rotate_point(g.x, g.y, *g.center(), g.rot)
    o = text_ui.with_layout(s, letter_spacing=40, line_spacing=150)
    h = o.geom
    assert rotate_point(h.x, h.y, *h.center(), h.rot) == pytest.approx(before)
    assert h.rot == 30.0 and _scale(o) == pytest.approx(_scale(s))


def test_with_layout_mirrored_and_clamped(qapp):
    _real_fonts(qapp)
    s = _text()
    s.geom.w = -40.0
    o = text_ui.with_layout(s, letter_spacing=999)
    assert o.letter_spacing == LETTER_SPACING_RANGE[1] and o.geom.w < -40.0
    assert text_ui.with_layout(s, align="bogus").text_align == "left"


def test_with_layout_new_text_grows_the_box(qapp):
    _real_fonts(qapp)
    s = _text("Hallo")
    o = text_ui.with_layout(s, text="Hallo\nWelt")
    assert o.text == "Hallo\nWelt" and o.geom.h > s.geom.h * 1.8
    assert _scale(o) == pytest.approx(_scale(s))


# --- Folgefunktionen -------------------------------------------------------------------------

def test_text_to_path_and_gcode_follow_the_layout(qapp):
    _real_fonts(qapp)
    from lumacut_canvas.export import job_layers
    doc = Document()
    lid = doc.active_layer_id
    s = _text()
    s.layer_id = lid
    doc.add_shape(s)
    plain = [[list(p) for p in jl.polylines] for jl in job_layers(doc)]
    spaced = text_ui.with_layout(s, letter_spacing=20, align="center")
    doc.remove_shape(s.id)
    doc.add_shape(spaced)
    out = [[list(p) for p in jl.polylines] for jl in job_layers(doc)]
    assert out != plain
    outline = text_to_outline(spaced)
    assert shape_area(outline).area == pytest.approx(shape_area(spaced).area, rel=1e-3)
    b = shape_path(outline).boundingRect()
    assert b.width() == pytest.approx(spaced.geom.w, abs=0.05)


def test_document_gcode_unchanged_without_layout(qapp):
    from lumacut_canvas.gcode import document_to_gcode
    doc = Document()
    s = _text()
    s.layer_id = doc.active_layer_id
    doc.add_shape(s)
    g0 = document_to_gcode(doc)
    doc2 = Document.from_dict(json.loads(json.dumps(doc.to_dict())))
    assert document_to_gcode(doc2) == g0
    doc2.shapes[0].letter_spacing = 10.0
    assert document_to_gcode(doc2) != g0


def test_serial_numbers_and_variable_text_keep_the_spacing(qapp):
    _real_fonts(qapp)
    from lumacut_job.serial import SerialSpec, serial_shapes
    from lumacut_job.vartext import refit_text
    src = _text("Nr 1", letter_spacing=40)
    src.geom.w = 12 * text_aspect("Nr 1", FAMILY, letter_spacing=40)
    src.geom.h = 12
    shapes = serial_shapes(src, SerialSpec("Nr {n}", start=1, count=2, columns=2), text_aspect)
    assert all(sh.letter_spacing == 40 for sh in shapes)
    assert shapes[0].geom.w == pytest.approx(src.geom.w)
    out = refit_text(src, "Nr 10", text_aspect)
    assert out.geom.w / out.geom.h == pytest.approx(text_aspect("Nr 10", FAMILY, letter_spacing=40))


def test_arc_text_spec_uses_the_layout_height(qapp):
    _real_fonts(qapp)
    from lumacut_job.arctext_qt import spec_from_text
    s = _text("AB\nAB")
    taller = text_ui.with_layout(s, line_spacing=200)
    assert spec_from_text(taller).height_mm == pytest.approx(spec_from_text(s).height_mm, abs=0.11)


# --- Bedienung -------------------------------------------------------------------------------

def test_controls_reflect_selection_and_enable_state(ed):
    bar = ed.property_bar.text_style
    one = _add(ed, "Hallo", letter_spacing=15)
    bar.refresh()
    assert not bar.isHidden() and bar.letter.value() == 15
    assert not bar.line.isEnabled() and not bar.align_buttons["center"].isEnabled()
    assert bar.multiline.isEnabled()
    two = _add(ed, "A\nBC", line_spacing=150, text_align="right")
    bar.refresh()
    assert bar.line.isEnabled() and bar.line.value() == 150
    assert bar.align_buttons["right"].isChecked() and not bar.align_buttons["left"].isChecked()
    ed.set_selection([one.id, two.id])
    bar.refresh()
    assert not any(b.isChecked() for b in bar.align_buttons.values())   # gemischt
    assert not bar.multiline.isEnabled()
    for w in (bar.letter, bar.line):
        assert w.toolTip() and w.suffix() == " %"


def test_spin_edits_undo_and_merge(ed):
    _real_fonts(ed)
    bar = ed.property_bar.text_style
    t = _add(ed)
    w0 = t.geom.w
    n0 = ed.undo_stack.count()
    bar.letter.setValue(10)
    bar.letter.setValue(20)
    s = ed.document.shape(t.id)
    assert s.letter_spacing == 20 and s.geom.w > w0
    assert ed.undo_stack.count() == n0 + 1                     # zusammengefasst
    assert ed.undo_stack.undoText() == "Zeichenabstand"
    bar.line.setValue(140)
    assert ed.document.shape(t.id).line_spacing == 140
    assert ed.undo_stack.count() == n0 + 2
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    back = ed.document.shape(t.id)
    assert (back.letter_spacing, back.line_spacing, back.geom.w) == (0.0, 100.0, w0)


def test_align_buttons_apply_to_all_selected_in_one_step(ed):
    bar = ed.property_bar.text_style
    a = _add(ed, "A\nBCD")
    b = _add(ed, "EF\nG", text_align="right")
    ed.set_selection([a.id, b.id])
    bar.refresh()
    n0 = ed.undo_stack.count()
    bar.align_buttons["center"].click()
    assert {ed.document.shape(i).text_align for i in (a.id, b.id)} == {"center"}
    assert ed.undo_stack.count() == n0 + 1 and "Zentriert" in ed.undo_stack.undoText()
    assert bar.align_buttons["center"].isChecked()
    ed.undo_stack.undo()
    assert ed.document.shape(a.id).text_align == "left"
    assert ed.document.shape(b.id).text_align == "right"
    # gleicher Wert: kein Undo-Schritt
    ed.set_selection([b.id])
    bar.refresh()
    n1 = ed.undo_stack.count()
    bar.align_buttons["right"].click()
    assert ed.undo_stack.count() == n1


def test_locked_layer_text_is_not_changed(ed):
    t = _add(ed, "A\nB")
    lay = ed.document.layer(t.layer_id)
    lay.locked = True
    bar = ed.property_bar.text_style
    bar.refresh()
    n0 = ed.undo_stack.count()
    bar._layout_edited("letter_spacing", 30.0, "Zeichenabstand")
    assert ed.undo_stack.count() == n0 and ed.document.shape(t.id).letter_spacing == 0


def test_multiline_edit_dialog(ed, monkeypatch):
    _real_fonts(ed)
    t = _add(ed, "Hallo")
    seen = {}

    def fake(parent, title, label, text):
        seen["text"] = text
        return "Hallo\r\nWelt", True
    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(fake))
    bar = ed.property_bar.text_style
    bar.refresh()
    h0 = t.geom.h
    n0 = ed.undo_stack.count()
    bar.multiline.click()
    s = ed.document.shape(t.id)
    assert seen["text"] == "Hallo" and s.text == "Hallo\nWelt"
    assert s.geom.h > h0 * 1.8 and ed.undo_stack.count() == n0 + 1
    assert ed.undo_stack.undoText() == "Text ändern"
    assert bar.line.isEnabled()                                 # jetzt mehrzeilig
    ed.undo_stack.undo()
    assert ed.document.shape(t.id).text == "Hallo"
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        staticmethod(lambda *a, **k: ("egal", False)))
    assert not bar.edit_multiline()
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        staticmethod(lambda *a, **k: ("  \n ", True)))
    assert not bar.edit_multiline() and ed.document.shape(t.id).text == "Hallo"


def test_double_click_multiline_text_opens_the_multiline_dialog(ed, monkeypatch):
    t = _add(ed, "Zeile 1\nZeile 2")
    calls = []
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(
        lambda *a, **k: calls.append("single") or ("x", False)))
    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(
        lambda *a, **k: calls.append("multi") or ("Zeile 1\nZeile 2\nZeile 3", True)))
    c = t.bounds()
    ed.tools.double_click(QPointF(c.x + c.w / 2, c.y + c.h / 2))
    assert calls == ["multi"]
    assert ed.document.shape(t.id).text.count("\n") == 2
    one = _add(ed, "Einzeilig")
    one_b = one.bounds()
    ed.document.remove_shape(t.id)
    ed.tools.double_click(QPointF(one_b.x + one_b.w / 2, one_b.y + one_b.h / 2))
    assert calls[-1] == "single"


def test_touch_mode_sizes(ed, qapp):
    bar = ed.property_bar.text_style
    _add(ed, "A\nB")
    bar.refresh()
    ed.set_touch_mode(True, persist=False)
    qapp.processEvents()
    try:
        for b in (*bar.align_buttons.values(), bar.multiline):
            assert b.sizeHint().height() >= 40 and b.sizeHint().width() >= 40
        for sp in (bar.letter, bar.line):
            assert sp.sizeHint().height() >= 34
    finally:
        ed.set_touch_mode(False, persist=False)


def test_icons_exist():
    from lumacut_canvas import icons
    for a in TEXT_ALIGNS:
        assert "align_" + a in icons.available() and not icons.icon("align_" + a).isNull()


def test_save_load_keeps_layout(ed, tmp_path):
    from lumacut_canvas.document_io import load_into, save_document
    t = _add(ed, "A\nBC", letter_spacing=-10, line_spacing=75, text_align="center")
    p = save_document(ed.document, tmp_path / "t.lcut")
    doc = Document()
    load_into(doc, p)
    s = doc.shape(t.id)
    assert (s.letter_spacing, s.line_spacing, s.text_align) == (-10.0, 75.0, "center")


def test_main_window_has_the_controls(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    win = main.LumaCutStudio()
    ed = win.canvas
    t = _add(ed, "A\nBCD")
    bar = ed.property_bar.text_style
    bar.refresh()
    bar.align_buttons["right"].click()
    bar.letter.setValue(5)
    s = ed.document.shape(t.id)
    assert s.text_align == "right" and s.letter_spacing == 5
    ed.undo_stack.setClean()
    win.close()
