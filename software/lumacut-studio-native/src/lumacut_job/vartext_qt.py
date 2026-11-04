"""Qt part of :mod:`lumacut_job.vartext`: the dialog „Variabler Text…“, the
undoable apply step and the tracker that advances counter / CSV row after a
successful upload.

The tracker wraps ``MachinePanel.send_gcode`` (like the job history and the
park-corner check). A job built by ``JobTools.job_gcode`` with variable text
carries a comment ``; VARIABLE TEXT <token>``; only an upload of exactly such
a job (and only once the panel reports the upload as done) advances the
values. Re-sending an older job from the history, a failed or refused upload
or a G-code file never advances anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, replace

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from lumacut_canvas.edit_commands import ReplaceShapeCommand

from . import vartext as vt

MARKER = "; VARIABLE TEXT "
_MARKER_RE = re.compile(r"^; VARIABLE TEXT ([0-9a-f]{12})\s*$", re.M)
UPLOAD_LABELS = ("Senden", "Senden & Starten", "Auftrag starten")
PREVIEW_ROWS = 500
HELP = ("{n} Zähler · {n:3} dreistellig mit Nullen · {date} Datum · {date:%Y-%m-%d} · "
        "{time} Uhrzeit · {Spalte} CSV-Spalte · {csv:2} 2. Spalte · {row} CSV-Zeile · "
        "{{ }} Klammern")


# --- job marker ---------------------------------------------------------------

def usage_token(usage: vt.JobUsage) -> str:
    data = [(u.key, asdict(u.spec), u.ids, u.texts) for u in usage.series]
    return hashlib.sha1(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def mark_gcode(gcode: str, token: str) -> str:
    """Insert the marker comment after the header line."""
    lines = gcode.split("\n", 1)
    rest = lines[1] if len(lines) > 1 else ""
    return f"{lines[0]}\n{MARKER}{token}\n{rest}"


def gcode_token(gcode: str) -> str:
    m = _MARKER_RE.search(gcode[:4000] if gcode else "")
    return m.group(1) if m else ""


# --- apply / advance ------------------------------------------------------------

def series_members(doc, key: str) -> list:
    return [s for s in doc.shapes if vt.is_variable(s) and vt.series_key(s) == key]


def apply_vartext(editor, ids, spec: vt.VarTextSpec | None, template: str | None = None) -> list[str]:
    """Make the text objects ``ids`` one variable-text series with ``spec``
    (``None`` = back to plain text). ``template`` replaces their text if given.
    One undo step. Returns the changed ids."""
    doc = editor.document
    shapes = [doc.shape(i) for i in ids if doc.has_shape(i) and doc.shape(i).kind == "text"]
    if not shapes:
        raise ValueError("Bitte ein oder mehrere Textobjekte auswählen")
    for s in shapes:
        layer = doc.layer(s.layer_id)
        if layer is not None and layer.locked:
            raise ValueError(f"Ebene „{layer.name}“ ist gesperrt")
    meta = None
    if spec is not None:
        spec = spec.normalized()
        if not spec.series:
            spec = replace(spec, series=vt.new_series())
        meta = vt.make_meta(spec)
    stack = editor.undo_stack
    stack.beginMacro("Variabler Text" if meta else "Variablen Text entfernen")
    try:
        for s in shapes:
            new = s.copy()
            new.generator = meta
            if template is not None and template.strip():
                new.text = template
            stack.push(ReplaceShapeCommand(doc, new, "Variabler Text"))
    finally:
        stack.endMacro()
    return [s.id for s in shapes]


def advance(editor, usage: vt.JobUsage) -> list[vt.VarTextSpec]:
    """Store the next values of every series in ``usage`` (one undo step)."""
    doc = editor.document
    todo = []
    for u in usage.series:
        nxt = u.next_spec()
        for s in series_members(doc, u.key):
            new = s.copy()
            new.generator = vt.make_meta(replace(nxt, series=vt.spec_of(s).series))
            todo.append(new)
    if not todo:
        return []
    stack = editor.undo_stack
    stack.beginMacro("Variablen Text weiterschalten")
    try:
        for new in todo:
            stack.push(ReplaceShapeCommand(doc, new, "Variablen Text weiterschalten"))
    finally:
        stack.endMacro()
    return [u.next_spec() for u in usage.series]


def describe(spec: vt.VarTextSpec, template: str = "") -> str:
    parts = []
    if not template or vt.uses_counter(template):
        parts.append(f"nächster Wert {vt.format_counter(spec.current, spec.pad)}")
    if spec.csv_path:
        parts.append(f"CSV-Zeile {spec.csv_row}")
    return " · ".join(parts)


class VarTextTracker(QObject):
    """Advance variable text after a successful upload of a marked job."""

    MAX_PENDING = 16

    def __init__(self, editor, panel, report=None, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.panel = panel
        self.report = report
        self._pending: dict[str, vt.JobUsage] = {}
        self._awaiting: tuple[str, str, vt.JobUsage] | None = None
        self.original = panel.send_gcode
        panel.send_gcode = self._send_gcode
        self._signal = getattr(panel, "command_finished", None)
        if self._signal is not None:
            self._signal.connect(self._finished)

    def remember(self, gcode: str, usage: vt.JobUsage) -> str:
        """Mark ``gcode`` as a job with ``usage``; returns the marked G-code."""
        token = usage_token(usage)
        self._pending.pop(token, None)
        self._pending[token] = usage
        while len(self._pending) > self.MAX_PENDING:
            self._pending.pop(next(iter(self._pending)))
        return mark_gcode(gcode, token)

    def _send_gcode(self, name, gcode, start=False, **kwargs):
        token = gcode_token(gcode)
        usage = self._pending.get(token) if token else None
        self._awaiting = (name, token, usage) if usage else None
        gen0 = getattr(self.panel, "_upload_gen", None)
        result = self.original(name, gcode, start=start, **kwargs)
        if usage is None:
            return result
        gen1 = getattr(self.panel, "_upload_gen", None)
        if result is False or (gen0 is not None and gen1 == gen0):
            self._awaiting = None          # refused or never dispatched
        elif self._signal is None:
            self._awaiting = None          # no async feedback: dispatched = sent
            self._advance(usage)
        return result

    def _finished(self, label: str, ok: bool) -> None:
        if self._awaiting is None or label not in UPLOAD_LABELS:
            return
        name, _token, usage = self._awaiting
        self._awaiting = None
        # Advance only if the command succeeded *and* the panel recorded exactly this upload
        # (a failed start after the upload keeps the values: re-send lasers the same text).
        uploaded = getattr(self.panel, "_uploaded", None)
        if ok and (uploaded is None or uploaded == name):
            self._advance(usage)

    def _advance(self, usage: vt.JobUsage) -> None:
        self._pending.clear()               # older builds refer to old values
        specs = advance(self.editor, usage)
        if specs and self.report is not None:
            text = "; ".join(describe(s) for s in specs if describe(s))
            self.report(f"Variabler Text weitergeschaltet: {text}")


# --- dialog ---------------------------------------------------------------------

class VarTextDialog(QDialog):
    """Settings of one variable-text series (template, counter, CSV)."""

    def __init__(self, template: str, spec: vt.VarTextSpec | None = None, copies: int = 1,
                 enabled: bool = True, parent=None, show_values: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Variabler Text")
        self.copies = max(1, int(copies))
        self._initial_template = template
        spec = (spec or vt.VarTextSpec()).normalized()
        self._series = spec.series
        self._table: vt.CsvTable | None = None
        lay = QVBoxLayout(self)
        self.enabled = QCheckBox("Platzhalter beim Senden auswerten (variabler Text)")
        self.enabled.setChecked(enabled)
        lay.addWidget(self.enabled)
        form = QFormLayout()
        self.template = QLineEdit(template)
        self.template.setToolTip(HELP)
        form.addRow("Vorlage", self.template)
        help_label = QLabel(HELP)
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #93a1b5;")
        form.addRow("", help_label)
        lay.addLayout(form)

        counter = QGroupBox("Zähler {n}")
        cf = QFormLayout(counter)
        self.start = self._int(vt.VALUE_RANGE, spec.start)
        self.step = self._int(vt.STEP_RANGE, spec.step)
        self.pad = self._int(vt.PAD_RANGE, spec.pad)
        self.pad.setToolTip("Stellen mit führenden Nullen für {n} (0 = ohne)")
        self.current = self._int(vt.VALUE_RANGE, spec.current)
        self.current.setToolTip("Dieser Wert wird beim nächsten Senden gelasert; danach wird "
                                "weitergezählt (im Projekt gespeichert)")
        self.reset_button = QPushButton("Auf Start")
        self.reset_button.clicked.connect(lambda: self.current.setValue(self.start.value()))
        row = QHBoxLayout()
        row.addWidget(self.current, 1)
        row.addWidget(self.reset_button)
        cf.addRow("Start", self.start)
        cf.addRow("Schritt", self.step)
        cf.addRow("Stellen", self.pad)
        cf.addRow("Nächster Wert", row)
        self.per_copy = QCheckBox("Kopien im Auftrag fortlaufend (jede Kopie nächster Wert / "
                                  "nächste Zeile)")
        self.per_copy.setChecked(spec.per_copy)
        cf.addRow("", self.per_copy)
        lay.addWidget(counter)

        merge = QGroupBox("CSV-Serienbrief")
        mf = QFormLayout(merge)
        self.csv_path = QLineEdit(spec.csv_path)
        self.csv_path.setPlaceholderText("keine – Spalten als {Name} in der Vorlage")
        self.browse_button = QPushButton("Datei…")
        self.browse_button.clicked.connect(self._browse)
        self.clear_button = QPushButton("Entfernen")
        self.clear_button.clicked.connect(lambda: self.csv_path.setText(""))
        prow = QHBoxLayout()
        prow.addWidget(self.csv_path, 1)
        prow.addWidget(self.browse_button)
        prow.addWidget(self.clear_button)
        mf.addRow("Datei", prow)
        self.csv_row = self._int(vt.ROW_RANGE, spec.csv_row)
        self.csv_row.setToolTip("Diese Datenzeile (1 = erste Zeile nach der Kopfzeile) wird "
                                "beim nächsten Senden gelasert")
        mf.addRow("Nächste Zeile", self.csv_row)
        self.advance_row = QCheckBox("Nach jedem Senden nächste Zeile")
        self.advance_row.setChecked(spec.advance_row)
        mf.addRow("", self.advance_row)
        self.csv_info = QLabel()
        self.csv_info.setWordWrap(True)
        mf.addRow("", self.csv_info)
        self.table = QTableWidget(0, 0)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(140)
        self.table.cellClicked.connect(lambda r, _c: self.csv_row.setValue(r + 1))
        mf.addRow(self.table)
        lay.addWidget(merge)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.preview)
        self.show_values = QCheckBox("Nächste Werte auf der Arbeitsfläche anzeigen "
                                     "(Hinweis unter jedem variablen Text)")
        self.show_values.setChecked(show_values)
        lay.addWidget(self.show_values)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self.template.textChanged.connect(self._update)
        for w in (self.start, self.step, self.pad, self.current, self.csv_row):
            w.valueChanged.connect(self._update)
        self.per_copy.toggled.connect(self._update)
        self.enabled.toggled.connect(self._update)
        self.csv_path.textChanged.connect(self._load_table)
        self._load_table()

    @staticmethod
    def _int(rng, value):
        w = QSpinBox()
        w.setRange(*rng)
        w.setValue(int(value))
        return w

    def _browse(self) -> None:
        start = os.path.dirname(self.csv_path.text()) if self.csv_path.text() else ""
        path, _ = QFileDialog.getOpenFileName(self, "CSV-Datei wählen", start,
                                              "CSV (*.csv *.txt);;Alle Dateien (*)")
        if path:
            self.csv_path.setText(path)

    def _load_table(self) -> None:
        path = self.csv_path.text().strip()
        self._table = None
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        if not path:
            self.csv_info.setText("Ohne CSV-Datei: nur Zähler, Datum und Uhrzeit.")
            self._update()
            return
        try:
            t = vt.load_csv(path)
        except vt.VarTextError as exc:
            self.csv_info.setText(f"⚠ {exc}")
            self._update()
            return
        self._table = t
        self.csv_info.setText(f"{len(t.rows)} Datenzeilen · Spalten: "
                              + ", ".join("{" + h + "}" for h in t.header))
        self.table.setColumnCount(len(t.header))
        self.table.setHorizontalHeaderLabels(t.header)
        shown = t.rows[:PREVIEW_ROWS]
        self.table.setRowCount(len(shown))
        for r, values in enumerate(shown):
            for c in range(len(t.header)):
                self.table.setItem(r, c, QTableWidgetItem(values[c] if c < len(values) else ""))
        self._update()

    def spec(self) -> vt.VarTextSpec:
        return vt.VarTextSpec(series=self._series, start=self.start.value(),
                              step=self.step.value(), pad=self.pad.value(),
                              current=self.current.value(), per_copy=self.per_copy.isChecked(),
                              csv_path=self.csv_path.text().strip(),
                              csv_row=self.csv_row.value(),
                              advance_row=self.advance_row.isChecked()).normalized()

    def is_enabled(self) -> bool:
        return self.enabled.isChecked()

    def template_text(self) -> str | None:
        """The template if the user changed it, else ``None`` (keep each text)."""
        t = self.template.text()
        return t if t != self._initial_template else None

    def preview_texts(self) -> list[str]:
        s = self.spec()
        n = self.copies if s.per_copy else 1
        out = []
        for i in range(min(n, 3)):
            out.append(vt.evaluate(self.template.text(), value=s.current + i * s.step,
                                   pad=s.pad, table=self._table, row=s.csv_row + i))
        return out

    def _update(self) -> None:
        on = self.enabled.isChecked()
        for w in (self.template, self.start, self.step, self.pad, self.current, self.reset_button,
                  self.per_copy, self.csv_path, self.browse_button, self.clear_button,
                  self.csv_row, self.advance_row, self.table):
            w.setEnabled(on)
        if self._table is not None and 1 <= self.csv_row.value() <= self.table.rowCount():
            self.table.blockSignals(True)
            self.table.selectRow(self.csv_row.value() - 1)
            self.table.blockSignals(False)
        if not on:
            self.preview.setText("Aus: der Text wird wörtlich gelasert.")
            self.preview.setStyleSheet("")
            return
        try:
            texts = self.preview_texts()
        except vt.VarTextError as exc:
            self.preview.setText(f"⚠ {exc}")
            self.preview.setStyleSheet("color: #f36b73;")
            return
        more = " …" if (self.per_copy.isChecked() and self.copies > 3) else ""
        label = "Nächster Auftrag" + (f" ({self.copies} Kopien)" if self.copies > 1 else "")
        self.preview.setText(f"{label}: " + " | ".join(t.replace("\n", "⏎") for t in texts) + more)
        self.preview.setStyleSheet("")


__all__ = ["HELP", "MARKER", "UPLOAD_LABELS", "VarTextDialog", "VarTextTracker", "advance",
           "apply_vartext", "describe", "gcode_token", "mark_gcode", "series_members",
           "usage_token"]
