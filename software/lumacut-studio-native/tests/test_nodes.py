"""Knotenbearbeitung: Geometrie (nodes) und Knotenwerkzeug im Editor (node_ui)."""

import json

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import QEvent

from lumacut_canvas import nodes, pathops
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.export import job_layers, shape_fill_segments
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.tools import Tool


def poly(doc, pts, kind="polygon", **kw):
    return doc.add_shape(Shape.from_points(kind, pts, doc.active_layer_id, **kw))


def close_pts(a, b, tol=1e-6):
    assert len(a) == len(b)
    for p, q in zip(a, b):
        assert p[0] == pytest.approx(q[0], abs=tol) and p[1] == pytest.approx(q[1], abs=tol)


@pytest.fixture
def doc(qapp):
    return Document()


SQUARE = [(10, 10), (30, 10), (30, 30), (10, 30)]


def test_move_node_renormalizes_box(doc):
    s = poly(doc, SQUARE)
    m = nodes.move_node(s, 2, (50, 40))
    assert m.id == s.id
    close_pts(nodes.scene_points(m), [(10, 10), (30, 10), (50, 40), (10, 30)])
    b = m.bounds()
    assert (b.x, b.y, b.w, b.h) == pytest.approx((10, 10, 40, 30))


def test_move_node_on_rotated_shape_keeps_other_nodes(doc):
    s = poly(doc, SQUARE)
    s.geom.rot = 30.0
    before = nodes.scene_points(s)
    m = nodes.move_node(s, 0, (0.0, 0.0))
    after = nodes.scene_points(m)
    assert m.geom.rot == 30.0
    close_pts(after[1:], before[1:])
    close_pts(after[:1], [(0.0, 0.0)])


def test_insert_and_delete_node_with_curves(doc):
    s = poly(doc, SQUARE, curves=[1])
    new, idx = nodes.insert_node(s, 1)            # Mitte des Kurvensegments 1→2
    assert idx == 2 and len(new.points) == 5
    assert set(new.curves) == {1, 2}               # beide Hälften bleiben Kurve
    new2, idx2 = nodes.insert_node(s, 3, (10, 20))  # Schlusssegment 3→0
    assert idx2 == 4 and nodes.scene_points(new2)[4] == pytest.approx((10, 20))
    d = nodes.delete_node(new, 2)
    assert len(d.points) == 4 and set(d.curves) == {1}
    tri = nodes.delete_node(s, 0)
    with pytest.raises(nodes.NodeError):
        nodes.delete_node(tri, 0)                  # Polygon braucht ≥ 3 Knoten


def test_delete_node_removes_small_ring_of_multi_ring(doc):
    s = poly(doc, SQUARE + [(15, 15), (25, 15), (20, 25)], rings=[4])
    d = nodes.delete_node(s, 5)
    assert len(d.points) == 4 and d.rings == ()


def test_toggle_curve_and_hatch_follow_curve(doc):
    s = poly(doc, SQUARE)
    c = nodes.toggle_curve(s, 0)
    assert c.curves == (0,)
    assert nodes.toggle_curve(c, 0).curves == ()
    # Kurve bauscht das Segment aus → Fläche ändert sich, Schraffur folgt.
    assert pathops.shape_area(c).area != pytest.approx(400, rel=1e-3)
    layer = doc.layer(c.layer_id)
    layer.fill_mode, layer.line_interval_mm = "hatch", 1.0
    straight = shape_fill_segments(s, layer)
    curved = shape_fill_segments(c, layer)
    assert curved and max(max(a[1], b[1]) for a, b in curved) <= 30.01
    assert min(min(a[1], b[1]) for a, b in curved) < min(min(a[1], b[1]) for a, b in straight)
    path = nodes.set_closed(s, False)[0]
    with pytest.raises(nodes.NodeError):
        nodes.toggle_curve(path, 3)                # Endknoten eines offenen Pfads


