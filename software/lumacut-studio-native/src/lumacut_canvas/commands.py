"""Undo/Redo-Befehle (QUndoCommand) für alle Dokumentänderungen.

Jede Benutzeraktion wird genau ein Befehl auf dem QUndoStack. Werte, die
während eines Zugs live geändert werden (Verschieben/Skalieren mit der Maus),
werden vor ``push`` auf den Ausgangszustand zurückgesetzt; ``redo`` setzt dann
den Endzustand. Spinbox-Änderungen derselben Ebene/desselben Felds werden
über ``mergeWith`` zu einem Schritt zusammengefasst.
"""

from __future__ import annotations

from PySide6.QtGui import QUndoCommand

from .model import Document, Geometry, ImageSettings, Layer, Shape

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


class SetGroupsCommand(QUndoCommand):
    """Gruppenzugehörigkeit mehrerer Objekte setzen (Gruppieren/Entgruppieren)."""

    def __init__(self, doc: Document, new: dict[str, tuple[str, ...]], text: str) -> None:
        super().__init__(text)
        self.doc = doc
        self.new = new
        self.old = {i: doc.shape(i).groups for i in new}

    def _apply(self, values: dict[str, tuple[str, ...]]) -> None:
        self.doc.begin_batch()
        for i, g in values.items():
            self.doc.set_groups(i, g)
        self.doc.end_batch()

    def redo(self) -> None:
        self._apply(self.new)

    def undo(self) -> None:
        self._apply(self.old)


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


# --- Abgeleitete Ebenen-Attribute (z. B. Materialbibliothek) -----------------
# Ein Hook ``fn(layer, changes) -> dict`` darf zu einer Ebenen-Änderung weitere
# Attribute liefern (z. B. neu geplante Leistung/Geschwindigkeit, wenn sich bei
# einer verknüpften Ebene die Dicke ändert). Sie landen im *selben* Undo-Schritt.
# Werte, die die Änderung selbst setzt, haben Vorrang – außer der Hook nennt sie
# unter dem Schlüssel ``"__override__"`` (z. B. abgeleitete Durchgänge, die das
# Panel aus veralteten Werten mitschickt). Fehler im Hook werden ignoriert,
# damit die eigentliche Änderung nie scheitert.
_LAYER_ATTR_HOOKS: list = []


def register_layer_attr_hook(fn) -> None:
    if fn not in _LAYER_ATTR_HOOKS:
        _LAYER_ATTR_HOOKS.append(fn)


def unregister_layer_attr_hook(fn) -> None:
    if fn in _LAYER_ATTR_HOOKS:
        _LAYER_ATTR_HOOKS.remove(fn)


def derived_layer_attrs(layer, changes: dict) -> dict:
    """Zusätzliche (bzw. ausdrücklich überschriebene) Attribute aller Hooks."""
    extra: dict = {}
    for fn in list(_LAYER_ATTR_HOOKS):
        try:
            more = dict(fn(layer, {**changes, **extra}) or {})
            override = tuple(more.pop("__override__", ()))
        except Exception:  # noqa: BLE001 - Hook darf die Änderung nicht verhindern
            continue
        for k, v in more.items():
            if k == "id" or not hasattr(layer, k) or (k in changes and k not in override):
                continue
            extra[k] = v
    return extra


class SetLayerAttrCommand(QUndoCommand):
    """Ändert ein Ebenen-Attribut (Name, Farbe, Leistung, ...).

    Aufeinanderfolgende Änderungen desselben Felds werden zusammengeführt,
    damit z. B. das Hochzählen der Leistung ein einziger Undo-Schritt ist.
    Abgeleitete Attribute (:func:`derived_layer_attrs`) gehören zum Schritt.
    """

    LABELS = {"name": "Ebene umbenennen", "color": "Ebenenfarbe", "power": "Leistung",
              "speed": "Geschwindigkeit", "passes": "Durchgänge",
              "visible": "Sichtbarkeit", "locked": "Sperre", "z_step": "Fokus-Absenkung",
              "material": "Material", "thickness_mm": "Materialdicke",
              "target_depth_mm": "Zieltiefe", "depth_per_pass_mm": "Tiefe je Durchgang",
              "material_link": "Materialverknüpfung"}

    def __init__(self, doc: Document, layer_id: str, attr: str, value) -> None:
        super().__init__(self.LABELS.get(attr, attr))
        self.doc = doc
        self.layer_id = layer_id
        self.attr = attr
        layer = doc.layer(layer_id)
        self.old = getattr(layer, attr)
        self.new = value
        self.extra_new = {k: v for k, v in derived_layer_attrs(layer, {attr: value}).items()
                          if k != attr}
        self.extra_old = {k: getattr(layer, k) for k in self.extra_new}

    def redo(self) -> None:
        self.doc.update_layer(self.layer_id, **{**self.extra_new, self.attr: self.new})

    def undo(self) -> None:
        self.doc.update_layer(self.layer_id, **{**self.extra_old, self.attr: self.old})

    def id(self) -> int:  # noqa: A003 - Qt API
        return _ID_LAYER_ATTR

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802 - Qt API
        if (isinstance(other, SetLayerAttrCommand) and other.layer_id == self.layer_id
                and other.attr == self.attr and self.attr in ("power", "speed", "passes", "name")
                and not other.extra_new):
            self.new = other.new
            return True
        return False


class SetLayerAttrsCommand(QUndoCommand):
    """Mehrere Ebenen-Attribute in einem Undo-Schritt (z. B. Material anwenden)."""

    def __init__(self, doc: Document, layer_id: str, attrs: dict, text: str = "Material anwenden") -> None:
        super().__init__(text)
        self.doc = doc
        self.layer_id = layer_id
        layer = doc.layer(layer_id)
        self.new = {**attrs, **derived_layer_attrs(layer, dict(attrs))}
        self.old = {k: getattr(layer, k) for k in self.new}

    def redo(self) -> None:
        self.doc.update_layer(self.layer_id, **self.new)

    def undo(self) -> None:
        self.doc.update_layer(self.layer_id, **self.old)


class SetImageSettingsCommand(QUndoCommand):
    """Gravur-Einstellungen eines Bildobjekts (Modus, Linienabstand, …)."""

    def __init__(self, doc: Document, shape_id: str, old: ImageSettings, new: ImageSettings,
                 text: str = "Bildeinstellungen") -> None:
        super().__init__(text)
        self.doc = doc
        self.shape_id = shape_id
        self.old = old
        self.new = new

    def redo(self) -> None:
        self.doc.set_image_settings(self.shape_id, self.new)

    def undo(self) -> None:
        self.doc.set_image_settings(self.shape_id, self.old)
