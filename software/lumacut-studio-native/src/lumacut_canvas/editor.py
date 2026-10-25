"""CanvasEditor: das einbettbare Editor-Widget (Werkzeuge, Lineale, Canvas,
Eigenschaftsleiste) inklusive Undo-Stack und Dateiaktionen.

Schnittstelle für die Hauptanwendung und andere Module::

    editor = CanvasEditor()
    editor.document            # model.Document (Qt-frei, Ebenen + Objekte)
    editor.undo_stack          # QUndoStack
    editor.documentChanged     # Signal() nach jeder Modelländerung
    editor.selectionChanged    # Signal(list[str])
    editor.cursorMoved         # Signal(float, float) in Arbeitsflächen-mm
    editor.statusMessage       # Signal(str) für die Statusleiste
    editor.set_backdrop(img)   # Kamerascan als Hintergrund (Scan-Modul)
    export.job_layers(editor.document)  # Laserparameter + Polylinien in Maschinen-mm
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QImage, QKeySequence, QUndoStack
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QToolBar, QToolButton, QVBoxLayout,
                               QWidget)

from . import icons, theme
from .canvas_view import CanvasScene, CanvasView, Ruler
from .commands import (AddShapesCommand, DeleteShapesCommand, SetGeometryCommand,
                       SetShapeLayerCommand, SetTextCommand)
from .document_io import FILE_SUFFIX, load_into, save_document
from .export import export_png, export_svg
from .model import Document, Geometry, Shape
from .tools import TOOL_LABELS, TOOL_SHORTCUTS, Tool, ToolController
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, Rect, clamp_offset

PASTE_OFFSET_MM = 5.0


def _mm_spin(minimum: float, maximum: float) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(minimum, maximum)
    s.setDecimals(2)
    s.setSingleStep(0.5)
    s.setSuffix(" mm")
    s.setKeyboardTracking(False)  # erst bei Enter/Fokuswechsel übernehmen
    s.setAlignment(Qt.AlignRight)
    s.setFixedWidth(104)
    return s


class PropertyBar(QWidget):
    """Kontextleiste über dem Canvas: Position/Größe in mm, Ebene, Text."""

    def __init__(self, editor: "CanvasEditor") -> None:
        super().__init__()
        self.setObjectName("PropertyBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.ed = editor
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(4)
        self.title = QLabel("Keine Auswahl")
        self.title.setObjectName("PropTitle")
        self.title.setMinimumWidth(120)
        lay.addWidget(self.title)
        self.x = _mm_spin(-1000, 1000)
        self.y = _mm_spin(-1000, 1000)
        self.w = _mm_spin(0, WORK_WIDTH_MM)
        self.h = _mm_spin(0, WORK_HEIGHT_MM)
        for label, spin, tip in (("X", self.x, "Linke Kante"), ("Y", self.y, "Obere Kante"),
                                 ("B", self.w, "Breite"), ("H", self.h, "Höhe")):
            lab = QLabel(label)
            lab.setToolTip(tip)
            spin.setToolTip(tip)
            lay.addWidget(lab)
            lay.addWidget(spin)
            spin.valueChanged.connect(self._geometry_edited)
        self.ratio = QToolButton()
        self.ratio.setCheckable(True)
        self.ratio.setChecked(True)
        self.ratio.setIcon(icons.icon("link"))
        self.ratio.setToolTip("Seitenverhältnis beibehalten")
        lay.addWidget(self.ratio)
        lay.addSpacing(12)
        lay.addWidget(QLabel("Ebene"))
        self.layer = QComboBox()
        self.layer.setMinimumWidth(150)
        self.layer.activated.connect(self._layer_chosen)
        lay.addWidget(self.layer)
        self.text_label = QLabel("Text")
        self.text = QLineEdit()
        self.text.setMinimumWidth(140)
        self.text.editingFinished.connect(self._text_edited)
        lay.addWidget(self.text_label)
        lay.addWidget(self.text)
        lay.addStretch()
        self._updating = False
        self.refresh()

    def _spins(self) -> tuple[QDoubleSpinBox, ...]:
        return (self.x, self.y, self.w, self.h)

    def refresh(self) -> None:
        ed = self.ed
        doc = ed.document
        sel = [i for i in ed.selection if doc.has_shape(i)]
        self._updating = True
        self.layer.clear()
        for l in doc.layers:
            self.layer.addItem(icons_swatch(l.color), l.name, l.id)
        b = doc.selection_bounds(sel) if sel else None
        for s in self._spins():
            s.setEnabled(b is not None)
        self.layer.setEnabled(b is not None)
        if b is None:
            self.title.setText("Keine Auswahl")
            for s in self._spins():
                s.setValue(0)
            self.layer.setCurrentIndex(-1)
        else:
            kinds = {doc.shape(i).kind for i in sel}
            names = {"rect": "Rechteck", "ellipse": "Ellipse", "line": "Linie", "text": "Text"}
            self.title.setText(names[kinds.pop()] if len(sel) == 1 else f"{len(sel)} Objekte")
            self.x.setValue(b.x)
            self.y.setValue(b.y)
            self.w.setValue(b.w)
            self.h.setValue(b.h)
            layers = {doc.shape(i).layer_id for i in sel}
            self.layer.setCurrentIndex(self.layer.findData(layers.pop()) if len(layers) == 1 else -1)
        single_text = len(sel) == 1 and doc.shape(sel[0]).kind == "text"
        self.text_label.setVisible(single_text)
        self.text.setVisible(single_text)
        if single_text and not self.text.hasFocus():
            self.text.setText(doc.shape(sel[0]).text)
        self._updating = False

    def _geometry_edited(self) -> None:
        if self._updating:
            return
        ed = self.ed
        doc = ed.document
        sel = [i for i in ed.selection if doc.has_shape(i)]
        ob = doc.selection_bounds(sel)
        if not sel or ob is None:
            return
        w, h = self.w.value(), self.h.value()
        sender = self.sender()
        if self.ratio.isChecked() and ob.w > 0 and ob.h > 0:
            if sender is self.w:
                h = ob.h * w / ob.w
            elif sender is self.h:
                w = ob.w * h / ob.h
        if ob.w == 0:
            w = 0.0
        if ob.h == 0:
            h = 0.0
        nb = Rect(self.x.value(), self.y.value(), w, h)
        old = {i: Geometry(*doc.shape(i).geom.as_tuple()) for i in sel}
        new = {i: g.mapped(ob, nb) for i, g in old.items()}
        ed.undo_stack.push(SetGeometryCommand(doc, old, new, "Maße ändern"))

    def _layer_chosen(self, index: int) -> None:
        lid = self.layer.itemData(index)
        sel = [i for i in self.ed.selection if self.ed.document.has_shape(i)]
        if lid and sel:
            self.ed.undo_stack.push(SetShapeLayerCommand(self.ed.document, sel, lid))

    def _text_edited(self) -> None:
        sel = self.ed.selection
        doc = self.ed.document
        if len(sel) == 1 and doc.has_shape(sel[0]) and doc.shape(sel[0]).kind == "text":
            t = self.text.text()
            if t.strip() and t != doc.shape(sel[0]).text:
                self.ed.undo_stack.push(SetTextCommand(doc, sel[0], t))


def icons_swatch(color: str):
    """Kleines Farbquadrat als Icon (Ebenenfarbe in Auswahllisten)."""
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
    pm = QPixmap(14, 14)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(QColor(theme.BORDER))
    p.drawRoundedRect(1, 1, 12, 12, 3, 3)
    p.end()
    return QIcon(pm)


class CanvasEditor(QWidget):
    documentChanged = Signal()  # noqa: N815
    selectionChanged = Signal(list)  # noqa: N815
    cursorMoved = Signal(float, float)  # noqa: N815
    statusMessage = Signal(str)  # noqa: N815
    fileChanged = Signal(str)  # noqa: N815

    def __init__(self, document: Document | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CanvasEditor")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(theme.CANVAS_QSS)
        self.document = document or Document()
        self.undo_stack = QUndoStack(self)
        self.selection: list[str] = []
        self.snap_enabled = True
        self.snap_step_mm = 1.0
        self.text_font_family = "Segoe UI"
        self.file_path: Path | None = None
        self._clipboard: list[Shape] = []
        self._paste_count = 0

        self.scene = CanvasScene(self.document)
        self.view = CanvasView(self.scene)
        self.tools = ToolController(self)
        self.view.tool_handler = self.tools
        self.view.cursorMoved.connect(self.cursorMoved)
        self.view.viewChanged.connect(self._emit_zoom)

        self.actions_by_name: dict[str, QAction] = {}
        self._build_actions()
        self.property_bar = PropertyBar(self)
        self._build_layout()

        self.document.add_listener(self._on_document_changed)
        self.undo_stack.cleanChanged.connect(self._clean_changed)
        self.set_tool(Tool.SELECT)

    # --- Aufbau -----------------------------------------------------------
    def _act(self, name: str, text: str, slot, shortcut: str | QKeySequence | None = None,
             icon: str | None = None, checkable: bool = False) -> QAction:
        a = QAction(text, self)
        if icon:
            a.setIcon(icons.icon(icon))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setToolTip(f"{text}  ({QKeySequence(shortcut).toString(QKeySequence.NativeText)})")
        else:
            a.setToolTip(text)
        a.setCheckable(checkable)
        # Kürzel gelten im ganzen Fenster, aber nicht während man in einem Zahlenfeld tippt
        # (Qt gibt fokussierten Eingabefeldern Vorrang für Tasten wie Entf).
        a.setShortcutContext(Qt.WindowShortcut)
        a.triggered.connect(slot)
        self.addAction(a)
        self.actions_by_name[name] = a
        return a

    def _build_actions(self) -> None:
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        for t in Tool:
            a = self._act(f"tool_{t.value}", TOOL_LABELS[t], lambda _=False, t=t: self.set_tool(t),
                          TOOL_SHORTCUTS[t], t.value, checkable=True)
            self.tool_group.addAction(a)
        undo = self.undo_stack.createUndoAction(self, "Rückgängig")
        undo.setIcon(icons.icon("undo"))
        undo.setShortcut(QKeySequence.Undo)
        undo.setToolTip("Rückgängig  (Strg+Z)")
        redo = self.undo_stack.createRedoAction(self, "Wiederholen")
        redo.setIcon(icons.icon("redo"))
        redo.setShortcuts([QKeySequence.Redo, QKeySequence("Ctrl+Y")])
        redo.setToolTip("Wiederholen  (Strg+Y)")
        for name, a in (("undo", undo), ("redo", redo)):
            self.addAction(a)
            self.actions_by_name[name] = a
        self._act("new", "Neu", self.new_document, QKeySequence.New)
        self._act("open", "Öffnen …", self.open_dialog, QKeySequence.Open, "open")
        self._act("save", "Speichern", self.save, QKeySequence.Save, "save")
        self._act("save_as", "Speichern unter …", self.save_as_dialog, QKeySequence("Ctrl+Shift+S"))
        self._act("export", "Exportieren (SVG/PNG) …", self.export_dialog, QKeySequence("Ctrl+E"), "export")
        self._act("delete", "Löschen", self.delete_selection, QKeySequence.Delete, "delete")
        self._act("duplicate", "Duplizieren", self.duplicate_selection, QKeySequence("Ctrl+D"), "duplicate")
        self._act("copy", "Kopieren", self.copy_selection, QKeySequence.Copy)
        self._act("paste", "Einfügen", self.paste, QKeySequence.Paste)
        self._act("select_all", "Alles auswählen", self.select_all, QKeySequence.SelectAll)
        self._act("zoom_in", "Vergrößern", lambda: self.view.zoom_by(1.25), QKeySequence.ZoomIn, "zoom_in")
        self._act("zoom_out", "Verkleinern", lambda: self.view.zoom_by(0.8), QKeySequence.ZoomOut, "zoom_out")
        self._act("fit", "Arbeitsfläche einpassen", self.view.fit_work_area, QKeySequence("Ctrl+0"), "fit")
        g = self._act("grid", "Raster anzeigen", lambda on: self.view.set_grid_visible(on), "Ctrl+'",
                      "grid", checkable=True)
        g.setChecked(True)
        s = self._act("snap", "Am Raster fangen (1 mm)", self._set_snap, "Ctrl+Shift+'", "snap", checkable=True)
        s.setChecked(True)

    def _toolbar(self, name: str, orientation: Qt.Orientation) -> QToolBar:
        tb = QToolBar()
        tb.setObjectName(name)
        tb.setOrientation(orientation)
        tb.setMovable(False)
        tb.setIconSize(QSize(22, 22))
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        return tb

    def _build_layout(self) -> None:
        a = self.actions_by_name
        bar = self._toolbar("ActionBar", Qt.Horizontal)
        for name in ("open", "save", "export", None, "undo", "redo", None, "duplicate", "delete", None,
                     "zoom_out", "zoom_in", "fit", None, "grid", "snap"):
            bar.addSeparator() if name is None else bar.addAction(a[name])
        self.zoom_label = QLabel("100 %")
        self.zoom_label.setStyleSheet(f"color: {theme.TEXT_DIM}; padding: 0 8px;")
        bar.addWidget(self.zoom_label)

        strip = self._toolbar("ToolStrip", Qt.Vertical)
        for t in Tool:
            strip.addAction(a[f"tool_{t.value}"])

        canvas = QWidget()
        grid = QGridLayout(canvas)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        corner = QLabel("mm")
        corner.setObjectName("Ruler")
        corner.setAlignment(Qt.AlignCenter)
        corner.setFixedSize(Ruler.THICKNESS, Ruler.THICKNESS)
        corner.setStyleSheet(f"background: {theme.PANEL}; color: {theme.TEXT_DIM}; font-size: 9px;")
        self.h_ruler = Ruler(self.view, Qt.Horizontal)
        self.v_ruler = Ruler(self.view, Qt.Vertical)
        grid.addWidget(corner, 0, 0)
        grid.addWidget(self.h_ruler, 0, 1)
        grid.addWidget(self.v_ruler, 1, 0)
        grid.addWidget(self.view, 1, 1)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(strip)
        body.addWidget(canvas, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(bar)
        root.addWidget(self.property_bar)
        root.addLayout(body, 1)

    # --- Zustand ----------------------------------------------------------
    def set_tool(self, tool: Tool) -> None:
        self.tools.set_tool(tool)
        self.actions_by_name[f"tool_{tool.value}"].setChecked(True)
        self.notify(f"Werkzeug: {TOOL_LABELS[tool]}")

    def _set_snap(self, on: bool) -> None:
        self.snap_enabled = on

    def _emit_zoom(self) -> None:
        # 100 % = Arbeitsfläche in physischer Größe (logische 96 dpi).
        pct = self.view.px_per_mm / (96 / 25.4) * 100
        self.zoom_label.setText(f"{pct:.0f} %")

    def notify(self, text: str) -> None:
        self.statusMessage.emit(text)

    def _clean_changed(self, _clean: bool) -> None:
        try:
            self.fileChanged.emit(self.title())
        except RuntimeError:  # Stack wird beim Schließen bereits abgebaut
            pass

    def title(self) -> str:
        name = self.file_path.name if self.file_path else "Unbenannt"
        return name + ("" if self.undo_stack.isClean() else " •")

    def _on_document_changed(self) -> None:
        self.scene.sync()
        # Auswahl bereinigen: gelöschte oder gesperrte/ausgeblendete Objekte fallen heraus.
        sel = [i for i in self.selection if self.document.has_shape(i) and self.document.is_editable(i)]
        if sel != self.selection:
            self.selection = sel
            self.selectionChanged.emit(list(sel))
        self.refresh_selection_overlay()
        self.property_bar.refresh()
        self.documentChanged.emit()

    def set_selection(self, ids: list[str]) -> None:
        ids = [i for i in dict.fromkeys(ids) if self.document.has_shape(i) and self.document.is_editable(i)]
        if ids == self.selection:
            return
        self.selection = ids
        self.refresh_selection_overlay()
        self.property_bar.refresh()
        self.selectionChanged.emit(list(ids))

    def refresh_selection_overlay(self) -> None:
        self.scene.overlay.set_rect(self.document.selection_bounds(self.selection) if self.selection else None)

    def set_backdrop(self, image: QImage | None) -> None:
        self.view.set_backdrop(image)

    # --- Bearbeiten -------------------------------------------------------
    def select_all(self) -> None:
        self.set_selection([s.id for s in self.document.shapes])

    def delete_selection(self) -> None:
        if self.selection:
            ids = list(self.selection)
            self.undo_stack.push(DeleteShapesCommand(self.document, ids))
            self.notify(f"{len(ids)} Objekt(e) gelöscht")

    def translate_selection(self, dx: float, dy: float) -> None:
        doc = self.document
        b = doc.selection_bounds(self.selection)
        if b is None:
            return
        cx, cy = clamp_offset(Rect(b.x + dx, b.y + dy, b.w, b.h))
        dx, dy = dx + cx, dy + cy
        if dx == 0 and dy == 0:
            return
        old = {i: Geometry(*doc.shape(i).geom.as_tuple()) for i in self.selection}
        new = {i: g.translated(dx, dy) for i, g in old.items()}
        self.undo_stack.push(SetGeometryCommand(doc, old, new, "Verschieben"))

    def copy_selection(self) -> None:
        self._clipboard = [self.document.shape(i).copy() for i in self.selection]
        self._paste_count = 0

    def paste(self) -> None:
        if not self._clipboard:
            return
        self._paste_count += 1
        self._insert_copies(self._clipboard, PASTE_OFFSET_MM * self._paste_count, "Einfügen")

    def duplicate_selection(self) -> None:
        if self.selection:
            shapes = [self.document.shape(i) for i in self.selection]
            self._insert_copies(shapes, PASTE_OFFSET_MM, "Duplizieren")

    def _insert_copies(self, shapes: list[Shape], offset: float, label: str) -> None:
        doc = self.document
        fallback = doc.active_layer_id
        copies = []
        for s in shapes:
            c = s.copy(new_identity=True)
            c.geom = c.geom.translated(offset, offset)
            if not any(l.id == c.layer_id for l in doc.layers):
                c.layer_id = fallback  # type: ignore[assignment]
            copies.append(c)
        self.undo_stack.push(AddShapesCommand(doc, copies, label))
        self.set_selection([c.id for c in copies])

    # --- Dateien ----------------------------------------------------------
    def confirm_discard(self) -> bool:
        """Vor Neu/Öffnen/Schließen: True, wenn weitergemacht werden darf.

        Bietet Speichern an; bricht der Nutzer den Speichern-Dialog ab, bleibt
        das Projekt offen.
        """
        if self.undo_stack.isClean():
            return True
        r = QMessageBox.question(self, "Ungespeicherte Änderungen",
                                 "Änderungen am aktuellen Projekt speichern?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                                 QMessageBox.Save)
        if r == QMessageBox.Save:
            self.save()
            return self.undo_stack.isClean()
        return r == QMessageBox.Discard

    _confirm_discard = confirm_discard

    def new_document(self) -> None:
        if not self._confirm_discard():
            return
        fresh = Document()
        self.document.load_dict(fresh.to_dict())
        self.file_path = None
        self._reset_history()

    def load_file(self, path: str | os.PathLike[str]) -> None:
        load_into(self.document, path)
        self.file_path = Path(path)
        self._reset_history()
        self.notify(f"Geöffnet: {self.file_path.name}")

    def save_file(self, path: str | os.PathLike[str]) -> Path:
        p = save_document(self.document, path)
        self.file_path = p
        self.undo_stack.setClean()
        self.fileChanged.emit(self.title())
        self.notify(f"Gespeichert: {p.name}")
        return p

    def _reset_history(self) -> None:
        self.undo_stack.clear()
        self.set_selection([])
        self.view.fit_work_area()
        self.fileChanged.emit(self.title())

    def _start_dir(self) -> str:
        return str(self.file_path.parent if self.file_path else Path.home())

    def open_dialog(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Projekt öffnen", self._start_dir(),
                                              f"LumaCut-Projekt (*{FILE_SUFFIX} *.json)")
        if path:
            try:
                self.load_file(path)
            except (OSError, ValueError, KeyError) as e:
                QMessageBox.warning(self, "Öffnen fehlgeschlagen", str(e))

    def save(self) -> None:
        if self.file_path is None:
            self.save_as_dialog()
        else:
            self.save_file(self.file_path)

    def save_as_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Projekt speichern",
                                              str(Path(self._start_dir()) / f"Projekt{FILE_SUFFIX}"),
                                              f"LumaCut-Projekt (*{FILE_SUFFIX})")
        if path:
            if not path.endswith(".json"):
                path += FILE_SUFFIX
            try:
                self.save_file(path)
            except OSError as e:
                QMessageBox.warning(self, "Speichern fehlgeschlagen", str(e))

    def export_dialog(self) -> None:
        path, flt = QFileDialog.getSaveFileName(self, "Arbeitsfläche exportieren",
                                                str(Path(self._start_dir()) / "Arbeitsflaeche.svg"),
                                                "SVG-Vektor (*.svg);;PNG-Bild 254 dpi (*.png)")
        if not path:
            return
        try:
            if path.lower().endswith(".png") or "PNG" in flt:
                if not path.lower().endswith(".png"):
                    path += ".png"
                export_png(self.document, path)
            else:
                if not path.lower().endswith(".svg"):
                    path += ".svg"
                export_svg(self.document, path)
            self.notify(f"Exportiert: {Path(path).name}")
        except OSError as e:
            QMessageBox.warning(self, "Export fehlgeschlagen", str(e))
