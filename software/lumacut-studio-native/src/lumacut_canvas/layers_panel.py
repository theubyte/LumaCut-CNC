"""Ebenen-Panel: Liste der Ebenen und Parameter der aktiven Ebene.

Jede Zeile zeigt Farbe, Name und die Laser-Einstellung der Ebene in
Kurzform ("80 % · 600 mm/min · 1×"), damit die Zuordnung Ebene → Parameter
ohne Klicken sichtbar ist. Darunter werden die Parameter der aktiven Ebene
bearbeitet. Alle Änderungen laufen über den Undo-Stack des Editors.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QUndoStack
from PySide6.QtWidgets import (QColorDialog, QDoubleSpinBox, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from . import icons, theme
from .commands import AddLayerCommand, MoveLayerCommand, RemoveLayerCommand, SetLayerAttrCommand
from .model import PASSES_RANGE, POWER_RANGE, SPEED_RANGE, Document, Layer


def layer_summary(layer: Layer) -> str:
    return f"{layer.power:g} % · {layer.speed:g} mm/min · {layer.passes}×"


class _LayerRow(QWidget):
    def __init__(self, panel: "LayersPanel", layer: Layer, count: int) -> None:
        super().__init__()
        self.setObjectName("LayerRow")
        self.panel = panel
        self.layer_id = layer.id
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 4, 4)
        lay.setSpacing(6)
        swatch = QFrame()
        swatch.setFixedSize(6, 30)
        swatch.setStyleSheet(f"background: {layer.color}; border-radius: 3px;")
        lay.addWidget(swatch)
        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel(f"{layer.name}  <span style='color:#93a1b5;font-weight:400'>({count})</span>")
        name.setObjectName("LayerName")
        summary = QLabel(layer_summary(layer))
        summary.setObjectName("LayerSummary")
        text.addWidget(name)
        text.addWidget(summary)
        lay.addLayout(text, 1)
        self.eye = self._toggle("eye" if layer.visible else "eye_off",
                                "Ausblenden" if layer.visible else "Einblenden",
                                lambda: panel.toggle(self.layer_id, "visible"))
        self.lock = self._toggle("lock" if layer.locked else "unlock",
                                 "Entsperren" if layer.locked else "Sperren",
                                 lambda: panel.toggle(self.layer_id, "locked"))
        lay.addWidget(self.eye)
        lay.addWidget(self.lock)

    def _toggle(self, icon_name: str, tip: str, slot) -> QToolButton:
        b = QToolButton()
        b.setIcon(icons.icon(icon_name))
        b.setIconSize(QSize(18, 18))
        b.setToolTip(tip)
        b.setAutoRaise(True)
        b.clicked.connect(slot)
        return b


class LayersPanel(QWidget):
    def __init__(self, document: Document, undo_stack: QUndoStack, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LayersPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        # Eigenes Stylesheet wie CanvasEditor: unabhängig davon, wann/wie das
        # Hauptfenster seine Styles setzt.
        self.setStyleSheet(theme.CANVAS_QSS)
        self.doc = document
        self.stack = undo_stack
        self._signature: tuple | None = None
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("Ebenen")
        title.setObjectName("SectionTitle")
        head.addWidget(title, 1)
        for icon_name, tip, slot in (("plus", "Neue Ebene", self.add_layer),
                                     ("up", "Ebene nach oben", lambda: self.move_active(-1)),
                                     ("down", "Ebene nach unten", lambda: self.move_active(1)),
                                     ("delete", "Ebene löschen (mit Objekten)", self.remove_active)):
            b = QToolButton()
            b.setIcon(icons.icon(icon_name))
            b.setIconSize(QSize(18, 18))
            b.setToolTip(tip)
            b.clicked.connect(slot)
            head.addWidget(b)
        root.addLayout(head)

        self.list = QListWidget()
        self.list.setSpacing(1)
        self.list.setMinimumHeight(140)
        self.list.currentRowChanged.connect(self._row_changed)
        self.list.itemDoubleClicked.connect(lambda _: (self.name.setFocus(), self.name.selectAll()))
        root.addWidget(self.list, 1)
        hint = QLabel("Oben liegende Ebenen werden zuletzt gelasert. Neue Objekte landen auf der aktiven Ebene.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.params = QGroupBox("Laser-Einstellung der Ebene")
        form = QFormLayout(self.params)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        self.name = QLineEdit()
        self.name.editingFinished.connect(self._name_edited)
        self.color = QPushButton()
        self.color.setObjectName("ColorButton")
        self.color.setToolTip("Ebenenfarbe wählen")
        self.color.clicked.connect(self._pick_color)
        self.power = QDoubleSpinBox()
        self.power.setRange(*POWER_RANGE)
        self.power.setDecimals(0)
        self.power.setSuffix(" %")
        self.speed = QDoubleSpinBox()
        self.speed.setRange(*SPEED_RANGE)
        self.speed.setDecimals(0)
        self.speed.setSingleStep(50)
        self.speed.setSuffix(" mm/min")
        self.passes = QSpinBox()
        self.passes.setRange(*PASSES_RANGE)
        self.passes.setSuffix(" ×")
        for spin, attr in ((self.power, "power"), (self.speed, "speed"), (self.passes, "passes")):
            spin.setKeyboardTracking(False)
            spin.setAlignment(Qt.AlignRight)
            spin.valueChanged.connect(lambda v, a=attr: self._param_edited(a, v))
        form.addRow("Name", self.name)
        form.addRow("Farbe", self.color)
        form.addRow("Leistung", self.power)
        form.addRow("Geschwindigkeit", self.speed)
        form.addRow("Durchgänge", self.passes)
        root.addWidget(self.params)

        self.doc.add_listener(self.refresh)
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        # Ein Hauptfenster mit setPalette() vererbt seine Palette beim
        # Einhängen und überschreibt damit die QSS-Farben der Kinder. Einmal
        # neu polieren, sobald das Panel endgültig im Fenster sitzt.
        if not getattr(self, "_restyled", False):
            self._restyled = True
            self.setStyleSheet("")
            self.setStyleSheet(theme.CANVAS_QSS)
        super().showEvent(event)

    # --- Anzeige ----------------------------------------------------------
    def _make_signature(self) -> tuple:
        counts = {l.id: 0 for l in self.doc.layers}
        for s in self.doc.shapes:
            counts[s.layer_id] = counts.get(s.layer_id, 0) + 1
        return (self.doc.active_layer_id,
                tuple((l.id, l.name, l.color, l.power, l.speed, l.passes, l.visible, l.locked,
                       counts[l.id]) for l in self.doc.layers))

    def refresh(self) -> None:
        """Nur neu aufbauen, wenn sich Ebenen tatsächlich geändert haben
        (Dokument meldet auch jede Mausbewegung beim Verschieben)."""
        sig = self._make_signature()
        if sig == self._signature:
            return
        self._signature = sig
        self._updating = True
        self.list.clear()
        counts = {entry[0]: entry[-1] for entry in sig[1]}
        for layer in self.doc.layers:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, layer.id)
            row = _LayerRow(self, layer, counts[layer.id])
            item.setSizeHint(QSize(0, 46))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
        active = self.doc.active_layer
        if active is not None:
            self.list.setCurrentRow(self.doc.layer_index(active.id))
            self.params.setEnabled(True)
            if not self.name.hasFocus():
                self.name.setText(active.name)
            self.color.setStyleSheet(f"background: {active.color};")
            self.power.setValue(active.power)
            self.speed.setValue(active.speed)
            self.passes.setValue(active.passes)
        else:
            self.params.setEnabled(False)
        self._updating = False

    # --- Aktionen ---------------------------------------------------------
    def _row_changed(self, row: int) -> None:
        if self._updating or row < 0:
            return
        lid = self.list.item(row).data(Qt.UserRole)
        self.doc.set_active_layer(lid)  # Auswahl der aktiven Ebene ist kein Undo-Schritt

    def add_layer(self) -> None:
        n = len(self.doc.layers) + 1
        layer = Layer(name=f"Ebene {n}", color=self.doc.next_layer_color())
        idx = self.doc.layer_index(self.doc.active_layer_id) if self.doc.active_layer_id else 0
        self.stack.push(AddLayerCommand(self.doc, layer, idx))

    def remove_active(self) -> None:
        if self.doc.active_layer_id and len(self.doc.layers) > 1:
            self.stack.push(RemoveLayerCommand(self.doc, self.doc.active_layer_id))

    def move_active(self, delta: int) -> None:
        lid = self.doc.active_layer_id
        if lid is None:
            return
        idx = self.doc.layer_index(lid)
        if 0 <= idx + delta < len(self.doc.layers):
            self.stack.push(MoveLayerCommand(self.doc, lid, idx + delta))

    def toggle(self, layer_id: str, attr: str) -> None:
        value = not getattr(self.doc.layer(layer_id), attr)
        self.stack.push(SetLayerAttrCommand(self.doc, layer_id, attr, value))

    def _param_edited(self, attr: str, value: float) -> None:
        if self._updating or self.doc.active_layer is None:
            return
        layer = self.doc.active_layer
        value = int(value) if attr == "passes" else float(value)
        if getattr(layer, attr) != value:
            self.stack.push(SetLayerAttrCommand(self.doc, layer.id, attr, value))

    def _name_edited(self) -> None:
        layer = self.doc.active_layer
        name = self.name.text().strip()
        if layer is not None and name and name != layer.name:
            self.stack.push(SetLayerAttrCommand(self.doc, layer.id, "name", name))

    def _pick_color(self) -> None:
        layer = self.doc.active_layer
        if layer is None:
            return
        c = QColorDialog.getColor(QColor(layer.color), self, "Ebenenfarbe")
        if c.isValid() and c.name() != layer.color:
            self.stack.push(SetLayerAttrCommand(self.doc, layer.id, "color", c.name()))
