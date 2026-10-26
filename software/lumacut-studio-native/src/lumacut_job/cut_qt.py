"""Dialog „Schnittoptionen der Ebene“: Kerf-Versatz, Haltestege, An-/Abfahrt.

Bearbeitet die Ebenen-Felder aus :data:`lumacut_canvas.model.CUT_LAYER_DEFAULTS`
als *einen* Undo-Schritt (``SetLayerAttrsCommand``). Die Werte wirken im Planer
(:mod:`lumacut_job.cutpath`) beim Senden, Schätzen und Rahmen.
"""

from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel, QSpinBox)

from lumacut_canvas.commands import SetLayerAttrsCommand
from lumacut_canvas.model import (CUT_LAYER_DEFAULTS, CUT_LAYER_FIELDS, KERF_RANGE, LEAD_RANGE,
                                  TAB_COUNT_RANGE, TAB_SPACING_RANGE, TAB_WIDTH_RANGE, Layer)


def _dspin(rng, value, step, suffix=" mm", special="", decimals=2):
    w = QDoubleSpinBox()
    w.setRange(*rng)
    w.setDecimals(decimals)
    w.setSingleStep(step)
    w.setSuffix(suffix)
    if special:
        w.setSpecialValueText(special)
    w.setValue(value)
    return w


class CutOptionsDialog(QDialog):
    """Schnittoptionen einer Ebene; :meth:`values` liefert die Feld-Werte."""

    def __init__(self, layer: Layer, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Schnittoptionen – {layer.name}")
        f = QFormLayout(self)
        info = QLabel("Gilt für geschlossene Konturen dieser Ebene. Positiver Versatz "
                      "verschiebt den Schnitt zur Abfallseite (Teil bleibt maßhaltig).")
        info.setWordWrap(True)
        f.addRow(info)
        self.kerf = _dspin(KERF_RANGE, layer.kerf_mm, 0.01, decimals=3)
        self.kerf.setToolTip("Halbe Schnittfugenbreite, z. B. 0,08 mm bei Holz 3 mm")
        self.tab_count = QSpinBox()
        self.tab_count.setRange(*TAB_COUNT_RANGE)
        self.tab_count.setSpecialValueText("aus")
        self.tab_count.setValue(layer.tab_count)
        self.tab_width = _dspin(TAB_WIDTH_RANGE, layer.tab_width_mm, 0.1)
        self.tab_spacing = _dspin(TAB_SPACING_RANGE, layer.tab_spacing_mm, 5.0,
                                  special="feste Anzahl")
        self.tab_spacing.setToolTip("> 0: ein Steg je Abstand entlang des Umfangs "
                                    "(Anzahl wird dann ignoriert)")
        self.lead_in = _dspin(LEAD_RANGE, layer.lead_in_mm, 0.5, special="aus")
        self.lead_arc = QCheckBox("als Bogen (tangential)")
        self.lead_arc.setChecked(layer.lead_in_arc)
        self.lead_out = _dspin(LEAD_RANGE, layer.lead_out_mm, 0.5, special="aus")
        for label, w in (("Kerf-Versatz", self.kerf), ("Haltestege Anzahl", self.tab_count),
                         ("Haltesteg-Breite", self.tab_width), ("Haltesteg-Abstand", self.tab_spacing),
                         ("Anfahrt (Lead-in)", self.lead_in), ("", self.lead_arc),
                         ("Abfahrt (Lead-out)", self.lead_out)):
            f.addRow(label, w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel
                              | QDialogButtonBox.RestoreDefaults)
        bb.button(QDialogButtonBox.RestoreDefaults).setText("Zurücksetzen")
        bb.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def restore_defaults(self) -> None:
        d = CUT_LAYER_DEFAULTS
        self.kerf.setValue(d["kerf_mm"])
        self.tab_count.setValue(d["tab_count"])
        self.tab_width.setValue(d["tab_width_mm"])
        self.tab_spacing.setValue(d["tab_spacing_mm"])
        self.lead_in.setValue(d["lead_in_mm"])
        self.lead_arc.setChecked(d["lead_in_arc"])
        self.lead_out.setValue(d["lead_out_mm"])

    def values(self) -> dict:
        return {"kerf_mm": self.kerf.value(), "tab_count": self.tab_count.value(),
                "tab_width_mm": self.tab_width.value(), "tab_spacing_mm": self.tab_spacing.value(),
                "lead_in_mm": self.lead_in.value(), "lead_in_arc": self.lead_arc.isChecked(),
                "lead_out_mm": self.lead_out.value()}


def apply_cut_options(editor, layer_id: str, values: dict) -> bool:
    """Werte als einen Undo-Schritt setzen; False, wenn sich nichts ändert."""
    doc = editor.document
    layer = doc.layer(layer_id)
    attrs = {k: v for k, v in values.items()
             if k in CUT_LAYER_FIELDS and getattr(layer, k) != v}
    if not attrs:
        return False
    editor.undo_stack.push(SetLayerAttrsCommand(doc, layer_id, attrs, "Schnittoptionen"))
    return True


def summary(layer: Layer) -> str:
    """Kurztext der aktiven Schnittoptionen (leer, wenn alle aus)."""
    parts = []
    if layer.kerf_mm:
        parts.append(f"Kerf {layer.kerf_mm:+.2f} mm")
    if layer.tab_spacing_mm > 0:
        parts.append(f"Stege je {layer.tab_spacing_mm:g} mm")
    elif layer.tab_count:
        parts.append(f"{layer.tab_count} Stege")
    if layer.lead_in_mm:
        parts.append(f"Anfahrt {layer.lead_in_mm:g} mm" + (" Bogen" if layer.lead_in_arc else ""))
    if layer.lead_out_mm:
        parts.append(f"Abfahrt {layer.lead_out_mm:g} mm")
    return ", ".join(parts)
