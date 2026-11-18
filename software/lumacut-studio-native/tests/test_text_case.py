"""Großbuchstaben für Textobjekte (xTool „Originalschreibweise / Großbuchstaben“): der Text
bleibt gespeichert, wie er getippt wurde; Umriss, Box, G-Code, variabler Text, Seriennummern,
Bogentext-Vorbelegung und „In Pfade“ zeigen ihn in Versalien – Modell, Datei, Umriss,
Folgefunktionen, Bedienung."""

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
from lumacut_canvas.model import (TEXT_CASE_LABELS, TEXT_CASES, Document, Geometry, Shape,  # noqa: E402
                                  cased_text, display_text, read_text_case, text_layout)
from lumacut_canvas.shape_paths import (shape_polygons, shape_text_path, text_aspect,  # noqa: E402
                                        text_bounds, text_path)

FAMILY = "DejaVu Sans"
NOW = dt.datetime(2026, 11, 18, 9, 0, 0)


def _elements(path):
    return [(e.type, round(e.x, 9), round(e.y, 9)) for e in
            (path.elementAt(i) for i in range(path.elementCount()))]


def _text(text="Grüße aus Köln", family=LINE_FONT_SANS, h=10.0, **kw):
    s = Shape("text", Geometry(20, 30, 10, h), "L1", text=text, font_family=family, **kw)
    s.geom.w = h * text_aspect(text, family, **text_layout(s))
    return s


def _doc_with(*shapes):
    doc = Document()
    for s in shapes:
        s.layer_id = doc.active_layer_id
        doc.add_shape(s)
    return doc


# --- Modell und Datei ------------------------------------------------------------------------

def test_cased_text():
    assert cased_text("Grüße, straße 3 €", "upper") == "GRÜSSE, STRASSE 3 €"
    assert cased_text("äöü ÄÖÜ é", "upper") == "ÄÖÜ ÄÖÜ É"
    assert cased_text("Abc", "") == "Abc" and cased_text("Abc", "kapitälchen") == "Abc"
    assert cased_text("", "upper") == "" and cased_text("a\nb", "upper") == "A\nB"
    assert TEXT_CASES == ("upper",) and TEXT_CASE_LABELS[""] == "Originalschreibweise"
    assert TEXT_CASE_LABELS["upper"] == "Großbuchstaben"


def test_default_is_original_and_not_saved():
    s = Shape("text", Geometry(0, 0, 10, 5), "L1", text="Abc")
    assert s.text_case == "" and "case" not in s.to_dict()
    assert "case" not in text_layout(s) and display_text(s) == "Abc"
    assert Shape.from_dict(s.to_dict()).text_case == ""


def test_upper_round_trip_keeps_the_typed_text():
    s = Shape("text", Geometry(0, 0, 10, 5), "L1", text="Anna", text_case="upper")
    d = json.loads(json.dumps(s.to_dict()))
    assert d["case"] == "upper" and d["text"] == "Anna"
    back = Shape.from_dict(d)
    assert back.text_case == "upper" and back.text == "Anna" and back.to_dict() == d
    assert display_text(back) == "ANNA" and text_layout(back) == {"case": "upper"}
    assert s.copy(new_identity=True).text_case == "upper"


@pytest.mark.parametrize("raw", ["lower", "UPPER", 1, True, None, ["upper"], {"a": 1}])
def test_unknown_case_values_read_as_original(raw):
    assert read_text_case(raw) == ""
    d = Shape("text", Geometry(0, 0, 10, 5), "L1", text="A").to_dict()
    d["case"] = raw
    assert Shape.from_dict(d).text_case == ""


def test_case_only_on_text_objects():
    d = Shape("rect", Geometry(0, 0, 10, 5), "L1").to_dict()
    d["case"] = "upper"
    r = Shape.from_dict(d)
    assert r.text_case == "" and "case" not in r.to_dict()


