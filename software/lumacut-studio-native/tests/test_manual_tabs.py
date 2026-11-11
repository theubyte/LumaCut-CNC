"""Manuelle Haltestege (LightBurn *Tab tool*): Stege je Objekt auf dem Umriss setzen,
entfernen, verschieben – Modell, Übertragen bei Pfad-Operationen, Planer / G-Code,
Werkzeug „Stege“ im Canvas, Menü, Hauptfenster."""

from __future__ import annotations

import json
import math
import re

import pytest
from _pi_guard import pi_check
from PySide6.QtCore import QPointF, Qt

from lumacut_canvas import nodes, pathops, pathsimplify, pathsplit, tabs
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.export import job_layers
from lumacut_canvas.model import Document, Geometry, Layer, Shape, tabs_from_world
from lumacut_canvas.shape_paths import shape_polygons
from lumacut_canvas.toolpath import parse_gcode
from lumacut_canvas.tools import TOOL_SHORTCUTS, Tool
from lumacut_canvas.workarea import to_machine
from lumacut_job.cutpath import (KIND_TAB, KIND_TAB_OFF, KIND_TAB_PULSE, CutOptions,
                                 apply_cut_options, assign_tab_points, manual_tab_intervals,
                                 tab_intervals)
from lumacut_job.planner import PlanReport, optimize_layers, optimized_document_gcode


def square(x, y, s):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]


def burned(g: str) -> float:
    return parse_gcode(g).cut_length_mm


def on_outline(shape, pts, tol=1e-6):
    rings = tabs.closed_rings(shape)
    return all(tabs.nearest_on_rings(rings, p)[0] <= tol for p in pts)


def gaps(g: str) -> int:
    """Lücken mit Laser aus innerhalb einer Kontur = G0 nach dem ersten Schnitt."""
    lines = [ln for ln in g.splitlines() if ln.startswith(("G0 X", "G1 X"))]
    first = next(i for i, ln in enumerate(lines) if ln.startswith("G1"))
    return sum(1 for ln in lines[first:] if ln.startswith("G0"))


@pytest.fixture
def doc(qapp):
    return Document()


@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def rect(lid, x=50.0, y=50.0, w=40.0, h=20.0, rot=0.0):
    return Shape("rect", Geometry(x, y, w, h, rot), lid)


# --- Modell -------------------------------------------------------------------------

def test_tab_points_follow_move_scale_rotate(doc):
    s = rect(doc.active_layer_id)
    s = tabs.with_tab_points(s, [(70.0, 50.0), (90.0, 60.0)])
    assert s.tabs == ((0.5, 0.0), (1.0, 0.5))
    assert s.tab_points() == [(70.0, 50.0), (90.0, 60.0)]
    s.geom = s.geom.translated(10, 5)
    assert s.tab_points() == [(80.0, 55.0), (100.0, 65.0)]
    s.geom = s.geom.mapped(s.geom.bounds(), type(s.geom.bounds())(60, 55, 80, 40))
    assert s.tab_points() == [(100.0, 55.0), (140.0, 75.0)]
    assert on_outline(s, s.tab_points())
    s.geom = s.geom.rotated(30, *s.geom.center())
    assert on_outline(s, s.tab_points(), 1e-6)
    back = tabs_from_world(s.geom, s.tab_points())
    assert all(math.isclose(a, b, abs_tol=1e-9) for t, u in zip(back, s.tabs) for a, b in zip(t, u))


def test_tabs_saved_in_project_and_old_files_unchanged(doc):
    s = rect(doc.active_layer_id)
    assert "tabs" not in s.to_dict()                 # alte Dateien bleiben byte-gleich
    s = tabs.with_tab_points(s, [(70.0, 50.0)])
    d = json.loads(json.dumps(s.to_dict()))
    assert d["tabs"] == [[0.5, 0.0]]
    assert Shape.from_dict(d).tabs == ((0.5, 0.0),)
    d["tabs"] = [[0.25, 1.0], ["x", 1], [1], None, [float("nan"), 0]]
    assert Shape.from_dict(d).tabs == ((0.25, 1.0),)
    doc.add_shape(s)
    again = Document.from_dict(json.loads(json.dumps(doc.to_dict())))
    assert again.shapes[0].tab_points() == [(70.0, 50.0)]
    c = s.copy(new_identity=True)                    # Duplizieren / Array nehmen sie mit
    assert c.tabs == s.tabs and c.id != s.id


