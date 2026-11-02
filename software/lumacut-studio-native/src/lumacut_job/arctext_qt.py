"""Dialog „Bogentext…“ und Glyphen aus der Schrift (Qt-Teil zu :mod:`lumacut_job.arctext`).

Qt liefert nur die Buchstabenumrisse (``QPainterPath.addText``) und die
Vorschübe (``QFontMetricsF``, mit Unterschneidung); das Setzen auf den Kreis
rechnet :func:`lumacut_job.arctext.place_glyphs`.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF
from PySide6.QtGui import QFont, QFontMetricsF, QPainterPath, QTransform
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFontComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QWidget)

from lumacut_canvas.commands import AddShapesCommand, DeleteShapesCommand
from lumacut_canvas.shape_paths import FLATTEN_TOL_MM, text_font, text_path

from . import arctext
from .arctext import ArcSpec, Glyph
from .generated import tag


def cap_height_pt(font: QFont) -> float:
    fm = QFontMetricsF(font)
    cap = fm.capHeight()
    if cap <= 0:
        p = QPainterPath()
        p.addText(QPointF(0, 0), font, "H")
        cap = -p.boundingRect().y()
    return cap if cap > 0 else fm.ascent() * 0.7


def glyphs_for(text: str, family: str, height_mm: float, bold: bool = False,
               italic: bool = False, tol: float = FLATTEN_TOL_MM) -> list[Glyph]:
    """Buchstaben als :class:`Glyph` in mm; ``height_mm`` = Höhe der Großbuchstaben."""
    font = text_font(family, bold, italic)
    fm = QFontMetricsF(font)
    scale = float(height_mm) / cap_height_pt(font)
    k = max(1.0, 0.5 / tol)
    to_mm = QTransform.fromScale(scale * k, scale * k)
    out = []
    prev = 0.0
    for i, ch in enumerate(text):
        width = fm.horizontalAdvance(text[:i + 1])   # inkl. Unterschneidung zum Vorgänger
        adv = (width - prev) * scale
        prev = width
        rings = []
        if not ch.isspace():
            p = QPainterPath()
            p.addText(QPointF(0, 0), font, ch)
            for poly in p.toSubpathPolygons(to_mm):
                pts = [(q.x() / k, q.y() / k) for q in poly]
                if len(pts) > 1 and pts[0] == pts[-1]:
                    pts.pop()
                if len(pts) >= 3:
                    rings.append(tuple(pts))
        out.append(Glyph(ch, max(0.0, adv), tuple(rings)))
    return out


def spec_from_text(shape) -> ArcSpec:
    """Vorbelegung aus einem Textobjekt: Text, Schrift und Großbuchstabenhöhe."""
    text = " ".join((shape.text or "").split("\n"))
    font = text_font(shape.font_family, shape.font_bold, shape.font_italic)
    r = text_path(shape.text, shape.font_family, shape.font_bold, shape.font_italic).boundingRect()
    cap = abs(shape.geom.h) / r.height() * cap_height_pt(font) if r.height() > 0 else 8.0
    width = abs(shape.geom.w)
    return ArcSpec(text=text, height_mm=round(cap, 1), radius_mm=round(max(10.0, width / 2.0), 1),
                   font_family=shape.font_family, bold=shape.font_bold,
                   italic=shape.font_italic).normalized()


class ArcTextDialog(QDialog):
    """Bogentext-Einstellungen; ``spec()`` liefert die normalisierte :class:`ArcSpec`."""

    def __init__(self, parent=None, spec: ArcSpec | None = None, can_replace: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Bogentext")
        s = (spec or ArcSpec()).normalized()
        form = QFormLayout(self)
        self.text = QLineEdit(s.text)
        self.font_box = QFontComboBox()
        self.font_box.setCurrentFont(QFont(s.font_family))
        self.bold = QCheckBox("Fett")
        self.bold.setChecked(s.bold)
        self.italic = QCheckBox("Kursiv")
        self.italic.setChecked(s.italic)
        style = QWidget()
        row = QHBoxLayout(style)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.bold)
        row.addWidget(self.italic)
        row.addStretch(1)
        self.height_mm = self._mm(arctext.HEIGHT_RANGE, s.height_mm, "Höhe der Großbuchstaben")
        self.radius = self._mm(arctext.RADIUS_RANGE, s.radius_mm, "Radius der Grundlinie")
        self.side = QComboBox()
        self.side.addItem("Oben/außen (im Uhrzeigersinn)", False)
        self.side.addItem("Unten/innen (gegen den Uhrzeigersinn)", True)
        self.side.setCurrentIndex(1 if s.bottom else 0)
        self.side.setToolTip("Oben: Buchstaben stehen außen auf dem Kreis. Unten: Buchstaben "
                             "stehen innen und lesen sich unten von links nach rechts")
        self.angle = QDoubleSpinBox()
        self.angle.setRange(*arctext.ANGLE_RANGE)
        self.angle.setDecimals(1)
        self.angle.setSuffix(" °")
        self.angle.setValue(s.angle_deg)
        self.angle.setToolTip("Lage auf dem Kreis, im Uhrzeigersinn ab 12 Uhr "
                              "(0° = oben, 90° = rechts, 180° = unten)")
        self.align = QComboBox()
        for key in arctext.ALIGNS:
            self.align.addItem(arctext.ALIGN_LABELS[key], key)
        self.align.setCurrentIndex(arctext.ALIGNS.index(s.align))
        self.align.setToolTip("Welcher Punkt des Textes beim Winkel liegt (Mitte, Anfang oder "
                              "Ende in Leserichtung)")
        self.spacing = self._mm(arctext.SPACING_RANGE, s.spacing_mm,
                                "Zusätzlicher Abstand zwischen den Buchstaben")
        self.replace = QCheckBox("Ausgewählten Text ersetzen")
        self.replace.setChecked(can_replace)
        self.replace.setVisible(can_replace)
        form.addRow("Text", self.text)
        form.addRow("Schrift", self.font_box)
        form.addRow("", style)
        form.addRow("Schrifthöhe", self.height_mm)
        form.addRow("Radius", self.radius)
        form.addRow("Lage", self.side)
        form.addRow("Winkel", self.angle)
        form.addRow("Bezugspunkt", self.align)
        form.addRow("Zeichenabstand", self.spacing)
        form.addRow("", self.replace)
        self.info = QLabel()
        self.info.setWordWrap(True)
        form.addRow("Info", self.info)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.Ok)
        self.ok_button.setText("Erzeugen")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.side.currentIndexChanged.connect(self._side_changed)
        self.align.currentIndexChanged.connect(self._update)
        self.text.textChanged.connect(self._update)
        self.font_box.currentFontChanged.connect(self._update)
        for w in (self.bold, self.italic):
            w.toggled.connect(self._update)
        for w in (self.height_mm, self.radius, self.spacing, self.angle):
            w.valueChanged.connect(self._update)
        self._update()

    @staticmethod
    def _mm(rng, value, tip):
        w = QDoubleSpinBox()
        w.setRange(*rng)
        w.setDecimals(1)
        w.setSuffix(" mm")
        w.setValue(value)
        w.setToolTip(tip)
        return w

    def _side_changed(self) -> None:
        bottom = bool(self.side.currentData())
        # Standardlage mitnehmen (oben 0°, unten 180°), eigene Winkel behalten.
        if self.angle.value() in (0.0, 180.0):
            self.angle.setValue(180.0 if bottom else 0.0)
        self._update()

    def spec(self) -> ArcSpec:
        return ArcSpec(text=self.text.text(), radius_mm=self.radius.value(),
                       height_mm=self.height_mm.value(), spacing_mm=self.spacing.value(),
                       angle_deg=self.angle.value(), bottom=bool(self.side.currentData()),
                       align=self.align.currentData(),
                       font_family=self.font_box.currentFont().family(), bold=self.bold.isChecked(),
                       italic=self.italic.isChecked()).normalized()

    def replace_source(self) -> bool:
        return not self.replace.isHidden() and self.replace.isChecked()

    def _update(self) -> None:
        s = self.spec()
        if not s.text.strip():
            self.info.setText("Bitte Text eingeben")
            self.ok_button.setEnabled(False)
            return
        glyphs = glyphs_for(s.text, s.font_family, s.height_mm, s.bold, s.italic, tol=0.1)
        span = arctext.text_span(glyphs, s.spacing_mm)
        try:
            arctext.place_glyphs(glyphs, s.radius_mm, s.angle_deg, s.bottom, s.spacing_mm,
                                 cap_height_mm=s.height_mm, align=s.align)
        except ValueError as exc:
            self.info.setText(str(exc))
            self.ok_button.setEnabled(False)
            return
        sweep = math.degrees(span / s.radius_mm)
        self.info.setText(f"Textlänge {span:.1f} mm, Bogen {sweep:.0f}° von 360°, "
                          f"Kreis Ø {2 * s.radius_mm:.1f} mm")
        self.ok_button.setEnabled(True)


def insert_arc_text(editor, spec: ArcSpec, replace_id: str | None = None,
                    center: tuple[float, float] | None = None) -> list[str]:
    """Bogentext als Gruppe einfügen (ein Undo-Schritt); optional Text ersetzen."""
    doc = editor.document
    s = spec.normalized()
    if replace_id is not None:
        src = doc.shape(replace_id)
        layer_id = src.layer_id
        if center is None:
            b = src.bounds()
            center = (b.x + b.w / 2.0, b.y + b.h / 2.0)
    else:
        active = doc.active_layer or (doc.layers[0] if doc.layers else None)
        if active is None:
            raise ValueError("Keine Ebene vorhanden")
        layer_id = active.id
    layer = doc.layer(layer_id)
    if layer.locked:
        raise ValueError(f"Ebene „{layer.name}“ ist gesperrt")
    glyphs = glyphs_for(s.text, s.font_family, s.height_mm, s.bold, s.italic)
    shapes = tag(arctext.arc_shapes(glyphs, s, layer_id, center, cap_height_mm=s.height_mm), s)
    if replace_id is not None:
        # The arc text takes the replaced text's place inside its groups; its own
        # group stays innermost (``groups[-1]``, see lumacut_job.generated).
        outer = tuple(doc.shape(replace_id).groups)
        for sh in shapes:
            sh.groups = outer + sh.groups
    stack = editor.undo_stack
    stack.beginMacro("Bogentext")
    try:
        stack.push(AddShapesCommand(doc, shapes, "Bogentext"))
        if replace_id is not None:
            stack.push(DeleteShapesCommand(doc, [replace_id]))
    finally:
        stack.endMacro()
    ids = [sh.id for sh in shapes]
    editor.set_selection(ids)
    return ids


__all__ = ["ArcTextDialog", "glyphs_for", "insert_arc_text", "spec_from_text"]
