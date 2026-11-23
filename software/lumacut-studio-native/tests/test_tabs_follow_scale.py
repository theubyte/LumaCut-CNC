"""Gleichmäßige Stege folgen dem Skalieren: lagen die Stege einer Kontur so, wie
„Stege gleichmäßig setzen …“ sie setzt, verteilt LumaCut sie nach dem Skalieren (Griffe am
Auswahlrahmen, Felder B / H – auch ungleichmäßig, gedreht, Gruppen) auf dem skalierten
Umriss gleich (gleiche Anzahl und Eckenregel, ab Startpunkt bzw. gezeichnetem Start); von
Hand gesetzte Stege werden wie bisher mitgestreckt. Verschieben, Drehen und Spiegeln lassen
die Stege, wo sie sind. Rechnung, Datei, G-Code durch den Pi-Wächter, Griff live mit Esc,
Maßfelder, Undo."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest
from _pi_guard import pi_check
from PySide6.QtCore import QPointF, Qt

from lumacut_canvas import corners, startpoint, tabs
from lumacut_canvas.commands import AddShapesCommand, SetGeometryCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.workarea import to_machine
from lumacut_job.cutpath import _cum_lengths, corner_positions, project_on_poly
from lumacut_job.planner import PlanReport, optimized_document_gcode

from test_tabs_follow_shape import gap_centres

CLEAR = 2.0 / 2 + 0.5          # Start-/Eckenabstand bei Stegbreite 2 mm
NO = Qt.NoModifier
SQUARE = [(20.0, 20.0), (60.0, 20.0), (60.0, 40.0), (20.0, 40.0), (20.0, 20.0)]


def rect(lid, x=50.0, y=50.0, w=40.0, h=20.0, rot=0.0):
    return Shape("rect", Geometry(x, y, w, h, rot), lid)


def same_points(a, b, tol=1e-6) -> bool:
    return len(a) == len(b) and all(any(math.dist(p, q) <= tol for q in b) for p in a)


def even(doc, s, values):
    return tabs.place_even_tabs(doc, [s], values).add[0]


def scaled(s, g):
    """Wie bisher: Stege normiert mitgestreckt."""
    return replace(s, geom=g)


def placed_on(doc, s, g, values):
    """„Stege gleichmäßig setzen …“ direkt auf der skalierten Form."""
    return even(doc, replace(s, geom=g, tabs=()), values)


def follow(doc, s, g):
    doc.add_shape(s)
    try:
        moved, res = tabs.follow_geometry(doc, {s.id: s.geom}, {s.id: g})
    finally:
        doc.remove_shape(s.id)
    return (replace(s, geom=g, tabs=moved[s.id][1]) if s.id in moved else None), res


def on_outline(s, tol=1e-6) -> bool:
    rings = tabs.closed_rings(s)
    return all(tabs.nearest_on_rings(rings, p)[0] <= tol for p in s.tab_points())


@pytest.fixture
def doc(qapp):
    d = Document()
    d.update_layer(d.active_layer_id, tab_width_mm=2.0)
    return d


# --- Rechnung ------------------------------------------------------------------------

@pytest.mark.parametrize("values", [{"count": 4}, {"count": 3}, {"count": 5, "avoid_corners": False},
                                    {"mode": "spacing", "spacing_mm": 20.0}])
def test_stretching_redistributes_like_placing_on_the_scaled_outline(doc, values):
    s = even(doc, rect(doc.active_layer_id), values)
    g = Geometry(50.0, 50.0, 90.0, 20.0)
    n = len(s.tabs)
    want = placed_on(doc, s, g, {**values, "mode": "count", "count": n})
    assert not same_points(scaled(s, g).tab_points(), want.tab_points(), 1e-3)   # bisher ungleich
    new, res = follow(doc, s, g)
    assert new is not None and same_points(new.tab_points(), want.tab_points())
    assert on_outline(new)
    assert res.contours == 1 and res.tabs == n and res.kept == 0 and res.too_short == 0
    assert res.readout() == f"{n} Stege an 1 Kontur auf dem skalierten Umriss gleichmäßig neu verteilt"


def test_spacing_layout_keeps_its_count(doc):
    s = even(doc, rect(doc.active_layer_id), {"mode": "spacing", "spacing_mm": 20.0})   # 120 mm → 6
    assert len(s.tabs) == 6
    new, _res = follow(doc, s, Geometry(50.0, 50.0, 120.0, 30.0))
    assert len(new.tabs) == 6


def test_tabs_keep_start_and_corner_clearance(doc):
    lid = doc.active_layer_id
    s = even(doc, startpoint.with_start(rect(lid), (60.0, 50.0)), {"count": 4})
    g = Geometry(50.0, 50.0, 40.0, 60.0)
    stretched = scaled(s, g)
    new, res = follow(doc, s, g)
    assert res.contours == 1
    assert new.start_point() == pytest.approx(stretched.start_point())
    (ring,) = tabs.closed_rings(new)
    ring = startpoint.rotate_ring_to(ring, new.start_point())
    cum = _cum_lengths(ring)
    cs = corner_positions(ring, cum)
    for p in new.tab_points():
        d = project_on_poly(ring, p, cum)[1]
        assert min(d, cum[-1] - d) >= CLEAR - 1e-6
        assert all(min(abs(d - c), cum[-1] - abs(d - c)) >= CLEAR - 1e-6 for c in cs)
    assert same_points(new.tab_points(), placed_on(doc, s, g, {"count": 4}).tab_points())


def test_uniform_scaling_restores_the_clearance_in_mm(doc):
    """Start- und Eckenabstand gelten in mm: 3 Stege auf 40 × 20 mm werden von zwei Ecken
    um 1,5 mm weggeschoben – doppelt so groß gestreckt stünden sie 3 mm daneben; neu
    verteilt halten sie wieder genau den Eckenabstand."""
    s = even(doc, rect(doc.active_layer_id), {"count": 3})
    g = Geometry(50.0, 50.0, 80.0, 40.0)
    want = placed_on(doc, s, g, {"count": 3})
    assert not same_points(scaled(s, g).tab_points(), want.tab_points(), 1e-3)
    new, res = follow(doc, s, g)
    assert new is not None and res.contours == 1
    assert same_points(new.tab_points(), want.tab_points())


def test_move_rotate_mirror_and_unchanged_spots_leave_the_tabs(doc):
    s = even(doc, rect(doc.active_layer_id), {"count": 4})
    g = s.geom
    doc.add_shape(s)
    for ng in (Geometry(80.0, 90.0, g.w, g.h), Geometry(g.x, g.y, g.w, g.h, 30.0),
               Geometry(g.x, g.y, -g.w, g.h), Geometry(g.x, g.y, g.w, -g.h),
               Geometry(g.x, g.y, g.w * 2, g.h * 2)):          # Plätze skalieren genau mit
        moved, res = tabs.follow_geometry(doc, {s.id: g}, {s.id: ng})
        assert moved == {} and res.readout() == ""


def test_hand_tabs_are_only_stretched_and_not_reported(doc):
    lid = doc.active_layer_id
    s = tabs.move_tab(even(doc, rect(lid), {"count": 4}), 0, (57.0, 49.0))
    hand = tabs.add_tab(rect(lid, x=150.0), (160.0, 50.0), 1.0)[0]
    for t in (s, hand):
        doc.add_shape(t)
        moved, res = tabs.follow_geometry(doc, {t.id: t.geom}, {t.id: replace(t.geom, w=90.0)})
        assert moved == {} and res.kept == 0 and res.readout() == ""


def test_too_small_keeps_the_stretched_tabs(doc):
    s = even(doc, rect(doc.active_layer_id), {"count": 6})
    doc.add_shape(s)
    moved, res = tabs.follow_geometry(doc, {s.id: s.geom}, {s.id: Geometry(50.0, 50.0, 4.0, 2.0)})
    assert moved == {} and res.too_short == 1
    assert res.readout() == "1 Kontur zu kurz für ihre Stege – nur übertragen"


def test_ellipse_rounded_rect_rotated_and_hole(doc):
    lid = doc.active_layer_id
    shapes = [even(doc, Shape("ellipse", Geometry(20.0, 150.0, 40.0, 20.0), lid), {"count": 4}),
              even(doc, corners.with_corner_radius(rect(lid, x=100.0, y=150.0), 5.0), {"count": 4}),
              even(doc, rect(lid, x=180.0, y=150.0, rot=30.0), {"count": 4}),
              even(doc, Shape.from_points("polygon", SQUARE + [(30.0, 25.0), (50.0, 25.0), (50.0, 35.0),
                                                            (30.0, 35.0), (30.0, 25.0)], lid, rings=[5]),
                   {"count": 4, "skip_inner": False})]
    assert len(shapes[3].tabs) == 8
    for s in shapes:
        g = replace(s.geom, w=s.geom.w * 1.7, h=s.geom.h * 0.8)
        new, res = follow(doc, s, g)
        want = placed_on(doc, s, g, {"count": 4, "skip_inner": False})
        assert new is not None and same_points(new.tab_points(), want.tab_points(), 1e-6), s.kind
        assert on_outline(new)


def test_saved_project_still_follows_and_has_no_new_key(doc):
    s = even(doc, rect(doc.active_layer_id), {"count": 4})
    loaded = Shape.from_dict(s.to_dict())                          # 6 Nachkommastellen
    g = Geometry(50.0, 50.0, 90.0, 20.0)
    new, res = follow(doc, loaded, g)
    assert res.contours == 1
    assert set(new.to_dict()) == set(s.to_dict())


def test_zero_tab_width_uses_the_fallback(doc):
    doc.update_layer(doc.active_layer_id, tab_width_mm=0.0)
    s = even(doc, rect(doc.active_layer_id), {"count": 4})
    g = Geometry(50.0, 50.0, 90.0, 20.0)
    new, res = follow(doc, s, g)
    assert res.contours == 1
    assert same_points(new.tab_points(), placed_on(doc, s, g, {"count": 4}).tab_points())


def test_old_tabs_override_and_several_shapes_summed(doc):
    lid = doc.active_layer_id
    a = even(doc, rect(lid), {"count": 4})
    b = even(doc, rect(lid, x=150.0), {"count": 3})
    plain = rect(lid, x=250.0)
    for s in (a, b, plain):
        doc.add_shape(s)
    old = {s.id: s.geom for s in (a, b, plain)}
    new = {s.id: replace(s.geom, w=90.0) for s in (a, b, plain)}
    a_tabs = a.tabs
    doc.shape(a.id).tabs = ()                                      # z. B. schon live geändert
    moved, res = tabs.follow_geometry(doc, old, new, {a.id: a_tabs})
    assert set(moved) == {a.id, b.id} and moved[a.id][0] == a_tabs
    assert res.contours == 2 and res.tabs == 7


def test_gcode_gaps_sit_on_the_redistributed_tabs(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, lead_in_mm=2.0)
    s = even(doc, startpoint.with_start(rect(lid), (60.0, 50.0)), {"count": 4})
    doc.add_shape(s)
    g = Geometry(50.0, 50.0, 90.0, 30.0)
    moved, _res = tabs.follow_geometry(doc, {s.id: s.geom}, {s.id: g})
    SetGeometryCommand(doc, {s.id: s.geom}, {s.id: g}, tabs=moved).redo()
    new = doc.shape(s.id)
    report = PlanReport()
    gc = optimized_document_gcode(doc, scan_offsets=None, report=report)
    assert same_points(gap_centres(gc), [to_machine(*p) for p in new.tab_points()], 1e-3)
    assert report.manual_tabs == 4 and report.dropped_tabs == 0 and report.manual_starts == 1
    pi_check(gc)


def test_command_undo_redo_and_merge(doc):
    s = even(doc, rect(doc.active_layer_id), {"count": 4})
    doc.add_shape(s)
    g1, g2 = Geometry(50.0, 50.0, 60.0, 20.0), Geometry(50.0, 50.0, 90.0, 20.0)
    m1, _ = tabs.follow_geometry(doc, {s.id: s.geom}, {s.id: g1})
    c1 = SetGeometryCommand(doc, {s.id: s.geom}, {s.id: g1}, mergeable=True, tabs=m1)
    c1.redo()
    m2, _ = tabs.follow_geometry(doc, {s.id: g1}, {s.id: g2})
    c2 = SetGeometryCommand(doc, {s.id: g1}, {s.id: g2}, mergeable=True, tabs=m2)
    assert c1.mergeWith(c2)
    c1.redo()
    assert doc.shape(s.id).tabs == m2[s.id][1]
    c1.undo()
    assert doc.shape(s.id).tabs == s.tabs and doc.shape(s.id).geom.as_tuple() == s.geom.as_tuple()


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


def test_handle_drag_redistributes_live_in_one_undo_step_and_escape_restores(ed):
    doc = ed.document
    (s,) = _add(ed, [even(doc, rect(doc.active_layer_id), {"count": 4})])
    s0 = s.copy()                                                  # Dokument hält dasselbe Objekt
    ed.set_selection([s.id])
    ov = ed.scene.overlay
    hp = ov.handle_points()[3]                                      # rechts Mitte
    assert ov.handle_at(hp) == 3
    n0 = ed.undo_stack.count()
    t = ed.tools
    t.press(hp, NO)
    t.move(QPointF(hp.x() + 20.0, hp.y()), NO, True)
    cur = doc.shape(s.id)
    assert cur.geom.w == pytest.approx(60.0)
    assert on_outline(cur) and same_points(cur.tab_points(), placed_on(doc, s0, cur.geom, {"count": 4})
                                           .tab_points())                # schon beim Ziehen
    t.move(QPointF(hp.x() + 50.0, hp.y()), NO, True)
    t.release(QPointF(hp.x() + 50.0, hp.y()), NO)
    cur = doc.shape(s.id)
    assert cur.geom.w == pytest.approx(90.0)
    want = placed_on(doc, s0, cur.geom, {"count": 4})
    assert same_points(cur.tab_points(), want.tab_points())
    assert ed.undo_stack.count() == n0 + 1 and ed.undo_stack.undoText() == "Skalieren"
    assert ed.msgs[-1] == "Skalieren · 4 Stege an 1 Kontur auf dem skalierten Umriss gleichmäßig neu verteilt"
    ed.undo_stack.undo()
    assert doc.shape(s.id).tabs == s0.tabs and doc.shape(s.id).geom.w == pytest.approx(40.0)
    ed.undo_stack.redo()
    assert same_points(doc.shape(s.id).tab_points(), want.tab_points())
    ed.undo_stack.undo()
    # Esc während des Ziehens: Größe und Stege wie vorher, kein Undo-Schritt.
    ed.set_selection([s.id])
    hp = ov.handle_points()[3]
    t.press(hp, NO)
    t.move(QPointF(hp.x() + 30.0, hp.y()), NO, True)
    assert doc.shape(s.id).tabs != s0.tabs
    t.cancel()
    assert doc.shape(s.id).tabs == s0.tabs and doc.shape(s.id).geom.w == pytest.approx(40.0)
    assert ed.undo_stack.index() == n0 and ed.undo_stack.count() == n0 + 1


def test_handle_drag_stretches_hand_tabs_as_before_and_move_leaves_tabs(ed):
    doc = ed.document
    lid = doc.active_layer_id
    (s,) = _add(ed, [tabs.move_tab(even(doc, rect(lid), {"count": 4}), 0, (57.0, 50.0))])
    s0 = s.copy()
    ed.set_selection([s.id])
    hp = ed.scene.overlay.handle_points()[3]
    n_msgs = len(ed.msgs)
    t = ed.tools
    t.press(hp, NO)
    t.move(QPointF(hp.x() + 50.0, hp.y()), NO, True)
    t.release(QPointF(hp.x() + 50.0, hp.y()), NO)
    assert doc.shape(s.id).tabs == s0.tabs                          # normiert mitgestreckt
    assert not any("neu verteilt" in m for m in ed.msgs[n_msgs:])
    ed.undo_stack.undo()
    # Verschieben: Stege bleiben normiert gleich.
    (e,) = _add(ed, [even(doc, rect(lid, x=150.0), {"count": 4})])
    e0 = e.copy()
    ed.set_selection([e.id])
    t.press(QPointF(160.0, 50.0), NO)
    t.move(QPointF(170.0, 60.0), NO, True)
    t.release(QPointF(170.0, 60.0), NO)
    assert ed.undo_stack.undoText() == "Verschieben" and doc.shape(e.id).tabs == e0.tabs


def test_size_fields_redistribute_in_one_undo_step(ed):
    doc = ed.document
    lid = doc.active_layer_id
    (s,) = _add(ed, [even(doc, rect(lid), {"count": 4})])
    s0 = s.copy()
    ed.set_selection([s.id])
    bar = ed.property_bar
    bar.ratio.setChecked(False)
    n0 = ed.undo_stack.count()
    bar.w.setValue(90.0)
    cur = doc.shape(s.id)
    assert cur.geom.w == pytest.approx(90.0) and cur.geom.h == pytest.approx(20.0)
    assert same_points(cur.tab_points(), placed_on(doc, s0, cur.geom, {"count": 4}).tab_points())
    assert ed.undo_stack.count() == n0 + 1 and ed.undo_stack.undoText() == "Maße ändern"
    assert ed.msgs[-1] == "Maße ändern · 4 Stege an 1 Kontur auf dem skalierten Umriss gleichmäßig neu verteilt"
    ed.undo_stack.undo()
    assert doc.shape(s.id).tabs == s0.tabs


def test_size_fields_on_a_rotated_object(ed):
    doc = ed.document
    (s,) = _add(ed, [even(doc, rect(doc.active_layer_id, x=100.0, y=100.0, rot=30.0), {"count": 4})])
    s0 = s.copy()
    ed.set_selection([s.id])
    bar = ed.property_bar
    bar.ratio.setChecked(False)
    bar.h.setValue(50.0)
    cur = doc.shape(s.id)
    assert cur.geom.rot == pytest.approx(30.0) and cur.geom.h == pytest.approx(50.0)
    assert same_points(cur.tab_points(), placed_on(doc, s0, cur.geom, {"count": 4}).tab_points())
    assert "skalierten Umriss" in ed.msgs[-1]


def test_dialog_tooltip_mentions_it(qapp):
    from lumacut_canvas.tabs_ui import EvenTabsDialog
    d = Document()
    s = rect(d.active_layer_id)
    d.add_shape(s)
    dlg = EvenTabsDialog(d, [s], values={"count": 4})
    try:
        tip = dlg.mode.toolTip()
        assert "nach Skalieren" in tip and "skalierten Umriss" in tip
        assert "neuen Umriss gleichmäßig neu verteilt" in tip
    finally:
        dlg.reject()
