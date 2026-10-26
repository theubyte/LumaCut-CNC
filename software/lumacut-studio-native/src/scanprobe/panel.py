"""Scan-&-Probe-Panel für LumaCut Studio (PySide6).

Bedienung (rechte Spalte im Hauptfenster):

1. Quelle wählen: *Simulation* (ohne Hardware) oder *Maschine (Pi-API)*
   mit Kamera-Quelle und ``camera.json``.
2. **Scan starten** – Kachel-Scan bei fester Höhe, Stitching, Objekterkennung.
   Das Mosaik wird Hintergrund der Arbeitsfläche, erkannte Werkstücke
   erscheinen als gestrichelte Hilfsformen und in der Liste.
3. **Auto-Probe** – probt die angehakten Werkstücke (optional nur die unter
   dem Design) und legt die Höhenkarte als Überlagerung auf den Canvas.
   **Scan + Probe** macht beides in einem Durchlauf (``workflow.run``).
4. Pause / Fortsetzen / Abbrechen steuern den laufenden Schritt (RunControl).

Die Hilfsformen sind reine Szenen-Items: Sie gehören nicht zum Dokument,
werden nicht exportiert und nicht gelasert.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QImage, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGraphicsItem,
    QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsSimpleTextItem, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from . import adapters
from .calibration import CameraCalibration
from .detection import DetectedObject
from .focus_export import FocusExport, compensate_for_export
from .geometry import DEFAULT_LIMITS, Polygon, Rect
from .heatmap import heatmap_rgba
from .heightmap import HeightMapSet
from .probe_plan import ProbeArea, ProbeSettings, areas_from_design_bounds, areas_from_objects
from .qt_bridge import ScanProbeWorker
from .stitch import Mosaic
from .workflow import ScanProbeWorkflow

# Arbeitsfläche (Canvas) = Maschine X30–390 / Y30–370 (siehe lumacut_canvas.workarea)
try:
    from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, from_machine, to_machine
except ImportError:  # pragma: no cover - Panel ohne Canvas-Paket
    WORK_WIDTH_MM, WORK_HEIGHT_MM = 360.0, 340.0

    def to_machine(x, y):
        return x + 30.0, y + 30.0

    def from_machine(x, y):
        return x - 30.0, y - 30.0

MODE_SIM = "sim"
MODE_PI = "pi"
PHASES = {"scan": "Scan", "stitch": "Stitching", "probe": "Proben", "reuse": "Kontrollmessung",
          "detect": "Erkennung"}
KINDS = {"rectangle": "Rechteck", "circle": "Kreis", "polygon": "Polygon"}
TAP_MM = 3.0        # kleiner aufgezogener Bereich = Antippen (Werkstück an/aus)
MANUAL_PAD_MM = 3.0  # Rand um Bereiche aus Canvas-Formen (wie bei der Design-Box)
Z_OVERLAY = 5e8  # über allen Ebenen (Rang × 1e6, auch bei vielen Ebenen z. B. Materialtest), unter Auswahlrahmen (1e9)


def work_rect_machine() -> Rect:
    x0, y0 = to_machine(0.0, 0.0)
    x1, y1 = to_machine(WORK_WIDTH_MM, WORK_HEIGHT_MM)
    return Rect(x0, y0, x1, y1)


def mosaic_to_work_image(mosaic: Mosaic, mm_per_px: float = 0.5) -> np.ndarray:
    """Mosaik auf die sichtbare Arbeitsfläche umrechnen (BGR, 360 × 340 mm)."""
    wr = work_rect_machine()
    w, h = int(round(wr.width / mm_per_px)), int(round(wr.height / mm_per_px))
    s = mm_per_px / mosaic.mm_per_px
    # Zielpixel (c, r) -> Maschine wr.xmin + (c + .5) * mm_per_px -> Mosaikpixel
    ox = (wr.xmin - mosaic.origin_mm[0]) / mosaic.mm_per_px - 0.5 + 0.5 * s
    oy = (wr.ymin - mosaic.origin_mm[1]) / mosaic.mm_per_px - 0.5 + 0.5 * s
    m = np.array([[s, 0, ox], [0, s, oy]], np.float64)
    interp = cv2.INTER_AREA if s > 1 else cv2.INTER_LINEAR
    return cv2.warpAffine(mosaic.image, m, (w, h), flags=cv2.WARP_INVERSE_MAP | interp,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))


def to_qimage(img: np.ndarray) -> QImage:
    """BGR/BGRA/Grau (numpy) -> eigenständige QImage-Kopie."""
    img = np.ascontiguousarray(img)
    if img.ndim == 2:
        q = QImage(img.data, img.shape[1], img.shape[0], img.strides[0], QImage.Format.Format_Grayscale8)
    elif img.shape[2] == 4:
        q = QImage(img.data, img.shape[1], img.shape[0], img.strides[0], QImage.Format.Format_RGBA8888)
    else:
        rgb = np.ascontiguousarray(img[..., ::-1])
        q = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888)
        return q.copy()
    return q.copy()


def describe(obj: DetectedObject) -> str:
    kind = KINDS.get(obj.kind, obj.kind)
    if obj.kind == "circle" and obj.radius_mm:
        size = f"Ø {2 * obj.radius_mm:.0f} mm"
    elif obj.size_mm:
        size = f"{obj.size_mm[0]:.0f} × {obj.size_mm[1]:.0f} mm"
    else:
        size = f"{obj.bounds.width:.0f} × {obj.bounds.height:.0f} mm"
    return f"{obj.id}: {kind} {size} ({obj.confidence * 100:.0f} %)"


def fmt_eta(seconds: float) -> str:
    s = int(max(0, round(seconds)))
    return f"{s // 60}:{s % 60:02d} min" if s >= 60 else f"{s} s"


class CanvasOverlay:
    """Hintergrund, Hilfsformen und Höhenkarte auf dem Canvas des Editors."""

    def __init__(self, canvas: Any):
        self.canvas = canvas
        self.object_items: list[QGraphicsItem] = []
        self.manual_items: list[QGraphicsItem] = []
        self.heat_item: Optional[QGraphicsPixmapItem] = None
        self.backdrop: Optional[QImage] = None

    @property
    def scene(self):
        return getattr(self.canvas, "scene", None)

    # --- Hintergrund ----------------------------------------------------
    def set_mosaic(self, mosaic: Optional[Mosaic], visible: bool = True) -> None:
        self.backdrop = None if mosaic is None else to_qimage(mosaic_to_work_image(mosaic))
        self.show_mosaic(visible)

    def show_mosaic(self, visible: bool) -> None:
        if hasattr(self.canvas, "set_backdrop"):
            self.canvas.set_backdrop(self.backdrop if visible else None)

    # --- Hilfsformen ----------------------------------------------------
    def set_objects(self, objects: list[DetectedObject], visible: bool = True) -> None:
        self.clear_objects()
        scene = self.scene
        if scene is None:
            return
        pen = QPen(QColor("#22d3ee"), 1.5, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        for obj in objects:
            path = QPainterPath()
            pts = [QPointF(*from_machine(x, y)) for x, y in obj.polygon.points]
            path.moveTo(pts[0])
            for p in pts[1:]:
                path.lineTo(p)
            path.closeSubpath()
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setBrush(QBrush(QColor(34, 211, 238, 28)))
            item.setZValue(Z_OVERLAY)
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            item.setData(0, obj.id)
            item.setToolTip(describe(obj))
            label = QGraphicsSimpleTextItem(obj.id)
            label.setBrush(QBrush(QColor("#22d3ee")))
            label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            label.setPos(QPointF(*from_machine(obj.bounds.xmin, obj.bounds.ymin)))
            label.setZValue(Z_OVERLAY + 1)
            label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            for it in (item, label):
                it.setVisible(visible)
                scene.addItem(it)
                self.object_items.append(it)

    def show_objects(self, visible: bool) -> None:
        for it in self.object_items + self.manual_items:
            it.setVisible(visible)

    def mark_objects(self, checked_ids: set[str]) -> None:
        """Angehakte Werkstücke gefüllt, nicht angehakte nur gestrichelt."""
        for it in self.object_items:
            if isinstance(it, QGraphicsPathItem):
                on = it.data(0) in checked_ids
                it.setBrush(QBrush(QColor(34, 211, 238, 28 if on else 0)))
                pen = it.pen()
                pen.setStyle(Qt.PenStyle.DashLine if on else Qt.PenStyle.DotLine)
                it.setPen(pen)

    def set_manual(self, areas: list[ProbeArea], visible: bool = True) -> None:
        """Manuell markierte Probe-Bereiche (orange, nicht anklickbar)."""
        for it in self.manual_items:
            if it.scene() is not None:
                it.scene().removeItem(it)
        self.manual_items = []
        scene = self.scene
        if scene is None:
            return
        pen = QPen(QColor("#f59e0b"), 1.5, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        for area in areas:
            pts = [QPointF(*from_machine(x, y)) for x, y in area.polygon.points]
            path = QPainterPath()
            path.moveTo(pts[0])
            for p in pts[1:]:
                path.lineTo(p)
            path.closeSubpath()
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setBrush(QBrush(QColor(245, 158, 11, 24)))
            item.setZValue(Z_OVERLAY)
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            item.setData(0, area.id)
            item.setToolTip(f"Manueller Probe-Bereich {area.id}")
            item.setVisible(visible)
            scene.addItem(item)
            self.manual_items.append(item)

    def clear_objects(self) -> None:
        for it in self.object_items:
            if it.scene() is not None:
                it.scene().removeItem(it)
        self.object_items = []

    # --- Höhenkarte -----------------------------------------------------
    def set_heatmap(self, maps: Optional[HeightMapSet], visible: bool = True,
                    px_per_mm: float = 2.0) -> Optional[tuple[float, float]]:
        self.clear_heatmap()
        scene = self.scene
        if maps is None or not maps.maps or scene is None:
            return None
        wr = work_rect_machine()
        rgba, lo, hi = heatmap_rgba(maps, wr, px_per_mm)
        item = QGraphicsPixmapItem(QPixmap.fromImage(to_qimage(rgba)))
        item.setScale(1.0 / px_per_mm)
        item.setPos(0.0, 0.0)                 # Arbeitsflächen-Ursprung = wr.xmin/ymin
        item.setZValue(Z_OVERLAY - 1)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        item.setVisible(visible)
        scene.addItem(item)
        self.heat_item = item
        return lo, hi

    def show_heatmap(self, visible: bool) -> None:
        if self.heat_item is not None:
            self.heat_item.setVisible(visible)

    def clear_heatmap(self) -> None:
        if self.heat_item is not None and self.heat_item.scene() is not None:
            self.heat_item.scene().removeItem(self.heat_item)
        self.heat_item = None

    def clear(self) -> None:
        self.clear_objects()
        self.set_manual([])
        self.clear_heatmap()
        self.backdrop = None
        self.show_mosaic(False)


class ScanPanel(QWidget):
    """Bedienfeld für Kachel-Scan, Objekterkennung und Auto-Probe."""

    statusMessage = Signal(str)  # noqa: N815
    busyChanged = Signal(bool)  # noqa: N815
    resultReady = Signal(str)  # noqa: N815 - "scan" | "probe" | "full"
    areasChanged = Signal()  # noqa: N815 - Markierung (Werkstücke/Design/manuell) geändert

    def __init__(self, canvas: Any = None, client_provider: Optional[Callable[[], Any]] = None,
                 parent: Optional[QWidget] = None, *, sim_delay_s: float = 0.0, ask: bool = True):
        super().__init__(parent)
        self.canvas = canvas
        self.overlay = CanvasOverlay(canvas)
        self.client_provider = client_provider
        self.sim_delay_s = sim_delay_s
        self.ask = ask
        self.calibration: Optional[CameraCalibration] = None
        self.calibration_path: Optional[Path] = None
        self.hardware: Optional[adapters.Hardware] = None
        self.workflow: Optional[ScanProbeWorkflow] = None
        self.worker: Optional[ScanProbeWorker] = None
        self.mosaic: Optional[Mosaic] = None
        self.objects: list[DetectedObject] = []
        self.maps: Optional[HeightMapSet] = None
        self.last_focus_export: Optional[FocusExport] = None
        self.last_notes: list[str] = []
        self.last_error = ""
        self._kind = ""
        self.manual_areas: list[ProbeArea] = []
        self._manual_seq = 0
        self._marking = False
        self._build()
        if canvas is not None and hasattr(canvas, "roiSelected"):
            canvas.roiSelected.connect(self._on_roi)
            canvas.roiCancelled.connect(self._on_roi_cancelled)
        self._update_enabled()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Simulation (ohne Hardware)", MODE_SIM)
        self.mode_combo.addItem("Maschine (Pi-API + Kamera)", MODE_PI)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        form.addRow("Quelle", self.mode_combo)
        self.camera_edit = QLineEdit("0")
        self.camera_edit.setPlaceholderText("USB-Index oder Stream-URL")
        self.camera_edit.setToolTip("z. B. 0 für die erste USB-Kamera oder http://lumacut.local:8081/stream")
        form.addRow("Kamera", self.camera_edit)
        cal_row = QHBoxLayout()
        self.cal_label = QLabel("Standardwerte (unkalibriert)")
        self.cal_label.setWordWrap(True)
        self.cal_button = QPushButton("Laden …")
        self.cal_button.clicked.connect(self._choose_calibration)
        cal_row.addWidget(self.cal_label, 1)
        cal_row.addWidget(self.cal_button)
        form.addRow("Kalibrierung", cal_row)
        self.spacing_spin = QDoubleSpinBox()
        self.spacing_spin.setRange(5.0, 60.0)
        self.spacing_spin.setValue(15.0)
        self.spacing_spin.setSuffix(" mm")
        self.spacing_spin.setDecimals(1)
        form.addRow("Rasterabstand", self.spacing_spin)
        lay.addLayout(form)
        self.design_only = QCheckBox("Nur Werkstücke unter dem Design proben")
        self.design_only.setChecked(True)
        self.design_only.toggled.connect(lambda *_: self._areas_changed())
        lay.addWidget(self.design_only)

        row = QHBoxLayout()
        self.scan_button = QPushButton("Scan starten")
        self.scan_button.setObjectName("primary")
        self.scan_button.clicked.connect(self.start_scan)
        self.probe_button = QPushButton("Auto-Probe")
        self.probe_button.clicked.connect(self.start_probe)
        row.addWidget(self.scan_button)
        row.addWidget(self.probe_button)
        lay.addLayout(row)
        self.full_button = QPushButton("Scan + Probe (komplett)")
        self.full_button.clicked.connect(self.start_full)
        lay.addWidget(self.full_button)

        row = QHBoxLayout()
        self.pause_button = QPushButton("Pause")
        self.pause_button.setCheckable(True)
        self.pause_button.toggled.connect(self._pause_toggled)
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.setObjectName("danger")
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.pause_button)
        row.addWidget(self.cancel_button)
        lay.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("%v / %m")
        lay.addWidget(self.progress)
        self.phase_label = QLabel("Bereit")
        self.phase_label.setWordWrap(True)
        lay.addWidget(self.phase_label)
        self.estimate_label = QLabel("")
        self.estimate_label.setWordWrap(True)
        lay.addWidget(self.estimate_label)
        self.preview = QLabel()
        self.preview.setFixedHeight(90)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setVisible(False)
        lay.addWidget(self.preview)

        lay.addWidget(QLabel("Erkannte Werkstücke"))
        self.objects_list = QListWidget()
        self.objects_list.setMaximumHeight(120)
        self.objects_list.itemChanged.connect(self._objects_checked)
        lay.addWidget(self.objects_list)
        row = QHBoxLayout()
        self.mark_button = QPushButton("Auf Canvas markieren")
        self.mark_button.setToolTip(
            "Bereich aufziehen: umschlossene Werkstücke werden angehakt, sonst wird der Bereich "
            "selbst geprobt. Ein kurzer Zug (< 3 mm) auf ein Werkstück schaltet es an/aus.")
        self.mark_button.clicked.connect(self.start_marking)
        self.selection_button = QPushButton("Auswahl als Bereich")
        self.selection_button.setToolTip("Umriss der auf dem Canvas ausgewählten Objekte proben")
        self.selection_button.clicked.connect(self.add_selection_areas)
        row.addWidget(self.mark_button)
        row.addWidget(self.selection_button)
        lay.addLayout(row)
        self.areas_label = QLabel("")
        self.areas_label.setWordWrap(True)
        self.areas_label.setStyleSheet("color: #93a1b5;")
        lay.addWidget(self.areas_label)
        self.clear_marks_button = QPushButton("Manuelle Bereiche löschen")
        self.clear_marks_button.clicked.connect(self.clear_manual_areas)
        lay.addWidget(self.clear_marks_button)

        self.show_mosaic = QCheckBox("Scanbild als Hintergrund")
        self.show_mosaic.setChecked(True)
        self.show_mosaic.toggled.connect(self.overlay.show_mosaic)
        self.show_objects = QCheckBox("Werkstück-Umrisse anzeigen")
        self.show_objects.setChecked(True)
        self.show_objects.toggled.connect(self.overlay.show_objects)
        self.show_heatmap = QCheckBox("Höhenkarte anzeigen")
        self.show_heatmap.setChecked(True)
        self.show_heatmap.toggled.connect(self.overlay.show_heatmap)
        for cb in (self.show_mosaic, self.show_objects, self.show_heatmap):
            lay.addWidget(cb)
        self.heat_label = QLabel("Noch keine Höhenkarte")
        self.heat_label.setWordWrap(True)
        lay.addWidget(self.heat_label)

        row = QHBoxLayout()
        self.save_button = QPushButton("Höhenmesh speichern …")
        self.save_button.clicked.connect(self._save_dialog)
        self.load_button = QPushButton("Laden …")
        self.load_button.clicked.connect(self._load_dialog)
        row.addWidget(self.save_button)
        row.addWidget(self.load_button)
        lay.addLayout(row)
        self.reuse_check = QCheckBox("Geladenes Mesh nach Kontrollmessung wiederverwenden")
        self.reuse_check.setChecked(True)
        lay.addWidget(self.reuse_check)
        # Export mit Fokuskorrektur (unkorrigierter Export bleibt Standard)
        self.focus_check = QCheckBox("Fokuskorrektur anwenden (Höhenmesh)")
        self.focus_check.setChecked(False)
        self.focus_check.setToolTip(
            "Z je Segment aus dem Höhenmesh – gilt für „An Pi senden“ und „G-Code exportieren“.")
        lay.addWidget(self.focus_check)
        self.focus_hint = QLabel("")
        self.focus_hint.setWordWrap(True)
        self.focus_hint.setStyleSheet("color: #93a1b5;")
        lay.addWidget(self.focus_hint)
        self.export_button = QPushButton("G-Code exportieren …")
        self.export_button.setToolTip("Sichtbare Ebenen als Marlin-G-Code speichern "
                                      "(mit Fokuskorrektur, falls angehakt)")
        self.export_button.clicked.connect(self._export_dialog)
        lay.addWidget(self.export_button)
        self.clear_button = QPushButton("Scan-Anzeige leeren")
        self.clear_button.clicked.connect(self.clear)
        lay.addWidget(self.clear_button)
        self._mode_changed()

    # ------------------------------------------------------------ Zustand
    @property
    def mode(self) -> str:
        return self.mode_combo.currentData()

    def set_mode(self, mode: str) -> None:
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(mode))

    @property
    def busy(self) -> bool:
        return self.worker is not None

    def _mode_changed(self, *_):
        pi = self.mode == MODE_PI
        self.camera_edit.setEnabled(pi)
        self.hardware = None
        self.workflow = None
        self._update_estimate()

    def _update_enabled(self) -> None:
        busy = self.busy
        for w in (self.scan_button, self.full_button, self.mode_combo, self.camera_edit,
                  self.cal_button, self.spacing_spin, self.load_button, self.clear_button):
            w.setEnabled(not busy)
        self.camera_edit.setEnabled(not busy and self.mode == MODE_PI)
        self.probe_button.setEnabled(not busy and (bool(self.checked_objects()) or bool(self.manual_areas)
                                                   or bool(self.design_bounds())))
        for w in (self.mark_button, self.selection_button):
            w.setEnabled(not busy and self.canvas is not None)
        self.clear_marks_button.setEnabled(not busy and bool(self.manual_areas))
        self.save_button.setEnabled(not busy and self.maps is not None)
        has_maps = self.maps is not None and bool(self.maps.maps)
        if not has_maps:
            self.focus_check.setChecked(False)
        self.focus_check.setEnabled(not busy and has_maps)
        self.focus_hint.setText("" if has_maps else
                                "Fokuskorrektur: erst „Auto-Probe“ ausführen oder Höhenmesh laden.")
        self.export_button.setEnabled(not busy)
        self.pause_button.setEnabled(busy)
        self.cancel_button.setEnabled(busy)
        if not busy and self.pause_button.isChecked():
            self.pause_button.blockSignals(True)
            self.pause_button.setChecked(False)
            self.pause_button.setText("Pause")
            self.pause_button.blockSignals(False)

    def _notify(self, text: str) -> None:
        self.phase_label.setText(text)
        self.statusMessage.emit(text)

    # --------------------------------------------------------- Kalibrierung
    def load_calibration(self, path: str | Path) -> CameraCalibration:
        cal = CameraCalibration.load(path)
        self.calibration, self.calibration_path = cal, Path(path)
        self.cal_label.setText(f"{Path(path).name}: {cal.px_per_mm:.2f} px/mm @ Z{cal.scan_z:.0f}, "
                               f"{cal.image_width}×{cal.image_height}")
        self.hardware = None
        self.workflow = None
        self._update_estimate()
        return cal

    def _choose_calibration(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Kamera-Kalibrierung laden", "",
                                              "Kalibrierung (*.json)")
        if path:
            try:
                self.load_calibration(path)
            except Exception as exc:  # noqa: BLE001 - Meldung an den Nutzer
                self._error(f"Kalibrierung ungültig: {exc}")

    # ---------------------------------------------------------- Hardware
    def _build_hardware(self) -> adapters.Hardware:
        if self.mode == MODE_SIM:
            hw = adapters.simulated_setup(self.sim_delay_s)
            if self.calibration is not None:  # Simulation mit eigener Kalibrierung
                from .fakes import FakeCamera
                hw.calibration = self.calibration
                hw.camera = FakeCamera(hw.machine, hw.camera.bed, self.calibration)
            return hw
        client = self.client_provider() if self.client_provider else None
        if client is None:
            raise adapters.HardwareNotReady("Nicht mit dem Pi verbunden – unten unter „Maschine“ verbinden")
        if self.calibration is None:
            raise adapters.HardwareNotReady("Für echte Scans zuerst camera.json laden (siehe docs/KAMERA_KALIBRIERUNG.md)")
        return adapters.pi_setup(client, self.calibration, self.camera_edit.text().strip())

    def _ensure_workflow(self, need_camera: bool) -> ScanProbeWorkflow:
        if self.hardware is None or self.workflow is None:
            self.hardware = self._build_hardware()
            self.workflow = ScanProbeWorkflow(
                self.hardware.machine, self.hardware.camera, self.hardware.probe,
                self.hardware.calibration, self._probe_settings(),
                settle_s=0.0 if self.hardware.simulated else 0.15)
        self.workflow.settings = self._probe_settings()
        if need_camera and self.hardware.camera is None:
            raise adapters.HardwareNotReady("Keine Kamera-Quelle angegeben")
        return self.workflow

    def _probe_settings(self) -> ProbeSettings:
        return ProbeSettings(spacing_mm=float(self.spacing_spin.value()))

    def _update_estimate(self) -> None:
        cal = self.calibration or adapters.default_calibration()
        try:
            from .tile_scan import plan_tiles
            plan = plan_tiles(DEFAULT_LIMITS.work_rect(), cal, 0.25)
            self.estimate_label.setText(f"Scan: {len(plan.tiles)} Kacheln bei Z{cal.scan_z:.0f}")
        except Exception:  # noqa: BLE001 - nur Info
            self.estimate_label.setText("")

    # ------------------------------------------------------------ Design
    def design_bounds(self) -> list[Rect]:
        """Bounding-Boxen der Formen auf sichtbaren Ebenen, in Maschinen-mm."""
        doc = getattr(self.canvas, "document", None)
        if doc is None:
            return []
        out = []
        for s in getattr(doc, "shapes", []):
            try:
                if not doc.layer(s.layer_id).visible:
                    continue
                b = s.bounds()
            except Exception:  # noqa: BLE001
                continue
            x0, y0 = to_machine(b.x, b.y)
            x1, y1 = to_machine(b.x + b.w, b.y + b.h)
            out.append(Rect(x0, y0, max(x1, x0 + 0.1), max(y1, y0 + 0.1)))
        return out

    def checked_objects(self) -> list[DetectedObject]:
        ids = {self.objects_list.item(i).data(Qt.ItemDataRole.UserRole)
               for i in range(self.objects_list.count())
               if self.objects_list.item(i).checkState() == Qt.CheckState.Checked}
        return [o for o in self.objects if o.id in ids]

    def probe_areas(self):
        """(Bereiche, Hinweise): angehakte Werkstücke bzw. Design-Bereiche plus
        manuell markierte Bereiche. Das Design dient nur als Rückfall, solange
        weder Werkstücke angehakt noch Bereiche markiert sind."""
        objs = self.checked_objects()
        manual = list(self.manual_areas)
        design = self.design_bounds() if self.design_only.isChecked() else []
        if design:
            areas, notes = areas_from_design_bounds(design, objs)
        elif objs:
            areas, notes = areas_from_objects(objs), []
        elif self.design_bounds() and not manual:
            areas, notes = areas_from_design_bounds(self.design_bounds(), [])
        else:
            areas, notes = [], []
        return list(areas) + manual, list(notes)

    # ------------------------------------------------------------ Markieren
    def start_marking(self) -> bool:
        """Nächsten Zug auf dem Canvas als Markierung auswerten (siehe :meth:`mark_rect`)."""
        if self.canvas is None or not hasattr(self.canvas, "request_roi") or self.busy:
            return False
        if getattr(self.canvas, "roi_pending", False) and not self._marking:
            self._error("Auf dem Canvas wird bereits ein Bereich aufgezogen.")
            return False
        self._marking = True
        self.canvas.request_roi("Probe-Bereich aufziehen oder Werkstück antippen (Esc bricht ab)")
        return True

    def _on_roi(self, x: float, y: float, w: float, h: float) -> None:
        if not self._marking:
            return  # Bereich gehört einem anderen Werkzeug
        self._marking = False
        if hasattr(self.canvas, "clear_roi"):
            self.canvas.clear_roi()  # eigene Anzeige über das Overlay
        x0, y0 = to_machine(x, y)
        x1, y1 = to_machine(x + w, y + h)
        self.mark_rect(Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))

    def _on_roi_cancelled(self) -> None:
        self._marking = False

    def mark_rect(self, r: Rect) -> str:
        """Markierung in Maschinen-mm auswerten.

        * Kleiner Bereich (< ``TAP_MM``, d. h. Antippen): Werkstück an dieser
          Stelle an-/abhaken.
        * Größerer Bereich: Werkstücke, deren Mitte darin liegt, werden angehakt;
          liegt keines darin, wird der Bereich selbst ein manueller Probe-Bereich.

        Rückgabe: ``"toggle"``, ``"objects"``, ``"manual"`` oder ``""`` (nichts).
        """
        if r.width < TAP_MM and r.height < TAP_MM:
            cx, cy = r.center
            hits = [o for o in self.objects if o.polygon.contains(cx, cy)]
            if not hits:
                self._notify("Kein erkanntes Werkstück an dieser Stelle – Bereich größer aufziehen.")
                return ""
            self._set_checked({o.id for o in hits}, toggle=True)
            self._notify("Werkstück " + ", ".join(o.id for o in hits) + " umgeschaltet.")
            return "toggle"
        inside = [o for o in self.objects if r.contains(*o.bounds.center)]
        if inside:
            self._set_checked({o.id for o in inside})
            self._notify(f"{len(inside)} Werkstück(e) markiert.")
            return "objects"
        self.add_manual_area(r.to_polygon(), kind="rectangle")
        return "manual"

    def add_manual_area(self, polygon: Polygon, kind: str = "polygon") -> Optional[ProbeArea]:
        """Manuellen Probe-Bereich (Maschinen-mm) anlegen, auf die Arbeitsfläche begrenzt."""
        wr = work_rect_machine()
        b = polygon.bounds
        if wr.intersect(b) is None:
            self._error("Bereich liegt außerhalb der Arbeitsfläche.")
            return None
        if b.xmin < wr.xmin or b.ymin < wr.ymin or b.xmax > wr.xmax or b.ymax > wr.ymax:
            pts = [(min(max(x, wr.xmin), wr.xmax), min(max(y, wr.ymin), wr.ymax)) for x, y in polygon.points]
            try:
                polygon = Polygon(pts)
            except ValueError:
                return None
            if polygon.area < 1.0:
                return None
        self._manual_seq += 1
        area = ProbeArea(f"m{self._manual_seq}", polygon, kind, "manual")
        self.manual_areas.append(area)
        self._manual_changed()
        self._notify(f"Probe-Bereich {area.id} markiert "
                     f"({polygon.bounds.width:.0f} × {polygon.bounds.height:.0f} mm).")
        return area

    def add_selection_areas(self) -> int:
        """Ausgewählte Canvas-Objekte als Probe-Bereiche (Umriss + Rand)."""
        doc = getattr(self.canvas, "document", None)
        ids = [i for i in getattr(self.canvas, "selection", []) if doc is not None and doc.has_shape(i)]
        if not ids:
            self._error("Keine Objekte auf dem Canvas ausgewählt.")
            return 0
        n = 0
        for sid in ids:
            poly = _shape_area_polygon(doc.shape(sid))
            if poly is not None and self.add_manual_area(poly) is not None:
                n += 1
        return n

    def clear_manual_areas(self) -> None:
        self.manual_areas = []
        self._manual_changed()

    def _manual_changed(self) -> None:
        self.overlay.set_manual(self.manual_areas, self.show_objects.isChecked())
        self._areas_changed()

    def _set_checked(self, ids: set[str], toggle: bool = False) -> None:
        self.objects_list.blockSignals(True)
        for i in range(self.objects_list.count()):
            item = self.objects_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) in ids:
                on = item.checkState() != Qt.CheckState.Checked if toggle else True
                item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.objects_list.blockSignals(False)
        self._objects_checked()

    def _objects_checked(self, *_):
        self.overlay.mark_objects({o.id for o in self.checked_objects()})
        self._areas_changed()

    def _areas_changed(self) -> None:
        areas, _notes = self.probe_areas()
        manual = len(self.manual_areas)
        self.areas_label.setText(
            f"Zu proben: {len(areas)} Bereich(e)" + (f", davon {manual} manuell" if manual else "")
            if areas else "Noch keine Probe-Bereiche markiert.")
        self._update_enabled()
        self.areasChanged.emit()

    # ------------------------------------------------------------ Aktionen
    def start_scan(self) -> bool:
        def task(wf: ScanProbeWorkflow):
            mosaic = wf.scan()
            wf.control.checkpoint()
            return {"mosaic": mosaic, "objects": wf.detect(mosaic)}
        return self._start("scan", task, need_camera=True)

    def start_probe(self) -> bool:
        areas, notes = self.probe_areas()
        if not areas:
            self._error("Keine Bereiche zum Proben – erst scannen oder ein Design anlegen.")
            return False
        mosaic = self.mosaic

        def task(wf: ScanProbeWorkflow):
            start = _machine_xy(wf.machine)
            job = wf.plan_probe(areas, start)
            res = wf.probe_areas(job, start, mosaic)
            if mosaic is not None and res.maps is not None and res.maps.maps:
                res.maps.add_fingerprints(mosaic)  # für die Prüfung beim Export
            return {"job": job, "probe": res, "notes": notes + job.warnings}
        return self._start("probe", task, need_camera=False)

    def start_full(self) -> bool:
        saved = self.maps if (self.maps is not None and self.reuse_check.isChecked()) else None
        design = self.design_bounds() if self.design_only.isChecked() else None
        manual = list(self.manual_areas)

        def task(wf: ScanProbeWorkflow):
            return {"result": wf.run(design_bounds=design or None, saved=saved, manual_areas=manual,
                                     start=_machine_xy(wf.machine))}
        return self._start("full", task, need_camera=True)

    def _start(self, kind: str, task, need_camera: bool) -> bool:
        if self.busy:
            return False
        try:
            wf = self._ensure_workflow(need_camera)
        except Exception as exc:  # noqa: BLE001
            self._error(str(exc))
            return False
        if self.hardware and not self.hardware.simulated and self.ask:
            text = {"scan": "Kopf fährt auf Scanhöhe und rastert die Arbeitsfläche ab.",
                    "probe": "Der Taster misst die gewählten Bereiche ab.",
                    "full": "Scan und anschließendes Abtasten."}[kind]
            if QMessageBox.question(self, "Maschine bewegen?",
                                    text + "\nArbeitsraum frei? Laser ist aus.") != QMessageBox.StandardButton.Yes:
                return False
        self._kind = kind
        self.last_error = ""
        self.worker = ScanProbeWorker(wf, self, task=task)
        self.worker.progress.connect(self._on_progress)
        self.worker.tile_captured.connect(self._on_tile)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_thread_done)
        self.progress.setRange(0, 0)
        self._notify({"scan": "Scan läuft …", "probe": "Proben läuft …", "full": "Scan + Probe läuft …"}[kind])
        self.worker.start()
        self.busyChanged.emit(True)
        self._update_enabled()
        return True

    @Slot(bool)
    def _pause_toggled(self, paused: bool) -> None:
        if self.worker is None:
            return
        if paused:
            self.worker.pause()
            self.pause_button.setText("Fortsetzen")
            self._notify("Pausiert – nach dem aktuellen Schritt angehalten")
        else:
            self.worker.resume()
            self.pause_button.setText("Pause")
            self._notify("Fortgesetzt")

    def pause(self) -> None:
        self.pause_button.setChecked(True)

    def resume(self) -> None:
        self.pause_button.setChecked(False)

    def cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self._notify("Abbruch angefordert …")

    def shutdown(self, timeout_ms: int = 5000) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(timeout_ms)
        cam = getattr(self.hardware, "camera", None)
        if cam is not None and hasattr(cam, "close"):
            cam.close()

    def wait(self, timeout_ms: int = 60000) -> bool:
        """Für Tests: auf das Ende des laufenden Schritts warten (inkl. Signale)."""
        from PySide6.QtCore import QCoreApplication, QElapsedTimer
        t = QElapsedTimer()
        t.start()
        while self.worker is not None and t.elapsed() < timeout_ms:
            QCoreApplication.processEvents()
            if self.worker is not None:
                self.worker.wait(20)
        QCoreApplication.processEvents()
        return self.worker is None

    # ------------------------------------------------------------ Signale
    @Slot(str, int, int, str, float)
    def _on_progress(self, phase: str, done: int, total: int, msg: str, eta: float) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(done, max(1, total)))
        text = f"{PHASES.get(phase, phase)}: {done}/{total}"
        if eta > 0:
            text += f" – noch ca. {fmt_eta(eta)}"
        if msg:
            text += f"\n{msg}"
        self.phase_label.setText(text)

    @Slot(object, object)
    def _on_tile(self, _tile, image) -> None:
        if image is None:
            return
        pix = QPixmap.fromImage(to_qimage(image))
        self.preview.setPixmap(pix.scaledToHeight(self.preview.height(), Qt.TransformationMode.FastTransformation))
        self.preview.setVisible(True)

    @Slot(object)
    def _on_finished(self, payload: dict) -> None:
        notes: list[str] = []
        if "result" in payload:  # komplett
            res = payload["result"]
            self.set_mosaic(res.mosaic)
            if res.objects or not res.reused:
                self.set_objects(res.objects)
            if res.maps is not None:
                self.set_maps(res.maps)
            notes = list(res.notes)
            done = "Höhenmesh wiederverwendet" if res.reused else (
                f"{len(res.areas)} Bereich(e) geprobt" if res.probe else "Kein Bereich geprobt")
            self._notify(f"Fertig: {len(res.objects)} Werkstück(e), {done}.")
        elif "mosaic" in payload:
            self.set_mosaic(payload["mosaic"])
            self.set_objects(payload["objects"])
            self._notify(f"Scan fertig: {len(self.objects)} Werkstück(e) erkannt.")
        elif "probe" in payload:
            res = payload["probe"]
            self.set_maps(res.maps)
            notes = list(payload.get("notes", []))
            if res.failures:
                notes.append(f"{len(res.failures)} Punkt(e) ohne Kontakt – interpoliert")
            self._notify(f"Proben fertig: {res.probes} Messungen in {res.duration_s:.0f} s.")
        self.last_notes = notes
        if notes:
            self.heat_label.setText(self.heat_label.text() + "\n" + "\n".join(notes))
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.resultReady.emit(self._kind)

    @Slot()
    def _on_cancelled(self) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self._notify("Abgebrochen.")

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self._error(message)

    @Slot()
    def _on_thread_done(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        self.busyChanged.emit(False)
        self._update_enabled()

    def _error(self, message: str) -> None:
        self.last_error = message
        self._notify(f"Fehler: {message}")

    # ------------------------------------------------------------ Ergebnisse
    def set_mosaic(self, mosaic: Optional[Mosaic]) -> None:
        self.mosaic = mosaic
        self.overlay.set_mosaic(mosaic, self.show_mosaic.isChecked())

    def set_objects(self, objects: list[DetectedObject]) -> None:
        self.objects = list(objects)
        self.objects_list.blockSignals(True)
        self.objects_list.clear()
        for o in self.objects:
            item = QListWidgetItem(describe(o))
            item.setData(Qt.ItemDataRole.UserRole, o.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.objects_list.addItem(item)
        self.objects_list.blockSignals(False)
        self.overlay.set_objects(self.objects, self.show_objects.isChecked())
        self._objects_checked()

    def set_maps(self, maps: Optional[HeightMapSet]) -> None:
        self.maps = maps
        rng = self.overlay.set_heatmap(maps, self.show_heatmap.isChecked())
        if maps is None or rng is None:
            self.heat_label.setText("Noch keine Höhenkarte")
        else:
            lines = [f"Höhenkarte: Z {rng[0]:.2f} … {rng[1]:.2f} mm (blau tief, rot hoch)"]
            for m in maps.maps:
                st = m.stats()
                lines.append(f"{m.area_id}: {m.measured_count} Punkte, Spanne {st.get('range', 0):.2f} mm")
            self.heat_label.setText("\n".join(lines))
        self._update_enabled()

    def save_maps(self, path: str | Path) -> None:
        if self.maps is None:
            raise ValueError("Keine Höhenkarte vorhanden")
        self.maps.save(path)

    def load_maps(self, path: str | Path) -> HeightMapSet:
        maps = HeightMapSet.load(path)
        self.set_maps(maps)
        return maps

    def _save_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Höhenmesh speichern", "hoehenmesh.json", "Höhenmesh (*.json)")
        if path:
            try:
                self.save_maps(path)
                self._notify(f"Gespeichert: {path}")
            except Exception as exc:  # noqa: BLE001
                self._error(str(exc))

    def _load_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Höhenmesh laden", "", "Höhenmesh (*.json)")
        if path:
            try:
                self.load_maps(path)
                self._notify(f"Geladen: {path}")
            except Exception as exc:  # noqa: BLE001
                self._error(f"Höhenmesh ungültig: {exc}")

    # ------------------------------------------------------ G-Code-Export
    def _pi_surface_z(self) -> Optional[float]:
        if self.mode != MODE_PI:
            return None
        client = self.client_provider() if self.client_provider else None
        if client is None:
            return None
        try:
            return client.status().workpiece_surface_z
        except Exception:  # noqa: BLE001 - nur Zusatzprüfung
            return None

    def compensate(self, gcode: str) -> FocusExport:
        """Fokuskorrektur mit allen Prüfungen (ohne Dialog)."""
        res = compensate_for_export(gcode, self.maps, mosaic=self.mosaic,
                                    pi_surface_z=self._pi_surface_z())
        self.last_focus_export = res
        return res

    def prepare_job_gcode(self, gcode: str) -> Optional[str]:
        """Hook für jeden G-Code-Export/Versand.

        Ohne Haken bei „Fokuskorrektur anwenden“ kommt ``gcode`` unverändert
        zurück. Mit Haken: korrigierter G-Code, oder ``None`` bei Fehler bzw.
        wenn Warnungen nicht bestätigt wurden.
        """
        self.last_focus_export = None
        if not self.focus_check.isChecked():
            return gcode
        res = self.compensate(gcode)
        if not res.ok:
            self._error(" ".join(res.errors))
            if self.ask:
                QMessageBox.critical(self, "Fokuskorrektur nicht möglich", res.summary())
            return None
        if res.warnings and self.ask:
            answer = QMessageBox.warning(
                self, "Fokuskorrektur – bitte prüfen", res.summary() + "\n\nTrotzdem fortfahren?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self._notify("Export abgebrochen (Fokuskorrektur).")
                return None
        r = res.report
        self._notify(f"Fokuskorrektur: Z {r.z_min:.2f} … {r.z_max:.2f} mm"
                     + (f", {len(res.warnings)} Warnung(en)" if res.warnings else ""))
        return res.gcode

    def _job_gcode(self) -> str:
        """Gleicher G-Code wie „An Pi senden“ (mit Schnittplaner, falls vorhanden)."""
        try:
            from lumacut_job.planner import optimized_document_gcode
        except ImportError:  # pragma: no cover - ältere Studio-Version ohne Planer
            from lumacut_canvas.gcode import document_to_gcode as optimized_document_gcode
        return optimized_document_gcode(self.canvas.document)

    def export_gcode(self, path: str | Path) -> bool:
        """Canvas → Marlin-G-Code (ggf. fokuskorrigiert) → Datei."""
        try:
            gcode = self._job_gcode()
        except ValueError as exc:
            self._error(f"Export nicht möglich: {exc}")
            return False
        out = self.prepare_job_gcode(gcode)
        if out is None:
            return False
        Path(path).write_text(out, encoding="utf-8")
        self._notify(f"G-Code gespeichert: {Path(path).name}"
                     + (" (fokuskorrigiert)" if self.last_focus_export else ""))
        return True

    def _export_dialog(self) -> None:
        name = "auftrag_fokus.gcode" if self.focus_check.isChecked() else "auftrag.gcode"
        path, _ = QFileDialog.getSaveFileName(self, "G-Code exportieren", name, "G-Code (*.gcode *.nc)")
        if path:
            self.export_gcode(path)

    def clear(self) -> None:
        self.mosaic, self.objects, self.maps = None, [], None
        self.manual_areas = []
        self.objects_list.clear()
        self.overlay.clear()
        self._areas_changed()
        self.heat_label.setText("Noch keine Höhenkarte")
        self.preview.setVisible(False)
        self._update_enabled()


def _shape_area_polygon(shape) -> Optional[Polygon]:
    """Probe-Bereich (Maschinen-mm) für eine Canvas-Form: gedrehte Box + Rand;
    Polygone/Ellipsen mit ihrem Umriss (Rand über die Box-Erweiterung)."""
    try:
        b = shape.bounds()
    except Exception:  # noqa: BLE001
        return None
    pts: list[tuple[float, float]] = []
    if shape.kind in ("polygon", "ellipse"):
        try:
            from lumacut_canvas.shape_paths import shape_path
            poly = shape_path(shape).toFillPolygon()
            raw = [(p.x(), p.y()) for p in poly]
            step = max(1, len(raw) // 64)
            pts = _offset_outline(raw[::step], MANUAL_PAD_MM)
        except Exception:  # noqa: BLE001 - Rückfall auf die Box
            pts = []
    if len(pts) < 3:
        x0, y0, x1, y1 = b.x - MANUAL_PAD_MM, b.y - MANUAL_PAD_MM, b.x + b.w + MANUAL_PAD_MM, b.y + b.h + MANUAL_PAD_MM
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    try:
        return Polygon([to_machine(x, y) for x, y in pts])
    except ValueError:
        return None


def _offset_outline(pts: list[tuple[float, float]], pad: float) -> list[tuple[float, float]]:
    """Punkte radial vom Schwerpunkt um ``pad`` nach außen schieben (grob, für
    konvexe/sternförmige Umrisse ausreichend – das Proben-Raster ist ohnehin gröber)."""
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        return []
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    out = []
    for x, y in pts:
        d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
        f = (d + pad) / d if d > 1e-9 else 1.0
        out.append((cx + (x - cx) * f, cy + (y - cy) * f))
    return out


def _machine_xy(machine) -> tuple[float, float]:
    """Startpunkt für die Reihenfolgeplanung (Fake: aktuelle Position)."""
    x, y = getattr(machine, "x", None), getattr(machine, "y", None)
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return float(x), float(y)
    pos = getattr(machine, "pos", None)
    return (float(pos[0]), float(pos[1])) if pos else (0.0, 0.0)
