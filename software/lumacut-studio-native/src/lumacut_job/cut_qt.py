"""Dialog „Schnittoptionen der Ebene“: Kerf-Versatz, Haltestege (inkl. höchstens N
Stege, Steg-Leistung und „Innere Formen ohne Stege“), An-/Abfahrt, Überschnitt,
Perforation und „Überlappende Linien entfernen“.

Bearbeitet die Ebenen-Felder aus :data:`lumacut_canvas.model.CUT_LAYER_DEFAULTS`
als *einen* Undo-Schritt (``SetLayerAttrsCommand``). Die Werte wirken im Planer
(:mod:`lumacut_job.cutpath`) beim Senden, Schätzen und Rahmen.
"""

from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel, QSpinBox)

from lumacut_canvas.commands import SetLayerAttrsCommand
from lumacut_canvas.model import (CUT_LAYER_DEFAULTS, CUT_LAYER_FIELDS, KERF_RANGE, LEAD_RANGE,
                                  OVERCUT_RANGE, OVERLAP_DEFAULT_MM, OVERLAP_RANGE, PERF_RANGE, TAB_COUNT_RANGE,
                                  TAB_CUT_POWER_RANGE, TAB_MAX_RANGE, TAB_SPACING_RANGE,
                                  TAB_WIDTH_RANGE, Layer)


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
        self.tab_width.setToolTip("Breite jedes Stegs – auch der manuellen Stege (Werkzeug „Stege“, "
                                  "Alt+Umschalt+T); 0 = keine Stege auf dieser Ebene")
        self.tab_spacing = _dspin(TAB_SPACING_RANGE, layer.tab_spacing_mm, 5.0,
                                  special="feste Anzahl")
        self.tab_spacing.setToolTip("> 0: ein Steg je Abstand entlang des Umfangs "
                                    "(Anzahl wird dann ignoriert)")
        self.tab_max = QSpinBox()
        self.tab_max.setRange(*TAB_MAX_RANGE)
        self.tab_max.setSpecialValueText("unbegrenzt")
        self.tab_max.setValue(layer.tab_max)
        self.tab_max.setToolTip("Nur mit Haltesteg-Abstand: höchstens so viele Stege je Kontur "
                                "(lange Konturen bekommen sonst sehr viele)")
        self.tab_power = _dspin(TAB_CUT_POWER_RANGE, layer.tab_cut_power, 5.0, suffix=" %",
                                special="aus (Lücke)", decimals=0)
        self.tab_power.setToolTip(
            "Statt den Steg ganz auszulassen, wird er mit kurzen Pulsen quer angeschnitten "
            "(Anteil der Laser-an-Zeit in %, mit der Leistung der Ebene). Höher = Steg "
            "schwächer und leichter auszubrechen; der Kopf fährt ohne Halt weiter.")
        self.tab_skip_inner = QCheckBox("Innere Formen ohne Stege")
        self.tab_skip_inner.setChecked(layer.tab_skip_inner)
        self.tab_skip_inner.setToolTip(
            "Konturen, die ganz in einer anderen Kontur dieser Ebene liegen (Löcher, "
            "Buchstaben-Innenformen, Teile in einem Rahmen), bekommen keine Haltestege.")
        self.tabs_hint = QLabel("")
        self.tabs_hint.setWordWrap(True)
        self.lead_in = _dspin(LEAD_RANGE, layer.lead_in_mm, 0.5, special="aus")
        self.lead_arc = QCheckBox("als Bogen (tangential)")
        self.lead_arc.setChecked(layer.lead_in_arc)
        self.lead_out = _dspin(LEAD_RANGE, layer.lead_out_mm, 0.5, special="aus")
        self.overcut = _dspin(OVERCUT_RANGE, layer.overcut_mm, 0.1, special="aus")
        self.overcut.setToolTip("Geschlossene Konturen über den Startpunkt hinaus weiter schneiden, "
                                "damit kein Faden stehen bleibt (z. B. 0,5–1 mm)")
        self.perf_cut = _dspin(PERF_RANGE, layer.perf_cut_mm, 0.1, special="aus")
        self.perf_cut.setToolTip("Perforation: so viel schneiden, dann die Lücke mit Laser aus "
                                 "überspringen (Reiß- und Falzlinien). 0,1–0,3 mm ergibt eine Punktlinie.")
        self.perf_skip = _dspin(PERF_RANGE, layer.perf_skip_mm, 0.1)
        self.perf_skip.setToolTip("Perforation: Länge der Lücke ohne Laser")
        self.overlap = _dspin(OVERLAP_RANGE, layer.overlap_tol_mm, 0.01, special="aus",
                              decimals=3)
        self.overlap.setToolTip(
            "Linien, die schon einmal geschnitten wurden (gemeinsame Kante zweier Teile, "
            "teilweise übereinander liegende Strecken), nur einmal schneiden. Wert = "
            f"Toleranz, z. B. {OVERLAP_DEFAULT_MM:g} mm. Nur Konturen/Linien – Füllungen und "
            "Bilder bleiben; wirkt nicht zusammen mit Kerf, Stegen, An-/Abfahrt oder Überschnitt.")
        self.overlap_hint = QLabel("")
        self.overlap_hint.setWordWrap(True)
        self.perf_cut.valueChanged.connect(self._update_enabled)
        for w in (self.overlap, self.kerf, self.lead_in, self.lead_out, self.overcut,
                  self.tab_width, self.tab_spacing):
            w.valueChanged.connect(self._update_enabled)
        self.tab_count.valueChanged.connect(self._update_enabled)
        self.tab_power.valueChanged.connect(self._update_enabled)
        for label, w in (("Kerf-Versatz", self.kerf), ("Haltestege Anzahl", self.tab_count),
                         ("Haltesteg-Breite", self.tab_width), ("Haltesteg-Abstand", self.tab_spacing),
                         ("Höchstens Stege je Kontur", self.tab_max),
                         ("Steg-Leistung", self.tab_power), ("", self.tab_skip_inner),
                         ("", self.tabs_hint),
                         ("Anfahrt (Lead-in)", self.lead_in), ("", self.lead_arc),
                         ("Abfahrt (Lead-out)", self.lead_out), ("Überschnitt", self.overcut),
                         ("Perforation Schnitt", self.perf_cut),
                         ("Perforation Lücke", self.perf_skip),
                         ("Überlappende Linien entfernen", self.overlap),
                         ("", self.overlap_hint)):
            f.addRow(label, w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel
                              | QDialogButtonBox.RestoreDefaults)
        bb.button(QDialogButtonBox.RestoreDefaults).setText("Zurücksetzen")
        bb.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self._update_enabled()

    def _contour_options_on(self) -> bool:
        return bool(self.kerf.value() or self.lead_in.value() > 0 or self.lead_out.value() > 0
                    or self.overcut.value() > 0
                    or (self.tab_width.value() > 0
                        and (self.tab_count.value() > 0 or self.tab_spacing.value() > 0)))

    def _tabs_on(self) -> bool:
        return self.tab_width.value() > 0 and (self.tab_count.value() > 0
                                               or self.tab_spacing.value() > 0)

    def _update_enabled(self) -> None:
        self.perf_skip.setEnabled(self.perf_cut.value() > 0)
        tabs = self._tabs_on()
        self.tab_max.setEnabled(tabs and self.tab_spacing.value() > 0)
        self.tab_power.setEnabled(tabs)
        self.tab_skip_inner.setEnabled(tabs)
        self.tabs_hint.setText(tab_power_hint(self.tab_width.value(), self.tab_power.value())
                               if tabs else "")
        self.tabs_hint.setVisible(bool(self.tabs_hint.text()))
        blocked = self.overlap.value() > 0 and self._contour_options_on()
        self.overlap_hint.setText(
            "Wirkt nicht: Kerf / Stege / An-/Abfahrt / Überschnitt brauchen ganze Konturen – "
            "Überlappungen dieser Ebene werden nicht entfernt." if blocked else "")
        self.overlap_hint.setVisible(blocked)

    def restore_defaults(self) -> None:
        d = CUT_LAYER_DEFAULTS
        self.kerf.setValue(d["kerf_mm"])
        self.tab_count.setValue(d["tab_count"])
        self.tab_width.setValue(d["tab_width_mm"])
        self.tab_spacing.setValue(d["tab_spacing_mm"])
        self.tab_max.setValue(d["tab_max"])
        self.tab_power.setValue(d["tab_cut_power"])
        self.tab_skip_inner.setChecked(d["tab_skip_inner"])
        self.lead_in.setValue(d["lead_in_mm"])
        self.lead_arc.setChecked(d["lead_in_arc"])
        self.lead_out.setValue(d["lead_out_mm"])
        self.overcut.setValue(d["overcut_mm"])
        self.perf_cut.setValue(d["perf_cut_mm"])
        self.perf_skip.setValue(d["perf_skip_mm"])
        self.overlap.setValue(d["overlap_tol_mm"])

    def values(self) -> dict:
        return {"kerf_mm": self.kerf.value(), "tab_count": self.tab_count.value(),
                "tab_width_mm": self.tab_width.value(), "tab_spacing_mm": self.tab_spacing.value(),
                "lead_in_mm": self.lead_in.value(), "lead_in_arc": self.lead_arc.isChecked(),
                "lead_out_mm": self.lead_out.value(), "overcut_mm": self.overcut.value(),
                "perf_cut_mm": self.perf_cut.value(), "perf_skip_mm": self.perf_skip.value(),
                "overlap_tol_mm": self.overlap.value(),
                "tab_skip_inner": self.tab_skip_inner.isChecked(),
                "tab_max": self.tab_max.value(), "tab_cut_power": self.tab_power.value()}


