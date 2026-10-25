from lumacut_canvas.model import Document, Geometry, Layer, Shape


def make_doc():
    doc = Document()
    doc.add_layer(Layer(name="Gravieren", color="#f3a64b"))
    return doc


def test_new_layer_goes_on_top():
    doc = make_doc()
    assert [l.name for l in doc.layers] == ["Gravieren", "Schneiden"]


def test_remove_layer_removes_its_shapes_and_restores():
    doc = make_doc()
    top, bottom = doc.layers
    doc.add_shape(Shape("rect", Geometry(1, 1, 5, 5), top.id))
    keep = doc.add_shape(Shape("ellipse", Geometry(1, 1, 5, 5), bottom.id))
    saved = doc.remove_layer(top.id)
    assert [s.id for s in doc.shapes] == [keep.id]
    assert doc.active_layer_id == bottom.id
    doc.restore_layer(*saved)
    assert len(doc.shapes) == 2 and doc.layers[0].id == top.id


def test_move_layer_reorders():
    doc = make_doc()
    first = doc.layers[0].id
    doc.move_layer(first, 1)
    assert doc.layers[1].id == first
    doc.move_layer(first, 99)  # wird begrenzt
    assert doc.layers[1].id == first


def test_rename_visibility_lock():
    doc = make_doc()
    lid = doc.layers[0].id
    doc.update_layer(lid, name="Markieren", visible=False, locked=True)
    l = doc.layer(lid)
    assert (l.name, l.visible, l.locked) == ("Markieren", False, True)


def test_next_layer_color_is_unused():
    doc = make_doc()
    assert doc.next_layer_color() not in {l.color for l in doc.layers}


def test_set_active_layer_unknown_raises():
    import pytest
    with pytest.raises(KeyError):
        Document().set_active_layer("nope")
