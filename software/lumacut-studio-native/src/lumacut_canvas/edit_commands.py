"""Undo-Befehle für Objekte, die als Ganzes ersetzt werden (Boole-Operationen,
Versatz, Text in Pfade, Knotenbearbeitung, Schriftschnitt).

Eigenes Modul neben :mod:`commands`, damit Pfad-/Knotenfunktionen ohne
Eingriff in die bestehenden Befehle auskommen.
"""

from __future__ import annotations

from PySide6.QtGui import QUndoCommand

from .model import Document, Shape


class ReplaceShapesCommand(QUndoCommand):
    """``remove`` (IDs) entfernen und ``add`` an der Stelle des untersten
    entfernten Objekts einfügen. ``remove`` darf leer sein (nur hinzufügen,
    oben auf dem Stapel)."""

    def __init__(self, doc: Document, remove: list[str], add: list[Shape], text: str) -> None:
        super().__init__(text)
        self.doc = doc
        self.remove = list(remove)
        self.add = list(add)
        self._removed: list[tuple[int, Shape]] = []

    def redo(self) -> None:
        d = self.doc
        d.begin_batch()
        try:
            order = sorted(self.remove, key=lambda i: d.shapes.index(d.shape(i)), reverse=True)
            # Von oben nach unten entfernen: jeder Index ist der ursprüngliche.
            self._removed = [d.remove_shape(i) for i in order][::-1]
            at = self._removed[0][0] if self._removed else None
            for k, s in enumerate(self.add):
                d.add_shape(s, None if at is None else at + k)
        finally:
            d.end_batch()

    def undo(self) -> None:
        d = self.doc
        d.begin_batch()
        try:
            for s in self.add:
                d.remove_shape(s.id)
            for idx, s in self._removed:   # aufsteigend: ursprüngliche Indizes
                d.add_shape(s, idx)
        finally:
            d.end_batch()


class ReplaceShapeCommand(QUndoCommand):
    """Ein Objekt durch eine geänderte Kopie mit derselben ID ersetzen
    (Knoten verschieben, Kurve/Linie, öffnen/schließen, Fett/Kursiv).
    Aufeinanderfolgende Schritte mit demselben ``merge_key`` verschmelzen."""

    _ID = 1101

    def __init__(self, doc: Document, new: Shape, text: str, merge_key: str | None = None) -> None:
        super().__init__(text)
        self.doc = doc
        self.old = doc.shape(new.id).copy()
        self.new = new.copy()
        self.merge_key = merge_key

    def _put(self, s: Shape) -> None:
        d = self.doc
        d.begin_batch()
        try:
            idx, _ = d.remove_shape(s.id)
            d.add_shape(s.copy(), idx)
        finally:
            d.end_batch()

    def redo(self) -> None:
        self._put(self.new)

    def undo(self) -> None:
        self._put(self.old)

    def id(self) -> int:  # noqa: A003 - Qt API
        return self._ID if self.merge_key else -1

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802 - Qt API
        if not isinstance(other, ReplaceShapeCommand) or other.merge_key != self.merge_key:
            return False
        if other.new.id != self.new.id:
            return False
        self.new = other.new
        return True
