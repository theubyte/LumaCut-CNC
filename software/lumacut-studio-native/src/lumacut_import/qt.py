"""Qt-Anbindung: Menü „Datei“, Importieren (Strg+I), Drag & Drop, Bildeinstellungen.

Außerdem „Bild nachzeichnen …“ (Alt+T, :mod:`.trace` / :mod:`.trace_qt`).

``install_import(window)`` erwartet ein Hauptfenster mit ``window.canvas``
(:class:`lumacut_canvas.editor.CanvasEditor`). Alle Importe laufen über einen
einzigen ``AddShapesCommand`` („Importieren“) und sind damit in einem Schritt
rückgängig zu machen.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QInputDialog, QLabel,
                               QMessageBox, QSpinBox, QVBoxLayout)

from lumacut_canvas.commands import AddShapesCommand, DeleteShapesCommand, SetImageSettingsCommand
from lumacut_canvas.document_io import FILE_SUFFIX
from lumacut_canvas.model import ImageSettings

from .placement import ALL_SUFFIXES, IMAGE_SUFFIXES, import_file

MODE_LABELS = {
    "threshold": "Schwellwert (Schwarz/Weiß)",
    "floyd": "Floyd-Steinberg (Dithering)",
    "atkinson": "Atkinson (Dithering)",
    "ordered": "Geordnet (Bayer)",
    "grayscale": "Graustufen (Leistung je Pixel)",
    "depth3d": "3D-Tiefe (Mehrfach-Durchgänge)",
}

FILTER = ("Alle unterstützten (" + " ".join(f"*{s}" for s in ALL_SUFFIXES) + ");;"
          "Vektor (*.svg *.dxf *.pdf);;"
          "PDF (*.pdf);;"
          "Bild (" + " ".join(f"*{s}" for s in IMAGE_SUFFIXES) + ")")


class ImageSettingsDialog(QDialog):
    """Gravur-Einstellungen eines Bildobjekts (LightBurn „Bildmodus“)."""

    def __init__(self, settings: ImageSettings, width_mm: float, px_width: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bildeinstellungen")
        self._width_mm = width_mm
        self._px = px_width
        st = settings.normalized()
        form = QFormLayout()
        self.mode = QComboBox()
        for key, label in MODE_LABELS.items():
            self.mode.addItem(label, key)
        self.mode.setCurrentIndex(list(MODE_LABELS).index(st.mode))
        self.interval = self._dspin(0.03, 2.0, st.line_interval_mm, 3, 0.01, " mm")
        self.dpi_label = QLabel()
        self.power = self._dspin(1, 100, st.power, 1, 1, " %")
        self.min_power = self._dspin(0, 100, st.min_power, 1, 1, " %")
        self.speed = self._dspin(1, 6000, st.speed_mm_min, 0, 100, " mm/min")
        self.passes = QSpinBox()
        self.passes.setRange(1, 30)
        self.passes.setValue(st.passes)
        self.threshold = QSpinBox()
        self.threshold.setRange(0, 255)
        self.threshold.setValue(st.threshold)
        self.overscan = self._dspin(0, 20, st.overscan_mm, 1, 0.5, " mm")
        self.bidirectional = QCheckBox("Bidirektional (hin und zurück lasern)")
        self.bidirectional.setChecked(st.bidirectional)
        self.negative = QCheckBox("Negativ (Helles lasern)")
        self.negative.setChecked(st.negative)
        self.levels = QSpinBox()
        self.levels.setRange(2, 64)
        self.levels.setValue(st.depth_levels)
        self.z_step = self._dspin(0, 2, st.z_step_mm, 2, 0.05, " mm")
        self.z_step.setToolTip("Fokus je Tiefenstufe absenken (0 = aus, max. 3 mm gesamt)")
        form.addRow("Modus", self.mode)
        form.addRow("Linienabstand", self.interval)
        form.addRow("", self.dpi_label)
        form.addRow("Leistung (max.)", self.power)
        form.addRow("Leistung (min., Graustufen)", self.min_power)
        form.addRow("Geschwindigkeit", self.speed)
        form.addRow("Durchgänge", self.passes)
        form.addRow("Schwellwert", self.threshold)
        form.addRow("Overscan", self.overscan)
        form.addRow("", self.bidirectional)
        form.addRow("", self.negative)
        form.addRow("Tiefenstufen (3D)", self.levels)
        form.addRow("Z-Schritt je Stufe (3D)", self.z_step)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Übernehmen")
        buttons.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.hint)
        lay.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self._update)
        self.interval.valueChanged.connect(self._update)
        self.levels.valueChanged.connect(self._update)
        self.z_step.valueChanged.connect(self._update)
        self._update()

    @staticmethod
    def _dspin(lo, hi, value, decimals, step, suffix) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(decimals)
        sb.setSingleStep(step)
        sb.setSuffix(suffix)
        sb.setValue(value)
        return sb

    def _update(self) -> None:
        mode = self.mode.currentData()
        self.min_power.setEnabled(mode == "grayscale")
        self.threshold.setEnabled(mode == "threshold")
        self.levels.setEnabled(mode == "depth3d")
        self.z_step.setEnabled(mode == "depth3d")
        dpi = 25.4 / self.interval.value()
        src_dpi = self._px / self._width_mm * 25.4 if self._width_mm > 0 else 0
        self.dpi_label.setText(f"= {dpi:.0f} DPI (Bild: {src_dpi:.0f} DPI)")
        drop = self.z_step.value() * (self.levels.value() - 1)
        if mode == "depth3d" and drop > 3.0:
            self.hint.setText(f"Fokus-Absenkung {drop:.2f} mm > 3 mm – Auftrag wird abgelehnt.")
        elif mode == "depth3d":
            self.hint.setText("Dunkle Bereiche werden öfter gelasert und damit tiefer. "
                              "Fokuskorrektur aus dem Scan ist mit Z-Schritten nicht kombinierbar.")
        else:
            self.hint.setText("")

    def settings(self) -> ImageSettings:
        return ImageSettings(
            mode=self.mode.currentData(), line_interval_mm=self.interval.value(),
            power=self.power.value(), min_power=self.min_power.value(),
            speed_mm_min=self.speed.value(), passes=self.passes.value(),
            threshold=self.threshold.value(), bidirectional=self.bidirectional.isChecked(),
            overscan_mm=self.overscan.value(), negative=self.negative.isChecked(),
            depth_levels=self.levels.value(), z_step_mm=self.z_step.value()).normalized()


class ImportTools(QObject):
    """Menü „Datei“ (Neu/Öffnen/Speichern/Importieren/Exportieren) + Drop."""

    def __init__(self, window, interactive: bool = True) -> None:
        super().__init__(window)
        self.window = window
        self.editor = window.canvas
        self.interactive = interactive
        self.last_error: str | None = None
        ed = self.editor
        self.import_action = QAction("Importieren …", window)
        self.import_action.setObjectName("import_action")
        self.import_action.setShortcut(QKeySequence("Ctrl+I"))
        self.import_action.setToolTip("SVG, DXF, PDF oder Bild (PNG/JPG/BMP) importieren  (Strg+I)")
        self.import_action.triggered.connect(lambda _=False: self.import_dialog())
        self.image_action = QAction("Bildeinstellungen …", window)
        self.image_action.setObjectName("image_settings_action")
        self.image_action.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self.image_action.setToolTip("Modus, Linienabstand, Leistung des ausgewählten Bildes  (Strg+Umschalt+I)")
        self.image_action.triggered.connect(lambda _=False: self.edit_image_settings())
        self.image_action.setEnabled(False)
        self.trace_action = QAction("Bild nachzeichnen …", window)
        self.trace_action.setObjectName("trace_image_action")
        self.trace_action.setShortcut(QKeySequence("Alt+T"))
        self.trace_action.setToolTip("Ausgewähltes Bild in Vektorkonturen umwandeln  (Alt+T)")
        self.trace_action.triggered.connect(lambda _=False: self.trace_image())
        self.trace_action.setEnabled(False)
        ed.selectionChanged.connect(lambda _ids: self._update_image_action())
        ed.documentChanged.connect(self._update_image_action)
        ed.image_settings_handler = self.edit_image_settings

        menu = window.menuBar().addMenu("&Datei")
        # Menü „Datei“ steht links von „Material“ (falls schon angelegt).
        actions = window.menuBar().actions()
        if len(actions) > 1:
            window.menuBar().insertMenu(actions[0], menu)
        self.menu = menu
        by = ed.actions_by_name
        for name in ("new", "open", "save", "save_as"):
            if name in by:
                menu.addAction(by[name])
        menu.addSeparator()
        menu.addAction(self.import_action)
        menu.addAction(self.image_action)
        menu.addAction(self.trace_action)
        if "export" in by:
            menu.addAction(by["export"])
        menu.addSeparator()
        quit_action = QAction("Beenden", window)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(lambda _=False: window.close())
        menu.addAction(quit_action)
        window.addAction(self.import_action)
        window.addAction(self.image_action)
        window.addAction(self.trace_action)
        try:
            ed.add_toolbar_action(self.import_action, "import")
        except Exception:  # noqa: BLE001 - Toolbar optional
            pass

        vp = ed.view.viewport()
        ed.view.setAcceptDrops(True)
        vp.setAcceptDrops(True)
        vp.installEventFilter(self)

    # ---------------------------------------------------------------- Import
    def _error(self, title: str, text: str) -> None:
        self.last_error = text
        self.editor.notify(f"{title}: {text}")
        if self.interactive:
            QMessageBox.warning(self.window, title, text)

    def import_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self.window, "Importieren", self.editor._start_dir(), FILTER)
        if path:
            self.import_path(path)

    def ask_pdf_page(self, path) -> int | None:
        """Seite eines mehrseitigen PDFs wählen (0-basiert); None = Abbruch.

        Ohne Dialog (``interactive=False``) oder bei einer Seite: erste Seite.
        """
        if not self.interactive:
            return 0
        from .pdf import page_count
        try:
            n = page_count(path)
        except ValueError:
            return 0  # Fehler meldet der eigentliche Import
        if n <= 1:
            return 0
        page, ok = QInputDialog.getInt(self.window, "PDF-Seite",
                                       f"Welche Seite importieren? (1–{n})", 1, 1, n)
        return page - 1 if ok else None

    def import_path(self, path, drop: tuple[float, float] | None = None,
                    page: int | None = None) -> list[str]:
        """Datei importieren; gibt die neuen Objekt-IDs zurück (leer bei Fehler).

        ``page``: PDF-Seite (0-basiert); ``None`` = bei mehrseitigen PDFs fragen.
        """
        doc = self.editor.document
        layer = doc.active_layer
        if layer is None:
            self._error("Import nicht möglich", "Keine aktive Ebene")
            return []
        if layer.locked:
            self._error("Import nicht möglich", f"Ebene „{layer.name}“ ist gesperrt")
            return []
        if Path(path).suffix.lower() == ".pdf" and page is None:
            page = self.ask_pdf_page(path)
            if page is None:
                return []
        try:
            res = import_file(path, layer.id, drop, page or 0)
        except (OSError, ValueError) as exc:
            self._error("Import fehlgeschlagen", str(exc))
            return []
        self.last_error = None
        self.editor.undo_stack.push(AddShapesCommand(doc, res.shapes, "Importieren"))
        ids = [s.id for s in res.shapes]
        self.editor.set_selection(ids)
        self.editor.notify(res.summary(Path(path).name))
        return ids

    # ---------------------------------------------------------------- Drop
    @staticmethod
    def _paths(mime) -> list[Path]:
        if not mime.hasUrls():
            return []
        return [Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()]

    @staticmethod
    def _accepted(p: Path) -> bool:
        name = p.name.lower()
        return name.endswith(FILE_SUFFIX) or p.suffix.lower() in ALL_SUFFIXES

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        et = event.type()
        if et in (QEvent.DragEnter, QEvent.DragMove):
            if any(self._accepted(p) for p in self._paths(event.mimeData())):
                event.acceptProposedAction()
                return True
            return False
        if et == QEvent.Drop:
            paths = [p for p in self._paths(event.mimeData()) if self._accepted(p)]
            if not paths:
                return False
            pos = event.position() if hasattr(event, "position") else QPointF(event.pos())
            sp = self.editor.view.mapToScene(pos.toPoint())
            event.acceptProposedAction()
            self.drop_paths(paths, (sp.x(), sp.y()))
            return True
        return False

    def drop_paths(self, paths, drop: tuple[float, float] | None) -> None:
        """Abgelegte Dateien: Projekt öffnen oder importieren (mehrere versetzt)."""
        project = [p for p in paths if Path(p).name.lower().endswith(FILE_SUFFIX)]
        if project:
            if self.editor.confirm_discard():
                try:
                    self.editor.load_file(project[0])
                except (OSError, ValueError, KeyError) as exc:
                    self._error("Öffnen fehlgeschlagen", str(exc))
            return
        for i, p in enumerate(paths):
            d = None if drop is None else (drop[0] + 10 * i, drop[1] + 10 * i)
            self.import_path(p, d)

    # ---------------------------------------------------------------- Bild
    def _selected_image(self) -> str | None:
        doc = self.editor.document
        imgs = [i for i in self.editor.selection if doc.has_shape(i) and doc.shape(i).kind == "image"]
        return imgs[0] if len(imgs) == 1 else None

    def _update_image_action(self) -> None:
        has_image = self._selected_image() is not None
        self.image_action.setEnabled(has_image)
        self.trace_action.setEnabled(has_image)

    def edit_image_settings(self, shape_id: str | None = None,
                            settings: ImageSettings | None = None) -> bool:
        """Dialog öffnen (oder ``settings`` direkt setzen); True bei Änderung."""
        shape_id = shape_id or self._selected_image()
        doc = self.editor.document
        if not shape_id or not doc.has_shape(shape_id) or doc.shape(shape_id).kind != "image":
            self.editor.notify("Bitte genau ein Bild auswählen")
            return False
        sh = doc.shape(shape_id)
        old = sh.image.settings
        if settings is None:
            dlg = ImageSettingsDialog(old, sh.geom.w, sh.image.px_width, self.window)
            if dlg.exec() != QDialog.Accepted:
                return False
            settings = dlg.settings()
        settings = settings.normalized()
        if settings == old:
            return False
        self.editor.undo_stack.push(SetImageSettingsCommand(doc, shape_id, old, settings))
        self.editor.notify("Bildeinstellungen übernommen")
        return True

    # ---------------------------------------------------------------- Nachzeichnen
    def trace_image(self, shape_id: str | None = None, settings=None,
                    delete_image: bool | None = None) -> list[str]:
        """Bild → Vektorkonturen (Dialog, oder direkt mit ``settings``).

        Die Konturen landen deckungsgleich in der aktiven Ebene; ein
        Rückgängig-Schritt (inkl. Löschen des Bildes, falls gewählt).
        Gibt die neuen Objekt-IDs zurück.
        """
        from .trace import trace_to_shapes

        shape_id = shape_id or self._selected_image()
        doc = self.editor.document
        if not shape_id or not doc.has_shape(shape_id) or doc.shape(shape_id).kind != "image":
            self.editor.notify("Bitte genau ein Bild auswählen")
            return []
        layer = doc.active_layer
        if layer is None or layer.locked:
            self._error("Nachzeichnen nicht möglich",
                        "Keine aktive Ebene" if layer is None else f"Ebene „{layer.name}“ ist gesperrt")
            return []
        sh = doc.shape(shape_id)
        if settings is None:
            from .trace_qt import TraceDialog
            try:
                dlg = TraceDialog(sh, parent=self.window)
            except ValueError as exc:
                self._error("Nachzeichnen fehlgeschlagen", str(exc))
                return []
            if dlg.exec() != QDialog.Accepted:
                return []
            settings = dlg.settings()
            if delete_image is None:
                delete_image = dlg.delete_image.isChecked()
        QApplication.setOverrideCursor(Qt.WaitCursor)   # Laufzeit begrenzt (TIME_LIMIT_S)
        try:
            shapes = trace_to_shapes(sh, settings, layer.id)
        except ValueError as exc:
            shapes, error = None, str(exc)
        finally:
            QApplication.restoreOverrideCursor()
        if shapes is None:
            self._error("Nachzeichnen fehlgeschlagen", error)
            return []
        if not shapes:
            self._error("Nachzeichnen", "Keine Konturen gefunden – Schwellwert oder Invertieren ändern")
            return []
        self.last_error = None
        stack = self.editor.undo_stack
        stack.beginMacro("Bild nachzeichnen")
        stack.push(AddShapesCommand(doc, shapes, "Bild nachzeichnen"))
        if delete_image and doc.has_shape(shape_id):
            stack.push(DeleteShapesCommand(doc, [shape_id]))
        stack.endMacro()
        ids = [s.id for s in shapes]
        self.editor.set_selection(ids)
        self.editor.notify(f"Nachgezeichnet: {len(ids)} Kontur(en) in Ebene „{layer.name}“")
        return ids


def install_import(window, interactive: bool = True) -> ImportTools:
    tools = ImportTools(window, interactive)
    window.import_tools = tools
    return tools