def test_open_and_close_path(doc):
    s = poly(doc, SQUARE)
    opened, at = nodes.set_closed(s, False, at=1)  # Segment 1→2 auftrennen
    assert opened.kind == "path"
    close_pts(nodes.scene_points(opened), [(30, 30), (10, 30), (10, 10), (30, 10)])
    assert at == 3
    closed, _ = nodes.set_closed(opened, True)
    assert closed.kind == "polygon"
    line = poly(doc, [(0, 0), (10, 0)], kind="path")
    with pytest.raises(nodes.NodeError):
        nodes.set_closed(line, True)


def test_hit_testing_nodes_and_segments(doc):
    s = poly(doc, SQUARE)
    assert nodes.node_at(s, (30.5, 10.2), 1.0) == 1
    assert nodes.node_at(s, (20, 20), 1.0) is None
    seg, q = nodes.segment_at(s, (20, 10.4), 1.0)
    assert seg == 0 and q == pytest.approx((20, 10))
    seg, _ = nodes.segment_at(s, (10.3, 20), 1.0)
    assert seg == 3                                # Schlusssegment


def test_convert_rect_ellipse_line(doc):
    r = doc.add_shape(Shape("rect", Geometry(0, 0, 20, 10, 15.0), doc.active_layer_id))
    pr = nodes.to_editable(r)
    assert pr.kind == "polygon" and pr.geom.rot == 15.0
    assert pathops.shape_area(pr).area == pytest.approx(200, rel=1e-6)
    e = doc.add_shape(Shape("ellipse", Geometry(0, 0, 40, 20), doc.active_layer_id))
    pe = nodes.to_editable(e)
    assert len(pe.points) == 16 and len(pe.curves) == 16  # §9.3: mind. 16 Knoten
    assert pathops.shape_area(pe).area == pytest.approx(pathops.shape_area(e).area, rel=1e-3)
    ln = doc.add_shape(Shape("line", Geometry(30, 20, -10, 5), doc.active_layer_id))
    pl = nodes.to_editable(ln)
    assert pl.kind == "path"
    close_pts(nodes.scene_points(pl), [(30, 20), (20, 25)])
    t = doc.add_shape(Shape("text", Geometry(0, 0, 20, 10), doc.active_layer_id, text="A"))
    with pytest.raises(nodes.NodeError):
        nodes.to_editable(t)


def test_curves_roundtrip_json(doc):
    s = nodes.toggle_curve(poly(doc, SQUARE), 2)
    doc.remove_shape(s.id)
    doc.add_shape(s)
    d2 = Document.from_dict(json.loads(json.dumps(doc.to_dict())))
    assert d2.shape(s.id).curves == (2,)


# --- Editor -------------------------------------------------------------------
@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, s):
    ed.undo_stack.push(AddShapesCommand(ed.document, [s]))
    return ed.document.shape(s.id)


def _key(ed, key, mods=Qt.NoModifier):
    return ed.tools.key_press(QKeyEvent(QEvent.KeyPress, key, mods))


def test_node_tool_in_strip_and_hides_handles(ed):
    assert "tool_node" in ed.actions_by_name
    assert ed.actions_by_name["tool_node"] in ed.tool_strip.actions()
    s = _add(ed, Shape.from_points("polygon", SQUARE, ed.document.active_layer_id))
    ed.set_selection([s.id])
    assert ed.scene.overlay.isVisible()
    ed.set_tool(Tool.NODE)
    assert ed.node_editor.shape_id == s.id
    assert not ed.scene.overlay.isVisible() and ed.node_editor.item.isVisible()
    assert ed.property_bar.node_controls.isVisible()
    ed.set_tool(Tool.SELECT)
    assert ed.node_editor.shape_id is None and not ed.property_bar.node_controls.isVisible()


