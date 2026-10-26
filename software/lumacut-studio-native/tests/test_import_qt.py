"""Import im Hauptfenster: Menü Datei, Strg+I, Drag & Drop, Bildeinstellungen, Undo."""
from __future__ import annotations

import pytest

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="10mm" viewBox="0 0 20 10">'
       '<rect x="0" y="0" width="20" height="10"/><circle cx="5" cy="5" r="2"/></svg>')


@pytest.fixture()
def win(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    yield w
    w.canvas.undo_stack.setClean()
    w.close()


def _png(tmp_path):
    from PySide6.QtGui import QColor, QImage
    img = QImage(50, 20, QImage.Format_RGB32)
    img.fill(QColor(0, 0, 0))
    img.setDotsPerMeterX(round(254 / 0.0254))
    img.setDotsPerMeterY(round(254 / 0.0254))
    p = tmp_path / "foto.png"
    img.save(str(p))
    return p


def test_file_menu_and_shortcut(win):
    menus = [a.text() for a in win.menuBar().actions()]
    assert menus[0] == "&Datei" and "&Material" in menus
    texts = [a.text() for a in win.import_tools.menu.actions() if a.text()]
    assert texts[:4] == ["Neu", "Öffnen …", "Speichern", "Speichern unter …"]
    assert "Importieren …" in texts and "Bildeinstellungen …" in texts
    assert win.import_tools.import_action.shortcut().toString() == "Ctrl+I"


def test_svg_import_is_one_undo_step(win, tmp_path):
    p = tmp_path / "a.svg"
    p.write_text(SVG)
    ed = win.canvas
    ids = win.import_tools.import_path(p)
    assert len(ids) == 2 and ed.selection == ids
    assert ed.undo_stack.undoText() == "Importieren"
    ed.undo_stack.undo()
    assert not ed.document.shapes
    ed.undo_stack.redo()
    assert len(ed.document.shapes) == 2


def test_locked_layer_and_errors(win, tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x")
    assert win.import_tools.import_path(p) == []
    assert "nicht unterstützt" in win.import_tools.last_error
    win.canvas.document.active_layer.locked = True
    q = tmp_path / "a.svg"
    q.write_text(SVG)
    assert win.import_tools.import_path(q) == []
    assert "gesperrt" in win.import_tools.last_error


def test_drop_imports_at_position_and_opens_projects(win, tmp_path):
    p = tmp_path / "a.svg"
    p.write_text(SVG)
    win.import_tools.drop_paths([p], (100.0, 100.0))
    b = win.canvas.document.shapes[0].bounds()
    assert (b.x, b.y) == pytest.approx((90, 95))
    proj = tmp_path / f"p.lumacut.json"
    win.canvas.save_file(proj)
    win.canvas.document.shapes.clear()
    win.import_tools.drop_paths([proj], None)
    assert len(win.canvas.document.shapes) == 2 and win.canvas.file_path == proj


def test_drop_event_filter_accepts_files(win, tmp_path):
    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    p = tmp_path / "a.svg"
    p.write_text(SVG)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p))])
    vp = win.canvas.view.viewport()
    enter = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    assert win.import_tools.eventFilter(vp, enter) and enter.isAccepted()
    drop = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    assert win.import_tools.eventFilter(vp, drop)
    assert len(win.canvas.document.shapes) == 2
    bad = QMimeData()
    bad.setUrls([QUrl.fromLocalFile(str(tmp_path / "x.exe"))])
    e2 = QDragEnterEvent(QPoint(1, 1), Qt.CopyAction, bad, Qt.LeftButton, Qt.NoModifier)
    assert not win.import_tools.eventFilter(vp, e2)


def test_image_import_settings_undo_save_and_send(win, tmp_path, monkeypatch):
    from lumacut_canvas.model import ImageSettings
    from _pi_guard import pi_check
    ed = win.canvas
    ids = win.import_tools.import_path(_png(tmp_path))
    sh = ed.document.shape(ids[0])
    assert sh.kind == "image" and (sh.geom.w, sh.geom.h) == pytest.approx((5, 2))
    assert win.import_tools.image_action.isEnabled()
    assert win.import_tools.edit_image_settings(settings=ImageSettings(mode="threshold", line_interval_mm=0.2))
    assert ed.document.shape(ids[0]).image.settings.mode == "threshold"
    assert ed.undo_stack.undoText() == "Bildeinstellungen"
    ed.undo_stack.undo()
    assert ed.document.shape(ids[0]).image.settings.mode == "floyd"
    ed.undo_stack.redo()
    # Speichern/Laden behält Bild + Einstellungen
    proj = tmp_path / "bild.lumacut.json"
    ed.save_file(proj)
    ed.load_file(proj)
    s2 = ed.document.shapes[0]
    assert s2.kind == "image" and s2.image.settings.line_interval_mm == 0.2
    sent = []
    monkeypatch.setattr(win.machine_panel, "send_gcode", lambda n, g, start=False: sent.append(g))
    win._send_canvas_job()
    assert sent and "; IMAGE" in sent[0]
    pi_check(sent[0])
    # Rahmen umfasst das Bild
    assert "G0" in win.job_tools.frame_program()


def test_image_dialog_roundtrip(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    st = ImageSettings(mode="depth3d", depth_levels=10, z_step_mm=0.5, line_interval_mm=0.2)
    dlg = ImageSettingsDialog(st, 10.0, 100)
    assert dlg.settings() == st.normalized()
    assert dlg.levels.isEnabled() and not dlg.threshold.isEnabled()
    assert "3 mm" in dlg.hint.text()  # 0.5 * 9 = 4.5 mm > 3 mm
    assert "127 DPI" in dlg.dpi_label.text() and "254 DPI" in dlg.dpi_label.text()
    dlg.mode.setCurrentIndex(0)
    assert dlg.threshold.isEnabled() and not dlg.levels.isEnabled()


def test_double_click_opens_image_settings(win, tmp_path, monkeypatch):
    from PySide6.QtCore import QPointF
    ids = win.import_tools.import_path(_png(tmp_path))
    called = []
    win.canvas.image_settings_handler = lambda sid: called.append(sid)
    sh = win.canvas.document.shape(ids[0])
    c = sh.geom.bounds()
    win.canvas.tools.double_click(QPointF(c.x + c.w / 2, c.y + c.h / 2))
    assert called == ids
