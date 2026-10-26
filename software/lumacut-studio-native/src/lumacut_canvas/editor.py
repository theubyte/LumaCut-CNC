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
    editor.add_overlay(key, overlay, z)   # weitere Bilder/Zeichnungen unter den Objekten
    editor.request_roi()       # Bereich aufziehen -> roiSelected(x, y, w, h) in mm
    editor.add_toolbar_action(action)     # eigene Aktion in die Aktionsleiste
    editor.set_touch_mode(on)  # Finger-Bedienung; touchModeChanged(bool), Aktion "touch_mode"
    export.job_layers(editor.document)  # Laserparameter + Polylinien in Maschinen-mm
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSettings, QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QImage, QKeySequence, QPen, QUndoStack
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QGraphicsRectItem,
                               QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMenu, QMessageBox, QToolBar, QToolButton, QVBoxLayout,
                               QWidget)

from . import arrange_ui, icons, pathops_ui, theme, touch
from .fill_preview import FillPreview
from .path_preview import PathPreview, PathPreviewBar
from .fit import HScrollStrip
from .canvas_view import PX_PER_MM_100, CanvasScene, CanvasView, Ruler
from .commands import (AddShapesCommand, DeleteShapesCommand, SetGeometryCommand, SetGroupsCommand,
                       SetLayerAttrsCommand, SetShapeLayerCommand, SetTextCommand)
from .document_io import FILE_SUFFIX, load_into, save_document
from .export import export_png, export_svg
from .material import Material, material_layer_attrs
from .model import Document, Geometry, Shape, keep_inside_together, new_id, normalize_angle
from .tools import TOOL_LABELS, TOOL_SHORTCUTS, Tool, ToolController
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, Rect, clamp_offset

PASTE_OFFSET_MM = 5.0
ROTATE_STEP_DEG = 15.0


