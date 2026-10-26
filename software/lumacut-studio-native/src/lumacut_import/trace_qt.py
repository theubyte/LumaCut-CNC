"""Dialog „Bild nachzeichnen“ (Alt+T, wie LightBurn „Trace Image“).

Modus „Kontur“ (Flächen mit Löchern) oder „Mittellinie“ (Strichzeichnungen
als offene Linien, :mod:`.centerline`), Schwellwert (fest oder „Auto“ nach
Otsu), Invertieren, Glättung, Toleranz und Mindestfläche mit Live-Vorschau (verkleinertes Bild, Konturen rot). Die
Vorschau rechnet auf höchstens ``PREVIEW_PX`` Pixeln mit kurzer Zeitgrenze,
damit der Dialog auch bei großen, unruhigen Bildern nicht hängt. Übernehmen legt die
Konturen als Polygone (Löcher als Ringe, mehrere Teile gruppiert) deckungsgleich
über das Bild in die aktive Ebene – ein Rückgängig-Schritt, auf Wunsch
einschließlich Löschen des Bildes.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QSpinBox, QVBoxLayout)

from .trace import (MIN_AREA_RANGE, MODE_CENTERLINE, MODE_OUTLINE, SMOOTHING_RANGE, THRESHOLD_RANGE, TOLERANCE_RANGE,
                    TraceSettings, decode_gray, image_mm_per_px, trace_gray)

PREVIEW_PX = 420
PREVIEW_TIME_LIMIT_S = 2.0


class TraceDialog(QDialog):
    def __init__(self, shape, settings: TraceSettings | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bild nachzeichnen")
        self.shape = shape
        st = (settings or TraceSettings.for_image(shape)).normalized()
        gray = decode_gray(shape.image.png)
        h, w = gray.shape
        f = min(1.0, PREVIEW_PX / max(w, h))
        if f < 1.0:
            import cv2
            gray = cv2.resize(gray, (max(1, round(w * f)), max(1, round(h * f))),
                              interpolation=cv2.INTER_AREA)
        self._gray = np.ascontiguousarray(gray)
        mx, my = image_mm_per_px(shape)
        ph, pw = self._gray.shape
        self._mm_per_px = (mx * w / pw, my * h / ph)

        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.setObjectName("trace_mode")
        self.mode.addItem("Kontur", MODE_OUTLINE)
        self.mode.addItem("Mittellinie", MODE_CENTERLINE)
        self.mode.setToolTip("Kontur: Umriss jeder Fläche (Füllen/Schneiden)\n"
                             "Mittellinie: Strichzeichnungen als einfache Linie – "
                             "jeder Strich wird nur einmal gelasert")
        self.mode.setCurrentIndex(max(0, self.mode.findData(st.mode)))
        self.threshold = QSpinBox()
        self.threshold.setRange(*THRESHOLD_RANGE)
        self.threshold.setValue(st.threshold)
        self.threshold.setToolTip("Pixel dunkler als dieser Wert werden nachgezeichnet")
        self.auto_threshold = QCheckBox("Auto")
        self.auto_threshold.setToolTip("Schwellwert automatisch bestimmen (Otsu) – für Fotos "
                                       "und Scans")
        self.auto_threshold.setChecked(st.auto_threshold)
        self.threshold.setEnabled(not st.auto_threshold)
        thr_row = QHBoxLayout()
        thr_row.addWidget(self.threshold, 1)
        thr_row.addWidget(self.auto_threshold)
        self.invert = QCheckBox("Invertieren (helle Bereiche nachzeichnen)")
        self.invert.setChecked(st.invert)
        self.smoothing = self._dspin(SMOOTHING_RANGE, st.smoothing_px, 0.5, 1, " px")
        self.smoothing.setToolTip("Weichzeichnen vor dem Schwellwert – glättet Treppenstufen und Rauschen")
        self.tolerance = self._dspin(TOLERANCE_RANGE, st.tolerance_mm, 0.01, 3, " mm")
        self.tolerance.setToolTip("Vereinfachen: Punkte mit weniger Abweichung fallen weg")
        self.min_area = self._dspin(MIN_AREA_RANGE, st.min_area_mm2, 0.1, 2, " mm²")
        self.min_area.setToolTip("Flecken und Löcher kleiner als diese Fläche ignorieren")
        self.delete_image = QCheckBox("Bild danach löschen")
        form.addRow("Modus", self.mode)
        form.addRow("Schwellwert", thr_row)
        form.addRow("", self.invert)
        form.addRow("Glättung", self.smoothing)
        form.addRow("Toleranz", self.tolerance)
        form.addRow("Mindestfläche", self.min_area)
        form.addRow("", self.delete_image)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(240, 180)
        self.info = QLabel()
        self.info.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Nachzeichnen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.Ok)

        row = QHBoxLayout()
        row.addLayout(form)
        row.addWidget(self.preview, 1)
        lay = QVBoxLayout(self)
        lay.addLayout(row)
        lay.addWidget(self.info)
        lay.addWidget(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.update_preview)
        for sig in (self.threshold.valueChanged, self.smoothing.valueChanged,
                    self.tolerance.valueChanged, self.min_area.valueChanged):
            sig.connect(lambda _v: self._timer.start())
        self.invert.toggled.connect(lambda _v: self._timer.start())
        self.mode.currentIndexChanged.connect(lambda _v: self._timer.start())
        self.auto_threshold.toggled.connect(self._auto_toggled)
        self.update_preview()

    @staticmethod
    def _dspin(rng, value, step, decimals, suffix) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(*rng)
        sp.setDecimals(decimals)
        sp.setSingleStep(step)
        sp.setValue(value)
        sp.setSuffix(suffix)
        return sp

    def _auto_toggled(self, on: bool) -> None:
        self.threshold.setEnabled(not on)
        self._timer.start()

    def settings(self) -> TraceSettings:
        return TraceSettings(threshold=self.threshold.value(), invert=self.invert.isChecked(),
                             smoothing_px=self.smoothing.value(), tolerance_mm=self.tolerance.value(),
                             min_area_mm2=self.min_area.value(),
                             auto_threshold=self.auto_threshold.isChecked(),
                             mode=self.mode.currentData() or MODE_OUTLINE).normalized()

    def update_preview(self) -> None:
        gray = self._gray
        ph, pw = gray.shape
        qimg = QImage(gray.data, pw, ph, pw, QImage.Format_Grayscale8).convertToFormat(
            QImage.Format_RGB32)
        try:
            # Glättung in Original-Pixeln → in Vorschau-Pixel umrechnen
            st = self.settings()
            f = pw / self.shape.image.px_width
            res = trace_gray(gray, replace(st, smoothing_px=st.smoothing_px * f),
                             self._mm_per_px, time_limit_s=PREVIEW_TIME_LIMIT_S)
            err = None
            if st.auto_threshold and res.threshold is not None:
                # gefundenen Wert anzeigen (ohne neue Vorschau auszulösen)
                self.threshold.blockSignals(True)
                self.threshold.setValue(res.threshold)
                self.threshold.blockSignals(False)
        except ValueError as exc:
            res, err = None, str(exc)
        p = QPainter(qimg)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(qimg.rect(), QColor(255, 255, 255, 150))
        if res is not None:
            pen = QPen(QColor(220, 30, 30))
            pen.setWidthF(1.2)
            p.setPen(pen)
            for part in res.parts:
                for ring in [part.outer, *part.holes]:
                    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in ring]))
            for line in res.lines:
                p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in line]))
        p.end()
        pix = QPixmap.fromImage(qimg)
        if max(pw, ph) < 240:
            pix = pix.scaled(pw * 240 // max(pw, ph), ph * 240 // max(pw, ph), Qt.KeepAspectRatio)
        self.preview.setPixmap(pix)
        auto = (f"Schwellwert automatisch: {res.threshold}. "
                if res is not None and self.auto_threshold.isChecked() else "")
        if err:
            self.info.setText(err)
        elif not res.count:
            self.info.setText(auto + "Keine Konturen – Schwellwert oder Invertieren ändern."
                              + (" Mittellinie ist für Striche gedacht, nicht für Flächen."
                                 if self.settings().mode == MODE_CENTERLINE else ""))
        else:
            what = (f"{len(res.lines)} Linie(n)" if res.lines and not res.parts
                    else f"{len(res.parts)} Kontur(en)")
            self.info.setText(auto + f"Vorschau: {what}, {res.point_count} Punkte"
                              + (f", {res.removed} Fleck(en) ignoriert" if res.removed else ""))
        self.ok_button.setEnabled(err is None and res is not None and bool(res.count))
