"""Laufrichtung umkehren (LightBurn *Edit › Reverse Shape Direction*): ``Shape.reverse`` –
Modell, Übertragen bei Pfad-Operationen, Export / Planer / G-Code (geschlossene Konturen
gleicher Start in Gegenrichtung, offene Pfade vom anderen Ende auch mit Optimierung, Kerf,
An-/Abfahrt, Überschnitt, Stege), Pfad › „Richtung umkehren“, Umschalt+Tippen im Werkzeug
„Startpunkt“, Pfeile, Hauptfenster."""

from __future__ import annotations

import json
import math
from dataclasses import replace

import pytest
from _pi_guard import pi_check
from PySide6.QtCore import QPointF, Qt

from lumacut_canvas import corners, direction, nodes, pathjoin, pathops, pathsimplify, pathsplit, startpoint
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.export import job_layers
from lumacut_canvas.model import REVERSE_KINDS, CutOrder, Document, Geometry, RasterImage, Shape
from lumacut_canvas.toolpath import parse_gcode
from lumacut_canvas.tools import Tool
from lumacut_canvas.workarea import to_machine
from lumacut_job.cutpath import KIND_LEAD_IN, KIND_LEAD_OUT
from lumacut_job.planner import optimize_layers, optimized_document_gcode, order_polylines


def square(x, y, s):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]


def rect(lid, x=50.0, y=50.0, w=40.0, h=20.0, rot=0.0):
    return Shape("rect", Geometry(x, y, w, h, rot), lid)


def rev(shape):
    return direction.with_reverse(shape, True)


def moves(g: str) -> list[str]:
    return [ln for ln in g.splitlines() if ln.startswith(("G0 X", "G1 X"))]


def xy(line: str) -> tuple[float, float]:
    parts = dict((t[0], t[1:]) for t in line.split()[1:] if t[0] in "XY")
    return (float(parts["X"]), float(parts["Y"]))


def first_cut(g: str) -> tuple[tuple[float, float], tuple[float, float]]:
    """Anfang des ersten Schnitts (Ziel der G0 davor) und das Ziel des ersten G1."""
    lines = moves(g)
    i = next(i for i, ln in enumerate(lines) if ln.startswith("G1"))
    return xy(lines[i - 1]), xy(lines[i])


def burned(g: str) -> float:
    return parse_gcode(g).cut_length_mm


def no_arcs(g: str) -> bool:
    return not any(ln.split()[0] in ("G2", "G3", "G02", "G03") for ln in g.splitlines() if ln.strip())


def signed_area(poly) -> float:
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:]))


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

def test_saved_only_when_set_round_trip_and_broken_values(doc):
    s = rect(doc.active_layer_id)
    assert s.reverse is False and "reverse" not in s.to_dict()      # alte Dateien byte-gleich
    r = rev(s)
    d = json.loads(json.dumps(r.to_dict()))
    assert d["reverse"] is True and Shape.from_dict(d).reverse is True
    for bad in (None, "true", 1, 0, [True], {"on": True}, False):
        d["reverse"] = bad
        assert Shape.from_dict(d).reverse is False
    doc.add_shape(r)
    again = Document.from_dict(json.loads(json.dumps(doc.to_dict())))
    assert again.shapes[0].reverse is True
    c = r.copy(new_identity=True)
    assert c.reverse and c.id != r.id
    moved = replace(r, geom=r.geom.translated(10, 5))
    assert moved.reverse