def test_old_project_file_unchanged(qapp):
    s = _text("Hallo", FAMILY, text_align="center")
    doc = _doc_with(s)
    d = doc.to_dict()
    assert "case" not in json.dumps(d)
    assert Document.from_dict(json.loads(json.dumps(d))).to_dict() == d


# --- Umriss ----------------------------------------------------------------------------------

@pytest.mark.parametrize("family", [FAMILY, LINE_FONT_SANS])
def test_text_path_equals_the_upper_case_text(qapp, family):
    a = text_path("Grüße\nstraße", family, case="upper", letter_spacing=5.0, align="center")
    b = text_path("GRÜSSE\nSTRASSE", family, letter_spacing=5.0, align="center")
    assert _elements(a) == _elements(b)
    assert _elements(text_path("abc", family, case="")) == _elements(text_path("abc", family))
    assert text_aspect("abc", family, case="upper") == text_aspect("ABC", family)


@pytest.mark.parametrize("family", [FAMILY, LINE_FONT_SANS])
def test_shape_outline_is_upper_case_text_unchanged(qapp, family):
    s = _text("anna", family, text_case="upper")
    assert _elements(shape_text_path(s)) == _elements(text_path("ANNA", family))
    assert s.text == "anna"


def test_line_font_strokes_are_the_upper_case_strokes(qapp):
    s = _text("anna", LINE_FONT_SANS, text_case="upper")
    ref = _text("ANNA", LINE_FONT_SANS)
    ref.geom = s.geom.copy()
    pa = [[(round(x, 6), round(y, 6)) for x, y in p] for p in shape_polygons(s)]
    pb = [[(round(x, 6), round(y, 6)) for x, y in p] for p in shape_polygons(ref)]
    assert pa == pb and len(pa) > 4


# --- Box im Text-Satz ------------------------------------------------------------------------

@pytest.mark.parametrize("family", [FAMILY, LINE_FONT_SANS])
def test_with_layout_keeps_font_size_and_left_top(qapp, family):
    s = _text("anna", family)
    k0 = abs(s.geom.h) / text_bounds(shape_text_path(s)).height()      # mm je Aufbau-Einheit
    pt0 = text_ui.size_pt(s)
    u = text_ui.with_layout(s, case="upper")
    assert u.text_case == "upper" and u.text == "anna" and s.text_case == ""
    k1 = abs(u.geom.h) / text_bounds(shape_text_path(u)).height()
    assert k1 == pytest.approx(k0, rel=1e-9) and text_ui.size_pt(u) == pytest.approx(pt0, rel=1e-6)
    assert u.geom.w > s.geom.w and (u.geom.x, u.geom.y) == (s.geom.x, s.geom.y)
    back = text_ui.with_layout(u, case="")
    for a, b in ((back.geom.x, s.geom.x), (back.geom.y, s.geom.y),
                 (back.geom.w, s.geom.w), (back.geom.h, s.geom.h)):
        assert a == pytest.approx(b, abs=1e-9)


def test_with_layout_right_aligned_keeps_the_right_edge(qapp):
    s = _text("ab\nc", LINE_FONT_SANS, text_align="right")
    u = text_ui.with_layout(s, case="upper")
    assert u.geom.x + u.geom.w == pytest.approx(s.geom.x + s.geom.w, abs=1e-9)


def test_with_layout_rotated_keeps_the_anchor(qapp):
    from lumacut_canvas.model import rotate_point
    s = _text("anna", LINE_FONT_SANS)
    s.geom.rot = 30.0
    u = text_ui.with_layout(s, case="upper")

    def anchor(g):
        cx, cy = g.center()
        return rotate_point(g.x, g.y, cx, cy, g.rot)
    assert anchor(u.geom) == pytest.approx(anchor(s.geom), abs=1e-9) and u.geom.rot == 30.0


def test_mirrored_text_stays_mirrored(qapp):
    s = _text("anna", LINE_FONT_SANS)
    s.geom.w = -s.geom.w
    u = text_ui.with_layout(s, case="upper")
    assert u.geom.w < 0 and abs(u.geom.w) > abs(s.geom.w)