def _angle_spin() -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(-180.0, 180.0)
    s.setWrapping(True)
    s.setDecimals(1)
    s.setSingleStep(ROTATE_STEP_DEG)
    s.setSuffix(" °")
    s.setKeyboardTracking(False)
    s.setAlignment(Qt.AlignRight)
    s.setFixedWidth(84)
    return s


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
        lay.addSpacing(8)
        angle_label = QLabel("Winkel")
        self.angle = _angle_spin()
        tip = "Drehung um die Mitte (im Uhrzeigersinn). Am Griff ziehen; Umschalt rastet in 15°-Schritten."
        angle_label.setToolTip(tip)
        self.angle.setToolTip(tip)
        lay.addWidget(angle_label)
        lay.addWidget(self.angle)
        self.angle.valueChanged.connect(self._angle_edited)
        self._angle_shown = 0.0
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
        return (self.x, self.y, self.w, self.h, self.angle)

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
            names = {"rect": "Rechteck", "ellipse": "Ellipse", "line": "Linie", "text": "Text",
                     "polygon": "Polygon", "path": "Freihand", "image": "Bild"}
            tops = {doc.shape(i).groups[0] if doc.shape(i).groups else i for i in sel}
            if len(sel) == 1:
                self.title.setText(names.get(kinds.pop(), "Objekt"))
            elif len(tops) == 1:
                self.title.setText(f"Gruppe ({len(sel)})")
            else:
                self.title.setText(f"{len(sel)} Objekte")
            self.x.setValue(b.x)
            self.y.setValue(b.y)
            g = doc.shape(sel[0]).geom
            if len(sel) == 1 and g.rot:
                # Gedrehtes Einzelobjekt: eigene Breite/Höhe statt Hüllbox.
                self.w.setValue(abs(g.w))
                self.h.setValue(abs(g.h))
            else:
                self.w.setValue(b.w)
                self.h.setValue(b.h)
            rots = {round(doc.shape(i).geom.rot, 6) for i in sel}
            self._angle_shown = rots.pop() if len(rots) == 1 else 0.0
            self.angle.setValue(self._angle_shown)
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
        g0 = doc.shape(sel[0]).geom
        if len(sel) == 1 and g0.rot:
            self._edit_rotated_single(sel[0], g0, ob, sender)
            return
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
        old = {i: doc.shape(i).geom.copy() for i in sel}
        new = {i: g.mapped(ob, nb) for i, g in old.items()}
        ed.undo_stack.push(SetGeometryCommand(doc, old, new, "Maße ändern"))

    def _edit_rotated_single(self, sid: str, g: Geometry, ob: Rect, sender) -> None:
        """Maße eines gedrehten Objekts: X/Y verschieben die Hüllbox, B/H ändern
        die eigene Größe um die Mitte."""
        if sender in (self.x, self.y):
            ng = g.translated(self.x.value() - ob.x, self.y.value() - ob.y)
        else:
            w, h = self.w.value(), self.h.value()
            aw, ah = abs(g.w), abs(g.h)
            if self.ratio.isChecked() and aw > 0 and ah > 0:
                if sender is self.w:
                    h = ah * w / aw
                elif sender is self.h:
                    w = aw * h / ah
            cx, cy = g.center()
            ng = Geometry(0, 0, w if g.w >= 0 else -w, h if g.h >= 0 else -h, g.rot).with_center(cx, cy)
            if aw == 0:
                ng.w = 0.0
            if ah == 0:
                ng.h = 0.0
            ng = ng.with_center(cx, cy)
        self.ed.undo_stack.push(SetGeometryCommand(self.ed.document, {sid: g.copy()}, {sid: ng}, "Maße ändern"))

    def _angle_edited(self, value: float) -> None:
        if self._updating:
            return
        delta = normalize_angle(value - self._angle_shown)
        if delta:
            self.ed.rotate_selection(delta)

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
    roiSelected = Signal(float, float, float, float)  # x, y, w, h in Arbeitsflächen-mm  # noqa: N815
    roiCancelled = Signal()  # noqa: N815
    touchModeChanged = Signal(bool)  # noqa: N815

    def __init__(self, document: Document | None = None, parent: QWidget | None = None, *,
                 settings: QSettings | None = None) -> None:
        """``settings``: wo die Touch-Modus-Wahl gespeichert wird (Standard:
        Anwendungs-QSettings, falls die App eine Organisation gesetzt hat)."""
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
        self.view.zoom_anchor_provider = self._selection_center
        self.view.cursorMoved.connect(self.cursorMoved)
        self.view.viewChanged.connect(self._emit_zoom)

        self.roi: Rect | None = None
        self._roi_item = QGraphicsRectItem()
        roi_pen = QPen(QColor(theme.ACCENT), 1.5, Qt.DashDotLine)
        roi_pen.setCosmetic(True)
        self._roi_item.setPen(roi_pen)
        self._roi_item.setZValue(1.9e9)
        self._roi_item.setVisible(False)
        self.scene.addItem(self._roi_item)

        self.actions_by_name: dict[str, QAction] = {}
        self._build_actions()
        self.property_bar = PropertyBar(self)
        self._build_layout()

        self.document.add_listener(self._on_document_changed)
        self.fill_preview = FillPreview(self)  # Schraffur der Ebenen sichtbar machen
        self.undo_stack.cleanChanged.connect(self._clean_changed)
        self.set_tool(Tool.SELECT)

        # Touch-Modus: gespeicherte Wahl, sonst automatisch (Touchscreen vorhanden).
        self.touch_mode = False
        self._settings = settings if settings is not None else touch.default_settings()
        saved = touch.load_setting(self._settings)
        self.set_touch_mode(touch.has_touchscreen() if saved is None else saved, persist=False)
        self.view.touchDetected.connect(self._on_touch_detected)
        self.context_menu: QMenu | None = None
        self.view.contextMenuRequested.connect(self._show_context_menu)

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
        self._act("rotate_cw", "90° im Uhrzeigersinn drehen", lambda: self.rotate_selection(90.0),
                  QKeySequence("Ctrl+R"), "rotate_cw")
        self._act("rotate_ccw", "90° gegen den Uhrzeigersinn drehen", lambda: self.rotate_selection(-90.0),
                  QKeySequence("Ctrl+Shift+R"), "rotate_ccw")
        self._act("group", "Gruppieren", self.group_selection, QKeySequence("Ctrl+G"), "group")
        self._act("ungroup", "Gruppierung aufheben", self.ungroup_selection, QKeySequence("Ctrl+Shift+G"),
                  "ungroup")
        self._act("copy", "Kopieren", self.copy_selection, QKeySequence.Copy)
        self._act("paste", "Einfügen", self.paste, QKeySequence.Paste)
        self._act("select_all", "Alles auswählen", self.select_all, QKeySequence.SelectAll)
        self._act("zoom_in", "Vergrößern", lambda: self.view.zoom_by(1.25), QKeySequence.ZoomIn, "zoom_in")
        self._act("zoom_out", "Verkleinern", lambda: self.view.zoom_by(0.8), QKeySequence.ZoomOut, "zoom_out")
        self._act("fit", "Arbeitsfläche einpassen", self.view.fit_work_area, QKeySequence("Ctrl+0"), "fit")
        self._act("fit_selection", "Auswahl einpassen", self.fit_selection, QKeySequence("Ctrl+Shift+A"))
        g = self._act("grid", "Raster anzeigen", lambda on: self.view.set_grid_visible(on), "Ctrl+'",
                      "grid", checkable=True)
        g.setChecked(True)
        s = self._act("snap", "Am Raster fangen (1 mm)", self._set_snap, "Ctrl+Shift+'", "snap", checkable=True)
        s.setChecked(True)
        self._act("path_preview", "Pfadvorschau (Laserbahn, Reihenfolge, Zeit)",
                  lambda on: self.set_path_preview(on), "Ctrl+Shift+P", "path", checkable=True)
        self.arranger = arrange_ui.install(self)  # Ausrichten/Verteilen/Array
        self.path_ops = pathops_ui.install(self)  # Boole/Verschweißen/Versatz/Text in Pfade
        self._act("touch_mode", "Touch-Modus (große Anfasser und Knöpfe)",
                  lambda on: self.set_touch_mode(on), None, "touch", checkable=True)

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
        self.action_bar = bar
        for name in ("open", "save", "export", None, "undo", "redo", None, "duplicate", "delete",
                     "rotate_ccw", "rotate_cw", "group", "ungroup", None,
                     "zoom_out", "zoom_in", "fit", None, "grid", "snap", "path_preview", "touch_mode"):
            bar.addSeparator() if name is None else bar.addAction(a[name])
            if name == "ungroup":
                self.arrange_button = arrange_ui.add_to_bar(self, bar)
                self.path_ops_button = pathops_ui.add_to_bar(self, bar)
        self.zoom_label = QLabel("100 %")
        self.zoom_label.setStyleSheet(f"color: {theme.TEXT_DIM}; padding: 0 8px;")
        self._zoom_label_action = bar.addWidget(self.zoom_label)
        self._extension_separator = None

        strip = self._toolbar("ToolStrip", Qt.Vertical)
        self.tool_strip = strip
        strip.setIconSize(QSize(24, 24))
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
        # Auf schmalen Fenstern waagerecht scrollbar statt abgeschnitten.
        self.property_scroll = HScrollStrip(self.property_bar)
        root.addWidget(self.property_scroll)
        # Pfadvorschau: Werte/Filter/Abspielen, nur sichtbar solange eingeschaltet.
        self.path_preview = PathPreview(self)
        self.path_preview_bar = PathPreviewBar(self.path_preview)
        self.path_preview_scroll = HScrollStrip(self.path_preview_bar)
        self.path_preview_scroll.setVisible(False)
        self.path_preview.changed.connect(
            lambda: self.path_preview_scroll.setVisible(self.path_preview.visible))
        root.addWidget(self.path_preview_scroll)
        root.addLayout(body, 1)

    # --- Zustand ----------------------------------------------------------
    def set_tool(self, tool: Tool) -> None:
        self.tools.set_tool(tool)
        self.actions_by_name[f"tool_{tool.value}"].setChecked(True)
        self.notify(f"Werkzeug: {TOOL_LABELS[tool]}")

    # --- Kontextmenü (Rechtsklick / langes Drücken) -------------------------
    def build_context_menu(self, scene_pt: QPointF) -> QMenu:
        """Menü für ``scene_pt`` (mm). Ein Objekt unter dem Punkt, das noch
        nicht ausgewählt ist, wird vorher ausgewählt (wie in Zeichenprogrammen)."""
        hit = self.scene.editable_shape_at(scene_pt)
        if hit is not None and hit not in self.selection:
            self.set_selection([hit])
        menu = QMenu(self)
        menu.setObjectName("CanvasContextMenu")
        if self.touch_mode:  # Zeilen ≥ 44 px für Finger
            menu.setStyleSheet("QMenu::item { padding: 13px 28px 13px 20px; min-height: 18px; }")
        a = self.actions_by_name
        groups: list[tuple[str, ...]] = []
        if self.selection:
            groups.append(("copy", "duplicate", "delete"))
            groups.append(("rotate_ccw", "rotate_cw", "group", "ungroup"))
            groups.append(("fit_selection",))
        groups.append(("paste", "select_all", "path_preview"))
        for g in groups:
            if menu.actions():
                menu.addSeparator()
            for name in g:
                if name == "paste" and not self._clipboard:
                    continue
                menu.addAction(a[name])
            if g and g[0] == "rotate_ccw":
                for build in (arrange_ui.build_menu, pathops_ui.build_menu):
                    sub = build(self, menu)
                    sub.setStyleSheet(menu.styleSheet())
                    menu.addMenu(sub)
        return menu

    def _show_context_menu(self, scene_pt: QPointF, global_pos) -> None:
        if self.context_menu is not None:
            self.context_menu.close()
            self.context_menu.deleteLater()
        self.context_menu = self.build_context_menu(scene_pt)
        self.context_menu.popup(global_pos)

    def set_path_preview(self, on: bool) -> None:
        """Pfadvorschau ein/aus (zeigt den G-Code des Sendepfads, ändert nichts)."""
        on = bool(on)
        act = self.actions_by_name["path_preview"]
        if act.isChecked() != on:
            act.blockSignals(True)
            act.setChecked(on)
            act.blockSignals(False)
        self.path_preview.set_visible(on)
        self.notify("Pfadvorschau an" if on else "Pfadvorschau aus")

    def set_touch_mode(self, on: bool, persist: bool = True) -> None:
        """Touch-Modus ein/aus. ``persist``: Wahl in QSettings merken (eine
        gespeicherte Wahl schaltet die automatische Erkennung ab)."""
        on = bool(on)
        if persist:
            touch.save_setting(self._settings, on)
        act = self.actions_by_name["touch_mode"]
        if act.isChecked() != on:
            act.blockSignals(True)
            act.setChecked(on)
            act.blockSignals(False)
        if on == self.touch_mode and self.view.touch_mode == on:
            return
        self.touch_mode = on
        self.view.set_touch_mode(on)
        self._apply_touch_style()
        self.touchModeChanged.emit(on)

    def _apply_touch_style(self) -> None:
        """Werkzeug- und Aktionsleiste: 32-px-Icons in ≥ 48-px-Knöpfen mit Abstand."""
        px = self.view.metrics.icon_px
        self.action_bar.setIconSize(QSize(px, px))
        strip_px = max(px, 24)  # Werkzeugleiste immer fingertauglich (≥ 44-px-Knöpfe)
        self.tool_strip.setIconSize(QSize(strip_px, strip_px))
        self.setProperty("touch", "true" if self.touch_mode else "false")
        self.setStyleSheet("")
        self.setStyleSheet(theme.CANVAS_QSS)

    def _on_touch_detected(self) -> None:
        if not self.touch_mode and touch.load_setting(self._settings) is None:
            self.set_touch_mode(True, persist=False)
            self.notify("Touch-Eingabe erkannt: Touch-Modus aktiv (abschaltbar in der Aktionsleiste).")

    def _set_snap(self, on: bool) -> None:
        self.snap_enabled = on

    def _emit_zoom(self) -> None:
        # 100 % = Arbeitsfläche in physischer Größe (logische 96 dpi).
        pct = self.view.px_per_mm / PX_PER_MM_100 * 100
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
        """Auswahl setzen; Gruppen werden automatisch ganz ausgewählt."""
        ids = self.document.expand_to_groups(dict.fromkeys(ids))
        if ids == self.selection:
            return
        self.selection = ids
        self.refresh_selection_overlay()
        self.property_bar.refresh()
        self.selectionChanged.emit(list(ids))

    def selection_frame(self) -> tuple[Rect, float] | None:
        """Auswahlrahmen: ein gedrehtes Einzelobjekt bekommt einen gedrehten
        Rahmen (Griffe an den Objektkanten), sonst die achsparallele Hüllbox."""
        sel = [i for i in self.selection if self.document.has_shape(i)]
        if not sel:
            return None
        if len(sel) == 1:
            g = self.document.shape(sel[0]).geom
            if g.rot:
                return g.local_bounds(), g.rot
        b = self.document.selection_bounds(sel)
        return (b, 0.0) if b is not None else None

    def refresh_selection_overlay(self) -> None:
        frame = self.selection_frame()
        if frame is None:
            self.scene.overlay.set_rect(None)
        else:
            self.scene.overlay.set_rect(*frame)

    def set_backdrop(self, image: QImage | None) -> None:
        self.view.set_backdrop(image)

    # --- Integrations-Hooks (Scan & Probe u. a.) ---------------------------
    def add_overlay(self, key: str, overlay, z: float = 0.0) -> None:
        """Bild/Zeichnung unter den Objekten einblenden (siehe ``overlays``)."""
        self.view.add_overlay(key, overlay, z)

    def remove_overlay(self, key: str) -> bool:
        return self.view.remove_overlay(key)

    def overlay(self, key: str):
        return self.view.overlay(key)

    def refresh_overlays(self) -> None:
        self.view.refresh_overlays()

    def add_toolbar_action(self, action: QAction, name: str | None = None) -> QAction:
        """Fremde Aktion rechts in die Aktionsleiste (vor die Zoomanzeige) hängen.

        Das Kürzel der Aktion gilt dann im ganzen Fenster; ``name`` macht sie
        unter ``actions_by_name`` auffindbar."""
        bar = self.action_bar
        if self._extension_separator is None:
            self._extension_separator = bar.insertSeparator(self._zoom_label_action)
        bar.insertAction(self._zoom_label_action, action)
        if action.shortcut():
            action.setShortcutContext(Qt.WindowShortcut)
            self.addAction(action)
        key = name or action.objectName()
        if key:
            if key in self.actions_by_name and self.actions_by_name[key] is not action:
                raise ValueError(f"Aktion {key!r} existiert bereits")
            self.actions_by_name[key] = action
        return action

    def request_roi(self, hint: str = "Bereich auf der Arbeitsfläche aufziehen (Esc bricht ab)") -> None:
        """Nächster Mauszug zieht einen Bereich auf; Ergebnis über ``roiSelected``
        (x, y, w, h in mm, auf die Fläche begrenzt), Abbruch über ``roiCancelled``.
        Das aktive Werkzeug und das Dokument bleiben unverändert."""
        if self.tools.roi_pending:
            return
        self.tools.cancel()
        self.tools.roi_pending = True
        self.tools.update_cursor()
        self.view.setFocus()
        self.notify(hint)

    def cancel_roi(self) -> None:
        if self.tools.roi_pending:
            self.tools.cancel()

    @property
    def roi_pending(self) -> bool:
        return self.tools.roi_pending

    def _roi_finished(self, r: Rect) -> None:
        self.set_roi(r)
        self.notify(f"Bereich: {r.w:.1f} × {r.h:.1f} mm bei X {r.x:.1f} / Y {r.y:.1f}")
        self.roiSelected.emit(r.x, r.y, r.w, r.h)

    def set_roi(self, r: Rect | None) -> None:
        """Bereich gestrichelt anzeigen (``None`` blendet ihn aus). Nicht Teil des Dokuments."""
        self.roi = r
        item = self._roi_item
        if r is None:
            item.setVisible(False)
        else:
            item.setRect(QRectF(r.x, r.y, r.w, r.h))
            item.setVisible(True)

    def clear_roi(self) -> None:
        self.set_roi(None)

    # --- Bearbeiten -------------------------------------------------------
    def _selection_center(self) -> QPointF | None:
        """Mitte der Auswahl (mm) als Mausrad-Zoomanker, None ohne Auswahl."""
        ids = [i for i in self.selection if self.document.has_shape(i)]
        r = self.document.selection_bounds(ids) if ids else None
        return None if r is None else QPointF(r.x + r.w / 2.0, r.y + r.h / 2.0)

    def apply_material(self, material: Material, layer_id: str | None = None,
                       target_depth_mm: float = 0.0, apply_settings: bool = True) -> None:
        """Material auf eine Ebene anwenden (ein Undo-Schritt).

        Setzt Dicke/Tiefe je Durchgang und die abgeleiteten Durchgänge, die der
        Nutzer danach im Ebenen-Panel überschreiben kann.
        """
        lid = layer_id or self.document.active_layer_id
        attrs = material_layer_attrs(material, target_depth_mm, apply_settings)
        self.undo_stack.push(SetLayerAttrsCommand(self.document, lid, attrs,
                                                  f"Material: {material.name}"))

    def fit_selection(self) -> None:
        """Zoom to the selection (Ctrl+Shift+A), or to all objects, or the work area."""
        doc = self.document
        ids = [i for i in self.selection if doc.has_shape(i)] or [s.id for s in doc.shapes]
        r = doc.selection_bounds(ids) if ids else None
        if r is None:
            self.view.fit_work_area()
        else:
            self.view.fit_rect(QRectF(r.x, r.y, r.w, r.h))

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
        old = {i: doc.shape(i).geom.copy() for i in self.selection}
        new = {i: g.translated(dx, dy) for i, g in old.items()}
        self.undo_stack.push(SetGeometryCommand(doc, old, new, "Verschieben"))

    def rotate_selection(self, delta_deg: float) -> None:
        """Auswahl um ihre Mitte drehen (ein Undo-Schritt); die Anordnung
        mehrerer Objekte bleibt erhalten und gemeinsam in der Fläche."""
        doc = self.document
        sel = [i for i in self.selection if doc.has_shape(i)]
        frame = self.selection_frame()
        if not sel or frame is None or not delta_deg:
            return
        r = frame[0]
        cx, cy = r.x + r.w / 2, r.y + r.h / 2
        old = {i: doc.shape(i).geom.copy() for i in sel}
        new = keep_inside_together({i: g.rotated(delta_deg, cx, cy) for i, g in old.items()})
        self.undo_stack.push(SetGeometryCommand(doc, old, new, "Drehen"))

    def group_selection(self) -> None:
        """Auswahl zu einer (ggf. verschachtelten) Gruppe zusammenfassen."""
        doc = self.document
        sel = [i for i in self.selection if doc.has_shape(i)]
        units = {doc.shape(i).groups[0] if doc.shape(i).groups else i for i in sel}
        if len(units) < 2:
            self.notify("Zum Gruppieren mindestens zwei Objekte oder Gruppen auswählen.")
            return
        gid = new_id()
        self.undo_stack.push(SetGroupsCommand(doc, {i: (gid,) + doc.shape(i).groups for i in sel},
                                              "Gruppieren"))
        self.notify(f"Gruppe aus {len(units)} Elementen erstellt")

    def ungroup_selection(self) -> None:
        """Äußerste Gruppe der ausgewählten Objekte auflösen (innere bleiben)."""
        doc = self.document
        sel = [i for i in self.selection if doc.has_shape(i) and doc.shape(i).groups]
        if not sel:
            self.notify("Keine Gruppe ausgewählt.")
            return
        # Alle Mitglieder (auch ausgeblendete/gesperrte) verlieren die Gruppe.
        tops = {doc.shape(i).groups[0] for i in sel}
        members = [s.id for s in doc.shapes if s.groups and s.groups[0] in tops]
        keep = list(self.selection)
        self.undo_stack.push(SetGroupsCommand(doc, {i: doc.shape(i).groups[1:] for i in members},
                                              "Gruppierung aufheben"))
        self.selection = []
        self.set_selection(keep)

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
        # Kopien bilden eigene Gruppen (gleiche Struktur, neue IDs).
        remap: dict[str, str] = {}
        for s in shapes:
            c = s.copy(new_identity=True)
            c.groups = tuple(remap.setdefault(g, new_id()) for g in s.groups)
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
