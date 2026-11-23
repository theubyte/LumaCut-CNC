"""Gleichmäßige Stege folgen dem geänderten Umriss: lagen die Stege einer Kontur so, wie
„Stege gleichmäßig setzen …“ sie setzt, verteilt LumaCut sie nach Knoten bearbeiten,
Pfade vereinfachen, Ecken abrunden und Eckenradius auf dem neuen Umriss gleich (gleiche
Anzahl und Eckenregel, ab Startpunkt bzw. gezeichnetem Start); von Hand gesetzte Stege
werden nur übertragen. Rechnung, Datei, G-Code durch den Pi-Wächter, Knotenwerkzeug
(Ziehen live, Esc, Pfeiltaste, Knoten löschen), Vereinfachen, Abrunden, Eckenradius-Feld
mit Undo."""

from __future__ import annotations

import math

import pytest
from _pi_guard import pi_check
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent

from lumacut_canvas import corners, nodes, pathfillet, pathsimplify, startpoint, tabs
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.tools import Tool
from lumacut_canvas.workarea import to_machine
from lumacut_job.cutpath import _cum_lengths, project_on_poly
from lumacut_job.planner import PlanReport, optimized_document_gcode

CLEAR = 2.0 / 2 + 0.5          # Start-/Eckenabstand bei Stegbreite 2 mm
SQUARE = [(20.0, 20.0), (60.0, 20.0), (60.0, 40.0), (20.0, 40.0), (20.0, 20.0)]


def poly(lid, pts=SQUARE, rings=()):
    return Shape.from_points("polygon", pts, lid, rings=list(rings)) if rings else \
        Shape.from_points("polygon", pts, lid)


def rect(lid, x=50.0, y=50.0, w=40.0, h=20.0):
    return Shape("rect", Geometry(x, y, w, h, 0.0), lid)


def same_points(a, b, tol=1e-6) -> bool:
    return len(a) == len(b) and all(any(math.dist(p, q) <= tol for q in b) for p in a)


def even(doc, s, values):
    return tabs.place_even_tabs(doc, [s], values).add[0]


def on_outline(s, tol=1e-6) -> bool:
    rings = tabs.closed_rings(s)
    return all(tabs.nearest_on_rings(rings, p)[0] <= tol for p in s.tab_points())


def fresh(s):
    """Gleiche Geometrie, ohne Stege (zum Vergleich mit „Stege gleichmäßig setzen …“)."""
    return tabs.clear_tabs(s)


def gap_centres(g: str) -> list[tuple[float, float]]:
    lines = [ln for ln in g.splitlines() if ln.startswith(("G0 X", "G1 X"))]

    def xy(ln):
        parts = dict((t[0], t[1:]) for t in ln.split()[1:] if t[0] in "XY")
        return float(parts["X"]), float(parts["Y"])

    first = next(i for i, ln in enumerate(lines) if ln.startswith("G1"))
    out = []
    for prev, ln in zip(lines[first:], lines[first + 1:]):
        if ln.startswith("G0"):
            a, b = xy(prev), xy(ln)
            out.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    return out


@pytest.fixture
def doc(qapp):
    d = Document()
    d.update_layer(d.active_layer_id, tab_width_mm=2.0)
    return d


# --- Rechnung ------------------------------------------------------------------------

@pytest.mark.parametrize("values", [{"count": 4}, {"count": 5, "avoid_corners": False},
                                    {"count": 3}, {"mode": "spacing", "spacing_mm": 20.0}])
def test_node_move_redistributes_like_placing_on_the_new_outline(doc, values):
    lid = doc.active_layer_id
    placed = even(doc, poly(lid), values)
    edited = nodes.move_node(placed, 2, (80.0, 50.0))
    assert on_outline(edited)                                       # nur übertragen: ungleich
    want = even(doc, fresh(edited), {**values, "mode": "count", "count": len(placed.tabs)})
    assert not same_points(edited.tab_points(), want.tab_points(), 1e-3)
    res = tabs.follow_shape(doc, placed, edited)
    assert res.contours == 1 and res.tabs == len(placed.tabs) and res.kept == 0 and res.too_short == 0
    assert same_points(res.shape.tab_points(), want.tab_points())
    assert [tuple(p) for p in res.shape.points] == [tuple(p) for p in edited.points]
    assert res.readout() == (f"{len(placed.tabs)} Stege an 1 Kontur auf dem neuen Umriss "
                             "gleichmäßig neu verteilt")


