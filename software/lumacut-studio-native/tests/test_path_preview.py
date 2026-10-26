"""Pfadvorschau: G-Code-Rücklesen, gleicher Generator wie der Sendepfad, Overlay/Leiste."""

from __future__ import annotations

import pytest

from lumacut_canvas.toolpath import CUT, RAPID, parse_gcode

G = """G21
G90
M5 I
M3 I
; LAYER Schnitt
G0 X1 Y1
G1 X11 Y1 F600 S800
G1 X11 Y11 F600 S800
G91
G0 Z-1 F600
G90
G0 X20 Y20
G1 X30 Y20 S800
G1 X40 Y20 S0
; IMAGE abc123 RASTER
G1 X41 Y20 S500
M5 I
M400
"""


def test_parse_classifies_moves_runs_and_sources():
    tp = parse_gcode(G)
    kinds = [m.kind for m in tp.moves]
    assert kinds == [CUT, CUT, RAPID, CUT, RAPID, CUT]
    assert tp.runs == [(0, 2), (3, 4), (5, 6)]
    assert tp.cut_length_mm == pytest.approx(31.0)
    assert tp.rapid_length_mm == pytest.approx(((9 ** 2 + 9 ** 2) ** 0.5) + 10)
    assert tp.moves[0].source == ("layer", "Schnitt")
    assert tp.moves[-1].source == ("image", "abc123")
    assert tp.moves[0].power == 800 and tp.moves[2].power == 0
    assert tp.lengths_until(2) == (pytest.approx(20.0), 0.0)
    assert tp.runs_until(4) == 2


def test_relative_moves_and_laser_off():
    tp = parse_gcode("G90\nG0 X0 Y0\nM3 I\nG91\nG1 X5 S100 F100\nG1 Y5\nM5 I\nG1 X5\n")
    assert [(m.kind, m.x1, m.y1) for m in tp.moves] == [(CUT, 5, 0), (CUT, 5, 5), (RAPID, 10, 5)]


def test_empty_gcode():
    tp = parse_gcode("")
    assert tp.moves == [] and tp.runs == [] and tp.cut_length_mm == 0


def _doc(**layer):
    from lumacut_canvas.model import Document, Geometry, Shape
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, **layer)
    doc.add_shape(Shape("rect", Geometry(20, 20, 30, 20), lid))
    doc.add_shape(Shape("ellipse", Geometry(80, 30, 20, 20), lid))
    return doc


def test_lengths_match_estimator_and_planner_output():
    from lumacut_job.estimate import estimate_gcode
    from lumacut_job.planner import optimized_document_gcode
    gcode = optimized_document_gcode(_doc())
    tp = parse_gcode(gcode)
    est = estimate_gcode(gcode)
    assert tp.cut_length_mm == pytest.approx(est.cut_length_mm, rel=1e-6)
    assert tp.rapid_length_mm == pytest.approx(est.travel_length_mm, rel=1e-6)
    assert len(tp.runs) == 2


def test_hatch_fill_is_part_of_the_preview():
    from lumacut_job.planner import optimized_document_gcode
    plain = parse_gcode(optimized_document_gcode(_doc()))
    filled = parse_gcode(optimized_document_gcode(_doc(fill_mode="hatch", line_interval_mm=1.0)))
    assert filled.cut_length_mm > plain.cut_length_mm + 500     # 30×20 mm Fläche / 1 mm
    assert len(filled.runs) > len(plain.runs)


def _editor(doc, gen=None):
    from lumacut_canvas.editor import CanvasEditor
    ed = CanvasEditor(doc)
    if gen is not None:
        ed.path_preview.set_generator(gen)
    return ed


