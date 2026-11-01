"""Dialog „QR-Code…“ und Einfügen in den Entwurf (Qt-Teil zu :mod:`lumacut_job.qr`).

Die Module landen als gefüllte ``polygon``-Objekte (eine Fläche je
zusammenhängendem Bereich, Löcher als Ringe) auf der **aktiven Ebene** und
werden dort wie jedes andere Objekt nach der Ebenen-Füllung (Schraffur/
Kreuzschraffur) graviert. Füllt die aktive Ebene nicht, schlägt der Dialog
eine eigene Ebene „QR-Code“ mit Schraffur 0,1 mm vor – sonst würden nur die
Umrisse gelasert und der Code wäre nicht lesbar.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel, QLineEdit, QSpinBox)

from lumacut_canvas.commands import AddLayerCommand, AddShapesCommand
from lumacut_canvas.model import Layer
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from . import qr

# Füll-Ebene für neue QR-Codes: Schraffur 0,1 mm, Kontur mitlasern (scharfe Kanten).
FILL_INTERVAL_MM = 0.1
FILL_LAYER_NAME = "QR-Code"


def layer_fills(layer) -> bool:
    return layer is not None and getattr(layer, "fill_mode", "none") != "none"


class QrDialog(QDialog):
    """Einstellungen; ``spec()`` liefert die normalisierte :class:`qr.QrSpec`."""

    def __init__(self, parent=None, spec: qr.QrSpec | None = None, active_layer=None):
        super().__init__(parent)
        self.setWindowTitle("QR-Code einfügen")
        s = (spec or qr.QrSpec()).normalized()
        form = QFormLayout(self)
        self.text = QLineEdit(s.text)
        self.text.setPlaceholderText("Text oder Adresse, z. B. https://example.com")
        self.text.setToolTip("Beliebiger Text (UTF-8, Umlaute erlaubt), Web-Adresse, WLAN-Daten …")
        self.ec = QComboBox()
        for key in qr.EC_LEVELS:
            self.ec.addItem(qr.EC_LABELS[key], key)
        self.ec.setCurrentIndex(qr.EC_LEVELS.index(s.ec))
        self.ec.setToolTip("Fehlerkorrektur: höher = robuster gegen Kratzer/Brandspuren, "
                           "aber mehr und kleinere Module")
        self.size_mm = QDoubleSpinBox()
        self.size_mm.setRange(*qr.SIZE_RANGE)
        self.size_mm.setDecimals(1)
        self.size_mm.setSuffix(" mm")
        self.size_mm.setValue(s.size_mm)
        self.size_mm.setToolTip("Kantenlänge des Codes ohne Ruhezone")
        self.quiet = QSpinBox()
        self.quiet.setRange(*qr.QUIET_RANGE)
        self.quiet.setSuffix(" Module")
        self.quiet.setValue(s.quiet_zone)
        self.quiet.setToolTip("Heller Rand um den Code (Norm: 4 Module); wird freigehalten, "
                              "invertiert mitgraviert")
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
        form.addRow("Fehlerkorrektur", self.ec)
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
        self.ec.currentIndexChanged.connect(self._update)
        self.size_mm.valueChanged.connect(self._update)
        self.quiet.valueChanged.connect(self._update)
        self.fill.toggled.connect(self._update)
        self._update()

    def spec(self) -> qr.QrSpec:
        return qr.QrSpec(text=self.text.text(), ec=self.ec.currentData(),
                         size_mm=self.size_mm.value(), quiet_zone=self.quiet.value(),
                         invert=self.invert.isChecked()).normalized()

    def fill_layer(self) -> bool:
        return self.fill.isChecked()

    def _update(self) -> None:
        s = self.spec()
        try:
            code = qr.encode(s.text, s.ec)
        except ValueError as exc:
            self.info.setText(str(exc))
            self.ok_button.setEnabled(False)
            return
        module = s.size_mm / code.size
        text = qr.describe(code, s.size_mm)
        ok = module >= qr.HARD_MIN_MODULE_MM
        if not ok:
            text += f" – zu klein (mindestens {qr.HARD_MIN_MODULE_MM:.1f} mm)"
        elif module < qr.MIN_MODULE_MM:
            text += f" – unter {qr.MIN_MODULE_MM:.1f} mm evtl. schlecht lesbar"
        total = s.total_mm(code)
        if total > min(WORK_WIDTH_MM, WORK_HEIGHT_MM):
            text += f" – mit Ruhezone {total:.0f} mm, größer als die Arbeitsfläche"
            ok = False
        if not self.fill.isChecked() and not self._active_fills:
            text += " – Achtung: aktive Ebene füllt nicht, es würden nur Umrisse gelasert"
        self.info.setText(text)
        self.ok_button.setEnabled(ok)


def centered(spec: qr.QrSpec, center: tuple[float, float] | None = None,
             code: qr.QrCode | None = None) -> qr.QrSpec:
    """Spec mit X/Y so, dass der Code (inkl. Ruhezone) um ``center`` liegt."""
    s = spec.normalized()
    code = code or qr.encode(s.text, s.ec)
    total = s.total_mm(code)
    cx, cy = center or (WORK_WIDTH_MM / 2.0, WORK_HEIGHT_MM / 2.0)
    x = min(max(0.0, cx - total / 2.0), max(0.0, WORK_WIDTH_MM - total))
    y = min(max(0.0, cy - total / 2.0), max(0.0, WORK_HEIGHT_MM - total))
    return replace(s, x=x, y=y)


def insert_qr(editor, spec: qr.QrSpec, fill_layer: bool = False,
              center: tuple[float, float] | None = None) -> list[str]:
    """QR-Code als Gruppe einfügen (ein Undo-Schritt, ggf. mit neuer Füll-Ebene).

    ``fill_layer`` False: auf die aktive Ebene. Wirft ``ValueError`` (leerer/zu
    langer Text, zu klein, passt nicht, Ebene gesperrt).
    """
    doc = editor.document
    s = spec.normalized()
    code = qr.encode(s.text, s.ec)
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
    shapes = qr.qr_shapes(s, layer_id, code)
    stack = editor.undo_stack
    stack.beginMacro("QR-Code einfügen")
    try:
        if layer is not None:
            stack.push(AddLayerCommand(doc, layer, 0))
        stack.push(AddShapesCommand(doc, shapes, "QR-Code"))
    finally:
        stack.endMacro()
    ids = [sh.id for sh in shapes]
    editor.set_selection(ids)
    return ids


__all__ = ["QrDialog", "centered", "insert_qr", "layer_fills"]