def test_drag_node_is_one_undo_step(ed):
    s = _add(ed, Shape.from_points("polygon", SQUARE, ed.document.active_layer_id))
    ed.set_tool(Tool.NODE)
    t = ed.tools
    t.press(QPointF(20, 20), Qt.NoModifier)       # Objekt antippen
    t.release(QPointF(20, 20), Qt.NoModifier)
    assert ed.node_editor.shape_id == s.id
    n = ed.undo_stack.count()
    t.press(QPointF(30, 30), Qt.NoModifier)       # Knoten 2 greifen
    assert ed.node_editor.node == 2
    t.move(QPointF(40, 35), Qt.NoModifier, True)
    t.move(QPointF(45, 40), Qt.NoModifier, True)
    t.release(QPointF(45, 40), Qt.NoModifier)
    assert ed.undo_stack.count() == n + 1
    assert nodes.scene_points(ed.document.shape(s.id))[2] == pytest.approx((45, 40))
    ed.undo_stack.undo()
    close_pts(nodes.scene_points(ed.document.shape(s.id)), SQUARE)
    ed.undo_stack.redo()
    assert nodes.scene_points(ed.document.shape(s.id))[2] == pytest.approx((45, 40))


def test_double_click_adds_and_deletes_nodes_keys(ed):
    s = _add(ed, Shape.from_points("polygon", SQUARE, ed.document.active_layer_id))
    ed.set_selection([s.id])
    ed.set_tool(Tool.NODE)
    ne = ed.node_editor
    ed.tools.double_click(QPointF(20, 10))        # Segment 0 → neuer Knoten 1
    sh = ed.document.shape(s.id)
    assert len(sh.points) == 5 and ne.node == 1
    assert nodes.scene_points(sh)[1] == pytest.approx((20, 10))
    assert _key(ed, Qt.Key_Down, Qt.ShiftModifier) and _key(ed, Qt.Key_Down)
    assert nodes.scene_points(ed.document.shape(s.id))[1] == pytest.approx((20, 21))
    n = ed.undo_stack.index()
    ed.actions_by_name["delete"].trigger()        # Entf löscht den Knoten, nicht das Objekt
    assert ed.document.has_shape(s.id) and len(ed.document.shape(s.id).points) == 4
    ed.tools.double_click(QPointF(30, 30))        # Doppelklick auf Knoten löscht ihn
    assert len(ed.document.shape(s.id).points) == 3
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert ed.undo_stack.index() == n
    assert len(ed.document.shape(s.id).points) == 5


def test_actions_curve_close_convert(ed):
    s = _add(ed, Shape.from_points("path", [(10, 10), (30, 10), (30, 30)], ed.document.active_layer_id))
    ed.set_selection([s.id])
    ed.set_tool(Tool.NODE)
    ne, a = ed.node_editor, ed.actions_by_name
    assert not a["node_curve"].isEnabled()        # erst einen Knoten wählen
    ne.node = 0
    ne.refresh()
    a["node_curve"].trigger()
    assert ed.document.shape(s.id).curves == (0,)
    assert a["node_close"].text() == "Pfad schließen"
    a["node_close"].trigger()
    assert ed.document.shape(s.id).kind == "polygon" and a["node_close"].text() == "Pfad öffnen"
    ed.undo_stack.undo()
    assert ed.document.shape(s.id).kind == "path"
    r = _add(ed, Shape("rect", Geometry(50, 50, 20, 20), ed.document.active_layer_id))
    ed.tools.press(QPointF(60, 60), Qt.NoModifier)
    ed.tools.release(QPointF(60, 60), Qt.NoModifier)
    assert ne.shape_id == r.id and a["node_convert"].isEnabled()
    ed.tools.double_click(QPointF(60, 60))        # Doppelklick wandelt um
    assert ed.document.shape(r.id).kind == "polygon"
    # G-Code-Weg sieht das bearbeitete Objekt
    assert len(job_layers(ed.document)) >= 1


def test_context_menu_in_node_mode(ed):
    s = _add(ed, Shape.from_points("polygon", SQUARE, ed.document.active_layer_id))
    ed.set_tool(Tool.NODE)
    ed.node_editor.set_target(s.id)
    menu = ed.build_context_menu(QPointF(30, 10))
    texts = [x.text() for x in menu.actions()]
    assert ed.node_editor.node == 1
    assert "Knoten löschen" in texts and "Segment: Kurve ⇄ Gerade" in texts
