"""Manueller Startpunkt (LightBurn *Set Start Point*): Startpunkt je Objekt auf dem Umriss
setzen, verschieben, entfernen – Modell, Übertragen bei Pfad-Operationen, Export / Planer /
G-Code (auch mit Kerf, An-/Abfahrt, Überschnitt, Stegen), Werkzeug „Startpunkt“, Menü,
Hauptfenster."""

from __future__ import annotations

import json
import math

import pytest
from _pi_guard import pi_check
from PySide6.QtCore import QPointF, Qt

from lumacut_canvas import corners, icons, ngon, nodes, pathops, pathsimplify, pathsplit, startpoint, tabs
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.export import job_layers
from lumacut_canvas.model import CutOrder, Document, Geometry, Shape
from lumacut_canvas.toolpath import parse_gcode
from lumacut_canvas.tools import TOOL_LABELS, TOOL_SHORTCUTS, Tool
from lumacut_canvas.workarea import to_machine
from lumacut_job.cutpath import KIND_LEAD_IN, KIND_LEAD_OUT, CutOptions, apply_cut_options
from lumacut_job.planner import PlanReport, optimize_layers, optimized_document_gcode, order_polylines


def square(x, y, s):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]


def rect(lid, x=50.0, y=50.0, w=40.0, h=20.0, rot=0.0):
    return Shape("rect", Geometry(x, y, w, h, rot), lid)


def moves(g: str) -> list[str]:
    return [ln for ln in g.splitlines() if ln.startswith(("G0 X", "G1 X"))]


def xy(line: str) -> tuple[float, float]:
    parts = dict((t[0], t[1:]) for t in line.split()[1:] if t[0] in "XY")
    return (float(parts["X"]), float(parts["Y"]))


def first_cut_start(g: str) -> tuple[float, float]:
    """Punkt, an dem der erste Schnitt beginnt (= Ziel der G0 davor)."""
    lines = moves(g)
    i = next(i for i, ln in enumerate(lines) if ln.startswith("G1"))
    return xy(lines[i - 1])


def burned(g: str) -> float:
    return parse_gcode(g).cut_length_mm


def no_arcs(g: str) -> bool:
    return not any(ln.split()[0] in ("G2", "G3", "G02", "G03") for ln in g.splitlines() if ln.strip())


@pytest.fixture
def doc(qapp):
    return Document()


@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    e.msgs = []
    e.statusMessage.connect(e.msgs.append)
    yield e
    e.undo_stack.setClean()
    e.close()


# --- Modell -------------------------------------------------------------------------------

def test_start_follows_move_scale_rotate_and_copy(doc):
    s = startpoint.with_start(rect(doc.active_layer_id), (70.0, 70.0))
    assert s.start == (0.5, 1.0) and s.start_point() == (70.0, 70.0)
    s.geom = s.geom.translated(10, 5)
    assert s.start_point() == (80.0, 75.0)
    s.geom = s.geom.mapped(s.geom.bounds(), type(s.geom.bounds())(60, 55, 80, 40))
    assert s.start_point() == pytest.approx((100.0, 95.0))
    s.geom = Geometry(s.geom.x, s.geom.y, s.geom.w, s.geom.h, 90.0)
    cx, cy = s.geom.center()
    assert s.start_point() == pytest.approx((cx - 20.0, cy))      # untere Mitte → links
    c = s.copy(new_identity=True)
    assert c.start == s.start and c.id != s.id
    assert rect(doc.active_layer_id).start_point() is None


