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

from lumacut_canvas.model import CUT_ORDER_DIRECTIONS, CUT_ORDER_UNITS, CutOrder, Document

#: Anzeigetexte der Richtungen (Reihenfolge wie :data:`CUT_ORDER_DIRECTIONS`).
DIRECTION_LABELS = {"": "aus", "top_bottom": "von oben nach unten",
                    "bottom_top": "von unten nach oben", "left_right": "von links nach rechts",
                    "right_left": "von rechts nach links"}
#: Anzeigetexte der Reihenfolge über Ebenen (wie :data:`CUT_ORDER_UNITS`).
UNIT_LABELS = {"layer": "Nach Ebenen", "group": "Nach Gruppen", "priority": "Nach Priorität"}


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
                      "Pfadvorschau und der Zeitschätzung. Die Ebenen laufen von unten nach "
                      "oben – „Nach Gruppen“ arbeitet jede Gruppe, „Nach Priorität“ jede "
                      "Priorität mit allen ihren Ebenen ab; gilt für das ganze Projekt.")
        info.setWordWrap(True)
        f.addRow(info)
        self.order_by = QComboBox()
        for key in CUT_ORDER_UNITS:
            self.order_by.addItem(UNIT_LABELS[key], key)
        self.order_by.setToolTip(
            "Nach Ebenen: erst alle Objekte der untersten Ebene, dann die nächste Ebene "
            "(Standard).\nNach Gruppen: jede Gruppe (Strg+G) wird mit allen ihren Ebenen fertig "
            "graviert und geschnitten, bevor die nächste beginnt – wie LightBurn „Order by "
            "Group“, z. B. ein Namensschild nach dem anderen. Objekte ohne Gruppe kommen "
            "zusammen zum Schluss.\nNach Priorität: zuerst alle Objekte mit der kleinsten "
            "Priorität (Feld „Priorität“ in der Eigenschaftsleiste) mit allen ihren Ebenen, dann "
            "die nächste – wie LightBurn „Order by Priority“, z. B. Markierungen vor dem "
            "Ausschnitt oder ein bestimmtes Teil zuerst.")
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
                                   "Kopfposition am nächsten liegt. Ein mit dem Werkzeug "
                                   "„Startpunkt“ (Alt+Umschalt+A) gesetzter Start bleibt.")
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
        for label, w in (("Reihenfolge", self.order_by), ("", self.enabled), ("", self.inside_first), ("", self.reduce_travel),
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
        self.order_by.currentIndexChanged.connect(self._update_enabled)
        self.set_value(order)

    def set_value(self, order: CutOrder) -> None:
        self.enabled.setChecked(order.enabled)
        self.inside_first.setChecked(order.inside_first)
        self.reduce_travel.setChecked(order.reduce_travel)
        self.best_start.setChecked(order.best_start)
        self.corners.setChecked(order.corners)
        self.best_direction.setChecked(order.best_direction)
        self.direction.setCurrentIndex(max(0, self.direction.findData(order.direction)))
        self.order_by.setCurrentIndex(max(0, self.order_by.findData(order.order_by)))
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
                        direction=self.direction.currentData() or "",
                        order_by=self.order_by.currentData() or "layer")


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
    if order.by_priority:
        return ("Nach Priorität: kleinere Werte zuerst, jede Priorität mit allen ihren Ebenen "
                "(Feld „Priorität“ in der Eigenschaftsleiste) – „Innere Formen zuerst“ wirkt nur "
                "innerhalb einer Priorität: ein Loch braucht höchstens die Priorität seines Teils.")
    if order.by_group:
        return ("Nach Gruppen: Löcher und Gravuren eines Teils gehören in dieselbe Gruppe – "
                "„Innere Formen zuerst“ wirkt innerhalb jeder Gruppe; Objekte ohne Gruppe "
                "kommen zum Schluss.")
    return ""


def group_count_note(doc: Document) -> str:
    """Hinweis zu „Nach Gruppen“ / „Nach Priorität“ für die Statusleiste („“ = nach Ebenen)."""
    if doc.cut_order.by_priority:
        return priority_count_note(doc)
    if not doc.cut_order.by_group:
        return ""
    from lumacut_canvas.export import cut_units
    groups = sum(1 for gid, _shapes in cut_units(doc) if gid)
    if not groups:
        return " (keine Gruppen im Projekt – läuft wie nach Ebenen)"
    return f" ({groups} Gruppe(n))"


def priority_count_note(doc: Document) -> str:
    """Hinweis zu „Nach Priorität“: verwendete Prioritäten und Konflikte mit inneren Formen."""
    from lumacut_canvas.export import priority_units
    prios = [p for p, _shapes in priority_units(doc)]
    if len(prios) < 2:
        return (" (alle Objekte haben dieselbe Priorität – läuft wie nach Ebenen; Feld "
                "„Priorität“ in der Eigenschaftsleiste)")
    shown = ", ".join(str(p) for p in prios[:8]) + (" …" if len(prios) > 8 else "")
    text = f" ({len(prios)} Prioritäten: {shown})"
    late = priority_conflicts(doc)
    if late:
        text += (f" · Achtung: {late} innere Form(en) mit höherer Priorität als ihre "
                 "Außenform – sie werden erst nach dem Ausschneiden gelasert")
    return text


#: Objektarten, die als Außenform eines Teils gelten (geschlossene Umrisse, kein Text).
OUTER_KINDS = ("rect", "ellipse", "polygon")
#: Höchstens so viele Box-Vergleiche für :func:`priority_conflicts` (große Importe).
CONFLICT_CHECK_LIMIT = 400_000


def priority_conflicts(doc: Document) -> int:
    """Objekte, deren Box in der Box eines geschlossenen Objekts mit *kleinerer*
    Priorität liegt (Loch / Gravur nach dem Ausschnitt seines Teils). 0 bei mehr
    als :data:`CONFLICT_CHECK_LIMIT` Vergleichen."""
    from lumacut_canvas.export import priority_units
    units = priority_units(doc)
    if len(units) < 2:
        return 0
    outers: list = []   # (box) der geschlossenen Objekte kleinerer Priorität
    count = 0
    checks = 0
    for _p, shapes in units:
        boxes = [s.bounds() for s in shapes]
        checks += len(boxes) * len(outers)
        if checks > CONFLICT_CHECK_LIMIT:
            return 0
        for b in boxes:
            if any(o.x <= b.x and o.y <= b.y and b.right <= o.right and b.bottom <= o.bottom
                   and o.w * o.h > b.w * b.h + 1e-6 for o in outers):
                count += 1
        outers.extend(s.bounds() for s in shapes if s.kind in OUTER_KINDS)
    return count


def apply_cut_order(editor, order: CutOrder) -> bool:
    """Einstellungen als einen Undo-Schritt setzen; False, wenn sich nichts ändert."""
    doc = editor.document
    if order == doc.cut_order:
        return False
    editor.undo_stack.push(SetCutOrderCommand(doc, order))
    return True


def summary(order: CutOrder) -> str:
    """Kurztext der Abweichungen vom Standard („Standard“, wenn keine)."""
    unit = (["nach Gruppen"] if order.by_group
            else ["nach Priorität"] if order.by_priority else [])
    if not order.enabled:
        return ", ".join(["Optimierung aus (Zeichenreihenfolge)"] + unit)
    parts = list(unit)
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