def test_add_remove_move_clear(doc):
    s = rect(doc.active_layer_id)
    new, why = tabs.add_tab(s, (70.3, 49.2), 1.0)
    assert why == "" and new.tab_points() == [(70.3, 50.0)]
    assert tabs.add_tab(new, (70.4, 50.5), 1.0)[0] is None            # schon ein Steg dort
    assert "schon" in tabs.add_tab(new, (70.4, 50.5), 1.0)[1]
    assert tabs.add_tab(new, (70.0, 60.0), 1.0)[0] is None            # Mitte, kein Umriss
    two, _ = tabs.add_tab(new, (90.5, 62.0), 1.0)
    assert two.tab_points() == [(70.3, 50.0), (90.0, 62.0)]
    assert tabs.tab_at(two, (90.2, 62.2), 0.5) == 1 and tabs.tab_at(two, (80, 60), 0.5) is None
    moved = tabs.move_tab(two, 0, (60.0, 75.0))                       # unter das Rechteck gezogen
    assert moved.tab_points()[0] == (60.0, 70.0)
    assert tabs.remove_tab(two, 0).tab_points() == [(90.0, 62.0)]
    assert tabs.clear_tabs(two).tabs == () and two.tabs                # Original unverändert


def test_which_kinds_take_tabs(doc, qapp):
    lid = doc.active_layer_id
    assert tabs.can_have_tabs(rect(lid))
    assert tabs.can_have_tabs(Shape("ellipse", Geometry(0, 0, 10, 10), lid))
    assert tabs.can_have_tabs(Shape("text", Geometry(0, 0, 30, 10), lid, text="O"))
    assert not tabs.can_have_tabs(Shape("line", Geometry(0, 0, 10, 10), lid))
    assert not tabs.can_have_tabs(Shape.from_points("path", [(0, 0), (10, 0), (10, 10)], lid))
    assert tabs.add_tab(Shape("line", Geometry(0, 0, 10, 10), lid), (5, 5), 1)[0] is None


# --- Übertragen bei Pfad-Operationen ---------------------------------------------------

def test_tabs_carried_through_node_edit_and_simplify(doc):
    lid = doc.active_layer_id
    poly = Shape.from_points("polygon", [(0, 0), (40, 0), (40, 20), (0, 20)], lid)
    poly = tabs.with_tab_points(poly, [(20.0, 0.0), (0.0, 10.0)])
    edited = nodes.move_node(poly, 2, (60.0, 30.0))       # Box wird größer
    pts = edited.tab_points()
    assert pts[0] == pytest.approx((20.0, 0.0)) and pts[1] == pytest.approx((0.0, 10.0))
    assert on_outline(edited, pts)
    dense = Shape.from_points("polygon", [(x, 0.0) for x in range(0, 41)] + [(40, 20), (0, 20)], lid)
    dense = tabs.with_tab_points(dense, [(20.5, 0.0)])
    simple = pathsimplify.simplify_shape(dense, 0.05)
    assert len(simple.points) == 4 and simple.tab_points() == [pytest.approx((20.5, 0.0))]