def test_saved_in_project_old_files_unchanged_and_broken_values(doc):
    s = rect(doc.active_layer_id)
    assert "start" not in s.to_dict()                 # alte Dateien bleiben byte-gleich
    s = startpoint.with_start(s, (50.0, 60.0))
    d = json.loads(json.dumps(s.to_dict()))
    assert d["start"] == [0.0, 0.5]
    assert Shape.from_dict(d).start == (0.0, 0.5)
    for bad in (None, "x", "12", [1], ["a", 1], [float("nan"), 0], {"u": 1}, 5):
        d["start"] = bad
        assert Shape.from_dict(d).start == ()
    line = Shape("line", Geometry(0, 0, 10, 0), doc.active_layer_id).to_dict()
    line["start"] = [0.5, 0.0]
    assert Shape.from_dict(line).start == ()          # Linien haben keinen Startpunkt
    doc.add_shape(s)
    again = Document.from_dict(json.loads(json.dumps(doc.to_dict())))
    assert again.shapes[0].start_point() == (50.0, 60.0)


def test_set_clear_and_which_kinds(doc, qapp):
    lid = doc.active_layer_id
    s = rect(lid)
    new, why = startpoint.set_start(s, (70.0, 49.5), 1.0)
    assert why == "" and new.start_point() == pytest.approx((70.0, 50.0))
    none, why = startpoint.set_start(s, (70.0, 60.0), 1.0)
    assert none is None and "Umriss" in why
    assert startpoint.clear_start(new).start == ()
    for kind, geom in (("ellipse", Geometry(0, 0, 20, 10)), ("text", Geometry(0, 0, 30, 10))):
        sh = Shape(kind, geom, lid, text="O")
        assert startpoint.can_have_start(sh)
    assert not startpoint.can_have_start(Shape("line", Geometry(0, 0, 10, 0), lid))
    open_path = Shape.from_points("path", [(0, 0), (10, 0), (10, 10)], lid)
    assert not startpoint.can_have_start(open_path)
    assert startpoint.set_start(open_path, (5.0, 0.0), 1.0)[0] is None


def test_rotate_ring_keeps_direction_and_inserts_node():
    ring = square(0, 0, 10)
    assert startpoint.rotate_ring_to(ring, (0.0, 0.0)) == ring           # schon dort
    r = startpoint.rotate_ring_to(ring, (10.2, 0.0))                       # Ecke
    assert r == [(10, 0), (10, 10), (0, 10), (0, 0), (10, 0)]
    r = startpoint.rotate_ring_to(ring, (5.0, 10.3))                       # Kantenmitte
    assert r[0] == pytest.approx((5.0, 10.0)) and r[-1] == r[0] and len(r) == 6
    assert r[1] == (0, 10)                                                 # gleiche Laufrichtung
    per = sum(math.dist(a, b) for a, b in zip(r, r[1:]))
    assert per == pytest.approx(40.0)


def test_apply_start_points_nearest_contour_reach_and_conflicts():
    a, b = square(0, 0, 10), square(20, 0, 10)
    polys, placed, dropped = startpoint.apply_start_points([a, b], [(25.0, 0.5)], 1.5)
    assert polys[0] == a and polys[1][0] == pytest.approx((25.0, 0.0)) and dropped == 0
    assert placed == [polys[1][0]]
    polys, placed, dropped = startpoint.apply_start_points([a, b], [(15.0, 5.0)], 1.5)
    assert polys == [a, b] and placed == [] and dropped == 1               # zu weit weg
    polys, placed, dropped = startpoint.apply_start_points([a], [(5.0, 0.4), (5.0, 0.1)], 1.5)
    assert placed == [pytest.approx((5.0, 0.0))] and dropped == 1          # der nähere gilt
    line = [(0.0, 20.0), (10.0, 20.0)]
    polys, placed, dropped = startpoint.apply_start_points([line], [(5.0, 20.0)], 1.5)
    assert polys == [line] and dropped == 1                                # offene Pfade nie


# --- Übertragen bei Pfad-Operationen ---------------------------------------------------------

def on_outline(shape, p, tol=1e-6):
    return startpoint.nearest_outline(shape, p)[0] <= tol