# --- Folgefunktionen -------------------------------------------------------------------------

def test_job_and_gcode_burn_capitals_pi_safe(qapp):
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.toolpath import parse_gcode
    from lumacut_job.planner import optimized_document_gcode
    s = _text("anna", LINE_FONT_SANS, text_case="upper")
    ref = _text("ANNA", LINE_FONT_SANS)
    ref.geom = s.geom.copy()
    pa = [p for jl in job_layers(_doc_with(s)) for p in jl.polylines]
    pb = [p for jl in job_layers(_doc_with(ref)) for p in jl.polylines]
    assert len(pa) == len(pb) and pa
    g = optimized_document_gcode(_doc_with(s), scan_offsets=None)
    pi_check(g)
    g_ref = optimized_document_gcode(_doc_with(ref), scan_offsets=None)
    assert parse_gcode(g).cut_length_mm == pytest.approx(parse_gcode(g_ref).cut_length_mm, abs=1e-6)


def test_document_gcode_unchanged_without_case(qapp):
    from lumacut_canvas.gcode import document_to_gcode
    doc = _doc_with(_text("anna", FAMILY))
    g0 = document_to_gcode(doc)
    doc2 = Document.from_dict(json.loads(json.dumps(doc.to_dict())))
    assert document_to_gcode(doc2) == g0
    doc2.shapes[0].text_case = "upper"
    assert document_to_gcode(doc2) != g0


def test_variable_text_values_are_burned_in_capitals(qapp, tmp_path):
    from lumacut_job import vartext as vt
    csv = tmp_path / "namen.csv"
    csv.write_text("Name\nanna müller\nJörg Groß\n", encoding="utf-8")
    s = _text("{Name}", LINE_FONT_SANS, text_case="upper")
    s.generator = vt.make_meta(vt.VarTextSpec(csv_path=str(csv)))
    doc = _doc_with(s)
    out, usage = vt.evaluate_document(doc, None, NOW)
    t = out.shapes[0]
    assert t.text == "anna müller" and t.text_case == "upper" and s.text == "{Name}"
    assert display_text(t) == "ANNA MÜLLER"
    assert _elements(shape_text_path(t)) == _elements(text_path("ANNA MÜLLER", LINE_FONT_SANS))
    # Breite nach der Laufweite der Versalien (Höhe bleibt)
    ratio = abs(s.geom.w) / (abs(s.geom.h) * text_aspect("{Name}", LINE_FONT_SANS, case="upper"))
    assert t.geom.h == s.geom.h
    assert t.geom.w == pytest.approx(
        t.geom.h * text_aspect("ANNA MÜLLER", LINE_FONT_SANS) * ratio, rel=1e-9)
    pi_check(__import__("lumacut_job.planner", fromlist=["x"]).optimized_document_gcode(
        out, scan_offsets=None))


def test_variable_text_canvas_label_shows_capitals(qapp, tmp_path):
    from lumacut_job import vartext as vt
    from lumacut_job.vartext_preview import VarTextValues
    ed = CanvasEditor()
    try:
        s = _text("Nr. {n:3} {input:Name=jörg}", LINE_FONT_SANS, text_case="upper")
        s.layer_id = ed.document.active_layer_id
        s.generator = vt.make_meta(vt.VarTextSpec(current=7))
        ed.document.add_shape(s)
        vt.clear_input_values()
        ov = VarTextValues(ed)
        assert ov.label_for(s.id).text == "→ NR. 007 JÖRG"
        assert ov.values[s.id].text == "Nr. 007 jörg"       # Auswertung selbst unverändert
        ed.document.shape(s.id).text_case = ""
        ov.rebuild()
        assert ov.label_for(s.id).text == "→ Nr. 007 jörg"
    finally:
        vt.clear_input_values()
        ed.undo_stack.setClean()
        ed.close()


