"""Qt-Anbindung: Menü „Datei“, Importieren (Strg+I), Drag & Drop, Bildeinstellungen.

Außerdem „Bild nachzeichnen …“ (Alt+T, :mod:`.trace` / :mod:`.trace_qt`).

``install_import(window)`` erwartet ein Hauptfenster mit ``window.canvas``
(:class:`lumacut_canvas.editor.CanvasEditor`). Alle Importe laufen über einen
einzigen ``AddShapesCommand`` („Importieren“) und sind damit in einem Schritt
rückgängig zu machen.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QInputDialog, QLabel,
                               QGroupBox, QHBoxLayout, QMessageBox, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from lumacut_canvas.commands import AddShapesCommand, DeleteShapesCommand, SetImageSettingsCommand
from lumacut_canvas.document_io import FILE_SUFFIX
from lumacut_canvas.model import ImageSettings
from lumacut_canvas.unit_ui import SpeedSpin, SpeedUnitCombo

from .curve_widget import CURVE_PRESETS, CUSTOM_LABEL, CurveWidget, preset_name
from .placement import ALL_SUFFIXES, IMAGE_SUFFIXES, PDF_LIKE_SUFFIXES, import_file

MODE_LABELS = {
    "threshold": "Schwellwert (Schwarz/Weiß)",
    "floyd": "Floyd-Steinberg (Dithering)",
    "atkinson": "Atkinson (Dithering)",
    "jarvis": "Jarvis (Dithering, Fotos)",
    "stucki": "Stucki (Dithering, Fotos)",
    "sierra": "Sierra (Dithering)",
    "ordered": "Geordnet (Bayer)",
    "halftone": "Halbton (Rasterpunkte, Zellen + Winkel)",
    "newsprint": "Zeitungsdruck (45°-Rasterpunkte)",
    "sketch": "Skizze (Kanten, Zeichenstil)",
    "grayscale": "Graustufen (Leistung je Pixel)",
    "depth3d": "3D-Tiefe (Mehrfach-Durchgänge)",
}
PREVIEW_SIZE = 300          # px, längste Kante der Vorschau im Dialog
PREVIEW_DEBOUNCE_MS = 150

FILTER = ("Alle unterstützten (" + " ".join(f"*{s}" for s in ALL_SUFFIXES) + ");;"
          "Vektor (*.svg *.dxf *.pdf *.ai *.eps);;"
          "PDF / Illustrator (*.pdf *.ai);;"
          "EPS (*.eps);;"
          "xTool-Projekt (*.xcs *.xs);;"
          "Bild (" + " ".join(f"*{s}" for s in IMAGE_SUFFIXES) + ")")


HISTOGRAM_HEIGHT = 70       # px


class HistogramWidget(QWidget):
    """Histogramm der Grauwerte (links Schwarz, rechts Weiß): hell = Bild,
    dunkel = nach der Bildanpassung (Wurzel-Skala, damit kleine Spitzen
    sichtbar bleiben). Rote Randstriche = reines Schwarz / Weiß nach Anpassung,
    blaue Striche = eingestellter Schwarz-/Weißpunkt."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("image_histogram")
        self.setMinimumSize(PREVIEW_SIZE, HISTOGRAM_HEIGHT)
        self.setMaximumHeight(HISTOGRAM_HEIGHT)
        self.data = None

    def set_data(self, data) -> None:
        self.data = data
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(255, 255, 255))
        p.setPen(QColor(187, 187, 187))
        p.drawRect(0, 0, w - 1, h - 1)
        d = self.data
        if d is not None:
            import numpy as np
            peak = max(float(np.sqrt(d.source.max())), float(np.sqrt(d.adjusted.max())), 1.0)
            for hist, color in ((d.source, QColor(190, 205, 225)), (d.adjusted, QColor(60, 60, 60))):
                vals = np.sqrt(hist.astype(float)) / peak
                p.setPen(color)
                for i in range(256):
                    x = 1 + int(i * (w - 2) / 256)
                    top = h - 1 - int(vals[i] * (h - 3))
                    p.drawLine(x, h - 2, x, top)
            bp, wp = getattr(d, "points", (0, 255))
            if (bp, wp) != (0, 255):
                p.setPen(QColor(30, 90, 200))
                for v in (bp, wp):
                    x = 1 + int((v + 0.5) * (w - 2) / 256)
                    p.drawLine(x, 1, x, h - 2)
            p.setPen(QColor(200, 30, 30))
            if d.black_share > 0.01:
                p.drawLine(1, 1, 1, h - 2)
            if d.white_share > 0.01:
                p.drawLine(w - 2, 1, w - 2, h - 2)
        p.end()


