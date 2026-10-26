"""Boole-Operationen, Verschweißen, Versatz und Text in Pfade (Modell + Editor)."""

import json

import pytest
from PySide6.QtCore import QPointF

from lumacut_canvas import pathops
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.export import job_layers, shape_fill_segments
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.shape_paths import shape_path


def area(s):
    return pathops.shape_area(s).area


def rect(doc, x, y, w, h, kind="rect"):
    return doc.add_shape(Shape(kind, Geometry(x, y, w, h), doc.active_layer_id))


@pytest.fixture
def doc(qapp):
    return Document()


def test_union_subtract_intersect_xor_areas(doc):
    a, b = rect(doc, 0, 0, 20, 20), rect(doc, 10, 10, 20, 20)
    shapes = [a, b]
    assert area(pathops.boolean(shapes, "union")[0]) == pytest.approx(700, rel=1e-3)
    assert area(pathops.boolean(shapes, "subtract")[0]) == pytest.approx(300, rel=1e-3)
    assert area(pathops.boolean(shapes, "intersect")[0]) == pytest.approx(100, rel=1e-3)
    assert area(pathops.boolean(shapes, "xor")[0]) == pytest.approx(600, rel=1e-3)


def test_subtract_inside_makes_hole_filled_even_odd(doc):
    outer, inner = rect(doc, 0, 0, 40, 40), rect(doc, 10, 10, 20, 20)
    res = pathops.boolean([outer, inner], "subtract")[0]
    assert res.kind == "polygon" and len(res.rings) == 1   # Außenkontur + ein Loch
    assert area(res) == pytest.approx(1600 - 400, rel=1e-3)
    assert len(shape_path(res).toSubpathPolygons()) == 2
    doc.add_shape(res)
    layer = doc.layer(res.layer_id)
    layer.fill_mode = "hatch"
    layer.line_interval_mm = 1.0
    segs = shape_fill_segments(res, layer)
    # Keine Schraffur im Loch (Mitte 20/20).
    for (x0, y0), (x1, y1) in segs:
        if abs(y0 - 20) < 0.6:
            lo, hi = sorted((x0, x1))
            assert not (lo < 20 < hi)
    # Rundreise über die Datei behält die Ringe.
    back = Shape.from_dict(json.loads(json.dumps(res.to_dict())))
    assert back.rings == res.rings and area(back) == pytest.approx(area(res))


def test_weld_splits_disjoint_parts_union_keeps_one_object(doc):
    a, b, c = rect(doc, 0, 0, 20, 20), rect(doc, 10, 0, 20, 20), rect(doc, 100, 100, 10, 10)
    weld = pathops.boolean([a, b, c], "weld")
    assert len(weld) == 2
    assert sorted(round(area(s)) for s in weld) == [100, 600]
    union = pathops.boolean([a, b, c], "union")
    assert len(union) == 1 and area(union[0]) == pytest.approx(700, rel=1e-3)


def test_rotation_and_ellipse_are_respected(doc):
    r = rect(doc, 0, 0, 20, 20)
    r.geom.rot = 45.0
    e = rect(doc, 50, 50, 20, 20, "ellipse")
    u = pathops.boolean([r, e], "union")[0]
    assert area(u) == pytest.approx(400 + 3.14159 * 100, rel=0.01)
    b = u.bounds()
    assert b.x == pytest.approx(10 - 14.142, abs=0.05)   # gedrehte Ecke ragt heraus


def test_open_shapes_are_rejected_for_boolean_but_offset_outlines_them(doc):
    line = rect(doc, 0, 0, 30, 0, "line")
    r = rect(doc, 0, 10, 10, 10)
    with pytest.raises(pathops.PathOpError):
        pathops.boolean([line, r], "union")
    with pytest.raises(pathops.PathOpError):
        pathops.boolean([r], "union")
    out = pathops.offset([line], 1.0)
    assert out[0].kind == "polygon"
    assert area(out[0]) == pytest.approx(30 * 2 + 3.14159, rel=0.02)


def test_offset_outwards_and_inwards(doc):
    r = rect(doc, 10, 10, 20, 20)
    grow = pathops.offset([r], 2.0, "miter")[0]
    assert area(grow) == pytest.approx(24 * 24, rel=1e-3)
    shrink = pathops.offset([r], -2.0)[0]
    assert area(shrink) == pytest.approx(16 * 16, rel=1e-3)
    assert pathops.offset([r], -11.0) == []          # nach innen verschwunden
    with pytest.raises(pathops.PathOpError):
        pathops.offset([r], 0.0)


