"""Gruppieren/Entgruppieren: Auswahl als Einheit, Transformationen, Undo,
Duplizieren, Ebenen, Speichern, Export und G-Code."""

import pytest
from PySide6.QtCore import QPointF, Qt

from lumacut_canvas.commands import AddShapesCommand, RemoveLayerCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.export import job_layers
from lumacut_canvas.gcode import document_to_gcode
from lumacut_canvas.model import Document, Geometry, Layer, Shape
from lumacut_canvas.tools import Tool

NO = Qt.NoModifier
SHIFT = Qt.ShiftModifier


def setup(qapp):
    ed = CanvasEditor()
    ed.resize(1000, 700)
    ed.show()
    qapp.processEvents()
    lid = ed.document.active_layer_id
    a = Shape("rect", Geometry(10, 10, 20, 20), lid)
    b = Shape("ellipse", Geometry(50, 10, 20, 20), lid)
    c = Shape("rect", Geometry(100, 100, 10, 10), lid)
    ed.undo_stack.push(AddShapesCommand(ed.document, [a, b, c]))
    ed.set_tool(Tool.SELECT)
    return ed, a.id, b.id, c.id


def click(ed, x, y, mods=NO):
    ed.tools.press(QPointF(x, y), mods)
    ed.tools.release(QPointF(x, y), mods)


def test_group_selects_as_unit_and_moves_together(qapp):
    ed, a, b, c = setup(qapp)
    ed.set_selection([a, b])
    ed.actions_by_name["group"].trigger()
    assert ed.undo_stack.undoText() == "Gruppieren"
    click(ed, 300, 300)
    assert ed.selection == []
    click(ed, 20, 20)  # Klick auf ein Mitglied wählt die ganze Gruppe
    assert set(ed.selection) == {a, b}
    assert ed.property_bar.title.text() == "Gruppe (2)"
    ed.tools.press(QPointF(20, 20), NO)
    ed.tools.move(QPointF(40, 50), NO, True)
    ed.tools.release(QPointF(40, 50), NO)
    d = ed.document
    assert d.shape(a).geom.as_tuple() == (30, 40, 20, 20)
    assert d.shape(b).geom.as_tuple() == (70, 40, 20, 20)
    assert d.shape(c).geom.as_tuple() == (100, 100, 10, 10)
    # Shift-Klick auf ein Gruppenmitglied nimmt die ganze Gruppe wieder heraus.
    click(ed, 105, 105, SHIFT)
    assert set(ed.selection) == {a, b, c}
    click(ed, 82, 55, SHIFT)
    assert ed.selection == [c]


def test_group_scale_rotate_delete_and_undo(qapp):
    ed, a, b, c = setup(qapp)
    d = ed.document
    ed.set_selection([a, b])
    ed.group_selection()
    # Skalieren über die Zahlenfelder wirkt auf die ganze Gruppe.
    ed.set_selection([a])
    assert set(ed.selection) == {a, b}
    ed.property_bar.w.setValue(120)  # 60 -> 120, Seitenverhältnis gekoppelt
    assert d.shape(a).geom.as_tuple() == (10, 10, 40, 40)
    assert d.shape(b).geom.as_tuple() == (90, 10, 40, 40)
    ed.rotate_selection(90)
    assert d.shape(a).geom.rot == d.shape(b).geom.rot == 90
    # Mitten um die gemeinsame Mitte (70, 30) gedreht und dann nach unten in die Fläche geschoben.
    assert d.shape(a).geom.center() == pytest.approx((70, 20)) and d.shape(b).geom.center() == pytest.approx((70, 100))
    assert d.selection_bounds([a, b]).y >= 0  # gemeinsam in der Fläche gehalten
    ed.delete_selection()
    assert [s.id for s in d.shapes] == [c]
    for _ in range(3):  # Löschen, Drehen, Skalieren
        ed.undo_stack.undo()
    assert {s.id for s in d.shapes} == {a, b, c}
    assert d.shape(a).geom.as_tuple() == (10, 10, 20, 20) and d.shape(a).geom.rot == 0
    assert d.shape(a).groups == d.shape(b).groups != ()
    ed.undo_stack.undo()  # Gruppieren rückgängig
    assert d.shape(a).groups == ()


def test_nested_groups_and_ungroup_one_level(qapp):
    ed, a, b, c = setup(qapp)
    d = ed.document
    ed.set_selection([a, b])
    ed.group_selection()
    inner = d.shape(a).groups
    ed.set_selection([a, c])  # Gruppe (a, b) + c
    assert set(ed.selection) == {a, b, c}
    ed.group_selection()
    outer = d.shape(c).groups
    assert len(outer) == 1 and d.shape(a).groups == outer + inner
    click(ed, 300, 300)
    click(ed, 105, 105)
    assert set(ed.selection) == {a, b, c}
    ed.actions_by_name["ungroup"].trigger()
    assert d.shape(a).groups == inner and d.shape(c).groups == ()
    click(ed, 300, 300)
    click(ed, 60, 20)
    assert set(ed.selection) == {a, b}  # innere Gruppe bleibt erhalten
    ed.ungroup_selection()
    click(ed, 300, 300)
    click(ed, 60, 20)
    assert ed.selection == [b]
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert d.shape(a).groups == outer + inner


def test_duplicate_group_creates_independent_group(qapp):
    ed, a, b, c = setup(qapp)
    d = ed.document
    ed.set_selection([a, b])
    ed.group_selection()
    ed.duplicate_selection()
    copies = list(ed.selection)
    assert len(copies) == 2 and not set(copies) & {a, b}
    g_new = {d.shape(i).groups for i in copies}
    assert len(g_new) == 1 and g_new.pop() != d.shape(a).groups
    ed.translate_selection(150, 150)  # Kopie bewegt sich als Einheit
    assert d.shape(copies[0]).geom.x == pytest.approx(165) and d.shape(a).geom.x == 10
    click(ed, 300, 300)
    click(ed, 20, 20)
    assert set(ed.selection) == {a, b}


def test_group_across_layers_keeps_layer_settings_and_locked_layer(qapp):
    ed, a, b, c = setup(qapp)
    d = ed.document
    engrave = Layer(name="Gravur", color="#ff0000", power=30, speed=2000, passes=1)
    d.add_layer(engrave, 0)
    d.set_shape_layer(b, engrave.id)
    ed.set_selection([a, b])
    ed.group_selection()
    jl = {l.name: l for l in job_layers(d)}
    assert len(jl["Gravur"].polylines) == 1 and jl["Gravur"].power_percent == 30
    assert "S76" in document_to_gcode(d)  # round(30 % * 2.55)
    # Gesperrte Ebene: das gesperrte Mitglied bleibt unberührt.
    d.update_layer(engrave.id, locked=True)
    click(ed, 300, 300)
    click(ed, 20, 20)
    assert ed.selection == [a]
    # Ebene löschen und wiederherstellen behält die Gruppenzugehörigkeit.
    d.update_layer(engrave.id, locked=False)
    ed.undo_stack.push(RemoveLayerCommand(d, engrave.id))
    assert not d.has_shape(b)
    ed.undo_stack.undo()
    assert d.shape(b).groups == d.shape(a).groups


def test_groups_round_trip():
    d = Document()
    lid = d.active_layer_id
    d.add_shape(Shape("rect", Geometry(1, 1, 5, 5), lid, groups=("g1", "g2")))
    data = d.to_dict()
    assert data["objects"][0]["groups"] == ["g1", "g2"]
    e = Document()
    e.load_dict(data)
    assert e.shapes[0].groups == ("g1", "g2")