def test_which_kinds_and_toggle(doc):
    lid = doc.active_layer_id
    assert set(REVERSE_KINDS) == {"rect", "ellipse", "polygon", "path", "text", "line"}
    img = Shape("image", Geometry(0, 0, 10, 10), lid, image=RasterImage(b"", 1, 1))
    assert not direction.can_reverse(img) and direction.with_reverse(img, True).reverse is False
    img.reverse = True
    assert "reverse" not in img.to_dict()                           # Bilder haben keine Richtung
    line = Shape("line", Geometry(0, 0, 10, 0), lid)
    assert direction.can_reverse(line)
    t = direction.toggled(rect(lid))
    assert t.reverse and direction.toggled(t).reverse is False      # zweimal = wie gezeichnet
    assert direction.reverse_polyline([(0, 0), (1, 0), (1, 1)]) == [(1, 1), (1, 0), (0, 0)]
    ring = square(0, 0, 10)
    r = direction.reverse_polyline(ring)
    assert r[0] == ring[0] and r[1] == (0, 10) and signed_area(r) == -signed_area(ring)


def test_contours_markers_and_start_direction(doc):
    lid = doc.active_layer_id
    s = rect(lid)
    (c,) = direction.contours(s)
    assert c[0] == (50.0, 50.0) and c[1] == (90.0, 50.0)            # gezeichnet: oben nach rechts
    (c,) = direction.contours(rev(s))
    assert c[0] == (50.0, 50.0) and c[1] == (50.0, 70.0)            # umgekehrt: links abwärts
    assert direction.direction_marker(rev(s)) == ((50.0, 50.0), pytest.approx((0.0, 1.0)))
    sp = startpoint.with_start(s, (70.0, 50.0))
    assert startpoint.start_direction(sp) == pytest.approx((1.0, 0.0))
    assert startpoint.start_direction(rev(sp)) == pytest.approx((-1.0, 0.0))
    corner = startpoint.with_start(s, (90.0, 50.0))
    assert startpoint.start_direction(rev(corner)) == pytest.approx((-1.0, 0.0))   # zum vorigen Knoten
    open_path = rev(Shape.from_points("path", [(0, 0), (10, 0), (10, 10)], lid))
    assert direction.direction_marker(open_path) == ((10.0, 10.0), pytest.approx((0.0, -1.0)))
    line = rev(Shape("line", Geometry(0, 0, 10, 0), lid))
    m = direction.direction_marker(line)
    assert m[1] == pytest.approx((-1.0, 0.0))
    assert direction.reverse_count([s, rev(s), line]) == 2


# --- Übertragen bei Pfad-Operationen ---------------------------------------------------------

def test_carried_through_node_edit_simplify_corners_close_and_text(doc, qapp):
    lid = doc.active_layer_id
    poly = rev(Shape.from_points("polygon", [(0, 0), (40, 0), (40, 20), (0, 20)], lid))
    assert nodes.move_node(poly, 2, (60.0, 30.0)).reverse
    dense = rev(Shape.from_points("polygon", [(x, 0.0) for x in range(0, 41)] + [(40, 20), (0, 20)], lid))
    assert pathsimplify.simplify_shape(dense, 0.05).reverse
    assert corners.with_corner_radius(rev(rect(lid)), 5.0).reverse
    gap = rev(Shape.from_points("path", [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0.05)], lid))
    res = pathjoin.close_paths([gap], 0.5)
    assert len(res.add) == 1 and res.add[0].reverse
    t = rev(Shape("text", Geometry(10, 10, 30, 12), lid, text="IO"))
    out = pathops.text_to_outline(t)
    assert out.reverse
    # Text und seine Umrisse werden gleich (umgekehrt) geschnitten
    a = [p for p in direction.contours(t)]
    b = [p for p in direction.contours(out)]
    assert len(a) == len(b)
    assert [signed_area(p) > 0 for p in a] == [signed_area(p) > 0 for p in b]


def test_break_apart_keeps_it_and_combine_only_when_all_reversed(doc):
    lid = doc.active_layer_id
    a = rev(Shape.from_points("polygon", square(0, 0, 20)[:-1], lid))
    b = rev(Shape.from_points("polygon", square(40, 0, 20)[:-1], lid))
    c = Shape.from_points("polygon", square(80, 0, 20)[:-1], lid)
    (both,) = pathsplit.combine([a, b]).add
    assert both.reverse
    parts = pathsplit.break_shape(both)
    assert len(parts) == 2 and all(p.reverse for p in parts)
    (mixed,) = pathsplit.combine([a, c]).add
    assert mixed.reverse is False


