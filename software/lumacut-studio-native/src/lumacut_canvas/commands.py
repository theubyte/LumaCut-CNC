"""Undo/Redo-Befehle (QUndoCommand) für alle Dokumentänderungen.

Jede Benutzeraktion wird genau ein Befehl auf dem QUndoStack. Werte, die
während eines Zugs live geändert werden (Verschieben/Skalieren mit der Maus),
werden vor ``push`` auf den Ausgangszustand zurückgesetzt; ``redo`` setzt dann
den Endzustand. Spinbox-Änderungen derselben Ebene/desselben Felds werden
über ``mergeWith`` zu einem Schritt zusammengefasst.
"""

from __future__ import annotations

from PySide6.QtGui import QUndoCommand

from .model import Document, Geometry, Layer, Shape

_ID_LAYER_ATTR = 1001
_ID_GEOMETRY = 1002


class AddShapesCommand(QUndoCommand):
    def __init__(self, doc: Document, shapes: list[Shape], text: str = "Objekt hinzufügen") -> None:
        super().__init__(text)
        self.doc = doc
        self.shapes = shapes

    def redo(self) -> None:
        self.doc.begin_batch()
        for s in self.shapes:
            self.doc.add_shape(s)
        self.doc.end_batch()

    def undo(self) -> None:
        self.doc.begin_batch()
        for s in self.shapes:
            self.doc.remove_shape(s.id)
        self.doc.end_batch()


class DeleteShapesCommand(QUndoCommand):
    def __init__(self, doc: Document, ids: list[str]) -> None:
        super().__init__("Löschen")
        self.doc = doc
        self.ids = ids
        self._removed: list[tuple[int, Shape]] = []

    def redo(self) -> None:
        self.doc.begin_batch()
        self._removed = [self.doc.remove_shape(i) for i in self.ids]
        self.doc.end_batch()

    def undo(self) -> None:
        self.doc.begin_batch()
        # Rückwärts einfügen, damit die ursprünglichen Indizes stimmen.
        for idx, s in reversed(self._removed):
            self.doc.add_shape(s, idx)
        self.doc.end_batch()


class SetGeometryCommand(QUndoCommand):
    """Neue Geometrie für ein oder mehrere Objekte (Verschieben, Skalieren, Zahlenfelder)."""

    def __init__(self, doc: Document, old: dict[str, Geometry], new: dict[str, Geometry],
                 text: str = "Geometrie ändern", mergeable: bool = False) -> None:
        super().__init__(text)
        self.doc = doc
        self.old = old
        self.new = new
        self.mergeable = mergeable

    def _apply(self, values: dict[str, Geometry]) -> None:
        self.doc.begin_batch()
        for sid, g in values.items():
            self.doc.set_geometry(sid, g.copy())
        self.doc.end_batch()

    def redo(self) -> None:
        self._apply(self.new)

    def undo(self) -> None:
        self._apply(self.old)

    def id(self) -> int:  # noqa: A003 - Qt API
        return _ID_GEOMETRY if self.mergeable else -1

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802 - Qt API
        if not isinstance(other, SetGeometryCommand) or not other.mergeable:
            return False
        if set(other.new) != set(self.new):
            return False
        self.new = other.new
        return True


class SetShapeLayerCommand(QUndoCommand):
    def __init__(self, doc: Document, ids: list[str], layer_id: str) -> None:
        super().__init__("Ebene zuweisen")
        self.doc = doc
        self.layer_id = layer_id
        self.old = {i: doc.shape(i).layer_id for i in ids}

    def redo(self) -> None:
        self.doc.begin_batch()
        for i in self.old:
            self.doc.set_shape_layer(i, self.layer_id)
        self.doc.end_batch()

    def undo(self) -> None:
        self.doc.begin_batch()
        for i, lid in self.old.items():
            self.doc.set_shape_layer(i, lid)
        self.doc.end_batch()


