"""Menü „Anordnen“: „Entlang Pfad kopieren …“ (LightBurn *Copy Along Path*).

Von :func:`arrange_ui.install` eingebunden (gleiches „Anordnen“-Menü in der
Aktionsleiste und im Kontextmenü). Auswahl: die zu kopierenden Objekte und ein
Pfad (Linie, Pfad, Polygon, Rechteck, Ellipse – :func:`alongpath.pick_path`).
Rechnen in :mod:`alongpath`; das Einfügen ist ein Undo-Schritt. Kürzel
Alt+Umschalt+C („Copy along path“).
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QLabel, QSpinBox)

from . import alongpath
from .alongpath import PathCurve
from .commands import AddShapesCommand

ACTIONS = [("copy_along_path", "Entlang Pfad kopieren …", "Alt+Shift+C")]
MENU_ACTIONS = [name for name, _t, _k in ACTIONS]
TITLE = "Entlang Pfad kopieren"


def default_values() -> dict:
    return {"count": 10, "rotate": True, "start_pct": 0.0}


class CopyAlongDialog(QDialog):
    """Anzahl, mitdrehen, Start (geschlossene Pfade); Abstand live."""

    def __init__(self, curve: PathCurve, parent=None, values: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.curve = curve
        v = {**default_values(), **(values or {})}
        form = QFormLayout(self)
        self.count = QSpinBox()
        self.count.setRange(*alongpath.COUNT_RANGE)
        self.count.setValue(int(v["count"]))
        self.count.setToolTip("Anzahl der Kopien: offener Pfad vom Anfang bis zum Ende, "
                              "geschlossener Pfad mit gleichen Abständen rundherum")
        self.rotate = QCheckBox("Mit dem Pfad drehen")
        self.rotate.setChecked(bool(v["rotate"]))
        self.rotate.setToolTip("Kopien folgen der Pfadrichtung (die Auswahl gilt als nach rechts "
                               "zeigend); aus = alle bleiben wie das Original ausgerichtet")
        self.start = QDoubleSpinBox()
        self.start.setRange(*alongpath.START_RANGE)
        self.start.setDecimals(1)
        self.start.setSuffix(" %")
        self.start.setValue(float(v["start_pct"]))
        self.start.setEnabled(curve.closed)
        self.start.setToolTip("Nur geschlossene Pfade: erste Kopie bei diesem Anteil der Länge "
                              "(0 % = oben in der Mitte, im Uhrzeigersinn)")
        form.addRow("Anzahl", self.count)
        form.addRow("", self.rotate)
        form.addRow("Start", self.start)
        self.readout = QLabel()
        self.readout.setWordWrap(True)
        form.addRow("Info", self.readout)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.count.valueChanged.connect(self._update)
        self._update()

    def _update(self) -> None:
        n = self.count.value()
        L = self.curve.length
        step = L / (n if self.curve.closed else n - 1)
        kind = "geschlossen" if self.curve.closed else "offen"
        self.readout.setText(f"Pfad {L:.1f} mm ({kind}) · Abstand {step:.1f} mm")

    def values(self) -> dict:
        return {"count": self.count.value(), "rotate": self.rotate.isChecked(),
                "start_pct": self.start.value()}


class CopyAlong:
    def __init__(self, editor) -> None:
        self.editor = editor
        self.last = default_values()        # letzte Eingabe (Sitzung)
        self.ask = self._ask                # für Tests austauschbar

    def _ask(self, curve: PathCurve):
        dlg = CopyAlongDialog(curve, self.editor, self.last)
        return dlg.values() if dlg.exec() == QDialog.Accepted else None

    def copy(self) -> list[str]:
        ed = self.editor
        doc = ed.document
        sel = doc.expand_to_groups(ed.selection)
        pid = alongpath.pick_path(doc, sel)
        if pid is None or len(sel) < 2:
            ed.notify(f"{TITLE}: Objekte und einen Pfad (Linie, Pfad, Polygon, Rechteck oder "
                      "Ellipse) auswählen.")
            return []
        try:
            curve = alongpath.shape_curve(doc.shape(pid))
        except ValueError as exc:
            ed.notify(f"{TITLE}: {exc}")
            return []
        v = self.ask(curve)
        if not v:
            return []
        v = {**default_values(), **v}
        self.last = dict(v)
        rest = [i for i in sel if i != pid]
        try:
            res = alongpath.copy_along(doc, rest, curve, v["count"], v["rotate"], v["start_pct"])
        except ValueError as exc:
            ed.notify(f"{TITLE}: {exc}")
            return []
        n_out = alongpath.outside_count(res.shapes)
        if n_out:
            ed.notify(f"{TITLE}: {n_out} Objekt(e) lägen außerhalb der Arbeitsfläche – kleinere "
                      "Objekte oder einen Pfad weiter innen wählen.")
            return []
        if len(res.shapes) > 5000:
            ed.notify(f"{TITLE}: zu viele Objekte ({len(res.shapes)} > 5000).")
            return []
        ed.undo_stack.push(AddShapesCommand(doc, res.shapes, TITLE))
        ids = [s.id for s in res.shapes]
        ed.set_selection(ids)
        ed.notify(f"{TITLE}: " + res.readout())
        return ids


def install(editor) -> CopyAlong:
    tool = CopyAlong(editor)
    for name, text, key in ACTIONS:
        editor._act(name, text, lambda _=False: tool.copy(), QKeySequence(key) if key else None)
    return tool
