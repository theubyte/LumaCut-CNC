"""Menü „Pfad“ im Canvas: Boole-Operationen, Verschweißen, Versatz, Text in Pfade,
Zerlegen / Kombinieren (:mod:`pathsplit`, LightBurn *Break Apart* / *Combine* – deren
Alt+B / Alt+C belegen hier Bogentext und Barcode, darum Strg+Alt+B / Strg+Alt+C),
Aufräumen (verbinden, schließen, vereinfachen, Duplikate – :mod:`pathjoin_ui`).

Von :class:`CanvasEditor` über :func:`install` eingebunden (Aktionen + Knopf
in der Aktionsleiste + Untermenü im Kontextmenü), wie :mod:`arrange_ui`.
Rechnen in :mod:`pathops`; jede Aktion ist genau ein Undo-Schritt.
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QMenu, QToolButton)

from . import icons, pathjoin_ui, pathops, pathsplit
from .edit_commands import ReplaceShapesCommand

BOOL_SHORTCUTS = {"union": "Ctrl+Alt+U", "subtract": "Ctrl+Alt+S", "intersect": "Ctrl+Alt+I",
                  "weld": "Ctrl+Alt+W"}
SPLIT_ACTIONS = [
    ("path_break", "Zerlegen", "Ctrl+Alt+B"),
    ("path_break_all", "Zerlegen (jeder Teilpfad einzeln)", None),
    ("path_combine", "Kombinieren", "Ctrl+Alt+C"),
]
MENU_ACTIONS = ([f"bool_{op}" for op in pathops.OPS] + [None, "path_offset", "text_to_path", None]
                + [name for name, _t, _k in SPLIT_ACTIONS] + [None]
                + pathjoin_ui.MENU_ACTIONS)


class OffsetDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Versatz")
        form = QFormLayout(self)
        self.distance = QDoubleSpinBox()
        self.distance.setRange(*pathops.OFFSET_RANGE)
        self.distance.setDecimals(2)
        self.distance.setSingleStep(0.5)
        self.distance.setValue(2.0)
        self.distance.setSuffix(" mm")
        self.distance.setToolTip("+ nach außen, − nach innen (Linien: Abstand der Kontur)")
        self.join = QComboBox()
        for key, label in (("round", "Rund"), ("miter", "Spitz"), ("bevel", "Abgeschrägt")):
            self.join.addItem(label, key)
        self.replace = QCheckBox("Original ersetzen")
        form.addRow("Abstand", self.distance)
        form.addRow("Ecken", self.join)
        form.addRow("", self.replace)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def values(self) -> dict:
        return {"distance_mm": self.distance.value(), "join": self.join.currentData(),
                "replace": self.replace.isChecked()}


class PathOps:
    def __init__(self, editor) -> None:
        self.editor = editor
        self.ask_offset = self._ask_offset   # für Tests austauschbar

    def _sel_shapes(self):
        ed = self.editor
        ids = [i for i in ed.selection if ed.document.has_shape(i) and ed.document.is_editable(i)]
        return pathops.document_order(ed.document, ids)

    def _apply(self, remove: list[str], add: list, label: str) -> None:
        ed = self.editor
        if not add:
            ed.notify(f"{label}: keine Fläche übrig.")
            return
        ed.undo_stack.push(ReplaceShapesCommand(ed.document, remove, add, label))
        ed.set_selection([s.id for s in add])
        ed.notify(f"{label}: {len(add)} Objekt(e)")

    def boolean(self, op: str) -> None:
        shapes = self._sel_shapes()
        label = pathops.OP_LABELS[op]
        try:
            out = pathops.boolean(shapes, op)
        except pathops.PathOpError as e:
            self.editor.notify(str(e))
            return
        self._apply([s.id for s in shapes], out, label)

    def _ask_offset(self):
        dlg = OffsetDialog(self.editor)
        return dlg.values() if dlg.exec() == QDialog.Accepted else None

    def offset(self) -> None:
        shapes = [s for s in self._sel_shapes() if s.kind != "image"]
        if not shapes:
            self.editor.notify("Für einen Versatz Objekte auswählen.")
            return
        v = self.ask_offset()
        if not v:
            return
        try:
            out = pathops.offset(shapes, v["distance_mm"], v.get("join", "round"))
        except pathops.PathOpError as e:
            self.editor.notify(str(e))
            return
        self._apply([s.id for s in shapes] if v.get("replace") else [], out, "Versatz")

    def text_to_path(self) -> None:
        texts = [s for s in self._sel_shapes() if s.kind == "text"]
        if not texts:
            self.editor.notify("Zum Umwandeln Textobjekte auswählen.")
            return
        ed = self.editor
        ed.undo_stack.beginMacro("Text in Pfade")
        new_ids = []
        try:
            for t in texts:
                out = pathops.text_to_outline(t)
                if out is not None:
                    ed.undo_stack.push(ReplaceShapesCommand(ed.document, [t.id], [out], "Text in Pfad"))
                    new_ids.append(out.id)
        finally:
            ed.undo_stack.endMacro()
        keep = [i for i in ed.selection if ed.document.has_shape(i)]
        ed.set_selection(keep + new_ids)
        ed.notify(f"Text in Pfade: {len(new_ids)} Objekt(e) – unabhängig von installierten Schriften")

    def break_apart(self, keep_holes: bool = True) -> None:
        """LightBurn *Break Apart*: Teilpfade der Auswahl werden eigene Objekte; je Objekt
        an seiner Stelle im Stapel, alles ein Undo-Schritt."""
        ed = self.editor
        shapes = self._sel_shapes()
        if not shapes:
            ed.notify("Zerlegen: Objekte mit mehreren Teilen auswählen "
                      "(z. B. importiertes Logo, Text in Pfade).")
            return
        res = pathsplit.break_apart(shapes, keep_holes)
        if not res.changed:
            ed.notify(res.summary() + ("" if not keep_holes else
                                       " (Löcher bleiben bei ihrer Außenkontur)"))
            return
        ed.undo_stack.beginMacro("Zerlegen")
        try:
            for old, parts in res.pairs:
                ed.undo_stack.push(ReplaceShapesCommand(ed.document, [old], parts, "Zerlegen"))
        finally:
            ed.undo_stack.endMacro()
        keep = [i for i in ed.selection if ed.document.has_shape(i)]
        ed.set_selection(keep + [s.id for s in res.add])
        text = res.summary()
        if keep_holes:
            text += " – Löcher bleiben bei ihrer Außenkontur"
        else:
            text += (" – Löcher sind jetzt eigene Objekte: eine Füllung füllt sie mit, "
                     "„Kombinieren“ (Strg+Alt+C) fasst sie wieder zusammen")
        ed.notify(text)

    def combine(self) -> None:
        """LightBurn *Combine*: Auswahl je Ebene zu einem Objekt mit mehreren Ringen."""
        ed = self.editor
        shapes = self._sel_shapes()
        res = pathsplit.combine(shapes)
        if not res.changed:
            ed.notify(res.summary())
            return
        ed.undo_stack.beginMacro("Kombinieren")
        try:      # je Ebene an der Stelle des untersten Objekts
            for ids, new in res.groups:
                ed.undo_stack.push(ReplaceShapesCommand(ed.document, ids, [new], "Kombinieren"))
        finally:
            ed.undo_stack.endMacro()
        keep = [i for i in ed.selection if ed.document.has_shape(i)]
        ed.set_selection(keep + [s.id for s in res.add])
        ed.notify(res.summary())


def install(editor) -> PathOps:
    ops = PathOps(editor)
    for op in pathops.OPS:
        sc = BOOL_SHORTCUTS.get(op)
        editor._act(f"bool_{op}", pathops.OP_LABELS[op], lambda _=False, op=op: ops.boolean(op),
                    QKeySequence(sc) if sc else None)
    editor._act("path_offset", "Versatz …", ops.offset, QKeySequence("Ctrl+Alt+O"))
    editor._act("text_to_path", "Text in Pfade umwandeln", ops.text_to_path, QKeySequence("Ctrl+Shift+O"))
    split_slots = {"path_break": lambda: ops.break_apart(True),
                   "path_break_all": lambda: ops.break_apart(False), "path_combine": ops.combine}
    for name, text, key in SPLIT_ACTIONS:
        editor._act(name, text, lambda _=False, f=split_slots[name]: f(), QKeySequence(key) if key else None)
    ops.cleanup = pathjoin_ui.install(editor)   # verbinden / schließen / vereinfachen / Duplikate / offene Formen
    return ops


def build_menu(editor, parent=None) -> QMenu:
    menu = QMenu("Pfad", parent or editor)
    menu.setObjectName("PathOpsMenu")
    menu.setIcon(icons.icon("pathops"))
    for name in MENU_ACTIONS:
        menu.addSeparator() if name is None else menu.addAction(editor.actions_by_name[name])
    return menu


def add_to_bar(editor, bar) -> QToolButton:
    btn = QToolButton(bar)
    btn.setObjectName("PathOpsButton")
    btn.setIcon(icons.icon("pathops"))
    btn.setToolTip("Pfad: vereinigen, abziehen, schneiden, verschweißen, versetzen, Text in Pfade, "
                   "zerlegen / kombinieren, Pfade verbinden / schließen / vereinfachen, Duplikate löschen")
    btn.setPopupMode(QToolButton.InstantPopup)
    btn.setMenu(build_menu(editor, btn))
    bar.addWidget(btn)
    return btn