def test_text_to_outline_keeps_shape_and_holes(doc):
    t = doc.add_shape(Shape("text", Geometry(10, 10, 40, 15), doc.active_layer_id, text="Bob"))
    out = pathops.text_to_outline(t)
    assert out.kind == "polygon" and len(out.rings) >= 4   # B (2 Löcher), o (1), b (1)
    assert area(out) == pytest.approx(area(t), rel=0.01)
    ob, tb = out.bounds(), t.bounds()
    assert (ob.x, ob.y) == pytest.approx((tb.x, tb.y), abs=0.05)
    assert (ob.w, ob.h) == pytest.approx((tb.w, tb.h), abs=0.05)


@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, *shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, list(shapes)))
    return [s.id for s in shapes]


def test_editor_boolean_is_one_undo_step(ed):
    lid = ed.document.active_layer_id
    ids = _add(ed, Shape("rect", Geometry(10, 10, 20, 20), lid), Shape("rect", Geometry(20, 20, 20, 20), lid),
               Shape("rect", Geometry(200, 200, 10, 10), lid))
    ed.set_selection(ids[:2])
    ed.actions_by_name["bool_union"].trigger()
    assert len(ed.document.shapes) == 2
    new = ed.document.shape(ed.selection[0])
    assert new.kind == "polygon"
    assert ed.document.shapes.index(new) == 0            # an der Stelle des untersten Objekts
    ed.undo_stack.undo()
    assert [s.id for s in ed.document.shapes] == ids
    ed.undo_stack.redo()
    assert len(ed.document.shapes) == 2
    # Offene Linie: Meldung statt Änderung.
    line_id = _add(ed, Shape("line", Geometry(50, 50, 10, 10), lid))[0]
    ed.set_selection([line_id, ids[2]])
    ed.actions_by_name["bool_subtract"].trigger()
    assert ed.document.has_shape(line_id)


def test_editor_offset_and_text_to_path(ed):
    lid = ed.document.active_layer_id
    rid = _add(ed, Shape("rect", Geometry(50, 50, 20, 20), lid))[0]
    ed.set_selection([rid])
    ed.path_ops.ask_offset = lambda: {"distance_mm": 1.0, "join": "miter", "replace": False}
    ed.actions_by_name["path_offset"].trigger()
    assert len(ed.document.shapes) == 2 and ed.document.has_shape(rid)
    ed.path_ops.ask_offset = lambda: None
    ed.set_selection([rid])
    ed.actions_by_name["path_offset"].trigger()
    assert len(ed.document.shapes) == 2
    tid = _add(ed, Shape("text", Geometry(100, 100, 40, 15), lid, text="Hi"))[0]
    ed.set_selection([tid])
    ed.actions_by_name["text_to_path"].trigger()
    assert not ed.document.has_shape(tid)
    poly = ed.document.shape(ed.selection[0])
    assert poly.kind == "polygon"
    # Text-Pfad landet im G-Code wie der Text vorher.
    n_polys = sum(len(jl.polylines) for jl in job_layers(ed.document))
    assert n_polys == 2 + len(poly.rings) + 1       # Rechteck + Versatz + Text-Ringe
    ed.undo_stack.undo()
    assert ed.document.has_shape(tid)


def test_pathops_menu_in_bar_and_context_menu(ed):
    lid = ed.document.active_layer_id
    _add(ed, Shape("rect", Geometry(10, 10, 20, 10), lid))
    assert ed.path_ops_button.menu().objectName() == "PathOpsMenu"
    menu = ed.build_context_menu(QPointF(20, 15))
    names = [a.menu().objectName() for a in menu.actions() if a.menu() is not None]
    assert "PathOpsMenu" in names and "ArrangeMenu" in names


def test_new_fields_only_serialized_when_set(doc):
    p = Shape.from_points("polygon", [(0, 0), (10, 0), (10, 10)], doc.active_layer_id)
    t = Shape("text", Geometry(0, 0, 10, 5), doc.active_layer_id, text="A")
    assert not {"rings", "curves"} & set(p.to_dict())
    assert not {"bold", "italic"} & set(t.to_dict())
    bad = dict(p.to_dict(), rings=[1, 99], curves=[0, 7])
    back = Shape.from_dict(bad)
    assert back.rings == () and back.curves == (0,)   # ungültige Angaben verworfen