def test_tabs_carried_through_break_apart_combine_and_text_outline(doc, qapp):
    lid = doc.active_layer_id
    a = tabs.with_tab_points(Shape.from_points("polygon", square(0, 0, 20)[:-1], lid), [(10.0, 0.0)])
    b = tabs.with_tab_points(Shape.from_points("polygon", square(40, 0, 20)[:-1], lid),
                             [(60.0, 10.0), (50.0, 20.0)])
    res = pathsplit.combine([a, b])
    (combined,) = res.add
    assert sorted(combined.tab_points()) == pytest.approx(sorted([(10.0, 0.0), (60.0, 10.0),
                                                                  (50.0, 20.0)]))
    parts = pathsplit.break_shape(combined)
    assert sorted(len(p.tabs) for p in parts) == [1, 2]
    for p in parts:
        assert on_outline(p, p.tab_points())
    t = Shape("text", Geometry(10, 10, 30, 12), lid, text="I")
    ring = tabs.closed_rings(t)[0]
    t = tabs.with_tab_points(t, [ring[1]])
    out = pathops.text_to_outline(t)
    assert len(out.tabs) == 1 and on_outline(out, out.tab_points(), 0.1)


# --- Planer / G-Code --------------------------------------------------------------------

def test_manual_intervals_clamp_merge_and_short_contours():
    sq = square(0, 0, 50)                                    # Umfang 200, Start (0, 0)
    assert manual_tab_intervals(sq, [(25, 0)], 2.0) == [pytest.approx((24.0, 26.0))]
    # am Konturstart: Mitte hält width/2 + 0,5 mm Abstand
    assert manual_tab_intervals(sq, [(0.2, 0)], 2.0) == [pytest.approx((0.5, 2.5))]
    assert manual_tab_intervals(sq, [(0, 0.2)], 2.0) == [pytest.approx((197.5, 199.5))]
    # sich berührende Stege verschmelzen, Reihenfolge der Punkte egal
    assert manual_tab_intervals(sq, [(26, 0), (25, 0), (50, 20)], 2.0) == [
        pytest.approx((24.0, 27.0)), pytest.approx((69.0, 71.0))]
    assert manual_tab_intervals(square(0, 0, 0.6), [(0.3, 0)], 1.0) == []    # zu kurz (< 2 · Breite + 1)
    assert manual_tab_intervals(sq, [(25, 0)], 0.0) == []
    assert manual_tab_intervals(sq[:-1], [(25, 0)], 1.0) == []             # offen


def test_points_go_to_the_nearest_contour():
    outer, inner, far = square(0, 0, 50), square(10, 10, 30), square(100, 0, 10)
    got, dropped = assign_tab_points([outer, inner, far, [(0, 60), (50, 60)]],
                                     [(25, 0.4), (25, 10.3), (25, 9.0), (30, 61), (200, 200)], 1.5)
    assert got == {0: [(25.0, 0.4)], 1: [(25.0, 10.3), (25.0, 9.0)]}
    assert dropped == 2                                  # offene Linie und weit weg


def test_manual_tabs_replace_auto_tabs_on_their_contour_only():
    a, b = square(0, 0, 50), square(100, 0, 50)
    opts = CutOptions(tab_count=4, tab_width_mm=2.0, tab_points=((125.0, 0.0),))
    res = apply_cut_options([a, b], opts, [0, 0])
    tabs_a = sum(1 for k in res.kinds if k == KIND_TAB)
    assert res.manual_tabs == 1 and res.dropped_tabs == 0
    # a: 4 automatische Stege (4 Lücken), b: genau eine Lücke an x = 125
    assert tabs_a == 4 + 1
    pieces_b = [p for p in res.polylines if p[0][0] >= 100]
    assert len(pieces_b) == 2
    ends = sorted([pieces_b[0][-1], pieces_b[1][0]])
    assert ends == [pytest.approx((124.0, 0.0)), pytest.approx((126.0, 0.0))]


