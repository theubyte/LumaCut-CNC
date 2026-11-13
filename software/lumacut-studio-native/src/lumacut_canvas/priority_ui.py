"""Schnitt-Priorität in der PropertyBar (LightBurn *Shape Properties › Priority*):
Feld „Priorität“ für die ausgewählten Objekte.

Sichtbar, solange Vektor-Objekte ausgewählt sind und das Projekt „Nach Priorität“
schneidet (``CutOrder.order_by == "priority"``, „Optimierung…“) – oder ein
ausgewähltes Objekt schon eine Priorität ≠ 0 hat, damit sie sich zurücksetzen
lässt. Bilder werden immer vorab graviert und bekommen keine Priorität. Eine
Änderung gilt für alle ausgewählten Objekte (ein Undo-Schritt).
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import QHBoxLayout, QLabel, QSpinBox, QWidget

from .edit_commands import ReplaceShapeCommand
from .model import PRIORITY_RANGE, Shape, read_priority

TIP = ("Schnitt-Priorität (wie LightBurn „Priority“): mit „Optimierung… › Reihenfolge: Nach "
       "Priorität“ werden zuerst alle Objekte mit der kleinsten Priorität mit allen ihren "
       "Ebenen gelasert, dann die nächste. 0 = Standard; gleiche Priorität = nach Ebenen.")


def priority_targets(doc, selection) -> list[Shape]:
    """Ausgewählte, bearbeitbare Vektor-Objekte (Bilder ausgenommen)."""
    shapes = [doc.shape(i) for i in selection if doc.has_shape(i)]
    return [s for s in shapes if s.kind != "image" and doc.is_editable(s.id)]


def describe(shapes: list[Shape], value: int) -> str:
    n = len(shapes)
    what = "1 Objekt" if n == 1 else f"{n} Objekte"
    return f"Priorität {value}: {what}"


class PriorityControls(QWidget):
    def __init__(self, editor) -> None:
        super().__init__()
        self.setObjectName("PriorityControls")
        self.ed = editor
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.label = QLabel("Priorität")
        self.label.setToolTip(TIP)
        self.priority = QSpinBox()
        self.priority.setObjectName("ShapePriority")
        self.priority.setRange(*PRIORITY_RANGE)
        self.priority.setKeyboardTracking(False)
        self.priority.setToolTip(TIP)
        self.priority.setFixedWidth(64)
        self.priority.valueChanged.connect(self._edited)
        lay.addSpacing(8)
        lay.addWidget(self.label)
        lay.addWidget(self.priority)
        self._updating = False
        self.setVisible(False)

    def targets(self) -> list[Shape]:
        return priority_targets(self.ed.document, self.ed.selection)

    def wanted(self, targets: list[Shape]) -> bool:
        """Feld zeigen? Nur mit Auswahl und „Nach Priorität“ oder vorhandener Priorität."""
        if not targets:
            return False
        order = getattr(self.ed.document, "cut_order", None)
        return bool(getattr(order, "by_priority", False)) or any(s.priority for s in targets)

    def refresh(self) -> None:
        targets = self.targets()
        self.setVisible(self.wanted(targets))
        if not targets or self.priority.hasFocus():
            return
        self._updating = True
        try:
            # Gemischte Werte: die kleinste zeigen (wie die Liste der Einheiten).
            self.priority.setValue(min(s.priority for s in targets))
        finally:
            self._updating = False

    def _edited(self, value: int) -> None:
        if self._updating:
            return
        self.apply(value)

    def apply(self, value) -> list[Shape]:
        """Priorität ``value`` auf alle ausgewählten Vektor-Objekte setzen (ein Undo-Schritt)."""
        value = read_priority(value)
        targets = self.targets()
        new = [replace(s, geom=s.geom.copy(), priority=value) for s in targets
               if s.priority != value]
        if not new:
            return []
        stack = self.ed.undo_stack
        label = "Priorität"
        if len(new) == 1:
            stack.push(ReplaceShapeCommand(self.ed.document, new[0], label))
        else:
            stack.beginMacro(label)
            try:
                for s in new:
                    stack.push(ReplaceShapeCommand(self.ed.document, s, label))
            finally:
                stack.endMacro()
        text = describe(new, value)
        order = getattr(self.ed.document, "cut_order", None)
        if not getattr(order, "by_priority", False):
            text += " · wirkt erst mit „Optimierung… › Reihenfolge: Nach Priorität“"
        self.ed.notify(text)
        return new
