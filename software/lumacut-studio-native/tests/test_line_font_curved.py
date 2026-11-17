"""Einlinien-Schrift für „Bogentext…“ und „Text auf Pfad…“: offene Striche je Buchstabe
auf dem Kreis / Pfad (LightBurns *Text on Path* mit Single-Line-Font, xTool Einlinien-Text
auf Kreis) – Glyphen, Objekte, Auftrag, G-Code, Dialoge, Fenster, Bearbeiten, Datei."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas import linefont  # noqa: E402
from lumacut_canvas.alongpath import PathCurve, normalize_closed  # noqa: E402
from lumacut_canvas.linefont import LINE_FONT_SANS, LINE_FONT_SCRIPT, LINE_FONTS  # noqa: E402
from lumacut_canvas.model import Document, Geometry, Shape, is_closed_shape  # noqa: E402
from lumacut_canvas.toolpath import parse_gcode  # noqa: E402
from lumacut_job import arctext, generated, pathtext  # noqa: E402
from lumacut_job.arctext import ArcSpec  # noqa: E402
from lumacut_job.pathtext import PathTextSpec  # noqa: E402

FONTS = list(LINE_FONTS)


def _strokes(text, family=LINE_FONT_SANS):
    return sum(len(linefont.glyph(family, ch).strokes) for ch in text if not ch.isspace())


def _doc(shapes, **layer):
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


def _circle(cx, cy, r, n=360):
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n))
            for k in range(n)]


# --- Glyphen ---------------------------------------------------------------------------------

@pytest.mark.parametrize("family", FONTS)
def test_line_glyphs_are_open_strokes_with_cap_height(qapp, family):
    from lumacut_job.arctext_qt import glyphs_for
    g = glyphs_for("HI H", family, 10.0)
    assert [x.char for x in g] == list("HI H") and all(x.open for x in g)
    assert g[2].rings == () and g[2].advance > 0
    assert len(g[0].rings) == len(linefont.glyph(family, "H").strokes)
    assert all(len(r) >= 2 for x in g for r in x.rings)
    if family == LINE_FONT_SANS:          # Versalhöhe = Schrifthöhe, Grundlinie bei 0
        ys = [p[1] for r in g[0].rings for p in r]
        assert min(ys) == pytest.approx(-10.0) and max(ys) == pytest.approx(0.0)
    big = glyphs_for("HI H", family, 20.0)
    assert arctext.text_span(big, 0) == pytest.approx(2 * arctext.text_span(g, 0))


def test_line_glyph_advances_match_the_text_object(qapp):
    from lumacut_job.arctext_qt import LINE_CAP_UNITS, glyphs_for
    text = "Grüße 20 €"
    g = glyphs_for(text, LINE_FONT_SANS, 7.0)
    span = arctext.text_span(g, 0.0)
    assert span == pytest.approx(linefont.line_advance(text, LINE_FONT_SANS) * 7.0 / LINE_CAP_UNITS)
    # Umlaut-Punkte über dem Buchstaben, ß / € eigene Striche
    u = g[2]
    assert len(u.rings) == len(linefont.glyph(LINE_FONT_SANS, "ü").strokes) > len(
        linefont.glyph(LINE_FONT_SANS, "u").strokes)
    assert min(p[1] for r in u.rings for p in r) < -7.0 * 14 / 21 + 0.01


def test_italic_slants_bold_ignored_and_missing_chars(qapp):
    from lumacut_job.arctext_qt import glyphs_for, missing_note
    up = glyphs_for("I", LINE_FONT_SANS, 10.0)[0]
    it = glyphs_for("I", LINE_FONT_SANS, 10.0, italic=True)[0]
    top_up = min(up.rings[0], key=lambda p: p[1])
    top_it = min(it.rings[0], key=lambda p: p[1])
    assert top_it[0] - top_up[0] == pytest.approx(linefont.ITALIC_SLANT * 10.0)
    assert glyphs_for("AB", LINE_FONT_SANS, 5.0, bold=True) == glyphs_for("AB", LINE_FONT_SANS, 5.0)
    q = glyphs_for("Ω", LINE_FONT_SANS, 5.0)[0]
    assert q.rings == glyphs_for("?", LINE_FONT_SANS, 5.0)[0].rings
    assert "„Ω“" in missing_note("aΩ", LINE_FONT_SANS) and missing_note("aΩ", "DejaVu Sans") == ""
    assert missing_note("Grüße", LINE_FONT_SANS) == ""


def test_outline_glyphs_stay_closed(qapp):
    from lumacut_job.arctext_qt import glyphs_for
    g = glyphs_for("HO", "DejaVu Sans", 10.0)
    assert not any(x.open for x in g) and all(len(r) >= 3 for x in g for r in x.rings)


# --- Objekte ---------------------------------------------------------------------------------

@pytest.mark.parametrize("family", FONTS)
def test_arc_shapes_are_open_paths_one_per_letter(qapp, family):
    from lumacut_job.arctext_qt import glyphs_for
    text = "Hallo Welt"
    s = ArcSpec(text=text, radius_mm=40.0, height_mm=8.0, font_family=family)
    shapes = arctext.arc_shapes(glyphs_for(text, family, 8.0), s, "L", (150.0, 100.0), cap_height_mm=8.0)
    assert len(shapes) == 9 and all(sh.kind == "path" for sh in shapes)
    assert len({sh.groups for sh in shapes}) == 1
    assert all(not is_closed_shape(sh) for sh in shapes)
    assert sum(len(sh.ring_ranges()) for sh in shapes) == _strokes(text, family)


def test_arc_baseline_of_line_text_lies_on_the_circle(qapp):
    from lumacut_canvas.shape_paths import shape_polygons
    from lumacut_job.arctext_qt import glyphs_for
    r = 30.0
    g = glyphs_for("HH", LINE_FONT_SANS, 6.0)
    pl = arctext.place_glyphs(g, r, 0.0, cap_height_mm=6.0)
    assert all(p.open for p in pl)
    for p in pl:      # „H“: Fußpunkte der Senkrechten auf dem Kreis, Oberkante 6 mm außen
        ds = [math.hypot(*pt) for ring in p.rings for pt in ring]
        assert r - 1e-9 <= min(ds) < r + 0.1 and max(ds) == pytest.approx(r + 6.0, abs=0.3)
    shapes = arctext.arc_shapes(g, ArcSpec(text="HH", radius_mm=r, height_mm=6.0,
                                           font_family=LINE_FONT_SANS), "L", (100.0, 100.0))
    polys = [q for sh in shapes for q in shape_polygons(sh)]
    assert len(polys) == 6 and all(q[0] != q[-1] for q in polys)


def test_bottom_line_text_reads_left_to_right(qapp):
    from lumacut_job.arctext_qt import glyphs_for
    g = glyphs_for("AB", LINE_FONT_SANS, 5.0)
    pl = arctext.place_glyphs(g, 30.0, 180.0, bottom=True, cap_height_mm=5.0)
    assert pl[0].anchor[0] < pl[1].anchor[0] and all(p.anchor[1] > 0 for p in pl)
    with pytest.raises(ValueError, match="höher als der Radius"):
        arctext.place_glyphs(g, 4.0, 180.0, bottom=True, cap_height_mm=5.0)


@pytest.mark.parametrize("closed", [False, True])
def test_path_text_shapes_are_open_paths(qapp, closed):
    from lumacut_job.arctext_qt import glyphs_for
    curve = (PathCurve(normalize_closed(_circle(150, 100, 40)), True) if closed
             else PathCurve([(30.0, 100.0), (130.0, 80.0), (230.0, 100.0)]))
    text = "a-b 17"
    shapes, res = pathtext.pathtext_shapes(glyphs_for(text, LINE_FONT_SANS, 6.0), curve,
                                           PathTextSpec(text=text, height_mm=6.0), "L")
    assert len(shapes) == 5 and all(sh.kind == "path" for sh in shapes)
    assert sum(len(sh.ring_ranges()) for sh in shapes) == _strokes(text)
    assert res.closed == closed and res.span_mm > 0


def test_flat_dash_on_a_straight_line_is_a_valid_path(qapp):
    from lumacut_canvas.shape_paths import shape_polygons
    from lumacut_job.arctext_qt import glyphs_for
    shapes, _res = pathtext.pathtext_shapes(glyphs_for("-", LINE_FONT_SANS, 6.0),
                                            PathCurve([(20, 50), (120, 50)]),
                                            PathTextSpec(text="-", height_mm=6.0), "L")
    (sh,) = shapes
    assert sh.kind == "path" and sh.geom.h == pytest.approx(0.0, abs=1e-9) and sh.geom.w > 0
    (poly,) = shape_polygons(sh)
    assert len(poly) == 2 and all(44.0 < p[1] < 50.0 for p in poly)     # über der Grundlinie


def test_outline_arc_and_path_text_unchanged(qapp):
    from lumacut_job.arctext_qt import glyphs_for
    g = glyphs_for("Ob", "DejaVu Sans", 8.0)
    a = arctext.arc_shapes(g, ArcSpec(text="Ob", font_family="DejaVu Sans"), "L")
    b, _ = pathtext.pathtext_shapes(g, PathCurve([(20, 50), (120, 50)]), PathTextSpec(text="Ob"), "L")
    assert all(sh.kind == "polygon" for sh in a + b) and a[0].rings and b[0].rings


# --- Auftrag / G-Code ------------------------------------------------------------------------

@pytest.mark.parametrize("fill", [False, True])
def test_job_lasers_every_stroke_once_never_filled(qapp, fill):
    from lumacut_canvas.export import job_layers, layer_fill_blocks
    from lumacut_job.arctext_qt import glyphs_for
    text = "Grüße 20 €"
    shapes = arctext.arc_shapes(glyphs_for(text, LINE_FONT_SANS, 6.0),
                                ArcSpec(text=text, radius_mm=35.0, height_mm=6.0, font_family=LINE_FONT_SANS),
                                "L", (150.0, 100.0))
    doc = _doc(shapes, **({"fill_mode": "hatch", "line_interval_mm": 0.2} if fill else {}))
    if fill:
        assert layer_fill_blocks(doc, doc.layers[0]) == []
    (jl,) = job_layers(doc)
    assert not jl.fills and len(jl.polylines) == _strokes(text)


@pytest.mark.parametrize("family", FONTS)
def test_gcode_pi_safe_and_much_shorter_than_outline_arc_text(qapp, family):
    from lumacut_canvas.shape_paths import shape_polygons
    from lumacut_job.arctext_qt import glyphs_for
    from lumacut_job.planner import optimized_document_gcode
    text = "LumaCut 2026"
    spec = ArcSpec(text=text, radius_mm=40.0, height_mm=8.0, font_family=family)
    line = arctext.arc_shapes(glyphs_for(text, family, 8.0), spec, "L", (150.0, 100.0))
    g = optimized_document_gcode(_doc(line, fill_mode="hatch", line_interval_mm=0.1), scan_offsets=None)
    pi_check(g)
    tp = parse_gcode(g)
    total = _length([q for sh in line for q in shape_polygons(sh)])
    assert tp.cut_length_mm == pytest.approx(total, abs=0.1)
    outline = arctext.arc_shapes(glyphs_for(text, "DejaVu Sans", 8.0),
                                 ArcSpec(text=text, radius_mm=40.0, height_mm=8.0, font_family="DejaVu Sans"),
                                 "L", (150.0, 100.0))
    g2 = optimized_document_gcode(_doc(outline, fill_mode="hatch", line_interval_mm=0.1), scan_offsets=None)
    assert parse_gcode(g2).cut_length_mm > 3 * tp.cut_length_mm


# --- Dialoge ---------------------------------------------------------------------------------

def test_arc_dialog_font_kind(qapp):
    from lumacut_job.arctext_qt import OUTLINE_LABEL, ArcTextDialog
    dlg = ArcTextDialog(spec=ArcSpec(text="LumaCut", font_family="DejaVu Sans", bold=True))
    assert [dlg.kind.itemText(i) for i in range(dlg.kind.count())] == [
        OUTLINE_LABEL, "Einlinie (Sans)", "Einlinie (Schreibschrift)"]
    assert "Einlinie" in dlg.kind.toolTip() and dlg.kind.currentIndex() == 0
    assert dlg.font_box.isEnabled() and dlg.spec().bold
    dlg.kind.setCurrentIndex(dlg.kind.findData(LINE_FONT_SCRIPT))
    s = dlg.spec()
    assert s.font_family == LINE_FONT_SCRIPT and not s.bold
    assert not dlg.font_box.isEnabled() and not dlg.bold.isEnabled() and dlg.italic.isEnabled()
    assert dlg.ok_button.isEnabled() and "Bogen" in dlg.info.text()
    dlg.text.setText("Grüße Ω")
    assert "„Ω“" in dlg.info.text() and dlg.ok_button.isEnabled()
    dlg.kind.setCurrentIndex(0)
    assert dlg.spec().font_family == dlg.font_box.currentFont().family() and dlg.spec().bold
    assert "Ω" not in dlg.info.text()
    dlg.deleteLater()


def test_arc_dialog_opens_with_a_line_font(qapp):
    from lumacut_job.arctext_qt import ArcTextDialog
    dlg = ArcTextDialog(spec=ArcSpec(text="Nr 17", font_family=LINE_FONT_SANS, italic=True))
    assert dlg.kind.currentData() == LINE_FONT_SANS and not dlg.font_box.isEnabled()
    s = dlg.spec()
    assert (s.font_family, s.italic, s.bold) == (LINE_FONT_SANS, True, False)
    dlg.deleteLater()


def test_path_dialog_font_kind(qapp):
    from lumacut_job.pathtext_qt import PathTextDialog
    curve = PathCurve(normalize_closed(_circle(100, 100, 40)), True)
    dlg = PathTextDialog(curve, spec=PathTextSpec(text="Hallo", font_family=LINE_FONT_SANS))
    assert dlg.kind.currentData() == LINE_FONT_SANS and not dlg.font_box.isEnabled()
    assert dlg.spec().font_family == LINE_FONT_SANS and "geschlossen" in dlg.info.text()
    dlg.text.setText("Ωmega")
    assert "„Ω“" in dlg.info.text()
    dlg.kind.setCurrentIndex(0)
    assert not linefont.is_line_font(dlg.spec().font_family) and dlg.font_box.isEnabled()
    dlg.deleteLater()


def test_spec_from_a_line_text_keeps_font_and_cap_height(qapp):
    from lumacut_canvas.shape_paths import text_aspect
    from lumacut_job.arctext_qt import spec_from_text
    from lumacut_job.pathtext_qt import spec_from_text_shape
    t = Shape("text", Geometry(20, 30, 10 * text_aspect("Hallo", LINE_FONT_SANS), 10.0), "L",
              text="Hallo", font_family=LINE_FONT_SANS, font_italic=True)
    a = spec_from_text(t)
    assert (a.text, a.font_family, a.italic) == ("Hallo", LINE_FONT_SANS, True)
    assert a.height_mm == pytest.approx(10.0, abs=0.1)        # „H“ / „l“ = ganze Texthöhe
    p = spec_from_text_shape(t)
    assert p.font_family == LINE_FONT_SANS and p.height_mm == a.height_mm
    low = Shape("text", Geometry(20, 30, 10 * text_aspect("ao", LINE_FONT_SANS), 10.0), "L",
                text="ao", font_family=LINE_FONT_SANS)
    assert spec_from_text(low).height_mm == pytest.approx(10.0 * 21 / 14, abs=0.1)


# --- Fenster ---------------------------------------------------------------------------------

@pytest.fixture
def win(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    msgs = []
    monkeypatch.setattr(w.job_tools, "_msg", lambda text, ms=8000: msgs.append(text))
    w.msgs = msgs
    yield w
    w.canvas.undo_stack.setClean()
    w.close()
    w.deleteLater()
    qapp.processEvents()


def _add(ed, *shapes):
    from lumacut_canvas.commands import AddShapesCommand
    for s in shapes:
        s.layer_id = ed.document.active_layer_id
    ed.undo_stack.push(AddShapesCommand(ed.document, list(shapes)))
    return shapes


def test_window_arc_text_with_line_font_one_undo_step(win):
    from lumacut_job.planner import optimized_document_gcode
    ed, doc = win.canvas, win.canvas.document
    depth = ed.undo_stack.index()
    ids = win.job_tools.arc_text(ArcSpec(text="Grüße 20 €", radius_mm=40.0, height_mm=6.0,
                                         font_family=LINE_FONT_SANS))
    assert len(ids) == 8 and ed.undo_stack.index() == depth + 1
    parts = [doc.shape(i) for i in ids]
    assert all(p.kind == "path" for p in parts) and len({p.groups for p in parts}) == 1
    assert parts[0].generator["spec"]["font_family"] == LINE_FONT_SANS
    g = optimized_document_gcode(doc)
    pi_check(g)
    assert parse_gcode(g).cut_length_mm > 0
    ed.undo_stack.undo()
    assert not any(doc.has_shape(i) for i in ids)


def test_window_replace_line_text_by_arc_text(win):
    from lumacut_canvas.shape_paths import text_aspect
    from lumacut_job.arctext_qt import spec_from_text
    ed, doc = win.canvas, win.canvas.document
    t, = _add(ed, Shape("text", Geometry(60, 50, 8 * text_aspect("Hallo", LINE_FONT_SCRIPT), 8.0), "?",
                        text="Hallo", font_family=LINE_FONT_SCRIPT))
    ed.set_selection([t.id])
    ids = win.job_tools.arc_text(spec_from_text(t), replace=True)
    assert len(ids) == 5 and not doc.has_shape(t.id)
    assert all(doc.shape(i).kind == "path" for i in ids)
    assert "Text ersetzt" in win.msgs[-1]


def test_window_path_text_with_line_text_on_a_circle(win):
    from lumacut_canvas.shape_paths import text_aspect
    from lumacut_job.pathtext_qt import spec_from_text_shape
    ed, doc = win.canvas, win.canvas.document
    circle, t = _add(ed, Shape("ellipse", Geometry(110, 80, 100, 100), "?"),
                     Shape("text", Geometry(60, 20, 8 * text_aspect("Nr 17", LINE_FONT_SANS), 8.0), "?",
                           text="Nr 17", font_family=LINE_FONT_SANS))
    ed.set_selection([circle.id, t.id])
    depth = ed.undo_stack.index()
    ids = win.job_tools.path_text(spec_from_text_shape(t), replace=True)
    assert len(ids) == 4 and ed.undo_stack.index() == depth + 1
    assert all(doc.shape(i).kind == "path" for i in ids) and not doc.has_shape(t.id)
    assert doc.has_shape(circle.id)


def test_new_dialogs_default_to_the_remembered_line_font(win, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from lumacut_job import arctext_qt, pathtext_qt
    ed = win.canvas
    seen = []

    def fake(self):
        seen.append(self.spec().font_family)
        return QDialog.Rejected
    monkeypatch.setattr(arctext_qt.ArcTextDialog, "exec", fake)
    monkeypatch.setattr(pathtext_qt.PathTextDialog, "exec", fake)
    ed.set_selection([])
    ed.text_font_family = "DejaVu Sans"
    assert win.job_tools.arc_text() == []
    ed.text_font_family = LINE_FONT_SCRIPT
    assert win.job_tools.arc_text() == []
    line, = _add(ed, Shape.from_points("path", [(30, 100), (230, 100)], "?"))
    ed.set_selection([line.id])
    assert win.job_tools.path_text() == []
    assert not linefont.is_line_font(seen[0]) and seen[1:] == [LINE_FONT_SCRIPT, LINE_FONT_SCRIPT]


def test_edit_generated_line_arc_text_keeps_the_font(win):
    from lumacut_job.generated_qt import edit_dialog, replace_unit, unit_spec
    ed, doc = win.canvas, win.canvas.document
    ids = win.job_tools.arc_text(ArcSpec(text="ABC", radius_mm=30.0, height_mm=6.0,
                                         font_family=LINE_FONT_SANS))
    unit = generated.find_unit(doc, ids[0])
    assert unit is not None and unit.kind == "arctext" and sorted(unit.ids) == sorted(ids)
    spec = unit_spec(unit)
    assert spec.font_family == LINE_FONT_SANS
    dlg = edit_dialog(unit, spec, doc.layer(unit.layer_id))
    assert dlg.kind.currentData() == LINE_FONT_SANS and dlg.windowTitle() == "Bogentext bearbeiten"
    dlg.text.setText("ABCD")
    new = replace_unit(ed, unit, dlg.spec())
    dlg.deleteLater()
    assert len(new) == 4 and all(doc.shape(i).kind == "path" for i in new)
    assert all(doc.shape(i).groups[-1] == unit.group for i in new)
    ed.undo_stack.undo()
    assert sorted(i for i in ids if doc.has_shape(i)) == sorted(ids)


def test_save_load_keeps_open_letters(win, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    from lumacut_canvas.shape_paths import shape_polygons
    doc = win.canvas.document
    ids = win.job_tools.arc_text(ArcSpec(text="Ob", radius_mm=30.0, height_mm=8.0,
                                         font_family=LINE_FONT_SANS))
    f = tmp_path / "a.lcs"
    save_document(doc, f)
    back = load_document(f)
    for i in ids:
        a, b = doc.shape(i), back.shape(i)
        assert b.kind == "path" and b.rings == a.rings and b.generator == a.generator
        pa, pb = shape_polygons(a), shape_polygons(b)
        assert [[pytest.approx(p) for p in q] for q in pa] == [list(q) for q in pb]
