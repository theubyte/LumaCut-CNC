"""Menü „Anordnen“ im Canvas: Ausrichten, Verteilen, Raster- und Kreis-Array.

Von :class:`CanvasEditor` über :func:`install` eingebunden (Aktionen +
Knopf in der Aktionsleiste + Untermenü im Kontextmenü). Rechnen in
:mod:`lumacut_canvas.arrange`; jede Aktion ist genau ein Undo-Schritt.
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QMenu, QSpinBox, QToolButton)

from . import arrange, icons
from .commands import AddShapesCommand, SetGeometryCommand
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

ALIGN_SHORTCUTS = {  # wie in gängigen Laserprogrammen: Strg+Umschalt+Pfeil/Buchstabe
    "left": "Ctrl+Shift+Left", "right": "Ctrl+Shift+Right",
    "top": "Ctrl+Shift+Up", "bottom": "Ctrl+Shift+Down",
    "hcenter": "Ctrl+Shift+H", "vcenter": "Ctrl+Shift+V",
}
MENU_ACTIONS = ([f"align_{m}" for m in arrange.ALIGN_MODES]
                + [None, "distribute_h", "distribute_v", None, "array_grid", "array_circular"])


def _spin(lo, hi, val, step=1.0, suffix=" mm", decimals=1):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(val)
    s.setSuffix(suffix)
    return s


class GridArrayDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Raster-Array")
        form = QFormLayout(self)
        self.cols = QSpinBox()
        self.cols.setRange(1, 50)
        self.cols.setValue(3)
        self.rows = QSpinBox()
        self.rows.setRange(1, 50)
        self.rows.setValue(2)
        self.gap_x = _spin(-100, 360, 5.0)
        self.gap_y = _spin(-100, 340, 5.0)
        form.addRow("Spalten", self.cols)
        form.addRow("Zeilen", self.rows)
        form.addRow("Lücke X", self.gap_x)
        form.addRow("Lücke Y", self.gap_y)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def values(self) -> dict:
        return {"cols": self.cols.value(), "rows": self.rows.value(),
                "gap_x": self.gap_x.value(), "gap_y": self.gap_y.value()}


class CircularArrayDialog(QDialog):
    def __init__(self, cx: float, cy: float, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kreis-Array")
        form = QFormLayout(self)
        self.count = QSpinBox()
        self.count.setRange(2, 200)
        self.count.setValue(6)
        self.cx = _spin(0, WORK_WIDTH_MM, cx)
        self.cy = _spin(0, WORK_HEIGHT_MM, cy)
        self.angle = _spin(-360, 360, 360, 15, " °", 1)
        self.rotate = QCheckBox("Kopien mitdrehen")
        self.rotate.setChecked(True)
        form.addRow("Anzahl (inkl. Original)", self.count)
        form.addRow("Mitte X", self.cx)
        form.addRow("Mitte Y", self.cy)
        form.addRow("Winkel", self.angle)
        form.addRow("", self.rotate)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def values(self) -> dict:
        return {"count": self.count.value(), "cx": self.cx.value(), "cy": self.cy.value(),
                "angle_deg": self.angle.value(), "rotate": self.rotate.isChecked()}


class Arranger:
    """Verbindet die Rechenfunktionen mit Auswahl, Undo und Meldungen des Editors."""

    def __init__(self, editor) -> None:
        self.editor = editor
        # Für Tests/Automatisierung austauschbar: liefert die Dialogwerte oder None.
        self.ask_grid = self._ask_grid
        self.ask_circular = self._ask_circular

    def _sel(self) -> list[str]:
        doc = self.editor.document
        return [i for i in self.editor.selection if doc.has_shape(i)]

    def _apply_moves(self, new: dict, label: str) -> None:
        doc = self.editor.document
        if not new:
            return
        old = {i: doc.shape(i).geom.copy() for i in new}
        self.editor.undo_stack.push(SetGeometryCommand(doc, old, new, label))

    def align(self, mode: str) -> None:
        sel = self._sel()
        if not sel:
            self.editor.notify("Zum Ausrichten Objekte auswählen.")
            return
        single = len(arrange.units_of(self.editor.document, sel)) == 1
        self._apply_moves(arrange.align(self.editor.document, sel, mode),
                          arrange.ALIGN_LABELS[mode] + (" (Arbeitsfläche)" if single else ""))

    def distribute(self, axis: str) -> None:
        sel = self._sel()
        if len(arrange.units_of(self.editor.document, sel)) < 3:
            self.editor.notify("Zum Verteilen mindestens drei Objekte oder Gruppen auswählen.")
            return
        self._apply_moves(arrange.distribute(self.editor.document, sel, axis),
                          "Waagerecht verteilen" if axis == "h" else "Senkrecht verteilen")

    def _add_copies(self, copies: list, label: str) -> None:
        ed = self.editor
        if not copies:
            return
        if len(copies) > arrange.MAX_ARRAY_COPIES:
            ed.notify(f"Zu viele Kopien ({len(copies)} > {arrange.MAX_ARRAY_COPIES}).")
            return
        n_out = arrange.outside_count(copies)
        if n_out:
            ed.notify(f"{n_out} Kopie(n) lägen außerhalb der Arbeitsfläche – "
                      "weniger Kopien oder kleinerer Abstand.")
            return
        keep = self._sel()
        ed.undo_stack.push(AddShapesCommand(ed.document, copies, label))
        ed.set_selection(keep + [c.id for c in copies])
        ed.notify(f"{label}: {len(copies)} Kopie(n)")

    def _ask_grid(self):
        dlg = GridArrayDialog(self.editor)
        return dlg.values() if dlg.exec() == QDialog.Accepted else None

    def _ask_circular(self, cx: float, cy: float):
        dlg = CircularArrayDialog(cx, cy, self.editor)
        return dlg.values() if dlg.exec() == QDialog.Accepted else None

    def grid(self) -> None:
        sel = self._sel()
        if not sel:
            self.editor.notify("Für ein Array Objekte auswählen.")
            return
        v = self.ask_grid()
        if v:
            self._add_copies(arrange.grid_array(self.editor.document, sel, **v), "Raster-Array")

    def circular(self) -> None:
        sel = self._sel()
        if not sel:
            self.editor.notify("Für ein Array Objekte auswählen.")
            return
        b = self.editor.document.selection_bounds(sel)
        # Vorschlag: Mitte unter der Auswahl, Radius ≈ Auswahlhöhe (mind. 20 mm).
        cx = b.x + b.w / 2
        cy = min(WORK_HEIGHT_MM, b.y + b.h / 2 + max(b.h, 20.0))
        v = self.ask_circular(cx, cy)
        if v:
            self._add_copies(arrange.circular_array(self.editor.document, sel, **v), "Kreis-Array")


def install(editor) -> Arranger:
    """Aktionen anlegen (``editor.actions_by_name``) – vor dem Layout aufrufen."""
    arr = Arranger(editor)
    for m in arrange.ALIGN_MODES:
        editor._act(f"align_{m}", arrange.ALIGN_LABELS[m], lambda _=False, m=m: arr.align(m),
                    QKeySequence(ALIGN_SHORTCUTS[m]))
    editor._act("distribute_h", "Waagerecht verteilen", lambda: arr.distribute("h"))
    editor._act("distribute_v", "Senkrecht verteilen", lambda: arr.distribute("v"))
    editor._act("array_grid", "Raster-Array …", arr.grid)
    editor._act("array_circular", "Kreis-Array …", arr.circular)
    return arr


def build_menu(editor, parent=None) -> QMenu:
    menu = QMenu("Anordnen", parent or editor)
    menu.setObjectName("ArrangeMenu")
    menu.setIcon(icons.icon("arrange"))
    for name in MENU_ACTIONS:
        menu.addSeparator() if name is None else menu.addAction(editor.actions_by_name[name])
    return menu


def add_to_bar(editor, bar) -> QToolButton:
    """Knopf „Anordnen“ (öffnet das Menü sofort, auch per Finger)."""
    btn = QToolButton(bar)
    btn.setObjectName("ArrangeButton")
    btn.setIcon(icons.icon("arrange"))
    btn.setToolTip("Anordnen: ausrichten, verteilen, Array")
    btn.setPopupMode(QToolButton.InstantPopup)
    btn.setMenu(build_menu(editor, btn))
    bar.addWidget(btn)
    return btn