def test_start_carried_through_node_edit_simplify_and_corner_radius(doc):
    lid = doc.active_layer_id
    poly = Shape.from_points("polygon", [(0, 0), (40, 0), (40, 20), (0, 20)], lid)
    poly = startpoint.with_start(poly, (20.0, 0.0))
    edited = nodes.move_node(poly, 2, (60.0, 30.0))         # Box wird größer
    assert edited.start_point() == pytest.approx((20.0, 0.0)) and on_outline(edited, edited.start_point())
    dense = Shape.from_points("polygon", [(x, 0.0) for x in range(0, 41)] + [(40, 20), (0, 20)], lid)
    dense = startpoint.with_start(dense, (20.5, 0.0))
    simple = pathsimplify.simplify_shape(dense, 0.05)
    assert len(simple.points) == 4 and simple.start_point() == pytest.approx((20.5, 0.0))
    r = startpoint.with_start(rect(lid), (50.0, 50.0))        # Ecke
    rounded = corners.with_corner_radius(r, 5.0)
    assert rounded.start and on_outline(rounded, rounded.start_point(), 1e-3)
    assert math.dist(rounded.start_point(), (50.0, 50.0)) < 3.0     # auf den Bogen gewandert


def test_start_carried_through_break_apart_combine_text_and_cleared_by_sides(doc, qapp):
    lid = doc.active_layer_id
    a = startpoint.with_start(Shape.from_points("polygon", square(0, 0, 20)[:-1], lid), (10.0, 0.0))
    b = startpoint.with_start(Shape.from_points("polygon", square(40, 0, 20)[:-1], lid), (60.0, 10.0))
    (combined,) = pathsplit.combine([a, b]).add
    assert combined.start_point() == pytest.approx((10.0, 0.0))       # der erste bleibt
    parts = pathsplit.break_shape(combined)
    assert sorted(bool(p.start) for p in parts) == [False, True]
    (with_start,) = [p for p in parts if p.start]
    assert with_start.start_point() == pytest.approx((10.0, 0.0))
    t = Shape("text", Geometry(10, 10, 30, 12), lid, text="I")
    ring = tabs.closed_rings(t)[0]
    out = pathops.text_to_outline(startpoint.with_start(t, ring[1]))
    assert out.start and on_outline(out, out.start_point(), 0.1)
    star = startpoint.with_start(ngon.make_shape(lid, 50, 50, 20, 6), (50.0, 30.0))
    assert ngon.with_spec(star, sides=8).start == ()                  # neue Ecken: Start fällt weg


# --- Export / Planer / G-Code -------------------------------------------------------------------

def test_job_layers_rotate_the_contour_and_collect_machine_points(doc):
    lid = doc.active_layer_id
    doc.add_shape(startpoint.with_start(rect(lid), (70.0, 70.0)))
    doc.add_shape(rect(lid, y=100.0))
    (jl,) = job_layers(doc)
    assert jl.polylines[0][0] == to_machine(70.0, 70.0) and jl.polylines[0][-1] == jl.polylines[0][0]
    assert len(jl.polylines[0]) == 6 and jl.start_points == (to_machine(70.0, 70.0),)
    assert jl.polylines[1][0] == to_machine(50.0, 100.0)               # ohne Startpunkt unverändert
    doc.update_layer(lid, fill_mode="hatch", hatch_outline=False)     # nur Füllung: keine Kontur
    (jl,) = job_layers(doc)
    assert jl.polylines == [] and jl.start_points == ()


@pytest.mark.parametrize("order", [CutOrder(), CutOrder(corners=True), CutOrder(enabled=False),
                                   CutOrder(direction="top_bottom")])
def test_gcode_starts_at_the_point_with_every_optimisation(doc, order):
    lid = doc.active_layer_id
    doc.set_cut_order(order)
    doc.add_shape(rect(lid))
    g0 = optimized_document_gcode(doc, scan_offsets=None)
    doc.shapes[0].start = startpoint.with_start(doc.shapes[0], (70.0, 70.0)).start
    report = PlanReport()
    g = optimized_document_gcode(doc, scan_offsets=None, report=report)
    assert first_cut_start(g) == pytest.approx(to_machine(70.0, 70.0))
    assert first_cut_start(g0) != pytest.approx(to_machine(70.0, 70.0))
    assert burned(g) == pytest.approx(burned(g0)) == pytest.approx(120.0)
    assert xy(moves(g)[-1]) == pytest.approx(to_machine(70.0, 70.0))   # geschlossen am Start
    assert report.manual_starts == 1 and report.dropped_starts == 0 and "Startpunkt" not in report.message()
    assert no_arcs(g)
    pi_check(g)


