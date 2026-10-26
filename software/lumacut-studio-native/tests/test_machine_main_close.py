"""Closing the main window while the Pi runs a job/frame asks first."""
import pytest


def test_close_is_ignored_while_machine_busy(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    win = main.LumaCutStudio()
    win.show()
    qapp.processEvents()
    shut = []
    monkeypatch.setattr(win.machine_panel, "shutdown", lambda: shut.append(True))
    monkeypatch.setattr(win.machine_panel, "confirm_close", lambda: False)
    win.close()
    qapp.processEvents()
    assert win.isVisible() and shut == []        # still open, Pi still watched
    monkeypatch.setattr(win.machine_panel, "confirm_close", lambda: True)
    win.canvas.undo_stack.setClean()
    win.close()
    qapp.processEvents()
    assert not win.isVisible() and shut == [True]
