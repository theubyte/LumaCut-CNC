"""Drehung: Modell, Griff, Zahlenfeld, Undo, Speichern, Export und G-Code."""

import math

import pytest
from PySide6.QtCore import QPointF, Qt

from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.export import export_svg, job_layers
from lumacut_canvas.gcode import document_to_gcode
from lumacut_canvas.items import ROTATE_HANDLE
from lumacut_canvas.model import Document, Geometry, Shape, constrain_geometry, normalize_angle
from lumacut_canvas.tools import Tool

NO = Qt.NoModifier
SHIFT = Qt.ShiftModifier


def editor_with(qapp, *geoms, kind="rect"):
    ed = CanvasEditor()
    ed.resize(1000, 700)
    ed.show()
    qapp.processEvents()
    lid = ed.document.active_layer_id
    shapes = [Shape(kind, g, lid) for g in geoms]
    ed.undo_stack.push(AddShapesCommand(ed.document, shapes))
    ed.set_tool(Tool.SELECT)
    return ed, shapes


def approx_rect(r, x, y, w, h, tol=1e-6):
    assert r.x == pytest.approx(x, abs=tol) and r.y == pytest.approx(y, abs=tol)
    assert r.w == pytest.approx(w, abs=tol) and r.h == pytest.approx(h, abs=tol)


def test_geometry_rotation_bounds_and_mapping():
    g = Geometry(100, 100, 40, 20, 90)
    approx_rect(g.bounds(), 110, 90, 20, 40)
    assert normalize_angle(270) == -90 and normalize_angle(-180) == 180 and normalize_angle(360) == 0
    # Drehen um einen fremden Punkt verschiebt die Mitte mit.
    r = Geometry(0, 0, 10, 10).rotated(90, 0, 0)
    assert r.center() == pytest.approx((-5, 5)) and r.rot == 90
    # Gleichmäßiges Skalieren ist für gedrehte Objekte exakt.
    b = g.bounds()
    m = g.mapped(b, type(b)(b.x, b.y, b.w * 2, b.h * 2))
    assert (m.w, m.h, m.rot) == (80, 40, 90)
    approx_rect(m.bounds(), b.x, b.y, b.w * 2, b.h * 2)
    # Gedreht über den Rand -> wird anhand der gedrehten Hüllbox hineingeschoben.
    c = constrain_geometry(Geometry(340, 100, 40, 10, 90))
    assert c.bounds().right <= 360 + 1e-9 and c.rot == 90


def test_rotate_handle_with_shift_snaps_to_15_degrees_one_undo_step(qapp):
    ed, (s,) = editor_with(qapp, Geometry(100, 100, 40, 20))
    ed.set_selection([s.id])
    ov = ed.scene.overlay
    hp = ov.handle_points()[ROTATE_HANDLE]
    assert ov.handle_at(hp) == ROTATE_HANDLE
    c = ov.center()
    # Griff (oben) um ~50° im Uhrzeigersinn um die Mitte ziehen.
    ang = math.radians(-90 + 50)
    rad = c.y() - hp.y()
    target = QPointF(c.x() + rad * math.cos(ang), c.y() + rad * math.sin(ang))
    t = ed.tools
    t.press(hp, NO)
    t.move(QPointF((hp.x() + target.x()) / 2, hp.y()), SHIFT, True)
    t.move(target, SHIFT, True)
    t.release(target, SHIFT)
    g = ed.document.shapes[0].geom
    assert g.rot == pytest.approx(45)
    assert g.center() == pytest.approx((120, 110))
    assert ed.undo_stack.count() == 2 and ed.undo_stack.undoText() == "Drehen"
    # Rahmen folgt dem Objekt (gedreht).
    assert ov.angle == pytest.approx(45)
    ed.undo_stack.undo()
    assert ed.document.shapes[0].geom.rot == 0
    ed.undo_stack.redo()
    assert ed.document.shapes[0].geom.rot == pytest.approx(45)


def test_free_rotation_without_shift(qapp):
    ed, (s,) = editor_with(qapp, Geometry(100, 100, 40, 20))
    ed.set_selection([s.id])
    ov = ed.scene.overlay
    hp = ov.handle_points()[ROTATE_HANDLE]
    c = ov.center()
    rad = c.y() - hp.y()
    ang = math.radians(-90 + 37)
    target = QPointF(c.x() + rad * math.cos(ang), c.y() + rad * math.sin(ang))
    ed.tools.press(hp, NO)
    ed.tools.move(target, NO, True)
    ed.tools.release(target, NO)
    assert ed.document.shapes[0].geom.rot == pytest.approx(37, abs=1e-6)