def tab_power_hint(width_mm: float, power: float) -> str:
    """Kurzer Text, wie ein Steg mit Steg-Leistung geschnitten wird (leer bei 0 %)."""
    from .cutpath import KIND_TAB_PULSE, tab_pulses
    if power <= 0 or width_mm <= 0:
        return ""
    pulses = tab_pulses([(0.0, 0.0), (width_mm, 0.0)], power)
    on = [p for p, k in pulses if k == KIND_TAB_PULSE]
    if not on:
        return "Steg-Leistung zu klein für diese Breite – der Steg bleibt ganz stehen."
    each = on[0][-1][0] - on[0][0][0]
    n = len(on)
    return (f"Je Steg {n} Puls{'e' if n != 1 else ''} à {each:.2f} mm".replace(".", ",")
            + " mit der Leistung der Ebene, dazwischen Laser aus.")


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
    tabs_on = layer.tab_width_mm > 0 and (layer.tab_count > 0 or layer.tab_spacing_mm > 0)
    if tabs_on and layer.tab_spacing_mm > 0 and getattr(layer, "tab_max", 0) > 0:
        parts.append(f"höchstens {layer.tab_max} Stege")
    if tabs_on and getattr(layer, "tab_cut_power", 0.0) > 0:
        parts.append(f"Steg-Leistung {layer.tab_cut_power:g} %")
    if tabs_on and getattr(layer, "tab_skip_inner", False):
        parts.append("innere Formen ohne Stege")
    if layer.lead_in_mm:
        parts.append(f"Anfahrt {layer.lead_in_mm:g} mm" + (" Bogen" if layer.lead_in_arc else ""))
    if layer.lead_out_mm:
        parts.append(f"Abfahrt {layer.lead_out_mm:g} mm")
    if layer.overcut_mm:
        parts.append(f"Überschnitt {layer.overcut_mm:g} mm")
    if layer.perf_cut_mm > 0 and layer.perf_skip_mm > 0:
        parts.append(f"Perforation {layer.perf_cut_mm:g}/{layer.perf_skip_mm:g} mm")
    if getattr(layer, "overlap_tol_mm", 0.0) > 0:
        parts.append(f"Überlappungen entfernen ({layer.overlap_tol_mm:g} mm)")
    return ", ".join(parts)
