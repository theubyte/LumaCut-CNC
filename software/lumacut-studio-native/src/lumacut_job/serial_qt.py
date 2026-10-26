"""Dialog „Seriennummern…“ (Qt-Teil zu :mod:`lumacut_job.serial`)."""

from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel,
                               QLineEdit, QSpinBox)

from lumacut_canvas.commands import AddShapesCommand, DeleteShapesCommand

from .serial import (COLUMNS_RANGE, COUNT_RANGE, GAP_RANGE, VALUE_RANGE, SerialSpec,
                     default_template, has_counter)


class SerialDialog(QDialog):
    def __init__(self, text: str, parent=None, spec: SerialSpec | None = None):
        super().__init__(parent)
        self.setWindowTitle("Seriennummern")
        spec = (spec or SerialSpec(template=default_template(text))).normalized()
        form = QFormLayout(self)
        self.template = QLineEdit(spec.template)
        self.template.setToolTip("{n} = Nummer, {n:3} = dreistellig mit Nullen, {date} = Datum")
        self.start = self._int(VALUE_RANGE, spec.start)
        self.step = self._int(VALUE_RANGE, spec.step)
        self.count = self._int(COUNT_RANGE, spec.count)
        self.columns = self._int(COLUMNS_RANGE, spec.columns)
        self.gap_x = self._mm(spec.gap_x_mm)
        self.gap_y = self._mm(spec.gap_y_mm)
        form.addRow("Vorlage", self.template)
        form.addRow("Start", self.start)
        form.addRow("Schritt", self.step)
        form.addRow("Anzahl", self.count)
        form.addRow("Spalten", self.columns)
        form.addRow("Abstand X", self.gap_x)
        form.addRow("Abstand Y", self.gap_y)
        self.preview = QLabel()
        form.addRow("Vorschau", self.preview)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.Ok)
        self.ok_button.setText("Erzeugen")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.template.textChanged.connect(self._update)
        for w in (self.start, self.step, self.count):
            w.valueChanged.connect(self._update)
        self._update()

    @staticmethod
    def _int(rng, value):
        w = QSpinBox()
        w.setRange(*rng)
        w.setValue(value)
        return w

    @staticmethod
    def _mm(value):
        w = QDoubleSpinBox()
        w.setRange(*GAP_RANGE)
        w.setDecimals(1)
        w.setSuffix(" mm")
        w.setValue(value)
        return w

    def spec(self) -> SerialSpec:
        return SerialSpec(self.template.text(), self.start.value(), self.step.value(),
                          self.count.value(), self.columns.value(),
                          self.gap_x.value(), self.gap_y.value()).normalized()

    def _update(self) -> None:
        if not has_counter(self.template.text()):
            self.preview.setText("Platzhalter {n} fehlt")
            self.ok_button.setEnabled(False)
            return
        texts = self.spec().texts()
        shown = ", ".join(t.replace("\n", " ") for t in texts[:3])
        if len(texts) > 3:
            shown += f", … {texts[-1].replace(chr(10), ' ')}"
        self.preview.setText(shown)
        self.ok_button.setEnabled(True)


def insert_serials(editor, shape_id: str, spec: SerialSpec) -> list[str]:
    """Text durch das nummerierte Raster ersetzen (ein Undo-Schritt). Neue IDs."""
    from lumacut_canvas.shape_paths import text_aspect

    from .serial import serial_shapes

    doc = editor.document
    src = doc.shape(shape_id)
    layer = doc.layer(src.layer_id)
    if layer is not None and layer.locked:
        raise ValueError(f"Ebene „{layer.name}“ ist gesperrt")
    shapes = serial_shapes(src, spec, text_aspect)
    stack = editor.undo_stack
    stack.beginMacro("Seriennummern")
    try:
        stack.push(AddShapesCommand(doc, shapes, "Seriennummern"))
        stack.push(DeleteShapesCommand(doc, [shape_id]))
    finally:
        stack.endMacro()
    ids = [s.id for s in shapes]
    editor.set_selection(ids)
    return ids
