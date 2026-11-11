"""Dialog „Optimierungseinstellungen“ (wie LightBurn „Optimization Settings“).

Bearbeitet die Schnittreihenfolge des Projekts (:class:`lumacut_canvas.model.CutOrder`,
``Document.cut_order``) als *einen* Undo-Schritt (:class:`SetCutOrderCommand`).
Der Planer (:func:`lumacut_job.planner.optimize_layers`) liest sie über
``JobLayer.cut_order`` – Senden, Pfadvorschau, Zeitschätzung, Rahmen und
„G-Code speichern“ planen damit gleich. Gespeichert wird sie in der
Projektdatei (nur, wenn vom Standard abweichend).
"""

from __future__ import annotations

from PySide6.QtGui import QUndoCommand
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QLabel)

from lumacut_canvas.model import CUT_ORDER_DIRECTIONS, CutOrder, Document

#: Anzeigetexte der Richtungen (Reihenfolge wie :data:`CUT_ORDER_DIRECTIONS`).
DIRECTION_LABELS = {"": "aus", "top_bottom": "von oben nach unten",
                    "bottom_top": "von unten nach oben", "left_right": "von links nach rechts",
                    "right_left": "von rechts nach links"}


class SetCutOrderCommand(QUndoCommand):
    """Optimierungseinstellungen des Projekts ändern (ein Undo-Schritt)."""

    def __init__(self, doc: Document, new: CutOrder, text: str = "Optimierungseinstellungen"):
        super().__init__(text)
        self.doc = doc
        self.old = doc.cut_order
        self.new = new

    def redo(self) -> None:
        self.doc.set_cut_order(self.new)

    def undo(self) -> None:
        self.doc.set_cut_order(self.old)