def test_without_start_points_gcode_unchanged(doc):
    lid = doc.active_layer_id
    for i in range(4):
        doc.add_shape(rect(lid, x=20.0 + 50 * i, y=40.0 + 7 * i, rot=15.0 * i))
    doc.add_shape(Shape("ellipse", Geometry(60, 120, 30, 20), lid))
    g = optimized_document_gcode(doc, scan_offsets=None)
    (jl,) = job_layers(doc)
    assert jl.start_points == ()
    ref = order_polylines(jl.polylines, (30.0, 30.0))
    assert order_polylines(jl.polylines, (30.0, 30.0), fixed_starts=set()) == ref
    assert order_polylines(jl.polylines, (30.0, 30.0), fixed_starts=None) == ref
    # Startpunkt setzen und wieder entfernen: identisch
    ring = tabs.closed_rings(doc.shapes[1])[0]
    mid = ((ring[1][0] + ring[2][0]) / 2, (ring[1][1] + ring[2][1]) / 2)
    doc.shapes[1].start = startpoint.with_start(doc.shapes[1], mid).start
    assert optimized_document_gcode(doc, scan_offsets=None) != g
    doc.shapes[1].start = ()
    assert optimized_document_gcode(doc, scan_offsets=None) == g


def test_kerf_lead_in_overcut_and_lead_out_start_at_the_point(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=0.2, lead_in_mm=2.0, overcut_mm=1.0, lead_out_mm=1.5)
    doc.add_shape(startpoint.with_start(rect(lid), (60.0, 70.0)))
    (jl,) = optimize_layers(job_layers(doc))
    kinds = list(jl.poly_kinds)
    lead = jl.polylines[kinds.index(KIND_LEAD_IN)]
    cut = jl.polylines[kinds.index("cut")]
    target = to_machine(60.0, 70.2)                                # Kerf 0,2 mm nach außen
    assert lead[-1] == pytest.approx(target, abs=1e-6) and cut[0] == pytest.approx(target, abs=1e-6)
    assert math.dist(cut[-1], target) > 0.9                        # Überschnitt 1 mm weiter
    out = jl.polylines[kinds.index(KIND_LEAD_OUT)]
    assert out[0] == pytest.approx(cut[-1], abs=1e-6)
    # nur Abfahrt: der Start bleibt (keine Kantenmitte)
    doc.update_layer(lid, kerf_mm=0.0, lead_in_mm=0.0, overcut_mm=0.0)
    doc.shapes[0].start = startpoint.with_start(doc.shapes[0], (50.0, 50.0)).start   # Ecke
    (jl,) = optimize_layers(job_layers(doc))
    assert jl.polylines[0][0] == pytest.approx(to_machine(50.0, 50.0))
    g = optimized_document_gcode(doc, scan_offsets=None)
    assert no_arcs(g)
    pi_check(g)


