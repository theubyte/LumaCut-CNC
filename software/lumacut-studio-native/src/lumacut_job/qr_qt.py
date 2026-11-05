"""Dialog „QR-Code…“ und Einfügen in den Entwurf (Qt-Teil zu :mod:`lumacut_job.qr`).

Die Module landen als gefüllte ``polygon``-Objekte (eine Fläche je
zusammenhängendem Bereich, Löcher als Ringe) auf der **aktiven Ebene** und
werden dort wie jedes andere Objekt nach der Ebenen-Füllung (Schraffur/
Kreuzschraffur) graviert. Füllt die aktive Ebene nicht, schlägt der Dialog
eine eigene Ebene „QR-Code“ mit Schraffur 0,1 mm vor – sonst würden nur die
Umrisse gelasert und der Code wäre nicht lesbar.

„Art“: Text / Adresse, GS1 QR-Code (Elementstring „(01)…(10)…“, FNC1-Modus),
GS1 Digital Link (Elementstring + Domain → Web-Adresse, oder eine fertige
Digital-Link-Adresse, die geprüft wird; Kurzname-Aliases ``/gtin/``, ``/lot/`` …
werden beim Einfügen akzeptiert, Ausgabe optional per Checkbox) oder **Micro QR**
(ISO/IEC 18004 M1–M4 – kleines Symbol für Bauteilkennzeichnung / wenig Platz;
Ruhezone Standard 2 Module; kein ECI / Kanji).

„UTF-8 kennzeichnen (ECI)“ (nur Text, Standard für neue Codes): Umlaute und Sonderzeichen
bekommen die Zeichensatz-Kennung ECI 26, japanischer Text den Kanji-Modus. Ältere Codes ohne
die Einstellung öffnen ausgeschaltet und bleiben beim Bearbeiten bitgleich.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox)

from lumacut_canvas.commands import AddLayerCommand, AddShapesCommand
from lumacut_canvas.model import Layer
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from . import gs1_link, qr
from .generated import tag

# Füll-Ebene für neue QR-Codes: Schraffur 0,1 mm, Kontur mitlasern (scharfe Kanten).
FILL_INTERVAL_MM = 0.1
FILL_LAYER_NAME = "QR-Code"

PLACEHOLDERS = {"text": "Text oder Adresse, z. B. https://example.com",
                "gs1": "(AI)Wert, z. B. " + qr.gs1.EXAMPLE,
                "link": "(01)GTIN… oder https://id.gs1.org/gtin/…",
                "micro": "Kurzer Text, z. B. Seriennummer oder Lot"}
TOOLTIPS = {"text": "Beliebiger Text (UTF-8, Umlaute erlaubt), Web-Adresse, WLAN-Daten …",
            "gs1": "GS1-Elementstring: Datenbezeichner in Klammern, feste Längen und Prüfziffern "
                   "werden geprüft; Trenner (FNC1) setzt der Code selbst",
            "link": "Elementstring mit genau einem Primärschlüssel (z. B. (01) GTIN) – daraus wird "
                    "die Adresse gebaut – oder eine fertige Digital-Link-Adresse "
                    "(auch mit Kurznamen /gtin/, /lot/, /ser/, ?exp= …)",
            "micro": "Micro QR (M1–M4): sehr kleines Symbol für Bauteilkennzeichnung und "
                     "beengte Flächen; numerisch / alphanumerisch / Byte (UTF-8); kein ECI, "
                     "kein Kanji – für längere Texte normalen QR-Code wählen"}
EXAMPLES = {"text": "https://example.com", "gs1": qr.gs1.EXAMPLE, "link": gs1_link.EXAMPLE,
            "micro": "SN-042"}


def layer_fills(layer) -> bool:
    return layer is not None and getattr(layer, "fill_mode", "none") != "none"


class QrDialog(QDialog):
    """Einstellungen; ``spec()`` liefert die normalisierte :class:`qr.QrSpec`."""

    def __init__(self, parent=None, spec: qr.QrSpec | None = None, active_layer=None):
        super().__init__(parent)
        self.setWindowTitle("QR-Code einfügen")
        s = (spec or qr.QrSpec(eci=True)).normalized()
        form = QFormLayout(self)
        self.mode = QComboBox()
        for key in qr.MODES:
            self.mode.addItem(qr.MODE_LABELS[key], key)
        self.mode.setCurrentIndex(qr.MODES.index(s.mode))
        self.mode.setToolTip("GS1 QR-Code: Produktdaten (GTIN, Charge, MHD …) für GS1-Scanner. "
                             "GS1 Digital Link: dieselben Daten als Web-Adresse – Handy öffnet "
                             "die Produktseite, Kassenscanner lesen die GTIN. "
                             "Micro QR: kleines Symbol (11–17 Module) für Bauteile / wenig Platz")
        self.text = QLineEdit(s.text)
        self.domain = QLineEdit(s.domain)
        self.domain.setPlaceholderText(gs1_link.DEFAULT_DOMAIN)
        self.domain.setToolTip("Eigene Domain (Resolver) für die Digital-Link-Adresse, z. B. "
                               "https://marke.example – Standard: " + gs1_link.DEFAULT_DOMAIN)
        self.short_names = QCheckBox("Kurzname (/gtin/, /lot/, …) statt numerischer AI")
        self.short_names.setChecked(s.short_names)
        self.short_names.setToolTip(
            "Ein: Adresse mit Convenience-Alphas aus GS1 Digital Link 1.1 "
            "(…/gtin/…/lot/…?exp=…). Aus (Standard): numerische AIs (…/01/…/10/…?17=…) – "
            "bitgleich zu älteren Dateien. Eingefügte Adressen mit Kurznamen werden "
            "immer akzeptiert.")
        self.example = QPushButton("Beispiel")
        self.example.setToolTip("Beispieldaten für die gewählte Art einsetzen")
        self.example.clicked.connect(self._insert_example)
        from . import micro_qr as mq
        self.ec = QComboBox()
        # Levels filled in _mode_changed (Micro vs full QR); seed current value here.
        self._pending_ec = s.ec
        self.ec.setToolTip("Fehlerkorrektur: höher = robuster gegen Kratzer/Brandspuren, "
                           "aber mehr und kleinere Module"
                           + ("; Micro QR: D nur M1, L/M bis M4, Q nur M4" if True else ""))
        self.size_mm = QDoubleSpinBox()
        self.size_mm.setRange(*(mq.SIZE_RANGE if s.mode == "micro" else qr.SIZE_RANGE))
        self.size_mm.setDecimals(1)
        self.size_mm.setSuffix(" mm")
        self.size_mm.setValue(s.size_mm)
        self.size_mm.setToolTip("Kantenlänge des Codes ohne Ruhezone")
        self.quiet = QSpinBox()
        self.quiet.setRange(*qr.QUIET_RANGE)
        self.quiet.setSuffix(" Module")
        self.quiet.setValue(s.quiet_zone)
        self.quiet.setToolTip("Heller Rand um den Code (Norm: 4 Module, Micro QR: 2); "
                              "wird freigehalten, invertiert mitgraviert")
        self.eci = QCheckBox("UTF-8 kennzeichnen (ECI) – Umlaute / Sonderzeichen sicher lesbar")
        self.eci.setChecked(s.eci)
        self.eci.setToolTip("Text mit Umlauten, „°“, „€“ … bekommt die Zeichensatz-Kennung "
                            "ECI 26 (UTF-8), damit Handys und Scanner ihn nicht raten müssen; "
                            "japanischer Text nutzt den kompakten Kanji-Modus. Reiner ASCII-Text "
                            "ändert sich nicht. Aus: wie ältere Codes (ohne Kennung)")
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
        form.addRow("Art", self.mode)
        row = QHBoxLayout()
        row.addWidget(self.text, 1)
        row.addWidget(self.example)
        form.addRow("Inhalt", row)
        form.addRow("Domain", self.domain)
        self.domain_label = form.labelForField(self.domain)
        form.addRow("", self.short_names)
        self.content = QLabel()
        self.content.setWordWrap(True)
        self.content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("", self.content)
        form.addRow("", self.eci)
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
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.domain.textChanged.connect(self._update)
        self.short_names.toggled.connect(self._update)
        self.eci.toggled.connect(self._update)
        self.ec.currentIndexChanged.connect(self._update)
        self.size_mm.valueChanged.connect(self._update)
        self.quiet.valueChanged.connect(self._update)
        self.fill.toggled.connect(self._update)
        self._mode_changed()

    def spec(self) -> qr.QrSpec:
        return qr.QrSpec(text=self.text.text(), ec=self.ec.currentData(),
                         size_mm=self.size_mm.value(), quiet_zone=self.quiet.value(),
                         invert=self.invert.isChecked(), mode=self.mode.currentData(),
                         domain=self.domain.text(), eci=self.eci.isChecked(),
                         short_names=self.short_names.isChecked()).normalized()

    def _mode_changed(self) -> None:
        from . import micro_qr as mq
        mode = self.mode.currentData()
        self.text.setPlaceholderText(PLACEHOLDERS[mode])
        self.text.setToolTip(TOOLTIPS[mode])
        link = mode == "link"
        micro = mode == "micro"
        self.domain.setVisible(link)
        if self.domain_label is not None:
            self.domain_label.setVisible(link)
        self.short_names.setVisible(link)
        self.content.setVisible(mode != "text")
        self.eci.setVisible(mode == "text")
        # Size / quiet defaults & EC levels for Micro vs full QR
        prev_ec = getattr(self, "_pending_ec", None) or self.ec.currentData()
        self._pending_ec = None
        self.ec.blockSignals(True)
        self.ec.clear()
        if micro:
            for key in mq.EC_LEVELS:
                self.ec.addItem(mq.EC_LABELS[key], key)
            self.size_mm.setRange(*mq.SIZE_RANGE)
            # Only nudge quiet/size when the user *switches* into Micro, not on first open
            switching = getattr(self, "_mode_ready", False)
            if switching and self.quiet.value() == 4:
                self.quiet.setValue(mq.DEFAULT_QUIET)
            if switching and self.size_mm.value() > 80:
                self.size_mm.setValue(15.0)
        else:
            for key in qr.EC_LEVELS:
                self.ec.addItem(qr.EC_LABELS[key], key)
            self.size_mm.setRange(*qr.SIZE_RANGE)
            switching = getattr(self, "_mode_ready", False)
            if switching and self.quiet.value() == mq.DEFAULT_QUIET:
                self.quiet.setValue(4)
        idx = self.ec.findData(prev_ec)
        if idx < 0:
            idx = self.ec.findData("L" if micro else "M")
        self.ec.setCurrentIndex(max(0, idx))
        self.ec.blockSignals(False)
        self._mode_ready = True
        self._update()

    def _insert_example(self) -> None:
        mode = self.mode.currentData()
        self.text.setText(EXAMPLES[mode])

    def fill_layer(self) -> bool:
        return self.fill.isChecked()

    def _update(self) -> None:
        from . import micro_qr as mq
        s = self.spec()
        fill_name = mq.FILL_LAYER_NAME if s.mode == "micro" else FILL_LAYER_NAME
        self.fill.setText(f"Neue Ebene „{fill_name}“ mit Füllung "
                          f"(Schraffur {FILL_INTERVAL_MM:.1f} mm) anlegen")
        try:
            info = qr.content_info(s)
            self.content.setText(info)
            self.content.setVisible(s.mode != "text" or bool(info))
            code = s.encode()
        except ValueError as exc:
            self.content.setText("")
            self.info.setText(str(exc))
            self.ok_button.setEnabled(False)
            return
        module = s.size_mm / code.size
        text = qr.describe(code, s.size_mm)
        hard = qr.HARD_MIN_MODULE_MM
        soft = qr.MIN_MODULE_MM
        ok = module >= hard
        if not ok:
            text += f" – zu klein (mindestens {hard:.1f} mm)"
        elif module < soft:
            text += f" – unter {soft:.1f} mm evtl. schlecht lesbar"
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
    code = code or s.encode()
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
    code = s.encode()
    s = centered(s, center, code)
    active = doc.active_layer or (doc.layers[0] if doc.layers else None)
    layer = None
    from . import micro_qr as mq
    layer_name = mq.FILL_LAYER_NAME if s.mode == "micro" else FILL_LAYER_NAME
    label = "Micro-QR-Code" if s.mode == "micro" else "QR-Code"
    if fill_layer:
        layer = Layer(layer_name, color=doc.next_layer_color(),
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
    shapes = tag(qr.qr_shapes(s, layer_id, code), s)
    stack = editor.undo_stack
    stack.beginMacro(f"{label} einfügen")
    try:
        if layer is not None:
            stack.push(AddLayerCommand(doc, layer, 0))
        stack.push(AddShapesCommand(doc, shapes, label))
    finally:
        stack.endMacro()
    ids = [sh.id for sh in shapes]
    editor.set_selection(ids)
    return ids


__all__ = ["QrDialog", "centered", "insert_qr", "layer_fills"]