# --- Export / Planer / G-Code -------------------------------------------------------------------

def test_job_layers_reverse_closed_contours_and_mark_open_ones(doc):
    lid = doc.active_layer_id
    doc.add_shape(rev(rect(lid)))
    doc.add_shape(rect(lid, y=100.0))
    doc.add_shape(rev(Shape.from_points("path", [(10, 150), (40, 150), (40, 170)], lid)))
    doc.add_shape(rev(Shape("line", Geometry(100, 150, 30, 0), lid)))
    (jl,) = job_layers(doc)
    r, plain, path, line = jl.polylines
    assert r[0] == to_machine(50.0, 50.0) and r[1] == to_machine(50.0, 70.0)
    assert plain[0] == to_machine(50.0, 100.0) and plain[1] == to_machine(90.0, 100.0)
    assert path[0] == to_machine(40.0, 170.0) and path[-1] == to_machine(10.0, 150.0)
    assert line[0] == to_machine(130.0, 150.0) and line[-1] == to_machine(100.0, 150.0)
    assert jl.kept_directions == (path[0], line[0])
    doc.update_layer(lid, fill_mode="hatch", hatch_outline=False)   # nur Füllung: keine Kontur
    (jl,) = job_layers(doc)
    assert jl.polylines == [path, line] and jl.kept_directions == (path[0], line[0])   # offene bleiben
    for s in list(doc.shapes):
        s.reverse = False
    doc.update_layer(lid, fill_mode="none")
    (jl,) = job_layers(doc)
    assert jl.kept_directions == ()


@pytest.mark.parametrize("order", [CutOrder(), CutOrder(corners=True), CutOrder(enabled=False),
                                   CutOrder(direction="top_bottom"), CutOrder(best_start=False)])
def test_closed_contour_runs_the_other_way_with_every_optimisation(doc, order):
    lid = doc.active_layer_id
    doc.set_cut_order(order)
    doc.add_shape(startpoint.with_start(rect(lid), (70.0, 70.0)))
    g0 = optimized_document_gcode(doc, scan_offsets=None)
    doc.shapes[0].reverse = True
    g = optimized_document_gcode(doc, scan_offsets=None)
    (s0, n0), (s1, n1) = first_cut(g0), first_cut(g)
    assert s0 == pytest.approx(to_machine(70.0, 70.0)) and s1 == pytest.approx(s0)   # gleicher Start
    assert n0 == pytest.approx(to_machine(50.0, 70.0)) and n1 == pytest.approx(to_machine(90.0, 70.0))
    assert burned(g) == pytest.approx(burned(g0)) == pytest.approx(120.0)
    assert xy(moves(g)[-1]) == pytest.approx(s0)
    assert no_arcs(g)
    pi_check(g)


def test_closed_contour_without_start_point_turns_around(doc):
    lid = doc.active_layer_id
    doc.add_shape(Shape("ellipse", Geometry(60, 60, 40, 20), lid))
    (jl0,) = optimize_layers(job_layers(doc))
    doc.shapes[0].reverse = True
    (jl,) = optimize_layers(job_layers(doc))
    a0, a = signed_area(jl0.polylines[0]), signed_area(jl.polylines[0])
    assert a0 * a < 0 and abs(a) == pytest.approx(abs(a0))
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)


@pytest.mark.parametrize("order", [CutOrder(), CutOrder(enabled=False), CutOrder(direction="left_right"),
                                   CutOrder(best_direction=False)])