def test_manual_tabs_without_auto_settings_and_with_skip_inner_and_pulses():
    outer, hole = square(0, 0, 50), square(10, 10, 30)
    # keine Anzahl / kein Abstand: nur die manuellen Stege; auch an innen liegenden Konturen
    opts = CutOptions(tab_width_mm=1.0, tab_skip_inner=True, tab_points=((25.0, 10.0),))
    assert opts.manual_tabs and not opts.auto_tabs and opts.active and opts.shapes_contours
    res = apply_cut_options([hole, outer], opts, [1, 0])
    assert res.kinds.count(KIND_TAB) == 1 and res.manual_tabs == 1
    # Stegbreite 0: keine Stege, auch keine manuellen
    off = CutOptions(tab_width_mm=0.0, tab_points=((25.0, 10.0),))
    assert not off.manual_tabs and not off.active
    # Steg-Leistung gilt auch für manuelle Stege
    pulsed = apply_cut_options([outer], CutOptions(tab_width_mm=2.0, tab_cut_power=50,
                                                   tab_points=((25.0, 0.0),)), [0])
    assert KIND_TAB_PULSE in pulsed.kinds and KIND_TAB_OFF in pulsed.kinds
    # Layer ohne manuelle Stege: Ausgabe wie bisher (automatische Stege)
    plain = apply_cut_options([outer], CutOptions(tab_count=3, tab_width_mm=2.0), [0])
    assert plain.manual_tabs == 0 and plain.kinds.count(KIND_TAB) == len(tab_intervals(outer, 3, 2.0))


def test_gcode_burns_perimeter_minus_manual_tabs_and_passes_the_pi_guard(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, tab_width_mm=2.0)
    s = tabs.with_tab_points(rect(lid), [(70.0, 50.0), (90.0, 60.0), (60.0, 70.0)])
    doc.add_shape(s)
    report = PlanReport()
    g = optimized_document_gcode(doc, scan_offsets=None, report=report)
    assert burned(g) == pytest.approx(120.0 - 3 * 2.0, abs=1e-3)
    assert gaps(g) == 3 and report.manual_tabs == 3 and report.dropped_tabs == 0
    assert not re.search(r"^G[23]\b", g, re.M)
    pi_check(g)
    # Lücke genau am Steg (Maschinen-mm)
    mx, my = to_machine(70.0, 50.0)
    lines = g.splitlines()
    g0 = [ln for ln in lines if ln.startswith("G0 X")][1:]
    xs = sorted(float(ln.split()[1][1:]) for ln in g0 if abs(float(ln.split()[2][1:]) - my) < 1e-6)
    assert any(abs(x - (mx - 1)) < 1e-3 or abs(x - (mx + 1)) < 1e-3 for x in xs)
    # ohne manuelle Stege: kein Steg
    doc.shapes[0].tabs = ()
    assert burned(optimized_document_gcode(doc, scan_offsets=None)) == pytest.approx(120.0, abs=1e-3)


def test_gcode_with_rotation_kerf_lead_in_and_reversed_direction(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, tab_width_mm=1.5, kerf_mm=0.2, lead_in_mm=2.0)
    s = rect(lid, rot=25.0)
    ring = tabs.closed_rings(s)[0]
    mid = ((ring[0][0] + ring[1][0]) / 2, (ring[0][1] + ring[1][1]) / 2)
    doc.add_shape(tabs.with_tab_points(s, [mid]))
    report = PlanReport()
    g = optimized_document_gcode(doc, scan_offsets=None, report=report)
    assert report.manual_tabs == 1 and report.dropped_tabs == 0
    per = 2 * (40.4 + 20.4)                         # Kerf 0,2 mm nach außen
    lead = 2.0
    assert burned(g) == pytest.approx(per - 1.5 + lead, abs=0.05)
    pi_check(g)


def test_dropped_tabs_reported(doc):
    lid = doc.active_layer_id
    s = rect(lid)
    s.tabs = ((0.5, 0.5),)                               # Mitte: keine Kontur in der Nähe
    doc.add_shape(s)
    report = PlanReport()
    g = optimized_document_gcode(doc, scan_offsets=None, report=report)
    assert report.dropped_tabs == 1 and burned(g) == pytest.approx(120.0, abs=1e-3)
    assert "1 manueller Steg weggelassen" in report.message()


def test_job_layers_collect_tab_points_of_burned_contours(doc):
    lid = doc.active_layer_id
    doc.add_shape(tabs.with_tab_points(rect(lid), [(70.0, 50.0)]))
    (jl,) = job_layers(doc)
    assert jl.tab_points == (to_machine(70.0, 50.0),)
    out = optimize_layers([jl])
    assert out[0].tab_points == jl.tab_points
    doc.update_layer(lid, fill_mode="hatch", hatch_outline=False)   # nur Füllung: keine Kontur
    assert job_layers(doc)[0].tab_points == ()
    doc.update_layer(lid, fill_mode="none", hatch_outline=True, visible=False)
    assert job_layers(doc) == []