def test_spacing_layout_keeps_its_count(doc):
    lid = doc.active_layer_id
    placed = even(doc, poly(lid), {"mode": "spacing", "spacing_mm": 20.0})       # 120 mm → 6
    assert len(placed.tabs) == 6
    bigger = nodes.move_node(placed, 2, (100.0, 60.0))
    res = tabs.follow_shape(doc, placed, bigger)
    assert len(res.shape.tabs) == 6 and res.contours == 1


def test_tabs_keep_corner_and_start_clearance_after_the_edit(doc):
    lid = doc.active_layer_id
    placed = even(doc, startpoint.with_start(poly(lid), (40.0, 20.0)), {"count": 4})
    edited = nodes.insert_node(placed, 2, (70.0, 30.0))[0]          # neue Ecke rechts
    res = tabs.follow_shape(doc, placed, edited)
    assert res.contours == 1
    new = res.shape
    assert new.start_point() == pytest.approx((40.0, 20.0))
    (ring,) = tabs.closed_rings(new)
    ring = startpoint.rotate_ring_to(ring, new.start_point())
    cum = _cum_lengths(ring)
    from lumacut_job.cutpath import corner_positions
    cs = corner_positions(ring, cum)
    for p in new.tab_points():
        s = project_on_poly(ring, p, cum)[1]
        assert min(s, cum[-1] - s) >= CLEAR - 1e-6                    # Startabstand
        assert all(min(abs(s - c), cum[-1] - abs(s - c)) >= CLEAR - 1e-6 for c in cs)
    want = even(doc, fresh(edited), {"count": 4})
    assert same_points(new.tab_points(), want.tab_points())


def test_hand_moved_tab_is_only_carried(doc):
    lid = doc.active_layer_id
    placed = even(doc, poly(lid), {"count": 4})
    hand = tabs.move_tab(placed, 0, (27.0, 19.0))
    edited = nodes.move_node(hand, 2, (80.0, 50.0))
    res = tabs.follow_shape(doc, hand, edited)
    assert res.contours == 0 and res.kept == 1 and res.shape is edited
    assert res.readout() == "von Hand gesetzte Stege an 1 Kontur nur übertragen"
    single = tabs.add_tab(poly(lid), (40.0, 20.0), 1.0)[0]
    res = tabs.follow_shape(doc, single, nodes.move_node(single, 2, (80.0, 50.0)))
    assert res.contours == 0 and res.kept == 1


def test_untouched_ring_stays_byte_identical_and_hole_follows_on_its_own(doc):
    lid = doc.active_layer_id
    outer = [(0.0, 0.0), (60.0, 0.0), (60.0, 40.0), (0.0, 40.0), (0.0, 0.0)]
    hole = [(20.0, 10.0), (40.0, 10.0), (40.0, 30.0), (20.0, 30.0), (20.0, 10.0)]
    s = poly(lid, outer + hole, rings=[5])
    placed = even(doc, s, {"count": 4, "skip_inner": False})
    assert len(placed.tabs) == 8
    hole_tabs = [p for p in placed.tab_points() if 15 < p[0] < 45 and 5 < p[1] < 35]
    edited = nodes.move_node(placed, 2, (90.0, 60.0))                 # nur der Außenring
    res = tabs.follow_shape(doc, placed, edited)
    assert res.contours == 1 and res.tabs == 4
    got_hole = [p for p in res.shape.tab_points() if 15 < p[0] < 45 and 5 < p[1] < 35]
    assert same_points(got_hole, hole_tabs, 1e-6)
    want = even(doc, fresh(edited), {"count": 4, "skip_inner": False})
    assert same_points(res.shape.tab_points(), want.tab_points())


