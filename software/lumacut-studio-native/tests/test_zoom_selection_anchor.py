"""Mausrad-Zoom: ohne Auswahl am Mauszeiger, mit Auswahl an deren Mitte (headless)."""

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from lumacut_canvas.canvas_view import MAX_SCALE
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.model import Geometry, Shape


@pytest.fixture
def ed(qapp):
    from lumacut_canvas.editor import CanvasEditor
    e = CanvasEditor()
    e.resize(900, 700)
    e.show()
    qapp.processEvents()
    lid = e.document.active_layer_id
    e.shapes = [Shape("rect", Geometry(100, 100, 40, 20), lid), Shape("rect", Geometry(160, 140, 20, 20), lid)]
    e.undo_stack.push(AddShapesCommand(e.document, e.shapes))
    e.set_selection([])
    e.view.set_zoom(3.0)
    e.view.centerOn(180, 170)
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def wheel(view, pos, dy=120):
    vp = view.viewport()
    ev = QWheelEvent(QPointF(pos), QPointF(vp.mapToGlobal(pos)), QPoint(0, 0), QPoint(0, dy),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(vp, ev)


def vp_pos(view, x, y):
    return view.viewportTransform().map(QPointF(x, y))


def close(a: QPointF, b: QPointF, px=1.5):
    return abs(a.x() - b.x()) <= px and abs(a.y() - b.y()) <= px


def test_without_selection_point_under_cursor_stays(ed):
    view = ed.view
    pos = QPoint(250, 200)
    before = view.mapToScene(pos)
    wheel(view, pos)
    assert view.px_per_mm == pytest.approx(3.0 * 1.15, rel=1e-6)
    assert close(vp_pos(view, before.x(), before.y()), QPointF(pos))


def test_with_selection_center_stays_regardless_of_cursor(ed):
    view = ed.view
    ed.set_selection([ed.shapes[0].id, ed.shapes[1].id])  # Mitte (140, 130)
    anchor = vp_pos(view, 140, 130)
    assert view.viewport().rect().contains(anchor.toPoint())
    for pos in (QPoint(20, 20), QPoint(800, 600)):  # Zeigerposition spielt keine Rolle
        wheel(view, pos)
        assert close(vp_pos(view, 140, 130), anchor)
    wheel(view, QPoint(5, 5), dy=-240)  # herauszoomen ebenso
    assert close(vp_pos(view, 140, 130), anchor)
    assert view.px_per_mm == pytest.approx(3.0, rel=1e-6)


def test_offscreen_selection_is_brought_into_view(ed):
    view = ed.view
    view.set_zoom(8.0)
    view.centerOn(20, 20)
    ed.set_selection([ed.shapes[1].id])  # Mitte (170, 150), außerhalb
    assert not view.viewport().rect().contains(vp_pos(view, 170, 150).toPoint())
    wheel(view, QPoint(100, 100))
    centre = QPointF(view.viewport().width() / 2, view.viewport().height() / 2)
    assert close(vp_pos(view, 170, 150), centre, px=2)


def test_zoom_clamped_and_view_signal_for_rulers(ed):
    view = ed.view
    ed.set_selection([ed.shapes[0].id])
    hits = []
    view.viewChanged.connect(lambda: hits.append(1))
    anchor = vp_pos(view, 120, 110)
    for _ in range(40):
        wheel(view, QPoint(10, 10))
    assert view.px_per_mm == pytest.approx(MAX_SCALE)
    assert hits  # Lineale/Raster werden nachgeführt
    assert close(vp_pos(view, 120, 110), anchor, px=2)


def test_pan_still_works_with_selection(ed):
    view = ed.view
    ed.set_selection([ed.shapes[0].id])
    hb = view.horizontalScrollBar()
    v0 = hb.value()
    hb.setValue(v0 + 50)  # Pan verschiebt die Scrollleisten
    assert hb.value() == v0 + 50
    wheel(view, QPoint(10, 10))
    assert ed.selection == [ed.shapes[0].id]  # Zoom ändert die Auswahl nicht