def test_blocked_lead_in_keeps_the_start_and_may_only_reverse():
    from lumacut_job.cutpath import LeadObstacles
    ring = startpoint.rotate_ring_to(square(100, 100, 10), (100.0, 105.0))
    opts = CutOptions(lead_in_mm=2.0, start_points=(ring[0],))
    res = apply_cut_options([ring], opts, [0])
    cut = res.polylines[res.kinds.index("cut")]
    assert cut[0] == pytest.approx((100.0, 105.0)) and res.moved_leads == 0
    free = apply_cut_options([square(100, 100, 10)], CutOptions(lead_in_mm=2.0), [0])
    assert free.polylines[free.kinds.index("cut")][0] == pytest.approx((105.0, 100.0))  # Kantenmitte
    # Ein Teil direkt links neben dem Startpunkt: die Anfahrt wird nie an eine andere
    # Stelle verlegt – kürzer oder weggelassen, der Schnitt beginnt trotzdem am Startpunkt.
    block = [(97.0, 101.0), (99.6, 101.0), (99.6, 109.0), (97.0, 109.0), (97.0, 101.0)]
    obstacles = LeadObstacles([ring, block])
    res = apply_cut_options([ring], opts, [0], obstacles)
    cut = res.polylines[res.kinds.index("cut")]
    assert cut[0] == pytest.approx((100.0, 105.0)) and res.moved_leads == 0
    lid_block = [(102.5, 97.2), (107.5, 97.2), (107.5, 99.5), (102.5, 99.5), (102.5, 97.2)]
    plain = apply_cut_options([square(100, 100, 10)], CutOptions(lead_in_mm=2.0), [0],
                              LeadObstacles([square(100, 100, 10), lid_block]))
    assert plain.moved_leads == 1                       # ohne Startpunkt darf er verlegen


def test_tabs_stay_clear_of_the_start_and_holes_still_first(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, tab_count=2, tab_width_mm=1.0)
    plate = Shape.from_points("polygon", square(40, 40, 60)[:-1], lid)
    hole = startpoint.with_start(Shape.from_points("polygon", square(60, 60, 10)[:-1], lid), (65.0, 70.0))
    doc.add_shape(startpoint.with_start(plate, (40.0, 70.0)))
    doc.add_shape(hole)
    (jl,) = optimize_layers(job_layers(doc))
    cuts = [p for p, k in zip(jl.polylines, jl.poly_kinds) if k == "cut"]
    assert cuts[0][0] == pytest.approx(to_machine(65.0, 70.0))         # Loch zuerst, am Startpunkt
    assert to_machine(40.0, 70.0) in [pytest.approx(p[0]) for p in cuts]
    g = optimized_document_gcode(doc, scan_offsets=None)
    per = 4 * 60 + 4 * 10
    assert burned(g) == pytest.approx(per - 4 * 1.0, abs=0.05)         # 2 Stege je Kontur


def test_text_with_several_rings_only_the_nearest_ring_is_fixed(doc, qapp):
    lid = doc.active_layer_id
    t = Shape("text", Geometry(10, 10, 40, 15), lid, text="O")
    rings = tabs.closed_rings(t)
    assert len(rings) == 2
    p = rings[1][len(rings[1]) // 2]
    doc.add_shape(startpoint.with_start(t, p))
    (jl,) = job_layers(doc)
    assert jl.start_points == (to_machine(*p),) or jl.start_points[0] == pytest.approx(to_machine(*p))
    starts = [poly[0] for poly in jl.polylines]
    assert sum(1 for q in starts if math.dist(q, to_machine(*p)) < 1e-6) == 1


def test_dropped_start_reported(doc):
    lid = doc.active_layer_id
    doc.add_shape(rect(lid))
    (jl,) = job_layers(doc)
    report = PlanReport()
    from dataclasses import replace
    optimize_layers([replace(jl, start_points=((0.0, 0.0),))], report=report)
    assert report.dropped_starts == 1 and "1 Startpunkt weggelassen" in report.message()


def test_path_preview_and_estimate_follow_the_start(doc):
    from lumacut_job.estimate import estimate_gcode
    lid = doc.active_layer_id
    doc.add_shape(startpoint.with_start(rect(lid), (90.0, 60.0)))
    g = optimized_document_gcode(doc, scan_offsets=None)
    tp = parse_gcode(g)
    assert tp.cut_length_mm == pytest.approx(120.0)
    est = estimate_gcode(g)
    assert est.cut_length_mm == pytest.approx(120.0) and est.cut_time_s > 0


# --- Werkzeug „Startpunkt“ im Canvas -------------------------------------------------------

def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, shapes))
    return shapes