def test_ring_removed_by_node_delete_maps_the_rest(doc):
    lid = doc.active_layer_id
    a = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0), (0.0, 0.0)]
    b = [(50.0, 0.0), (90.0, 0.0), (90.0, 20.0), (50.0, 20.0), (50.0, 0.0)]
    s = poly(lid, a + b, rings=[5])
    placed = even(doc, s, {"count": 4, "skip_inner": False})
    # Ring a: Knoten löschen, bis nur noch Ring b bleibt (Ring b ändert sich zusätzlich)
    cur = placed
    while len(tabs.closed_rings(cur)) > 1:
        cur = nodes.delete_node(cur, 0)
    cur = nodes.move_node(cur, 2, (100.0, 30.0))
    res = tabs.follow_shape(doc, placed, cur)
    want = even(doc, fresh(cur), {"count": 4})
    assert len(tabs.closed_rings(res.shape)) == 1
    assert same_points(res.shape.tab_points(), want.tab_points())


def test_hand_tab_and_start_slide_along_a_moved_edge(doc):
    lid = doc.active_layer_id
    s = tabs.add_tab(poly(lid), (60.0, 33.0), 1.0)[0]               # rechte Kante, 65 %
    s = startpoint.with_start(s, (60.0, 25.0))
    moved = nodes.move_node(s, 2, (80.0, 50.0))
    assert same_points(moved.tab_points(), [(73.0, 39.5)])            # früher entfallen (> 1,5 mm)
    assert moved.start_point() == pytest.approx((65.0, 27.5))       # 25 % der Kante
    assert tabs.slide_points(s, moved, [(5.0, 5.0)]) == [(5.0, 5.0)]  # neben dem Umriss: bleibt
    # andere Eckenzahl (Knoten eingefügt): nächster Umrisspunkt wie bisher
    ins = nodes.insert_node(s, 1, (60.0, 30.0))[0]
    assert tabs.slide_points(s, ins, s.tab_points()) == s.tab_points()
    assert same_points(ins.tab_points(), [(60.0, 33.0)])


def test_too_short_outline_keeps_the_carried_tabs(doc):
    lid = doc.active_layer_id
    placed = even(doc, poly(lid), {"count": 8})
    small = nodes.move_node(nodes.move_node(placed, 2, (24.0, 22.0)), 1, (24.0, 20.0))
    small = nodes.move_node(small, 3, (20.0, 22.0))                 # 4 × 2 mm-Kästchen: 12 mm
    res = tabs.follow_shape(doc, placed, small)
    assert res.contours == 0 and res.too_short == 1 and res.shape is small
    assert "1 Kontur zu kurz für ihre Stege – nur übertragen" in res.readout()


def test_nothing_to_follow(doc):
    lid = doc.active_layer_id
    plain = poly(lid)
    edited = nodes.move_node(plain, 2, (80.0, 50.0))
    assert tabs.follow_shape(doc, plain, edited).shape is edited      # keine Stege
    placed = even(doc, poly(lid), {"count": 4})
    same = nodes.move_node(placed, 2, (60.0, 40.0))                   # Knoten bleibt, wo er war
    res = tabs.follow_shape(doc, placed, same)
    assert res.shape is same and res.contours == 0 and res.readout() == ""


def test_zero_tab_width_uses_the_fallback(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, tab_width_mm=0.0)
    placed = even(doc, poly(lid), {"count": 4})
    edited = nodes.move_node(placed, 2, (80.0, 50.0))
    res = tabs.follow_shape(doc, placed, edited)
    assert res.contours == 1
    assert same_points(res.shape.tab_points(), even(doc, fresh(edited), {"count": 4}).tab_points())


def test_saved_project_still_follows(doc):
    lid = doc.active_layer_id
    placed = even(doc, poly(lid, [(10.123457, 10.0), (61.7, 13.3), (55.0, 47.9), (12.0, 41.0),
                                  (10.123457, 10.0)]), {"count": 5})
    loaded = Shape.from_dict(placed.to_dict())                       # 6 Nachkommastellen
    edited = nodes.move_node(loaded, 1, (75.0, 5.0))
    res = tabs.follow_shape(doc, loaded, edited)
    assert res.contours == 1
    assert same_points(res.shape.tab_points(), even(doc, fresh(edited), {"count": 5}).tab_points())
    back = Shape.from_dict(res.shape.to_dict())
    assert set(back.to_dict()) == set(edited.to_dict())              # kein neuer Schlüssel


