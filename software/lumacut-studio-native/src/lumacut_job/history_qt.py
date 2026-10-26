"""Qt: Auftragsverlauf („Verlauf…“) und „G-Code speichern…“.

:func:`attach_history` legt jeden über ``machine_panel.send_gcode`` gesendeten
Auftrag im :class:`~lumacut_job.history.JobHistory` ab (Canvas, Ablauf, Relief,
Materialtest – egal wer sendet). Der Dialog sendet einen Eintrag erneut
(ohne Start; gestartet wird wie immer über „Start“) oder speichert ihn als Datei.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout)

from .estimate import estimate_gcode
from .history import HistoryEntry, JobHistory


def default_dir() -> Path:
    env = os.environ.get("LUMACUT_HISTORY_DIR")
    if env:
        return Path(env)
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base or Path.home() / ".lumacut") / "history"


def _summary(gcode: str) -> str:
    try:
        return estimate_gcode(gcode).summary()
    except Exception:  # Schätzung ist nur Beiwerk
        return ""


def attach_history(machine_panel, history: JobHistory):
    """``send_gcode`` des Panels umhüllen; gibt die ursprüngliche Methode zurück."""
    original = machine_panel.send_gcode

    def send_gcode(name, gcode, start=False):
        result = original(name, gcode, start=start)
        if getattr(machine_panel, "_client", None) is not None:
            try:
                history.record(name, gcode, _summary(gcode))
            except OSError:
                pass
        return result

    machine_panel.send_gcode = send_gcode
    return original


def save_gcode_file(parent, gcode: str, suggested: str) -> str:
    path, _ = QFileDialog.getSaveFileName(parent, "G-Code speichern", suggested,
                                          "G-Code (*.gcode *.gc *.nc)")
    if not path:
        return ""
    Path(path).write_text(gcode, encoding="utf-8", newline="\n")
    return path


class HistoryDialog(QDialog):
    def __init__(self, history: JobHistory, send, parent=None):
        super().__init__(parent)
        self.history = history
        self.send = send
        self.setWindowTitle("Auftragsverlauf")
        self.resize(560, 400)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Zuletzt gesendete Aufträge (neueste zuerst). „Erneut senden“ "
                             "lädt den Auftrag auf den Pi; gestartet wird über „Start“."))
        self.list = QListWidget()
        lay.addWidget(self.list)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.resend_btn = QPushButton("Erneut senden")
        self.save_btn = QPushButton("Als Datei speichern …")
        self.remove_btn = QPushButton("Entfernen")
        for b in (self.resend_btn, self.save_btn, self.remove_btn):
            bb.addButton(b, QDialogButtonBox.ActionRole)
        bb.rejected.connect(self.reject)
        self.resend_btn.clicked.connect(self.resend)
        self.save_btn.clicked.connect(self.save)
        self.remove_btn.clicked.connect(self.remove)
        self.list.itemDoubleClicked.connect(lambda _item: self.resend())
        self.list.currentRowChanged.connect(lambda _r: self._sync())
        lay.addWidget(bb)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        for e in self.history.entries():
            item = QListWidgetItem(e.label())
            item.setData(Qt.UserRole, e)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.list.addItem("Noch keine Aufträge gesendet")
            self.list.item(0).setFlags(Qt.NoItemFlags)
        self._sync()

    def current(self) -> HistoryEntry | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _sync(self) -> None:
        on = self.current() is not None
        for b in (self.resend_btn, self.save_btn, self.remove_btn):
            b.setEnabled(on)

    def resend(self) -> bool:
        e = self.current()
        if e is None:
            return False
        self.send(e.name, self.history.load(e))
        return True

    def save(self, path: str | None = None) -> str:
        e = self.current()
        if e is None:
            return ""
        if path is None:
            return save_gcode_file(self, self.history.load(e), e.name)
        Path(path).write_text(self.history.load(e), encoding="utf-8", newline="\n")
        return path

    def remove(self, confirm: bool = True) -> bool:
        e = self.current()
        if e is None:
            return False
        if confirm and QMessageBox.question(self, "Verlauf", f"„{e.name}“ aus dem Verlauf "
                                            "entfernen?") != QMessageBox.Yes:
            return False
        self.history.remove(e)
        self.refresh()
        return True