def test_serial_numbers_keep_the_case_and_widths(qapp):
    from lumacut_job.serial import SerialSpec, serial_shapes
    src = _text("nr 1", LINE_FONT_SANS, text_case="upper")
    shapes = serial_shapes(src, SerialSpec("nr {n}", start=9, count=2, columns=2), text_aspect)
    assert [sh.text for sh in shapes] == ["nr 9", "nr 10"]
    assert all(sh.text_case == "upper" for sh in shapes)
    k = abs(src.geom.w) / (abs(src.geom.h) * text_aspect("NR 1", LINE_FONT_SANS))
    assert shapes[1].geom.w == pytest.approx(
        abs(src.geom.h) * text_aspect("NR 10", LINE_FONT_SANS) * k, rel=1e-9)


def test_text_to_path_converts_the_capitals(qapp):
    from lumacut_canvas.pathops import text_to_outline
    s = _text("anna", LINE_FONT_SANS, text_case="upper")
    ref = _text("ANNA", LINE_FONT_SANS)
    ref.geom = s.geom.copy()
    a, b = text_to_outline(s), text_to_outline(ref)
    assert a.points == b.points and a.rings == b.rings


def test_arc_text_from_an_upper_case_text(qapp):
    from lumacut_job.arctext_qt import spec_from_text
    s = _text("anna\nbert", LINE_FONT_SANS, text_case="upper")
    assert spec_from_text(s).text == "ANNA BERT"
    s.text_case = ""
    assert spec_from_text(s).text == "anna bert"


def test_svg_export_shows_capitals(qapp, tmp_path):
    from lumacut_canvas.export import export_svg
    a, b, c = tmp_path / "a.svg", tmp_path / "b.svg", tmp_path / "c.svg"
    s = _text("anna", LINE_FONT_SANS, text_case="upper")
    ref = _text("ANNA", LINE_FONT_SANS)
    ref.geom = s.geom.copy()
    export_svg(_doc_with(s), a)
    export_svg(_doc_with(ref), b)
    plain = _text("anna", LINE_FONT_SANS)
    plain.geom = s.geom.copy()
    export_svg(_doc_with(plain), c)
    assert a.read_text() == b.read_text() != c.read_text()


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


def _add(ed, text="anna", **kw):
    s = _text(text, kw.pop("family", LINE_FONT_SANS), **kw)
    s.layer_id = ed.document.active_layer_id
    ed.document.add_shape(s)
    ed.set_selection([s.id])
    return ed.document.shape(s.id)


def test_button_toggles_in_one_undo_step(ed):
    bar = ed.property_bar.text_style
    t = _add(ed)
    bar.refresh()
    assert bar.upper.isCheckable() and not bar.upper.isChecked() and bar.upper.isEnabled()
    assert bar.upper.text() == "AA" and bar.upper.objectName() == "TextUpperCase"
    n0 = ed.undo_stack.count()
    w0 = t.geom.w
    bar.upper.click()
    s = ed.document.shape(t.id)
    assert s.text_case == "upper" and s.text == "anna" and ed.undo_stack.count() == n0 + 1
    assert ed.undo_stack.undoText() == "Großbuchstaben" and s.geom.w > w0
    bar.refresh()
    assert bar.upper.isChecked()
    bar.upper.click()
    assert ed.document.shape(t.id).text_case == ""
    assert ed.undo_stack.undoText() == "Originalschreibweise"
    assert ed.document.shape(t.id).geom.w == pytest.approx(w0, abs=1e-9)
    ed.undo_stack.undo()
    assert ed.document.shape(t.id).text_case == "upper"
    ed.undo_stack.undo()
    assert ed.document.shape(t.id).text_case == "" and ed.document.shape(t.id).geom.w == w0


