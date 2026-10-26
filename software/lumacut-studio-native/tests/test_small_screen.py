"""Hauptfenster auf kleinen Bildschirmen (Surface Pro, 1024×600, 1280×720), offscreen."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect, QSettings
from PySide6.QtWidgets import QScrollArea, QToolButton

from lumacut_canvas import fit, touch


@pytest.fixture
def make_win(qapp, tmp_path, monkeypatch):
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    wins = []

    def make(w, h):
        win = main.LumaCutStudio()
        win.resize(w, h)
        win.show()
        for _ in range(3):
            qapp.processEvents()
        wins.append(win)
        return win
    yield make
    for win in wins:
        win.canvas.undo_stack.setClean()
        win.close()


def _not_clipped(area: QScrollArea) -> bool:
    content = area.widget()
    fits = content.minimumSizeHint().width() <= area.viewport().width()
    return fits or area.horizontalScrollBar().isVisible()


@pytest.mark.parametrize("size", [(1024, 600), (1280, 720), (1368, 912)])
def test_panels_fit_inside_small_windows(make_win, size):
    win = make_win(*size)
    assert win.width() == size[0]
    sp = win.splitter
    assert sum(sp.sizes()) + sp.handleWidth() * (sp.count() - 1) <= win.width()
    for w in (win.layers_panel, win.canvas, win.right_scroll):
        assert w.geometry().right() <= sp.width()
    # Seitenleisten: senkrecht scrollbar, Inhalt nicht abgeschnitten.
    for area in (win.right_scroll, win.layers_panel.scroll):
        assert isinstance(area, QScrollArea) and area.widgetResizable()
        assert _not_clipped(area)
    # Ab 1024 px braucht keine Seitenleiste einen waagerechten Bildlauf.
    assert not win.right_scroll.horizontalScrollBar().isVisible()
    assert not win.layers_panel.scroll.horizontalScrollBar().isVisible()
    # Canvas (inkl. Eigenschaftsleiste) passt, die Leiste scrollt notfalls.
    assert win.canvas.minimumSizeHint().width() <= win.canvas.width()
    assert _not_clipped(win.canvas.property_scroll)
    assert win.canvas.view.width() >= 200


def test_very_narrow_window_scrolls_instead_of_clipping(make_win):
    win = make_win(800, 560)
    assert win.width() == 800
    assert win.minimumSizeHint().width() <= 800 or win.minimumWidth() <= 800
    for area in (win.right_scroll, win.layers_panel.scroll, win.canvas.property_scroll):
        assert _not_clipped(area)


@pytest.mark.parametrize("touch_on", [False, True])
def test_tool_strip_buttons_at_least_44px(make_win, touch_on):
    win = make_win(1280, 720)
    win.canvas.set_touch_mode(touch_on, persist=False)
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    buttons = [b for b in win.canvas.tool_strip.findChildren(QToolButton) if b.defaultAction()]
    assert len(buttons) >= 7
    for b in buttons:
        assert b.width() >= 44 and b.height() >= 44, (b.defaultAction().text(), b.size())
    ys = sorted(b.y() for b in buttons)
    assert min(b - a for a, b in zip(ys, ys[1:])) >= 44 + 4  # Abstand zwischen Knöpfen


def test_small_screen_defaults_to_touch_mode(make_win, monkeypatch):
    monkeypatch.setattr(fit, "is_small_screen", lambda screen=None: True)
    win = make_win(1024, 600)
    assert win.canvas.touch_mode and win.layers_panel.touch_mode
    win.canvas.set_touch_mode(False)  # manuelle Wahl gewinnt
    assert not win.layers_panel.touch_mode


def test_large_screen_keeps_mouse_mode(make_win, monkeypatch):
    monkeypatch.setattr(fit, "is_small_screen", lambda screen=None: False)
    monkeypatch.setattr(touch, "has_touchscreen", lambda: False)
    win = make_win(1280, 720)
    assert not win.canvas.touch_mode


class _FakeScreen:
    def __init__(self, w, h):
        self._g = QRect(0, 0, w, h)

    def availableGeometry(self):  # noqa: N802
        return self._g


@pytest.mark.parametrize("avail", [(1368, 872), (1280, 680), (1024, 560), (2560, 1400)])
def test_default_window_size_fits_available_screen(avail):
    s = fit.default_window_size(_FakeScreen(*avail))
    assert s.width() <= avail[0] - 16 and s.height() <= avail[1] - 48
    assert s.width() <= 1400 and s.height() <= 900
    assert fit.is_small_screen(_FakeScreen(*avail)) == (avail[0] < 1500)
