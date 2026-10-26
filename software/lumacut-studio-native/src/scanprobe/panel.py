"""Scan-&-Probe-Panel für LumaCut Studio (PySide6).

Hauptansicht (Anforderungen 2026-10-26 §3/§5): Pause/Abbrechen, Fortschritt und eine Statuszeile. Höhenmesh und
Fokuskorrektur laufen automatisch im Auftrag (``job_flow.OneClickJob``); es
gibt keinen Haken „Fokuskorrektur anwenden“ mehr. Den Knopf **Kamera-Scan** hat die
Canvas-Hauptansicht (``lumacut_canvas.main_view``); er ruft :meth:`ScanPanel.start_scan`.
Alles Weitere steckt unter **„Mehr …“**:

1. Quelle wählen: *Simulation* (ohne Hardware) oder *Maschine (Pi-API)*
   mit Kamera „Pi (Snapshot)“ oder „Lokal (USB/URL)“ und der Kalibrierung vom Pi.
   :meth:`ScanPanel.camera_scan` wechselt bei verbundenem Pi selbst auf *Maschine*.
2. **Kamera-Scan** – Kachel-Scan bei fester Höhe, Stitching, Objekterkennung.
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
    QToolButton, QVBoxLayout, QWidget,
)

from . import adapters
from .calibration import CameraCalibration
from . import pi_calibration
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
# Bildschirm-mm (Canvas, oben links) <-> Maschinen-mm. Vertrag (ZUSAMMENARBEIT_CLAUDE_GROK.md §2,
# Anforderungen 2026-10-26 §2.3, wie Android Work.toMachine/fromMachine):
#   maschine_x = 390 − x, maschine_y = 30 + y;  x = 390 − maschine_x, y = maschine_y − 30.
# Ansicht von der Tür (Drehung, keine Spiegelung des Motivs). Mosaik und Höhenkarte liegen
# als Maschinen-Raster vor; ihre Spalten werden für den Bildschirm umgekehrt (Spalte 0 = links
# = großes Maschinen-X).
# Umgerechnet wird nur über to_machine/from_machine; Rechtecke aus zwei Ecken
# deshalb immer mit min/max bilden (siehe :func:`machine_rect`).
try:
    from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, from_machine, to_machine
except ImportError:  # pragma: no cover - Panel ohne Canvas-Paket
    WORK_WIDTH_MM, WORK_HEIGHT_MM = 360.0, 340.0

    def to_machine(x, y):
        return 390.0 - x, y + 30.0

    def from_machine(x, y):
        return 390.0 - x, y - 30.0

MODE_SIM = "sim"
MODE_PI = "pi"
PHASES = {"scan": "Scan", "stitch": "Stitching", "probe": "Proben", "reuse": "Kontrollmessung",
          "detect": "Erkennung"}
KINDS = {"rectangle": "Rechteck", "circle": "Kreis", "polygon": "Polygon"}
TAP_MM = 3.0        # kleiner aufgezogener Bereich = Antippen (Werkstück an/aus)
MANUAL_PAD_MM = 3.0  # Rand um Bereiche aus Canvas-Formen (wie bei der Design-Box)
Z_OVERLAY = 5e8  # über allen Ebenen (Rang × 1e6, auch bei vielen Ebenen z. B. Materialtest), unter Auswahlrahmen (1e9)


def image_flip_x() -> bool:
    """Liegt das kleinste Maschinen-X rechts auf dem Bildschirm (Nullpunkt oben rechts)?

    Abgeleitet aus :func:`to_machine` statt aus einem eigenen Schalter, damit
    Bilder (Mosaik, Höhenkarte) immer zur Platzierung passen.
    """
    return to_machine(1.0, 0.0)[0] < to_machine(0.0, 0.0)[0]


def machine_rect(x0: float, y0: float, x1: float, y1: float) -> Rect:
    """Bildschirm-Rechteck (zwei Ecken) -> Maschinen-:class:`Rect` (Ecken sortiert)."""
    ax, ay = to_machine(x0, y0)
    bx, by = to_machine(x1, y1)
    return Rect(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))


def work_rect_machine() -> Rect:
    return machine_rect(0.0, 0.0, WORK_WIDTH_MM, WORK_HEIGHT_MM)


def machine_image_to_screen(img: np.ndarray) -> np.ndarray:
    """Bild in Maschinenrichtung (Spalte 0 = kleinstes X) für die Arbeitsfläche ausrichten."""
    return np.ascontiguousarray(img[:, ::-1]) if image_flip_x() else img


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
    out = cv2.warpAffine(mosaic.image, m, (w, h), flags=cv2.WARP_INVERSE_MAP | interp,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    return machine_image_to_screen(out)  # Spalte 0 = Bildschirm links


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
            lx = obj.bounds.xmax if image_flip_x() else obj.bounds.xmin  # linke Bildschirmkante
            label.setPos(QPointF(*from_machine(lx, obj.bounds.ymin)))
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
        rgba = machine_image_to_screen(rgba)  # wie das Mosaik (§2.3)
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
        # Liefert (G-Code, Planer-Hinweis) wie „An Pi senden“; None = JobTools des
        # Hauptfensters (``window().job_tools``, „Nur Auswahl“) oder reiner Planer.
        self.job_gcode_source: Optional[Callable[[], tuple[str, str]]] = None
        self.calibration: Optional[CameraCalibration] = None
        self.calibration_path: Optional[Path] = None
        # Stand auf dem Pi (Revision/Status); None = noch nicht gelesen/kein Pi
        self.pi_calibration: Optional[pi_calibration.PiCalibration] = None
        self.pi_calibration_error = ""
        self.calibration_dirty = False      # lokal geändert, noch nicht auf dem Pi
        # Fähigkeiten des Pi (moveto/Snapshot); None = noch nicht gelesen
        self.pi_features: Optional[adapters.PiFeatures] = None
        self._camera_kind_chosen = False    # Nutzer hat Pi/Lokal selbst gewählt
        self._mode_chosen = False           # Nutzer hat Simulation/Maschine selbst gewählt
        # Nur für Tests/Fehlersuche, nie in der Oberfläche: Auftrag ohne Fokuskorrektur
        self.skip_focus_correction = False
        # Laufender Ein-Klick-Auftrag (pause/resume/cancel), steuert Pause/Abbrechen mit
        self.external_run: Any = None
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
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        # --- Hauptansicht: Fortschritt; der Knopf „Kamera-Scan“ sitzt in der
        # Canvas-Hauptansicht (lumacut_canvas.main_view) ---
        row = QHBoxLayout()
        self.pause_button = QPushButton("Pause")
        self.pause_button.setCheckable(True)
        self.pause_button.toggled.connect(self._pause_toggled)
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.setObjectName("danger")
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.pause_button)
        row.addWidget(self.cancel_button)
        main.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("%v / %m")
        main.addWidget(self.progress)
        self.phase_label = QLabel("Bereit")
        self.phase_label.setWordWrap(True)
        main.addWidget(self.phase_label)
        self.preview = QLabel()
        self.preview.setFixedHeight(90)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setVisible(False)
        main.addWidget(self.preview)
        self.more_button = QToolButton()
        self.more_button.setText("Mehr …")
        self.more_button.setCheckable(True)
        self.more_button.setToolTip("Quelle, Kalibrierung, Werkstücke, Höhenmesh, Export")
        main.addWidget(self.more_button)

        # --- „Mehr …“: alles für Fachleute, standardmäßig verborgen ---
        self.advanced = QWidget()
        self.advanced.setVisible(False)
        self.more_button.toggled.connect(self.show_advanced)
        main.addWidget(self.advanced)
        lay = QVBoxLayout(self.advanced)
        lay.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Simulation (ohne Hardware)", MODE_SIM)
        self.mode_combo.addItem("Maschine (Pi-API + Kamera)", MODE_PI)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.mode_combo.activated.connect(self._mode_activated)
        form.addRow("Quelle", self.mode_combo)
        self.camera_kind_combo = QComboBox()
        self.camera_kind_combo.addItem("Pi (Snapshot)", adapters.CAMERA_PI)
        self.camera_kind_combo.addItem("Lokal (USB/URL)", adapters.CAMERA_LOCAL)
        self.camera_kind_combo.setCurrentIndex(1)   # Pi erst, wenn der Pi es meldet
        self.camera_kind_combo.setToolTip("Pi: Kopfkamera am Pi (GET /api/camera/snapshot); "
                                          "Lokal: Kamera am PC oder Stream-URL")
        self.camera_kind_combo.activated.connect(self._camera_kind_activated)
        self.camera_kind_combo.currentIndexChanged.connect(self._camera_kind_changed)
        self.camera_edit = QLineEdit("0")
        self.camera_edit.setPlaceholderText("USB-Index oder Stream-URL")
        self.camera_edit.setToolTip("z. B. 0 für die erste USB-Kamera oder http://lumacut.local:8081/stream")
        cam_row = QHBoxLayout()
        cam_row.addWidget(self.camera_kind_combo)
        cam_row.addWidget(self.camera_edit, 1)
        form.addRow("Kamera", cam_row)
        self.camera_note = QLabel("")
        self.camera_note.setWordWrap(True)
        form.addRow("", self.camera_note)
        cal_box = QVBoxLayout()
        self.cal_label = QLabel("Standardwerte (unkalibriert)")
        self.cal_label.setWordWrap(True)
        cal_box.addWidget(self.cal_label)
        cal_row = QHBoxLayout()
        self.pi_cal_button = QPushButton("Vom Pi laden")
        self.pi_cal_button.setToolTip("Kalibrierung gehört zur Maschine und liegt auf dem Pi")
        self.pi_cal_button.clicked.connect(lambda: self.refresh_pi_calibration(report=True))
        self.pi_save_button = QPushButton("Auf Pi speichern")
        self.pi_save_button.clicked.connect(lambda: self.save_calibration_to_pi())
        self.cal_button = QPushButton("Importieren …")
        self.cal_button.setToolTip("camera.json laden (Import, Simulation/offline)")
        self.cal_button.clicked.connect(self._choose_calibration)
        self.cal_export_button = QPushButton("Exportieren …")
        self.cal_export_button.clicked.connect(self._export_calibration_dialog)
        for b in (self.pi_cal_button, self.pi_save_button, self.cal_button, self.cal_export_button):
            cal_row.addWidget(b)
        cal_box.addLayout(cal_row)
        form.addRow("Kalibrierung", cal_box)
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
        self.probe_button = QPushButton("Nur Höhenmesh messen")
        self.probe_button.setToolTip("Für Fachleute – der Auftrag misst ohnehin automatisch")
        self.probe_button.clicked.connect(self.start_probe)
        self.full_button = QPushButton("Scan + Höhenmesh")
        self.full_button.clicked.connect(self.start_full)
        row.addWidget(self.probe_button)
        row.addWidget(self.full_button)
        lay.addLayout(row)
        self.estimate_label = QLabel("")
        self.estimate_label.setWordWrap(True)
        lay.addWidget(self.estimate_label)

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
        self.export_button = QPushButton("G-Code exportieren …")
        self.export_button.setToolTip("Sichtbare Ebenen als Marlin-G-Code speichern "
                                      "(fokuskorrigiert, sobald ein Höhenmesh vorliegt)")
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

    def _mode_activated(self, *_):
        self._mode_chosen = True

    @property
    def busy(self) -> bool:
        return self.worker is not None or self.external_run is not None

    def show_advanced(self, visible: bool = True) -> None:
        """„Mehr …“ auf-/zuklappen."""
        if self.more_button.isChecked() != visible:
            self.more_button.setChecked(visible)   # ruft show_advanced erneut
            return
        self.advanced.setVisible(visible)
        self.more_button.setText("Weniger" if visible else "Mehr …")

    def attach_external_run(self, run: Any, text: str = "Auftrag läuft …") -> None:
        """Ein-Klick-Auftrag übernimmt Pause/Abbrechen/Fortschritt dieses Panels."""
        self.external_run = run
        self.progress.setRange(0, 0)
        self._notify(text)
        self.busyChanged.emit(True)
        self._update_enabled()

    def detach_external_run(self) -> None:
        self.external_run = None
        self.busyChanged.emit(self.busy)
        self._update_enabled()

    def show_job_event(self, ev: dict) -> None:
        """``job_state``-Ereignis (``scanprobe.contract``) in Fortschritt/Status zeigen."""
        if ev.get("type") != "job_state":
            return
        step, steps, prog = ev.get("step"), ev.get("steps") or 5, ev.get("progress")
        if step:
            frac = (step - 1 + (prog if prog is not None else 0.0)) / steps
            self.progress.setRange(0, 100)
            self.progress.setValue(int(round(100 * frac)))
            self.progress.setFormat(f"Schritt {step}/{steps} · {ev.get('label', '')}")
        elif ev.get("state") in ("fertig", "fehler", "abgebrochen"):
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if ev["state"] == "fertig" else 0)
            self.progress.setFormat(ev.get("label", ""))
        text = f"{ev.get('label', '')}: {ev.get('message', '')}".strip(": ")
        if ev.get("state") == "fehler":
            self.last_error = ev.get("message", "")
            text = f"Fehler: {ev.get('message', '')}"
        self._notify(text)

    def camera_scan(self) -> bool:
        """Einstieg für den Knopf „Kamera-Scan“ (Canvas-Hauptansicht): wie
        :meth:`start_scan`, nimmt aber bei verbundenem Pi automatisch die Maschine."""
        self._auto_mode()
        return self.start_scan()

    def _auto_mode(self) -> None:
        """Bei verbundenem Pi automatisch die Maschine benutzen, solange der
        Nutzer unter „Mehr …“ nicht selbst gewählt hat."""
        if not self._mode_chosen and self.mode == MODE_SIM and self._client() is not None:
            self.set_mode(MODE_PI)

    @property
    def camera_kind(self) -> str:
        return self.camera_kind_combo.currentData()

    def set_camera_kind(self, kind: str) -> None:
        """Kamera-Quelle setzen (wie eine Auswahl durch den Nutzer)."""
        self._camera_kind_chosen = True
        self.camera_kind_combo.setCurrentIndex(self.camera_kind_combo.findData(kind))

    def _camera_kind_activated(self, *_):
        self._camera_kind_chosen = True

    def _camera_kind_changed(self, *_):
        self.hardware = None
        self.workflow = None
        if hasattr(self, "pi_save_button"):
            self._update_enabled()

    def refresh_pi_features(self) -> Optional[adapters.PiFeatures]:
        """Fähigkeiten des Pi lesen; Standard-Kamera „Pi (Snapshot)“, wenn möglich."""
        client = self._client()
        if client is None:
            return None
        try:
            feats = adapters.pi_features(client)
        except Exception as exc:  # noqa: BLE001 - Hinweis, kein Abbruch
            self.pi_features = None
            self.camera_note.setText(f"Pi-Fähigkeiten nicht lesbar: {exc}")
            return None
        self.pi_features = feats
        if not self._camera_kind_chosen:
            kind = adapters.CAMERA_PI if feats.snapshot else adapters.CAMERA_LOCAL
            self.camera_kind_combo.setCurrentIndex(self.camera_kind_combo.findData(kind))
        self.camera_note.setText(feats.summary)
        return feats

    def _mode_changed(self, *_):
        pi = self.mode == MODE_PI
        self.camera_edit.setEnabled(pi)
        self.hardware = None
        self.workflow = None
        if pi and self._client() is not None:
            if self.pi_calibration is None:
                self.refresh_pi_calibration()
            self.refresh_pi_features()
        self._update_estimate()
        if hasattr(self, "pi_save_button"):
            self._update_enabled()

    def _update_enabled(self) -> None:
        busy = self.busy
        for w in (self.full_button, self.mode_combo, self.camera_edit,
                  self.cal_button, self.cal_export_button, self.spacing_spin, self.load_button,
                  self.clear_button):
            w.setEnabled(not busy)
        self.camera_kind_combo.setEnabled(not busy and self.mode == MODE_PI)
        self.camera_edit.setEnabled(not busy and self.mode == MODE_PI
                                    and self.camera_kind == adapters.CAMERA_LOCAL)
        pi = self.mode == MODE_PI
        self.pi_cal_button.setEnabled(not busy and pi)
        self.pi_save_button.setEnabled(not busy and pi and self.calibration is not None)
        self.probe_button.setEnabled(not busy and (bool(self.checked_objects()) or bool(self.manual_areas)
                                                   or bool(self.design_bounds())))
        for w in (self.mark_button, self.selection_button):
            w.setEnabled(not busy and self.canvas is not None)
        self.clear_marks_button.setEnabled(not busy and bool(self.manual_areas))
        self.save_button.setEnabled(not busy and self.maps is not None)
        self.export_button.setEnabled(not busy)
        self.more_button.setEnabled(True)
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
    # Die Kalibrierung gehört zur Maschine: im Pi-Modus gilt der Stand auf dem
    # Pi (GET/PUT /api/camera/calibration). camera.json ist Import/Export und
    # Rückfall für Simulation/offline (docs/KAMERA_STATUS_UND_KALIBRIERUNG.md).
    def _client(self):
        return self.client_provider() if self.client_provider else None

    def _set_calibration(self, cal: Optional[CameraCalibration]) -> None:
        self.calibration = cal
        self.hardware = None
        self.workflow = None
        self._update_estimate()

    def _show_calibration_status(self) -> None:
        cal = self.calibration
        if self.calibration_dirty and cal is not None:
            name = self.calibration_path.name if self.calibration_path else "lokal"
            text = (f"{name}: {cal.px_per_mm:.2f} px/mm @ Z{cal.scan_z:.0f}, "
                    f"{cal.image_width}×{cal.image_height}")
            if self.mode == MODE_PI:
                text += " – nicht auf dem Pi gespeichert"
            if self.pi_calibration_error:
                text += f"\n{self.pi_calibration_error}"
        elif self.pi_calibration is not None:
            text = self.pi_calibration.status_text()
        elif self.pi_calibration_error:
            text = self.pi_calibration_error
        else:
            text = "Standardwerte (unkalibriert)"
        self.cal_label.setText(text)

    def refresh_pi_calibration(self, report: bool = False) -> Optional[pi_calibration.PiCalibration]:
        """Kalibrierung vom Pi holen; Fehler als deutscher Hinweis im Label."""
        client = self._client()
        if client is None:
            self.pi_calibration_error = "Pi nicht verbunden – Kalibrierung vom Pi nicht geladen"
            self._show_calibration_status()
            if report:
                self._error(self.pi_calibration_error)
            return None
        try:
            pc = pi_calibration.fetch(client)
        except pi_calibration.PiCalibrationError as exc:
            self.pi_calibration = None
            self.pi_calibration_error = str(exc)
            self._show_calibration_status()
            if report:
                self._error(str(exc))
            return None
        self.pi_calibration, self.pi_calibration_error = pc, ""
        self.calibration_dirty = False
        self.calibration_path = None
        # Platzhalter des Pi nie als echte Kalibrierung verwenden.
        self._set_calibration(None if pc.placeholder else pc.calibration)
        self._show_calibration_status()
        if report:
            self._notify(pc.status_text().splitlines()[0])
        self._update_enabled()
        return pc

    def save_calibration_to_pi(self, notes: Optional[str] = None) -> bool:
        """Aktuelle Kalibrierung (mit Bestätigung) auf den Pi schreiben."""
        if self.calibration is None:
            self._error("Keine Kalibrierung zum Speichern – zuerst camera.json importieren")
            return False
        client = self._client()
        if client is None:
            self._error("Pi nicht verbunden – Kalibrierung nicht gespeichert")
            return False
        if self.pi_calibration is None and self.refresh_pi_calibration() is None:
            # Nur bei unbekannter Revision abbrechen; lokale Werte bleiben erhalten.
            self._error(self.pi_calibration_error or "Kalibrierung auf dem Pi nicht lesbar")
            return False
        base = self.pi_calibration
        if self.ask:
            before = "Platzhalter" if base.placeholder else f"Revision {base.revision}"
            if QMessageBox.question(
                    self, "Kalibrierung auf dem Pi speichern?",
                    f"Die Kamera-Kalibrierung gehört zur Maschine und gilt danach für alle "
                    f"Clients.\nAuf dem Pi ersetzen ({before})?") != QMessageBox.StandardButton.Yes:
                return False
        try:
            pc = pi_calibration.store(client, self.calibration, base.revision, notes=notes)
        except pi_calibration.Conflict as exc:
            if exc.current is not None:
                self.pi_calibration = exc.current
            self._error(f"{exc}\nLokale Werte bleiben erhalten; „Vom Pi laden“ zeigt den neuen Stand.")
            return False
        except pi_calibration.PiCalibrationError as exc:
            self._error(str(exc))
            return False
        self.pi_calibration, self.pi_calibration_error = pc, ""
        self.calibration_dirty = False
        self._set_calibration(pc.calibration)
        self._show_calibration_status()
        self._notify(f"Kalibrierung auf dem Pi gespeichert (Revision {pc.revision})")
        self._update_enabled()
        return True

    def load_calibration(self, path: str | Path) -> CameraCalibration:
        """camera.json importieren (lokal; im Pi-Modus danach „Auf Pi speichern“)."""
        cal = CameraCalibration.load(path)
        self.calibration_path = Path(path)
        self.calibration_dirty = True
        self._set_calibration(cal)
        self._show_calibration_status()
        self._update_enabled()
        return cal

    def export_calibration(self, path: str | Path) -> CameraCalibration:
        cal = self.calibration or adapters.default_calibration()
        cal.save(path)
        self._notify(f"Kalibrierung exportiert: {path}")
        return cal

    def _choose_calibration(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Kamera-Kalibrierung importieren", "",
                                              "Kalibrierung (*.json)")
        if path:
            try:
                self.load_calibration(path)
            except Exception as exc:  # noqa: BLE001 - Meldung an den Nutzer
                self._error(f"Kalibrierung ungültig: {exc}")
                return
            if self.mode == MODE_PI and self._client() is not None:
                self.save_calibration_to_pi()

    def _export_calibration_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Kamera-Kalibrierung exportieren",
                                              "camera.json", "Kalibrierung (*.json)")
        if path:
            try:
                self.export_calibration(path)
            except Exception as exc:  # noqa: BLE001
                self._error(f"Export fehlgeschlagen: {exc}")

    # ---------------------------------------------------------- Hardware
    def _build_hardware(self, need_camera: bool = True) -> adapters.Hardware:
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
        if self.calibration is None and not self.calibration_dirty:
            self.refresh_pi_calibration()
        if self.calibration is None and not need_camera:
            # Nur Proben (Ein-Klick-Auftrag, „Nur Höhenmesh“): der Taster braucht
            # keine Kamera-Kalibrierung – ohne Kamera, mit Standardwerten.
            if self.pi_features is None:
                self.refresh_pi_features()
            hw = adapters.pi_setup(client, adapters.default_calibration(), None,
                                   adapters.CAMERA_LOCAL, self.pi_features)
            hw.camera = None
            return hw
        if self.calibration is None:
            why = self.pi_calibration_error or (
                "Auf dem Pi ist noch keine Kalibrierung gespeichert (Platzhalter)")
            raise adapters.HardwareNotReady(
                f"{why}. Für echte Scans camera.json importieren und „Auf Pi speichern“ "
                "(siehe docs/KAMERA_STATUS_UND_KALIBRIERUNG.md)")
        if self.pi_features is None:
            self.refresh_pi_features()
        return adapters.pi_setup(client, self.calibration, self.camera_edit.text().strip(),
                                 self.camera_kind, self.pi_features)

    def _ensure_workflow(self, need_camera: bool) -> ScanProbeWorkflow:
        if self.hardware is not None and need_camera and self.hardware.camera is None \
                and not self.hardware.simulated:
            self.hardware = self.workflow = None   # vorher nur fürs Proben gebaut
        if self.hardware is None or self.workflow is None:
            self.hardware = self._build_hardware(need_camera)
            self.workflow = ScanProbeWorkflow(
                self.hardware.machine, self.hardware.camera, self.hardware.probe,
                self.hardware.calibration, self._probe_settings(),
                settle_s=0.0 if self.hardware.simulated else 0.15)
        self.workflow.settings = self._probe_settings()
        if need_camera and self.hardware.camera is None:
            raise adapters.HardwareNotReady("Keine Kamera-Quelle angegeben")
        check = getattr(self.hardware.machine, "check_scan_height", None)
        if need_camera and not self.hardware.simulated and check is not None:
            # vor dem Start prüfen statt mitten im Scan scheitern (Z-Freigabe, Scanhöhe)
            notes = check(self.hardware.calibration.scan_z)
            if notes:
                self.camera_note.setText("\n".join(notes))
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
            r = machine_rect(b.x, b.y, b.x + b.w, b.y + b.h)
            out.append(Rect(r.xmin, r.ymin, max(r.xmax, r.xmin + 0.1), max(r.ymax, r.ymin + 0.1)))
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
        self.mark_rect(machine_rect(x, y, x + w, y + h))

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
        target = self.worker if self.worker is not None else self.external_run
        if target is None:
            return
        if paused:
            target.pause()
            self.pause_button.setText("Fortsetzen")
            self._notify("Pausiert – nach dem aktuellen Schritt angehalten")
        else:
            target.resume()
            self.pause_button.setText("Pause")
            self._notify("Fortgesetzt")

    def pause(self) -> None:
        self.pause_button.setChecked(True)

    def resume(self) -> None:
        self.pause_button.setChecked(False)

    def cancel(self) -> None:
        target = self.worker if self.worker is not None else self.external_run
        if target is not None:
            target.cancel()
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

    @property
    def has_maps(self) -> bool:
        return self.maps is not None and bool(self.maps.maps)

    def prepare_job_gcode(self, gcode: str) -> Optional[str]:
        """Hook für jeden G-Code-Export/Versand (Anforderungen 2026-10-26 §1).

        Liegt ein Höhenmesh vor, wird **immer** fokuskorrigiert – es gibt keine
        Auswahl mehr. Ohne Mesh kommt ``gcode`` unverändert zurück (der
        Ein-Klick-Auftrag misst dann selbst). ``None`` bei Fehlern; ein zu altes
        Mesh ist ein Fehler („neu messen“). Übrige Warnungen werden automatisch
        behandelt und nur als Hinweis gemeldet. ``skip_focus_correction`` ist
        ein verstecktes Experten-/Test-Schalterchen ohne Oberfläche.
        """
        self.last_focus_export = None
        if self.skip_focus_correction or not self.has_maps:
            return gcode
        res = self.compensate(gcode)
        errors = list(res.errors)
        if res.ok:
            stale = [w for w in res.warnings if " h alt (> " in w]
            if stale:
                errors = stale + ["Höhenmesh neu messen – der Auftrag tut das automatisch."]
        if errors:
            self._error(" ".join(errors))
            if self.ask:
                QMessageBox.critical(self, "Fokuskorrektur nicht möglich",
                                     "\n".join(errors))
            return None
        r = res.report
        self.last_notes = list(res.warnings)
        self._notify(f"Fokuskorrektur: Z {r.z_min:.2f} … {r.z_max:.2f} mm"
                     + (f" ({len(res.warnings)} Hinweis(e))" if res.warnings else ""))
        return res.gcode

    def _job_gcode_with_note(self) -> tuple[str, str]:
        """Gleicher G-Code wie „An Pi senden“: JobTools („Nur Auswahl“, Planer-Hinweise),
        sonst Schnittplaner bzw. reiner Canvas-Export. ValueError bei leerem Auftrag."""
        source = self.job_gcode_source
        if source is None:
            tools = getattr(self.window(), "job_tools", None)
            source = getattr(tools, "job_gcode", None)
        if source is not None:
            return source()
        try:
            from lumacut_job.planner import optimized_document_gcode
        except ImportError:  # pragma: no cover - ältere Studio-Version ohne Planer
            from lumacut_canvas.gcode import document_to_gcode as optimized_document_gcode
        return optimized_document_gcode(self.canvas.document), ""

    def _job_gcode(self) -> str:
        return self._job_gcode_with_note()[0]

    def export_gcode(self, path: str | Path) -> bool:
        """Canvas → Marlin-G-Code (ggf. fokuskorrigiert) → Datei."""
        try:
            gcode, note = self._job_gcode_with_note()
        except ValueError as exc:
            self._error(f"Export nicht möglich: {exc}")
            return False
        out = self.prepare_job_gcode(gcode)
        if out is None:
            return False
        Path(path).write_text(out, encoding="utf-8")
        self._notify(f"G-Code gespeichert: {Path(path).name}"
                     + (" (fokuskorrigiert)" if self.last_focus_export else "")
                     + (f" – {note}" if note else ""))
        return True

    def _export_dialog(self) -> None:
        name = "auftrag_fokus.gcode" if self.has_maps and not self.skip_focus_correction \
            else "auftrag.gcode"
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
