"""Qt side of the scanning offset: settings storage, table dialog, test pattern.

* :func:`load_table` / :func:`save_table` – app QSettings key
  ``job/scan_offset`` (JSON, see :class:`.scan_offset.ScanOffsetTable`);
  without an organisation name (tests) nothing is read or written.
* :class:`ScanOffsetDialog` – „Scan-Versatz…“: on/off, table speed → offset
  with add / remove / sort, live interpolation check, button „Testmuster…“.
* :class:`ScanTestDialog` – calibration job (rows = speeds, columns = trial
  offsets): „Senden“ uploads it to the Pi without starting, „Speichern…“
  writes the G-code file.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QSettings, Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from .scan_offset import ScanOffsetTable, ScanTestSpec, test_pattern_gcode

SETTINGS_KEY = "job/scan_offset"

HELP = ("Bei schneller, bidirektionaler Gravur brennt der Laser in Fahrtrichtung etwas zu spät – "
        "hin- und rücklaufende Linien liegen versetzt, senkrechte Kanten werden unscharf. "
        "Den gemessenen Versatz (Abstand der Kanten) je Geschwindigkeit eintragen; dazwischen "
        "wird interpoliert. Gilt für Bilder und Schraffur-Füllungen, nicht für Konturen.")


def default_settings() -> QSettings | None:
    """App QSettings, only when the app has an organisation (not in tests)."""
    if QCoreApplication.instance() is None or not QCoreApplication.organizationName():
        return None
    return QSettings()


def load_table(settings: QSettings | None) -> ScanOffsetTable | None:
    """Stored table or None (nothing stored / unreadable)."""
    if settings is None or not settings.contains(SETTINGS_KEY):
        return None
    try:
        return ScanOffsetTable.from_json(str(settings.value(SETTINGS_KEY)))
    except ValueError:
        return None


def save_table(settings: QSettings | None, table: ScanOffsetTable) -> None:
    if settings is not None:
        settings.setValue(SETTINGS_KEY, table.to_json())
        settings.sync()


def _dspin(lo, hi, value, step, decimals, suffix=""):
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(decimals)
    w.setSingleStep(step)
    w.setValue(value)
    if suffix:
        w.setSuffix(suffix)
    return w


def _parse(text: str) -> float:
    return float(str(text).strip().replace(",", ".").replace("−", "-"))


class ScanOffsetDialog(QDialog):
    """Edit the speed table; ``table()`` returns the validated result."""

    def __init__(self, table: ScanOffsetTable | None = None, parent=None, test_callback=None):
        super().__init__(parent)
        self.setWindowTitle("Scan-Versatz")
        self.setObjectName("scan_offset_dialog")
        t = table or ScanOffsetTable(enabled=True)
        lay = QVBoxLayout(self)
        info = QLabel(HELP)
        info.setWordWrap(True)
        lay.addWidget(info)
        self.enabled = QCheckBox("Scan-Versatz anwenden")
        self.enabled.setChecked(bool(t.enabled))
        lay.addWidget(self.enabled)
        self.grid = QTableWidget(0, 2)
        self.grid.setHorizontalHeaderLabels(["Geschwindigkeit (mm/min)", "Versatz (mm)"])
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectRows)
        for speed, off in t.entries:
            self._append(speed, off)
        self.grid.itemChanged.connect(lambda _i: self._update_check())
        lay.addWidget(self.grid)
        row = QHBoxLayout()
        self.add_btn = QPushButton("Zeile hinzufügen")
        self.add_btn.clicked.connect(self.add_row)
        self.remove_btn = QPushButton("Zeile entfernen")
        self.remove_btn.clicked.connect(self.remove_selected)
        self.test_btn = QPushButton("Testmuster…")
        self.test_btn.setToolTip("Kalibrier-Auftrag: je Geschwindigkeit eine Reihe Felder mit "
                                 "steigendem Versatz – das Feld mit geraden Kanten ablesen")
        self.test_btn.setEnabled(test_callback is not None)
        if test_callback is not None:
            self.test_btn.clicked.connect(lambda: test_callback(self))
        for b in (self.add_btn, self.remove_btn, self.test_btn):
            row.addWidget(b)
        lay.addLayout(row)
        check = QHBoxLayout()
        check.addWidget(QLabel("Prüfen bei"))
        self.probe = QLineEdit("3000")
        self.probe.setMaximumWidth(80)
        self.probe.textChanged.connect(lambda _t: self._update_check())
        check.addWidget(self.probe)
        check.addWidget(QLabel("mm/min:"))
        self.check_label = QLabel()
        self.check_label.setObjectName("scan_offset_check")
        check.addWidget(self.check_label, 1)
        lay.addLayout(check)
        self.error = QLabel()
        self.error.setStyleSheet("color: #d9534f")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.enabled.toggled.connect(lambda _on: self._update_check())
        self._update_check()

    def _append(self, speed: float, offset: float) -> None:
        r = self.grid.rowCount()
        self.grid.insertRow(r)
        for c, v in enumerate((f"{speed:g}", f"{offset:.3f}".rstrip("0").rstrip(".") or "0")):
            item = QTableWidgetItem(v)
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.grid.setItem(r, c, item)

    def add_row(self) -> None:
        speeds = []
        for r in range(self.grid.rowCount()):
            try:
                speeds.append(_parse(self.grid.item(r, 0).text()))
            except (AttributeError, ValueError):
                pass
        nxt = min(6000.0, (max(speeds) + 1000.0) if speeds else 1000.0)
        while nxt in speeds and nxt > 1:
            nxt -= 100.0
        self.grid.blockSignals(True)
        self._append(nxt, 0.0)
        self.grid.blockSignals(False)
        self._update_check()

    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.grid.selectedIndexes()}, reverse=True)
        if not rows and self.grid.rowCount():
            rows = [self.grid.rowCount() - 1]
        for r in rows:
            self.grid.removeRow(r)
        self._update_check()

    def set_entries(self, entries) -> None:
        self.grid.blockSignals(True)
        self.grid.setRowCount(0)
        for s, o in entries:
            self._append(s, o)
        self.grid.blockSignals(False)
        self._update_check()

    def table(self) -> ScanOffsetTable:
        """Validated table; ``ValueError`` (German) for bad cells."""
        entries = []
        for r in range(self.grid.rowCount()):
            cells = [self.grid.item(r, c) for c in (0, 1)]
            texts = [c.text().strip() if c is not None else "" for c in cells]
            if not any(texts):
                continue
            try:
                entries.append((_parse(texts[0]), _parse(texts[1])))
            except ValueError:
                raise ValueError(f"Scan-Versatz: Zeile {r + 1} ist keine Zahl") from None
        return ScanOffsetTable(self.enabled.isChecked(), entries).normalized()

    def _update_check(self) -> None:
        try:
            t = self.table()
        except ValueError as exc:
            self.error.setText(str(exc))
            self.check_label.setText("–")
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            return
        self.error.setText("")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)
        try:
            v = _parse(self.probe.text())
        except ValueError:
            self.check_label.setText("–")
            return
        if not t.enabled:
            self.check_label.setText("aus")
        elif not t.entries:
            self.check_label.setText("keine Einträge (0 mm)")
        else:
            off = t.offset_for(v)
            self.check_label.setText(f"Versatz {off:.3f} mm – je Linie {off / 2:.3f} mm "
                                     "zurück".replace(".", ","))

    def _accept(self) -> None:
        try:
            self.table()
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class ScanTestDialog(QDialog):
    """Parameters of the calibration job; ``send`` / ``save`` callbacks get the G-code."""

    def __init__(self, spec: ScanTestSpec | None = None, parent=None, send=None, save=None):
        super().__init__(parent)
        self.setWindowTitle("Scan-Versatz-Testmuster")
        self.setObjectName("scan_test_dialog")
        s = spec or ScanTestSpec()
        self._send, self._save = send, save
        self.result_gcode = ""
        f = QFormLayout(self)
        self.speeds = QLineEdit(" ".join(f"{v:g}" for v in s.speeds))
        self.speeds.setToolTip("Geschwindigkeiten in mm/min, durch Leerzeichen oder ; getrennt")
        self.off_min = _dspin(-2, 2, s.offset_min, 0.05, 2, " mm")
        self.off_max = _dspin(-2, 2, s.offset_max, 0.05, 2, " mm")
        self.off_step = _dspin(0.01, 1, s.offset_step, 0.01, 2, " mm")
        self.power = QSpinBox()
        self.power.setRange(1, 100)
        self.power.setValue(int(round(s.power)))
        self.power.setSuffix(" %")
        self.interval = _dspin(0.05, 2, s.line_interval_mm, 0.05, 2, " mm")
        self.patch_w = _dspin(2, 50, s.patch_w_mm, 1, 1, " mm")
        self.patch_h = _dspin(1, 50, s.patch_h_mm, 1, 1, " mm")
        self.x = _dspin(0, 360, s.x, 5, 1, " mm")
        self.y = _dspin(0, 340, s.y, 5, 1, " mm")
        self.labels = QCheckBox("Beschriftung (Versatz oben, Geschwindigkeit links)")
        self.labels.setChecked(s.labels)
        for label, w in (("Geschwindigkeiten", self.speeds), ("Versatz von", self.off_min),
                         ("Versatz bis", self.off_max), ("Schrittweite", self.off_step),
                         ("Leistung", self.power), ("Linienabstand", self.interval),
                         ("Feldbreite", self.patch_w), ("Feldhöhe", self.patch_h),
                         ("Position X", self.x), ("Position Y", self.y), ("", self.labels)):
            f.addRow(label, w)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("scan_test_info")
        f.addRow(self.info)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.send_btn = bb.addButton("Senden (ohne Start)", QDialogButtonBox.ActionRole)
        self.save_btn = bb.addButton("Speichern…", QDialogButtonBox.ActionRole)
        self.send_btn.setEnabled(send is not None)
        self.save_btn.setEnabled(save is not None)
        self.send_btn.clicked.connect(lambda: self._run(self._send))
        self.save_btn.clicked.connect(lambda: self._run(self._save))
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        for w in (self.off_min, self.off_max, self.off_step, self.interval, self.patch_w,
                  self.patch_h, self.x, self.y):
            w.valueChanged.connect(lambda _v: self._update())
        self.power.valueChanged.connect(lambda _v: self._update())
        self.speeds.textChanged.connect(lambda _t: self._update())
        self.labels.toggled.connect(lambda _on: self._update())
        self._update()

    def spec(self) -> ScanTestSpec:
        parts = [p for p in self.speeds.text().replace(";", " ").split() if p]
        try:
            speeds = [_parse(p) for p in parts]
        except ValueError:
            raise ValueError("Scan-Test: Geschwindigkeiten als Zahlen eingeben") from None
        return ScanTestSpec(speeds=speeds, offset_min=self.off_min.value(),
                            offset_max=self.off_max.value(), offset_step=self.off_step.value(),
                            power=float(self.power.value()),
                            line_interval_mm=self.interval.value(), patch_w_mm=self.patch_w.value(),
                            patch_h_mm=self.patch_h.value(), x=self.x.value(), y=self.y.value(),
                            labels=self.labels.isChecked())

    def _update(self) -> bool:
        try:
            spec = self.spec()
            spec.validate()
        except ValueError as exc:
            self.info.setText(str(exc))
            ok = False
        else:
            w, h = spec.size()
            offs = ", ".join(f"{o:.2f}" for o in spec.offsets()).replace(".", ",")
            self.info.setText(f"{len(spec.speeds)} Reihen × {len(spec.offsets())} Felder, "
                              f"{w:.0f} × {h:.0f} mm. Versatz je Spalte: {offs} mm. "
                              "Je Reihe das Feld mit den geradesten Kanten in die Tabelle "
                              "übernehmen.")
            ok = True
        self.send_btn.setEnabled(ok and self._send is not None)
        self.save_btn.setEnabled(ok and self._save is not None)
        return ok

    def gcode(self) -> str:
        return test_pattern_gcode(self.spec())

    def _run(self, fn) -> None:
        if fn is None:
            return
        try:
            g = self.gcode()
        except ValueError as exc:
            self.info.setText(str(exc))
            return
        self.result_gcode = g
        fn(g)
