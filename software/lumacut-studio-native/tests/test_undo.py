from PySide6.QtGui import QUndoStack

from lumacut_canvas.commands import (AddLayerCommand, AddShapesCommand, DeleteShapesCommand,
                                     MoveLayerCommand, RemoveLayerCommand, SetGeometryCommand,
                                     SetLayerAttrCommand, SetShapeLayerCommand, SetTextCommand)
from lumacut_canvas.model import Document, Geometry, Layer, Shape


def setup():
    doc = Document()
    return doc, QUndoStack()


def test_add_and_delete_undo_redo(qapp):
    doc, st = setup()
    a = Shape("rect", Geometry(0, 0, 10, 10), doc.active_layer_id)
    b = Shape("ellipse", Geometry(5, 5, 10, 10), doc.active_layer_id)
    st.push(AddShapesCommand(doc, [a, b]))
    assert len(doc.shapes) == 2
    st.push(DeleteShapesCommand(doc, [a.id]))
    assert [s.id for s in doc.shapes] == [b.id]
    st.undo()
    assert [s.id for s in doc.shapes] == [a.id, b.id]  # Reihenfolge bleibt
    st.undo()
    assert doc.shapes == []
    st.redo(); st.redo()
    assert [s.id for s in doc.shapes] == [b.id]


def test_geometry_command_and_merge(qapp):
    doc, st = setup()
    s = Shape("rect", Geometry(0, 0, 10, 10), doc.active_layer_id)
    st.push(AddShapesCommand(doc, [s]))
    old = {s.id: Geometry(0, 0, 10, 10)}
    st.push(SetGeometryCommand(doc, old, {s.id: Geometry(1, 0, 10, 10)}, mergeable=True))
    st.push(SetGeometryCommand(doc, old, {s.id: Geometry(2, 0, 10, 10)}, mergeable=True))
    assert st.count() == 2
    st.undo()
    assert doc.shape(s.id).geom.x == 0


def test_layer_commands(qapp):
    doc, st = setup()
    base = doc.layers[0].id
    new = Layer(name="Gravieren")
    st.push(AddLayerCommand(doc, new))
    assert doc.active_layer_id == new.id
    st.push(SetLayerAttrCommand(doc, new.id, "power", 30))
    st.push(SetLayerAttrCommand(doc, new.id, "power", 35))  # zusammengeführt
    st.push(MoveLayerCommand(doc, new.id, 1))
    assert doc.layers[1].id == new.id
    st.undo()
    assert doc.layers[0].id == new.id
    st.undo()
    assert doc.layer(new.id).power == 50
    st.undo()
    assert [l.id for l in doc.layers] == [base]
    assert doc.active_layer_id == base


def test_remove_layer_undo_restores_shapes(qapp):
    doc, st = setup()
    st.push(AddLayerCommand(doc, Layer(name="B")))
    lid = doc.active_layer_id
    st.push(AddShapesCommand(doc, [Shape("line", Geometry(0, 0, 5, 5), lid)]))
    st.push(RemoveLayerCommand(doc, lid))
    assert len(doc.layers) == 1 and doc.shapes == []
    st.undo()
    assert len(doc.layers) == 2 and len(doc.shapes) == 1


def test_last_layer_cannot_be_removed(qapp):
    doc, st = setup()
    st.push(RemoveLayerCommand(doc, doc.layers[0].id))
    assert len(doc.layers) == 1


def test_shape_layer_and_text(qapp):
    doc, st = setup()
    st.push(AddLayerCommand(doc, Layer(name="B")))
    other = doc.layers[1].id
    t = Shape("text", Geometry(0, 0, 20, 8), doc.active_layer_id, text="A")
    st.push(AddShapesCommand(doc, [t]))
    st.push(SetShapeLayerCommand(doc, [t.id], other))
    st.push(SetTextCommand(doc, t.id, "B"))
    assert doc.shape(t.id).layer_id == other and doc.shape(t.id).text == "B"
    st.undo(); st.undo()
    assert doc.shape(t.id).layer_id != other and doc.shape(t.id).text == "A"
