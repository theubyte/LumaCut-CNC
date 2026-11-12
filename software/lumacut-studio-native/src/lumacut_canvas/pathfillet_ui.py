"""Pfad-Menü: „Ecken abrunden …“ (LightBurn *Radius tool*, xTool „Eckenradius“
für Polygone / Sterne).

Von :func:`pathops_ui.install` eingebunden (gleiches „Pfad“-Menü in der
Aktionsleiste und im Kontextmenü). Rechnen in :mod:`pathfillet`; die Aktion ist
genau ein Undo-Schritt. Bereich wie „Pfade vereinfachen“: die Auswahl, ohne
Auswahl alle bearbeitbaren Objekte. Kürzel Alt+Umschalt+R („Radius“).
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QLabel)

from . import pathfillet
from .edit_commands import ReplaceShapesCommand

ACTIONS = [("path_fillet", "Ecken abrunden …", "Alt+Shift+R")]
MENU_ACTIONS = [name for name, _t, _k in ACTIONS]


def default_values() -> dict:
    return {"radius_mm": pathfillet.RADIUS_MM, "mode": "round", "corners": "all",
            "min_angle_deg": pathfillet.MIN_ANGLE_DEG}


class FilletDialog(QDialog):
    """Art, Radius, welche Ecken, Mindestwinkel; Ecken-Zähler live."""

    def __init__(self, shapes, parent=None, values: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ecken abrunden")
        self.shapes = list(shapes)
        v = {**default_values(), **(values or {})}
        form = QFormLayout(self)
        self.mode = QComboBox()
        for key in pathfillet.MODES:
            self.mode.addItem(pathfillet.MODE_LABELS[key], key)
        self.mode.setCurrentIndex(max(0, self.mode.findData(v["mode"])))
        self.mode.setToolTip("Abrunden: Kreisbogen, der beide Kanten berührt · "
                             "Abschrägen: gerade Fase zwischen denselben Punkten")
        self.radius = QDoubleSpinBox()
        self.radius.setRange(*pathfillet.RADIUS_RANGE)
        self.radius.setDecimals(2)
        self.radius.setSingleStep(0.5)
        self.radius.setSuffix(" mm")
        self.radius.setValue(v["radius_mm"])
        self.radius.setToolTip("Radius des Bogens (Abschrägen: Fase an denselben Berührpunkten). "
                               "Ist eine Kante zu kurz, wird der Radius an dieser Ecke kleiner.")
        self.corners = QComboBox()
        for key in pathfillet.CORNERS:
            self.corners.addItem(pathfillet.CORNER_LABELS[key], key)
        self.corners.setCurrentIndex(max(0, self.corners.findData(v["corners"])))
        self.corners.setToolTip("Außenecken: nach außen zeigende Spitzen (beim Stern die Zacken) · "
                                "Innenecken: Einbuchtungen. Offene Pfade: jede Ecke.")
        self.min_angle = QDoubleSpinBox()
        self.min_angle.setRange(*pathfillet.MIN_ANGLE_RANGE)
        self.min_angle.setDecimals(0)
        self.min_angle.setSingleStep(5)
        self.min_angle.setSuffix(" °")
        self.min_angle.setValue(v["min_angle_deg"])
        self.min_angle.setToolTip("Nur Knicke ab dieser Richtungsänderung sind Ecken – flache Knicke "
                                  "abgeflachter Kreise und Kurven bleiben unverändert")
        self.readout = QLabel()
        self.readout.setObjectName("FilletReadout")
        self.readout.setWordWrap(True)
        form.addRow("Art", self.mode)
        form.addRow("Radius", self.radius)
        form.addRow("Ecken", self.corners)
        form.addRow("Knick ab", self.min_angle)
        form.addRow(self.readout)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.mode.currentIndexChanged.connect(self.update_readout)
        self.radius.valueChanged.connect(self.update_readout)
        self.corners.currentIndexChanged.connect(self.update_readout)
        self.min_angle.valueChanged.connect(self.update_readout)
        self.update_readout()

    def result_preview(self) -> pathfillet.FilletResult:
        v = self.values()
        return pathfillet.fillet_shapes(self.shapes, v["radius_mm"], v["mode"], v["corners"],
                                        v["min_angle_deg"])

    def update_readout(self) -> None:
        res = self.result_preview()
        self.readout.setText(res.readout())
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(res.changed > 0)

    def values(self) -> dict:
        return {"radius_mm": self.radius.value(), "mode": self.mode.currentData(),
                "corners": self.corners.currentData(), "min_angle_deg": self.min_angle.value()}


class CornerFillet:
    def __init__(self, editor) -> None:
        self.editor = editor
        self.last = default_values()        # letzte Eingabe (Sitzung), wie LightBurn
        self.ask = self._ask                # für Tests austauschbar

    def _ask(self, shapes):
        dlg = FilletDialog(shapes, self.editor, self.last)
        return dlg.values() if dlg.exec() == QDialog.Accepted else None

    def _scope(self):
        ed = self.editor
        doc = ed.document
        ids = ed.selection if ed.selection else [s.id for s in doc.shapes]
        want = {i for i in ids if doc.has_shape(i) and doc.is_editable(i)}
        return [s for s in doc.shapes if s.id in want and pathfillet.can_fillet(s)]

    def fillet(self) -> None:
        ed = self.editor
        shapes = self._scope()
        if not shapes:
            ed.notify("Ecken abrunden: keine Polygone, Pfade oder Rechtecke "
                      + ("in der Auswahl" if ed.selection else "im Dokument"))
            return
        v = self.ask(shapes)
        if not v:
            return
        v = {**default_values(), **v}
        self.last = dict(v)
        res = pathfillet.fillet_shapes(shapes, v["radius_mm"], v["mode"], v["corners"],
                                       v["min_angle_deg"])
        title = "Ecken abrunden" if v["mode"] == "round" else "Ecken abschrägen"
        if res.changed:
            ed.undo_stack.beginMacro(title)
            try:       # einzeln ersetzen: jede Form bleibt an ihrer Stelle im Stapel
                for old, new in zip(res.remove, res.add):
                    ed.undo_stack.push(ReplaceShapesCommand(ed.document, [old], [new], title))
            finally:
                ed.undo_stack.endMacro()
            if ed.selection:     # Auswahl bleibt (ersetzte Formen durch ihre Nachfolger)
                keep = [i for i in ed.selection if ed.document.has_shape(i)]
                ed.set_selection(list(dict.fromkeys(keep + [s.id for s in res.add])))
        ed.notify(f"{title}: " + res.readout())


def install(editor) -> CornerFillet:
    tools = CornerFillet(editor)
    for name, text, key in ACTIONS:
        editor._act(name, text, lambda _=False: tools.fillet(), QKeySequence(key) if key else None)
    return tools
