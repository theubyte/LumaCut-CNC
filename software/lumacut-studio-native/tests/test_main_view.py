"""Aufgeräumte Hauptansicht (Vereinfachung 2026-10-26, §1/§3): Material · Design ·
Start, „Mehr“ standardmäßig zu, große Knöpfe, Kamera-Scan optional, Ein-Klick-Start."""
from __future__ import annotations

import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))


def _wait(pred, timeout=10.0):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    return pred()


@pytest.fixture()
def make_win(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    monkeypatch.delenv("LUMACUT_KEY", raising=False)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    wins = []

    def make(w=1280, h=720):
        win = main.LumaCutStudio()
        win.import_tools.interactive = False
        win.machine_panel._confirm = lambda *_: True
        win.scan_panel.ask = False
        win.resize(w, h)
        win.show()
        _wait(lambda: True, 0.05)
        wins.append(win)
        return win
    yield make
    for win in wins:
        win.scan_panel.shutdown()
        win.machine_panel.shutdown()
        win.canvas.undo_stack.setClean()
        win.close()


def _visible_in(win, w):
    return w.isVisibleTo(win)


def test_main_view_three_big_actions_and_more_closed(make_win):
    win = make_win()
    a = win.main_actions
    for b in (a.material_button, a.design_button, a.start_button):
        assert _visible_in(win, b)
        assert b.height() >= 48 and b.minimumHeight() >= 48, (b.text(), b.height())
    assert [b.text().split()[-1] for b in (a.material_button, a.design_button, a.start_button)] == \
        ["Material", "Design", "Start"]
    assert a.scan_button.height() >= 48 and win.more_toggle.height() >= 48
    # Material-Schnellwahl (Material + Dicke) bleibt sichtbar
    assert win.material_group.title() == "Material" and _visible_in(win, win.material_group)
    quick = win.material_tools.quick
    assert quick is not None and _visible_in(win, quick.thickness) and _visible_in(win, quick.combo)
    # Erweitertes zu
    assert not win.more_toggle.isChecked() and not _visible_in(win, win.more_panel)
    assert not _visible_in(win, win.job_tools.toolbar)
    assert not _visible_in(win, win.layers_panel.params)
    assert not _visible_in(win, win.layers_panel.fill_box)
    assert not _visible_in(win, win.scan_panel) and not _visible_in(win, win.machine_panel)


def test_more_toggle_shows_everything_advanced(make_win):
    win = make_win()
    win.more_toggle.click()
    _wait(lambda: True, 0.05)
    assert win.more_toggle.text() == "Mehr ▾"
    for w in (win.more_panel, win.job_tools.toolbar, win.layers_panel.params, win.layers_panel.fill_box,
              win.scan_panel, win.machine_panel, win.workflow_panel):
        assert _visible_in(win, w), w
    col = win.workflow_panel.parentWidget().parentWidget()
    assert col is win.more_panel
    win.more_toggle.click()
    assert not _visible_in(win, win.more_panel) and win.more_toggle.text() == "Mehr ▸"


def test_job_tool_shortcuts_reachable_while_toolbar_hidden(make_win):
    win = make_win()
    acts = [a for a in win.job_tools.toolbar.actions() if not a.isSeparator()]
    assert acts and all(a in win.actions() for a in acts)
    assert set(win.main_view.job_menu.actions()) == set(acts)


@pytest.mark.parametrize("size", [(1024, 600), (1280, 720), (1368, 912), (800, 560)])
@pytest.mark.parametrize("more", [False, True])
def test_main_view_not_clipped_small_screens(make_win, size, more):
    from PySide6.QtWidgets import QApplication
    win = make_win(*size)
    win.main_view.set_more(more)
    for _ in range(5):
        QApplication.processEvents()
    sc = win.right_scroll
    content = sc.widget()
    if size[0] >= 1024 or not more:
        assert not sc.horizontalScrollBar().isVisible()
    else:  # sehr schmal + „Mehr“ offen: scrollen statt abschneiden
        assert (content.minimumSizeHint().width() <= sc.viewport().width()
                or sc.horizontalScrollBar().isVisible())
        return
    for b in (win.main_actions.material_button, win.main_actions.start_button, win.more_toggle):
        right = b.mapTo(content, b.rect().topRight()).x()
        assert right <= sc.viewport().width() + 1, (size, b.text())


def test_design_menu_offers_import_text_shapes(make_win):
    win = make_win()
    texts = [a.text() for a in win.main_view.design_menu.actions() if a.text()]
    assert texts[0].startswith("Importieren")
    for t in ("Text", "Rechteck", "Ellipse"):
        assert t in texts
    rect = next(a for a in win.main_view.design_menu.actions() if a.text() == "Rechteck")
    rect.trigger()
    assert win.canvas.tools.tool.value == "rect"


def test_material_button_opens_library(make_win, monkeypatch):
    win = make_win()
    calls = []
    monkeypatch.setattr(win.material_tools, "open", lambda *a, **k: calls.append(1))
    win.main_actions.material_button.click()
    assert calls == [1]


def test_camera_scan_button_calls_scan_entry_point(make_win, monkeypatch):
    win = make_win()
    calls = []
    monkeypatch.setattr(win.scan_panel, "start_scan", lambda: calls.append(1) or True)
    win.main_actions.scan_button.click()
    assert calls == [1]


def test_start_without_connection_explains(make_win):
    win = make_win()
    win.main_actions.start_button.click()
    assert "Nicht mit der Maschine verbunden" in win.statusBar().currentMessage()


def test_one_click_start_uploads_then_autoruns(make_win):
    from fake_pi import FakePi
    from lumacut_canvas import Geometry, Shape
    win = make_win()
    mp = win.machine_panel
    doc = win.canvas.document
    doc.add_shape(Shape("rect", Geometry(60, 60, 80, 40), doc.active_layer_id))
    win.canvas.documentChanged.emit()
    with FakePi() as pi:
        mp.url_edit.setText(pi.url)
        win.main_actions.connect_button.click()
        assert _wait(lambda: mp.connection_state == "connected")
        assert _wait(lambda: not win.main_actions.connect_button.isVisibleTo(win))
        assert win.main_actions.start_button.isEnabled()
        win.main_actions.start_button.click()

        def ops():
            with pi.lock:
                return [r.get("form", {}).get("op") for r in pi.requests if r["path"] == "/api/action"]
        assert _wait(lambda: "autorun" in ops()), ops()
        assert pi.uploads == ["canvas.gcode"]
        assert win.main_view.starter.pending is None
        mp.disconnect_from_pi()
