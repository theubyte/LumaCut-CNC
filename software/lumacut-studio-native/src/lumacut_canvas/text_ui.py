"""Schrift-Steuerung für Textobjekte in der PropertyBar: Schriftart, Größe,
Fett, Kursiv (und Knopf „In Pfade“).

Die Objektbox bleibt die maßgebliche Größe in mm (siehe :mod:`shape_paths`).
„Größe“ in pt rechnet nur um: Geviert (em) = pt · 25,4/72 mm, die Box wird
gleichmäßig um die linke obere Ecke skaliert. Schriftart/Fett/Kursiv behalten
die Höhe und passen die Breite an das neue Seitenverhältnis an.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontInfo
from PySide6.QtWidgets import QDoubleSpinBox, QFontComboBox, QHBoxLayout, QLabel, QToolButton, QWidget

from .edit_commands import ReplaceShapeCommand
from .model import Shape
from .shape_paths import text_aspect, text_font, text_path

MM_PER_PT = 25.4 / 72.0
SIZE_RANGE_PT = (2.0, 2000.0)


def _em_ratio(s: Shape) -> float:
    """Boxhöhe / Geviert für Text und Schrift von ``s`` (aus dem Umriss)."""
    font = text_font(s.font_family, s.font_bold, s.font_italic)
    em = QFontInfo(font).pixelSize() or 1
    h = text_path(s.text, s.font_family, s.font_bold, s.font_italic).boundingRect().height()
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
    out.geom.w = h * text_aspect(out.text, out.font_family, out.font_bold, out.font_italic) * (
        1 if out.geom.w >= 0 else -1)
    return out


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
        lay.addWidget(self.outline)
        self._updating = False
        self.setVisible(False)

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
        finally:
            self._updating = False

    def _push(self, new: list[Shape], label: str) -> None:
        stack = self.ed.undo_stack
        if len(new) == 1:
            stack.push(ReplaceShapeCommand(self.ed.document, new[0], label))
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