class OptimizeDialog(QDialog):
    """Schnittreihenfolge bearbeiten; :meth:`value` liefert die neue :class:`CutOrder`."""

    def __init__(self, order: CutOrder, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Optimierungseinstellungen")
        f = QFormLayout(self)
        info = QLabel("Reihenfolge, Startpunkt und Richtung der Konturen beim Senden, in der "
                      "Pfadvorschau und der Zeitschätzung. Die Ebenen laufen weiter von unten "
                      "nach oben; gilt für das ganze Projekt.")
        info.setWordWrap(True)
        f.addRow(info)
        self.enabled = QCheckBox("Optimierung und Umsortierung aktiv")
        self.enabled.setToolTip("Aus: Konturen in der Reihenfolge, in der sie gezeichnet wurden, "
                                "mit ihrem gezeichneten Startpunkt und ihrer Richtung.")
        self.inside_first = QCheckBox("Innere Formen zuerst")
        self.inside_first.setToolTip("Löcher und Gravuren in einem Teil vor dessen Außenkontur "
                                     "schneiden – das Teil fällt erst zum Schluss heraus.")
        self.reduce_travel = QCheckBox("Leerfahrten verkürzen")
        self.reduce_travel.setToolTip("Als Nächstes immer die nächstgelegene Kontur schneiden.")
        self.best_start = QCheckBox("Besten Startpunkt wählen")
        self.best_start.setToolTip("Geschlossene Konturen am Punkt beginnen, der der "
                                   "Kopfposition am nächsten liegt.")
        self.corners = QCheckBox("Möglichst an Ecken beginnen")
        self.corners.setToolTip("Startpunkt geschlossener Konturen an eine Ecke legen (Knick ab "
                                "40°) – die Einstichstelle fällt dort kaum auf. Konturen ohne "
                                "Ecken (Kreise) beginnen am nächsten Punkt.")
        self.best_direction = QCheckBox("Beste Richtung wählen")
        self.best_direction.setToolTip("Offene Pfade und Linien dürfen vom näheren Ende aus "
                                       "geschnitten werden (sonst wie gezeichnet).")
        self.direction = QComboBox()
        for key in CUT_ORDER_DIRECTIONS:
            self.direction.addItem(DIRECTION_LABELS[key], key)
        self.direction.setToolTip("Konturen Zeile für Zeile in dieser Richtung schneiden, z. B. "
                                  "von oben nach unten, damit Rauch und Späne nicht über "
                                  "fertige Teile ziehen. Innerhalb einer Zeile gilt "
                                  "„Leerfahrten verkürzen“.")
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        for label, w in (("", self.enabled), ("", self.inside_first), ("", self.reduce_travel),
                         ("", self.best_start), ("", self.corners), ("", self.best_direction),
                         ("In Richtung schneiden", self.direction), ("", self.hint)):
            f.addRow(label, w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel
                              | QDialogButtonBox.RestoreDefaults)
        bb.button(QDialogButtonBox.RestoreDefaults).setText("Zurücksetzen")
        bb.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        for box in (self.enabled, self.reduce_travel, self.best_start, self.best_direction,
                    self.inside_first, self.corners):
            box.toggled.connect(self._update_enabled)
        self.direction.currentIndexChanged.connect(self._update_enabled)
        self.set_value(order)

    def set_value(self, order: CutOrder) -> None:
        self.enabled.setChecked(order.enabled)
        self.inside_first.setChecked(order.inside_first)
        self.reduce_travel.setChecked(order.reduce_travel)
        self.best_start.setChecked(order.best_start)
        self.corners.setChecked(order.corners)
        self.best_direction.setChecked(order.best_direction)
        self.direction.setCurrentIndex(max(0, self.direction.findData(order.direction)))
        self._update_enabled()

    def restore_defaults(self) -> None:
        self.set_value(CutOrder())

    def _update_enabled(self, *_args) -> None:
        on = self.enabled.isChecked()
        for w in (self.inside_first, self.reduce_travel, self.direction):
            w.setEnabled(on)
        # Startpunkt / Richtung wirken nur, wenn der Planer eine Kontur auswählt.
        picks = on and (self.reduce_travel.isChecked() or bool(self.direction.currentData()))
        self.best_start.setEnabled(picks)
        self.best_direction.setEnabled(picks)
        self.corners.setEnabled(picks and self.best_start.isChecked())
        self.hint.setText(order_hint(self.value()))
        self.hint.setVisible(bool(self.hint.text()))

    def value(self) -> CutOrder:
        return CutOrder(enabled=self.enabled.isChecked(),
                        inside_first=self.inside_first.isChecked(),
                        reduce_travel=self.reduce_travel.isChecked(),
                        best_start=self.best_start.isChecked(),
                        corners=self.corners.isChecked(),
                        best_direction=self.best_direction.isChecked(),
                        direction=self.direction.currentData() or "")


def order_hint(order: CutOrder) -> str:
    """Warnung zu einer Einstellung, die Teile verrutschen lassen kann (sonst leer)."""
    if not order.enabled:
        return ("Achtung: Konturen laufen in Zeichenreihenfolge – ein Teil kann vor seinen "
                "Löchern ausgeschnitten werden und verrutschen.")
    if not order.inside_first:
        return ("Achtung: Ohne „Innere Formen zuerst“ kann ein Teil vor seinen Löchern "
                "herausfallen oder verrutschen.")
    if not order.reduce_travel and not order.direction:
        return "Konturen laufen in Zeichenreihenfolge (nur innere Formen werden vorgezogen)."
    return ""


def apply_cut_order(editor, order: CutOrder) -> bool:
    """Einstellungen als einen Undo-Schritt setzen; False, wenn sich nichts ändert."""
    doc = editor.document
    if order == doc.cut_order:
        return False
    editor.undo_stack.push(SetCutOrderCommand(doc, order))
    return True


def summary(order: CutOrder) -> str:
    """Kurztext der Abweichungen vom Standard („Standard“, wenn keine)."""
    if not order.enabled:
        return "Optimierung aus (Zeichenreihenfolge)"
    parts = []
    if not order.inside_first:
        parts.append("innere Formen nicht zuerst")
    if not order.reduce_travel:
        parts.append("Leerfahrten nicht verkürzt")
    if order.direction:
        parts.append(f"in Richtung {DIRECTION_LABELS[order.direction]}")
    picks = order.reduce_travel or bool(order.direction)
    if picks and not order.best_start:
        parts.append("Startpunkt wie gezeichnet")
    if picks and order.best_start and order.corners:
        parts.append("Start an Ecken")
    if picks and not order.best_direction:
        parts.append("Richtung wie gezeichnet")
    return ", ".join(parts) or "Standard"
