"""Integrations-Hooks für Scan & Probe: Overlays, ROI-Signal, Docks/Aktionen."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QLabel, QMainWindow

from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.integration import add_dock_panel, make_action
from lumacut_canvas.model import Geometry, Shape
from lumacut_canvas.overlays import ImageOverlay, PainterOverlay
from lumacut_canvas.workarea import Rect

NO = Qt.NoModifier


def _editor(qapp):
    ed = CanvasEditor()
    ed.resize(900, 700)
    ed.show()
    qapp.processEvents()
    ed.view.fit_work_area()
    return ed


def _render(ed) -> QImage:
    """Szene über die Arbeitsfläche rendern, 1 px = 1 mm (inkl. drawBackground)."""
    img = QImage(360, 340, QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    src = ed.view.mapFromScene(QRectF(0, 0, 360, 340)).boundingRect()
    ed.view.render(p, QRectF(img.rect()), src, Qt.IgnoreAspectRatio)
    p.end()
    return img


def test_overlays_draw_under_objects_in_z_order(qapp):
    ed = _editor(qapp)
    red = QImage(10, 10, QImage.Format_RGB32)
    red.fill(QColor("#ff0000"))
    blue = QImage(10, 10, QImage.Format_RGB32)
    blue.fill(QColor("#0000ff"))
    ed.view.set_grid_visible(False)
    ed.add_overlay("scan", ImageOverlay(red))                               # ganze Fläche
    ed.add_overlay("hoehe", ImageOverlay(blue, Rect(200, 200, 100, 100)), z=5)
    assert ed.view.overlay_keys() == ["scan", "hoehe"]
    calls = []
    ed.add_overlay("cb", PainterOverlay(lambda p, work: calls.append(work.width())), z=-1)
    assert ed.view.overlay_keys() == ["cb", "scan", "hoehe"]
    # Ein Objekt liegt über den Overlays.
    ed.document.add_shape(Shape("rect", Geometry(20, 20, 60, 60), ed.document.active_layer_id))
    qapp.processEvents()
    img = _render(ed)
    assert calls and calls[-1] == 360
    assert QColor(img.pixel(150, 100)).red() > 200                      # Scanbild
    assert QColor(img.pixel(250, 250)).blue() > 200                     # Höhenkarte darüber (z=5)
    # Overlays sind nicht anklickbar und landen nicht im Dokument.
    assert ed.scene.editable_shape_at(QPointF(150, 100)) is None
    assert len(ed.document.shapes) == 1
    ed.overlay("hoehe").visible = False
    ed.refresh_overlays()
    assert QColor(_render(ed).pixel(250, 250)).red() > 200
    assert ed.remove_overlay("scan") and not ed.remove_overlay("scan")
    assert ed.overlay("scan") is None


def test_broken_overlay_does_not_break_painting(qapp):
    ed = _editor(qapp)

    def boom(p, work):
        raise RuntimeError("kaputt")

    ed.add_overlay("boom", PainterOverlay(boom))
    _render(ed)  # darf nicht werfen
    try:
        ed.add_overlay("bad", object())
    except TypeError:
        pass
    else:
        raise AssertionError("Overlay ohne paint() muss abgelehnt werden")


def _drag(ed, a, b):
    ed.tools.press(QPointF(*a), NO)
    ed.tools.move(QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), NO, True)
    ed.tools.move(QPointF(*b), NO, True)
    ed.tools.release(QPointF(*b), NO)


def test_request_roi_emits_mm_rect_without_touching_document(qapp):
    ed = _editor(qapp)
    ed.document.add_shape(Shape("rect", Geometry(20, 20, 60, 60), ed.document.active_layer_id))
    got, cancelled = [], []
    ed.roiSelected.connect(lambda *r: got.append(r))
    ed.roiCancelled.connect(lambda: cancelled.append(True))
    ed.request_roi()
    assert ed.roi_pending
    _drag(ed, (30, 40), (400, 120.4))  # über den Rand hinaus -> begrenzt, Raster 1 mm
    assert got == [(30.0, 40.0, 330.0, 80.0)]
    assert not ed.roi_pending and ed.roi == Rect(30, 40, 330, 80)
    assert ed._roi_item.isVisible()
    # Das Objekt wurde weder verschoben noch ausgewählt, kein Undo-Eintrag.
    assert ed.document.shapes[0].geom.as_tuple() == (20, 20, 60, 60)
    assert ed.selection == [] and ed.undo_stack.count() == 0
    # Normale Bedienung danach wieder möglich.
    _drag(ed, (50, 50), (60, 50))
    assert ed.document.shapes[0].geom.x == 30
    ed.clear_roi()
    assert ed.roi is None and not ed._roi_item.isVisible()
    # Abbruch mit Esc (Auswahl bleibt erhalten)
    ed.set_selection([ed.document.shapes[0].id])
    ed.request_roi()
    ed.tools.press(QPointF(10, 10), NO)
    ed.tools.release(QPointF(10, 10), NO)  # bloßer Klick: wartet weiter
    assert ed.roi_pending and len(got) == 1
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    ed.tools.key_press(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, NO))
    assert cancelled == [True] and not ed.roi_pending and len(ed.selection) == 1


def test_dock_panels_and_toolbar_actions(qapp):
    win = QMainWindow()
    ed = CanvasEditor()
    win.setCentralWidget(ed)
    dock = add_dock_panel(win, QLabel("Scan"), "Scan & Probe")
    dock2 = add_dock_panel(win, QLabel("Höhe"), "Höhenkarte", tabify_with=dock)
    assert dock.objectName() == "dock_scan___probe" and dock2.widget().text() == "Höhe"
    assert win.dockWidgetArea(dock) == Qt.RightDockWidgetArea
    assert dock2 in win.tabifiedDockWidgets(dock)
    hits = []
    act = make_action(win, "Bereich scannen", lambda: hits.append(1), shortcut="Ctrl+Shift+B",
                      icon="grid", name="scan_roi")
    ed.add_toolbar_action(act)
    assert ed.actions_by_name["scan_roi"] is act and act in ed.action_bar.actions()
    acts = ed.action_bar.actions()
    assert acts.index(act) < acts.index(ed._zoom_label_action)
    assert "Strg" in act.toolTip() or "Ctrl" in act.toolTip()
    act.trigger()
    assert hits == [1]
    try:
        ed.add_toolbar_action(make_action(win, "x", lambda: None), name="scan_roi")
    except ValueError:
        pass
    else:
        raise AssertionError("doppelter Name muss abgelehnt werden")
    win.close()