def test_button_applies_to_the_whole_selection(ed):
    bar = ed.property_bar.text_style
    a = _add(ed, "ab")
    b = _add(ed, "cd", text_case="upper")
    ed.set_selection([a.id, b.id])
    bar.refresh()
    assert not bar.upper.isChecked()                # gemischt
    n0 = ed.undo_stack.count()
    bar.upper.click()
    assert all(ed.document.shape(i).text_case == "upper" for i in (a.id, b.id))
    assert ed.undo_stack.count() == n0 + 1          # nur „a“ geändert, ein Schritt
    c = _add(ed, "ef")
    ed.set_selection([a.id, b.id, c.id])
    bar.refresh()
    bar.upper.click()
    assert all(ed.document.shape(i).text_case == "upper" for i in (a.id, b.id, c.id))
    assert ed.undo_stack.count() == n0 + 2
    ed.undo_stack.undo()
    assert ed.document.shape(c.id).text_case == ""


def test_refresh_does_not_push(ed):
    bar = ed.property_bar.text_style
    _add(ed, text_case="upper")
    n0 = ed.undo_stack.count()
    bar.refresh()
    assert bar.upper.isChecked() and ed.undo_stack.count() == n0


def test_locked_layer_text_is_not_changed(ed):
    t = _add(ed)
    ed.document.layer(t.layer_id).locked = True
    bar = ed.property_bar.text_style
    n0 = ed.undo_stack.count()
    bar._case_toggled(True)
    assert ed.undo_stack.count() == n0 and ed.document.shape(t.id).text_case == ""


def test_editing_the_text_keeps_capitals(ed):
    t = _add(ed, text_case="upper")
    ok = text_ui.with_layout(t, text="bert")
    assert ok.text == "bert" and ok.text_case == "upper"
    assert _elements(shape_text_path(ok)) == _elements(text_path("BERT", LINE_FONT_SANS))


def test_line_font_missing_note_uses_capitals(ed):
    t = _add(ed, "straße", family=FAMILY, text_case="upper")
    bar = ed.property_bar.text_style
    bar.refresh()
    notes = []
    ed.notify = notes.append
    bar._stroke_chosen(bar.stroke.findData(LINE_FONT_SANS))
    s = ed.document.shape(t.id)
    assert s.font_family == LINE_FONT_SANS and s.text_case == "upper"
    assert not notes                     # „SS“ statt „ß“ – kein „?“-Hinweis nötig


def test_canvas_item_shows_capitals(ed, qapp):
    t = _add(ed)
    ed.property_bar.text_style.refresh()
    ed.property_bar.text_style.upper.click()
    qapp.processEvents()
    item = next(i for i in ed.scene.items() if getattr(i, "shape_id", None) == t.id)
    s = ed.document.shape(t.id)
    ref = _text("ANNA", LINE_FONT_SANS)
    ref.geom = s.geom.copy()
    ref.layer_id = s.layer_id
    from lumacut_canvas.shape_paths import local_path
    assert _elements(item._path) == _elements(local_path(ref))


def test_touch_mode_size(ed, qapp):
    bar = ed.property_bar.text_style
    _add(ed)
    bar.refresh()
    ed.set_touch_mode(True, persist=False)
    qapp.processEvents()
    try:
        assert bar.upper.sizeHint().height() >= 40 and bar.upper.sizeHint().width() >= 40
    finally:
        ed.set_touch_mode(False, persist=False)


def test_tooltip_names_xtool_and_keeps_the_typed_text():
    tip = text_ui.TIP_CASE
    assert "xTool" in tip and "Großbuchstaben" in tip and "ß → SS" in tip
    assert "getippt" in tip and "variabler Texte" in tip


def test_save_load_keeps_case(ed, tmp_path):
    from lumacut_canvas.document_io import load_into, save_document
    t = _add(ed, text_case="upper")
    p = save_document(ed.document, tmp_path / "t.lcut")
    doc = Document()
    load_into(doc, p)
    assert doc.shape(t.id).text_case == "upper" and doc.shape(t.id).text == "anna"


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
    bar.upper.click()
    assert ed.document.shape(t.id).text_case == "upper"
    ed.undo_stack.setClean()
    win.close()