class SetTextCommand(QUndoCommand):
    def __init__(self, doc: Document, shape_id: str, text: str) -> None:
        super().__init__("Text ändern")
        self.doc = doc
        self.sid = shape_id
        self.old = doc.shape(shape_id).text
        self.new = text

    def redo(self) -> None:
        self.doc.set_text(self.sid, self.new)

    def undo(self) -> None:
        self.doc.set_text(self.sid, self.old)


class AddLayerCommand(QUndoCommand):
    def __init__(self, doc: Document, layer: Layer, index: int = 0) -> None:
        super().__init__("Ebene hinzufügen")
        self.doc = doc
        self.layer = layer
        self.index = index
        self._prev_active = doc.active_layer_id

    def redo(self) -> None:
        self.doc.begin_batch()
        self.doc.add_layer(self.layer, self.index)
        self.layer = self.doc.layer(self.layer.id)
        self.doc.set_active_layer(self.layer.id)
        self.doc.end_batch()

    def undo(self) -> None:
        self.doc.begin_batch()
        self.doc.remove_layer(self.layer.id)
        if self._prev_active and any(l.id == self._prev_active for l in self.doc.layers):
            self.doc.set_active_layer(self._prev_active)
        self.doc.end_batch()


class RemoveLayerCommand(QUndoCommand):
    """Entfernt eine Ebene samt ihren Objekten. Die letzte Ebene bleibt immer erhalten."""

    def __init__(self, doc: Document, layer_id: str) -> None:
        super().__init__("Ebene löschen")
        self.doc = doc
        self.layer_id = layer_id
        self._prev_active = doc.active_layer_id
        self._saved: tuple[int, Layer, list[tuple[int, Shape]]] | None = None

    def redo(self) -> None:
        if len(self.doc.layers) <= 1:
            self.setObsolete(True)
            return
        self._saved = self.doc.remove_layer(self.layer_id)

    def undo(self) -> None:
        if self._saved is None:
            return
        self.doc.begin_batch()
        self.doc.restore_layer(*self._saved)
        self.doc.set_active_layer(self._prev_active)
        self.doc.end_batch()


class MoveLayerCommand(QUndoCommand):
    def __init__(self, doc: Document, layer_id: str, new_index: int) -> None:
        super().__init__("Ebene verschieben")
        self.doc = doc
        self.layer_id = layer_id
        self.old_index = doc.layer_index(layer_id)
        self.new_index = max(0, min(len(doc.layers) - 1, new_index))

    def redo(self) -> None:
        self.doc.move_layer(self.layer_id, self.new_index)

    def undo(self) -> None:
        self.doc.move_layer(self.layer_id, self.old_index)


class SetLayerAttrCommand(QUndoCommand):
    """Ändert ein Ebenen-Attribut (Name, Farbe, Leistung, ...).

    Aufeinanderfolgende Änderungen desselben Felds werden zusammengeführt,
    damit z. B. das Hochzählen der Leistung ein einziger Undo-Schritt ist.
    """

    LABELS = {"name": "Ebene umbenennen", "color": "Ebenenfarbe", "power": "Leistung",
              "speed": "Geschwindigkeit", "passes": "Durchgänge",
              "visible": "Sichtbarkeit", "locked": "Sperre"}

    def __init__(self, doc: Document, layer_id: str, attr: str, value) -> None:
        super().__init__(self.LABELS.get(attr, attr))
        self.doc = doc
        self.layer_id = layer_id
        self.attr = attr
        self.old = getattr(doc.layer(layer_id), attr)
        self.new = value

    def redo(self) -> None:
        self.doc.update_layer(self.layer_id, **{self.attr: self.new})

    def undo(self) -> None:
        self.doc.update_layer(self.layer_id, **{self.attr: self.old})

    def id(self) -> int:  # noqa: A003 - Qt API
        return _ID_LAYER_ATTR

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802 - Qt API
        if (isinstance(other, SetLayerAttrCommand) and other.layer_id == self.layer_id
                and other.attr == self.attr and self.attr in ("power", "speed", "passes", "name")):
            self.new = other.new
            return True
        return False
