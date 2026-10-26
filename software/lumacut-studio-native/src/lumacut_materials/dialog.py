"""Qt-Dialog „Materialbibliothek“ und Menü-Anbindung.

Material, Dicke, Operation und Laser wählen → berechnete Startwerte
(Leistung, Geschwindigkeit, Durchgänge, Fokus-Absenkung je Durchgang) auf die
aktive Ebene übernehmen (ein Undo-Schritt). „Ebene verknüpfen“ lässt die
Ebene der Bibliothek folgen: Dicke ändern plant die Werte neu (:mod:`.link`).
Presets lassen sich speichern – auch aus einer Zelle des Materialtest-Rasters
(:mod:`.testgrid`). Für 3D-Relief erzeugt der Dialog G-Code aus einer
Bild-Höhenkarte. Das Feld „Material“ im Design-Bereich des Hauptfensters wird
von :class:`MaterialQuickPanel` belegt.

Eingebunden von ``main.py`` mit :func:`install_materials`; nutzt nur die
öffentlichen APIs von Editor (``document``, ``undo_stack``) und
Maschinenpanel (``send_gcode``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QStandardPaths, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from lumacut_canvas.commands import SetLayerAttrsCommand

from .db import OPERATION_LABELS, MaterialDB, MaterialError, load_db
from .heightmap import HeightmapOptions, heightmap_from_image
from .link import install_link_hook, link_status, parse_ref, plan_layer_attrs, preset_layer_attrs
from .depth3d import apply_to_image_settings, depth3d_image_settings
from .process import process_defaults
from .presets import Preset, PresetStore, make_preset
from .relief import job_from_plan, relief_to_gcode
from .planner import plan_relief
from .testgrid import is_test_cell, preset_from_test_cell, find_test_cells

STATUS_LABELS = {"ok": "", "caution": " ⚠", "engrave_only": " (nur Gravur)"}


def default_preset_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation) or str(Path.home())
    return Path(base) / "material_presets.json"


def apply_preset(editor, preset: Preset, layer_id: str | None = None, link: bool = False,
                 db: MaterialDB | None = None) -> str:
    """Preset als *einen* Undo-Schritt auf eine Ebene anwenden. Gibt die Ebenen-ID zurück.

    Setzt Leistung/Geschwindigkeit/Durchgänge/Fokus-Absenkung sowie Material,
    Dicke und Tiefe je Durchgang (Bibliotheksbezug); ``link`` verknüpft.
    """
    doc = editor.document
    lid = layer_id or doc.active_layer_id
    if lid is None:
        raise ValueError("Keine Ebene ausgewählt")
    db = db or load_db()
    attrs = preset_layer_attrs(db, preset, link=link, layer=doc.layer(lid))
    editor.undo_stack.push(SetLayerAttrsCommand(doc, lid, attrs, f"Material: {preset.name}"))
    return lid


def apply_depth3d(editor: Any, fields: dict, shape_ids: list[str] | None = None) -> list[str]:
    """``depth3d``-Felder auf Bildobjekte (Standard: Auswahl) – ein Undo-Schritt."""
    from lumacut_canvas.commands import SetImageSettingsCommand

    doc = editor.document
    ids = list(shape_ids if shape_ids is not None else getattr(editor, "selection", []))
    ids = [i for i in ids if doc.has_shape(i) and doc.shape(i).image is not None]
    if not ids:
        return []
    stack = editor.undo_stack
    stack.beginMacro("3D-Tiefe aus Materialbibliothek")
    for sid in ids:
        old = doc.shape(sid).image.settings
        stack.push(SetImageSettingsCommand(doc, sid, old, apply_to_image_settings(old, fields)))
    stack.endMacro()
    return ids


def apply_library(editor, db: MaterialDB, material_id: str, op: str, thickness_mm: float | None,
                  laser_id: str | None = None, depth_mm: float | None = None, link: bool = True,
                  layer_id: str | None = None) -> str:
    """Bibliothekswerte zuweisen/verknüpfen (ein Undo-Schritt). Gibt die Ebenen-ID zurück."""
    doc = editor.document
    lid = layer_id or doc.active_layer_id
    if lid is None:
        raise ValueError("Keine Ebene ausgewählt")
    attrs = plan_layer_attrs(db, material_id, op, thickness_mm, laser_id, depth_mm, link=link,
                             layer=doc.layer(lid))
    verb = "verknüpfen" if link else "zuweisen"
    editor.undo_stack.push(SetLayerAttrsCommand(doc, lid, attrs, f"Material {verb}: {attrs['material']}"))
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
    presetsChanged = Signal()  # eigene Presets gespeichert

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
        self.preset_from_library = False
        install_link_hook(self.db)

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
        self.link = QCheckBox("Ebene verknüpfen (Dicke ändern → Werte neu planen)")
        self.link.setChecked(True)
        self.link.setToolTip("Aus: Werte nur einmal zuweisen. An: Die Ebene folgt der Bibliothek, "
                             "bis Leistung/Geschwindigkeit/Durchgänge von Hand geändert werden.")
        form.addRow("", self.link)

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
        self.test_btn = QPushButton("Testzelle als Preset…")
        self.test_btn.setToolTip("Beste Zelle des Materialtest-Rasters (Ebene „Test P…% F…“) als "
                                 "eigenes Preset für die gewählte Auswahl speichern")
        self.relief_btn = QPushButton("Relief aus Bild…")
        self.depth3d_btn = QPushButton("Auf Bild (3D-Tiefe)")
        self.depth3d_btn.setObjectName("materials_depth3d_apply")
        self.depth3d_btn.setToolTip("Reliefplan als 3D-Tiefe-Einstellung auf die gewählten Bilder "
                                    "übernehmen (Schichten = Tiefenstufen)")
        close_btn = QPushButton("Schließen")
        buttons = QHBoxLayout()
        for b in (self.apply_btn, self.save_btn, self.test_btn, self.relief_btn, self.depth3d_btn,
                  close_btn):
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
        self.test_btn.clicked.connect(lambda: self.save_test_cell())
        self.relief_btn.clicked.connect(lambda: self.relief_from_image())
        self.depth3d_btn.clicked.connect(lambda: self.apply_depth3d())
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
        self.preset_from_library = False
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
        proc = ""
        if op == "cut" and self._thickness():
            try:
                d = process_defaults(self.db, mid, self._thickness(), self.laser.currentData())
            except (MaterialError, ValueError):
                d = None
            if d is not None:
                proc = f"<br>Bahn-Startwerte: {d.summary()} (Schätzung)"
        self.preset_from_library = True
        self.result.setText(f"<b>{p.name}</b><br>{p.summary()}{offs}{start}{proc}")
        self.warnings.setText("\n".join(p.warnings))
        self._enable(True)
        return p

    def _enable(self, ok: bool) -> None:
        self.apply_btn.setEnabled(ok and self.editor is not None)
        self.save_btn.setEnabled(ok)
        self.test_btn.setEnabled(ok and self.editor is not None)
        self.depth3d_btn.setEnabled(ok and self.editor is not None
                                    and self.operation.currentData() == "relief")

    # --- Aktionen -----------------------------------------------------------
    def apply(self, preset: Preset | None = None) -> str | None:
        p = preset or self.preset
        if p is None or self.editor is None:
            return None
        if preset is None and self.preset_from_library:
            op = self.operation.currentData()
            lid = apply_library(self.editor, self.db, p.material_id, op, self._thickness(),
                                p.laser_id, self.relief_depth.value() if op == "relief" else None,
                                link=self.link.isChecked())
        else:
            lid = apply_preset(self.editor, p, link=False, db=self.db)
        self.presetApplied.emit(lid)
        return lid

    def apply_depth3d(self, shape_ids: list[str] | None = None) -> list[str]:
        """Reliefplan als ``depth3d``-Bildeinstellung (ein Undo-Schritt)."""
        if self.editor is None or self.operation.currentData() != "relief":
            return []
        try:
            fields = depth3d_image_settings(self.db, self.material.currentData(),
                                            self.relief_depth.value(), self.laser.currentData())
        except (MaterialError, ValueError) as exc:
            QMessageBox.warning(self, "3D-Tiefe", str(exc))
            return []
        return apply_depth3d(self.editor, fields, shape_ids)

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
        self.presetsChanged.emit()
        return p

    def test_cell_layer(self):
        """Aktive Ebene, wenn sie eine Testzelle ist, sonst ``None``."""
        if self.editor is None:
            return None
        layer = self.editor.document.active_layer
        return layer if layer is not None and is_test_cell(layer) else None

    def save_test_cell(self, name: str | None = None, layer=None) -> Preset | None:
        """Testzelle (Standard: aktive Ebene) als eigenes Preset speichern.

        Material/Dicke/Operation/Laser kommen aus der Dialog-Auswahl.
        """
        if self.editor is None:
            return None
        layer = layer or self.test_cell_layer()
        if layer is None:
            cells = find_test_cells(self.editor.document)
            if not cells:
                QMessageBox.information(self, "Materialtest",
                                        "Kein Materialtest-Raster im Dokument (Auftrag → Materialtest).")
                return None
            if name is not None:  # programmatisch ohne Auswahl
                return None
            label, ok = QInputDialog.getItem(self, "Testzelle wählen", "Beste Zelle:",
                                             [c.name for c in cells], 0, False)
            if not ok:
                return None
            layer = next(c for c in cells if c.name == label)
        op = self.operation.currentData()
        try:
            p = preset_from_test_cell(self.db, layer, self.material.currentData(), op,
                                      self._thickness(), self.laser.currentData(),
                                      depth_mm=self.relief_depth.value() if op == "relief" else None)
        except (MaterialError, ValueError) as exc:
            QMessageBox.warning(self, "Materialtest", str(exc))
            return None
        if name is None:
            name, ok = QInputDialog.getText(self, "Testzelle als Preset", "Name:", text=p.name)
            if not ok or not name.strip():
                return None
        p = Preset.from_dict({**p.to_dict(), "name": name.strip()})
        self.store.put(p)
        self.store.save()
        self._reload_saved()
        self.saved.setCurrentIndex(self.saved.findData(p.name))
        self.preset = p
        self.preset_from_library = False
        self.result.setText(f"<b>{p.name}</b> (aus Materialtest)<br>{p.summary()}")
        self.presetsChanged.emit()
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
            self.preset_from_library = False
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


class MaterialQuickPanel(QObject):
    """Belegt das Feld „Material“ im Design-Bereich des Hauptfensters.

    Material, Dicke und Operation wählen → „Auf Ebene“ verknüpft (oder weist
    zu) die aktive Ebene in einem Undo-Schritt. Zeigt den Bibliotheksbezug der
    aktiven Ebene an.
    """

    def __init__(self, window, combo: QComboBox, form: QFormLayout, db: MaterialDB) -> None:
        super().__init__(window)
        self.window = window
        self.db = db
        self.combo = combo
        combo.setObjectName("design_material_combo")
        combo.addItem("—", None)
        for m in db.compatible():
            combo.addItem(m.name_de + STATUS_LABELS.get(m.status, ""), m.id)
        self.thickness = _dspin(0.1, 50, 3.0, 0.5)
        self.thickness.setObjectName("design_material_thickness")
        self.operation = QComboBox()
        self.operation.setObjectName("design_material_operation")
        self.link = QCheckBox("verknüpfen")
        self.link.setChecked(True)
        self.link.setToolTip("Ebene folgt der Bibliothek: Dicke ändern plant Leistung/"
                             "Geschwindigkeit/Durchgänge neu (ein Undo-Schritt)")
        self.apply_btn = QPushButton("Auf aktive Ebene")
        self.apply_btn.setObjectName("design_material_apply")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #93a1b5; font-size: 11px;")
        row = QHBoxLayout()
        row.addWidget(self.link)
        row.addWidget(self.apply_btn, 1)
        form.addRow("Dicke", self.thickness)
        form.addRow("Operation", self.operation)
        form.addRow("", row)
        form.addRow("", self.status)
        combo.currentIndexChanged.connect(lambda _i: self._material_changed())
        self.apply_btn.clicked.connect(lambda: self.apply())
        editor = self.editor
        if editor is not None and hasattr(editor, "documentChanged"):
            editor.documentChanged.connect(self.sync)
        self._material_changed()
        self.sync()

    @property
    def editor(self):
        return getattr(self.window, "canvas", None)

    def _material_changed(self) -> None:
        mid = self.combo.currentData()
        self.operation.clear()
        if mid is not None:
            for op in self.db.material(mid).operations():
                self.operation.addItem(OPERATION_LABELS[op], op)
        self.apply_btn.setEnabled(mid is not None and self.editor is not None)

    def apply(self) -> str | None:
        mid, op = self.combo.currentData(), self.operation.currentData()
        if mid is None or op is None or self.editor is None:
            return None
        try:
            lid = apply_library(self.editor, self.db, mid, op, self.thickness.value(),
                                link=self.link.isChecked())
        except (MaterialError, ValueError) as exc:
            self.status.setText(f"Nicht möglich: {exc}")
            return None
        self.sync()
        return lid

    def sync(self) -> None:
        """Anzeige an die aktive Ebene anpassen (Bezug, Dicke)."""
        editor = self.editor
        layer = editor.document.active_layer if editor is not None else None
        if layer is None:
            self.status.setText("")
            return
        self.status.setText(link_status(layer) and f"Ebene „{layer.name}“: {link_status(layer)}")
        parsed = parse_ref(getattr(layer, "material_ref", ""))
        if parsed is None:
            return
        for w in (self.combo, self.thickness, self.operation):
            w.blockSignals(True)
        try:
            idx = self.combo.findData(parsed[0])
            if idx >= 0 and idx != self.combo.currentIndex():
                self.combo.setCurrentIndex(idx)
                self._material_changed()
            oi = self.operation.findData(parsed[1])
            if oi >= 0:
                self.operation.setCurrentIndex(oi)
            if layer.thickness_mm:
                self.thickness.setValue(layer.thickness_mm)
        finally:
            for w in (self.combo, self.thickness, self.operation):
                w.blockSignals(False)


def _design_material_slot(window) -> tuple[QComboBox, QFormLayout] | None:
    """Leere „Material“-Combobox im Design-Bereich des Hauptfensters finden."""
    for box in window.findChildren(QGroupBox):
        form = box.layout()
        if box.title() != "Design" or not isinstance(form, QFormLayout):
            continue
        for row in range(form.rowCount()):
            label = form.itemAt(row, QFormLayout.LabelRole)
            field = form.itemAt(row, QFormLayout.FieldRole)
            lw = label.widget() if label else None
            fw = field.widget() if field else None
            if isinstance(lw, QLabel) and lw.text() == "Material" and isinstance(fw, QComboBox) \
                    and fw.count() == 0:
                return fw, form
    return None


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
        self.test_action = QAction("Testzelle als Preset speichern …", window)
        self.test_action.setObjectName("materials_test_cell_action")
        self.test_action.setToolTip("Beste Zelle des Materialtest-Rasters (aktive Ebene) als eigenes "
                                    "Preset für Material/Dicke/Operation speichern")
        self.test_action.triggered.connect(lambda _=False: self.save_test_cell())
        menu.addAction(self.test_action)
        self.dialog: MaterialLibraryDialog | None = None
        self.db = load_db()
        install_link_hook(self.db)
        slot = _design_material_slot(window)
        self.quick = MaterialQuickPanel(window, *slot, self.db) if slot else None

    def open(self, modal: bool = False) -> MaterialLibraryDialog:
        if self.dialog is None:
            self.dialog = MaterialLibraryDialog(getattr(self.window, "canvas", None), self.window,
                                                db=self.db,
                                                machine=getattr(self.window, "machine_panel", None))
            self.dialog.presetsChanged.connect(self._presets_changed)
            self.dialog.presetApplied.connect(
                lambda _lid: self.window.statusBar().showMessage("Material-Startwerte übernommen", 5000))
        if modal:
            self.dialog.exec()
        else:
            self.dialog.show()
            self.dialog.raise_()
        return self.dialog


    def _presets_changed(self) -> None:
        panel = getattr(self.window, "layers_panel", None)
        if panel is not None and hasattr(panel, "reload_presets"):
            panel.reload_presets()

    def save_test_cell(self) -> Preset | None:
        """Dialog öffnen und die aktive Testzelle (oder eine gewählte) speichern."""
        dlg = self.open()
        return dlg.save_test_cell()


def install_materials(window) -> MaterialTools:
    """Menü „Material“ anlegen, Verknüpfungs-Hook registrieren und das
    „Material“-Feld im Design-Bereich belegen."""
    tools = MaterialTools(window)
    window.material_tools = tools
    return tools