def test_overlap_removal_skipped_with_manual_tabs(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, overlap_tol_mm=0.05)
    doc.add_shape(tabs.with_tab_points(rect(lid), [(70.0, 50.0)]))
    doc.add_shape(rect(lid, x=90.0))                     # teilt eine Kante
    report = PlanReport()
    optimized_document_gcode(doc, scan_offsets=None, report=report)
    assert report.overlap_skipped and not report.overlap_removed


# --- Werkzeug „Stege“ im Canvas -------------------------------------------------------------

def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, shapes))
    return shapes


def click(ed, x, y):
    ed.tools.press(QPointF(x, y), Qt.NoModifier)
    ed.tools.release(QPointF(x, y), Qt.NoModifier)


def test_tool_sets_and_removes_tabs_with_one_undo_step_each(ed):
    msgs = []
    ed.statusMessage.connect(msgs.append)
    (s,) = _add(ed, [rect(ed.document.active_layer_id)])
    ed.actions_by_name["tool_tabs"].trigger()
    assert ed.tools.tool == Tool.TABS and "Steg antippen entfernt" in msgs[-1]
    n0 = ed.undo_stack.count()
    click(ed, 70.0, 50.2)
    shape = ed.document.shape(s.id)
    assert shape.tab_points() == [(70.0, 50.0)] and ed.undo_stack.count() == n0 + 1
    assert ed.selection == [s.id]
    assert "Steg gesetzt – 1 manueller Steg" in msgs[-1] and "Stegbreite 1 mm" in msgs[-1]
    assert len(ed.tab_tool.item.marks) == 1
    click(ed, 90.0, 61.0)
    assert len(ed.document.shape(s.id).tabs) == 2
    click(ed, 70.1, 50.0)                                  # Tippen auf den Steg entfernt ihn
    assert ed.document.shape(s.id).tab_points() == [(90.0, 61.0)]
    assert "Steg entfernt" in msgs[-1]
    ed.undo_stack.undo()
    assert len(ed.document.shape(s.id).tabs) == 2
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert ed.document.shape(s.id).tabs == () and ed.tab_tool.item.marks == []
    click(ed, 70.0, 60.0)                                  # mitten in der Fläche: Hinweis
    assert ed.document.shape(s.id).tabs == () and "Umriss" in msgs[-1]


def test_tool_drags_tab_along_outline_and_escape_restores(ed):
    (s,) = _add(ed, [rect(ed.document.active_layer_id)])
    ed.set_tool(Tool.TABS)
    click(ed, 70.0, 50.0)
    n0 = ed.undo_stack.count()
    ed.tools.press(QPointF(70.0, 50.0), Qt.NoModifier)
    assert ed.tab_tool.hot == (s.id, 0)
    ed.tools.move(QPointF(75.0, 45.0), Qt.NoModifier, True)
    ed.tools.move(QPointF(80.0, 48.0), Qt.NoModifier, True)
    assert ed.document.shape(s.id).tab_points() == [(80.0, 50.0)]
    ed.tools.release(QPointF(80.0, 48.0), Qt.NoModifier)
    assert ed.undo_stack.count() == n0 + 1 and ed.undo_stack.undoText() == "Steg verschieben"
    assert ed.document.shape(s.id).tab_points() == [(80.0, 50.0)]
    ed.undo_stack.undo()
    assert ed.document.shape(s.id).tab_points() == [(70.0, 50.0)]
    ed.tools.press(QPointF(70.0, 50.0), Qt.NoModifier)
    ed.tools.move(QPointF(85.0, 55.0), Qt.NoModifier, True)
    ed.tools.cancel()
    assert ed.document.shape(s.id).tab_points() == [(70.0, 50.0)] and ed.tab_tool.hot is None


