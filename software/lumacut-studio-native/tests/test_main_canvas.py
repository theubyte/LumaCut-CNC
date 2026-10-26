"""Hauptfenster mit eingebautem Canvas (offscreen, ohne Pi)."""

import pytest


def test_main_window_hosts_canvas(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    from lumacut_canvas.model import Geometry, Shape

    win = main.LumaCutStudio()
    win.show()
    qapp.processEvents()
    assert win.layers_panel.list.count() == len(win.canvas.document.layers)
    sent = []
    monkeypatch.setattr(win.machine_panel, "send_gcode", lambda n, g, start=False: sent.append((n, g, start)))
    win._send_canvas_job()  # leer -> nur Statusmeldung
    assert sent == []
    win.canvas.document.add_shape(Shape("rect", Geometry(0, 0, 10, 10), win.canvas.document.active_layer_id))
    win._send_canvas_job()
    assert sent and sent[0][0] == "canvas.gcode" and sent[0][2] is False and "M3 I" in sent[0][1]
    win.canvas.cursorMoved.emit(12.34, 5.0)
    assert "12.3" in win.cursor_label.text()
    win.canvas.undo_stack.setClean()
    win.close()
