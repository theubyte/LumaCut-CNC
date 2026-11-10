"""Pfad-Menü, Teil „Aufräumen“: verbinden, schließen, Duplikate, offene Formen.

Von :func:`pathops_ui.install` eingebunden (gleiches „Pfad“-Menü in der
Aktionsleiste und im Kontextmenü). Rechnen in :mod:`pathjoin`; jede Aktion ist
genau ein Undo-Schritt. Kürzel wie LightBurn: Alt+J verbinden; „Duplikate
löschen“ liegt auf Alt+Umschalt+D, weil Alt+D das Menü „Datei“ öffnet.
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QLabel)

from . import pathjoin
from .commands import DeleteShapesCommand
from .edit_commands import ReplaceShapesCommand

ACTIONS = [
    ("path_join", "Pfade verbinden", "Alt+J"),
    ("path_close", "Pfade schließen (Toleranz) …", "Alt+Shift+J"),
    ("delete_duplicates", "Duplikate löschen", "Alt+Shift+D"),
    ("select_open", "Offene Formen auswählen", None),
]
MENU_ACTIONS = [name for name, _t, _k in ACTIONS]


class ClosePathsDialog(QDialog):
    """LightBurn „Close Selected Paths With Tolerance“: Abstand, Art, Zähler live."""

    def __init__(self, shapes, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pfade schließen")
        self.shapes = list(shapes)
        form = QFormLayout(self)
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setRange(*pathjoin.CLOSE_TOLERANCE_RANGE)
        self.tolerance.setDecimals(2)
        self.tolerance.setSingleStep(0.1)
        self.tolerance.setValue(pathjoin.CLOSE_TOLERANCE_MM)
        self.tolerance.setSuffix(" mm")
        self.tolerance.setToolTip("Größter Abstand zwischen Anfang und Ende eines Pfads, "
                                  "der noch geschlossen wird")
        self.mode = QComboBox()
        for key in pathjoin.CLOSE_MODES:
            self.mode.addItem(pathjoin.CLOSE_MODE_LABELS[key], key)
        self.mode.setToolTip("Zusammenführen: Anfang und Ende treffen sich in der Mitte der Lücke · "
                             "Linie: eine neue gerade Strecke schließt die Lücke")
        self.readout = QLabel()
        self.readout.setObjectName("ClosePathsReadout")
        form.addRow("Abstand höchstens", self.tolerance)
        form.addRow("Schließen durch", self.mode)
        form.addRow(self.readout)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.tolerance.valueChanged.connect(self.update_readout)
        self.update_readout()

    def result_preview(self) -> pathjoin.CloseResult:
        v = self.values()
        return pathjoin.close_paths(self.shapes, v["tolerance_mm"], v["mode"])

    def update_readout(self) -> None:
        res = self.result_preview()
        self.readout.setText(res.summary())
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(res.closed > 0)

    def values(self) -> dict:
        return {"tolerance_mm": self.tolerance.value(), "mode": self.mode.currentData()}


class PathCleanup:
    def __init__(self, editor) -> None:
        self.editor = editor
        self.ask_close = self._ask_close     # für Tests austauschbar

    def _editable(self, ids):
        doc = self.editor.document
        want = {i for i in ids if doc.has_shape(i) and doc.is_editable(i)}
        return [s for s in doc.shapes if s.id in want]

    def _scope(self):
        """Auswahl, sonst alle bearbeitbaren Objekte (wie LightBurn „Delete Duplicates“)."""
        ed = self.editor
        if ed.selection:
            return self._editable(ed.selection), True
        return self._editable(s.id for s in ed.document.shapes), False

    def join(self) -> None:
        ed = self.editor
        shapes, _sel = self._scope()
        if not any(pathjoin.is_open(s) for s in shapes):
            ed.notify("Pfade verbinden: keine offenen Pfade oder Linien "
                      + ("in der Auswahl" if ed.selection else "im Dokument"))
            return
        res = pathjoin.auto_join(shapes)
        if res.changed:
            ed.undo_stack.push(ReplaceShapesCommand(ed.document, res.remove, res.add, "Pfade verbinden"))
            ed.set_selection([s.id for s in res.add])
        ed.notify(res.summary())

    def _ask_close(self, shapes):
        dlg = ClosePathsDialog(shapes, self.editor)
        return dlg.values() if dlg.exec() == QDialog.Accepted else None

    def close(self) -> None:
        ed = self.editor
        shapes = [s for s in self._scope()[0] if pathjoin.is_open(s)]
        if not shapes:
            ed.notify("Pfade schließen: keine offenen Pfade "
                      + ("in der Auswahl" if ed.selection else "im Dokument"))
            return
        v = self.ask_close(shapes)
        if not v:
            return
        res = pathjoin.close_paths(shapes, v["tolerance_mm"], v.get("mode", "move"))
        if res.closed:
            ed.undo_stack.beginMacro("Pfade schließen")
            try:
                for old, new in zip(res.remove, res.add):
                    ed.undo_stack.push(ReplaceShapesCommand(ed.document, [old], [new], "Pfad schließen"))
            finally:
                ed.undo_stack.endMacro()
            keep = [i for i in ed.selection if ed.document.has_shape(i)]
            ed.set_selection(keep + [s.id for s in res.add])
        ed.notify("Pfade schließen: " + res.summary())

    def delete_duplicates(self) -> None:
        ed = self.editor
        shapes, sel = self._scope()
        dupes = pathjoin.find_duplicates(shapes)
        where = "in der Auswahl" if sel else "im Dokument"
        if not dupes:
            ed.notify(f"Duplikate löschen: keine doppelten Objekte {where}")
            return
        cmd = DeleteShapesCommand(ed.document, dupes)
        cmd.setText("Duplikate löschen")
        ed.undo_stack.push(cmd)
        ed.set_selection([i for i in ed.selection if ed.document.has_shape(i)])
        ed.notify(f"Duplikate löschen: {len(dupes)} doppelte(s) Objekt(e) {where} entfernt – "
                  "sie wären doppelt gelasert worden")

    def select_open(self) -> None:
        ed = self.editor
        ids = [s.id for s in self._editable(s.id for s in ed.document.shapes) if pathjoin.is_open(s)]
        ed.set_selection(ids)
        ed.notify(f"{len(ids)} offene Form(en) ausgewählt" if ids else "Keine offenen Formen im Dokument")


def install(editor) -> PathCleanup:
    tools = PathCleanup(editor)
    slots = {"path_join": tools.join, "path_close": tools.close,
             "delete_duplicates": tools.delete_duplicates, "select_open": tools.select_open}
    for name, text, key in ACTIONS:
        editor._act(name, text, lambda _=False, f=slots[name]: f(), QKeySequence(key) if key else None)
    return tools
