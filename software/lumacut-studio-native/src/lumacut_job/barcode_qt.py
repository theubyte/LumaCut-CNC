"""Dialog "Barcode einfügen…" and insertion into the design (Qt side of :mod:`lumacut_job.barcode`).

Bars become filled rectangle ``polygon`` objects on the **active layer**, the
human-readable line becomes glyph outlines (:func:`arctext_qt.glyphs_for`).
Like the QR code dialog, a new layer "Barcode" with 0.1 mm hatch fill is
proposed when the active layer does not fill – otherwise only the outlines
would be lasered.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFontComboBox, QFormLayout, QLabel, QLineEdit)

from lumacut_canvas.commands import AddLayerCommand, AddShapesCommand
from lumacut_canvas.model import Layer

from . import barcode
from .arctext_qt import glyphs_for
from .generated import tag
from .qr_qt import FILL_INTERVAL_MM, layer_fills

FILL_LAYER_NAME = "Barcode"
PLACEHOLDERS = {"code128": "Text oder Nummer, z. B. LC-2026-0815",
                "gs1_128": "(AI)Wert, z. B. (01)09501101530003(17)261231(10)AB-12",
                "ean13": "12 Ziffern (Prüfziffer wird ergänzt) oder 13",
                "ean8": "7 Ziffern (Prüfziffer wird ergänzt) oder 8",
                "upca": "11 Ziffern (Prüfziffer wird ergänzt) oder 12"}
EXAMPLES = {"code128": "LumaCut", "gs1_128": "(01)09501101530003(10)AB-12",
            "ean13": "400638133393", "ean8": "9638507", "upca": "03600029145"}


def glyph_fn(family: str):
    """``barcode.GlyphFn`` for the human-readable line in ``family``."""
    return lambda text, height: glyphs_for(text, family, height)


def _mm(rng, value, tip, decimals=2, step=0.01):
    w = QDoubleSpinBox()
    w.setRange(*rng)
    w.setDecimals(decimals)
    w.setSingleStep(step)
    w.setSuffix(" mm")
    w.setValue(value)
    w.setToolTip(tip)
    return w


class BarcodeDialog(QDialog):
    """Settings; ``spec()`` returns the normalized :class:`barcode.BarcodeSpec`."""

    def __init__(self, parent=None, spec: barcode.BarcodeSpec | None = None, active_layer=None):
        super().__init__(parent)
        self.setWindowTitle("Barcode einfügen")
        s = (spec or barcode.BarcodeSpec()).normalized()
        form = QFormLayout(self)
        self.kind = QComboBox()
        for key in barcode.SYMBOLOGIES:
            self.kind.addItem(barcode.LABELS[key], key)
        self.kind.setCurrentIndex(barcode.SYMBOLOGIES.index(s.symbology))
        self.kind.setToolTip("Code 128: beliebiger ASCII-Text. GS1-128: GS1-Datenbezeichner in "
                             "Klammern, z. B. (01) GTIN, (17) Verfallsdatum, (10) Charge. "
                             "EAN/UPC: Artikelnummern (nur Ziffern)")
        self.data = QLineEdit(s.data)
        self.escapes = QCheckBox("Steuerzeichen als \\t \\r \\n \\g \\xHH eingeben (Code 128)")
        self.escapes.setChecked(s.escapes)
        self.escapes.setToolTip("Für Scanner, die z. B. Tab oder Enter senden sollen: \\t Tab, "
                                "\\r Enter (CR), \\n Zeilenvorschub, \\g Gruppentrenner (GS), "
                                "\\e Escape, \\xHH beliebiges ASCII-Zeichen, \\\\ Backslash")
        self.module = _mm((barcode.HARD_MIN_MODULE_MM, barcode.MODULE_RANGE[1]), s.module_mm,
                          "Breite des schmalsten Strichs (Modul). Unter "
                          f"{barcode.WARN_MODULE_MM:.2f} mm verlaufen die Striche mit dem Laserfleck")
        self.height = _mm(barcode.HEIGHT_RANGE, s.height_mm, "Höhe der Striche", 1, 1.0)
        self.quiet = QCheckBox("Ruhezone freihalten (Norm: 10 Module Code 128, 11/7 EAN-13)")
        self.quiet.setChecked(s.quiet_zone)
        self.show_text = QCheckBox("Klartext unter den Strichen (als Vektorumrisse)")
        self.show_text.setChecked(s.show_text)
        self.text_mm = _mm(barcode.TEXT_RANGE, s.text_mm, "Ziffernhöhe des Klartexts", 1, 0.5)
        self.font_box = QFontComboBox()
        self.font_box.setCurrentFont(QFont(s.font_family))
        self.shrink = _mm(barcode.SHRINK_RANGE, s.shrink_mm,
                          "Striche um diesen Betrag schmaler machen – gleicht die Verbreiterung "
                          "durch den Laserfleck aus (typisch 0,05–0,1 mm)")
        self.invert = QCheckBox("Invertiert (Hintergrund lasern – für Material, das hell wird)")
        self.invert.setChecked(s.invert)
        self.invert.setToolTip("Lasert Lücken, Ruhezone und einen Rand; Striche und Klartext "
                               "bleiben unbearbeitet (z. B. eloxiertes Alu, Schiefer, "
                               "beschichtetes Metall)")
        fills = layer_fills(active_layer)
        name = getattr(active_layer, "name", "")
        self.fill = QCheckBox(f"Neue Ebene „{FILL_LAYER_NAME}“ mit Füllung "
                              f"(Schraffur {FILL_INTERVAL_MM:.1f} mm) anlegen")
        self.fill.setChecked(not fills)
        self.fill.setToolTip("Aus: Barcode auf die aktive Ebene"
                             + (f" „{name}“" if name else "")
                             + " – sie muss füllen (Schraffur), sonst werden nur Umrisse gelasert")
        self._active_fills = fills
        form.addRow("Typ", self.kind)
        form.addRow("Inhalt", self.data)
        form.addRow("", self.escapes)
        form.addRow("Modulbreite", self.module)
        form.addRow("Strichhöhe", self.height)
        form.addRow("", self.quiet)
        form.addRow("", self.show_text)
        form.addRow("Schrifthöhe", self.text_mm)
        form.addRow("Schrift", self.font_box)
        form.addRow("Strichkorrektur", self.shrink)
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
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.data.textChanged.connect(self._update)
        for w in (self.module, self.height, self.text_mm, self.shrink):
            w.valueChanged.connect(self._update)
        for w in (self.quiet, self.show_text, self.fill, self.invert, self.escapes):
            w.toggled.connect(self._update)
        self.font_box.currentFontChanged.connect(self._update)
        self._kind_changed(keep=True)

    def _kind_changed(self, *_args, keep: bool = False) -> None:
        sym = self.kind.currentData()
        self.data.setPlaceholderText(PLACEHOLDERS[sym])
        self.escapes.setEnabled(sym == "code128")
        if not keep:
            try:
                barcode.encode(sym, self.data.text(), self.escapes.isChecked() and sym == "code128")
            except ValueError:
                self.data.setText(EXAMPLES[sym])   # old content does not fit the new type
        self._update()

    def spec(self) -> barcode.BarcodeSpec:
        return barcode.BarcodeSpec(
            symbology=self.kind.currentData(), data=self.data.text(),
            module_mm=self.module.value(), height_mm=self.height.value(),
            quiet_zone=self.quiet.isChecked(), show_text=self.show_text.isChecked(),
            text_mm=self.text_mm.value(), shrink_mm=self.shrink.value(),
            font_family=self.font_box.currentFont().family(),
            invert=self.invert.isChecked(),
            escapes=self.escapes.isChecked() and self.kind.currentData() == "code128").normalized()

    def fill_layer(self) -> bool:
        return self.fill.isChecked()

    def _update(self) -> None:
        s = self.spec()
        self.text_mm.setEnabled(s.show_text)
        self.font_box.setEnabled(s.show_text)
        self.quiet.setEnabled(not s.invert)          # inverted: quiet zone is always engraved
        self.shrink.setToolTip("Striche um diesen Betrag breiter machen (Lücken schmaler) – "
                               "invertiert wird der Hintergrund gelasert" if s.invert else
                               "Striche um diesen Betrag schmaler machen – gleicht die "
                               "Verbreiterung durch den Laserfleck aus (typisch 0,05–0,1 mm)")
        try:
            code = s.encode()
            barcode.check(barcode.centered(s, code=code), code)
        except ValueError as exc:
            self.info.setText(str(exc))
            self.ok_button.setEnabled(False)
            return
        text = barcode.describe(s, code)
        if s.module_mm < barcode.WARN_MODULE_MM:
            text += (f" – Achtung: Modul unter {barcode.WARN_MODULE_MM:.2f} mm, der Laserfleck "
                     "lässt die Striche verlaufen (schlecht lesbar)")
        if not self.fill.isChecked() and not self._active_fills:
            text += " – Achtung: aktive Ebene füllt nicht, es würden nur Umrisse gelasert"
        self.info.setText(text)
        self.ok_button.setEnabled(True)


def insert_barcode(editor, spec: barcode.BarcodeSpec, fill_layer: bool = False,
                   center: tuple[float, float] | None = None) -> list[str]:
    """Insert the barcode as one group (one undo step, optionally with a new fill layer).

    ``fill_layer`` False: onto the active layer. Raises ``ValueError`` (invalid
    content, too thin, does not fit, layer locked).
    """
    doc = editor.document
    s = spec.normalized()
    code = s.encode()
    s = barcode.centered(s, center, code)
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
    shapes = tag(barcode.barcode_shapes(s, layer_id, code, glyph_fn(s.font_family)), s)
    stack = editor.undo_stack
    stack.beginMacro("Barcode einfügen")
    try:
        if layer is not None:
            stack.push(AddLayerCommand(doc, layer, 0))
        stack.push(AddShapesCommand(doc, shapes, "Barcode"))
    finally:
        stack.endMacro()
    ids = [sh.id for sh in shapes]
    editor.set_selection(ids)
    return ids


__all__ = ["BarcodeDialog", "glyph_fn", "insert_barcode"]
