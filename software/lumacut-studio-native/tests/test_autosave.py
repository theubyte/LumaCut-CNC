"""Autosave + Wiederherstellung nach Absturz (eigener Ordner, Rückfrage injiziert)."""
from __future__ import annotations

import json

import pytest


@pytest.fixture()
def editor(qapp):
    from lumacut_canvas.editor import CanvasEditor
    ed = CanvasEditor()
    yield ed
    ed.undo_stack.setClean()


def _add_rect(ed, x=10):
    from lumacut_canvas import Geometry, Shape
    from lumacut_canvas.commands import AddShapesCommand
    doc = ed.document
    s = Shape("rect", Geometry(x, 20, 30, 15), doc.active_layer_id)
    ed.undo_stack.push(AddShapesCommand(doc, [s], "Rechteck"))
    return s


def test_saves_only_when_dirty_and_changed(editor, tmp_path):
    from lumacut_session import Autosave
    a = Autosave(editor, tmp_path, interval_ms=10_000_000)
    assert not a.save_now()                       # sauber → nichts
    _add_rect(editor)
    assert a.save_now() and a.project_path.exists()
    meta = json.loads(a.meta_path.read_text(encoding="utf-8"))
    assert meta["file_path"] == "" and meta["saved_at"] > 0
    assert not a.save_now()                       # unverändert → nicht erneut
    _add_rect(editor, 50)
    assert a.save_now()
    from lumacut_canvas.document_io import load_document
    assert len(load_document(a.project_path).shapes) == 2
    a.shutdown()


def test_save_and_undo_to_clean_discard_backup(editor, tmp_path):
    from lumacut_session import Autosave
    a = Autosave(editor, tmp_path / "auto", interval_ms=10_000_000)
    _add_rect(editor)
    assert a.save_now()
    editor.save_file(tmp_path / "p.lumacut.json")  # Speichern → Sicherung weg
    assert not a.project_path.exists() and not a.meta_path.exists()
    _add_rect(editor, 60)
    assert a.save_now()
    editor.undo_stack.undo()                       # zurück auf gespeicherten Stand
    assert editor.undo_stack.isClean() and not a.project_path.exists()
    a.shutdown()


def test_crash_recovery_restores_and_marks_unsaved(qapp, tmp_path):
    from lumacut_canvas.editor import CanvasEditor
    from lumacut_session import Autosave
    d = tmp_path / "auto"
    crashed = CanvasEditor()
    crashed.file_path = tmp_path / "werkstueck.lumacut.json"
    a = Autosave(crashed, d, interval_ms=10_000_000)
    _add_rect(crashed)
    _add_rect(crashed, 80)
    assert a.save_now()
    a.timer.stop()
    a.lock.unlock()        # Prozess „abgestürzt“: Sperre weg, Sicherung bleibt

    fresh = CanvasEditor()
    questions = []
    b = Autosave(fresh, d, interval_ms=10_000_000,
                 ask=lambda title, text: questions.append(text) or True)
    assert len(b.orphans()) == 1
    assert b.check_recovery()
    assert "werkstueck.lumacut.json" in questions[0]
    assert len(fresh.document.shapes) == 2
    assert fresh.file_path.name == "werkstueck.lumacut.json"
    assert not fresh.undo_stack.isClean()          # Speichern wird angeboten
    assert b.project_path.exists()                 # sofort eigene Sicherung
    assert b.orphans() == [] and not a.project_path.exists()
    fresh.undo_stack.setClean()
    b.shutdown()


def test_declined_recovery_discards_and_running_session_is_not_offered(qapp, tmp_path):
    from lumacut_canvas.editor import CanvasEditor
    from lumacut_session import Autosave
    d = tmp_path / "auto"
    other = CanvasEditor()
    running = Autosave(other, d, interval_ms=10_000_000)
    _add_rect(other)
    assert running.save_now()
    fresh = CanvasEditor()
    asked = []
    b = Autosave(fresh, d, interval_ms=10_000_000, ask=lambda *_: asked.append(1) or False)
    assert b.orphans() == [] and not b.check_recovery() and asked == []   # läuft noch
    running.timer.stop()
    running.lock.unlock()
    assert not b.check_recovery() and asked == [1]
    assert fresh.document.shapes == [] and not running.project_path.exists()
    other.undo_stack.setClean()
    b.shutdown()


def test_timer_and_main_window_close_removes_backup(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    monkeypatch.setenv("LUMACUT_AUTOSAVE_DIR", str(tmp_path / "auto"))
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    a = w.autosave
    assert a.dir == tmp_path / "auto" and a.timer.interval() == 60_000
    _add_rect(w.canvas)
    a.timer.setInterval(10)
    import time
    from PySide6.QtWidgets import QApplication
    end = time.monotonic() + 5
    while time.monotonic() < end and not a.project_path.exists():
        QApplication.processEvents()
        time.sleep(0.01)
    assert a.project_path.exists()
    w.canvas.undo_stack.setClean()
    w.close()
    assert not a.project_path.exists() and not a.timer.isActive()