def test_open_path_starts_at_the_other_end_even_when_farther(doc, order):
    lid = doc.active_layer_id
    doc.set_cut_order(order)
    # Planer beginnt bei Maschine (30, 30): das gezeichnete Anfangsende (340, 120) ist das nähere
    near, far = (340.0, 120.0), (300.0, 200.0)
    doc.add_shape(Shape.from_points("path", [near, (300.0, 120.0), far], lid))
    g0 = optimized_document_gcode(doc, scan_offsets=None)
    assert first_cut(g0)[0] == pytest.approx(to_machine(*near))
    doc.shapes[0].reverse = True
    g = optimized_document_gcode(doc, scan_offsets=None)
    assert first_cut(g)[0] == pytest.approx(to_machine(*far))       # umgekehrt: am fernen Ende
    assert burned(g) == pytest.approx(burned(g0)) == pytest.approx(120.0)
    doc.shapes[0].reverse = False
    doc.shapes[0].points = tuple(reversed(doc.shapes[0].points))     # andersherum gezeichnet
    g2 = optimized_document_gcode(doc, scan_offsets=None)
    keeps_drawn = not order.enabled or not order.best_direction
    assert first_cut(g2)[0] == pytest.approx(to_machine(*(far if keeps_drawn else near)))
    pi_check(g)


def test_order_polylines_without_kept_directions_unchanged():
    polys = [[(0.0, 0.0), (10.0, 0.0)], [(20.0, 0.0), (50.0, 0.0)], square(5, 5, 3)]
    ref = order_polylines(polys, (60.0, 0.0))
    assert order_polylines(polys, (60.0, 0.0), kept_directions=set()) == ref
    assert order_polylines(polys, (60.0, 0.0), kept_directions=None) == ref
    kept = order_polylines(polys, (60.0, 0.0), kept_directions={(20.0, 0.0)})
    assert [(50.0, 0.0), (20.0, 0.0)] in ref                          # ohne: nähere Ende zuerst
    assert [(20.0, 0.0), (50.0, 0.0)] in kept and [(50.0, 0.0), (20.0, 0.0)] not in kept
    closed_kept = order_polylines([square(0, 0, 10)], (10.0, 10.0), kept_directions={(0, 0)})
    assert closed_kept == order_polylines([square(0, 0, 10)], (10.0, 10.0))  # nur offene Pfade


def test_without_reverse_gcode_unchanged_and_toggle_twice_identical(doc, qapp):
    lid = doc.active_layer_id
    for i in range(3):
        doc.add_shape(rect(lid, x=20.0 + 50 * i, y=40.0 + 7 * i, rot=15.0 * i))
    doc.add_shape(Shape("ellipse", Geometry(60, 120, 30, 20), lid))
    doc.add_shape(Shape.from_points("path", [(200, 200), (240, 210), (260, 260)], lid))
    doc.add_shape(Shape("line", Geometry(100, 250, 40, 0), lid))
    doc.add_shape(Shape("text", Geometry(150, 100, 40, 15), lid, text="AB"))
    g = optimized_document_gcode(doc, scan_offsets=None)
    (jl,) = job_layers(doc)
    assert jl.kept_directions == ()
    for k in (0, 4, 5, 6):
        doc.shapes[k].reverse = True
        assert optimized_document_gcode(doc, scan_offsets=None) != g
        doc.shapes[k] = direction.toggled(doc.shapes[k])
        assert optimized_document_gcode(doc, scan_offsets=None) == g
    from lumacut_canvas.gcode import document_to_gcode
    plain = document_to_gcode(doc)
    doc.shapes[0].reverse = True
    assert document_to_gcode(doc) != plain                           # auch ohne Planer
    doc.shapes[0].reverse = False
    assert document_to_gcode(doc) == plain


