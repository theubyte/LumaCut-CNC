"""Schrift-Steuerung für Textobjekte in der PropertyBar: Schriftart, Größe,
Fett, Kursiv, Text-Satz (Ausrichtung, Zeichen- und Zeilenabstand, mehrzeilig
bearbeiten – wie LightBurns *Align X / H-Space / V-Space*) und Knopf „In Pfade“.

Die Objektbox bleibt die maßgebliche Größe in mm (siehe :mod:`shape_paths`).
„Größe“ in pt rechnet nur um: Geviert (em) = pt · 25,4/72 mm, die Box wird
gleichmäßig um die linke obere Ecke skaliert. Schriftart/Fett/Kursiv behalten
die Höhe und passen die Breite an das neue Seitenverhältnis an. Der Text-Satz
behält die Buchstabengröße (mm je Aufbau-Einheit) und passt die Box an; fest
bleibt die obere Kante an der linken Ecke, der Mitte oder der rechten Ecke – je
nach Ausrichtung.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QButtonGroup, QDoubleSpinBox, QFontComboBox, QHBoxLayout, QInputDialog,
                               QLabel, QToolButton, QWidget)

from . import icons
from .edit_commands import ReplaceShapeCommand
from .model import (LETTER_SPACING_RANGE, LINE_SPACING_RANGE, TEXT_ALIGN_LABELS, TEXT_ALIGNS, Shape,
                    read_letter_spacing, read_line_spacing, read_text_align, rotate_point)
from .shape_paths import em_units, shape_text_path, text_aspect, text_font, text_layout

MM_PER_PT = 25.4 / 72.0
SIZE_RANGE_PT = (2.0, 2000.0)


def _em_ratio(s: Shape) -> float:
    """Boxhöhe / Geviert für Text und Schrift von ``s`` (aus dem Umriss)."""
    em = em_units(text_font(s.font_family, s.font_bold, s.font_italic))
    h = shape_text_path(s).boundingRect().height()
    return h / em if h > 0 else 1.0


def size_pt(s: Shape) -> float:
    """Schriftgröße in pt, die der Boxhöhe von ``s`` entspricht."""
    return abs(s.geom.h) / _em_ratio(s) / MM_PER_PT


def with_size_pt(s: Shape, pt: float) -> Shape:
    out = s.copy()
    h_new = pt * MM_PER_PT * _em_ratio(s)
    h_old = abs(s.geom.h)
    k = h_new / h_old if h_old > 0 else 1.0
    out.geom.w *= k
    out.geom.h *= k
    return out


def with_style(s: Shape, family: str | None = None, bold: bool | None = None,
               italic: bool | None = None) -> Shape:
    out = s.copy()
    if family is not None:
        out.font_family = family
    if bold is not None:
        out.font_bold = bold
    if italic is not None:
        out.font_italic = italic
    h = abs(out.geom.h)
    out.geom.w = h * text_aspect(out.text, out.font_family, out.font_bold, out.font_italic,
                                 **text_layout(out)) * (1 if out.geom.w >= 0 else -1)
    return out


TIP_ALIGN = ("Ausrichtung mehrzeiliger Texte (wie LightBurn „Align X“): Zeilen links, mittig oder "
             "rechts nach ihrer Laufweite ausrichten. Wirkt erst ab zwei Zeilen (¶).")
TIP_LETTER = ("Zeichenabstand (wie LightBurn „H-Space“ / xTool „Zeichenabstand“) in % der "
              "Schriftgröße – zusätzlich nach jedem Zeichen, negativ rückt die Buchstaben "
              "zusammen. 0 % = Abstand der Schrift. Die Buchstaben behalten ihre Größe, die "
              "Box wird breiter oder schmaler.")
TIP_LINE = ("Zeilenabstand mehrzeiliger Texte (wie LightBurn „V-Space“ / xTool „Zeilenabstand“) "
            "in % des Standardabstands (100 % = 1,25 × Schriftgröße). Die Buchstaben behalten "
            "ihre Größe, die Box wird höher oder niedriger.")
TIP_MULTILINE = "Text mehrzeilig bearbeiten … (eine Zeile je Absatz; die Buchstaben behalten ihre Größe)"


def with_layout(s: Shape, *, letter_spacing: float | None = None, line_spacing: float | None = None,
                align: str | None = None, text: str | None = None) -> Shape:
    """Kopie von ``s`` mit geändertem Text-Satz (und/oder Text).

    Die Buchstaben behalten ihre Größe in mm (Maßstab je Achse aus der alten Box),
    die Box folgt dem neuen Umriss. Fest bleibt die obere Kante – links, in der Mitte
    oder rechts je nach (neuer) Ausrichtung, im gedrehten Objektrahmen.
    """
    out = s.copy()
    if letter_spacing is not None:
        out.letter_spacing = read_letter_spacing(letter_spacing)
    if line_spacing is not None:
        out.line_spacing = read_line_spacing(line_spacing)
    if align is not None:
        out.text_align = read_text_align(align)
    if text is not None:
        out.text = text
    g = s.geom
    r0 = shape_text_path(s).boundingRect()
    r1 = shape_text_path(out).boundingRect()
    if min(r0.width(), r0.height(), r1.width(), r1.height()) <= 0:
        return out
    w = math.copysign(r1.width() * abs(g.w) / r0.width(), g.w if g.w else 1.0)
    h = math.copysign(r1.height() * abs(g.h) / r0.height(), g.h if g.h else 1.0)
    if not (math.isfinite(w) and math.isfinite(h)):
        return out
    fx = {"left": 0.0, "center": 0.5, "right": 1.0}[out.text_align]
    if g.rot:
        cx, cy = g.center()
        ax, ay = rotate_point(g.x + fx * g.w, g.y, cx, cy, g.rot)       # Anker in der Welt
        ox, oy = rotate_point(fx * w - w / 2.0, -h / 2.0, 0.0, 0.0, g.rot)  # Anker − neue Mitte
        out.geom.x, out.geom.y = ax - ox - w / 2.0, ay - oy - h / 2.0
    elif fx:
        out.geom.x = g.x + fx * (g.w - w)
    out.geom.w, out.geom.h = w, h
    return out


def line_count(s: Shape) -> int:
    return len((s.text or "").split("\n"))


class TextStyleControls(QWidget):
    """Sichtbar, solange nur Textobjekte ausgewählt sind."""

    def __init__(self, editor) -> None:
        super().__init__()
        self.setObjectName("TextStyleControls")
        self.ed = editor
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.family = QFontComboBox()
        self.family.setObjectName("TextFontFamily")
        self.family.setToolTip("Schriftart")
        self.family.setMinimumWidth(150)
        self.family.setMaximumWidth(220)
        self.family.currentFontChanged.connect(self._family_chosen)
        self.size = QDoubleSpinBox()
        self.size.setObjectName("TextFontSize")
        self.size.setRange(*SIZE_RANGE_PT)
        self.size.setDecimals(1)
        self.size.setSuffix(" pt")
        self.size.setKeyboardTracking(False)
        self.size.setToolTip("Schriftgröße (Geviert); die Objektbox wird gleichmäßig skaliert")
        self.size.valueChanged.connect(self._size_edited)
        self.bold = self._toggle("F", "Fett", QFont.Bold, False)
        self.italic = self._toggle("K", "Kursiv", QFont.Normal, True)
        self.bold.toggled.connect(lambda on: self._apply(bold=on, label="Fett"))
        self.italic.toggled.connect(lambda on: self._apply(italic=on, label="Kursiv"))
        self.align_buttons: dict[str, QToolButton] = {}
        self.align_group = QButtonGroup(self)
        self.align_group.setExclusive(True)
        for key in TEXT_ALIGNS:
            b = QToolButton()
            b.setObjectName("TextAlign" + key.capitalize())
            b.setCheckable(True)
            b.setIcon(icons.icon("align_" + key))
            b.setToolTip(f"{TEXT_ALIGN_LABELS[key]} – {TIP_ALIGN}")
            b.clicked.connect(lambda _=False, k=key: self._layout_edited(
                "align", k, f"Ausrichtung: {TEXT_ALIGN_LABELS[k]}"))
            self.align_group.addButton(b)
            self.align_buttons[key] = b
        self.letter = self._percent_spin("TextLetterSpacing", LETTER_SPACING_RANGE, 5.0, TIP_LETTER)
        self.letter.valueChanged.connect(lambda v: self._layout_edited(
            "letter_spacing", v, "Zeichenabstand", merge="text_letter_spacing"))
        self.letter_label = QLabel("Abstand")
        self.letter_label.setToolTip(TIP_LETTER)
        self.line = self._percent_spin("TextLineSpacing", LINE_SPACING_RANGE, 10.0, TIP_LINE)
        self.line.valueChanged.connect(lambda v: self._layout_edited(
            "line_spacing", v, "Zeilenabstand", merge="text_line_spacing"))
        self.line_label = QLabel("Zeilen")
        self.line_label.setToolTip(TIP_LINE)
        self.multiline = QToolButton()
        self.multiline.setObjectName("TextMultiline")
        self.multiline.setText("¶")
        self.multiline.setToolTip(TIP_MULTILINE)
        self.multiline.clicked.connect(self.edit_multiline)
        self.outline = QToolButton()
        self.outline.setObjectName("TextToPath")
        self.outline.setText("In Pfade")
        self.outline.setToolTip("Text in Pfade umwandeln (für Schraffur und G-Code ohne Schriftabhängigkeit)")
        self.outline.clicked.connect(lambda: editor.actions_by_name["text_to_path"].trigger())
        lay.addWidget(self.family)
        lay.addWidget(QLabel("Größe"))
        lay.addWidget(self.size)
        lay.addWidget(self.bold)
        lay.addWidget(self.italic)
        lay.addSpacing(6)
        for b in self.align_buttons.values():
            lay.addWidget(b)
        lay.addWidget(self.letter_label)
        lay.addWidget(self.letter)
        lay.addWidget(self.line_label)
        lay.addWidget(self.line)
        lay.addWidget(self.multiline)
        lay.addWidget(self.outline)
        self._updating = False
        self.setVisible(False)

    @staticmethod
    def _percent_spin(name: str, rng: tuple[float, float], step: float, tip: str) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setObjectName(name)
        sp.setRange(*rng)
        sp.setDecimals(0)
        sp.setSingleStep(step)
        sp.setSuffix(" %")
        sp.setKeyboardTracking(False)
        sp.setToolTip(tip)
        sp.setFixedWidth(78)
        return sp

    def _toggle(self, text: str, tip: str, weight, italic: bool) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setCheckable(True)
        b.setToolTip(tip)
        f = b.font()
        f.setWeight(weight)
        f.setItalic(italic)
        b.setFont(f)
        return b

    def _texts(self) -> list[Shape]:
        doc = self.ed.document
        sel = [i for i in self.ed.selection if doc.has_shape(i)]
        shapes = [doc.shape(i) for i in sel]
        if not shapes or any(s.kind != "text" for s in shapes):
            return []
        return [s for s in shapes if doc.is_editable(s.id)]

    def refresh(self) -> None:
        texts = self._texts()
        self.setVisible(bool(texts))
        if not texts:
            return
        self._updating = True
        try:
            s = texts[0]
            self.family.setCurrentFont(QFont(s.font_family))
            if not self.size.hasFocus():
                self.size.setValue(size_pt(s))
            self.bold.setChecked(all(t.font_bold for t in texts))
            self.italic.setChecked(all(t.font_italic for t in texts))
            aligns = {t.text_align for t in texts}
            self.align_group.setExclusive(False)
            for key, b in self.align_buttons.items():
                b.setChecked(aligns == {key})
            self.align_group.setExclusive(True)
            multi = any(line_count(t) > 1 for t in texts)
            for b in self.align_buttons.values():
                b.setEnabled(multi)
            self.line.setEnabled(multi)
            self.line_label.setEnabled(multi)
            if not self.letter.hasFocus():
                self.letter.setValue(s.letter_spacing)
            if not self.line.hasFocus():
                self.line.setValue(s.line_spacing)
            self.multiline.setEnabled(len(texts) == 1)
        finally:
            self._updating = False

    def _push(self, new: list[Shape], label: str, merge: str | None = None) -> None:
        stack = self.ed.undo_stack
        if len(new) == 1:
            stack.push(ReplaceShapeCommand(self.ed.document, new[0], label, merge_key=merge))
            return
        stack.beginMacro(label)
        try:
            for s in new:
                stack.push(ReplaceShapeCommand(self.ed.document, s, label))
        finally:
            stack.endMacro()

    def _apply(self, label: str, **style) -> None:
        if self._updating:
            return
        texts = self._texts()
        if texts:
            self._push([with_style(s, **style) for s in texts], label)
        # Zuletzt gewählte Schrift gilt auch für neue Textobjekte.
        if "family" in style:
            self.ed.text_font_family = style["family"]
        if "bold" in style:
            self.ed.text_font_bold = style["bold"]
        if "italic" in style:
            self.ed.text_font_italic = style["italic"]

    def _family_chosen(self, font: QFont) -> None:
        self._apply(family=font.family(), label="Schriftart")

    def _size_edited(self, pt: float) -> None:
        if self._updating:
            return
        texts = self._texts()
        if texts:
            self._push([with_size_pt(s, pt) for s in texts], "Schriftgröße")

    def _layout_edited(self, field: str, value, label: str, merge: str | None = None) -> None:
        """Ausrichtung / Zeichen- / Zeilenabstand für alle ausgewählten Texte (ein Undo-Schritt)."""
        if self._updating:
            return
        texts = self._texts()
        key = {"align": "text_align"}.get(field, field)
        new = [with_layout(t, **{field: value}) for t in texts if getattr(t, key) != value]
        if new:
            self._push(new, label, merge)

    def edit_multiline(self) -> bool:
        """Text des ausgewählten Textobjekts mehrzeilig bearbeiten (Box folgt, Buchstaben
        behalten ihre Größe). True, wenn sich etwas geändert hat."""
        texts = self._texts()
        return len(texts) == 1 and edit_multiline(self.ed, texts[0].id)


def edit_multiline(editor, shape_id: str) -> bool:
    """Mehrzeiliger Bearbeiten-Dialog für das Textobjekt ``shape_id`` (ein Undo-Schritt
    „Text ändern“; die Box folgt dem neuen Text, die Buchstaben behalten ihre Größe)."""
    doc = editor.document
    if not doc.has_shape(shape_id) or doc.shape(shape_id).kind != "text":
        return False
    s = doc.shape(shape_id)
    text, ok = QInputDialog.getMultiLineText(editor, "Text bearbeiten",
                                             "Text (eine Zeile je Absatz):", s.text)
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not ok or not text.strip() or text == s.text:
        return False
    editor.undo_stack.push(ReplaceShapeCommand(doc, with_layout(s, text=text), "Text ändern"))
    return True
