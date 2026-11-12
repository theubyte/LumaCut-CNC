"""Menü „Anordnen“: „Verschachteln …“ (LightBurn *Nesting* – Quick Nest / True Nest,
xTool „Intelligentes Verschachteln“).

Von :func:`arrange_ui.install` eingebunden (gleiches „Anordnen“-Menü in der
Aktionsleiste und im Kontextmenü). Rechnen in :mod:`nesting`; die Aktion ist
genau ein Undo-Schritt. Bereich: die Auswahl (Teile, optional ein Rechteck als
Material wie bei LightBurn). Kürzel Alt+Umschalt+N („Nesting“).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel)

from . import nesting
from .commands import SetGeometryCommand

ACTIONS = [("nest", "Verschachteln …", "Alt+Shift+N")]
MENU_ACTIONS = [name for name, _t, _k in ACTIONS]


def default_values() -> dict:
    return {"container": "work", "spacing": nesting.SPACING_MM, "margin": nesting.MARGIN_MM,
            "rotation": "90", "corner": "top_right", "form": "true",
            "keep_contained": True, "avoid_others": True}


def _fmt(v: float) -> str:
    return f"{v:.1f}".replace(".", ",")


def _combo(keys, labels, current) -> QComboBox:
    c = QComboBox()
    for k in keys:
        c.addItem(labels[k], k)
    c.setCurrentIndex(max(0, c.findData(current)))
    return c


def _spin(rng, value, tip) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(*rng)
    s.setDecimals(1)
    s.setSingleStep(0.5)
    s.setSuffix(" mm")
    s.setValue(value)
    s.setToolTip(tip)
    return s


class NestDialog(QDialog):
    """Bereich, Abstände, Drehung, Form, Startecke und Optionen; Teile-Zähler."""

    def __init__(self, n_parts: int, container: nesting.Rect | None, parent=None,
                 values: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Verschachteln")
        v = {**default_values(), **(values or {})}
        if container is None:
            v["container"] = "work"
        form = QFormLayout(self)
        self.container = _combo(nesting.CONTAINERS, nesting.CONTAINER_LABELS, v["container"])
        if container is None:   # kein passendes Rechteck in der Auswahl
            self.container.model().item(self.container.findData("rect")).setEnabled(False)
        self.container.setToolTip("Material: das größte ausgewählte Rechteck bleibt stehen und "
                                  "nimmt die Teile auf (wie LightBurn) – sonst die Arbeitsfläche")
        self.spacing = _spin(nesting.SPACING_RANGE, v["spacing"],
                             "Mindestabstand zwischen den Teilen (Schnittbreite, Einlauf und Stege "
                             "mit bedenken)")
        self.margin = _spin(nesting.MARGIN_RANGE, v["margin"],
                            "Mindestabstand der Teile zum Rand des Materials / der Arbeitsfläche")
        self.rotation = _combo(nesting.ROTATIONS, nesting.ROTATION_LABELS, v["rotation"])
        self.rotation.setToolTip("Teile drehen, wenn sie so besser passen (45°: dichter, langsamer). "
                                 "Bei Maserung oder Gravurrichtung „Nicht drehen“ wählen")
        self.form = _combo(nesting.FORMS, nesting.FORM_LABELS, v["form"])
        self.form.setToolTip("Echte Form: Teile greifen ineinander (wie LightBurn True Nest) · "
                             "Hüllbox: Rechtecke um die Teile, ordentliche Reihen (Quick Nest)")
        self.corner = _combo(nesting.CORNERS, nesting.CORNER_LABELS, v["corner"])
        self.corner.setToolTip("Ecke, an der die Teile beginnen – der Rest des Materials bleibt "
                               "am Stück frei")
        self.keep = QCheckBox("Enthaltene Objekte zusammenhalten")
        self.keep.setChecked(bool(v["keep_contained"]))
        self.keep.setToolTip("Gravuren, Texte und Löcher innerhalb eines Teils bewegen sich mit "
                             "dem Teil (wie xTool)")
        self.avoid = QCheckBox("Andere Objekte aussparen")
        self.avoid.setChecked(bool(v["avoid_others"]))
        self.avoid.setToolTip("Nicht ausgewählte sichtbare Objekte im Bereich bleiben frei "
                              "(bereits belegte Stellen auf dem Material)")
        size = "" if container is None else f" · Material {_fmt(container.w)} × {_fmt(container.h)} mm"
        self.readout = QLabel(f"{n_parts} Teil(e) ausgewählt{size}")
        self.readout.setObjectName("NestReadout")
        self.readout.setWordWrap(True)
        form.addRow("Bereich", self.container)
        form.addRow("Abstand", self.spacing)
        form.addRow("Randabstand", self.margin)
        form.addRow("Drehen", self.rotation)
        form.addRow("Form", self.form)
        form.addRow("Beginnen", self.corner)
        form.addRow("", self.keep)
        form.addRow("", self.avoid)
        form.addRow(self.readout)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Verschachteln")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(n_parts > 0)
        form.addRow(self.buttons)

    def values(self) -> dict:
        return {"container": self.container.currentData(), "spacing": self.spacing.value(),
                "margin": self.margin.value(), "rotation": self.rotation.currentData(),
                "corner": self.corner.currentData(), "form": self.form.currentData(),
                "keep_contained": self.keep.isChecked(), "avoid_others": self.avoid.isChecked()}


class Nester:
    def __init__(self, editor) -> None:
        self.editor = editor
        self.last: dict | None = None       # letzte Eingabe (Sitzung)
        self.ask = self._ask                # für Tests austauschbar

    def _ask(self, n_parts: int, container):
        # Bereich folgt der Auswahl: mit Material-Rechteck dieses, sonst die Arbeitsfläche
        vals = {**(self.last or {}), "container": "rect" if container is not None else "work"}
        dlg = NestDialog(n_parts, container, self.editor, vals)
        return dlg.values() if dlg.exec() == QDialog.Accepted else None

    def nest(self) -> None:
        ed = self.editor
        doc = ed.document
        sel = doc.expand_to_groups(ed.selection)
        if not sel:
            ed.notify("Zum Verschachteln Teile auswählen (optional ein Rechteck als Material).")
            return
        cid = nesting.container_candidate(doc, sel)
        n_parts = len([u for u in nesting._units(doc, sel) if u != [cid]])
        if not n_parts:
            ed.notify("Verschachteln: außer dem Material-Rechteck keine Teile ausgewählt.")
            return
        v = self.ask(n_parts, doc.shape(cid).bounds() if cid else None)
        if not v:
            return
        v = {**default_values(), **v}
        self.last = dict(v)
        if v["container"] == "rect" and cid is None:
            v["container"] = "work"
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = nesting.nest(doc, sel, container_id=cid if v["container"] == "rect" else None,
                               spacing=v["spacing"], margin=v["margin"], rotation=v["rotation"],
                               corner=v["corner"], form=v["form"],
                               keep_contained=v["keep_contained"], avoid_others=v["avoid_others"])
        finally:
            QGuiApplication.restoreOverrideCursor()
        moves = {i: g for i, g in res.moves.items()
                 if doc.shape(i).geom.as_tuple() != g.as_tuple() or doc.shape(i).geom.rot != g.rot}
        if moves:
            old = {i: doc.shape(i).geom.copy() for i in moves}
            ed.undo_stack.push(SetGeometryCommand(doc, old, moves, "Verschachteln"))
        ed.notify("Verschachteln: " + res.readout())


def install(editor) -> Nester:
    n = Nester(editor)
    for name, text, key in ACTIONS:
        editor._act(name, text, lambda _=False: n.nest(), QKeySequence(key) if key else None)
    return n
