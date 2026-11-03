"""Qt glue: a "Auftrag" toolbar with time estimate, framing and material test.

Installed by ``main.py`` with :func:`install_job_tools`; it only *uses* the
public APIs of the canvas editor (``document``, ``undo_stack``) and the
machine panel (``frame_gcode``, ``set_frame_provider``) and owns no state of
theirs. Framing runs on the Pi as ``op=frame`` and never replaces the job
that was sent before.
"""

from __future__ import annotations

from dataclasses import replace

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
        self.vartext_action = self._add("Variabler Text…", self.variable_text, "Alt+V",
                                        "Ausgewählte Texte beim Senden auswerten: Zähler {n}, "
                                        "Datum/Uhrzeit, CSV-Spalten {Name} – zählt nach jedem "
                                        "gesendeten Auftrag weiter")
        self.vartext_action.setObjectName("variable_text_action")
        self.qr_action = self._add("QR-Code…", self.qr_code, "Alt+Q",
                                   "QR-Code (Text/Adresse) als gefüllte Vektorflächen einfügen")
        self.qr_action.setObjectName("qr_code_action")
        self.barcode_action = self._add("Barcode einfügen…", self.barcode, "Alt+C",
                                        "Strichcode (Code 128, EAN-13/-8, UPC-A) als gefüllte "
                                        "Vektorstriche einfügen")
        self.barcode_action.setObjectName("barcode_action")
        self.datamatrix_action = self._add("Data Matrix…", self.datamatrix, "Alt+X",
                                           "2D-Code Data Matrix (ECC 200) als gefüllte "
                                           "Vektorflächen einfügen")
        self.datamatrix_action.setObjectName("datamatrix_action")
        self.aztec_action = self._add("Aztec-Code…", self.aztec, "Alt+Z",
                                      "2D-Code Aztec (kompakt, ohne Ruhezone) als gefüllte "
                                      "Vektorflächen einfügen")
        self.aztec_action.setObjectName("aztec_action")
        self.pdf417_action = self._add("PDF417-Code…", self.pdf417, "Alt+F",
                                       "Gestapelter 2D-Code PDF417 (auch kompakt) als gefüllte "
                                       "Vektorflächen einfügen")
        self.pdf417_action.setObjectName("pdf417_action")
        self.arc_action = self._add("Bogentext…", self.arc_text, "Alt+B",
                                    "Text entlang eines Kreisbogens als Vektorpfade einfügen "
                                    "(ausgewählter Text wird übernommen)")
        self.arc_action.setObjectName("arc_text_action")
        self.edit_generated_action = self._add(
            "Code bearbeiten…", self.edit_generated, "Alt+E",
            "Ausgewählten QR-Code, Barcode, Data Matrix, Aztec-, PDF417-Code oder Bogentext mit seinen "
            "Parametern "
            "neu erzeugen (auch per Doppelklick)")
        self.edit_generated_action.setObjectName("edit_generated_action")
        # Double click with the select tool (lumacut_canvas.tools) asks this hook first.
        editor.generated_edit_handler = self.edit_generated_at
        self.cut_action = self._add("Schnittoptionen…", self.cut_options, "Alt+K",
                                    "Kerf-Versatz, Haltestege und An-/Abfahrt der aktiven Ebene")
        self.scan_offset_action = self._add(
            "Scan-Versatz…", self.scan_offset, None,
            "Versatz hin-/rücklaufender Linien je Geschwindigkeit ausgleichen (Bilder und "
            "Schraffur, wie LightBurn „Scanning Offset Adjustment“) – mit Testmuster")
        self.scan_offset_action.setObjectName("scan_offset_action")
        self._load_scan_offset()
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
        if hasattr(machine_panel, "send_gcode"):
            # Park corner (Pi 9ae8577): refuse before uploading, not at the Pi.
            from .park_corner import attach_park_check
            attach_park_check(machine_panel, lambda text: self._msg(text, 15000))
        # Variable text (lumacut_job.vartext): outermost wrapper, advances after a successful upload.
        self.vartext_tracker = None
        if hasattr(machine_panel, "send_gcode"):
            from .vartext_qt import VarTextTracker
            self.vartext_tracker = VarTextTracker(editor, machine_panel,
                                                  lambda text: self._msg(text, 10000), self)
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

    def _job_source(self):
        doc = self.editor.document
        if not getattr(self, "selection_only", False):
            return doc
        from .selection import selection_document
        return selection_document(doc, getattr(self.editor, "selection", ()) or ())

    def job_document_and_usage(self):
        """(Auftragsdokument, verwendete variable Texte) – Platzhalter ausgewertet."""
        from .vartext import evaluate_document
        return evaluate_document(JobTools._job_source(self))

    def job_document(self):
        """Dokument für den Auftrag; ValueError bei „Nur Auswahl“ ohne Auswahl.

        Variable Texte sind darin schon ausgewertet (das Original behält die
        Vorlage); ValueError, wenn ein Platzhalter nicht auswertbar ist."""
        return JobTools.job_document_and_usage(self)[0]

    def job_gcode(self) -> tuple[str, str]:
        """(optimierter G-Code, Hinweis des Planers) – wie beim Senden.

        Der Hinweis meldet z. B. weggelassene An-/Abfahrten (Kollision mit
        anderen Teilen) und ist leer, wenn nichts zu melden ist. Mit variablem
        Text trägt der G-Code eine Markierung, damit das Hochladen genau dieses
        Auftrags Zähler/CSV-Zeile weiterschaltet.
        """
        report = PlanReport()
        doc, usage = self.job_document_and_usage()
        g = optimized_document_gcode(doc, report=report)
        note = report.message()
        if usage:
            tracker = getattr(self, "vartext_tracker", None)
            if tracker is not None:
                g = tracker.remember(g, usage)
            note = (note + " " + usage.summary()).strip()
        if self.selection_only:
            note = ("Nur Auswahl. " + note).strip()
        return g, note

    def estimate(self):
        return estimate_gcode(self.job_gcode()[0])

    def park_preflight(self, gcode: str, origin: str | None = None) -> str:
        """German refusal text if the Pi would refuse ``gcode`` because of the
        park corner (as sent, and at the panel's chosen origin unless
        ``origin`` is given), else ""."""
        from .park_corner import check_for_panel
        res = check_for_panel(self.machine, gcode, "absolute")
        if res.ok and origin != "absolute":
            res = check_for_panel(self.machine, gcode, origin)
        return "" if res.ok else res.message

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
        park = self.park_preflight(g)
        if park:
            text += f" – {park}"
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

    def variable_text(self, spec=None, template: str | None = None,
                      enabled: bool = True) -> list[str]:
        """Ausgewählte Texte als variablen Text einstellen (ein Undo-Schritt).

        Alle ausgewählten Texte (und die übrigen Kopien ihrer Serie) bilden
        eine Serie. ``spec`` ohne Dialog (Tests/Skripte); ``enabled=False``
        macht sie wieder zu normalem Text.
        """
        from . import vartext as vt
        from .vartext_qt import VarTextDialog, apply_vartext, describe, series_members
        doc = self.editor.document
        sel = [i for i in self.editor.selection
               if doc.has_shape(i) and doc.shape(i).kind == "text"]
        if not sel:
            self._msg("Variabler Text: bitte ein oder mehrere Textobjekte auswählen")
            return []
        keys = {vt.series_key(doc.shape(i)) for i in sel if vt.is_variable(doc.shape(i))}
        ids = list(sel)
        for key in keys:
            ids += [s.id for s in series_members(doc, key) if s.id not in ids]
        first = next((doc.shape(i) for i in ids if vt.is_variable(doc.shape(i))), None)
        start = vt.spec_of(first) if first is not None else vt.VarTextSpec()
        same = len(keys) == 1 and all(vt.is_variable(doc.shape(i)) for i in ids)
        series = start.series if same else ""
        if spec is None:
            visible = {l.id for l in doc.layers if l.visible}
            copies = sum(1 for i in ids if doc.shape(i).layer_id in visible) or 1
            dlg = VarTextDialog(doc.shape(sel[0]).text, replace(start, series=series), copies,
                                parent=self.window)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec, template, enabled = dlg.spec(), dlg.template_text(), dlg.is_enabled()
        else:
            spec = replace(spec, series=spec.series or series)
        try:
            changed = apply_vartext(self.editor, ids, spec if enabled else None, template)
        except ValueError as exc:
            self._msg(f"Variabler Text: {exc}")
            return []
        if not enabled:
            self._msg(f"Variabler Text aus – {len(changed)} Text(e) werden wörtlich gelasert")
            return changed
        tmpl = doc.shape(changed[0]).text
        if not vt.has_placeholders(tmpl):
            self._msg("Variabler Text: die Vorlage enthält noch keinen Platzhalter, z. B. "
                      "„Nr. {n:3}“ oder „{Name}“")
        else:
            self._msg(f"Variabler Text für {len(changed)} Text(e): "
                      f"{describe(vt.spec_of(doc.shape(changed[0])), tmpl)} – wird beim Senden "
                      "ausgewertet")
        return changed

    def qr_code(self, spec=None, fill_layer: bool | None = None) -> list[str]:
        """QR-Code einfügen (ein Undo-Schritt); Standard: aktive Ebene."""
        from .qr_qt import QrDialog, insert_qr, layer_fills
        doc = self.editor.document
        active = doc.active_layer or (doc.layers[0] if doc.layers else None)
        if spec is None:
            dlg = QrDialog(self.window, active_layer=active)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec, fill_layer = dlg.spec(), dlg.fill_layer()
        if fill_layer is None:
            fill_layer = not layer_fills(active)
        try:
            ids = insert_qr(self.editor, spec, fill_layer=fill_layer)
        except ValueError as exc:
            QMessageBox.warning(self.window, "QR-Code", str(exc))
            self._msg(f"QR-Code: {exc}")
            return []
        layer = doc.shape(ids[0]).layer_id if ids else ""
        name = doc.layer(layer).name if layer else ""
        kind = {"gs1": "GS1 QR-Code", "link": "GS1-Digital-Link-QR-Code"}.get(
            spec.normalized().mode, "QR-Code")
        self._msg(f"{kind} eingefügt ({len(ids)} Flächen, Ebene „{name}“)")
        return ids

    def barcode(self, spec=None, fill_layer: bool | None = None) -> list[str]:
        """Insert a 1D barcode (one undo step); default: active layer."""
        from .barcode_qt import BarcodeDialog, insert_barcode
        from .qr_qt import layer_fills
        doc = self.editor.document
        active = doc.active_layer or (doc.layers[0] if doc.layers else None)
        if spec is None:
            dlg = BarcodeDialog(self.window, active_layer=active)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec, fill_layer = dlg.spec(), dlg.fill_layer()
        if fill_layer is None:
            fill_layer = not layer_fills(active)
        try:
            ids = insert_barcode(self.editor, spec, fill_layer=fill_layer)
        except ValueError as exc:
            QMessageBox.warning(self.window, "Barcode", str(exc))
            self._msg(f"Barcode: {exc}")
            return []
        layer = doc.shape(ids[0]).layer_id if ids else ""
        name = doc.layer(layer).name if layer else ""
        self._msg(f"Barcode eingefügt ({len(ids)} Flächen, Ebene „{name}“)")
        return ids

    def datamatrix(self, spec=None, fill_layer: bool | None = None) -> list[str]:
        """Insert a Data Matrix ECC 200 symbol (one undo step); default: active layer."""
        from .datamatrix_qt import DataMatrixDialog, insert_datamatrix
        from .qr_qt import layer_fills
        doc = self.editor.document
        active = doc.active_layer or (doc.layers[0] if doc.layers else None)
        if spec is None:
            dlg = DataMatrixDialog(self.window, active_layer=active)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec, fill_layer = dlg.spec(), dlg.fill_layer()
        if fill_layer is None:
            fill_layer = not layer_fills(active)
        try:
            ids = insert_datamatrix(self.editor, spec, fill_layer=fill_layer)
        except ValueError as exc:
            QMessageBox.warning(self.window, "Data Matrix", str(exc))
            self._msg(f"Data Matrix: {exc}")
            return []
        layer = doc.shape(ids[0]).layer_id if ids else ""
        name = doc.layer(layer).name if layer else ""
        self._msg(f"Data Matrix eingefügt ({len(ids)} Flächen, Ebene „{name}“)")
        return ids

    def aztec(self, spec=None, fill_layer: bool | None = None) -> list[str]:
        """Insert an Aztec code (one undo step); default: active layer."""
        from .aztec_qt import AztecDialog, insert_aztec
        from .qr_qt import layer_fills
        doc = self.editor.document
        active = doc.active_layer or (doc.layers[0] if doc.layers else None)
        if spec is None:
            dlg = AztecDialog(self.window, active_layer=active)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec, fill_layer = dlg.spec(), dlg.fill_layer()
        if fill_layer is None:
            fill_layer = not layer_fills(active)
        try:
            ids = insert_aztec(self.editor, spec, fill_layer=fill_layer)
        except ValueError as exc:
            QMessageBox.warning(self.window, "Aztec-Code", str(exc))
            self._msg(f"Aztec-Code: {exc}")
            return []
        layer = doc.shape(ids[0]).layer_id if ids else ""
        name = doc.layer(layer).name if layer else ""
        self._msg(f"Aztec-Code eingefügt ({len(ids)} Flächen, Ebene „{name}“)")
        return ids

    def pdf417(self, spec=None, fill_layer: bool | None = None) -> list[str]:
        """Insert a PDF417 code (one undo step); default: active layer."""
        from .pdf417_qt import Pdf417Dialog, insert_pdf417
        from .qr_qt import layer_fills
        doc = self.editor.document
        active = doc.active_layer or (doc.layers[0] if doc.layers else None)
        if spec is None:
            dlg = Pdf417Dialog(self.window, active_layer=active)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec, fill_layer = dlg.spec(), dlg.fill_layer()
        if fill_layer is None:
            fill_layer = not layer_fills(active)
        try:
            ids = insert_pdf417(self.editor, spec, fill_layer=fill_layer)
        except ValueError as exc:
            QMessageBox.warning(self.window, "PDF417-Code", str(exc))
            self._msg(f"PDF417-Code: {exc}")
            return []
        layer = doc.shape(ids[0]).layer_id if ids else ""
        name = doc.layer(layer).name if layer else ""
        self._msg(f"PDF417-Code eingefügt ({len(ids)} Flächen, Ebene „{name}“)")
        return ids

    def arc_text(self, spec=None, replace: bool | None = None) -> list[str]:
        """Bogentext einfügen (ein Undo-Schritt); ein ausgewählter Text wird übernommen."""
        from .arctext_qt import ArcTextDialog, insert_arc_text, spec_from_text
        doc = self.editor.document
        sel = [i for i in (self.editor.selection or ()) if doc.has_shape(i)]
        src = doc.shape(sel[0]) if len(sel) == 1 and doc.shape(sel[0]).kind == "text" else None
        if spec is None:
            dlg = ArcTextDialog(self.window, spec_from_text(src) if src else None,
                                can_replace=src is not None)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec, replace = dlg.spec(), dlg.replace_source()
        replace_id = src.id if (src is not None and replace) else None
        try:
            ids = insert_arc_text(self.editor, spec, replace_id)
        except ValueError as exc:
            QMessageBox.warning(self.window, "Bogentext", str(exc))
            self._msg(f"Bogentext: {exc}")
            return []
        self._msg(f"Bogentext eingefügt ({len(ids)} Zeichen, gruppiert)"
                  + (" – Text ersetzt" if replace_id else ""))
        return ids

    def edit_generated_at(self, shape_id: str) -> bool:
        """Double-click hook: True if ``shape_id`` belongs to a generated object
        (the dialog was shown, even if cancelled)."""
        from .generated_qt import generated_unit
        from .vartext import is_variable
        doc = self.editor.document
        if doc.has_shape(shape_id) and is_variable(doc.shape(shape_id)):
            return False   # variable text: double click edits the template as usual
        try:
            unit = generated_unit(self.editor, shape_id)
        except ValueError as exc:
            self._msg(str(exc))
            return True
        if unit is None:
            return False
        self.edit_generated(shape_id=shape_id)
        return True

    def edit_generated(self, spec=None, shape_id: str | None = None) -> list[str]:
        """Re-create the selected QR code / barcode / Data Matrix / arc text with
        changed parameters (one undo step, same place, rotation and layer)."""
        from .generated_qt import edit_dialog, generated_unit, replace_unit, unit_spec
        try:
            unit = generated_unit(self.editor, shape_id)
        except ValueError as exc:
            self._msg(f"Code bearbeiten: {exc}")
            return []
        if unit is None:
            self._msg("Code bearbeiten: bitte einen QR-Code, Barcode, Data Matrix oder "
                      "Bogentext auswählen (Doppelklick genügt)")
            return []
        doc = self.editor.document
        if spec is None:
            try:
                start = unit_spec(unit)
            except ValueError as exc:
                self._msg(f"{unit.label} bearbeiten: {exc}")
                return []
            dlg = edit_dialog(unit, start, doc.layer(unit.layer_id), self.window)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec = dlg.spec()
        try:
            ids = replace_unit(self.editor, unit, spec)
        except ValueError as exc:
            QMessageBox.warning(self.window, f"{unit.label} bearbeiten", str(exc))
            self._msg(f"{unit.label}: {exc}")
            return []
        self._msg(f"{unit.label} neu erzeugt ({len(ids)} Flächen, Ebene "
                  f"„{doc.layer(unit.layer_id).name}“)")
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


    # --- Scan-Versatz (lumacut_job.scan_offset) ------------------------------
    def _load_scan_offset(self) -> None:
        from .scan_offset import set_active_table
        from .scan_offset_qt import default_settings, load_table
        table = load_table(default_settings())
        if table is not None:
            set_active_table(table)
            self._refresh_scan_previews()

    def _refresh_scan_previews(self) -> None:
        """Pfad- und Schraffur-Vorschau neu berechnen (Scan-Versatz geändert)."""
        for name in ("path_preview", "fill_preview"):
            preview = getattr(self.editor, name, None)
            if callable(getattr(preview, "schedule", None)):
                preview.schedule()

    def scan_offset(self, table=None):
        """Scan-Versatz-Tabelle bearbeiten, aktivieren und speichern.

        ``table`` (Tests) überspringt den Dialog. Gibt die neue Tabelle
        zurück oder None (abgebrochen)."""
        from .scan_offset import active_table, set_active_table
        from .scan_offset_qt import ScanOffsetDialog, default_settings, save_table
        if table is None:
            dlg = ScanOffsetDialog(active_table(), self.window,
                                   test_callback=lambda d: self.scan_test(parent=d))
            if dlg.exec() != QDialog.Accepted:
                return None
            table = dlg.table()
        try:
            table = table.normalized()
        except ValueError as exc:
            self._msg(str(exc))
            return None
        set_active_table(table)
        save_table(default_settings(), table)
        self._refresh_scan_previews()   # Pfad-/Schraffur-Vorschau = Auftrag, mit neuem Versatz
        self._msg(table.summary() + " – gilt für Bilder und Schraffur" if table.active
                  else "Scan-Versatz aus")
        return table

    def scan_test(self, spec=None, action: str | None = None, path: str | None = None,
                  parent=None) -> str:
        """Kalibrier-Testmuster: Dialog, oder mit ``spec`` direkt ``action``
        "send" (hochladen ohne Start) / "save" (``path``). Gibt den G-Code zurück."""
        from .scan_offset import test_pattern_gcode
        from .scan_offset_qt import ScanTestDialog

        def send(g):
            if not hasattr(self.machine, "send_gcode"):
                self._msg("Scan-Test: kein Maschinen-Panel")
                return
            self.machine.send_gcode("scan-versatz-test.gcode", g, start=False)
            self._msg("Scan-Versatz-Test gesendet – mit „Start“ ausführen, dann je Reihe das "
                      "Feld mit geraden Kanten in die Tabelle übernehmen", 15000)

        def save(g, target=None):
            from .history_qt import save_gcode_file
            if target is None:
                target = save_gcode_file(parent or self.window, g, "scan-versatz-test.gcode")
            else:
                from pathlib import Path
                Path(target).write_text(g, encoding="utf-8", newline="\n")
            if target:
                self._msg(f"Scan-Versatz-Test gespeichert: {target}")

        if spec is None:
            dlg = ScanTestDialog(None, parent or self.window, send, save)
            dlg.exec()
            return dlg.result_gcode
        try:
            g = test_pattern_gcode(spec)
        except ValueError as exc:
            self._msg(str(exc))
            return ""
        if action == "send":
            send(g)
        elif action == "save":
            save(g, path)
        return g

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