def test_tool_status_warns_about_zero_width_and_replaced_auto_tabs(ed):
    msgs = []
    ed.statusMessage.connect(msgs.append)
    lid = ed.document.active_layer_id
    _add(ed, [rect(lid)])
    ed.set_tool(Tool.TABS)
    ed.document.update_layer(lid, tab_count=4)
    click(ed, 70.0, 50.0)
    assert "ersetzt an dieser Kontur die automatischen Stege" in msgs[-1]
    ed.document.update_layer(lid, tab_width_mm=0.0)
    click(ed, 90.0, 60.0)
    assert "Stegbreite der Ebene" in msgs[-1] and "ist 0" in msgs[-1]


def test_locked_layer_and_hidden_layer(ed):
    lid = ed.document.active_layer_id
    (s,) = _add(ed, [tabs.with_tab_points(rect(lid), [(70.0, 50.0)])])
    ed.set_tool(Tool.TABS)
    ed.document.update_layer(lid, locked=True)
    click(ed, 90.0, 60.0)
    click(ed, 70.0, 50.0)
    assert ed.document.shape(s.id).tab_points() == [(70.0, 50.0)]
    assert len(ed.tab_tool.item.marks) == 1
    ed.document.update_layer(lid, locked=False, visible=False)
    assert ed.tab_tool.item.marks == []


def test_clear_action_in_path_menu_one_undo_step(ed):
    msgs = []
    ed.statusMessage.connect(msgs.append)
    lid = ed.document.active_layer_id
    a, b, c = _add(ed, [tabs.with_tab_points(rect(lid), [(70.0, 50.0), (50.0, 60.0)]),
                        tabs.with_tab_points(rect(lid, y=100), [(70.0, 100.0)]), rect(lid, y=150)])
    texts = [x.text() for x in ed.path_ops_button.menu().actions() if x.text()]
    assert "Stege" in texts and "Manuelle Stege entfernen" in texts
    assert "manuelle Stege" in ed.path_ops_button.toolTip()
    ed.set_selection([c.id])
    ed.actions_by_name["tabs_clear"].trigger()
    assert "keine manuellen Stege" in msgs[-1]
    ed.set_selection([a.id, b.id, c.id])
    n0 = ed.undo_stack.count()
    ed.actions_by_name["tabs_clear"].trigger()
    assert all(not s.tabs for s in ed.document.shapes) and ed.undo_stack.count() == n0 + 1
    assert "3 manuelle Stege entfernt (2 Objekt(e))" in msgs[-1]
    ed.undo_stack.undo()
    assert [len(s.tabs) for s in ed.document.shapes] == [2, 1, 0]


def test_tool_in_strip_icon_and_shortcut(ed):
    a = ed.actions_by_name["tool_tabs"]
    assert a in ed.tool_strip.actions() and a.isCheckable() and not a.icon().isNull()
    assert TOOL_SHORTCUTS[Tool.TABS] == "Alt+Shift+T"
    assert a.shortcut().toString() == "Alt+Shift+T"


def test_editor_file_round_trip_and_path_preview_gaps(ed, tmp_path):
    lid = ed.document.active_layer_id
    ed.document.update_layer(lid, tab_width_mm=2.0)
    _add(ed, [tabs.with_tab_points(rect(lid), [(70.0, 50.0)])])
    path = ed.save_file(tmp_path / "steg.lcs")
    ed.undo_stack.setClean()
    ed.load_file(path)
    (s,) = ed.document.shapes
    assert s.tab_points() == [(70.0, 50.0)]
    assert ed.tab_tool.item.scene() is ed.scene and len(ed.tab_tool.item.marks) == 1
    g = optimized_document_gcode(ed.document, scan_offsets=None)
    assert burned(g) == pytest.approx(118.0, abs=1e-3)


def test_main_window_shortcut_unique(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    try:
        owners = [a for a in w.findChildren(QAction) if a.shortcut() == QKeySequence("Alt+Shift+T")]
        assert [a.text() for a in owners] == ["Stege"]
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
