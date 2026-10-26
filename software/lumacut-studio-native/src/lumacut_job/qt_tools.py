"""Qt glue: a "Auftrag" toolbar with time estimate, framing and material test.

Installed by ``main.py`` with :func:`install_job_tools`; it only *uses* the
public APIs of the canvas editor (``document``, ``undo_stack``) and the
machine panel (``frame_gcode``, ``set_frame_provider``) and owns no state of
theirs. Framing runs on the Pi as ``op=frame`` and never replaces the job
that was sent before.
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
from .planner import PlanReport, optimize_layers, optimized_document_gcode


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
        self.serial_action = self._add("Seriennummern…", self.serial_numbers, "Alt+N",
                                       "Ausgewählten Text als Raster fortlaufend nummerierter Kopien "
                                       "(Platzhalter {n}, {n:3}, {date})")
        self.serial_action.setObjectName("serial_numbers_action")
        self.cut_action = self._add("Schnittoptionen…", self.cut_options, "Alt+K",
                                    "Kerf-Versatz, Haltestege und An-/Abfahrt der aktiven Ebene")
        self.selection_action = self._add("Nur Auswahl", self._selection_toggled, None,
                                          "Senden, Schätzen, Rahmen und Speichern nur mit den "
                                          "ausgewählten Objekten (wie „Cut Selected Graphics“)")
        self.selection_action.setCheckable(True)
        self.save_action = self._add("G-Code speichern…", self.save_gcode, "Alt+G",
                                     "Optimierten G-Code des Designs als Datei speichern")
        self.history_action = self._add("Verlauf…", self.show_history, "Ctrl+H",
                                        "Zuletzt gesendete Aufträge erneut senden oder speichern")
        window.addToolBar(self.toolbar)
        from .history import JobHistory
        from .history_qt import attach_history, default_dir
        self.history = JobHistory(default_dir())
        self._send_without_history = (attach_history(machine_panel, self.history)
                                      if hasattr(machine_panel, "send_gcode") else None)
        if hasattr(machine_panel, "set_frame_provider"):
            machine_panel.set_frame_provider(self.frame_program)
        signal = getattr(machine_panel, "frame_available_changed", None)
        if signal is not None:
            signal.connect(self._sync_frame_actions)
            self._sync_frame_actions(bool(getattr(machine_panel, "frame_available", False)))

    def _sync_frame_actions(self, available: bool) -> None:
        tip = "" if available else " (erst verbinden und referenzieren; nicht während Auftrag)"
        for action, text in ((self.frame_action, "Umriss des Auftrags mit ausgeschaltetem Laser abfahren"),
                             (self.hull_action, "Konvexe Hülle statt Rechteck abfahren")):
            action.setEnabled(available)
            action.setToolTip(text + tip)

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

    # --- Auftrag (ganzes Design oder nur Auswahl) ---------------------------
    @property
    def selection_only(self) -> bool:
        return self.selection_action.isChecked()

    def set_selection_only(self, on: bool) -> None:
        self.selection_action.setChecked(bool(on))
        self._selection_toggled()

    def _selection_toggled(self) -> None:
        self._msg("Auftrag: nur ausgewählte Objekte" if self.selection_only
                  else "Auftrag: ganzes Design")

    def job_document(self):
        """Dokument für den Auftrag; ValueError bei „Nur Auswahl“ ohne Auswahl."""
        doc = self.editor.document
        if not getattr(self, "selection_only", False):
            return doc
        from .selection import selection_document
        return selection_document(doc, getattr(self.editor, "selection", ()) or ())

    def job_gcode(self) -> tuple[str, str]:
        """(optimierter G-Code, Hinweis des Planers) – wie beim Senden.

        Der Hinweis meldet z. B. weggelassene An-/Abfahrten (Kollision mit
        anderen Teilen) und ist leer, wenn nichts zu melden ist.
        """
        report = PlanReport()
        g = optimized_document_gcode(self.job_document(), report=report)
        note = report.message()
        if self.selection_only:
            note = ("Nur Auswahl. " + note).strip()
        return g, note

    def estimate(self):
        return estimate_gcode(self.job_gcode()[0])

    def show_estimate(self):
        try:
            g, note = self.job_gcode()
        except ValueError as exc:
            self._msg(f"Keine Schätzung: {exc}")
            return None
        est = estimate_gcode(g)
        text = f"Auftrag {est.summary()} (ohne Referenzfahrt/Fokus/Parken)"
        if est.layer_summary():
            text += f" – {est.layer_summary()}"
        if note:
            text += f" – {note}"
        self._msg(text, 15000)
        return est

    def frame_program(self, mode: str = "box") -> str:
        """Frame G-code (laser off) of the current design; ValueError if empty."""
        from .images import image_outline_layers
        doc = JobTools.job_document(self)
        return frame_gcode(optimize_layers(job_layers(doc)) + image_outline_layers(doc), mode=mode)

    def frame_job(self, mode: str = "box", confirm: bool = True):
        try:
            g = self.frame_program(mode)
        except ValueError as exc:
            self._msg(f"Rahmen nicht möglich: {exc}")
            return None
        if confirm and QMessageBox.question(
                self.window, "Rahmen",
                "Umriss mit ausgeschaltetem Laser abfahren?\n"
                "Der gesendete Auftrag bleibt geladen und kann danach direkt "
                "gestartet werden.") != QMessageBox.Yes:
            return None
        if not self.machine.frame_gcode(g, mode):
            self._msg("Rahmen nicht gestartet – siehe Maschinen-Panel")
            return None
        self._msg("Rahmenfahrt angefordert (Laser aus) – gesendeter Auftrag bleibt geladen")
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


    def serial_numbers(self, spec=None) -> list[str]:
        """Ausgewählten Text durch nummerierte Kopien ersetzen (ein Undo-Schritt)."""
        from .serial_qt import SerialDialog, insert_serials
        doc = self.editor.document
        sel = [i for i in self.editor.selection if doc.has_shape(i)]
        if len(sel) != 1 or doc.shape(sel[0]).kind != "text":
            self._msg("Seriennummern: bitte genau ein Textobjekt auswählen")
            return []
        src = doc.shape(sel[0])
        if spec is None:
            dlg = SerialDialog(src.text, self.window)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec = dlg.spec()
        try:
            ids = insert_serials(self.editor, src.id, spec)
        except ValueError as exc:
            QMessageBox.warning(self.window, "Seriennummern", str(exc))
            self._msg(f"Seriennummern: {exc}")
            return []
        self._msg(f"{len(ids)} nummerierte Texte erzeugt (gruppiert)")
        return ids

    def cut_options(self, values: dict | None = None) -> bool:
        """Schnittoptionen der aktiven Ebene bearbeiten (ein Undo-Schritt)."""
        from .cut_qt import CutOptionsDialog, apply_cut_options, summary
        doc = self.editor.document
        layer = doc.active_layer or (doc.layers[0] if doc.layers else None)
        if layer is None:
            self._msg("Schnittoptionen: keine Ebene vorhanden")
            return False
        if values is None:
            dlg = CutOptionsDialog(layer, self.window)
            if dlg.exec() != QDialog.Accepted:
                return False
            values = dlg.values()
        changed = apply_cut_options(self.editor, layer.id, values)
        text = summary(doc.layer(layer.id)) or "alle aus"
        self._msg(f"Schnittoptionen „{layer.name}“: {text}" if changed
                  else "Schnittoptionen unverändert")
        return changed


    def save_gcode(self, path: str | None = None) -> str:
        """Optimierten G-Code (wie beim Senden, ohne Scan-Fokuskorrektur) speichern."""
        from .history_qt import save_gcode_file
        try:
            g, note = self.job_gcode()
        except ValueError as exc:
            self._msg(f"Speichern nicht möglich: {exc}")
            return ""
        fp = getattr(self.editor, "file_path", None)
        name = (fp.name.split(".")[0] if fp else "auftrag") + ".gcode"
        if path is None:
            path = save_gcode_file(self.window, g, name)
        else:
            from pathlib import Path
            Path(path).write_text(g, encoding="utf-8", newline="\n")
        if path:
            self._msg(f"G-Code gespeichert: {path}" + (f" – {note}" if note else ""))
        return path

    def show_history(self, modal: bool = True):
        from .history_qt import HistoryDialog

        def send(name, gcode):
            if self._send_without_history is None:
                return
            self._send_without_history(name, gcode, start=False)
            self._msg(f"Erneut gesendet: {name} – mit „Start“ ausführen")
        dlg = HistoryDialog(self.history, send, self.window)
        if modal:
            dlg.exec()
        return dlg


def install_job_tools(window) -> JobTools:
    """Attach the job toolbar to ``LumaCutStudio`` (needs canvas, machine_panel)."""
    tools = JobTools(window, window.canvas, window.machine_panel, window.statusBar())
    window.job_tools = tools
    return tools
