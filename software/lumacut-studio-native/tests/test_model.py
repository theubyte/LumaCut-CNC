from lumacut_canvas.model import Document, Geometry, Layer, Shape, constrain_geometry
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, from_machine, to_machine


def rect(doc, x=10, y=10, w=20, h=10, layer=None):
    return doc.add_shape(Shape("rect", Geometry(x, y, w, h), layer or doc.active_layer_id))


def test_default_document_has_one_active_layer():
    doc = Document()
    assert len(doc.layers) == 1
    assert doc.active_layer is doc.layers[0]


def test_shapes_inherit_layer_parameters():
    doc = Document()
    s = rect(doc)
    layer = doc.layer(s.layer_id)
    doc.update_layer(layer.id, power=33, speed=900, passes=3, color="#ff0000")
    assert doc.layer(s.layer_id).power == 33
    assert doc.layer(s.layer_id).color == "#ff0000"


def test_layer_parameters_are_clamped():
    doc = Document()
    lid = doc.layers[0].id
    doc.update_layer(lid, power=250, speed=0, passes=99)
    l = doc.layer(lid)
    assert (l.power, l.speed, l.passes) == (100.0, 1.0, 30)


def test_shape_outside_work_area_is_silently_moved_inside():
    doc = Document()
    s = rect(doc, x=350, y=-5, w=20, h=10)
    b = s.bounds()
    assert b.x == WORK_WIDTH_MM - 20 and b.y == 0


def test_too_large_shape_is_scaled_proportionally():
    g = constrain_geometry(Geometry(0, 0, 720, 340))
    assert g.w == WORK_WIDTH_MM and g.h == 170


def test_line_with_negative_vector_is_constrained_by_bounds():
    g = constrain_geometry(Geometry(10, 10, -30, 5))
    b = g.bounds()
    assert b.x == 0 and b.w == 30 and g.w == -30


def test_geometry_mapping_scales_both_points():
    from lumacut_canvas.workarea import Rect
    g = Geometry(10, 10, 10, 10).mapped(Rect(10, 10, 10, 10), Rect(0, 0, 40, 20))
    assert g.as_tuple() == (0, 0, 40, 20)


def test_hidden_or_locked_layer_makes_shape_not_editable():
    doc = Document()
    s = rect(doc)
    assert doc.is_editable(s.id)
    doc.update_layer(s.layer_id, locked=True)
    assert not doc.is_editable(s.id)
    doc.update_layer(s.layer_id, locked=False, visible=False)
    assert not doc.is_editable(s.id)


def test_listener_called_once_per_batch():
    doc = Document()
    calls = []
    doc.add_listener(lambda: calls.append(1))
    doc.begin_batch()
    rect(doc)
    rect(doc)
    doc.end_batch()
    assert calls == [1]


def test_machine_mapping_applies_hidden_safezone_offset():
    # Nullpunkt oben rechts (Anforderungen 2026-10-26 §2.1): X = 390 − x, Y = 30 + y
    assert to_machine(0, 0) == (390, 30)
    assert to_machine(WORK_WIDTH_MM, WORK_HEIGHT_MM) == (30, 370)
    assert from_machine(*to_machine(12.5, 7)) == (12.5, 7)