class ImageSettingsDialog(QDialog):
    """Gravur-Einstellungen eines Bildobjekts (LightBurn „Bildmodus“)."""

    def __init__(self, settings: ImageSettings, width_mm: float, px_width: int, parent=None,
                 png: bytes | None = None, height_mm: float | None = None,
                 shape=None) -> None:
        """``png`` + ``height_mm``: Bilddaten für die Vorschau (ohne: keine Vorschau).

        ``shape``: das Bildobjekt – dann rendert die Vorschau es wie der Auftrag
        (Drehung, Glättung, Spiegelung im Maschinen-Nullpunkt)."""
        super().__init__(parent)
        if shape is not None and getattr(shape, "image", None) is not None:
            png = shape.image.png if png is None else png
            height_mm = shape.geom.h if height_mm is None else height_mm
        self._shape = shape
        self._render_key = None
        self._rendered = None
        self.histogram_runs = 0
        self.last_histograms = None
        self.setWindowTitle("Bildeinstellungen")
        self._width_mm = width_mm
        self._height_mm = height_mm
        self._px = px_width
        self._gray = None
        self.preview_runs = 0
        self.last_preview = None
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
        self.speed = SpeedSpin(1, 6000, st.speed_mm_min)  # Wert mm/min, Anzeige mm/min oder mm/s
        self.speed.setKeyboardTracking(True)
        self.speed_unit = SpeedUnitCombo()
        self.passes = QSpinBox()
        self.passes.setRange(1, 30)
        self.passes.setValue(st.passes)
        self.threshold = QSpinBox()
        self.threshold.setRange(0, 255)
        self.threshold.setValue(st.threshold)
        self.overscan = self._dspin(0, 20, st.overscan_mm, 1, 0.5, " mm")
        # Scan-Winkel (LightBurn „Scan Angle“ / „Angle Increment“).
        self.scan_angle = self._dspin(-90, 90, st.scan_angle, 1, 15, " °")
        self.scan_angle.setObjectName("image_scan_angle")
        self.scan_angle.setToolTip("Rasterzeilen unter diesem Winkel lasern (gegen den "
                                   "Uhrzeigersinn; 0 = entlang X, 90 = entlang Y). Z. B. "
                                   "entlang der Holzmaserung oder schräg gegen Streifen.")
        self.angle_increment = self._dspin(-90, 90, st.angle_increment, 1, 15, " °")
        self.angle_increment.setObjectName("image_angle_increment")
        self.angle_increment.setToolTip("Jeder weitere Durchgang wird um diesen Winkel weiter "
                                        "gedreht gelasert (z. B. 90° = Kreuzraster); "
                                        "nur bei mehreren Durchgängen")
        self.bidirectional = QCheckBox("Bidirektional (hin und zurück lasern)")
        self.bidirectional.setChecked(st.bidirectional)
        self.negative = QCheckBox("Negativ (Helles lasern)")
        self.negative.setChecked(st.negative)
        self.levels = QSpinBox()
        self.levels.setRange(2, 64)
        self.levels.setValue(st.depth_levels)
        self.z_step = self._dspin(0, 2, st.z_step_mm, 2, 0.05, " mm")
        self.z_step.setToolTip("Fokus je Tiefenstufe absenken (0 = aus, max. 3 mm gesamt)")
        self.cpi = self._dspin(5, 150, st.halftone_cpi, 1, 1, " /Zoll")
        self.cpi.setToolTip("Rasterzellen je Zoll (LightBurn „Cells per Inch“) – je Zelle ein Punkt")
        self.angle = self._dspin(-90, 90, st.halftone_angle, 1, 7.5, " °")
        self.angle.setToolTip("Winkel des Halbtonrasters")
        self.dot_width = self._dspin(0, 2, st.dot_width_mm, 3, 0.01, " mm")
        self.dot_width.setToolTip("Punktbreitenkorrektur: jede gelaserte Strecke wird um diesen Wert "
                                  "kürzer (je Ende die Hälfte), damit der Strahl Punkte nicht "
                                  "verbreitert. Etwa die halbe Strahlbreite; höchstens der Linienabstand.")
        # Bildanpassung (LightBurn „Adjust Image“): vor dem Modus, auch in der Vorschau.
        self.brightness = self._dspin(-100, 100, st.brightness, 0, 5, " %")
        self.brightness.setToolTip("Helligkeit: + hellt auf (weniger lasern), − dunkelt ab")
        self.contrast = self._dspin(-100, 100, st.contrast, 0, 5, " %")
        self.contrast.setToolTip("Kontrast um Mittelgrau: +100 = 10-fach, −100 = ein Zehntel")
        self.gamma = self._dspin(0.2, 5.0, st.gamma, 2, 0.05, "")
        self.gamma.setToolTip("Gamma: > 1 hellt die Mitteltöne auf, < 1 dunkelt sie ab; "
                              "Schwarz und Weiß bleiben")
        self.sharpen = self._dspin(0, 500, st.sharpen, 0, 10, " %")
        self.sharpen.setToolTip("Schärfen (Unscharf maskieren): betont Kanten und feine Details")
        self.sharpen_radius = self._dspin(0.5, 10, st.sharpen_radius, 1, 0.5, " Punkte")
        self.sharpen_radius.setToolTip("Radius des Schärfens in Laserpunkten (Linienabstand)")
        # Tonwert (Schwarz-/Weißpunkt): Grauwerte ≤ Schwarzpunkt werden Schwarz,
        # ≥ Weißpunkt Weiß, dazwischen linear gestreckt (nach dem Schärfen).
        self.black_point = QSpinBox()
        self.black_point.setRange(0, 254)
        self.black_point.setValue(st.black_point)
        self.black_point.setToolTip("Schwarzpunkt: Grauwerte bis hier werden reines Schwarz "
                                    "(volle Leistung); 0 = unverändert")
        self.white_point = QSpinBox()
        self.white_point.setRange(1, 255)
        self.white_point.setValue(st.white_point)
        self.white_point.setToolTip("Weißpunkt: Grauwerte ab hier werden reines Weiß "
                                    "(nicht gelasert); 255 = unverändert")
        self.black_point.valueChanged.connect(self._levels_changed_black)
        self.white_point.valueChanged.connect(self._levels_changed_white)
        # Gradationskurve (nach dem Schwarz-/Weißpunkt, vor Helligkeit/Kontrast/Gamma).
        self.curve = CurveWidget(st.curve)
        self.curve_preset = QComboBox()
        self.curve_preset.setObjectName("image_curve_preset")
        for name in CURVE_PRESETS:
            self.curve_preset.addItem(name)
        self.curve_preset.addItem(CUSTOM_LABEL)
        self.curve_preset.setToolTip("Gradationskurve: Vorlage wählen oder die Kurve unten "
                                     "bearbeiten (Mitteltöne gezielt heller/dunkler, S-Kurve "
                                     "für mehr Kontrast)")
        self._sync_curve_preset(st.curve)
        self.curve_preset.activated.connect(self._curve_preset_chosen)
        self.curve.curve_changed.connect(self._curve_edited)
        self.reset_adjust = QPushButton("Zurücksetzen")
        self.reset_adjust.setToolTip("Tonwert, Kurve, Helligkeit, Kontrast, Gamma und Schärfen "
                                     "auf „unverändert“")
        self.reset_adjust.clicked.connect(self.reset_adjustments)
        self.auto_levels = QPushButton("Auto-Tonwert")
        self.auto_levels.setToolTip("Schwarz- und Weißpunkt so setzen, dass der Tonwertumfang des "
                                    "Bildes (ohne je 0,5 % Ausreißer) von Schwarz bis Weiß reicht; "
                                    "Helligkeit und Kontrast auf 0, Gamma bleibt")
        self.auto_levels.clicked.connect(self.apply_auto_levels)
        self.histogram = HistogramWidget()
        self.histogram_label = QLabel()
        self.histogram_label.setWordWrap(True)
        adjust_form = QFormLayout()
        adjust_form.addRow("Schwarzpunkt", self.black_point)
        adjust_form.addRow("Weißpunkt", self.white_point)
        adjust_form.addRow("Kurve", self.curve_preset)
        adjust_form.addRow("", self.curve)
        adjust_form.addRow("Helligkeit", self.brightness)
        adjust_form.addRow("Kontrast", self.contrast)
        adjust_form.addRow("Gamma", self.gamma)
        adjust_form.addRow("Schärfen", self.sharpen)
        adjust_form.addRow("Schärferadius", self.sharpen_radius)
        adjust_buttons = QHBoxLayout()
        adjust_buttons.addWidget(self.auto_levels)
        adjust_buttons.addWidget(self.reset_adjust)
        adjust_form.addRow("", adjust_buttons)
        self.adjust_box = QGroupBox("Bildanpassung")
        self.adjust_box.setLayout(adjust_form)
        form.addRow("Modus", self.mode)
        form.addRow("Linienabstand", self.interval)
        form.addRow("", self.dpi_label)
        form.addRow("Leistung (max.)", self.power)
        form.addRow("Leistung (min., Graustufen)", self.min_power)
        speed_row = QHBoxLayout()
        speed_row.addWidget(self.speed, 1)
        speed_row.addWidget(self.speed_unit)
        form.addRow("Geschwindigkeit", speed_row)
        form.addRow("Durchgänge", self.passes)
        form.addRow("Schwellwert", self.threshold)
        form.addRow("Overscan", self.overscan)
        form.addRow("Scan-Winkel", self.scan_angle)
        form.addRow("Winkel-Schritt je Durchgang", self.angle_increment)
        form.addRow("", self.bidirectional)
        form.addRow("", self.negative)
        form.addRow("Tiefenstufen (3D)", self.levels)
        form.addRow("Z-Schritt je Stufe (3D)", self.z_step)
        form.addRow("Rasterzellen (Halbton)", self.cpi)
        form.addRow("Rasterwinkel (Halbton)", self.angle)
        form.addRow("Punktbreitenkorrektur", self.dot_width)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.preview = QLabel()
        self.preview.setObjectName("image_preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self.preview.setStyleSheet("background: white; border: 1px solid #bbb;")
        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        self.preview_label.setMaximumWidth(PREVIEW_SIZE)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(PREVIEW_DEBOUNCE_MS)
        self._preview_timer.timeout.connect(self.update_preview)
        if png is not None and height_mm:
            try:
                from .image_preview import gray_from_png
                self._gray = gray_from_png(png)
            except (ValueError, RuntimeError):
                self._gray = None
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Übernehmen")
        buttons.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        left = QVBoxLayout()
        left.addLayout(form)
        left.addWidget(self.adjust_box)
        left.addWidget(self.hint)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addLayout(left)
        if self._gray is not None:
            right = QVBoxLayout()
            right.addWidget(self.preview)
            right.addWidget(self.preview_label)
            right.addWidget(self.histogram)
            right.addWidget(self.histogram_label)
            right.addStretch(1)
            row.addLayout(right)
        else:
            self.preview.hide()
            self.preview_label.hide()
            self.histogram.hide()
            self.histogram_label.hide()
            self.auto_levels.setEnabled(False)
            self.auto_levels.setToolTip("Ohne Bilddaten nicht verfügbar")
        lay.addLayout(row)
        lay.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self._update)
        self.interval.valueChanged.connect(self._update)
        self.levels.valueChanged.connect(self._update)
        self.z_step.valueChanged.connect(self._update)
        self.cpi.valueChanged.connect(self._update)
        self.dot_width.valueChanged.connect(self._update)
        self.sharpen.valueChanged.connect(self._update)
        self.passes.valueChanged.connect(self._update)
        self.scan_angle.valueChanged.connect(self._update)
        for w in (self.power, self.min_power, self.threshold, self.angle, self.levels,
                  self.brightness, self.contrast, self.gamma, self.sharpen_radius,
                  self.black_point, self.white_point):
            w.valueChanged.connect(self._schedule_preview)
        self.negative.toggled.connect(self._schedule_preview)
        self._update()
        if self._gray is not None:
            self._preview_timer.stop()
            self.update_preview()

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
        self.cpi.setEnabled(mode == "halftone")
        self.angle.setEnabled(mode == "halftone")
        self.dot_width.setMaximum(self.interval.value())
        self.sharpen_radius.setEnabled(self.sharpen.value() > 0)
        self.angle_increment.setEnabled(self.passes.value() > 1)
        dpi = 25.4 / self.interval.value()
        src_dpi = self._px / self._width_mm * 25.4 if self._width_mm > 0 else 0
        self.dpi_label.setText(f"= {dpi:.0f} DPI (Bild: {src_dpi:.0f} DPI)")
        drop = self.z_step.value() * (self.levels.value() - 1)
        if mode == "depth3d" and drop > 3.0:
            self.hint.setText(f"Fokus-Absenkung {drop:.2f} mm > 3 mm – Auftrag wird abgelehnt.")
        elif mode == "depth3d":
            self.hint.setText("Dunkle Bereiche werden öfter gelasert und damit tiefer. "
                              "Fokuskorrektur aus dem Scan ist mit Z-Schritten nicht kombinierbar.")
        elif mode == "halftone":
            cell = 25.4 / self.cpi.value()
            px = cell / self.interval.value()
            text = f"Zelle {cell:.2f} mm = {px:.1f} Punkte"
            if px < 3:
                text += " – zu klein für den Linienabstand, weniger Zellen je Zoll wählen."
            self.hint.setText(text)
        elif mode == "sketch":
            self.hint.setText("Lasert nur Kanten und Strukturen, gleichmäßige Flächen bleiben frei. "
                              "Kontrast und Schärfen verstärken die Linien.")
        else:
            self.hint.setText("")
        self._schedule_preview()

    def _schedule_preview(self, *_args) -> None:
        if self._gray is not None:
            self._preview_timer.start()

    def update_preview(self) -> None:
        """Vorschau sofort neu rechnen (sonst entprellt nach jeder Änderung)."""
        if self._gray is None:
            return
        from .image_preview import preview_array, preview_shape, to_qimage
        self._preview_timer.stop()
        st = self.settings()
        self.update_histogram(st)
        try:
            if self._shape is not None:
                self._render_cached(st)
                pv = preview_shape(self._shape, st, rendered=self._rendered)
            else:
                pv = preview_array(self._gray, self._width_mm, self._height_mm, st)
        except ValueError as exc:
            self.preview.clear()
            self.preview_label.setText(f"Keine Vorschau: {exc}")
            return
        self.preview_runs += 1
        self.last_preview = pv
        pix = QPixmap.fromImage(to_qimage(pv.pixels))
        self.preview.setPixmap(pix.scaled(PREVIEW_SIZE, PREVIEW_SIZE, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation))
        h, w = pv.pixels.shape
        text = f"Vorschau: {w} × {h} Laserpunkte, {pv.burn_share * 100:.0f} % gelasert"
        if pv.cropped:
            text += " (Ausschnitt aus der Bildmitte)"
        rot = self._shape.geom.rot if self._shape is not None else 0.0
        if rot:
            text += f", gedreht um {rot:g}°"
        if st.scan_angle:
            text += f", Scan-Winkel {st.scan_angle:g}°"
        if st.angle_increment and st.passes > 1:
            text += " (Vorschau: 1. Durchgang)"
        self.preview_label.setText(text)

    def _render_cached(self, st: ImageSettings):
        """Bildobjekt wie im Auftrag rendern (Cache je Linienabstand / Negativ)."""
        from .image_preview import render_for_preview
        from lumacut_job.images import pass_angles
        key = (st.line_interval_mm, st.negative, pass_angles(st)[0])
        if key != self._render_key:
            self._rendered = render_for_preview(self._shape, st)
            self._render_key = key
        return self._rendered

    def update_histogram(self, st: ImageSettings | None = None) -> None:
        """Histogramm vor/nach der Bildanpassung neu rechnen; bei gedrehtem
        Bildobjekt vom gedrehten Bild wie im Auftrag (ohne die Ecken der Hüllbox)."""
        if self._gray is None:
            return
        from .image_preview import histograms, histograms_rendered
        st = st or self.settings()
        try:
            if self._shape is not None and (self._shape.geom.rot or st.scan_angle):
                gray, inside = self._render_cached(st)
                h = histograms_rendered(gray, inside, st)
            else:
                h = histograms(self._gray, self._width_mm, self._height_mm, st)
        except ValueError:
            return
        self.histogram_runs += 1
        self.last_histograms = h
        self.histogram.set_data(h)
        from .image_preview import curve_input_histogram
        self.curve.set_histogram(curve_input_histogram(h.source, *h.points))
        text = (f"Histogramm: hell = Bild, dunkel = angepasst – reines Schwarz "
                f"{h.black_share * 100:.1f} %, reines Weiß {h.white_share * 100:.1f} %")
        if h.levels is not None:
            text += f"; Tonwertumfang {h.levels[0]}–{h.levels[1]}"
        if h.points != (0, 255):
            text += f"; Schwarz-/Weißpunkt {h.points[0]} / {h.points[1]} (blau)"
        if st.curve:
            text += f"; Kurve: {preset_name(st.curve)}"
        self.histogram_label.setText(text)

    def apply_auto_levels(self) -> bool:
        """„Auto-Tonwert“: Schwarz-/Weißpunkt aus dem Histogramm, Helligkeit und
        Kontrast auf 0 (Gamma und Schärfen bleiben); True bei Änderung."""
        if self._gray is None:
            return False
        from .image_preview import auto_points_for
        black, white = auto_points_for(self._gray, self._width_mm, self._height_mm,
                                       self.settings())
        before = (self.black_point.value(), self.white_point.value(),
                  self.brightness.value(), self.contrast.value())
        self.white_point.setValue(255)    # erst Platz schaffen, dann setzen –
        self.black_point.setValue(black)  # die Felder schieben sich sonst gegenseitig
        self.white_point.setValue(white)
        self.brightness.setValue(0.0)
        self.contrast.setValue(0.0)
        return (black, white, 0.0, 0.0) != before

    def _levels_changed_black(self, value: int) -> None:
        """Schwarzpunkt bleibt unter dem Weißpunkt (schiebt ihn mit)."""
        if self.white_point.value() <= value:
            self.white_point.setValue(value + 1)

    def _levels_changed_white(self, value: int) -> None:
        """Weißpunkt bleibt über dem Schwarzpunkt (schiebt ihn mit)."""
        if self.black_point.value() >= value:
            self.black_point.setValue(value - 1)

    def _sync_curve_preset(self, curve) -> None:
        idx = self.curve_preset.findText(preset_name(curve))
        self.curve_preset.blockSignals(True)
        self.curve_preset.setCurrentIndex(max(0, idx))
        self.curve_preset.blockSignals(False)

    def _curve_preset_chosen(self, index: int) -> None:
        name = self.curve_preset.itemText(index)
        if name in CURVE_PRESETS:
            self.curve.set_curve(CURVE_PRESETS[name], emit=True)
        self._sync_curve_preset(self.curve.curve())

    def _curve_edited(self, curve) -> None:
        self._sync_curve_preset(curve)
        self._schedule_preview()

    def reset_adjustments(self) -> None:
        """Bildanpassung auf „unverändert“ (Vorgaben)."""
        d = ImageSettings()
        self.curve.set_curve(d.curve, emit=True)
        self.black_point.setValue(d.black_point)
        self.white_point.setValue(d.white_point)
        self.brightness.setValue(d.brightness)
        self.contrast.setValue(d.contrast)
        self.gamma.setValue(d.gamma)
        self.sharpen.setValue(d.sharpen)
        self.sharpen_radius.setValue(d.sharpen_radius)

    def settings(self) -> ImageSettings:
        return ImageSettings(
            mode=self.mode.currentData(), line_interval_mm=self.interval.value(),
            power=self.power.value(), min_power=self.min_power.value(),
            speed_mm_min=self.speed.value(), passes=self.passes.value(),
            threshold=self.threshold.value(), bidirectional=self.bidirectional.isChecked(),
            overscan_mm=self.overscan.value(), negative=self.negative.isChecked(),
            depth_levels=self.levels.value(), z_step_mm=self.z_step.value(),
            halftone_cpi=self.cpi.value(), halftone_angle=self.angle.value(),
            dot_width_mm=self.dot_width.value(), brightness=self.brightness.value(),
            contrast=self.contrast.value(), gamma=self.gamma.value(),
            sharpen=self.sharpen.value(),
            sharpen_radius=self.sharpen_radius.value(),
            black_point=self.black_point.value(),
            white_point=self.white_point.value(),
            curve=self.curve.curve(),
            scan_angle=self.scan_angle.value(),
            angle_increment=self.angle_increment.value()).normalized()


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
        self.import_action.setToolTip("SVG, DXF, PDF, AI, EPS, xTool (.xcs/.xs) oder Bild (PNG/JPG/BMP) importieren  (Strg+I)")
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
        if Path(path).suffix.lower() in PDF_LIKE_SUFFIXES and page is None:
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
            dlg = ImageSettingsDialog(old, sh.geom.w, sh.image.px_width, self.window,
                                      png=sh.image.png, height_mm=sh.geom.h, shape=sh)
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
