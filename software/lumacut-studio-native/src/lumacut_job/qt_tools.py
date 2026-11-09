"""Qt glue: a "Auftrag" toolbar with time estimate, framing and material test.

Installed by ``main.py`` with :func:`install_job_tools`; it only *uses* the
public APIs of the canvas editor (``document``, ``undo_stack``) and the
machine panel (``frame_gcode``, ``set_frame_provider``) and owns no state of
theirs. Framing runs on the Pi as ``op=frame`` and never replaces the job
that was sent before.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QSpinBox, QToolBar, QWidget)

from lumacut_canvas.commands import AddLayerCommand, AddShapesCommand
from lumacut_canvas.export import job_layers
from lumacut_canvas.unit_ui import SpeedSpin, SpeedUnitCombo

from .estimate import estimate_gcode, frame_gcode
from lumacut_canvas.model import Z_OFFSET_RANGE

from .material_test import (AXIS_PARAM_LABELS, AXIS_PARAMS, IMAGE_ADJUST_OPTIONS,
                            IMAGE_AXIS_DIGITS, IMAGE_AXIS_MODE_LABELS, IMAGE_AXIS_PARAMS,
                            IMAGE_AXIS_UNITS, IMAGE_EXTRA_OPTIONS, IMAGE_MODE_OPTIONS,
                            IMAGE_OPTION_RANGES, image_axis_mode,
                            IMAGE_SOURCE_LABELS, IMAGE_SOURCES, INTERVAL_TEST_RANGE,
                            MAX_DEPTH_DROP_MM, TEST_IMAGE_MODES,
                            MaterialTestSpec, build_material_test)
from .planner import PlanReport, optimize_layers, optimized_document_gcode


def _spin(lo, hi, value, step=1.0, decimals=0, suffix=""):
    w = QDoubleSpinBox() if decimals else QSpinBox()
    w.setRange(lo, hi)
    if decimals:
        w.setDecimals(decimals)
    w.setSingleStep(step)
    w.setValue(value)
    if suffix:
        w.setSuffix(suffix)
    return w


# "Art" combo of the material test dialog: index -> cell kind.
CELL_FILL, CELL_OUTLINE, CELL_IMAGE = 0, 1, 2


class MaterialTestDialog(QDialog):
    def __init__(self, parent=None, spec: MaterialTestSpec | None = None):
        super().__init__(parent)
        self.setWindowTitle("Materialtest-Raster")
        s = spec or MaterialTestSpec()
        f = QFormLayout(self)
        self.p_min = _spin(1, 100, s.power_min, suffix=" %")
        self.p_max = _spin(1, 100, s.power_max, suffix=" %")
        self.cols = _spin(1, 12, s.columns)
        # Geschwindigkeit: Wert mm/min, Anzeige mm/min oder mm/s (unit_ui)
        self.s_min = SpeedSpin(1, 6000, s.speed_min)
        self.s_max = SpeedSpin(1, 6000, s.speed_max)
        for w in (self.s_min, self.s_max):
            w.setKeyboardTracking(True)
        self.speed_unit = SpeedUnitCombo()
        self.rows = _spin(1, 12, s.rows)
        self.cell = _spin(2, 60, s.cell_mm, 1, 1, " mm")
        self.gap = _spin(0, 30, s.gap_mm, 1, 1, " mm")
        self.x = _spin(0, 360, s.x, 5, 1, " mm")
        self.y = _spin(0, 340, s.y, 5, 1, " mm")
        self.passes = _spin(1, 30, s.passes)
        self.passes_max = _spin(1, 30, s.passes_max)
        self.mode = QComboBox()
        self.mode.addItems(["Füllen (Gravur)", "Kontur (Schnitt)", "Bild (Graustufen-Verlauf)"])
        self.mode.setCurrentIndex(CELL_IMAGE if s.image_mode
                                  else CELL_FILL if s.line_interval_mm else CELL_OUTLINE)
        # Image cells: image mode and power at white (LightBurn "Dithered Image" test).
        from lumacut_import.qt import MODE_LABELS
        self.image_mode = QComboBox()
        for key in TEST_IMAGE_MODES:
            self.image_mode.addItem(MODE_LABELS.get(key, key), key)
        idx = self.image_mode.findData(s.image_mode or "floyd")
        self.image_mode.setCurrentIndex(max(0, idx))
        self.image_min = _spin(0, 100, s.image_min_power, suffix=" %")
        self.image_source = QComboBox()
        for key in IMAGE_SOURCES:
            self.image_source.addItem(IMAGE_SOURCE_LABELS[key], key)
        src = s.image_source if s.image_source in IMAGE_SOURCES else "ramp"
        if src == "photo" and not s.image_png:
            src = "ramp"
        self.image_source.setCurrentIndex(IMAGE_SOURCES.index(src))
        self.image_source.setToolTip(
            "Gemeinsames Testbild für alle Zellen: Verlauf (Weiß→Schwarz), "
            "Stufenkeil (diskrete Graustufen) oder ein eigenes Foto.")
        self._photo_png = s.image_png if src == "photo" else None
        self._photo_path = ""
        self.photo_row = QWidget()
        photo_lay = QHBoxLayout(self.photo_row)
        photo_lay.setContentsMargins(0, 0, 0, 0)
        self.photo_label = QLabel("kein Bild")
        self.photo_label.setToolTip("Optionales Foto für die Bild-Testzellen (wird als Graustufen eingebettet).")
        self.photo_btn = QPushButton("Bild wählen…")
        self.photo_btn.setToolTip("PNG, JPG oder BMP wählen – wird als 8-Bit-Graustufen in die Zellen gelegt.")
        self.photo_btn.clicked.connect(self._pick_photo)
        photo_lay.addWidget(self.photo_label, 1)
        photo_lay.addWidget(self.photo_btn)
        if self._photo_png:
            self.photo_label.setText(f"eingebettet ({len(self._photo_png)} Bytes)")
        self._build_image_options(s)
        self.interval = _spin(*INTERVAL_TEST_RANGE, s.line_interval_mm or 0.2, 0.05, 2, " mm")
        self.interval_max = _spin(*INTERVAL_TEST_RANGE, s.interval_max, 0.05, 2, " mm")
        # Focus Test (LightBurn): relative Z offset; needs motorized Z.
        self.focus_min = _spin(*Z_OFFSET_RANGE, s.focus_min, 0.1, 2, " mm")
        self.focus_max = _spin(*Z_OFFSET_RANGE, s.focus_max, 0.1, 2, " mm")
        tip = ("Relativ zum Fokus beim Start des Auftrags. Negativ = näher am "
               "Material (Kopf senken). Braucht motorisierte Z-Achse (LumaCut hat sie).")
        for w in (self.focus_min, self.focus_max):
            w.setToolTip(tip)
        # Parameter per axis (LightBurn Material Test: X / Y parameter); image options
        # (Bild-Achse) only selectable with image cells.
        self.col_param = QComboBox()
        self.row_param = QComboBox()
        for combo, value in ((self.col_param, s.column_param), (self.row_param, s.row_param)):
            for key in AXIS_PARAMS:
                label = AXIS_PARAM_LABELS[key]
                combo.addItem(f"{label} (Bild)" if key in IMAGE_AXIS_PARAMS else label, key)
            combo.setCurrentIndex(AXIS_PARAMS.index(value) if value in AXIS_PARAMS else 0)
        self._build_image_axes(s)
        self.labels = QCheckBox(
            "Beschriftung (Leistung % / Geschw. mm/s / Abstand mm / Durchgänge / Fokus mm)")
        self.labels.setChecked(s.labels)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self._rows: dict = {}
        for key, label, w in (("cparam", "Spalten-Parameter", self.col_param),
                              ("cols", "Spalten", self.cols),
                              ("c_from", "Spalten von", self.axis_from[0]),
                              ("c_to", "Spalten bis", self.axis_to[0]),
                              ("rparam", "Zeilen-Parameter", self.row_param),
                              ("rows", "Zeilen", self.rows),
                              ("r_from", "Zeilen von", self.axis_from[1]),
                              ("r_to", "Zeilen bis", self.axis_to[1]),
                              ("p_min", "Leistung von", self.p_min),
                              ("p_max", "Leistung bis", self.p_max),
                              ("s_min", "Geschw. von", self.s_min),
                              ("s_max", "Geschw. bis", self.s_max),
                              ("unit", "Geschw.-Einheit", self.speed_unit),
                              ("passes", "Durchgänge", self.passes),
                              ("passes_max", "Durchgänge bis", self.passes_max),
                              ("mode", "Art", self.mode),
                              ("image_source", "Bildquelle", self.image_source),
                              ("photo", "Eigenes Bild", self.photo_row),
                              ("image_mode", "Bildmodus", self.image_mode),
                              ("image_min", "Min.-Leistung (Weiß)", self.image_min),
                              ("opt_threshold", "Schwellwert", self.opt_threshold),
                              ("opt_cpi", "Halbton-Zellen", self.opt_cpi),
                              ("opt_angle", "Rasterwinkel", self.opt_angle),
                              ("opt_levels", "3D-Stufen", self.opt_levels),
                              ("opt_zstep", "Z-Schritt je Stufe", self.opt_zstep),
                              ("opt_brightness", "Helligkeit", self.opt_brightness),
                              ("opt_contrast", "Kontrast", self.opt_contrast),
                              ("opt_gamma", "Gamma", self.opt_gamma),
                              ("opt_negative", "", self.opt_negative),
                              ("opt_more", "", self.opt_more),
                              ("opt_sharpen", "Schärfen", self.opt_sharpen),
                              ("opt_sharpen_radius", "Schärferadius", self.opt_sharpen_radius),
                              ("opt_black", "Schwarzpunkt", self.opt_black),
                              ("opt_white", "Weißpunkt", self.opt_white),
                              ("opt_curve", "Kurve", self.opt_curve),
                              ("opt_dot_width", "Punktbreitenkorrektur", self.opt_dot_width),
                              ("opt_scan_angle", "Scan-Winkel", self.opt_scan_angle),
                              ("opt_angle_increment", "Winkel-Schritt je Durchgang",
                               self.opt_angle_increment),
                              ("opt_overscan", "Overscan", self.opt_overscan),
                              ("opt_bidirectional", "", self.opt_bidirectional),
                              ("interval", "Linienabstand", self.interval),
                              ("interval_max", "Linienabstand bis", self.interval_max),
                              ("focus_min", "Fokus von", self.focus_min),
                              ("focus_max", "Fokus bis", self.focus_max),
                              ("cell", "Zellgröße", self.cell), ("gap", "Abstand", self.gap),
                              ("x", "Position X", self.x), ("y", "Position Y", self.y),
                              ("labels", "", self.labels), ("hint", "", self.hint)):
            lab = QLabel(label)
            self._rows[key] = lab
            f.addRow(lab, w)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        f.addRow(self.bb)
        for combo in (self.col_param, self.row_param, self.mode, self.image_source,
                      self.image_mode):
            combo.currentIndexChanged.connect(self._update_fields)
        for spin in (self.image_min, self.p_min, self.focus_min, self.focus_max,
                     self.opt_levels, self.opt_zstep, self.opt_black, self.opt_white,
                     self.opt_dot_width, self.opt_sharpen, self.interval, self.interval_max,
                     self.cols, self.rows, *self.axis_from, *self.axis_to):
            spin.valueChanged.connect(self._update_fields)
        self.opt_more.toggled.connect(self._update_fields)
        self._update_fields()

    def _build_image_axes(self, s: MaterialTestSpec) -> None:
        """From/to spins of an image-option axis (column, row). Ranges are remembered
        per option, so switching the axis parameter keeps the entered values."""
        self._axis_ranges = {k: s.image_axis_range(k) for k in IMAGE_AXIS_PARAMS}
        self._axis_shown: list = [None, None]
        self.axis_from = (QDoubleSpinBox(), QDoubleSpinBox())
        self.axis_to = (QDoubleSpinBox(), QDoubleSpinBox())
        for w in self.axis_from + self.axis_to:
            w.setKeyboardTracking(True)
        self._configure_image_axes()

    def _configure_image_axes(self) -> None:
        """Adapt the from/to spins to the image option on each axis."""
        for i, combo in enumerate((self.col_param, self.row_param)):
            key = combo.currentData()
            old = self._axis_shown[i]
            if old == key:
                continue
            lo_w, hi_w = self.axis_from[i], self.axis_to[i]
            if old in IMAGE_AXIS_PARAMS:
                self._axis_ranges[old] = (lo_w.value(), hi_w.value())
            self._axis_shown[i] = key
            if key not in IMAGE_AXIS_PARAMS:
                continue
            digits = IMAGE_AXIS_DIGITS.get(key, 1)
            rlo, rhi = IMAGE_OPTION_RANGES[key]
            unit = IMAGE_AXIS_UNITS[key]
            step = {"threshold": 16, "gamma": 0.1, "halftone_cpi": 5}.get(key, 5)
            for w, v in zip((lo_w, hi_w), self._axis_ranges[key]):
                w.blockSignals(True)
                w.setDecimals(digits)
                w.setRange(rlo, rhi)
                w.setSingleStep(step)
                w.setSuffix(f" {unit}" if unit else "")
                w.setValue(v)
                w.setToolTip(f"{AXIS_PARAM_LABELS[key]} je Zelle – ersetzt den Wert der "
                             "Bildoptionen für das ganze Raster.")
                w.blockSignals(False)

    def _image_axes(self) -> tuple[str, ...]:
        return tuple(p for p in self._axes() if p in IMAGE_AXIS_PARAMS)

    def image_axis_ranges(self) -> dict | None:
        """From/to of the image options on an axis (None without an image axis)."""
        out = {}
        for i, key in enumerate(self._axes()):
            if key in IMAGE_AXIS_PARAMS:
                lo, hi = self.axis_from[i].value(), self.axis_to[i].value()
                if IMAGE_AXIS_DIGITS.get(key, 1) == 0:
                    lo, hi = int(round(lo)), int(round(hi))
                out[key] = (lo, hi)
        return out or None

    def _build_image_options(self, s: MaterialTestSpec) -> None:
        """Extra image-mode parameters for all image cells (LightBurn applies the
        full image settings in an Interval Test). Start values: spec or defaults."""
        from lumacut_canvas.model import ImageSettings
        d = ImageSettings()
        o = dict(s.image_options or {})
        r = IMAGE_OPTION_RANGES

        def val(key):
            return o.get(key, getattr(d, key))

        self.opt_threshold = _spin(*r["threshold"], int(val("threshold")))
        self.opt_threshold.setToolTip("Schwellwert-Modus: Pixel dunkler als dieser Wert "
                                      "werden gelasert (0..255).")
        self.opt_cpi = _spin(*r["halftone_cpi"], float(val("halftone_cpi")), 1, 1, " /Zoll")
        self.opt_cpi.setToolTip("Halbton: Rasterzellen je Zoll (LightBurn „Cells per Inch“). "
                                "Weniger Zellen = gröbere Punkte.")
        self.opt_angle = _spin(*r["halftone_angle"], float(val("halftone_angle")), 7.5, 1, " °")
        self.opt_angle.setToolTip("Halbton: Rasterwinkel in Grad (LightBurn „Halftone Angle“).")
        self.opt_levels = _spin(*r["depth_levels"], int(val("depth_levels")))
        self.opt_levels.setToolTip("3D-Tiefe: Anzahl der Graustufen-Scheiben (Durchgänge "
                                   "je Bild). Dunkle Bereiche werden öfter gelasert.")
        self.opt_zstep = _spin(*r["z_step_mm"], float(val("z_step_mm")), 0.05, 2, " mm")
        self.opt_zstep.setToolTip("3D-Tiefe: Fokus je Stufe tiefer nachführen (0 = aus). "
                                  f"Gesamt höchstens {MAX_DEPTH_DROP_MM:g} mm.")
        self.opt_brightness = _spin(*r["brightness"], float(val("brightness")), 5, 1, " %")
        self.opt_brightness.setDecimals(0)
        self.opt_brightness.setToolTip("Helligkeit: + hellt auf (weniger lasern), − dunkelt ab. "
                                       "Gilt für alle Bild-Testzellen.")
        self.opt_contrast = _spin(*r["contrast"], float(val("contrast")), 5, 1, " %")
        self.opt_contrast.setDecimals(0)
        self.opt_contrast.setToolTip("Kontrast um Mittelgrau: +100 = 10-fach, −100 = ein Zehntel. "
                                     "Gilt für alle Bild-Testzellen.")
        self.opt_gamma = _spin(*r["gamma"], float(val("gamma")), 0.05, 2)
        self.opt_gamma.setToolTip("Gamma: > 1 hellt die Mitteltöne auf, < 1 dunkelt sie ab. "
                                  "Gilt für alle Bild-Testzellen.")
        self.opt_negative = QCheckBox("Negativ (Helles lasern)")
        self.opt_negative.setChecked(bool(val("negative")))
        self.opt_negative.setToolTip("Bild invertieren – z. B. für Schiefer oder eloxiertes Alu.")
        self._build_extra_options(o, d)
        self._opt_widgets = {"threshold": self.opt_threshold, "halftone_cpi": self.opt_cpi,
                             "halftone_angle": self.opt_angle, "depth_levels": self.opt_levels,
                             "z_step_mm": self.opt_zstep, "brightness": self.opt_brightness,
                             "contrast": self.opt_contrast, "gamma": self.opt_gamma,
                             "negative": self.opt_negative, "sharpen": self.opt_sharpen,
                             "sharpen_radius": self.opt_sharpen_radius,
                             "black_point": self.opt_black, "white_point": self.opt_white,
                             "curve": self.opt_curve, "dot_width_mm": self.opt_dot_width,
                             "scan_angle": self.opt_scan_angle,
                             "angle_increment": self.opt_angle_increment,
                             "bidirectional": self.opt_bidirectional,
                             "overscan_mm": self.opt_overscan}
        self._opt_rows = {"threshold": "opt_threshold", "halftone_cpi": "opt_cpi",
                          "halftone_angle": "opt_angle", "depth_levels": "opt_levels",
                          "z_step_mm": "opt_zstep", "brightness": "opt_brightness",
                          "contrast": "opt_contrast", "gamma": "opt_gamma",
                          "negative": "opt_negative", "sharpen": "opt_sharpen",
                          "sharpen_radius": "opt_sharpen_radius", "black_point": "opt_black",
                          "white_point": "opt_white", "curve": "opt_curve",
                          "dot_width_mm": "opt_dot_width", "scan_angle": "opt_scan_angle",
                          "angle_increment": "opt_angle_increment",
                          "bidirectional": "opt_bidirectional", "overscan_mm": "opt_overscan"}

    def _build_extra_options(self, o: dict, d) -> None:
        """„Weitere Bildoptionen“ (all modes): sharpen, levels, tone curve, dot width,
        scan angle, overscan, bidirectional. Hidden and not applied unless the
        checkbox is on; it starts on when the spec carries one of them."""
        from lumacut_canvas.model import normalize_curve
        from lumacut_import.curve_widget import CURVE_PRESETS, CUSTOM_LABEL
        r = IMAGE_OPTION_RANGES

        def val(key):
            return o.get(key, getattr(d, key))

        self.opt_more = QCheckBox("Weitere Bildoptionen (Schärfen, Tonwerte, Kurve, Scan)")
        self.opt_more.setChecked(any(k in o for k in IMAGE_EXTRA_OPTIONS))
        self.opt_more.setToolTip("Restliche Bildeinstellungen für alle Bild-Testzellen. "
                                 "Aus = Vorgaben der Bildeinstellungen.")
        self.opt_sharpen = _spin(*r["sharpen"], float(val("sharpen")), 10, 1, " %")
        self.opt_sharpen.setDecimals(0)
        self.opt_sharpen.setToolTip("Schärfen (Unscharf maskieren): betont Kanten und feine "
                                    "Details. 0 = aus.")
        self.opt_sharpen_radius = _spin(*r["sharpen_radius"], float(val("sharpen_radius")),
                                        0.5, 1, " Punkte")
        self.opt_sharpen_radius.setToolTip("Radius des Schärfens in Laserpunkten "
                                           "(Linienabstand).")
        self.opt_black = _spin(*r["black_point"], int(val("black_point")))
        self.opt_black.setToolTip("Schwarzpunkt: Grauwerte bis hier werden reines Schwarz "
                                  "(0..254).")
        self.opt_white = _spin(*r["white_point"], int(val("white_point")))
        self.opt_white.setToolTip("Weißpunkt: Grauwerte ab hier werden reines Weiß – muss "
                                  "größer als der Schwarzpunkt sein.")
        self.opt_curve = QComboBox()
        self._curve_choices = [normalize_curve(pts) for pts in CURVE_PRESETS.values()]
        for name in CURVE_PRESETS:
            self.opt_curve.addItem(name)
        cur = normalize_curve(val("curve"))
        if cur not in self._curve_choices:
            self._curve_choices.append(cur)
            self.opt_curve.addItem(CUSTOM_LABEL)
        self.opt_curve.setCurrentIndex(self._curve_choices.index(cur))
        self.opt_curve.setToolTip("Gradationskurve für alle Bild-Testzellen (Vorlagen wie in "
                                  "den Bildeinstellungen).")
        self.opt_dot_width = _spin(*r["dot_width_mm"], float(val("dot_width_mm")),
                                   0.01, 3, " mm")
        self.opt_dot_width.setToolTip("Punktbreitenkorrektur: jede gelaserte Strecke wird um "
                                      "diesen Wert kürzer (höchstens der kleinste "
                                      "Linienabstand). 0 = aus.")
        self.opt_scan_angle = _spin(*r["scan_angle"], float(val("scan_angle")), 15, 1, " °")
        self.opt_scan_angle.setToolTip("Rasterzeilen unter diesem Winkel lasern (0 = entlang X, "
                                       "90 = entlang Y).")
        self.opt_angle_increment = _spin(*r["angle_increment"], float(val("angle_increment")),
                                         15, 1, " °")
        self.opt_angle_increment.setToolTip("Jeder weitere Durchgang wird um diesen Winkel "
                                            "weiter gedreht (nur bei mehreren Durchgängen).")
        self.opt_overscan = _spin(*r["overscan_mm"], float(val("overscan_mm")), 0.5, 1, " mm")
        self.opt_overscan.setToolTip("Overscan: Anlauf/Auslauf ohne Leistung an jedem "
                                     "Zeilenende.")
        self.opt_bidirectional = QCheckBox("Bidirektional (hin und zurück lasern)")
        self.opt_bidirectional.setChecked(bool(val("bidirectional")))
        self.opt_bidirectional.setToolTip("Aus = jede Zeile in derselben Richtung (langsamer, "
                                          "ohne Hin-/Rück-Versatz).")

    def _option_keys(self) -> tuple[str, ...]:
        """Image options that apply to the chosen image mode (plus the further options
        when „Weitere Bildoptionen“ is on)."""
        keys = IMAGE_MODE_OPTIONS.get(self.image_mode.currentData(), ()) + IMAGE_ADJUST_OPTIONS
        return keys + IMAGE_EXTRA_OPTIONS if self.opt_more.isChecked() else keys

    def _option_value(self, key: str):
        w = self._opt_widgets[key]
        if key == "curve":
            return self._curve_choices[w.currentIndex()]
        return w.isChecked() if isinstance(w, QCheckBox) else w.value()

    def _min_interval(self) -> float:
        if "interval" in self._axes():
            return min(self.interval.value(), self.interval_max.value())
        return self.interval.value()

    def image_options(self) -> dict | None:
        """Options of the chosen mode that differ from the defaults (None = all default,
        so an untouched dialog gives the same spec / G-code as before)."""
        from lumacut_canvas.model import ImageSettings
        d = ImageSettings()
        out = {}
        swept = self._image_axes()
        for key in self._option_keys():
            if key in swept:
                continue                      # per cell from the axis
            v = self._option_value(key)
            if v != getattr(d, key):
                out[key] = v
        return out or None

    def _axes(self) -> tuple[str, str]:
        return self.col_param.currentData(), self.row_param.currentData()

    def _update_fields(self) -> None:
        """Range fields only for parameters on an axis; fixed value otherwise."""
        self._configure_image_axes()
        axes = self._axes()
        kind = self.mode.currentIndex()
        engrave = kind in (CELL_FILL, CELL_IMAGE)
        image = kind == CELL_IMAGE
        photo = image and self.image_source.currentData() == "photo"
        for key, w in (("image_source", self.image_source),
                       ("image_mode", self.image_mode), ("image_min", self.image_min)):
            self._rows[key].setVisible(image)
            w.setVisible(image)
        self._rows["photo"].setVisible(photo)
        img_mode = self.image_mode.currentData()
        for combo in (self.col_param, self.row_param):
            model = combo.model()
            for key in IMAGE_AXIS_PARAMS:
                need = image_axis_mode(key)
                model.item(combo.findData(key)).setEnabled(
                    image and (not need or need == img_mode))
        for i, key in enumerate(axes):
            on = key in IMAGE_AXIS_PARAMS
            name = AXIS_PARAM_LABELS[key]
            for row, w, text in ((("c_from", "r_from")[i], self.axis_from[i], f"{name} von"),
                                 (("c_to", "r_to")[i], self.axis_to[i], f"{name} bis")):
                self._rows[row].setText(text)
                self._rows[row].setVisible(on)
                w.setVisible(on)
        shown = (set(self._option_keys()) - set(self._image_axes())) if image else set()
        for key, w in self._opt_widgets.items():
            self._rows[self._opt_rows[key]].setVisible(key in shown)
            w.setVisible(key in shown)
        self._rows["opt_more"].setVisible(image)
        self.opt_more.setVisible(image)
        self.opt_sharpen_radius.setEnabled(self.opt_sharpen.value() > 0)
        more = image and self.opt_more.isChecked()
        self.photo_row.setVisible(photo)
        fields = {"power": ("p_min", "p_max", "Leistung", self.p_max),
                  "speed": ("s_min", "s_max", "Geschw.", self.s_max),
                  "passes": ("passes", "passes_max", "Durchgänge", self.passes_max),
                  "interval": ("interval", "interval_max", "Linienabstand", self.interval_max),
                  "focus": ("focus_min", "focus_max", "Fokus", self.focus_max)}
        for param, (lo, hi, name, hi_w) in fields.items():
            varied = param in axes
            self._rows[lo].setText(f"{name} von" if varied else name)
            hi_w.setEnabled(varied)
            self._rows[hi].setEnabled(varied)
        # Fokus von/bis only when focus is on an axis (LightBurn Focus Test).
        focus_on = "focus" in axes
        for key, w in (("focus_min", self.focus_min), ("focus_max", self.focus_max)):
            self._rows[key].setVisible(focus_on)
            w.setVisible(focus_on)
        self.interval.setEnabled(engrave)
        self._rows["interval"].setEnabled(engrave)
        self._rows["cols"].setText(f"Spalten ({AXIS_PARAM_LABELS[axes[0]]})")
        self._rows["rows"].setText(f"Zeilen ({AXIS_PARAM_LABELS[axes[1]]})")
        problem = ""
        if axes[0] == axes[1]:
            problem = "Spalten und Zeilen brauchen verschiedene Parameter."
        elif self._image_axis_problem(image, img_mode):
            problem = self._image_axis_problem(image, img_mode)
        elif "interval" in axes and not engrave:
            problem = "Linienabstand-Test nur mit „Füllen (Gravur)“ oder „Bild“."
        elif image and self.image_min.value() > self.p_min.value():
            problem = "Min.-Leistung (Weiß) darf die kleinste Leistung nicht übersteigen."
        elif photo and not self._photo_png:
            problem = "Eigenes Bild fehlt – bitte eine Bilddatei wählen."
        elif (image and self.image_mode.currentData() == "depth3d"
              and self.opt_zstep.value() * (self.opt_levels.value() - 1)
              > MAX_DEPTH_DROP_MM + 1e-9):
            drop = self.opt_zstep.value() * (self.opt_levels.value() - 1)
            problem = (f"Fokus-Absenkung {drop:.2f} mm > {MAX_DEPTH_DROP_MM:g} mm – "
                       "Z-Schritt oder 3D-Stufen verkleinern.")
        elif more and self.opt_black.value() >= self.opt_white.value():
            problem = "Schwarzpunkt muss kleiner als der Weißpunkt sein."
        elif more and self.opt_dot_width.value() > self._min_interval() + 1e-9:
            problem = (f"Punktbreitenkorrektur {self.opt_dot_width.value():g} mm > kleinster "
                       f"Linienabstand {self._min_interval():g} mm.")
        elif "focus" in axes and self.focus_min.value() == self.focus_max.value():
            problem = "Fokus von und bis müssen verschieden sein."
        self.hint.setText(problem)
        self.hint.setVisible(bool(problem))
        self.bb.button(QDialogButtonBox.Ok).setEnabled(not problem)

    def _image_axis_problem(self, image: bool, img_mode: str) -> str:
        """German hint for an image-option axis that cannot run ("" = fine)."""
        for i, key in enumerate(self._axes()):
            if key not in IMAGE_AXIS_PARAMS:
                continue
            name = AXIS_PARAM_LABELS[key]
            if not image:
                return f"„{name}“ als Achse nur mit Art „Bild“."
            need = image_axis_mode(key)
            if need and need != img_mode:
                return (f"{name}-Achse nur im Bildmodus "
                        f"„{IMAGE_AXIS_MODE_LABELS.get(need, need)}“.")
            ranges = self.image_axis_ranges() or {}
            lo, hi = ranges[key]
            n = (self.cols, self.rows)[i].value()
            digits = IMAGE_AXIS_DIGITS.get(key, 1)
            vals = {round(lo + (hi - lo) * j / max(1, n - 1), digits) for j in range(n)}
            if lo == hi or len(vals) < n:
                return f"{name} von und bis müssen verschieden sein."
        return ""

    def spec(self) -> MaterialTestSpec:
        return MaterialTestSpec(
            power_min=self.p_min.value(), power_max=self.p_max.value(), columns=self.cols.value(),
            speed_min=self.s_min.value(), speed_max=self.s_max.value(), rows=self.rows.value(),
            cell_mm=self.cell.value(), gap_mm=self.gap.value(), x=self.x.value(), y=self.y.value(),
            passes=self.passes.value(),
            line_interval_mm=(0.0 if self.mode.currentIndex() == CELL_OUTLINE
                              else self.interval.value()),
            labels=self.labels.isChecked(),
            column_param=self.col_param.currentData(), row_param=self.row_param.currentData(),
            interval_max=self.interval_max.value(), passes_max=self.passes_max.value(),
            focus_min=self.focus_min.value(), focus_max=self.focus_max.value(),
            image_mode=(self.image_mode.currentData()
                        if self.mode.currentIndex() == CELL_IMAGE else ""),
            image_min_power=(self.image_min.value()
                             if self.mode.currentIndex() == CELL_IMAGE else 0.0),
            image_source=(self.image_source.currentData()
                          if self.mode.currentIndex() == CELL_IMAGE else "ramp"),
            image_png=(self._photo_png
                       if (self.mode.currentIndex() == CELL_IMAGE
                           and self.image_source.currentData() == "photo") else None),
            image_options=(self.image_options()
                           if self.mode.currentIndex() == CELL_IMAGE else None),
            image_axis_ranges=(self.image_axis_ranges()
                               if self.mode.currentIndex() == CELL_IMAGE else None))


    def _pick_photo(self) -> None:
        """Load a user photo as 8-bit grey PNG for the image cells."""
        from lumacut_import.image import grayscale_png
        from lumacut_import.placement import IMAGE_SUFFIXES
        from PySide6.QtGui import QImageReader

        filt = ("Bild (" + " ".join(f"*{s}" for s in IMAGE_SUFFIXES) + ")")
        path, _ = QFileDialog.getOpenFileName(self, "Testbild wählen", "", filt)
        if not path:
            return
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        img = reader.read()
        if img.isNull():
            QMessageBox.warning(self, "Bild", f"Bild nicht lesbar: {reader.errorString()}")
            return
        # Cap long side so a photo test cell stays snappy (same order as the ramp).
        from PySide6.QtCore import Qt
        long_side = max(img.width(), img.height())
        max_side = 512
        if long_side > max_side:
            img = img.scaled(img.width() * max_side // long_side,
                             img.height() * max_side // long_side,
                             Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        try:
            png, _, _ = grayscale_png(img)
        except ValueError as exc:
            QMessageBox.warning(self, "Bild", str(exc))
            return
        self._photo_png = png
        self._photo_path = path
        from pathlib import Path
        self.photo_label.setText(Path(path).name)
        self._update_fields()


def insert_material_test(editor, spec: MaterialTestSpec) -> int:
    """Add the grid to the editor's document as one undo step. Returns #layers."""
    layers, shapes = build_material_test(spec)
    stack = editor.undo_stack
    stack.beginMacro("Materialtest einfügen")
    try:
        for layer in reversed(layers):
            stack.push(AddLayerCommand(editor.document, layer, 0))
        stack.push(AddShapesCommand(editor.document, shapes, "Materialtest"))
    finally:
        stack.endMacro()
    return len(layers)


