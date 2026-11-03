"""Dialog "PDF417-Code…" and insertion into the design (Qt side of :mod:`lumacut_job.pdf417`).

Same behaviour as the Aztec / Data Matrix dialogs: the modules become filled
``polygon`` objects (one per connected area, holes as rings) in one group on
the **active layer**; when that layer does not fill, a new layer "PDF417" with
0.1 mm hatch is proposed. Insertion is one undo step.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel, QLineEdit, QSpinBox)

from lumacut_canvas.commands import AddLayerCommand, AddShapesCommand
from lumacut_canvas.model import Layer
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from . import pdf417 as pd
from .generated import tag
from .qr_qt import FILL_INTERVAL_MM, layer_fills

FILL_LAYER_NAME = "PDF417"
ISO_ROW_HEIGHT = 3.0


class Pdf417Dialog(QDialog):
    """Settings; ``spec()`` returns the normalized :class:`pdf417.Pdf417Spec`."""

    def __init__(self, parent=None, spec: pd.Pdf417Spec | None = None, active_layer=None):
        super().__init__(parent)
        self.setWindowTitle("PDF417-Code einfügen")
        s = (spec or pd.Pdf417Spec()).normalized()
        form = QFormLayout(self)
        self.text = QLineEdit(s.text)
        self.text.setPlaceholderText("Text, Adresse, Seriennummer oder Datensatz")
        self.text.setToolTip("Beliebiger Text; Buchstaben und Satzzeichen werden als Text "
                             "(2 Zeichen je Codewort), lange Ziffernfolgen numerisch, alles "
                             "andere als Bytes codiert. Umlaute/Unicode als UTF-8 (ECI 26)")
        self.columns = QSpinBox()
        self.columns.setRange(0, pd.COLUMNS_RANGE[1])
        self.columns.setSpecialValueText("Automatisch")
        self.columns.setValue(s.columns)
        self.columns.setToolTip("Datenspalten (1–30, je 17 Module); die Zeilenzahl (3–90) "
                                "ergibt sich. Automatisch: Seitenverhältnis etwa 3 : 1")
        self.ecc = QComboBox()
        self.ecc.addItem("Automatisch (ISO-Empfehlung)", pd.AUTO_ECC)
        for lvl in pd.ECC_LEVELS:
            self.ecc.addItem(f"Stufe {lvl} ({pd.ecc_count(lvl)} Prüfwörter)", lvl)
        self.ecc.setCurrentIndex(max(0, self.ecc.findData(s.ecc_level)))
        self.ecc.setToolTip("Reed-Solomon-Fehlerkorrektur; höhere Stufen machen den Code "
                            "robuster gegen Brandflecken und Kratzer, aber größer")
        self.width_mm = QDoubleSpinBox()
        self.width_mm.setRange(*pd.WIDTH_RANGE)
        self.width_mm.setDecimals(1)
        self.width_mm.setSuffix(" mm")
        self.width_mm.setValue(s.width_mm)
        self.width_mm.setToolTip("Breite des Codes ohne Ruhezone; die Höhe ergibt sich aus "
                                 "Zeilenzahl und Zeilenhöhe")
        self.row_height = QDoubleSpinBox()
        self.row_height.setRange(*pd.ROW_HEIGHT_RANGE)
        self.row_height.setDecimals(2)
        self.row_height.setSingleStep(0.5)
        self.row_height.setSuffix(" × Modul")
        self.row_height.setValue(s.row_height)
        self.row_height.setToolTip("Zeilenhöhe als Vielfaches der Modulbreite (ISO: mindestens 3)")
        self.quiet = QSpinBox()
        self.quiet.setRange(*pd.QUIET_RANGE)
        self.quiet.setSuffix(" Module")
        self.quiet.setValue(s.quiet_zone)
        self.quiet.setToolTip("Heller Rand um den Code (ISO: 2 Module); wird freigehalten, "
                              "invertiert mitgraviert")
        self.compact = QCheckBox("Kompakt (Compact/Truncated PDF417 – schmaler, weniger robust)")
        self.compact.setChecked(s.compact)
        self.compact.setToolTip("Ohne rechte Zeilenkennung, Stopp-Muster nur ein Strich: "
                                "34 Module schmaler")
        self.invert = QCheckBox("Invertiert (helle Module lasern – für Material, das hell wird)")
        self.invert.setChecked(s.invert)
        fills = layer_fills(active_layer)
        name = getattr(active_layer, "name", "")
        self.fill = QCheckBox(f"Neue Ebene „{FILL_LAYER_NAME}“ mit Füllung "
                              f"(Schraffur {FILL_INTERVAL_MM:.1f} mm) anlegen")
        self.fill.setChecked(not fills)
        self.fill.setToolTip("Aus: Code auf die aktive Ebene"
                             + (f" „{name}“" if name else "")
                             + " – sie muss füllen (Schraffur), sonst werden nur Umrisse gelasert")
        self._active_fills = fills
        form.addRow("Inhalt", self.text)
        form.addRow("Spalten", self.columns)
        form.addRow("Fehlerkorrektur", self.ecc)
        form.addRow("Breite", self.width_mm)
        form.addRow("Zeilenhöhe", self.row_height)
        form.addRow("Ruhezone", self.quiet)
        form.addRow("", self.compact)
        form.addRow("", self.invert)
        form.addRow("", self.fill)
        self.info = QLabel()
        self.info.setWordWrap(True)
        form.addRow("Info", self.info)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.Ok)
        self.ok_button.setText("Einfügen")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.text.textChanged.connect(self._update)
        self.columns.valueChanged.connect(self._update)
        self.ecc.currentIndexChanged.connect(self._update)
        self.width_mm.valueChanged.connect(self._update)
        self.row_height.valueChanged.connect(self._update)
        self.quiet.valueChanged.connect(self._update)
        self.compact.toggled.connect(self._update)
        self.fill.toggled.connect(self._update)
        self._update()

    def spec(self) -> pd.Pdf417Spec:
        lvl = self.ecc.currentData()
        return pd.Pdf417Spec(text=self.text.text(), columns=self.columns.value(),
                             ecc_level=pd.AUTO_ECC if lvl is None else lvl,
                             width_mm=self.width_mm.value(), row_height=self.row_height.value(),
                             quiet_zone=self.quiet.value(), compact=self.compact.isChecked(),
                             invert=self.invert.isChecked()).normalized()

    def fill_layer(self) -> bool:
        return self.fill.isChecked()

    def _update(self) -> None:
        s = self.spec()
        try:
            code = s.encode()
        except ValueError as exc:
            self.info.setText(str(exc))
            self.ok_button.setEnabled(False)
            return
        module = s.module_mm(code)
        text = pd.describe(code, s.width_mm, s.row_height)
        ok = module >= pd.HARD_MIN_MODULE_MM - 1e-9
        if not ok:
            text += (f" – zu schmal (Modul mindestens {pd.HARD_MIN_MODULE_MM:.1f} mm): "
                     "breiter machen oder weniger Spalten")
        elif module < pd.MIN_MODULE_MM:
            text += f" – Module unter {pd.MIN_MODULE_MM:.1f} mm evtl. schlecht lesbar"
        if s.row_height < ISO_ROW_HEIGHT:
            text += f" – Zeilenhöhe unter {ISO_ROW_HEIGHT:.0f} × Modul (ISO-Minimum)"
        if code.ecc_level < code.recommended:
            text += (f" – Fehlerkorrektur unter der ISO-Empfehlung (Stufe {code.recommended})")
        if s.quiet_zone < pd.DEFAULT_QUIET and not s.invert:
            text += f" – Ruhezone unter {pd.DEFAULT_QUIET} Modulen"
        tw, th = s.total(code)
        if tw > WORK_WIDTH_MM or th > WORK_HEIGHT_MM:
            text += f" – mit Ruhezone {tw:.0f} × {th:.0f} mm, größer als die Arbeitsfläche"
            ok = False
        if not self.fill.isChecked() and not self._active_fills:
            text += " – Achtung: aktive Ebene füllt nicht, es würden nur Umrisse gelasert"
        self.info.setText(text)
        self.ok_button.setEnabled(ok)


def centered(spec: pd.Pdf417Spec, center: tuple[float, float] | None = None,
             code: pd.Pdf417Code | None = None) -> pd.Pdf417Spec:
    """Spec with X/Y so that the symbol (incl. quiet zone) is centred on ``center``."""
    s = spec.normalized()
    code = code or s.encode()
    tw, th = s.total(code)
    cx, cy = center or (WORK_WIDTH_MM / 2.0, WORK_HEIGHT_MM / 2.0)
    x = min(max(0.0, cx - tw / 2.0), max(0.0, WORK_WIDTH_MM - tw))
    y = min(max(0.0, cy - th / 2.0), max(0.0, WORK_HEIGHT_MM - th))
    return replace(s, x=x, y=y)


def insert_pdf417(editor, spec: pd.Pdf417Spec, fill_layer: bool = False,
                  center: tuple[float, float] | None = None) -> list[str]:
    """Insert the symbol as one group (one undo step, optionally with a new fill layer).

    ``fill_layer`` False: on the active layer. Raises ``ValueError`` (empty/too
    long text, too narrow, does not fit, layer locked).
    """
    doc = editor.document
    s = spec.normalized()
    code = s.encode()
    s = centered(s, center, code)
    active = doc.active_layer or (doc.layers[0] if doc.layers else None)
    layer = None
    if fill_layer:
        layer = Layer(FILL_LAYER_NAME, color=doc.next_layer_color(),
                      power=active.power if active else 50.0,
                      speed=active.speed if active else 1500.0,
                      fill_mode="hatch", line_interval_mm=FILL_INTERVAL_MM, hatch_outline=True)
        layer_id = layer.id
    else:
        if active is None:
            raise ValueError("Keine Ebene vorhanden")
        if active.locked:
            raise ValueError(f"Ebene „{active.name}“ ist gesperrt")
        layer_id = active.id
    shapes = tag(pd.pdf417_shapes(s, layer_id, code), s)
    stack = editor.undo_stack
    stack.beginMacro("PDF417-Code einfügen")
    try:
        if layer is not None:
            stack.push(AddLayerCommand(doc, layer, 0))
        stack.push(AddShapesCommand(doc, shapes, "PDF417-Code"))
    finally:
        stack.endMacro()
    ids = [sh.id for sh in shapes]
    editor.set_selection(ids)
    return ids


__all__ = ["Pdf417Dialog", "centered", "insert_pdf417"]