def test_angle_field_rotates_and_shows_angle(qapp):
    ed, (s,) = editor_with(qapp, Geometry(100, 100, 40, 20))
    ed.set_selection([s.id])
    pb = ed.property_bar
    pb.angle.setValue(30)
    assert ed.document.shapes[0].geom.rot == pytest.approx(30)
    assert ed.undo_stack.undoText() == "Drehen"
    # Eigene Breite bleibt sichtbar und editierbar, Mitte bleibt.
    assert pb.w.value() == pytest.approx(40)
    pb.w.setValue(80)
    g = ed.document.shapes[0].geom
    assert (g.w, g.h, g.rot) == (pytest.approx(80), pytest.approx(40), pytest.approx(30))
    assert g.center() == pytest.approx((120, 110))
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert ed.document.shapes[0].geom.rot == 0
    assert pb.angle.value() == 0


def test_ctrl_r_rotates_group_around_common_center(qapp):
    ed, shapes = editor_with(qapp, Geometry(100, 100, 20, 10), Geometry(140, 100, 20, 10))
    ed.select_all()
    ed.actions_by_name["rotate_cw"].trigger()
    g1, g2 = (s.geom for s in ed.document.shapes)
    assert g1.rot == g2.rot == 90
    # Gemeinsame Mitte (130, 105); Abstand der Mitten bleibt 40 mm, jetzt vertikal.
    assert g1.center() == pytest.approx((130, 85)) and g2.center() == pytest.approx((130, 125))
    assert ed.undo_stack.count() == 2


def test_move_and_scale_on_rotated_object(qapp):
    ed, (s,) = editor_with(qapp, Geometry(100, 100, 40, 20, 90))
    ed.set_selection([s.id])
    t = ed.tools
    # Verschieben
    t.press(QPointF(120, 110), NO)
    t.move(QPointF(130, 120), NO, True)
    t.release(QPointF(130, 120), NO)
    g = ed.document.shapes[0].geom
    assert g.center() == pytest.approx((130, 120)) and g.rot == 90
    # Skalieren am rechten Griff des gedrehten Rahmens = Objektbreite (zeigt nach unten).
    ov = ed.scene.overlay
    hp = ov.handle_points()[3]
    assert hp.x() == pytest.approx(130) and hp.y() == pytest.approx(140)
    t.press(hp, NO)
    t.move(QPointF(hp.x(), hp.y() + 10), NO, True)
    t.release(QPointF(hp.x(), hp.y() + 10), NO)
    g = ed.document.shapes[0].geom
    assert g.w == pytest.approx(50) and g.h == pytest.approx(20) and g.rot == 90
    # Gegenüberliegende Kante (oben, y = 100) bleibt fest.
    assert g.bounds().y == pytest.approx(100)
    assert ed.undo_stack.count() == 3


def test_rotation_round_trip_and_old_files():
    d = Document()
    d.add_shape(Shape("ellipse", Geometry(10, 10, 30, 10, 33.5), d.active_layer_id))
    data = d.to_dict()
    assert data["version"] == 2 and data["objects"][0]["rot"] == 33.5
    e = Document()
    e.load_dict(data)
    assert e.shapes[0].geom.rot == 33.5
    # v1-Datei ohne "rot" lädt weiterhin (ungedreht).
    data["version"] = 1
    del data["objects"][0]["rot"]
    e.load_dict(data)
    assert e.shapes[0].geom.rot == 0
    data["version"] = 3
    with pytest.raises(ValueError):
        e.load_dict(data)


def test_export_and_gcode_respect_rotation(qapp, tmp_path):
    d = Document()
    lid = d.active_layer_id
    d.add_shape(Shape("rect", Geometry(100, 100, 40, 20, 90), lid))
    d.add_shape(Shape("line", Geometry(10, 10, 20, 0, 90), lid))
    rect_poly, line_poly = (jl for jl in job_layers(d)[0].polylines)
    xs = [p[0] - 30 for p in rect_poly]
    ys = [p[1] - 30 for p in rect_poly]
    assert min(xs) == pytest.approx(110) and max(xs) == pytest.approx(130)
    assert min(ys) == pytest.approx(90) and max(ys) == pytest.approx(130)
    assert [(round(x - 30, 6), round(y - 30, 6)) for x, y in line_poly] == [(20, 0), (20, 20)]
    gcode = document_to_gcode(d)
    assert "G0 X160.000 Y120.000" in gcode and "G1 X140.000 Y160.000 F600" in gcode
    svg = tmp_path / "r.svg"
    export_svg(d, svg)
    assert svg.read_text(encoding="utf-8").count("<path") >= 1