def test_simplify_and_fillet_and_corner_radius(doc):
    lid = doc.active_layer_id
    dense = poly(lid, [(20.0 + i, 20.0 + 0.001 * (i % 2)) for i in range(0, 40)]
                 + [(60.0, 20.0), (60.0, 40.0), (20.0, 40.0), (20.0, 20.0)])
    placed = even(doc, dense, {"count": 4})
    simple = pathsimplify.simplify_shape(placed, 0.05)
    res = tabs.follow_shape(doc, placed, simple)
    assert same_points(res.shape.tab_points(), even(doc, fresh(simple), {"count": 4}).tab_points())
    # Abrunden: ein Steg nahe einer Ecke landete auf dem Bogen, jetzt wieder gleichmäßig
    sq = even(doc, poly(lid), {"count": 6, "avoid_corners": False})
    round_ = pathfillet.fillet_shape(sq, 6.0).shape
    res = tabs.follow_shape(doc, sq, round_)
    assert res.contours == 1
    assert same_points(res.shape.tab_points(),
                       even(doc, fresh(round_), {"count": 6, "avoid_corners": False}).tab_points())
    # Eckenradius am Rechteck
    r = even(doc, rect(lid), {"count": 6})
    rr = corners.with_corner_radius(r, 8.0)
    res = tabs.follow_shape(doc, r, rr)
    assert res.shape.corner_radius == 8.0
    assert same_points(res.shape.tab_points(), even(doc, fresh(rr), {"count": 6}).tab_points())


def test_follow_shapes_sums_up(doc):
    lid = doc.active_layer_id
    a = even(doc, poly(lid), {"count": 4})
    b = tabs.move_tab(even(doc, rect(lid), {"count": 3}), 0, (55.0, 50.0))
    out, total = tabs.follow_shapes(doc, [(a, nodes.move_node(a, 2, (80.0, 50.0))),
                                          (b, corners.with_corner_radius(b, 5.0))])
    assert len(out) == 2 and total.contours == 1 and total.tabs == 4 and total.kept == 1
    assert total.readout() == ("4 Stege an 1 Kontur auf dem neuen Umriss gleichmäßig neu verteilt · "
                               "von Hand gesetzte Stege an 1 Kontur nur übertragen")


# --- G-Code --------------------------------------------------------------------------

def test_gcode_gaps_sit_on_the_redistributed_tabs(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, lead_in_mm=2.0)
    placed = even(doc, startpoint.with_start(poly(lid), (40.0, 20.0)), {"count": 4})
    edited = nodes.move_node(placed, 2, (80.0, 50.0))
    new = tabs.follow_shape(doc, placed, edited).shape
    doc.add_shape(new)
    report = PlanReport()
    g = optimized_document_gcode(doc, scan_offsets=None, report=report)
    assert same_points(gap_centres(g), [to_machine(*p) for p in new.tab_points()], 1e-3)
    assert report.manual_tabs == 4 and report.dropped_tabs == 0 and report.manual_starts == 1
    pi_check(g)


# --- Bedienung -----------------------------------------------------------------------

@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    e.msgs = []
    e.statusMessage.connect(e.msgs.append)
    e.document.update_layer(e.document.active_layer_id, tab_width_mm=2.0)
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, shapes))
    return shapes


def _target(ed, s):
    ed.set_tool(Tool.NODE)
    ed.tools.press(QPointF(20.0, 30.0), Qt.NoModifier)
    ed.tools.release(QPointF(20.0, 30.0), Qt.NoModifier)
    assert ed.node_editor.shape_id == s.id


