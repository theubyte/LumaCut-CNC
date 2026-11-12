"""Dialog „Text auf Pfad…“ und Einfügen (Qt-Teil zu :mod:`lumacut_job.pathtext`).

Auswahl wie in LightBurn: ein Pfad (Linie, Pfad, Polygon, Rechteck, Ellipse)
und optional ein Textobjekt – dessen Text, Schrift und Höhe werden übernommen
und er kann ersetzt werden. Die Glyphen kommen aus
:func:`lumacut_job.arctext_qt.glyphs_for`, der Pfad aus
:func:`lumacut_canvas.alongpath.shape_curve`. Einfügen ist ein Undo-Schritt.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFontComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QWidget)

from lumacut_canvas.alongpath import PathCurve, pick_path, shape_curve
from lumacut_canvas.commands import AddShapesCommand, DeleteShapesCommand

from . import arctext, pathtext
from .arctext_qt import glyphs_for, spec_from_text
from .pathtext import PathTextSpec

TITLE = "Text auf Pfad"


def spec_from_text_shape(shape) -> PathTextSpec:
    """Vorbelegung aus einem Textobjekt: Text, Schrift und Großbuchstabenhöhe."""
    a = spec_from_text(shape)
    return PathTextSpec(text=a.text, height_mm=a.height_mm, font_family=a.font_family,
                        bold=a.bold, italic=a.italic).normalized()


def split_selection(doc, ids) -> tuple[str | None, str | None]:
    """(Pfad-ID, Text-ID) aus der Auswahl; Text nur, wenn genau ein Textobjekt dabei ist."""
    sel = doc.expand_to_groups(ids)
    texts = [i for i in sel if doc.shape(i).kind == "text" and not doc.shape(i).groups]
    path_id = pick_path(doc, [i for i in sel if i not in texts])
    return path_id, (texts[0] if len(texts) == 1 else None)


class PathTextDialog(QDialog):
    """Einstellungen; ``spec()`` liefert die normalisierte :class:`PathTextSpec`."""

    def __init__(self, curve: PathCurve, parent=None, spec: PathTextSpec | None = None,
                 can_replace: bool = False):
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.curve = curve
        s = (spec or PathTextSpec()).normalized(curve.closed)
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
        self.height_mm = self._spin(arctext.HEIGHT_RANGE, s.height_mm, " mm",
                                    "Höhe der Großbuchstaben")
        self.position = self._spin(pathtext.POSITION_RANGE, s.position_pct, " %",
                                   "Lage auf dem Pfad in % seiner Länge. Geschlossene Umrisse "
                                   "beginnen oben in der Mitte und laufen im Uhrzeigersinn "
                                   "(0 % = oben, 50 % = unten), offene am Anfang der Linie")
        self.align = QComboBox()
        for key in arctext.ALIGNS:
            self.align.addItem(arctext.ALIGN_LABELS[key], key)
        self.align.setCurrentIndex(arctext.ALIGNS.index(s.align))
        self.align.setToolTip("Welcher Punkt des Textes bei der Lage liegt (Mitte, Anfang oder "
                              "Ende in Leserichtung)")
        self.side = QComboBox()
        self.side.addItem("Oberseite (in Pfadrichtung)", False)
        self.side.addItem("Andere Seite (gegen die Pfadrichtung)", True)
        self.side.setCurrentIndex(1 if s.flip else 0)
        self.side.setToolTip("Andere Seite: der Text liegt auf der anderen Seite des Pfads und "
                             "läuft in Gegenrichtung – z. B. unten auf einem Kreis, von links "
                             "nach rechts lesbar")
        self.distance = self._spin(pathtext.DISTANCE_RANGE, s.distance_mm, " mm",
                                   "Abstand der Grundlinie vom Pfad: positiv = weg vom Pfad zur "
                                   "Oberseite der Buchstaben, negativ = darunter "
                                   "(−Schrifthöhe/2 legt den Text mittig auf den Pfad)")
        self.spacing = self._spin(arctext.SPACING_RANGE, s.spacing_mm, " mm",
                                  "Zusätzlicher Abstand zwischen den Buchstaben")
        self.rotate = QCheckBox("Buchstaben mit dem Pfad drehen")
        self.rotate.setChecked(s.rotate)
        self.rotate.setToolTip("Aus: alle Buchstaben bleiben aufrecht")
        self.replace = QCheckBox("Ausgewählten Text ersetzen")
        self.replace.setChecked(can_replace)
        self.replace.setVisible(can_replace)
        self.delete_path = QCheckBox("Pfad danach löschen (nur Hilfslinie)")
        self.delete_path.setChecked(False)
        form.addRow("Text", self.text)
        form.addRow("Schrift", self.font_box)
        form.addRow("", style)
        form.addRow("Schrifthöhe", self.height_mm)
        form.addRow("Lage", self.position)
        form.addRow("Bezugspunkt", self.align)
        form.addRow("Seite", self.side)
        form.addRow("Abstand vom Pfad", self.distance)
        form.addRow("Zeichenabstand", self.spacing)
        form.addRow("", self.rotate)
        form.addRow("", self.replace)
        form.addRow("", self.delete_path)
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
        for w in (self.bold, self.italic, self.rotate):
            w.toggled.connect(self._update)
        for w in (self.height_mm, self.position, self.spacing, self.distance):
            w.valueChanged.connect(self._update)
        self._update()

    @staticmethod
    def _spin(rng, value, suffix, tip):
        w = QDoubleSpinBox()
        w.setRange(*rng)
        w.setDecimals(1)
        w.setSuffix(suffix)
        w.setValue(value)
        w.setToolTip(tip)
        return w

    def _side_changed(self) -> None:
        flip = bool(self.side.currentData())
        # Geschlossener Umriss: Standardlage mitnehmen (oben 0 %, unten 50 %), eigene behalten.
        if self.curve.closed and self.position.value() in (0.0, 50.0):
            self.position.setValue(50.0 if flip else 0.0)
        self._update()

    def spec(self) -> PathTextSpec:
        return PathTextSpec(text=self.text.text(), height_mm=self.height_mm.value(),
                            spacing_mm=self.spacing.value(), position_pct=self.position.value(),
                            distance_mm=self.distance.value(),
                            flip=bool(self.side.currentData()), align=self.align.currentData(),
                            rotate=self.rotate.isChecked(),
                            font_family=self.font_box.currentFont().family(),
                            bold=self.bold.isChecked(),
                            italic=self.italic.isChecked()).normalized(self.curve.closed)

    def replace_source(self) -> bool:
        return not self.replace.isHidden() and self.replace.isChecked()

    def remove_path(self) -> bool:
        return self.delete_path.isChecked()

    def _update(self) -> None:
        s = self.spec()
        if not s.text.strip():
            self.info.setText("Bitte Text eingeben")
            self.ok_button.setEnabled(False)
            return
        glyphs = glyphs_for(s.text, s.font_family, s.height_mm, s.bold, s.italic, tol=0.1)
        try:
            shapes, res = pathtext.pathtext_shapes(glyphs, self.curve, s, "preview")
        except ValueError as exc:
            self.info.setText(str(exc))
            self.ok_button.setEnabled(False)
            return
        self.info.setText(res.readout())
        self.ok_button.setEnabled(bool(shapes))


def insert_path_text(editor, spec: PathTextSpec, path_id: str, replace_id: str | None = None,
                     remove_path: bool = False) -> tuple[list[str], pathtext.PathTextResult]:
    """Text auf Pfad als Gruppe einfügen (ein Undo-Schritt); optional Text ersetzen
    und den Pfad löschen. Ebene: die des ersetzten Texts, sonst die aktive."""
    doc = editor.document
    path = doc.shape(path_id)
    curve = shape_curve(path)
    s = spec.normalized(curve.closed)
    if replace_id is not None:
        layer_id = doc.shape(replace_id).layer_id
    else:
        active = doc.active_layer or (doc.layers[0] if doc.layers else None)
        if active is None:
            raise ValueError("Keine Ebene vorhanden")
        layer_id = active.id
    layer = doc.layer(layer_id)
    if layer.locked:
        raise ValueError(f"Ebene „{layer.name}“ ist gesperrt")
    if remove_path and not doc.is_editable(path_id):
        raise ValueError("Der Pfad liegt auf einer gesperrten oder ausgeblendeten Ebene")
    glyphs = glyphs_for(s.text, s.font_family, s.height_mm, s.bold, s.italic)
    shapes, res = pathtext.pathtext_shapes(glyphs, curve, s, layer_id)
    if replace_id is not None:
        outer = tuple(doc.shape(replace_id).groups)
        for sh in shapes:
            sh.groups = outer + sh.groups
    stack = editor.undo_stack
    stack.beginMacro(TITLE)
    try:
        stack.push(AddShapesCommand(doc, shapes, TITLE))
        gone = [i for i in (replace_id, path_id if remove_path else None) if i is not None]
        if gone:
            stack.push(DeleteShapesCommand(doc, gone))
    finally:
        stack.endMacro()
    ids = [sh.id for sh in shapes]
    editor.set_selection(ids)
    return ids, res


__all__ = ["PathTextDialog", "insert_path_text", "spec_from_text_shape", "split_selection"]