class JobTools(QObject):
    def __init__(self, window, editor, machine_panel, status_bar):
        super().__init__(window)
        self.window = window
        self.editor = editor
        self.machine = machine_panel
        self.status = status_bar
        self.toolbar = QToolBar("Auftrag")
        self.toolbar.setObjectName("lumacut_job_toolbar")
        self.toolbar.setMovable(False)
        self.estimate_action = self._add("Zeit schätzen", self.show_estimate, "Alt+P",
                                         "Laufzeit, Schnitt- und Leerfahrtstrecke berechnen")
        self.frame_action = self._add("Rahmen", self.frame_job, "Ctrl+Shift+F",
                                      "Umriss des Auftrags mit ausgeschaltetem Laser abfahren")
        self.hull_action = self._add("Gummiband-Rahmen", lambda: self.frame_job("hull"), "Alt+Shift+F",
                                     "Konvexe Hülle statt Rechteck abfahren")
        self.test_action = self._add("Materialtest…", self.material_test, None,
                                     "Leistung × Geschwindigkeit-Testraster einfügen")
        self.serial_action = self._add("Seriennummern…", self.serial_numbers, "Alt+N",
                                       "Ausgewählten Text als Raster fortlaufend nummerierter Kopien "
                                       "(Platzhalter {n}, {n:3}, {date})")
        self.serial_action.setObjectName("serial_numbers_action")
        self.vartext_action = self._add("Variabler Text…", self.variable_text, "Alt+V",
                                        "Ausgewählte Texte beim Senden auswerten: Zähler {n}, "
                                        "Datum/Uhrzeit, CSV-Spalten {Name} – zählt nach jedem "
                                        "gesendeten Auftrag weiter")
        self.vartext_action.setObjectName("variable_text_action")
        self.qr_action = self._add("QR-Code…", self.qr_code, "Alt+Q",
                                   "QR-Code (Text/Adresse) als gefüllte Vektorflächen einfügen")
        self.qr_action.setObjectName("qr_code_action")
        self.barcode_action = self._add("Barcode einfügen…", self.barcode, "Alt+C",
                                        "Strichcode (Code 128, EAN-13/-8, UPC-A) als gefüllte "
                                        "Vektorstriche einfügen")
        self.barcode_action.setObjectName("barcode_action")
        self.datamatrix_action = self._add("Data Matrix…", self.datamatrix, "Alt+X",
                                           "2D-Code Data Matrix (ECC 200) als gefüllte "
                                           "Vektorflächen einfügen")
        self.datamatrix_action.setObjectName("datamatrix_action")
        self.aztec_action = self._add("Aztec-Code…", self.aztec, "Alt+Z",
                                      "2D-Code Aztec (kompakt, ohne Ruhezone) als gefüllte "
                                      "Vektorflächen einfügen")
        self.aztec_action.setObjectName("aztec_action")
        self.pdf417_action = self._add("PDF417-Code…", self.pdf417, "Alt+F",
                                       "Gestapelter 2D-Code PDF417 (auch kompakt) als gefüllte "
                                       "Vektorflächen einfügen")
        self.pdf417_action.setObjectName("pdf417_action")
        self.arc_action = self._add("Bogentext…", self.arc_text, "Alt+B",
                                    "Text entlang eines Kreisbogens als Vektorpfade einfügen "
                                    "(ausgewählter Text wird übernommen)")
        self.arc_action.setObjectName("arc_text_action")
        self.edit_generated_action = self._add(
            "Code bearbeiten…", self.edit_generated, "Alt+E",
            "Ausgewählten QR-Code, Barcode, Data Matrix, Aztec-, PDF417-Code oder Bogentext mit seinen "
            "Parametern "
            "neu erzeugen (auch per Doppelklick)")
        self.edit_generated_action.setObjectName("edit_generated_action")
        # Double click with the select tool (lumacut_canvas.tools) asks this hook first.
        editor.generated_edit_handler = self.edit_generated_at
        self.cut_action = self._add("Schnittoptionen…", self.cut_options, "Alt+K",
                                    "Kerf-Versatz, Haltestege und An-/Abfahrt der aktiven Ebene")
        self.scan_offset_action = self._add(
            "Scan-Versatz…", self.scan_offset, None,
            "Versatz hin-/rücklaufender Linien je Geschwindigkeit ausgleichen (Bilder und "
            "Schraffur, wie LightBurn „Scanning Offset Adjustment“) – mit Testmuster")
        self.scan_offset_action.setObjectName("scan_offset_action")
        self._load_scan_offset()
        self.selection_action = self._add("Nur Auswahl", self._selection_toggled, None,
                                          "Senden, Schätzen, Rahmen und Speichern nur mit den "
                                          "ausgewählten Objekten (wie „Cut Selected Graphics“)")
        self.selection_action.setCheckable(True)
        # Variable text: next value of every variable text as a label on the canvas.
        from .scan_offset_qt import default_settings
        from .vartext_preview import VarTextValues, load_enabled
        self.vartext_values = VarTextValues(editor, lambda: JobTools._job_source(self),
                                            load_enabled(default_settings()))
        self.save_action = self._add("G-Code speichern…", self.save_gcode, "Alt+G",
                                     "Optimierten G-Code des Designs als Datei speichern")
        self.history_action = self._add("Verlauf…", self.show_history, "Ctrl+H",
                                        "Zuletzt gesendete Aufträge erneut senden oder speichern")
        window.addToolBar(self.toolbar)
        from .history import JobHistory
        from .history_qt import attach_history, default_dir
        self.history = JobHistory(default_dir())
        self._send_without_history = (attach_history(machine_panel, self.history)
                                      if hasattr(machine_panel, "send_gcode") else None)
        if hasattr(machine_panel, "send_gcode"):
            # Park corner (Pi 9ae8577): refuse before uploading, not at the Pi.
            from .park_corner import attach_park_check
            attach_park_check(machine_panel, lambda text: self._msg(text, 15000))
        # Park corner as a red hatched no-go zone on the canvas (follows the origin; live warning).
        self.park_zone = None
        if hasattr(editor, "add_overlay"):
            from .park_zone import install_park_zone
            self.park_zone = install_park_zone(
                editor, machine_panel, self, report=lambda text: self._msg(text, 10000),
                selection_only=lambda: bool(getattr(self, "selection_only", False)))
        # Variable text (lumacut_job.vartext): outermost wrapper, advances after a successful upload.
        self.vartext_tracker = None
        if hasattr(machine_panel, "send_gcode"):
            from .vartext_qt import VarTextTracker
            self.vartext_tracker = VarTextTracker(editor, machine_panel,
                                                  lambda text: self._msg(text, 10000), self)
        if hasattr(machine_panel, "set_frame_provider"):
            machine_panel.set_frame_provider(self.frame_program)
        signal = getattr(machine_panel, "frame_available_changed", None)
        if signal is not None:
            signal.connect(self._sync_frame_actions)
            self._sync_frame_actions(bool(getattr(machine_panel, "frame_available", False)))

    def _sync_frame_actions(self, available: bool) -> None:
        tip = "" if available else " (erst verbinden und referenzieren; nicht während Auftrag)"
        for action, text in ((self.frame_action, "Umriss des Auftrags mit ausgeschaltetem Laser abfahren"),
                             (self.hull_action, "Konvexe Hülle statt Rechteck abfahren")):
            action.setEnabled(available)
            action.setToolTip(text + tip)

    def _add(self, text, slot, shortcut, tip):
        a = QAction(text, self.window)
        a.setToolTip(tip)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(lambda _=False: slot())
        self.toolbar.addAction(a)
        return a

    def _msg(self, text, ms=8000):
        self.status.showMessage(text, ms)

    # --- Auftrag (ganzes Design oder nur Auswahl) ---------------------------
    @property
    def selection_only(self) -> bool:
        return self.selection_action.isChecked()

    def set_selection_only(self, on: bool) -> None:
        self.selection_action.setChecked(bool(on))
        self._selection_toggled()

    def _selection_toggled(self) -> None:
        values = getattr(self, "vartext_values", None)
        if values is not None:
            values.schedule()
        zone = getattr(self, "park_zone", None)
        if zone is not None:
            zone.update()
        self._msg("Auftrag: nur ausgewählte Objekte" if self.selection_only
                  else "Auftrag: ganzes Design")

    def _job_source(self):
        doc = self.editor.document
        if not getattr(self, "selection_only", False):
            return doc
        from .selection import selection_document
        return selection_document(doc, getattr(self.editor, "selection", ()) or ())

    def job_document_and_usage(self):
        """(Auftragsdokument, verwendete variable Texte) – Platzhalter ausgewertet."""
        from .vartext import evaluate_document
        return evaluate_document(JobTools._job_source(self))

    def job_document(self):
        """Dokument für den Auftrag; ValueError bei „Nur Auswahl“ ohne Auswahl.

        Variable Texte sind darin schon ausgewertet (das Original behält die
        Vorlage); ValueError, wenn ein Platzhalter nicht auswertbar ist."""
        return JobTools.job_document_and_usage(self)[0]

    def job_gcode(self) -> tuple[str, str]:
        """(optimierter G-Code, Hinweis des Planers) – wie beim Senden.

        Der Hinweis meldet z. B. weggelassene An-/Abfahrten (Kollision mit
        anderen Teilen) und ist leer, wenn nichts zu melden ist. Mit variablem
        Text trägt der G-Code eine Markierung, damit das Hochladen genau dieses
        Auftrags Zähler/CSV-Zeile weiterschaltet.
        """
        report = PlanReport()
        doc, usage = self.job_document_and_usage()
        g = optimized_document_gcode(doc, report=report)
        note = report.message()
        if usage:
            tracker = getattr(self, "vartext_tracker", None)
            if tracker is not None:
                g = tracker.remember(g, usage)
            note = (note + " " + usage.summary()).strip()
        if self.selection_only:
            note = ("Nur Auswahl. " + note).strip()
        return g, note

    def estimate(self):
        return estimate_gcode(self.job_gcode()[0])

    def park_preflight(self, gcode: str, origin: str | None = None) -> str:
        """German refusal text if the Pi would refuse ``gcode`` because of the
        park corner (as sent, and at the panel's chosen origin unless
        ``origin`` is given), else ""."""
        from .park_corner import check_for_panel
        res = check_for_panel(self.machine, gcode, "absolute")
        if res.ok and origin != "absolute":
            res = check_for_panel(self.machine, gcode, origin)
        return "" if res.ok else res.message

    def show_estimate(self):
        try:
            g, note = self.job_gcode()
        except ValueError as exc:
            self._msg(f"Keine Schätzung: {exc}")
            return None
        est = estimate_gcode(g)
        text = f"Auftrag {est.summary()} (ohne Referenzfahrt/Fokus/Parken)"
        if est.layer_summary():
            text += f" – {est.layer_summary()}"
        if note:
            text += f" – {note}"
        park = self.park_preflight(g)
        if park:
            text += f" – {park}"
        self._msg(text, 15000)
        return est

    def frame_program(self, mode: str = "box") -> str:
        """Frame G-code (laser off) of the current design; ValueError if empty."""
        from .images import image_outline_layers
        doc = JobTools.job_document(self)
        return frame_gcode(optimize_layers(job_layers(doc)) + image_outline_layers(doc), mode=mode)

    def frame_job(self, mode: str = "box", confirm: bool = True):
        try:
            g = self.frame_program(mode)
        except ValueError as exc:
            self._msg(f"Rahmen nicht möglich: {exc}")
            return None
        if confirm and QMessageBox.question(
                self.window, "Rahmen",
                "Umriss mit ausgeschaltetem Laser abfahren?\n"
                "Der gesendete Auftrag bleibt geladen und kann danach direkt "
                "gestartet werden.") != QMessageBox.Yes:
            return None
        if not self.machine.frame_gcode(g, mode):
            self._msg("Rahmen nicht gestartet – siehe Maschinen-Panel")
            return None
        self._msg("Rahmenfahrt angefordert (Laser aus) – gesendeter Auftrag bleibt geladen")
        return g

    def material_test(self, spec: MaterialTestSpec | None = None):
        if spec is None:
            dlg = MaterialTestDialog(self.window)
            if dlg.exec() != QDialog.Accepted:
                return 0
            spec = dlg.spec()
        try:
            n = insert_material_test(self.editor, spec)
        except ValueError as exc:
            self._msg(f"Materialtest: {exc}")
            return 0
        self._msg(f"Materialtest mit {n} Ebenen eingefügt")
        return n


    def serial_numbers(self, spec=None) -> list[str]:
        """Ausgewählten Text durch nummerierte Kopien ersetzen (ein Undo-Schritt)."""
        from .serial_qt import SerialDialog, insert_serials
        doc = self.editor.document
        sel = [i for i in self.editor.selection if doc.has_shape(i)]
        if len(sel) != 1 or doc.shape(sel[0]).kind != "text":
            self._msg("Seriennummern: bitte genau ein Textobjekt auswählen")
            return []
        src = doc.shape(sel[0])
        if spec is None:
            dlg = SerialDialog(src.text, self.window)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec = dlg.spec()
        try:
            ids = insert_serials(self.editor, src.id, spec)
        except ValueError as exc:
            QMessageBox.warning(self.window, "Seriennummern", str(exc))
            self._msg(f"Seriennummern: {exc}")
            return []
        self._msg(f"{len(ids)} nummerierte Texte erzeugt (gruppiert)")
        return ids

    def variable_text(self, spec=None, template: str | None = None,
                      enabled: bool = True) -> list[str]:
        """Ausgewählte Texte als variablen Text einstellen (ein Undo-Schritt).

        Alle ausgewählten Texte (und die übrigen Kopien ihrer Serie) bilden
        eine Serie. ``spec`` ohne Dialog (Tests/Skripte); ``enabled=False``
        macht sie wieder zu normalem Text.
        """
        from . import vartext as vt
        from .vartext_qt import VarTextDialog, apply_vartext, describe, series_members
        doc = self.editor.document
        sel = [i for i in self.editor.selection
               if doc.has_shape(i) and doc.shape(i).kind == "text"]
        if not sel:
            self._msg("Variabler Text: bitte ein oder mehrere Textobjekte auswählen")
            return []
        keys = {vt.series_key(doc.shape(i)) for i in sel if vt.is_variable(doc.shape(i))}
        ids = list(sel)
        for key in keys:
            ids += [s.id for s in series_members(doc, key) if s.id not in ids]
        first = next((doc.shape(i) for i in ids if vt.is_variable(doc.shape(i))), None)
        start = vt.spec_of(first) if first is not None else vt.VarTextSpec()
        same = len(keys) == 1 and all(vt.is_variable(doc.shape(i)) for i in ids)
        series = start.series if same else ""
        if spec is None:
            visible = {l.id for l in doc.layers if l.visible}
            copies = sum(1 for i in ids if doc.shape(i).layer_id in visible) or 1
            values = getattr(self, "vartext_values", None)
            dlg = VarTextDialog(doc.shape(sel[0]).text, replace(start, series=series), copies,
                                parent=self.window,
                                show_values=values.enabled if values is not None else True)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec, template, enabled = dlg.spec(), dlg.template_text(), dlg.is_enabled()
            self.set_vartext_values_shown(dlg.show_values.isChecked())
        else:
            spec = replace(spec, series=spec.series or series)
        try:
            changed = apply_vartext(self.editor, ids, spec if enabled else None, template)
        except ValueError as exc:
            self._msg(f"Variabler Text: {exc}")
            return []
        if not enabled:
            self._msg(f"Variabler Text aus – {len(changed)} Text(e) werden wörtlich gelasert")
            return changed
        tmpl = doc.shape(changed[0]).text
        if not vt.has_placeholders(tmpl):
            self._msg("Variabler Text: die Vorlage enthält noch keinen Platzhalter, z. B. "
                      "„Nr. {n:3}“ oder „{Name}“")
        else:
            self._msg(f"Variabler Text für {len(changed)} Text(e): "
                      f"{describe(vt.spec_of(doc.shape(changed[0])), tmpl)} – wird beim Senden "
                      "ausgewertet")
        return changed

    def qr_code(self, spec=None, fill_layer: bool | None = None) -> list[str]:
        """QR-Code einfügen (ein Undo-Schritt); Standard: aktive Ebene."""
        from .qr_qt import QrDialog, insert_qr, layer_fills
        doc = self.editor.document
        active = doc.active_layer or (doc.layers[0] if doc.layers else None)
        if spec is None:
            dlg = QrDialog(self.window, active_layer=active)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec, fill_layer = dlg.spec(), dlg.fill_layer()
        if fill_layer is None:
            fill_layer = not layer_fills(active)
        try:
            ids = insert_qr(self.editor, spec, fill_layer=fill_layer)
        except ValueError as exc:
            QMessageBox.warning(self.window, "QR-Code", str(exc))
            self._msg(f"QR-Code: {exc}")
            return []
        layer = doc.shape(ids[0]).layer_id if ids else ""
        name = doc.layer(layer).name if layer else ""
        kind = {"gs1": "GS1 QR-Code", "link": "GS1-Digital-Link-QR-Code"}.get(
            spec.normalized().mode, "QR-Code")
        self._msg(f"{kind} eingefügt ({len(ids)} Flächen, Ebene „{name}“)")
        return ids

    def barcode(self, spec=None, fill_layer: bool | None = None) -> list[str]:
        """Insert a 1D barcode (one undo step); default: active layer."""
        from .barcode_qt import BarcodeDialog, insert_barcode
        from .qr_qt import layer_fills
        doc = self.editor.document
        active = doc.active_layer or (doc.layers[0] if doc.layers else None)
        if spec is None:
            dlg = BarcodeDialog(self.window, active_layer=active)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec, fill_layer = dlg.spec(), dlg.fill_layer()
        if fill_layer is None:
            fill_layer = not layer_fills(active)
        try:
            ids = insert_barcode(self.editor, spec, fill_layer=fill_layer)
        except ValueError as exc:
            QMessageBox.warning(self.window, "Barcode", str(exc))
            self._msg(f"Barcode: {exc}")
            return []
        layer = doc.shape(ids[0]).layer_id if ids else ""
        name = doc.layer(layer).name if layer else ""
        self._msg(f"Barcode eingefügt ({len(ids)} Flächen, Ebene „{name}“)")
        return ids

    def datamatrix(self, spec=None, fill_layer: bool | None = None) -> list[str]:
        """Insert a Data Matrix ECC 200 symbol (one undo step); default: active layer."""
        from .datamatrix_qt import DataMatrixDialog, insert_datamatrix
        from .qr_qt import layer_fills
        doc = self.editor.document
        active = doc.active_layer or (doc.layers[0] if doc.layers else None)
        if spec is None:
            dlg = DataMatrixDialog(self.window, active_layer=active)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec, fill_layer = dlg.spec(), dlg.fill_layer()
        if fill_layer is None:
            fill_layer = not layer_fills(active)
        try:
            ids = insert_datamatrix(self.editor, spec, fill_layer=fill_layer)
        except ValueError as exc:
            QMessageBox.warning(self.window, "Data Matrix", str(exc))
            self._msg(f"Data Matrix: {exc}")
            return []
        layer = doc.shape(ids[0]).layer_id if ids else ""
        name = doc.layer(layer).name if layer else ""
        self._msg(f"Data Matrix eingefügt ({len(ids)} Flächen, Ebene „{name}“)")
        return ids

    def aztec(self, spec=None, fill_layer: bool | None = None) -> list[str]:
        """Insert an Aztec code (one undo step); default: active layer."""
        from .aztec_qt import AztecDialog, insert_aztec
        from .qr_qt import layer_fills
        doc = self.editor.document
        active = doc.active_layer or (doc.layers[0] if doc.layers else None)
        if spec is None:
            dlg = AztecDialog(self.window, active_layer=active)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec, fill_layer = dlg.spec(), dlg.fill_layer()
        if fill_layer is None:
            fill_layer = not layer_fills(active)
        try:
            ids = insert_aztec(self.editor, spec, fill_layer=fill_layer)
        except ValueError as exc:
            QMessageBox.warning(self.window, "Aztec-Code", str(exc))
            self._msg(f"Aztec-Code: {exc}")
            return []
        layer = doc.shape(ids[0]).layer_id if ids else ""
        name = doc.layer(layer).name if layer else ""
        self._msg(f"Aztec-Code eingefügt ({len(ids)} Flächen, Ebene „{name}“)")
        return ids

    def pdf417(self, spec=None, fill_layer: bool | None = None) -> list[str]:
        """Insert a PDF417 code (one undo step); default: active layer."""
        from .pdf417_qt import Pdf417Dialog, insert_pdf417
        from .qr_qt import layer_fills
        doc = self.editor.document
        active = doc.active_layer or (doc.layers[0] if doc.layers else None)
        if spec is None:
            dlg = Pdf417Dialog(self.window, active_layer=active)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec, fill_layer = dlg.spec(), dlg.fill_layer()
        if fill_layer is None:
            fill_layer = not layer_fills(active)
        try:
            ids = insert_pdf417(self.editor, spec, fill_layer=fill_layer)
        except ValueError as exc:
            QMessageBox.warning(self.window, "PDF417-Code", str(exc))
            self._msg(f"PDF417-Code: {exc}")
            return []
        layer = doc.shape(ids[0]).layer_id if ids else ""
        name = doc.layer(layer).name if layer else ""
        self._msg(f"PDF417-Code eingefügt ({len(ids)} Flächen, Ebene „{name}“)")
        return ids

    def arc_text(self, spec=None, replace: bool | None = None) -> list[str]:
        """Bogentext einfügen (ein Undo-Schritt); ein ausgewählter Text wird übernommen."""
        from .arctext_qt import ArcTextDialog, insert_arc_text, spec_from_text
        doc = self.editor.document
        sel = [i for i in (self.editor.selection or ()) if doc.has_shape(i)]
        src = doc.shape(sel[0]) if len(sel) == 1 and doc.shape(sel[0]).kind == "text" else None
        if spec is None:
            dlg = ArcTextDialog(self.window, spec_from_text(src) if src else None,
                                can_replace=src is not None)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec, replace = dlg.spec(), dlg.replace_source()
        replace_id = src.id if (src is not None and replace) else None
        try:
            ids = insert_arc_text(self.editor, spec, replace_id)
        except ValueError as exc:
            QMessageBox.warning(self.window, "Bogentext", str(exc))
            self._msg(f"Bogentext: {exc}")
            return []
        self._msg(f"Bogentext eingefügt ({len(ids)} Zeichen, gruppiert)"
                  + (" – Text ersetzt" if replace_id else ""))
        return ids

    def set_vartext_values_shown(self, on: bool) -> None:
        """Labels with the next values of variable texts on/off (stored in the settings)."""
        from .scan_offset_qt import default_settings
        from .vartext_preview import save_enabled
        values = getattr(self, "vartext_values", None)
        if values is not None and values.enabled != bool(on):
            values.set_enabled(on)
        save_enabled(default_settings(), on)

    def edit_generated_at(self, shape_id: str) -> bool:
        """Double-click hook: True if ``shape_id`` belongs to a generated object
        (the dialog was shown, even if cancelled)."""
        from .generated_qt import generated_unit
        from .vartext import is_variable
        doc = self.editor.document
        if doc.has_shape(shape_id) and is_variable(doc.shape(shape_id)):
            return False   # variable text: double click edits the template as usual
        try:
            unit = generated_unit(self.editor, shape_id)
        except ValueError as exc:
            self._msg(str(exc))
            return True
        if unit is None:
            return False
        self.edit_generated(shape_id=shape_id)
        return True

    def edit_generated(self, spec=None, shape_id: str | None = None) -> list[str]:
        """Re-create the selected QR code / barcode / Data Matrix / arc text with
        changed parameters (one undo step, same place, rotation and layer)."""
        from .generated_qt import edit_dialog, generated_unit, replace_unit, unit_spec
        try:
            unit = generated_unit(self.editor, shape_id)
        except ValueError as exc:
            self._msg(f"Code bearbeiten: {exc}")
            return []
        if unit is None:
            self._msg("Code bearbeiten: bitte einen QR-Code, Barcode, Data Matrix oder "
                      "Bogentext auswählen (Doppelklick genügt)")
            return []
        doc = self.editor.document
        if spec is None:
            try:
                start = unit_spec(unit)
            except ValueError as exc:
                self._msg(f"{unit.label} bearbeiten: {exc}")
                return []
            dlg = edit_dialog(unit, start, doc.layer(unit.layer_id), self.window)
            if dlg.exec() != QDialog.Accepted:
                return []
            spec = dlg.spec()
        try:
            ids = replace_unit(self.editor, unit, spec)
        except ValueError as exc:
            QMessageBox.warning(self.window, f"{unit.label} bearbeiten", str(exc))
            self._msg(f"{unit.label}: {exc}")
            return []
        self._msg(f"{unit.label} neu erzeugt ({len(ids)} Flächen, Ebene "
                  f"„{doc.layer(unit.layer_id).name}“)")
        return ids

    def cut_options(self, values: dict | None = None) -> bool:
        """Schnittoptionen der aktiven Ebene bearbeiten (ein Undo-Schritt)."""
        from .cut_qt import CutOptionsDialog, apply_cut_options, summary
        doc = self.editor.document
        layer = doc.active_layer or (doc.layers[0] if doc.layers else None)
        if layer is None:
            self._msg("Schnittoptionen: keine Ebene vorhanden")
            return False
        if values is None:
            dlg = CutOptionsDialog(layer, self.window)
            if dlg.exec() != QDialog.Accepted:
                return False
            values = dlg.values()
        changed = apply_cut_options(self.editor, layer.id, values)
        text = summary(doc.layer(layer.id)) or "alle aus"
        self._msg(f"Schnittoptionen „{layer.name}“: {text}" if changed
                  else "Schnittoptionen unverändert")
        return changed


    # --- Scan-Versatz (lumacut_job.scan_offset) ------------------------------
    def _load_scan_offset(self) -> None:
        from .scan_offset import set_active_table
        from .scan_offset_qt import default_settings, load_table
        table = load_table(default_settings())
        if table is not None:
            set_active_table(table)
            self._refresh_scan_previews()

    def _refresh_scan_previews(self) -> None:
        """Pfad- und Schraffur-Vorschau neu berechnen (Scan-Versatz geändert)."""
        for name in ("path_preview", "fill_preview"):
            preview = getattr(self.editor, name, None)
            if callable(getattr(preview, "schedule", None)):
                preview.schedule()

    def scan_offset(self, table=None):
        """Scan-Versatz-Tabelle bearbeiten, aktivieren und speichern.

        ``table`` (Tests) überspringt den Dialog. Gibt die neue Tabelle
        zurück oder None (abgebrochen)."""
        from .scan_offset import active_table, set_active_table
        from .scan_offset_qt import ScanOffsetDialog, default_settings, save_table
        if table is None:
            dlg = ScanOffsetDialog(active_table(), self.window,
                                   test_callback=lambda d: self.scan_test(parent=d))
            if dlg.exec() != QDialog.Accepted:
                return None
            table = dlg.table()
        try:
            table = table.normalized()
        except ValueError as exc:
            self._msg(str(exc))
            return None
        set_active_table(table)
        save_table(default_settings(), table)
        self._refresh_scan_previews()   # Pfad-/Schraffur-Vorschau = Auftrag, mit neuem Versatz
        self._msg(table.summary() + " – gilt für Bilder und Schraffur" if table.active
                  else "Scan-Versatz aus")
        return table

    def scan_test(self, spec=None, action: str | None = None, path: str | None = None,
                  parent=None) -> str:
        """Kalibrier-Testmuster: Dialog, oder mit ``spec`` direkt ``action``
        "send" (hochladen ohne Start) / "save" (``path``). Gibt den G-Code zurück."""
        from .scan_offset import test_pattern_gcode
        from .scan_offset_qt import ScanTestDialog

        def send(g):
            if not hasattr(self.machine, "send_gcode"):
                self._msg("Scan-Test: kein Maschinen-Panel")
                return
            self.machine.send_gcode("scan-versatz-test.gcode", g, start=False)
            self._msg("Scan-Versatz-Test gesendet – mit „Start“ ausführen, dann je Reihe das "
                      "Feld mit geraden Kanten in die Tabelle übernehmen", 15000)

        def save(g, target=None):
            from .history_qt import save_gcode_file
            if target is None:
                target = save_gcode_file(parent or self.window, g, "scan-versatz-test.gcode")
            else:
                from pathlib import Path
                Path(target).write_text(g, encoding="utf-8", newline="\n")
            if target:
                self._msg(f"Scan-Versatz-Test gespeichert: {target}")

        if spec is None:
            dlg = ScanTestDialog(None, parent or self.window, send, save)
            dlg.exec()
            return dlg.result_gcode
        try:
            g = test_pattern_gcode(spec)
        except ValueError as exc:
            self._msg(str(exc))
            return ""
        if action == "send":
            send(g)
        elif action == "save":
            save(g, path)
        return g

    def save_gcode(self, path: str | None = None) -> str:
        """Optimierten G-Code (wie beim Senden, ohne Scan-Fokuskorrektur) speichern."""
        from .history_qt import save_gcode_file
        try:
            g, note = self.job_gcode()
        except ValueError as exc:
            self._msg(f"Speichern nicht möglich: {exc}")
            return ""
        fp = getattr(self.editor, "file_path", None)
        name = (fp.name.split(".")[0] if fp else "auftrag") + ".gcode"
        if path is None:
            path = save_gcode_file(self.window, g, name)
        else:
            from pathlib import Path
            Path(path).write_text(g, encoding="utf-8", newline="\n")
        if path:
            self._msg(f"G-Code gespeichert: {path}" + (f" – {note}" if note else ""))
        return path

    def show_history(self, modal: bool = True):
        from .history_qt import HistoryDialog

        def send(name, gcode):
            if self._send_without_history is None:
                return
            self._send_without_history(name, gcode, start=False)
            self._msg(f"Erneut gesendet: {name} – mit „Start“ ausführen")
        dlg = HistoryDialog(self.history, send, self.window)
        if modal:
            dlg.exec()
        return dlg


def install_job_tools(window) -> JobTools:
    """Attach the job toolbar to ``LumaCutStudio`` (needs canvas, machine_panel)."""
    tools = JobTools(window, window.canvas, window.machine_panel, window.statusBar())
    window.job_tools = tools
    return tools