def test_kerf_lead_in_overcut_lead_out_and_tabs_follow_the_new_direction(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=0.2, lead_in_mm=2.0, overcut_mm=1.0, lead_out_mm=1.5)
    doc.add_shape(rev(startpoint.with_start(rect(lid), (60.0, 70.0))))
    (jl,) = optimize_layers(job_layers(doc))
    kinds = list(jl.poly_kinds)
    lead = jl.polylines[kinds.index(KIND_LEAD_IN)]
    cut = jl.polylines[kinds.index("cut")]
    target = to_machine(60.0, 70.2)                                  # Kerf 0,2 mm nach außen
    assert lead[-1] == pytest.approx(target, abs=1e-6) and cut[0] == pytest.approx(target, abs=1e-6)
    # umgekehrt: unten nach rechts (Bildschirm) statt nach links
    nxt = next(q for q in cut[1:] if math.dist(q, cut[0]) > 1e-6)
    screen_dx = -(nxt[0] - cut[0][0])                                # Maschinen-X wächst nach links
    assert screen_dx > 0
    assert math.dist(cut[-1], target) > 0.9                          # Überschnitt 1 mm weiter
    out = jl.polylines[kinds.index(KIND_LEAD_OUT)]
    assert out[0] == pytest.approx(cut[-1], abs=1e-6)
    doc.update_layer(lid, kerf_mm=0.0, lead_in_mm=0.0, overcut_mm=0.0, lead_out_mm=0.0,
                     tab_count=2, tab_width_mm=1.0)
    g = optimized_document_gcode(doc, scan_offsets=None)
    assert burned(g) == pytest.approx(120.0 - 2 * 1.0, abs=0.05)
    assert no_arcs(g)
    pi_check(g)


def test_path_preview_and_estimate(doc):
    from lumacut_job.estimate import estimate_gcode
    lid = doc.active_layer_id
    doc.add_shape(rev(rect(lid)))
    doc.add_shape(rev(Shape.from_points("path", [(10, 150), (40, 150), (40, 170)], lid)))
    g = optimized_document_gcode(doc, scan_offsets=None)
    assert parse_gcode(g).cut_length_mm == pytest.approx(120.0 + 50.0)
    est = estimate_gcode(g)
    assert est.cut_length_mm == pytest.approx(170.0) and est.cut_time_s > 0


# --- Bedienung ---------------------------------------------------------------------------------

def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, shapes))
    return shapes


def click(ed, x, y, mods=Qt.NoModifier):
    ed.tools.press(QPointF(x, y), mods)
    ed.tools.release(QPointF(x, y), mods)


def test_path_menu_action_toggles_selection_in_one_undo_step(ed):
    lid = ed.document.active_layer_id
    a, b, c = _add(ed, [rect(lid), rev(rect(lid, y=100)), rect(lid, y=150)])
    texts = [x.text() for x in ed.path_ops_button.menu().actions() if x.text()]
    assert texts.index("Richtung umkehren") == texts.index("Startpunkte entfernen") + 1
    act = ed.actions_by_name["path_reverse"]
    assert act.shortcut().toString() == "Alt+Shift+U"
    ed.set_selection([a.id, b.id])
    n0 = ed.undo_stack.count()
    act.trigger()
    assert [s.reverse for s in ed.document.shapes] == [True, False, False]
    assert ed.undo_stack.count() == n0 + 1 and ed.undo_stack.undoText() == "Richtung umkehren"
    assert "1 Objekt mit umgekehrter Laufrichtung" in ed.msgs[-1] and "1 wieder wie gezeichnet" in ed.msgs[-1]
    assert len(ed.start_tool.item.rev_marks) == 1
    ed.undo_stack.undo()
    assert [s.reverse for s in ed.document.shapes] == [False, True, False]
    ed.set_selection([])
    act.trigger()
    assert "zuerst Vektorobjekte wählen" in ed.msgs[-1] and ed.undo_stack.count() == n0 + 1 - 0
    ed.document.update_layer(lid, fill_mode="hatch", hatch_outline=False)
    ed.set_selection([c.id])
    act.trigger()
    assert ed.document.shape(c.id).reverse and "füllt ohne Kontur" in ed.msgs[-1]