def test_node_drag_redistributes_live_in_one_undo_step_and_escape_restores(ed):
    doc = ed.document
    lid = doc.active_layer_id
    (s,) = _add(ed, [even(doc, startpoint.with_start(poly(lid), (40.0, 20.0)), {"count": 4})])
    _target(ed, s)
    n0 = ed.undo_stack.count()
    t = ed.tools
    t.press(QPointF(60.0, 40.0), Qt.NoModifier)
    assert ed.node_editor.node == 2
    t.move(QPointF(70.0, 45.0), Qt.NoModifier, True)
    cur = doc.shape(s.id)
    assert on_outline(cur) and len(cur.tabs) == 4                    # schon beim Ziehen
    assert same_points(cur.tab_points(), even(doc, fresh(cur), {"count": 4}).tab_points())
    assert cur.start_point() == pytest.approx((40.0, 20.0))
    t.move(QPointF(80.0, 50.0), Qt.NoModifier, True)
    t.release(QPointF(80.0, 50.0), Qt.NoModifier)
    cur = doc.shape(s.id)
    assert nodes.scene_points(cur)[2] == pytest.approx((80.0, 50.0))
    assert same_points(cur.tab_points(), even(doc, fresh(cur), {"count": 4}).tab_points())
    assert ed.undo_stack.count() == n0 + 1 and ed.undo_stack.undoText() == "Knoten verschieben"
    assert ed.msgs[-1] == "Knoten verschieben · 4 Stege an 1 Kontur auf dem neuen Umriss gleichmäßig neu verteilt"
    ed.undo_stack.undo()
    assert doc.shape(s.id).tabs == s.tabs and doc.shape(s.id).start == s.start
    ed.undo_stack.redo()
    assert same_points(doc.shape(s.id).tab_points(), cur.tab_points())
    ed.undo_stack.undo()
    t.press(QPointF(60.0, 40.0), Qt.NoModifier)
    t.move(QPointF(80.0, 50.0), Qt.NoModifier, True)
    assert doc.shape(s.id).tabs != s.tabs
    ed.tools.cancel()
    back = doc.shape(s.id)
    assert back.tabs == s.tabs and back.start == s.start and back.points == s.points


def test_node_drag_keeps_hand_tabs_and_start_point_on_the_outline(ed):
    """Vorher wurden Stege und Startpunkt beim Ziehen mit der Objektbox gestreckt."""
    doc = ed.document
    lid = doc.active_layer_id
    hand = tabs.add_tab(poly(lid), (27.0, 20.0), 1.0)[0]
    hand = tabs.add_tab(hand, (60.0, 33.0), 1.0)[0]
    (s,) = _add(ed, [startpoint.with_start(hand, (20.0, 25.0))])
    _target(ed, s)
    n_msgs = len(ed.msgs)
    t = ed.tools
    t.press(QPointF(60.0, 40.0), Qt.NoModifier)
    t.move(QPointF(80.0, 50.0), Qt.NoModifier, True)
    t.release(QPointF(80.0, 50.0), Qt.NoModifier)
    cur = doc.shape(s.id)
    assert on_outline(cur) and len(cur.tabs) == 2
    # die Kante (60, 20)–(60, 40) wird zu (60, 20)–(80, 50): der Steg bleibt bei 65 %
    assert same_points(cur.tab_points(), [(27.0, 20.0), (73.0, 39.5)], 1e-6)
    assert cur.start_point() == pytest.approx((20.0, 25.0), abs=1e-6)
    assert not any("neu verteilt" in m for m in ed.msgs[n_msgs:])


def test_arrow_key_and_node_delete_follow(ed):
    doc = ed.document
    lid = doc.active_layer_id
    pts = [(20.0, 20.0), (40.0, 20.0), (60.0, 20.0), (60.0, 40.0), (20.0, 40.0), (20.0, 20.0)]
    (s,) = _add(ed, [even(doc, poly(lid, pts), {"count": 4})])
    _target(ed, s)
    ed.node_editor.node = 3
    n0 = ed.undo_stack.count()
    ed.tools.key_press(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.ShiftModifier))
    cur = doc.shape(s.id)
    assert nodes.scene_points(cur)[3] == pytest.approx((70.0, 40.0))
    assert same_points(cur.tab_points(), even(doc, fresh(cur), {"count": 4}).tab_points())
    assert "gleichmäßig neu verteilt" in ed.msgs[-1]
    assert ed.node_editor.delete_node(1)                              # Knoten löschen
    cur = doc.shape(s.id)
    assert same_points(cur.tab_points(), even(doc, fresh(cur), {"count": 4}).tab_points())
    assert ed.undo_stack.count() == n0 + 2
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert doc.shape(s.id).tabs == s.tabs