def test_off_by_default_and_lazy(qapp):
    calls = []
    doc = _doc()
    from lumacut_job.planner import optimized_document_gcode

    def gen(d):
        calls.append(1)
        return optimized_document_gcode(d)

    ed = _editor(doc, gen)
    pv = ed.path_preview
    assert not pv.visible and not ed.actions_by_name["path_preview"].isChecked()
    assert ed.actions_by_name["path_preview"] in ed.action_bar.actions()
    doc.update_layer(doc.active_layer_id, power=500)
    assert calls == [] and not pv.pending()       # aus = rechnet nicht
    ed.actions_by_name["path_preview"].trigger()
    assert pv.visible and calls == [1]
    assert ed.view.foreground("path_preview") is pv
    assert not ed.path_preview_scroll.isHidden()
    ed.set_path_preview(False)
    assert ed.view.foreground("path_preview") is None and ed.path_preview_scroll.isHidden()


def test_same_gcode_as_send_path_and_no_side_effects(qapp):
    from lumacut_job.planner import optimized_document_gcode
    doc = _doc(fill_mode="cross", line_interval_mm=2.0)
    before_doc = doc.to_dict()
    before = optimized_document_gcode(doc)
    ed = _editor(doc)
    ed.set_path_preview(True)
    pv = ed.path_preview
    assert pv.gcode == before                      # derselbe Generator wie _send_canvas_job
    ed.grab()                                      # Zeichnen ohne Fehler
    assert optimized_document_gcode(doc) == before and doc.to_dict() == before_doc
    assert ed.undo_stack.count() == 0


def test_debounced_rebuild_and_work_coordinates(qapp):
    doc = _doc()
    ed = _editor(doc)
    pv = ed.path_preview
    ed.set_path_preview(True)
    xs = [m.x1 for m in pv.toolpath.moves if m.kind == CUT]
    assert min(xs) == pytest.approx(20, abs=0.5) and max(xs) == pytest.approx(100, abs=0.5)
    old = pv.toolpath.cut_length_mm
    shape = doc.shapes[0]
    from lumacut_canvas.model import Geometry
    doc.set_geometry(shape.id, Geometry(20, 20, 60, 20))
    assert pv.pending() and pv.toolpath.cut_length_mm == old
    pv.rebuild()                                   # sonst nach DEBOUNCE_MS
    assert pv.toolpath.cut_length_mm == pytest.approx(old + 60, abs=0.5)


def test_readout_filter_and_scrub(qapp):
    doc = _doc()
    ed = _editor(doc)
    pv, bar = ed.path_preview, ed.path_preview_bar
    ed.set_path_preview(True)
    text = bar.readout.text()
    assert "Schneiden" in text and "Leerfahrt" in text and "ca." in text and "2 Läufe" in text
    assert bar.filter.count() == 2                 # Alle + eine Ebene
    total = len(pv.toolpath.moves)
    assert bar.slider.maximum() == total and bar.slider.value() == total
    bar.slider.setValue(1)
    assert pv.shown_count() == 1 and len(pv.visible_moves()) == 1
    assert "bis Schritt 1" in bar.readout.text()
    ed.grab()
    bar.slider.setValue(total)
    assert pv.limit is None
    bar.filter.setCurrentIndex(1)
    assert pv.source_filter.startswith("layer:") and pv.visible_moves()
    pv.set_filter("layer:gibtsnicht")
    assert pv.visible_moves() == [] and pv.visible_runs() == []


def test_empty_document_shows_message(qapp):
    from lumacut_canvas.model import Document
    ed = _editor(Document())
    ed.set_path_preview(True)
    assert ed.path_preview.toolpath.moves == []
    assert ed.path_preview_bar.readout.text()      # Hinweis statt Absturz
    ed.grab()


def test_layer_colour_mapping(qapp):
    from PySide6.QtGui import QColor
    doc = _doc()
    doc.update_layer(doc.active_layer_id, color="#ff0000")
    ed = _editor(doc)
    ed.set_path_preview(True)
    src = ed.path_preview.toolpath.moves[0].source
    assert ed.path_preview.color(src) == QColor("#ff0000")


def test_icon_exists(qapp):
    from lumacut_canvas import icons
    assert "path" in icons.available() and not icons.icon("path").isNull()
