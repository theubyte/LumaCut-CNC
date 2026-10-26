"""Touch-Bedienung des Canvas (Surface Pro): Griffgrößen, Fangbereiche,
Pinch-Zoom, Touch-Pan, Touch-Modus-Schalter – alles headless.

Touch-Ereignisse werden mit einem eigenen, *nicht* global registrierten
QPointingDevice erzeugt (``QTest.createTouchDevice`` würde ein Gerät
registrieren und damit in späteren Tests die automatische Erkennung auslösen).
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, QSettings, Qt

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