def test_convert_to_path_leaves_tabs(ed):
    doc = ed.document
    lid = doc.active_layer_id
    (s,) = _add(ed, [even(doc, rect(lid, 20.0, 20.0, 40.0, 20.0), {"count": 4})])
    ed.set_selection([s.id])
    ed.set_tool(Tool.NODE)
    ed.node_editor.set_target(s.id)
    assert ed.node_editor.convert()
    cur = doc.shape(s.id)
    assert cur.kind != "rect" and same_points(cur.tab_points(), s.tab_points(), 1e-6)


def test_simplify_action_redistributes_with_readout(ed):
    doc = ed.document
    lid = doc.active_layer_id
    dense = poly(lid, [(20.0 + i, 20.0 + 0.001 * (i % 2)) for i in range(0, 40)]
                 + [(60.0, 20.0), (60.0, 40.0), (20.0, 40.0), (20.0, 20.0)])
    (s,) = _add(ed, [even(doc, dense, {"count": 3})])
    ed.path_ops.cleanup.ask_simplify = lambda shapes: {"tolerance_mm": 0.05, "fit_lines": False}
    ed.set_selection([s.id])
    n0 = ed.undo_stack.count()
    ed.actions_by_name["path_simplify"].trigger()
    (cur,) = doc.shapes
    assert len(cur.points) < len(s.points)
    assert same_points(cur.tab_points(), even(doc, fresh(cur), {"count": 3}).tab_points())
    assert ed.msgs[-1].startswith("Pfade vereinfachen: ")
    assert ed.undo_stack.count() == n0 + 1
    ed.undo_stack.undo()
    assert doc.shapes[0].tabs == s.tabs


def test_fillet_action_redistributes_with_readout(ed):
    doc = ed.document
    lid = doc.active_layer_id
    (s,) = _add(ed, [even(doc, poly(lid), {"count": 6, "avoid_corners": False})])
    ed.path_ops.fillet.ask = lambda shapes: {"radius_mm": 6.0, "mode": "round", "corners": "all",
                                             "min_angle_deg": 10}
    ed.set_selection([s.id])
    n0 = ed.undo_stack.count()
    ed.actions_by_name["path_fillet"].trigger()
    (cur,) = doc.shapes
    assert same_points(cur.tab_points(),
                       even(doc, fresh(cur), {"count": 6, "avoid_corners": False}).tab_points())
    assert ed.msgs[-1].startswith("Ecken abrunden: ")
    assert "6 Stege an 1 Kontur auf dem neuen Umriss gleichmäßig neu verteilt" in ed.msgs[-1]
    assert ed.undo_stack.count() == n0 + 1
    ed.undo_stack.undo()
    assert doc.shapes[0].tabs == s.tabs


def test_corner_radius_field_redistributes_in_one_undo_step(ed, qapp):
    doc = ed.document
    lid = doc.active_layer_id
    (a,) = _add(ed, [even(doc, rect(lid), {"count": 6})])
    (b,) = _add(ed, [tabs.add_tab(rect(lid, y=100.0), (60.0, 100.0), 1.0)[0]])
    ed.set_selection([a.id, b.id])
    qapp.processEvents()
    n0 = ed.undo_stack.count()
    ed.property_bar.corner_controls.radius.setValue(5.0)
    assert ed.undo_stack.count() == n0 + 1
    cur = doc.shape(a.id)
    assert cur.corner_radius == 5.0
    assert same_points(cur.tab_points(), even(doc, fresh(cur), {"count": 6}).tab_points())
    assert on_outline(doc.shape(b.id)) and len(doc.shape(b.id).tabs) == 1
    assert "6 Stege an 1 Kontur auf dem neuen Umriss gleichmäßig neu verteilt" in ed.msgs[-1]
    assert "von Hand" not in ed.msgs[-1]
    ed.undo_stack.undo()
    assert doc.shape(a.id).tabs == a.tabs and doc.shape(a.id).corner_radius == 0


def test_dialog_tooltip_mentions_it(qapp):
    from lumacut_canvas.tabs_ui import EvenTabsDialog
    d = Document()
    s = rect(d.active_layer_id)
    d.add_shape(s)
    dlg = EvenTabsDialog(d, [s], values={"count": 4})
    try:
        tip = dlg.mode.toolTip()
        assert "Knoten bearbeiten" in tip and "neuen Umriss gleichmäßig neu verteilt" in tip
    finally:
        dlg.reject()
