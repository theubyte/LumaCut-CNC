import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QNativeGestureEvent, QPointingDevice, QWheelEvent
from PySide6.QtWidgets import QApplication

from lumacut_canvas.canvas_view import MAX_SCALE, MIN_SCALE
from lumacut_canvas.model import Geometry, Shape


@pytest.fixture
def editor(qapp):
    from lumacut_canvas.editor import CanvasEditor
    ed = CanvasEditor()
    ed.resize(900, 700)
    ed.show()
    qapp.processEvents()
    yield ed
    ed.undo_stack.setClean()
    ed.close()
    ed.deleteLater()
    qapp.processEvents()


def _wheel(view, pos, dy=120, pixel=0):
    vp = view.viewport()
    ev = QWheelEvent(QPointF(pos), QPointF(vp.mapToGlobal(pos)), QPoint(0, pixel), QPoint(0, dy),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(vp, ev)


def test_wheel_zoom_keeps_point_under_cursor(editor):
    view = editor.view
    view.set_zoom(4.0)  # scene larger than the viewport -> room to scroll
    view.centerOn(180, 170)
    pos = QPoint(200, 150)
    before = view.mapToScene(pos)
    _wheel(view, pos)
    assert view.px_per_mm == pytest.approx(4.0 * 1.15, rel=1e-6)
    after = view.mapToScene(pos)
    tol = 1.5 / view.px_per_mm  # one pixel rounding
    assert abs(after.x() - before.x()) < tol and abs(after.y() - before.y()) < tol


def test_trackpad_pixel_delta_zooms(editor):
    view = editor.view
    view.set_zoom(2.0)
    _wheel(view, QPoint(100, 100), dy=0, pixel=60)
    assert view.px_per_mm == pytest.approx(2.3, rel=1e-6)


def test_zoom_limits(editor):
    view = editor.view
    view.set_zoom(1000)
    assert view.px_per_mm == pytest.approx(MAX_SCALE)
    view.zoom_by(0.0001)
    assert view.px_per_mm == pytest.approx(MIN_SCALE)


def test_keyboard_zoom_keeps_view_centre(editor):
    view = editor.view
    view.set_zoom(3.0)
    view.centerOn(180, 170)
    vp = view.viewport().rect()
    c = QPoint(vp.width() // 2, vp.height() // 2)
    before = view.mapToScene(c)
    view.zoom_by(1.25)  # same call as the Ctrl+= action
    after = view.mapToScene(c)
    assert view.px_per_mm == pytest.approx(3.75, rel=1e-6)
    assert abs(after.x() - before.x()) < 1.0 and abs(after.y() - before.y()) < 1.0


def test_pinch_gesture_zooms_at_fingers(editor):
    view = editor.view
    view.set_zoom(4.0)
    view.centerOn(180, 170)
    pos = QPointF(250, 200)
    before = view.mapToScene(pos.toPoint())
    vp = view.viewport()
    ev = QNativeGestureEvent(Qt.ZoomNativeGesture, QPointingDevice.primaryPointingDevice(), 2,
                             pos, pos, QPointF(vp.mapToGlobal(pos.toPoint())), 0.5, QPointF(), 0)
    QApplication.sendEvent(vp, ev)
    assert view.px_per_mm == pytest.approx(6.0, rel=1e-6)
    after = view.mapToScene(pos.toPoint())
    assert abs(after.x() - before.x()) < 1.0 and abs(after.y() - before.y()) < 1.0


def test_fit_selection(editor):
    doc = editor.document
    s = doc.add_shape(Shape("rect", Geometry(100, 100, 40, 20), doc.active_layer_id))
    editor.set_selection([s.id])
    editor.fit_selection()
    view = editor.view
    vis = view.mapToScene(view.viewport().rect()).boundingRect()
    assert vis.contains(QRectF(100, 100, 40, 20))
    assert vis.width() < 120  # zoomed in, not the whole 360 mm work area
    tiny = doc.add_shape(Shape("rect", Geometry(10, 10, 0.1, 0.1), doc.active_layer_id))
    editor.set_selection([tiny.id])
    editor.fit_selection()
    assert view.px_per_mm <= MAX_SCALE + 1e-9
    editor.set_selection([])
    doc.remove_shape(s.id)
    doc.remove_shape(tiny.id)
    editor.fit_selection()  # nothing -> work area
    vis = view.mapToScene(view.viewport().rect()).boundingRect()
    assert vis.width() >= 360 or vis.height() >= 340


def test_main_window_job_tools(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    from lumacut_job.material_test import MaterialTestSpec
    win = main.LumaCutStudio()
    tools = win.job_tools
    assert tools.show_estimate() is None  # empty document
    doc = win.canvas.document
    doc.add_shape(Shape("rect", Geometry(10, 10, 50, 30), doc.active_layer_id))
    est = tools.show_estimate()
    assert est is not None and est.cut_length_mm == pytest.approx(160, rel=0.01)
    sent = []
    monkeypatch.setattr(win.machine_panel, "send_gcode",
                        lambda n, g, start=False: sent.append((n, g, start)))
    g = tools.frame_job(confirm=False)
    assert sent == [("lumacut-frame.gcode", g, True)] and "M3 I" not in g
    win._send_canvas_job()
    assert sent[-1][0] == "canvas.gcode" and sent[-1][2] is False
    assert "Gesendet" in win.statusBar().currentMessage()
    assert tools.material_test(MaterialTestSpec(columns=2, rows=2, x=100, y=100)) == 5
    win.canvas.undo_stack.setClean()
    win.close()
