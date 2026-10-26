"""Polygon-Werkzeug: Punkte setzen, schließen, abbrechen, Transformationen,
Speichern, Export und G-Code."""

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent

from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.export import export_svg, job_layers
from lumacut_canvas.gcode import document_to_gcode
from lumacut_canvas.model import Document, Shape
from lumacut_canvas.shape_paths import shape_path
from lumacut_canvas.tools import TOOL_SHORTCUTS, Tool

NO = Qt.NoModifier
SHIFT = Qt.ShiftModifier


def editor(qapp):
    ed = CanvasEditor()
    ed.resize(1000, 700)
    ed.show()
    qapp.processEvents()
    ed.set_tool(Tool.POLYGON)
    return ed


def click(ed, x, y, mods=NO):
    ed.tools.press(QPointF(x, y), mods)
    ed.tools.release(QPointF(x, y), mods)


def key(ed, k):
    return ed.tools.key_press(QKeyEvent(QEvent.KeyPress, k, NO))


def test_polygon_tool_action_and_shortcut(qapp):
    ed = editor(qapp)
    a = ed.actions_by_name["tool_polygon"]
    assert TOOL_SHORTCUTS[Tool.POLYGON] == "P" and a.shortcut().toString() == "P"
    assert a.isChecked() and not a.icon().isNull()


def test_click_points_double_click_closes_one_undo_step(qapp):
    ed = editor(qapp)
    d = ed.document
    for p in ((10, 10), (60, 10), (60, 40)):
        click(ed, *p)
    ed.tools.move(QPointF(20, 50), NO, False)       # Vorschau folgt der Maus
    assert len(d.shapes) == 1 and d.shapes[0].kind == "polygon"
    assert ed.undo_stack.count() == 0                # Vorschau ist kein Undo-Schritt
    click(ed, 10.4, 39.6)                            # Raster 1 mm -> (10, 40)
    ed.tools.double_click(QPointF(10.4, 39.6))
    assert len(d.shapes) == 1 and ed.undo_stack.count() == 1
    s = d.shapes[0]
    assert s.kind == "polygon" and s.geom.as_tuple() == (10, 10, 50, 30)
    assert s.abs_points() == pytest.approx([(10, 10), (60, 10), (60, 40), (10, 40)])
    assert ed.selection == [s.id] and ed.property_bar.title.text() == "Polygon"
    ed.undo_stack.undo()
    assert d.shapes == []
    ed.undo_stack.redo()
    assert d.shapes[0].kind == "polygon"


def test_click_on_first_point_or_enter_closes_backspace_and_escape(qapp):
    ed = editor(qapp)
    d = ed.document
    for p in ((100, 100), (150, 100), (150, 150)):
        click(ed, *p)
    click(ed, 100.5, 100.5)                          # nah am Startpunkt -> schließen
    assert len(d.shapes) == 1 and len(d.shapes[0].points) == 3
    for p in ((10, 200), (40, 200), (40, 230), (70, 260)):
        click(ed, *p)
    assert key(ed, Qt.Key_Backspace)                 # letzten Punkt entfernen
    assert key(ed, Qt.Key_Return)
    assert len(d.shapes) == 2 and d.shapes[1].abs_points() == pytest.approx([(10, 200), (40, 200), (40, 230)])
    click(ed, 200, 200)
    click(ed, 250, 200)
    assert key(ed, Qt.Key_Escape)
    assert len(d.shapes) == 2 and ed.undo_stack.count() == 2
    click(ed, 200, 200)
    click(ed, 250, 200)
    assert key(ed, Qt.Key_Return)                    # nur 2 Punkte -> kein Polygon
    assert len(d.shapes) == 2


def test_shift_constrains_edges_to_45_degrees(qapp):
    ed = editor(qapp)
    click(ed, 10, 10)
    click(ed, 50, 12, SHIFT)
    click(ed, 50, 50, SHIFT)
    key(ed, Qt.Key_Return)
    pts = ed.document.shapes[0].abs_points()
    assert pts[1] == pytest.approx((50, 10)) and pts[2] == pytest.approx((50, 50))


def test_polygon_scale_rotate_round_trip_export_gcode(qapp, tmp_path):
    ed = editor(qapp)
    for p in ((10, 10), (30, 10), (10, 30)):
        click(ed, *p)
    key(ed, Qt.Key_Return)
    d = ed.document
    sid = d.shapes[0].id
    ed.property_bar.w.setValue(40)                   # Seitenverhältnis gekoppelt
    # Rechte Kante (Nullpunkt-Seite) bleibt bei 30 → links −10, in die Fläche geschoben.
    assert d.shape(sid).abs_points() == pytest.approx([(0, 10), (40, 10), (0, 50)])
    ed.rotate_selection(90)                          # um die Mitte (20, 30)
    path = shape_path(d.shape(sid))
    pts = [(path.elementAt(i).x, path.elementAt(i).y) for i in range(3)]
    assert pts == pytest.approx([(40, 10), (40, 50), (0, 10)])
    # Speichern/Laden
    data = d.to_dict()
    assert data["objects"][0]["points"] == [[0, 0], [1, 0], [0, 1]]
    d2 = Document.from_dict(data)
    assert d2.shapes[0].kind == "polygon" and d2.shapes[0].abs_points() == pytest.approx(
        d.shape(sid).abs_points())
    bad = dict(data["objects"][0], points=[[0, 0], [1, 1]])
    with pytest.raises(ValueError):
        Shape.from_dict(bad)
    # Export und G-Code: geschlossener Zug (Startpunkt am Ende wiederholt)
    polys = job_layers(d)[0].polylines
    assert len(polys) == 1 and len(polys[0]) == 4 and polys[0][0] == pytest.approx(polys[0][-1])
    assert polys[0][0] == pytest.approx((350, 40))   # Maschine: X = 390 − x, Y = 30 + y
    g = document_to_gcode(d)
    assert "G0 X350.000 Y40.000" in g and "G1 X350.000 Y80.000" in g
    out = tmp_path / "poly.svg"
    export_svg(d, out)
    assert "<path" in out.read_text(encoding="utf-8")


def test_polygon_hit_inside_and_duplicate(qapp):
    ed = editor(qapp)
    for p in ((10, 10), (60, 10), (60, 60), (10, 60)):
        click(ed, *p)
    key(ed, Qt.Key_Return)
    sid = ed.document.shapes[0].id
    assert ed.scene.editable_shape_at(QPointF(35, 35)) == sid
    ed.duplicate_selection()
    dup = ed.document.shapes[1]
    assert dup.kind == "polygon" and dup.points == ed.document.shape(sid).points