def click(ed, x, y):
    ed.tools.press(QPointF(x, y), Qt.NoModifier)
    ed.tools.release(QPointF(x, y), Qt.NoModifier)


def test_tool_sets_replaces_and_removes_with_one_undo_step_each(ed):
    (s,) = _add(ed, [rect(ed.document.active_layer_id)])
    ed.actions_by_name["tool_start"].trigger()
    assert ed.tools.tool == Tool.START and "Startpunkt antippen entfernt" in ed.msgs[-1]
    n0 = ed.undo_stack.count()
    click(ed, 70.0, 50.2)
    assert ed.document.shape(s.id).start_point() == pytest.approx((70.0, 50.0))
    assert ed.undo_stack.count() == n0 + 1 and ed.undo_stack.undoText() == "Startpunkt setzen"
    assert ed.selection == [s.id] and "Startpunkt gesetzt" in ed.msgs[-1]
    assert len(ed.start_tool.item.marks) == 1
    pt, direction, hot = ed.start_tool.item.marks[0]
    assert direction == pytest.approx((1.0, 0.0)) and not hot      # Rechteck läuft oben nach rechts
    click(ed, 90.0, 61.0)                                          # zweiter Klick ersetzt
    assert ed.document.shape(s.id).start_point() == pytest.approx((90.0, 61.0))
    assert "Startpunkt versetzt" in ed.msgs[-1] and len(ed.start_tool.item.marks) == 1
    assert ed.start_tool.item.marks[0][1] == pytest.approx((0.0, 1.0))   # rechte Kante abwärts
    click(ed, 90.1, 61.0)                                          # Tippen auf den Punkt entfernt
    assert ed.document.shape(s.id).start == () and "Startpunkt entfernt" in ed.msgs[-1]
    ed.undo_stack.undo()
    assert ed.document.shape(s.id).start_point() == pytest.approx((90.0, 61.0))
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert ed.document.shape(s.id).start == () and ed.start_tool.item.marks == []
    click(ed, 70.0, 60.0)                                          # mitten in der Fläche: Hinweis
    assert ed.document.shape(s.id).start == () and "Umriss" in ed.msgs[-1]


def test_tool_drags_along_outline_and_escape_restores(ed):
    (s,) = _add(ed, [rect(ed.document.active_layer_id)])
    ed.set_tool(Tool.START)
    click(ed, 70.0, 50.0)
    n0 = ed.undo_stack.count()
    ed.tools.press(QPointF(70.0, 50.0), Qt.NoModifier)
    assert ed.start_tool.hot == s.id
    ed.tools.move(QPointF(75.0, 45.0), Qt.NoModifier, True)
    ed.tools.move(QPointF(80.0, 48.0), Qt.NoModifier, True)
    assert ed.document.shape(s.id).start_point() == pytest.approx((80.0, 50.0))
    ed.tools.release(QPointF(80.0, 48.0), Qt.NoModifier)
    assert ed.undo_stack.count() == n0 + 1 and ed.undo_stack.undoText() == "Startpunkt verschieben"
    ed.undo_stack.undo()
    assert ed.document.shape(s.id).start_point() == pytest.approx((70.0, 50.0))
    ed.tools.press(QPointF(70.0, 50.0), Qt.NoModifier)
    ed.tools.move(QPointF(85.0, 55.0), Qt.NoModifier, True)
    ed.tools.cancel()
    assert ed.document.shape(s.id).start_point() == pytest.approx((70.0, 50.0))
    assert ed.start_tool.hot is None


def test_status_hints_lead_in_and_fill_without_outline(ed):
    lid = ed.document.active_layer_id
    _add(ed, [rect(lid)])
    ed.set_tool(Tool.START)
    ed.document.update_layer(lid, lead_in_mm=2.0)
    click(ed, 70.0, 50.0)
    assert "Anfahrt setzt hier an" in ed.msgs[-1]
    ed.document.update_layer(lid, fill_mode="hatch", hatch_outline=False)
    click(ed, 90.0, 60.0)
    assert "füllt ohne Kontur" in ed.msgs[-1]


