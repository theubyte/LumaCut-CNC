"""Touch-Bedienung des Canvas (Surface Pro): Griffgrößen, Fangbereiche,
Pinch-Zoom, Touch-Pan, Touch-Modus-Schalter – alles headless.

Touch-Ereignisse werden mit einem eigenen, *nicht* global registrierten
QPointingDevice erzeugt (``QTest.createTouchDevice`` würde ein Gerät
registrieren und damit in späteren Tests die automatische Erkennung auslösen).
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
from PySide6.QtWidgets import QApplication

from lumacut_canvas import touch
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.items import ROTATE_HANDLE
from lumacut_canvas.model import Geometry, Shape


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "touch.ini"), QSettings.IniFormat)


@pytest.fixture
def ed(qapp, settings, monkeypatch):
    monkeypatch.setattr(touch, "has_touchscreen", lambda: False)
    e = CanvasEditor(settings=settings)
    e.resize(1000, 800)
    e.show()
    qapp.processEvents()
    e.view.set_zoom(4.0)
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def _rect(ed, x, y, w, h, kind="rect"):
    s = Shape(kind, Geometry(x, y, w, h), ed.document.active_layer_id)
    ed.document.add_shape(s)
    return s.id


def _vp(ed, scene_pt: QPointF) -> QPointF:
    return ed.view.mapFromScene(scene_pt).toPointF()


# --- 1: Griffe -------------------------------------------------------------
def test_handle_sizes_by_mode_are_screen_pixels(ed):
    sid = _rect(ed, 50, 50, 40, 30)
    ed.set_selection([sid])
    ov = ed.scene.overlay
    assert ed.touch_mode is False
    mouse_draw, mouse_hit = ov.handle_size_mm(), ov.handle_hit_mm()
    ed.set_touch_mode(True)
    assert ov.metrics is touch.TOUCH
    px = ed.view.px_per_mm
    # Touch: ≥ 28 px Trefferfläche (2 × halbe Kante), Trefferfläche ≥ gezeichneter Griff.
    assert 28 <= 2 * ov.handle_hit_mm() * px <= 40
    assert ov.handle_hit_mm() * 2 >= ov.handle_size_mm()
    assert ov.handle_size_mm() > mouse_draw and ov.handle_hit_mm() > mouse_hit
    # Konstante Bildschirmgröße bei jedem Zoom.
    for z in (1.0, 12.0):
        ed.view.set_zoom(z)
        assert ov.handle_size_mm() * ed.view.px_per_mm == pytest.approx(touch.TOUCH.handle_px)
        assert ov.handle_hit_mm() * ed.view.px_per_mm == pytest.approx(touch.TOUCH.handle_hit_px)
    ed.set_touch_mode(False)
    assert ov.metrics is touch.MOUSE
    assert ov.handle_size_mm() * ed.view.px_per_mm == pytest.approx(9.0)


def test_touch_handles_hit_farther_and_rotate_offset_grows(ed):
    sid = _rect(ed, 50, 50, 40, 30)
    ed.set_selection([sid])
    ov = ed.scene.overlay
    px = ed.view.px_per_mm
    corner = QPointF(90, 80)  # Griff 4 (unten rechts)
    off = QPointF(corner.x() + 13 / px, corner.y() + 13 / px)  # 13 px daneben
    assert ov.handle_at(off) is None
    rot_mouse = ov.handle_points()[ROTATE_HANDLE]
    ed.set_touch_mode(True)
    assert ov.handle_at(off) == 4
    rot_touch = ov.handle_points()[ROTATE_HANDLE]
    assert (50 - rot_touch.y()) * px == pytest.approx(touch.TOUCH.rotate_offset_px)
    assert rot_touch.y() < rot_mouse.y()
    assert ov.handle_at(rot_touch) == ROTATE_HANDLE


def test_touch_mode_toggle_persists_and_overrides_autodetect(qapp, settings, monkeypatch):
    monkeypatch.setattr(touch, "has_touchscreen", lambda: True)
    e = CanvasEditor(settings=settings)
    assert e.touch_mode is True  # automatisch: Touchscreen vorhanden
    assert e.actions_by_name["touch_mode"].isChecked()
    seen = []
    e.touchModeChanged.connect(seen.append)
    e.actions_by_name["touch_mode"].trigger()  # Benutzer schaltet ab
    assert e.touch_mode is False and seen == [False]
    assert touch.load_setting(settings) is False
    e2 = CanvasEditor(settings=settings)
    assert e2.touch_mode is False  # gespeicherte Wahl schlägt die Erkennung
    e2.view.touchDetected.emit()
    assert e2.touch_mode is False
    settings.remove(touch.SETTINGS_KEY)
    monkeypatch.setattr(touch, "has_touchscreen", lambda: False)
    e3 = CanvasEditor(settings=settings)
    assert e3.touch_mode is False
    e3.view.touchDetected.emit()  # erste echte Touch-Eingabe -> automatisch ein
    assert e3.touch_mode is True and touch.load_setting(settings) is None


def test_default_settings_only_with_organization(qapp):
    old = qapp.organizationName()
    try:
        qapp.setOrganizationName("")
        assert touch.default_settings() is None
    finally:
        qapp.setOrganizationName(old)


# --- Hilfen für Touch-Ereignisse -----------------------------------------
_DEV = None


def _device():
    from PySide6.QtGui import QInputDevice, QPointingDevice
    global _DEV
    if _DEV is None:  # bewusst nicht registriert (siehe Moduldoku)
        _DEV = QPointingDevice("lumacut test touch", 4711, QInputDevice.DeviceType.TouchScreen,
                               QPointingDevice.PointerType.Finger, QInputDevice.Capability.Position, 10, 0)
    return _DEV


def _touch(ed, etype, points, device=None):
    """points: [(id, viewport-Position, Zustand)] mit Zustand 'p'/'m'/'s'/'r'."""
    from PySide6.QtGui import QEventPoint, QTouchEvent
    from PySide6.QtWidgets import QApplication
    states = {"p": QEventPoint.State.Pressed, "m": QEventPoint.State.Updated,
              "s": QEventPoint.State.Stationary, "r": QEventPoint.State.Released}
    vp = ed.view.viewport()
    eps = [QEventPoint(i, states[s], QPointF(pos), vp.mapToGlobal(QPointF(pos))) for i, pos, s in points]
    ev = QTouchEvent(etype, device or _device(), Qt.NoModifier, eps)
    QApplication.sendEvent(vp, ev)
    return ev


def _drag1(ed, a: QPointF, b: QPointF, steps=5):
    _touch(ed, QEvent.TouchBegin, [(0, a, "p")])
    for k in range(1, steps + 1):
        _touch(ed, QEvent.TouchUpdate, [(0, a + (b - a) * (k / steps), "m")])
    _touch(ed, QEvent.TouchEnd, [(0, b, "r")])


def _pinch(ed, c: QPointF, d0: float, d1: float, shift=QPointF(0, 0), steps=6):
    """Zwei Finger waagrecht um ``c``, Abstand d0 -> d1, Mitte wandert um ``shift``."""
    def pts(d, cc, state):
        return [(1, cc - QPointF(d / 2, 0), state), (2, cc + QPointF(d / 2, 0), state)]
    _touch(ed, QEvent.TouchBegin, pts(d0, c, "p"))
    for k in range(1, steps + 1):
        f = k / steps
        _touch(ed, QEvent.TouchUpdate, pts(d0 + (d1 - d0) * f, c + shift * f, "m"))
    _touch(ed, QEvent.TouchEnd, pts(d1, c + shift, "r"))


# --- 2: Pinch-Zoom -----------------------------------------------------------
def test_pinch_zooms_about_finger_center(ed):
    v = ed.view
    c = QPointF(400, 300)
    scene_c = v.mapToScene(c.toPoint())
    z0 = v.px_per_mm
    seen = []
    v.viewChanged.connect(lambda: seen.append(1))
    _pinch(ed, c, 100, 200)
    assert v.px_per_mm == pytest.approx(2 * z0, rel=1e-6)
    after = v.mapFromScene(scene_c).toPointF()
    assert abs(after.x() - c.x()) <= 1.5 and abs(after.y() - c.y()) <= 1.5
    assert seen  # Lineale/Raster bekommen die Änderung mit


def test_pinch_with_moving_center_pans_and_respects_limits(ed):
    from lumacut_canvas.canvas_view import MAX_SCALE, MIN_SCALE
    v = ed.view
    c = QPointF(400, 300)
    scene_c = v.mapToScene(c.toPoint())
    shift = QPointF(60, -40)
    _pinch(ed, c, 150, 150, shift)  # reines Zwei-Finger-Verschieben
    after = v.mapFromScene(scene_c).toPointF()
    assert abs(after.x() - (c + shift).x()) <= 1.5 and abs(after.y() - (c + shift).y()) <= 1.5
    _pinch(ed, c, 20, 2000)
    assert v.px_per_mm == pytest.approx(MAX_SCALE)
    _pinch(ed, c, 2000, 20)
    _pinch(ed, c, 2000, 20)
    assert v.px_per_mm == pytest.approx(MIN_SCALE)


def test_pinch_math_helper_direct(ed):
    v = ed.view
    anchor, scene_pt = QPointF(300, 200), QPointF(100, 100)
    v.pinch_to(8.0, anchor, scene_pt)
    assert v.px_per_mm == pytest.approx(8.0)
    p = v.mapFromScene(scene_pt).toPointF()
    assert abs(p.x() - anchor.x()) <= 1 and abs(p.y() - anchor.y()) <= 1


def test_second_finger_aborts_object_drag(ed):
    sid = _rect(ed, 60, 60, 40, 40)
    g0 = ed.document.shape(sid).geom.copy()
    a = _vp(ed, QPointF(80, 80))
    _touch(ed, QEvent.TouchBegin, [(1, a, "p")])
    _touch(ed, QEvent.TouchUpdate, [(1, a + QPointF(40, 0), "m")])  # Objekt wird gezogen …
    assert ed.document.shape(sid).geom.x != g0.x
    b = a + QPointF(140, 0)
    _touch(ed, QEvent.TouchUpdate, [(1, a + QPointF(40, 0), "s"), (2, b, "p")])  # … zweiter Finger
    assert ed.document.shape(sid).geom.x == pytest.approx(g0.x)  # zurückgesprungen
    _touch(ed, QEvent.TouchUpdate, [(1, a + QPointF(20, 0), "m"), (2, b + QPointF(30, 0), "m")])
    _touch(ed, QEvent.TouchUpdate, [(2, b + QPointF(30, 0), "s"), (1, a, "r")])
    _touch(ed, QEvent.TouchEnd, [(2, b + QPointF(60, 0), "r")])
    assert ed.document.shape(sid).geom.x == pytest.approx(g0.x)
    assert not ed.undo_stack.canUndo() or ed.undo_stack.undoText() != "Verschieben"


def test_one_finger_drag_moves_object_like_mouse(ed):
    sid = _rect(ed, 60, 60, 40, 40)
    px = ed.view.px_per_mm
    _drag1(ed, _vp(ed, QPointF(80, 80)), _vp(ed, QPointF(80, 80)) + QPointF(20 * px, 0))
    assert ed.document.shape(sid).geom.x == pytest.approx(80, abs=1.0)
    assert ed.undo_stack.undoText() == "Verschieben"


def test_tap_selects_object(ed):
    sid = _rect(ed, 60, 60, 40, 40)
    p = _vp(ed, QPointF(80, 80))
    _touch(ed, QEvent.TouchBegin, [(0, p, "p")])
    _touch(ed, QEvent.TouchEnd, [(0, p + QPointF(3, 2), "r")])
    assert ed.selection == [sid]


def test_touchpad_events_are_left_to_qt(ed):
    from PySide6.QtGui import QInputDevice, QPointingDevice
    pad = QPointingDevice("pad", 4712, QInputDevice.DeviceType.TouchPad,
                          QPointingDevice.PointerType.Finger, QInputDevice.Capability.Position, 5, 0)
    z0 = ed.view.px_per_mm
    c = QPointF(400, 300)
    _touch(ed, QEvent.TouchBegin, [(1, c - QPointF(50, 0), "p"), (2, c + QPointF(50, 0), "p")], pad)
    _touch(ed, QEvent.TouchUpdate, [(1, c - QPointF(100, 0), "m"), (2, c + QPointF(100, 0), "m")], pad)
    assert ed.view.px_per_mm == pytest.approx(z0)


def test_zoom_buttons_large_and_only_in_touch_mode(ed):
    from lumacut_canvas.canvas_view import PX_PER_MM_100
    zb = ed.view.zoom_buttons
    assert not zb.isVisible()
    ed.set_touch_mode(True)
    assert zb.isVisible()
    for b in zb.buttons.values():
        assert b.width() >= 44 and b.height() >= 44
    z0 = ed.view.px_per_mm
    zb.buttons["zoom_in"].click()
    assert ed.view.px_per_mm == pytest.approx(z0 * 1.25)
    zb.buttons["zoom_out"].click()
    assert ed.view.px_per_mm == pytest.approx(z0)
    zb.buttons["zoom_100"].click()
    assert ed.view.px_per_mm == pytest.approx(PX_PER_MM_100)
    assert ed.zoom_label.text() == "100 %"
    zb.buttons["fit"].click()
    assert ed.view.px_per_mm != pytest.approx(PX_PER_MM_100)
    vp = ed.view.viewport().geometry()
    assert vp.contains(zb.geometry())
    ed.set_touch_mode(False)
    assert not zb.isVisible()


# --- 3: Touch-Scrollen -------------------------------------------------------
def test_one_finger_on_empty_background_pans(ed):
    from lumacut_canvas.tools import Tool
    sid = _rect(ed, 60, 60, 40, 40)
    ed.set_selection([sid])
    v = ed.view
    a = _vp(ed, QPointF(250, 250))  # leer
    probe = QPointF(250, 250)
    _drag1(ed, a, a + QPointF(-80, 50))
    after = v.mapFromScene(probe).toPointF()
    assert abs(after.x() - (a.x() - 80)) <= 1.5 and abs(after.y() - (a.y() + 50)) <= 1.5
    assert ed.selection == [sid]  # Verschieben hebt die Auswahl nicht auf
    assert ed.document.shape(sid).geom.x == pytest.approx(60)
    assert not ed.tools._rubber.isVisible()
    # Mit einem Zeichenwerkzeug zeichnet derselbe Zug ein Rechteck.
    ed.set_tool(Tool.RECT)
    n = len(ed.document.shapes)
    b = _vp(ed, QPointF(250, 250))
    _drag1(ed, b, b + QPointF(80, 60))
    assert len(ed.document.shapes) == n + 1


def test_tap_on_empty_background_clears_selection(ed):
    sid = _rect(ed, 60, 60, 40, 40)
    ed.set_selection([sid])
    p = _vp(ed, QPointF(250, 250))
    _touch(ed, QEvent.TouchBegin, [(0, p, "p")])
    _touch(ed, QEvent.TouchEnd, [(0, p, "r")])
    assert ed.selection == []


def test_mouse_drag_on_empty_space_still_rubber_bands(ed, qapp):
    from PySide6.QtTest import QTest
    a = _rect(ed, 60, 60, 10, 10)
    b = _rect(ed, 80, 60, 10, 10)
    vp = ed.view.viewport()
    p0 = _vp(ed, QPointF(50, 50)).toPoint()
    p1 = _vp(ed, QPointF(95, 75)).toPoint()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, p0)
    QTest.mouseMove(vp, p1)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, p1)
    assert set(ed.selection) == {a, b}


def test_synthesized_mouse_after_touch_is_not_handled_twice(ed, qapp):
    from PySide6.QtGui import QMouseEvent, QPointingDevice
    from PySide6.QtWidgets import QApplication
    sid = _rect(ed, 60, 60, 40, 40)
    p = _vp(ed, QPointF(80, 80))
    _drag1(ed, p, p + QPointF(40, 0))  # per Touch verschoben (ein Undo-Schritt)
    count = ed.undo_stack.count()
    x = ed.document.shape(sid).geom.x
    vp = ed.view.viewport()
    # Das System liefert dieselbe Geste noch einmal als "Maus" nach.
    def mouse(t, pos, buttons):
        ev = QMouseEvent(t, QPointF(pos), vp.mapToGlobal(QPointF(pos)), Qt.LeftButton, buttons,
                         Qt.NoModifier, _device())
        QApplication.sendEvent(vp, ev)
    mouse(QEvent.MouseButtonPress, p + QPointF(40, 0), Qt.LeftButton)
    mouse(QEvent.MouseMove, p + QPointF(120, 0), Qt.LeftButton)
    mouse(QEvent.MouseButtonRelease, p + QPointF(120, 0), Qt.NoButton)
    assert ed.document.shape(sid).geom.x == pytest.approx(x)
    assert ed.undo_stack.count() == count
    assert QPointingDevice.primaryPointingDevice().type() != _device().type()


def test_double_tap_acts_as_double_click(ed, monkeypatch):
    calls = []
    monkeypatch.setattr(ed.tools, "double_click", lambda pos: calls.append(pos))
    p = _vp(ed, QPointF(250, 250))
    for _ in range(2):
        _touch(ed, QEvent.TouchBegin, [(0, p, "p")])
        _touch(ed, QEvent.TouchEnd, [(0, p, "r")])
    assert len(calls) == 1


# --- Schritt 4: große Werkzeugknöpfe / Ebenen-Panel -----------------------
def _strip_buttons(ed):
    from PySide6.QtWidgets import QToolButton
    return [b for b in ed.tool_strip.findChildren(QToolButton) if b.defaultAction() is not None]


def test_tool_buttons_grow_in_touch_mode(ed):
    ed.show()
    QApplication.processEvents()
    small = [b.sizeHint() for b in _strip_buttons(ed)]
    # Werkzeugleiste ist immer fingertauglich (>= 44 px), Touch-Modus legt nach.
    assert small and min(min(s.height(), s.width()) for s in small) >= 44
    assert max(s.height() for s in small) < 48
    ed.set_touch_mode(True)
    QApplication.processEvents()
    assert ed.tool_strip.iconSize().width() == touch.TOUCH.icon_px
    assert ed.action_bar.iconSize().width() == touch.TOUCH.icon_px
    big = [b.sizeHint() for b in _strip_buttons(ed)]
    assert min(s.height() for s in big) >= 48 and min(s.width() for s in big) >= 48
    ed.set_touch_mode(False)
    QApplication.processEvents()
    again = [b.sizeHint() for b in _strip_buttons(ed)]
    assert [s.height() for s in again] == [s.height() for s in small]
    ed.close()


def test_layers_panel_touch_mode(ed):
    from PySide6.QtWidgets import QToolButton
    from lumacut_canvas.layers_panel import LayersPanel
    panel = LayersPanel(ed.document, ed.undo_stack)
    panel.show()
    QApplication.processEvents()
    assert panel.list.item(0).sizeHint().height() == 46
    panel.set_touch_mode(True)
    QApplication.processEvents()
    assert panel.property("touch") == "true"
    assert panel.list.item(0).sizeHint().height() == 56
    buttons = panel.findChildren(QToolButton)
    assert buttons and min(b.sizeHint().height() for b in buttons if b.isVisible()) >= 40
    assert panel.name.sizeHint().height() >= 34
    panel.set_touch_mode(False)
    assert panel.list.item(0).sizeHint().height() == 46
    panel.close()


# --- Schritt 5: Fangbereich und Trefferpriorität --------------------------
def test_hit_tolerance_is_screen_pixels_and_grows_in_touch_mode(ed):
    lid = _rect(ed, 20, 50, 100, 0, kind="line")
    ed.view.set_zoom(4.0)
    for zoom in (4.0, 16.0):
        ed.view.set_zoom(zoom)
        px = ed.view.px_per_mm
        near = QPointF(60, 50 + 3.5 / px)    # 3,5 px neben der Linie
        mid = QPointF(60, 50 + 9.0 / px)     # 9 px daneben
        far = QPointF(60, 50 + 15.0 / px)    # 15 px daneben
        ed.set_touch_mode(False)
        assert ed.scene.editable_shape_at(near) == lid
        assert ed.scene.editable_shape_at(mid) is None
        ed.set_touch_mode(True)
        assert ed.scene.editable_shape_at(mid) == lid
        assert ed.scene.editable_shape_at(far) is None
        assert 10 <= touch.TOUCH.hit_tolerance_px <= 14


def test_hit_priority_prefers_smaller_object_and_outline(ed):
    ed.set_touch_mode(True)
    small = _rect(ed, 40, 40, 10, 10)          # unten
    big = _rect(ed, 0, 0, 100, 100)            # oben, deckt small ab
    # Im kleinen Objekt (beide nur innen getroffen): das kleinere gewinnt.
    assert ed.scene.editable_shape_at(QPointF(45, 45)) == small
    # Auf dem Umriss des großen (weit weg vom kleinen): das große.
    assert ed.scene.editable_shape_at(QPointF(100, 60)) == big
    # Eine dünne Linie unter einer Fläche ist knapp daneben noch greifbar.
    line = _rect(ed, 10, 80, 30, 0, kind="line")
    px = ed.view.px_per_mm
    assert ed.scene.editable_shape_at(QPointF(25, 80 + 8 / px)) == line
    # Innen in der großen Fläche, fern von allem anderen: die große.
    assert ed.scene.editable_shape_at(QPointF(75, 30)) == big


def test_hit_priority_topmost_wins_for_equal_objects(ed):
    a = _rect(ed, 10, 10, 30, 30)
    b = _rect(ed, 12, 12, 30, 30)  # gleich groß, oben
    assert ed.scene.editable_shape_at(QPointF(25, 25)) == b
    assert ed.scene.editable_shape_at(QPointF(10, 25)) == a  # nur a im Umriss-Fangbereich (b: 8 px weg)
