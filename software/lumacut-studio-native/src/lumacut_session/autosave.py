"""Automatisches Sichern und Wiederherstellen nach einem Absturz.

* Alle ``interval_ms`` (Standard 60 s) wird das Projekt nach
  ``<AppData>/LumaCut/LumaCut Studio/autosave/`` gesichert – nur wenn es
  ungespeicherte Änderungen hat und sich seit der letzten Sicherung geändert hat.
  Schreiben ist atomar (``save_document``: temporäre Datei + Umbenennen).
* Speichern (Undo-Stapel sauber), „Neu“, „Öffnen“ oder ein normales Beenden
  löschen die Sicherung.
* Eine Sperrdatei (``QLockFile``) zeigt, ob die Sitzung noch läuft. Findet der
  Start eine Sicherung, deren Sitzung nicht mehr läuft (Absturz, Stromausfall),
  wird die Wiederherstellung angeboten. Laufen zwei Studios gleichzeitig,
  sichert jedes in eine eigene Datei (``autosave-<pid>``) und nur verwaiste
  Sicherungen werden angeboten.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QLockFile, QObject, QStandardPaths, QTimer
from PySide6.QtWidgets import QMessageBox

from lumacut_canvas.document_io import load_into, save_document

DEFAULT_INTERVAL_MS = 60_000


def default_dir() -> Path:
    """``LUMACUT_AUTOSAVE_DIR`` (Tests/portable) oder der AppData-Ordner."""
    env = os.environ.get("LUMACUT_AUTOSAVE_DIR")
    if env:
        return Path(env)
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base or Path.home() / ".lumacut") / "autosave"


class Autosave(QObject):
    def __init__(self, editor: Any, directory: Optional[Path] = None, *,
                 interval_ms: int = DEFAULT_INTERVAL_MS,
                 ask: Optional[Callable[[str, str], bool]] = None, parent: Optional[QObject] = None):
        super().__init__(parent or editor)
        self.ed = editor
        self.dir = Path(directory) if directory else default_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ask = ask or self._ask
        self.tag = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.project_path = self.dir / f"autosave-{self.tag}.lumacut.json"
        self.meta_path = self.dir / f"autosave-{self.tag}.meta.json"
        self.lock = QLockFile(str(self.dir / f"autosave-{self.tag}.lock"))
        self.lock.setStaleLockTime(0)
        self.lock.tryLock(0)
        self._dirty_since_save = False
        self.last_saved: Optional[float] = None
        self.last_error = ""
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.save_now)
        self.timer.start()
        editor.documentChanged.connect(self._on_changed)
        editor.undo_stack.indexChanged.connect(self._on_changed)
        editor.undo_stack.cleanChanged.connect(self._on_clean_changed)
        editor.fileChanged.connect(lambda *_: self._on_clean_changed(editor.undo_stack.isClean()))

    # --------------------------------------------------------------- Sichern
    def _on_changed(self, *_args) -> None:
        # Beim Push feuert documentChanged vor dem Indexwechsel (Stapel wirkt noch
        # „sauber“) – daher immer merken; save_now prüft den Stapel selbst.
        self._dirty_since_save = True

    def _on_clean_changed(self, clean: bool) -> None:
        if clean:
            self.discard()

    def _gesture_running(self) -> bool:
        tools = getattr(self.ed, "tools", None)
        return bool(getattr(tools, "_preview_id", None))

    def save_now(self, force: bool = False) -> bool:
        """Sichern, wenn nötig. True, wenn geschrieben wurde."""
        if self.ed.undo_stack.isClean() and not force:
            return False
        if not (self._dirty_since_save or force) or self._gesture_running():
            return False
        try:
            save_document(self.ed.document, self.project_path)
            fp = getattr(self.ed, "file_path", None)
            self.meta_path.write_text(json.dumps({
                "file_path": str(fp) if fp else "",
                "saved_at": time.time(),
                "pid": os.getpid(),
                "lock": self.lock.fileName(),
            }, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            self.last_error = f"Autosave fehlgeschlagen: {exc}"
            return False
        self._dirty_since_save = False
        self.last_saved = time.time()
        self.last_error = ""
        return True

    def discard(self) -> None:
        """Eigene Sicherung löschen (gespeichert, verworfen, normal beendet)."""
        for p in (self.project_path, self.meta_path):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        self._dirty_since_save = False

    def shutdown(self) -> None:
        """Normales Beenden: Timer stoppen, Sicherung + Sperre entfernen."""
        self.timer.stop()
        self.discard()
        self.lock.unlock()

    # -------------------------------------------------------- Wiederherstellen
    def orphans(self) -> list[tuple[Path, dict]]:
        """Sicherungen beendeter/abgestürzter Sitzungen, neueste zuerst."""
        out = []
        for meta in self.dir.glob("autosave-*.meta.json"):
            if meta == self.meta_path:
                continue
            project = meta.with_name(meta.name.replace(".meta.json", ".lumacut.json"))
            if not project.exists():
                continue
            try:
                info = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = {}
            lock = QLockFile(str(meta.with_name(meta.name.replace(".meta.json", ".lock"))))
            lock.setStaleLockTime(0)
            if not lock.tryLock(0):
                continue  # Sitzung läuft noch (zweites Studio)
            lock.unlock()
            out.append((project, info))
        out.sort(key=lambda t: t[1].get("saved_at", 0), reverse=True)
        return out

    def check_recovery(self) -> bool:
        """Beim Start: verwaiste Sicherung anbieten. True, wenn wiederhergestellt."""
        orphans = self.orphans()
        if not orphans:
            return False
        project, info = orphans[0]
        name = Path(info["file_path"]).name if info.get("file_path") else "unbenanntes Projekt"
        when = time.strftime("%d.%m.%Y %H:%M", time.localtime(info.get("saved_at", project.stat().st_mtime)))
        restored = False
        if self.ask("Projekt wiederherstellen?",
                    f"LumaCut Studio wurde nicht normal beendet. Automatische Sicherung von "
                    f"„{name}“ ({when}) wiederherstellen?\n\nNein verwirft die Sicherung."):
            try:
                load_into(self.ed.document, project)
            except (OSError, ValueError, KeyError) as exc:
                self.last_error = f"Wiederherstellung fehlgeschlagen: {exc}"
                return False
            fp = info.get("file_path") or ""
            self.ed.file_path = Path(fp) if fp else None
            self.ed.undo_stack.clear()
            self.ed.undo_stack.resetClean()   # gilt als ungespeichert → Speichern anbieten
            self.ed.set_selection([])
            self.ed.fileChanged.emit(self.ed.title())
            self.ed.notify(f"Wiederhergestellt: {name} – bitte speichern")
            self._dirty_since_save = True
            self.save_now()                    # sofort in die eigene Sicherung übernehmen
            restored = True
        for p, _ in orphans:  # alle verwaisten Sicherungen aufräumen
            for f in (p, p.with_name(p.name.replace(".lumacut.json", ".meta.json")),
                      p.with_name(p.name.replace(".lumacut.json", ".lock"))):
                try:
                    f.unlink()
                except OSError:
                    pass
        return restored

    def _ask(self, title: str, text: str) -> bool:
        return QMessageBox.question(self.ed, title, text) == QMessageBox.StandardButton.Yes


def install_autosave(window: Any, directory: Optional[Path] = None, *, recover: bool = True,
                     ask: Optional[Callable[[str, str], bool]] = None) -> Autosave:
    """Autosave für das Hauptfenster; Wiederherstellung kurz nach dem Start anbieten."""
    auto = Autosave(window.canvas, directory, ask=ask, parent=window)
    window.autosave = auto
    if recover:
        QTimer.singleShot(0, auto.check_recovery)
    return auto
