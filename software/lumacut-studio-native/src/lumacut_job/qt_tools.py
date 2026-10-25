"""Qt glue: a "Auftrag" toolbar with time estimate, framing and material test.

Installed by ``main.py`` with :func:`install_job_tools`; it only *uses* the
public APIs of the canvas editor (``document``, ``undo_stack``) and the
machine panel (``send_gcode``) and owns no state of theirs.
"""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QMessageBox, QSpinBox, QToolBar)

from lumacut_canvas.commands import AddLayerCommand, AddShapesCommand
from lumacut_canvas.export import job_layers

from .estimate import estimate_gcode, frame_gcode
from .material_test import MaterialTestSpec, build_material_test
from .planner import optimize_layers, optimized_document_gcode


def _spin(lo, hi, value, step=1.0, decimals=0, suffix=""):
    w = QDoubleSpinBox() if decimals else QSpinBox()
    w.setRange(lo, hi)
    if decimals:
        w.setDecimals(decimals)
    w.setSingleStep(step)
    w.setValue(value)
    if suffix:
        w.setSuffix(suffix)
    return w


class MaterialTestDialog(QDialog):
    def __init__(self, parent=None, spec: MaterialTestSpec | None = None):
        super().__init__(parent)
        self.setWindowTitle("Materialtest-Raster")
        s = spec or MaterialTestSpec()
        f = QFormLayout(self)
        self.p_min = _spin(1, 100, s.power_min, suffix=" %")
        self.p_max = _spin(1, 100, s.power_max, suffix=" %")
        self.cols = _spin(1, 12, s.columns)
        self.s_min = _spin(1, 6000, s.speed_min, 100, suffix=" mm/min")
        self.s_max = _spin(1, 6000, s.speed_max, 100, suffix=" mm/min")
        self.rows = _spin(1, 12, s.rows)
        self.cell = _spin(2, 60, s.cell_mm, 1, 1, " mm")
        self.gap = _spin(0, 30, s.gap_mm, 1, 1, " mm")
        self.x = _spin(0, 360, s.x, 5, 1, " mm")
        self.y = _spin(0, 340, s.y, 5, 1, " mm")
        self.passes = _spin(1, 30, s.passes)
        self.mode = QComboBox()
        self.mode.addItems(["Füllen (Gravur)", "Kontur (Schnitt)"])
        self.interval = _spin(0.05, 2.0, s.line_interval_mm or 0.2, 0.05, 2, " mm")
        self.labels = QCheckBox("Beschriftung (Leistung % / Geschw. mm/s)")
        self.labels.setChecked(s.labels)
        for label, w in (("Leistung von", self.p_min), ("Leistung bis", self.p_max),
                         ("Spalten (Leistung)", self.cols), ("Geschw. von", self.s_min),
                         ("Geschw. bis", self.s_max), ("Zeilen (Geschw.)", self.rows),
                         ("Zellgröße", self.cell), ("Abstand", self.gap), ("Position X", self.x),
                         ("Position Y", self.y), ("Durchgänge", self.passes), ("Art", self.mode),
                         ("Linienabstand", self.interval), ("", self.labels)):
            f.addRow(label, w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def spec(self) -> MaterialTestSpec:
        return MaterialTestSpec(
            power_min=self.p_min.value(), power_max=self.p_max.value(), columns=self.cols.value(),
            speed_min=self.s_min.value(), speed_max=self.s_max.value(), rows=self.rows.value(),
            cell_mm=self.cell.value(), gap_mm=self.gap.value(), x=self.x.value(), y=self.y.value(),
            passes=self.passes.value(),
            line_interval_mm=self.interval.value() if self.mode.currentIndex() == 0 else 0.0,
            labels=self.labels.isChecked())


def insert_material_test(editor, spec: MaterialTestSpec) -> int:
    """Add the grid to the editor's document as one undo step. Returns #layers."""
    layers, shapes = build_material_test(spec)
    stack = editor.undo_stack
    stack.beginMacro("Materialtest einfügen")
    try:
        for layer in reversed(layers):
            stack.push(AddLayerCommand(editor.document, layer, 0))
        stack.push(AddShapesCommand(editor.document, shapes, "Materialtest"))
    finally:
        stack.endMacro()
    return len(layers)


class JobTools(QObject):
    def __init__(self, window, editor, machine_panel, status_bar):
        super().__init__(window)
        self.window = window
        self.editor = editor
        self.machine = machine_panel
        self.status = status_bar
        self.toolbar = QToolBar("Auftrag")
        self.toolbar.setObjectName("lumacut_job_toolbar")
        self.toolbar.setMovable(False)
        self.estimate_action = self._add("Zeit schätzen", self.show_estimate, "Alt+P",
                                         "Laufzeit, Schnitt- und Leerfahrtstrecke berechnen")
        self.frame_action = self._add("Rahmen", self.frame_job, "Ctrl+Shift+F",
                                      "Umriss des Auftrags mit ausgeschaltetem Laser abfahren")
        self.hull_action = self._add("Gummiband-Rahmen", lambda: self.frame_job("hull"), "Alt+Shift+F",
                                     "Konvexe Hülle statt Rechteck abfahren")
        self.test_action = self._add("Materialtest…", self.material_test, None,
                                     "Leistung × Geschwindigkeit-Testraster einfügen")
        window.addToolBar(self.toolbar)

    def _add(self, text, slot, shortcut, tip):
        a = QAction(text, self.window)
        a.setToolTip(tip)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(lambda _=False: slot())
        self.toolbar.addAction(a)
        return a

    def _msg(self, text, ms=8000):
        self.status.showMessage(text, ms)

    def estimate(self):
        return estimate_gcode(optimized_document_gcode(self.editor.document))

    def show_estimate(self):
        try:
            est = self.estimate()
        except ValueError as exc:
            self._msg(f"Keine Schätzung: {exc}")
            return None
        self._msg(f"Auftrag {est.summary()} (ohne Referenzfahrt/Fokus/Parken)", 15000)
        return est

    def frame_job(self, mode: str = "box", confirm: bool = True):
        try:
            g = frame_gcode(optimize_layers(job_layers(self.editor.document)), mode=mode)
        except ValueError as exc:
            self._msg(f"Rahmen nicht möglich: {exc}")
            return None
        if confirm and QMessageBox.question(
                self.window, "Rahmen",
                "Umriss mit ausgeschaltetem Laser abfahren?\n"
                "Danach vor 'Start Job' erneut 'Design senden'.") != QMessageBox.Yes:
            return None
        self.machine.send_gcode("lumacut-frame.gcode", g, start=True)
        self._msg("Rahmen gesendet – danach 'Design senden' vor 'Start Job'")
        return g

    def material_test(self, spec: MaterialTestSpec | None = None):
        if spec is None:
            dlg = MaterialTestDialog(self.window)
            if dlg.exec() != QDialog.Accepted:
                return 0
            spec = dlg.spec()
        try:
            n = insert_material_test(self.editor, spec)
        except ValueError as exc:
            self._msg(f"Materialtest: {exc}")
            return 0
        self._msg(f"Materialtest mit {n} Ebenen eingefügt")
        return n


def install_job_tools(window) -> JobTools:
    """Attach the job toolbar to ``LumaCutStudio`` (needs canvas, machine_panel)."""
    tools = JobTools(window, window.canvas, window.machine_panel, window.statusBar())
    window.job_tools = tools
    return tools