def test_locked_and_hidden_layer(ed):
    lid = ed.document.active_layer_id
    (s,) = _add(ed, [startpoint.with_start(rect(lid), (70.0, 50.0))])
    ed.set_tool(Tool.START)
    ed.document.update_layer(lid, locked=True)
    click(ed, 90.0, 60.0)
    click(ed, 70.0, 50.0)
    assert ed.document.shape(s.id).start_point() == pytest.approx((70.0, 50.0))
    assert len(ed.start_tool.item.marks) == 1
    ed.document.update_layer(lid, locked=False, visible=False)
    assert ed.start_tool.item.marks == []


def test_clear_action_in_path_menu_one_undo_step(ed):
    lid = ed.document.active_layer_id
    a, b, c = _add(ed, [startpoint.with_start(rect(lid), (70.0, 50.0)),
                        startpoint.with_start(rect(lid, y=100), (70.0, 100.0)), rect(lid, y=150)])
    texts = [x.text() for x in ed.path_ops_button.menu().actions() if x.text()]
    assert "Startpunkt" in texts and "Startpunkte entfernen" in texts
    assert texts.index("Startpunkt") > texts.index("Manuelle Stege entfernen")
    ed.set_selection([c.id])
    ed.actions_by_name["start_clear"].trigger()
    assert "keine Startpunkte" in ed.msgs[-1]
    ed.set_selection([a.id, b.id, c.id])
    n0 = ed.undo_stack.count()
    ed.actions_by_name["start_clear"].trigger()
    assert all(not s.start for s in ed.document.shapes) and ed.undo_stack.count() == n0 + 1
    assert "2 Startpunkte entfernt" in ed.msgs[-1]
    ed.undo_stack.undo()
    assert [bool(s.start) for s in ed.document.shapes] == [True, True, False]


def test_tool_in_strip_icon_shortcut_and_touch_reach(ed):
    a = ed.actions_by_name["tool_start"]
    assert TOOL_LABELS[Tool.START] == "Startpunkt" and TOOL_SHORTCUTS[Tool.START] == "Alt+Shift+A"
    assert a in ed.tool_strip.actions() and a.isCheckable() and not a.icon().isNull()
    assert a.shortcut().toString() == "Alt+Shift+A" and "start" in icons.available()
    mouse = ed.start_tool.outline_tol_mm()
    ed.set_touch_mode(True, persist=False)
    try:
        assert ed.start_tool.outline_tol_mm() > mouse
        (s,) = _add(ed, [rect(ed.document.active_layer_id)])
        ed.set_tool(Tool.START)
        off = 0.6 * ed.start_tool.outline_tol_mm()
        click(ed, 70.0, 50.0 - off)                                 # Finger neben dem Umriss
        assert ed.document.shape(s.id).start_point() == pytest.approx((70.0, 50.0))
        ed.start_tool.item.sync()
        ed.start_tool.item.update()
    finally:
        ed.set_touch_mode(False, persist=False)


def test_editor_file_round_trip_and_gcode(ed, tmp_path):
    lid = ed.document.active_layer_id
    _add(ed, [startpoint.with_start(rect(lid), (90.0, 60.0))])
    path = ed.save_file(tmp_path / "start.lcs")
    ed.undo_stack.setClean()
    ed.load_file(path)
    (s,) = ed.document.shapes
    assert s.start_point() == pytest.approx((90.0, 60.0))
    assert ed.start_tool.item.scene() is ed.scene and len(ed.start_tool.item.marks) == 1
    g = optimized_document_gcode(ed.document, scan_offsets=None)
    assert first_cut_start(g) == pytest.approx(to_machine(90.0, 60.0))


def test_main_window_shortcut_unique(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    try:
        owners = [a for a in w.findChildren(QAction) if a.shortcut() == QKeySequence("Alt+Shift+A")]
        assert [a.text() for a in owners] == ["Startpunkt"]
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