def test_locked_layer_and_hidden_layer(ed):
    lid = ed.document.active_layer_id
    (s,) = _add(ed, [rev(rect(lid))])
    assert len(ed.start_tool.item.rev_marks) == 1
    ed.set_selection([s.id])
    ed.document.update_layer(lid, locked=True)
    ed.actions_by_name["path_reverse"].trigger()
    assert ed.document.shape(s.id).reverse                          # gesperrt: unverändert
    ed.document.update_layer(lid, locked=False, visible=False)
    assert ed.start_tool.item.rev_marks == []


def test_shift_tap_in_start_tool(ed):
    lid = ed.document.active_layer_id
    s, p = _add(ed, [rect(lid), Shape.from_points("path", [(150, 50), (200, 50), (200, 90)], lid)])
    ed.set_tool(Tool.START)
    assert "Umschalt+Tippen kehrt die Richtung um" in ed.msgs[-1]
    n0 = ed.undo_stack.count()
    click(ed, 70.0, 50.2, Qt.ShiftModifier)                       # Umriss: Start + Umkehr
    cur = ed.document.shape(s.id)
    assert cur.start_point() == pytest.approx((70.0, 50.0)) and cur.reverse
    assert ed.undo_stack.count() == n0 + 1
    assert ed.undo_stack.undoText() == "Startpunkt setzen und Richtung umkehren"
    pt, d, _hot = ed.start_tool.item.marks[0]
    assert d == pytest.approx((-1.0, 0.0)) and ed.start_tool.item.rev_marks == []
    click(ed, 70.0, 50.0, Qt.ShiftModifier)                       # auf dem Startpunkt: nur Richtung
    cur = ed.document.shape(s.id)
    assert cur.start_point() == pytest.approx((70.0, 50.0)) and not cur.reverse
    assert "wieder wie gezeichnet" in ed.msgs[-1]
    click(ed, 175.0, 50.3, Qt.ShiftModifier)                      # offener Pfad
    assert ed.document.shape(p.id).reverse and "anderen Ende" in ed.msgs[-1]
    assert len(ed.start_tool.item.rev_marks) == 1
    pt, d = ed.start_tool.item.rev_marks[0]
    assert (pt.x(), pt.y()) == pytest.approx((200.0, 90.0)) and d == pytest.approx((0.0, -1.0))
    click(ed, 120.0, 120.0, Qt.ShiftModifier)                     # nichts getroffen
    assert "mit Umschalt" in ed.msgs[-1]
    click(ed, 70.0, 50.0)                                          # ohne Umschalt wie bisher
    assert ed.document.shape(s.id).start == () and not ed.document.shape(s.id).reverse
    ed.start_tool.item.update()


def test_touch_mode_menu_reach_and_markers(ed):
    lid = ed.document.active_layer_id
    ed.set_touch_mode(True, persist=False)
    try:
        (s,) = _add(ed, [rect(lid)])
        ed.set_selection([s.id])
        ed.actions_by_name["path_reverse"].trigger()
        assert ed.document.shape(s.id).reverse
        ed.start_tool.item.sync()
        ed.start_tool.item.update()
        assert len(ed.start_tool.item.rev_marks) == 1
    finally:
        ed.set_touch_mode(False, persist=False)


def test_editor_file_round_trip_and_gcode(ed, tmp_path):
    lid = ed.document.active_layer_id
    _add(ed, [rev(startpoint.with_start(rect(lid), (90.0, 60.0)))])
    path = ed.save_file(tmp_path / "reverse.lcs")
    ed.undo_stack.setClean()
    ed.load_file(path)
    (s,) = ed.document.shapes
    assert s.reverse and s.start_point() == pytest.approx((90.0, 60.0))
    g = optimized_document_gcode(ed.document, scan_offsets=None)
    start, nxt = first_cut(g)
    assert start == pytest.approx(to_machine(90.0, 60.0)) and nxt == pytest.approx(to_machine(90.0, 50.0))


def test_main_window_shortcut_unique(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    try:
        owners = [a for a in w.findChildren(QAction) if a.shortcut() == QKeySequence("Alt+Shift+U")]
        assert [a.text() for a in owners] == ["Richtung umkehren"]
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
