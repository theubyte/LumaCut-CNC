"""Dialog "Data Matrix…" and insertion into the design (Qt side of :mod:`lumacut_job.datamatrix`).

Same behaviour as the QR code dialog: the modules become filled ``polygon``
objects (one per connected area, holes as rings) in one group on the
**active layer**; when that layer does not fill, a new layer "Data Matrix"
with 0.1 mm hatch is proposed. Insertion is one undo step.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel, QLineEdit, QSpinBox)

from lumacut_canvas.commands import AddLayerCommand, AddShapesCommand
from lumacut_canvas.model import Layer
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from . import datamatrix as dm
from .qr_qt import FILL_INTERVAL_MM, layer_fills

FILL_LAYER_NAME = "Data Matrix"


class DataMatrixDialog(QDialog):
    """Settings; ``spec()`` returns the normalized :class:`datamatrix.DataMatrixSpec`."""

    def __init__(self, parent=None, spec: dm.DataMatrixSpec | None = None, active_layer=None):
        super().__init__(parent)
        self.setWindowTitle("Data Matrix einfügen")
        s = (spec or dm.DataMatrixSpec()).normalized()
        form = QFormLayout(self)
        self.text = QLineEdit(s.text)
        self.text.setPlaceholderText("Text oder Seriennummer, z. B. LC-2026-0815")
        self.text.setToolTip("Beliebiger Text; Ziffernpaare werden kompakt codiert, "
                             "Umlaute/Unicode erlaubt")
        self.symbol = QComboBox()
        self.symbol.addItem("Automatisch (kleinste passende)", dm.AUTO)
        for n in dm.SIZES:
            self.symbol.addItem(f"{n} × {n} Module (bis {dm.SYMBOLS[n][2]} Codewörter)", n)
        self.symbol.setCurrentIndex(self.symbol.findData(s.symbol))
        self.symbol.setToolTip("Mindestgröße des Symbols; reicht sie nicht, wird die nächste "
                               "passende gewählt")
        self.size_mm = QDoubleSpinBox()
        self.size_mm.setRange(*dm.SIZE_RANGE)
        self.size_mm.setDecimals(1)
        self.size_mm.setSuffix(" mm")
        self.size_mm.setValue(s.size_mm)
        self.size_mm.setToolTip("Kantenlänge des Codes ohne Ruhezone")
        self.quiet = QSpinBox()
        self.quiet.setRange(*dm.QUIET_RANGE)
        self.quiet.setSuffix(" Module")
        self.quiet.setValue(s.quiet_zone)
        self.quiet.setToolTip("Heller Rand um den Code (Norm: mindestens 1 Modul); wird "
                              "freigehalten, invertiert mitgraviert")
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
        form.addRow("Symbolgröße", self.symbol)
        form.addRow("Größe", self.size_mm)
        form.addRow("Ruhezone", self.quiet)
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
        self.symbol.currentIndexChanged.connect(self._update)
        self.size_mm.valueChanged.connect(self._update)
        self.quiet.valueChanged.connect(self._update)
        self.fill.toggled.connect(self._update)
        self._update()

    def spec(self) -> dm.DataMatrixSpec:
        return dm.DataMatrixSpec(text=self.text.text(), symbol=int(self.symbol.currentData() or 0),
                                 size_mm=self.size_mm.value(), quiet_zone=self.quiet.value(),
                                 invert=self.invert.isChecked()).normalized()

    def fill_layer(self) -> bool:
        return self.fill.isChecked()

    def _update(self) -> None:
        s = self.spec()
        try:
            code = dm.encode(s.text, s.symbol)
        except ValueError as exc:
            self.info.setText(str(exc))
            self.ok_button.setEnabled(False)
            return
        module = s.size_mm / code.size
        text = dm.describe(code, s.size_mm)
        if s.symbol and code.size != s.symbol:
            text += f" – {s.symbol} × {s.symbol} reicht nicht, nächste passende Größe gewählt"
        ok = module >= dm.HARD_MIN_MODULE_MM
        if not ok:
            text += f" – zu klein (mindestens {dm.HARD_MIN_MODULE_MM:.1f} mm)"
        elif module < dm.MIN_MODULE_MM:
            text += f" – unter {dm.MIN_MODULE_MM:.1f} mm evtl. schlecht lesbar"
        total = s.total_mm(code)
        if total > min(WORK_WIDTH_MM, WORK_HEIGHT_MM):
            text += f" – mit Ruhezone {total:.0f} mm, größer als die Arbeitsfläche"
            ok = False
        if not self.fill.isChecked() and not self._active_fills:
            text += " – Achtung: aktive Ebene füllt nicht, es würden nur Umrisse gelasert"
        self.info.setText(text)
        self.ok_button.setEnabled(ok)


def centered(spec: dm.DataMatrixSpec, center: tuple[float, float] | None = None,
             code: dm.DataMatrix | None = None) -> dm.DataMatrixSpec:
    """Spec with X/Y so that the symbol (incl. quiet zone) is centred on ``center``."""
    s = spec.normalized()
    code = code or dm.encode(s.text, s.symbol)
    total = s.total_mm(code)
    cx, cy = center or (WORK_WIDTH_MM / 2.0, WORK_HEIGHT_MM / 2.0)
    x = min(max(0.0, cx - total / 2.0), max(0.0, WORK_WIDTH_MM - total))
    y = min(max(0.0, cy - total / 2.0), max(0.0, WORK_HEIGHT_MM - total))
    return replace(s, x=x, y=y)


def insert_datamatrix(editor, spec: dm.DataMatrixSpec, fill_layer: bool = False,
                      center: tuple[float, float] | None = None) -> list[str]:
    """Insert the symbol as one group (one undo step, optionally with a new fill layer).

    ``fill_layer`` False: on the active layer. Raises ``ValueError`` (empty/too
    long text, too small, does not fit, layer locked).
    """
    doc = editor.document
    s = spec.normalized()
    code = dm.encode(s.text, s.symbol)
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
    shapes = dm.datamatrix_shapes(s, layer_id, code)
    stack = editor.undo_stack
    stack.beginMacro("Data Matrix einfügen")
    try:
        if layer is not None:
            stack.push(AddLayerCommand(doc, layer, 0))
        stack.push(AddShapesCommand(doc, shapes, "Data Matrix"))
    finally:
        stack.endMacro()
    ids = [sh.id for sh in shapes]
    editor.set_selection(ids)
    return ids


__all__ = ["DataMatrixDialog", "centered", "insert_datamatrix"]
