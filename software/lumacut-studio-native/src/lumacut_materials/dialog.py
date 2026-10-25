"""Qt-Dialog „Materialbibliothek“ und Menü-Anbindung.

Material, Dicke, Operation und Laser wählen → berechnete Startwerte
(Leistung, Geschwindigkeit, Durchgänge, Fokus-Absenkung je Durchgang) auf die
aktive Ebene übernehmen (ein Undo-Schritt). Presets lassen sich speichern.
Für 3D-Relief erzeugt der Dialog G-Code aus einer Bild-Höhenkarte.

Eingebunden von ``main.py`` mit :func:`install_materials`; nutzt nur die
öffentlichen APIs von Editor (``document``, ``undo_stack``) und
Maschinenpanel (``send_gcode``).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from lumacut_canvas.commands import SetLayerAttrCommand

from .db import OPERATION_LABELS, MaterialDB, MaterialError, load_db
from .heightmap import HeightmapOptions, heightmap_from_image
from .presets import Preset, PresetStore, make_preset
from .relief import job_from_plan, relief_to_gcode
from .planner import plan_relief

STATUS_LABELS = {"ok": "", "caution": " ⚠", "engrave_only": " (nur Gravur)"}


def default_preset_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation) or str(Path.home())
    return Path(base) / "material_presets.json"


def apply_preset(editor, preset: Preset, layer_id: str | None = None) -> str:
    """Preset als *einen* Undo-Schritt auf eine Ebene anwenden. Gibt die Ebenen-ID zurück."""
    doc = editor.document
    lid = layer_id or doc.active_layer_id
    if lid is None:
        raise ValueError("Keine Ebene ausgewählt")
    stack = editor.undo_stack
    stack.beginMacro(f"Material: {preset.name}")
    try:
        for attr, value in preset.layer_values().items():
            if getattr(doc.layer(lid), attr) != value:
                stack.push(SetLayerAttrCommand(doc, lid, attr, value))
    finally:
        stack.endMacro()
    return lid


def _dspin(lo, hi, value, step, decimals=1, suffix=" mm"):
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(decimals)
    w.setSingleStep(step)
    w.setValue(value)
    w.setSuffix(suffix)
    return w


class MaterialLibraryDialog(QDialog):
    presetApplied = Signal(str)  # Ebenen-ID

    def __init__(self, editor, parent: QWidget | None = None, db: MaterialDB | None = None,
                 store: PresetStore | None = None, machine=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Materialbibliothek")
        self.setMinimumWidth(520)
        self.editor = editor
        self.db = db or load_db()
        self.store = store if store is not None else PresetStore(default_preset_path())
        self.machine = machine
        self.preset: Preset | None = None

        self.material = QComboBox()
        for m in self.db.compatible():
            self.material.addItem(m.name_de + STATUS_LABELS.get(m.status, ""), m.id)
        self.material.insertSeparator(self.material.count())
        for m in self.db.incompatible():
            self.material.addItem("✕ " + m.name_de, m.id)
        self.thickness = QComboBox()
        self.thickness.setEditable(True)
        self.operation = QComboBox()
        self.laser = QComboBox()
        for l in self.db.lasers:
            self.laser.addItem(l.name + (f" – {l.optical_power_w:g} W optisch" if l.primary else ""), l.id)
        self.relief_depth = _dspin(0.1, 10, 1.0, 0.1)
        self.relief_width = _dspin(5, 360, 80, 5)
        self.relief_x = _dspin(0, 360, 20, 5)
        self.relief_y = _dspin(0, 340, 20, 5)
        self.saved = QComboBox()
        self.saved.addItem("—", None)
        self._reload_saved()

        form = QFormLayout()
        form.addRow("Material", self.material)
        form.addRow("Dicke (mm)", self.thickness)
        form.addRow("Operation", self.operation)
        form.addRow("Laser", self.laser)
        self.relief_rows = [("Relieftiefe", self.relief_depth), ("Breite", self.relief_width),
                            ("Position X", self.relief_x), ("Position Y", self.relief_y)]
        for label, w in self.relief_rows:
            form.addRow(label, w)
        form.addRow("Eigene Presets", self.saved)

        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.RichText)
        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        self.warnings.setStyleSheet("color: #f5b14c;")
        self.disclaimer = QLabel(self.db.disclaimer)
        self.disclaimer.setWordWrap(True)
        self.disclaimer.setStyleSheet("color: #93a1b5; font-size: 11px;")

        self.apply_btn = QPushButton("Auf aktive Ebene anwenden")
        self.apply_btn.setObjectName("primary")
        self.save_btn = QPushButton("Als Preset speichern…")
        self.relief_btn = QPushButton("Relief aus Bild…")
        close_btn = QPushButton("Schließen")
        buttons = QHBoxLayout()
        for b in (self.apply_btn, self.save_btn, self.relief_btn, close_btn):
            buttons.addWidget(b)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.result)
        lay.addWidget(self.warnings)
        lay.addWidget(self.disclaimer)
        lay.addLayout(buttons)

        self.material.currentIndexChanged.connect(self._material_changed)
        self.thickness.currentTextChanged.connect(lambda _t: self.recompute())
        self.operation.currentIndexChanged.connect(lambda _i: self._op_changed())
        self.laser.currentIndexChanged.connect(lambda _i: self.recompute())
        self.relief_depth.valueChanged.connect(lambda _v: self.recompute())
        self.saved.activated.connect(self._saved_chosen)
        self.apply_btn.clicked.connect(lambda: self.apply())
        self.save_btn.clicked.connect(lambda: self.save_preset())
        self.relief_btn.clicked.connect(lambda: self.relief_from_image())
        close_btn.clicked.connect(self.accept)
        self._material_changed()

    # --- Auswahl ------------------------------------------------------------
    def select(self, material_id: str, thickness: float | None = None, op: str | None = None,
               laser_id: str | None = None) -> None:
        """Programmatische Auswahl (Tests, Presets)."""
        idx = self.material.findData(material_id)
        if idx < 0:
            raise MaterialError(f"Unbekanntes Material: {material_id}")
        self.material.setCurrentIndex(idx)
        if laser_id:
            self.laser.setCurrentIndex(self.laser.findData(laser_id))
        if thickness is not None:
            self.thickness.setCurrentText(f"{thickness:g}")
        if op:
            self.operation.setCurrentIndex(self.operation.findData(op))
        self.recompute()

    def _material_changed(self) -> None:
        if self.material.currentData() is None:  # Trennlinie
            self.material.setCurrentIndex(0)
            return
        m = self.db.material(self.material.currentData())
        self.thickness.blockSignals(True)
        self.thickness.clear()
        self.thickness.addItems([f"{t:g}" for t in m.thicknesses_mm])
        if "3" in [self.thickness.itemText(i) for i in range(self.thickness.count())]:
            self.thickness.setCurrentText("3")
        self.thickness.blockSignals(False)
        self.operation.blockSignals(True)
        self.operation.clear()
        for op in m.operations():
            self.operation.addItem(OPERATION_LABELS[op], op)
        self.operation.blockSignals(False)
        self._op_changed()

    def _op_changed(self) -> None:
        relief = self.operation.currentData() == "relief"
        for _label, w in self.relief_rows:
            w.setEnabled(relief)
        self.relief_btn.setEnabled(relief)
        self.recompute()

    def _thickness(self) -> float | None:
        try:
            return float(self.thickness.currentText().replace(",", "."))
        except ValueError:
            return None

    def recompute(self) -> Preset | None:
        mid = self.material.currentData()
        m = self.db.material(mid)
        op = self.operation.currentData()
        self.preset = None
        if not m.compatible or op is None:
            self.result.setText(f"<b>{m.name_de}</b>: nicht lasern.")
            self.warnings.setText("\n".join(self.db.check(mid)))
            self._enable(False)
            return None
        try:
            self.preset = make_preset(self.db, mid, op, self._thickness(), self.laser.currentData(),
                                      depth_mm=self.relief_depth.value() if op == "relief" else None)
        except (MaterialError, ValueError) as exc:
            self.result.setText(f"<b>Nicht möglich:</b> {exc}")
            self.warnings.setText("")
            self._enable(False)
            return None
        p = self.preset
        offs = ""
        if p.z_step_mm:
            offs = ", ".join(f"{-i * p.z_step_mm:+.2f}" for i in range(min(p.passes, 8)))
            offs = f"<br>Fokus je Durchgang (mm): {offs}{' …' if p.passes > 8 else ''}"
        start = (f"<br>Fokus-Start: {p.focus_start_mm:+g} mm (am Pi einstellen)"
                 if p.focus_start_mm else "")
        self.result.setText(f"<b>{p.name}</b><br>{p.summary()}{offs}{start}")
        self.warnings.setText("\n".join(p.warnings))
        self._enable(True)
        return p

    def _enable(self, ok: bool) -> None:
        self.apply_btn.setEnabled(ok and self.editor is not None)
        self.save_btn.setEnabled(ok)

    # --- Aktionen -----------------------------------------------------------
    def apply(self, preset: Preset | None = None) -> str | None:
        p = preset or self.preset
        if p is None or self.editor is None:
            return None
        lid = apply_preset(self.editor, p)
        self.presetApplied.emit(lid)
        return lid

    def save_preset(self, name: str | None = None) -> Preset | None:
        if self.preset is None:
            return None
        if name is None:
            name, ok = QInputDialog.getText(self, "Preset speichern", "Name:", text=self.preset.name)
            if not ok or not name.strip():
                return None
        p = Preset.from_dict({**self.preset.to_dict(), "name": name.strip()})
        self.store.put(p)
        self.store.save()
        self._reload_saved()
        return p

    def _reload_saved(self) -> None:
        self.saved.blockSignals(True)
        self.saved.clear()
        self.saved.addItem("—", None)
        for n in self.store.names():
            self.saved.addItem(n, n)
        self.saved.blockSignals(False)

    def _saved_chosen(self, index: int) -> None:
        name = self.saved.itemData(index)
        if name:
            p = self.store.get(name)
            self.preset = p
            self.result.setText(f"<b>{p.name}</b> (gespeichert)<br>{p.summary()}")
            self.warnings.setText("\n".join(p.warnings))
            self._enable(True)

    def relief_gcode(self, image_path: str | Path) -> tuple[str, object]:
        """Relief-G-Code für das gewählte Material aus einer Bilddatei."""
        mid = self.material.currentData()
        plan = plan_relief(self.db, mid, self.relief_depth.value(), self.laser.currentData())
        hm = heightmap_from_image(image_path, HeightmapOptions(
            width_mm=self.relief_width.value(), line_interval_mm=plan.line_interval_mm,
            depth_mm=self.relief_depth.value(), blur_mm=plan.line_interval_mm * 1.5))
        return relief_to_gcode(job_from_plan(plan, hm, self.relief_x.value(), self.relief_y.value()))

    def relief_from_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Höhenkarte wählen (weiß = hoch)", "",
                                              "Bilder (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if not path:
            return
        try:
            code, stats = self.relief_gcode(path)
        except (ValueError, MaterialError) as exc:
            QMessageBox.warning(self, "Relief", str(exc))
            return
        info = (f"{stats.passes} Durchgänge, {stats.lines} Zeilen, "
                f"ca. {stats.est_seconds / 60:.0f} min (Schätzung)")
        if self.machine is not None and QMessageBox.question(
                self, "Relief", f"{info}\n\nAn die Maschine senden (ohne Start)?") == QMessageBox.Yes:
            self.machine.send_gcode("lumacut-relief.gcode", code, start=False)
            return
        out, _ = QFileDialog.getSaveFileName(self, "Relief-G-Code speichern", "relief.gcode",
                                             "G-Code (*.gcode *.nc)")
        if out:
            Path(out).write_text(code, encoding="ascii")


class MaterialTools(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        menu = window.menuBar().addMenu("&Material")
        self.menu = menu
        self.action = QAction("Materialbibliothek …", window)
        self.action.setObjectName("materials_library_action")
        self.action.setShortcut("Ctrl+Shift+M")
        self.action.setToolTip("Startwerte für Material, Dicke und Operation auf die aktive Ebene anwenden")
        self.action.triggered.connect(lambda _=False: self.open())
        menu.addAction(self.action)
        self.dialog: MaterialLibraryDialog | None = None

    def open(self, modal: bool = False) -> MaterialLibraryDialog:
        if self.dialog is None:
            self.dialog = MaterialLibraryDialog(getattr(self.window, "canvas", None), self.window,
                                                machine=getattr(self.window, "machine_panel", None))
            self.dialog.presetApplied.connect(
                lambda _lid: self.window.statusBar().showMessage("Material-Startwerte übernommen", 5000))
        if modal:
            self.dialog.exec()
        else:
            self.dialog.show()
            self.dialog.raise_()
        return self.dialog


def install_materials(window) -> MaterialTools:
    """Menü „Material → Materialbibliothek …“ am Hauptfenster anlegen."""
    tools = MaterialTools(window)
    window.material_tools = tools
    return tools
