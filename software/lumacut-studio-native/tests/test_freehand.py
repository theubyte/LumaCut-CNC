"""Freihand-Werkzeug (F): Ziehen zeichnet, RDP vereinfacht, offener Pfad."""

import math

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QKeyEvent

from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.export import export_png, export_svg, job_layers
from lumacut_canvas.gcode import document_to_gcode
from lumacut_canvas.model import Document, simplify_polyline
from lumacut_canvas.tools import FREEHAND_TOLERANCE_MM, TOOL_SHORTCUTS, Tool

NO = Qt.NoModifier


@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    e.set_tool(Tool.FREEHAND)
    yield e
    e.undo_stack.setClean()
    e.close()


def stroke(ed, pts):
    ed.tools.press(QPointF(*pts[0]), NO)
    for p in pts[1:]:
        ed.tools.move(QPointF(*p), NO, True)
    ed.tools.release(QPointF(*pts[-1]), NO)


def test_rdp_simplify():
    line = [(x / 10, 0.01 * math.sin(x)) for x in range(101)]   # fast gerade, 101 Punkte
    assert simplify_polyline(line, 0.2) == [line[0], line[-1]]
    corner = [(i, 0.0) for i in range(11)] + [(10.0, float(i)) for i in range(1, 11)]
    assert simplify_polyline(corner, 0.1) == [(0, 0), (10, 0), (10, 10)]
    assert simplify_polyline([(1, 1), (1, 1), (2, 2)], 0.1) == [(1, 1), (2, 2)]
    assert simplify_polyline([(0, 0), (5, 0), (0, 0.0001)], 0.0) == [(0, 0), (5, 0), (0, 0.0001)]


def test_tool_action_shortcut_icon(ed):
    a = ed.actions_by_name["tool_freehand"]
    assert TOOL_SHORTCUTS[Tool.FREEHAND] == "F" and a.shortcut().toString() == "F"
    assert a.isChecked() and not a.icon().isNull()


def test_drag_creates_simplified_open_path_one_undo_step(ed):
    d = ed.document
    pts = [(10 + i * 0.5, 40 + 20 * math.sin(i / 10)) for i in range(120)]   # Welle, ~60 mm
    ed.tools.press(QPointF(*pts[0]), NO)
    for p in pts[1:60]:
        ed.tools.move(QPointF(*p), NO, True)
    assert len(d.shapes) == 1 and ed.undo_stack.count() == 0          # Vorschau
    for p in pts[60:]:
        ed.tools.move(QPointF(*p), NO, True)
    ed.tools.release(QPointF(*pts[-1]), NO)
    assert len(d.shapes) == 1 and ed.undo_stack.count() == 1
    s = d.shapes[0]
    assert s.kind == "path" and 3 <= len(s.points) < 40                # vereinfacht
    # Jeder Rohpunkt liegt nah am vereinfachten Pfad.
    ap = s.abs_points()
    for px, py in pts:
        dist = min(_seg_dist(px, py, a, b) for a, b in zip(ap, ap[1:]))
        assert dist <= FREEHAND_TOLERANCE_MM + 1e-6
    assert ap[0] == pytest.approx(pts[0]) and ap[-1] == pytest.approx(pts[-1])
    assert ed.selection == [s.id] and ed.property_bar.title.text() == "Freihand"
    ed.undo_stack.undo()
    assert d.shapes == []
    ed.undo_stack.redo()
    assert d.shapes[0].kind == "path"


def _seg_dist(px, py, a, b):
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def test_click_or_tiny_stroke_creates_nothing_and_escape_cancels(ed):
    stroke(ed, [(50, 50), (50.1, 50.1)])
    assert ed.document.shapes == [] and ed.undo_stack.count() == 0
    ed.tools.press(QPointF(10, 10), NO)
    for i in range(1, 30):
        ed.tools.move(QPointF(10 + i, 10), NO, True)
    assert len(ed.document.shapes) == 1
    assert ed.tools.key_press(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, NO))
    assert ed.document.shapes == [] and ed.undo_stack.count() == 0
    stroke(ed, [(-20, 10), (30, 10), (400, 10)])                     # auf die Fläche begrenzt
    b = ed.document.shapes[0].bounds()
    assert b.x == pytest.approx(0) and b.right == pytest.approx(360)


def test_transform_group_roundtrip_export_gcode(ed, tmp_path):
    stroke(ed, [(10, 10), (20, 30), (30, 10), (40, 30)])              # offenes "W"
    d = ed.document
    sid = d.shapes[0].id
    ed.translate_selection(5, 0)
    assert d.shape(sid).abs_points()[0] == pytest.approx((15, 10))
    ed.property_bar.w.setValue(60)                                   # Skalieren
    assert d.shape(sid).geom.w == pytest.approx(60)
    ed.rotate_selection(90)
    assert d.shape(sid).geom.rot == 90
    ed.set_tool(Tool.RECT)
    ed.tools.press(QPointF(200, 200), NO); ed.tools.release(QPointF(200, 200), NO)
    ed.set_selection([s.id for s in d.shapes])
    ed.group_selection()
    assert d.shape(sid).groups and d.unit_of(sid) == [s.id for s in d.shapes]
    data = d.to_dict()
    d2 = Document.from_dict(data)
    assert d2.to_dict() == data and d2.shape(sid).kind == "path"
    # Offener Zug: Start- und Endpunkt verschieden, 4 Punkte, nicht geschlossen.
    poly = next(p for p in job_layers(d)[0].polylines if len(p) == 4)
    assert poly[0] != pytest.approx(poly[-1])
    g = document_to_gcode(d)
    assert g.count("G0 ") == 2
    svg = tmp_path / "f.svg"
    export_svg(d, svg)
    assert "<path" in svg.read_text(encoding="utf-8")
    png = tmp_path / "f.png"
    export_png(d, png)
    assert not QImage(str(png)).isNull()
