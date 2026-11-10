"""Material test grid, like xTool's "Material Test Array" and LightBurn's
Material Test / Interval Test.

By default columns vary power and rows vary speed. Like LightBurn's Material
Test, the parameter of each axis can be chosen: power, speed, line interval
(interval test, engrave cells only), passes or focus (relative Z offset /
LightBurn *Focus Test*); a parameter that is not on an axis takes its fixed
value (``power_min``, ``speed_min``, ``line_interval_mm``, ``passes``,
``focus_min``). Every cell gets its own canvas layer (one layer = one laser
setting in LumaCut), so the existing G-code path, layer panel and preview work
unchanged. Cells are either outlines or filled with a serpentine hatch at the
cell's line interval (engrave test). Optional labels go on a separate
low-power layer. The focus axis sets ``Layer.z_offset`` (mm relative to the
current focus when the job starts; negative = closer to the material) and
keeps the ``Test P…% F…`` layer names so the material library still parses
the cells.

Image cells (LightBurn Interval Test "Dithered Image", photo-engraving test):
with ``image_mode`` set, every cell is an image object engraved in that image
mode (dithering, greyscale, halftone, ...) with the cell's power (at black),
speed, line interval and passes in its image settings. ``image_source`` chooses
the shared test image for the whole grid: ``ramp`` (default white→black
horizontal grey ramp, byte-identical to earlier rounds), ``wedge`` (discrete
step wedge / Stufenkeil) or ``photo`` (user-supplied 8-bit grey PNG in
``image_png``). The image raster path (``lumacut_job.images``) runs them before
the vector layers, so the labels still run last. The cell layer keeps the same
name and values, so the material library's "Preset aus Testzelle" works the
same way. Default ``image_mode = ""`` = vector cells, output unchanged.

``image_options`` carries the image mode's extra parameters for every image
cell (LightBurn applies the layer's full image settings in an Interval Test):
threshold (``threshold``), halftone cells per inch / screen angle
(``halftone``), 3D depth levels / Z step (``depth3d``) and the adjustments
brightness / contrast / gamma / negative (all modes), plus the remaining image
settings for every mode (``IMAGE_EXTRA_OPTIONS``): sharpen / sharpen radius,
black / white point, tone curve, dot width correction, scan angle / angle
increment, bidirectional and overscan. Keys that do not apply to the chosen mode
are ignored; ``None`` (default) = ImageSettings defaults, so existing grids stay
byte-identical.

Image-option axes (LightBurn Interval Test with a swept image setting): with image
cells, a column or row axis can also sweep one numeric image option
(``IMAGE_AXIS_PARAMS``: threshold, halftone cells / screen angle, brightness,
contrast, gamma, sharpen, scan angle, black / white point, dot width correction,
overscan, angle increment) from ``image_axis_ranges[param] = (from, to)``
(default ``IMAGE_AXIS_DEFAULT_RANGES``), or one on / off image option
(``IMAGE_BOOL_AXIS_PARAMS``: negative, bidirectional) over exactly two columns /
rows (off, on – no range). The cell's value overrides the grid-wide
``image_options`` value; mode-specific options only on an axis in their mode
(threshold → ``threshold``, halftone → ``halftone``). Cell layers get the swept
value appended (``Test P…% F… Gamma 1.2``) so the cells stay distinguishable;
grids without an image axis keep their names and output byte-identical.
Coupled options are checked per cell: black point < white point (axis value against
the grid-wide or the other axis's value) and dot width ≤ the cell's line interval.
An angle-increment axis needs more than one pass in some cell (it only turns the
second and later passes).

Since round 51 the 3D-depth options (``depth_levels``, ``z_step_mm``; image mode
``depth3d``) are numeric image axes as well (focus drop z_step × (levels − 1) is
checked per cell), and the tone curve is a *choice* axis
(``IMAGE_CHOICE_AXIS_PARAMS``): every column / row gets one curve of
``image_axis_curves`` (``((in, out), ...)`` grey points, ``()`` = linear; ``None`` =
the first n presets of ``CURVE_PRESETS``), the count must match the curves.
Cells, layer names and labels carry the curve's short name (``CURVE_SHORT_LABELS``,
``Eigene 1`` … for curves that are no preset).
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from lumacut_canvas.model import (CURVE_MAX_POINTS, IMAGE_MODES, LAYER_COLORS, PASSES_RANGE,
                                  POWER_RANGE, SPEED_RANGE, Z_OFFSET_RANGE, Document, Geometry,
                                  ImageSettings, Layer, RasterImage, Shape, normalize_curve)
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from .raster import CURVE_PRESETS, CURVE_SHORT_LABELS
from .raster import MAX_DEPTH_DROP_MM  # 3D depth: max. z_step × (levels − 1)


# Parameters that can vary along the columns / rows of the grid.
TEST_PARAMS = ("power", "speed", "interval", "passes", "focus")
TEST_PARAM_LABELS = {"power": "Leistung", "speed": "Geschwindigkeit",
                     "interval": "Linienabstand", "passes": "Durchgänge",
                     "focus": "Fokus-Versatz"}
INTERVAL_TEST_RANGE = (0.05, 2.0)   # mm
# Image modes offered for image test cells (sketch only draws edges, a ramp has none).
TEST_IMAGE_MODES = tuple(m for m in IMAGE_MODES if m != "sketch")
# Shared test-image sources for image cells (LightBurn Interval Test style).
IMAGE_SOURCES = ("ramp", "wedge", "photo")
IMAGE_SOURCE_LABELS = {"ramp": "Verlauf", "wedge": "Stufenkeil", "photo": "Eigenes Bild…"}
# Extra image-settings parameters per image mode (ImageSettings field names) and the
# adjustments that apply to every mode. Applied to every image cell of the grid.
IMAGE_MODE_OPTIONS = {"threshold": ("threshold",),
                      "halftone": ("halftone_cpi", "halftone_angle"),
                      "depth3d": ("depth_levels", "z_step_mm")}
IMAGE_ADJUST_OPTIONS = ("brightness", "contrast", "gamma", "negative")
# Remaining image settings, also for every mode (dialog: „Weitere Bildoptionen“).
IMAGE_EXTRA_OPTIONS = ("sharpen", "sharpen_radius", "black_point", "white_point", "curve",
                       "dot_width_mm", "scan_angle", "angle_increment", "bidirectional",
                       "overscan_mm")
IMAGE_OPTION_KEYS = ("threshold", "halftone_cpi", "halftone_angle", "depth_levels",
                     "z_step_mm") + IMAGE_ADJUST_OPTIONS + IMAGE_EXTRA_OPTIONS
# Option value types besides float (curve: ((in, out), ...) grey values).
IMAGE_BOOL_OPTIONS = ("negative", "bidirectional")
IMAGE_INT_OPTIONS = ("threshold", "depth_levels", "black_point", "white_point")
# Allowed range of each numeric option (same limits as ImageSettings.normalized()).
IMAGE_OPTION_RANGES = {"threshold": (0, 255), "halftone_cpi": (5.0, 150.0),
                       "halftone_angle": (-90.0, 90.0), "depth_levels": (2, 64),
                       "z_step_mm": (0.0, 2.0), "brightness": (-100.0, 100.0),
                       "contrast": (-100.0, 100.0), "gamma": (0.2, 5.0),
                       "sharpen": (0.0, 500.0), "sharpen_radius": (0.5, 10.0),
                       "black_point": (0, 254), "white_point": (1, 255),
                       "dot_width_mm": (0.0, 2.0), "scan_angle": (-90.0, 90.0),
                       "angle_increment": (-90.0, 90.0), "overscan_mm": (0.0, 20.0)}
IMAGE_OPTION_LABELS = {"threshold": "Schwellwert", "halftone_cpi": "Halbton-Zellen",
                       "halftone_angle": "Rasterwinkel", "depth_levels": "3D-Stufen",
                       "z_step_mm": "Z-Schritt", "brightness": "Helligkeit",
                       "contrast": "Kontrast", "gamma": "Gamma", "negative": "Negativ",
                       "sharpen": "Schärfen", "sharpen_radius": "Schärferadius",
                       "black_point": "Schwarzpunkt", "white_point": "Weißpunkt",
                       "curve": "Kurve", "dot_width_mm": "Punktbreitenkorrektur",
                       "scan_angle": "Scan-Winkel", "angle_increment": "Winkel-Schritt",
                       "bidirectional": "Bidirektional", "overscan_mm": "Overscan"}
# Numeric image options that can be swept along a column / row axis (image cells only).
IMAGE_AXIS_PARAMS = ("threshold", "halftone_cpi", "halftone_angle", "brightness",
                     "contrast", "gamma", "sharpen", "scan_angle", "black_point",
                     "white_point", "dot_width_mm", "overscan_mm", "angle_increment",
                     "depth_levels", "z_step_mm")
# On / off image options that can be put on an axis: exactly two columns / rows,
# first off, then on (``IMAGE_BOOL_AXIS_VALUES``).
IMAGE_BOOL_AXIS_PARAMS = ("negative", "bidirectional")
IMAGE_BOOL_AXIS_VALUES = (False, True)
IMAGE_BOOL_LABELS = {False: "aus", True: "an"}
# Choice axes: one value of a list per column / row (tone curve: image_axis_curves).
IMAGE_CHOICE_AXIS_PARAMS = ("curve",)
# Every image option that can be on an axis (numeric + on / off + choice).
IMAGE_ALL_AXIS_PARAMS = IMAGE_AXIS_PARAMS + IMAGE_BOOL_AXIS_PARAMS + IMAGE_CHOICE_AXIS_PARAMS
# Curves of a curve axis without image_axis_curves: the first n presets.
CURVE_AXIS_PRESETS = tuple(normalize_curve(pts) for pts in CURVE_PRESETS.values())
# Default from/to of an image axis without an explicit range.
IMAGE_AXIS_DEFAULT_RANGES = {"threshold": (64, 192), "halftone_cpi": (20.0, 60.0),
                             "halftone_angle": (0.0, 45.0), "brightness": (-40.0, 40.0),
                             "contrast": (-40.0, 40.0), "gamma": (0.6, 1.8),
                             "sharpen": (0.0, 200.0), "scan_angle": (0.0, 90.0),
                             "black_point": (0, 64), "white_point": (192, 255),
                             "dot_width_mm": (0.0, 0.1), "overscan_mm": (0.0, 5.0),
                             "angle_increment": (0.0, 90.0), "depth_levels": (4, 16),
                             "z_step_mm": (0.0, 0.2)}
# Unit of an image axis value in layer names / the dialog.
IMAGE_AXIS_UNITS = {"threshold": "", "halftone_cpi": "/Zoll", "halftone_angle": "°",
                    "brightness": "%", "contrast": "%", "gamma": "", "sharpen": "%",
                    "scan_angle": "°", "black_point": "", "white_point": "",
                    "dot_width_mm": "mm", "overscan_mm": "mm", "angle_increment": "°",
                    "negative": "", "bidirectional": "", "depth_levels": "",
                    "z_step_mm": "mm", "curve": ""}
# Decimals of the swept values (threshold is an integer grey value).
IMAGE_AXIS_DIGITS = {"threshold": 0, "gamma": 2, "black_point": 0, "white_point": 0,
                     "dot_width_mm": 3, "depth_levels": 0, "z_step_mm": 2}
# German names of the image modes a mode-specific axis needs (error messages).
IMAGE_AXIS_MODE_LABELS = {"threshold": "Schwellwert", "halftone": "Halbton",
                          "depth3d": "3D-Tiefe"}
# Every axis parameter (vector + image) and its label.
AXIS_PARAMS = TEST_PARAMS + IMAGE_ALL_AXIS_PARAMS
AXIS_PARAM_LABELS = {**TEST_PARAM_LABELS,
                     **{k: IMAGE_OPTION_LABELS[k] for k in IMAGE_ALL_AXIS_PARAMS}}


def image_axis_mode(param: str) -> str:
    """Image mode a mode-specific image axis needs ("" = every image mode)."""
    for mode, keys in IMAGE_MODE_OPTIONS.items():
        if param in keys:
            return mode
    return ""


def curve_label(curve, custom_index: int = 1) -> str:
    """Short label of a tone curve: preset short name or „Eigene N“."""
    c = normalize_curve(curve)
    for name, pts in CURVE_PRESETS.items():
        if normalize_curve(pts) == c:
            return CURVE_SHORT_LABELS.get(name, name)
    return f"Eigene {custom_index}"


# Pixel size of the embedded grey ramp / step wedge (white left -> black right).
RAMP_PX = (256, 16)
# Number of equal grey bands in a step wedge (white → black).
WEDGE_STEPS = 16
# Rough width of one label character relative to the label height.
_LABEL_CHAR_W = 0.62


@dataclass
class MaterialTestSpec:
    power_min: float = 20.0      # %
    power_max: float = 100.0
    columns: int = 5
    speed_min: float = 600.0     # mm/min
    speed_max: float = 3000.0
    rows: int = 5
    cell_mm: float = 10.0
    gap_mm: float = 4.0
    x: float = 20.0              # top-left of the grid, work-area mm
    y: float = 20.0
    passes: int = 1
    line_interval_mm: float = 0.2  # 0 = outline only
    labels: bool = True
    label_power: float = 15.0
    label_speed: float = 3000.0
    label_mm: float = 3.0
    # Axis parameters (TEST_PARAMS); default = the classic power x speed grid.
    column_param: str = "power"
    row_param: str = "speed"
    interval_max: float = 0.5      # mm, only used when "interval" is on an axis
    passes_max: int = 5            # only used when "passes" is on an axis
    # Focus Test (LightBurn): relative Z offset in mm; only used when "focus" is
    # on an axis. Relative to the focus height when the job starts; negative =
    # closer to the material. Needs motorized Z (LumaCut has it).
    focus_min: float = -1.0
    focus_max: float = 1.0
    # Image cells: "" = vector cells (hatch / outline); an image mode (TEST_IMAGE_MODES)
    # = image cells engraved in that mode. image_min_power = power at white.
    # image_source selects the shared PNG (ramp / wedge / photo); photo needs image_png.
    image_mode: str = ""
    image_min_power: float = 0.0
    image_source: str = "ramp"
    image_png: bytes | None = None
    # Extra image-mode parameters (IMAGE_OPTION_KEYS -> value); None = defaults.
    image_options: dict | None = None
    # From/to of an image-option axis (IMAGE_AXIS_PARAMS -> (from, to)); missing =
    # IMAGE_AXIS_DEFAULT_RANGES. Only used when that option is on an axis.
    image_axis_ranges: dict | None = None
    # Curves of a tone-curve axis in column / row order (((in, out), ...), () = linear);
    # None = the first n presets (CURVE_AXIS_PRESETS). Only used when "curve" is on an axis.
    image_axis_curves: tuple | None = None

    def image_axes(self) -> tuple[str, ...]:
        """Image options on an axis (column first)."""
        return tuple(p for p in (self.column_param, self.row_param)
                     if p in IMAGE_ALL_AXIS_PARAMS)

    def image_axis_range(self, param: str) -> tuple[float, float]:
        rng = (self.image_axis_ranges or {}).get(param)
        if rng is None:
            rng = IMAGE_AXIS_DEFAULT_RANGES[param]
        lo, hi = rng
        return float(lo), float(hi)

    def image_overrides(self) -> dict:
        """ImageSettings overrides for the image cells: only the keys that apply to
        ``image_mode`` (mode-specific + adjustments); {} without options."""
        if not self.image_mode or not self.image_options:
            return {}
        keys = (IMAGE_MODE_OPTIONS.get(self.image_mode, ()) + IMAGE_ADJUST_OPTIONS
                + IMAGE_EXTRA_OPTIONS)
        out = {}
        for k in keys:
            if k not in self.image_options:
                continue
            v = self.image_options[k]
            if k in IMAGE_BOOL_OPTIONS:
                out[k] = bool(v)
            elif k in IMAGE_INT_OPTIONS:
                out[k] = int(v)
            elif k == "curve":
                out[k] = normalize_curve(v)
            else:
                out[k] = float(v)
        return out

    def max_passes(self) -> int:
        """Largest number of passes of all cells (passes axis included)."""
        if "passes" in (self.column_param, self.row_param):
            return max(self.param_values("passes", 2))
        return int(self.passes)

    def min_interval(self) -> float:
        """Smallest line interval of all cells (interval axis included)."""
        if "interval" in (self.column_param, self.row_param):
            return min(self.param_values("interval", 2))
        return self.line_interval_mm

    def powers(self) -> list[float]:
        return _steps(self.power_min, self.power_max, self.columns)

    def speeds(self) -> list[float]:
        return _steps(self.speed_min, self.speed_max, self.rows)

    def param_values(self, param: str, n: int) -> list:
        """``n`` values of ``param`` from its minimum to its maximum."""
        if param == "power":
            return _steps(self.power_min, self.power_max, n)
        if param == "speed":
            return _steps(self.speed_min, self.speed_max, n)
        if param == "interval":
            return _steps(self.line_interval_mm, self.interval_max, n, 3)
        if param == "passes":
            return [int(round(v)) for v in _steps(self.passes, self.passes_max, n, 6)]
        if param == "focus":
            return _steps(self.focus_min, self.focus_max, n, 3)
        if param in IMAGE_BOOL_AXIS_PARAMS:
            # off / on; validate() requires exactly two columns / rows.
            return [IMAGE_BOOL_AXIS_VALUES[i % 2] for i in range(n)]
        if param in IMAGE_CHOICE_AXIS_PARAMS:
            curves = (CURVE_AXIS_PRESETS if self.image_axis_curves is None
                      else tuple(normalize_curve(c) for c in self.image_axis_curves))
            # validate() requires exactly n curves (n presets at most without a list).
            return [curves[i % len(curves)] for i in range(n)] if curves else [()] * n
        if param in IMAGE_AXIS_PARAMS:
            lo, hi = self.image_axis_range(param)
            digits = IMAGE_AXIS_DIGITS.get(param, 1)
            vals = _steps(lo, hi, n, digits)
            return [int(v) for v in vals] if digits == 0 else vals
        raise ValueError(f"Unbekannter Testparameter: {param}")

    def column_values(self) -> list:
        return self.param_values(self.column_param, self.columns)

    def row_values(self) -> list:
        return self.param_values(self.row_param, self.rows)

    def cell_settings(self, row: int, column: int) -> dict:
        """power / speed / interval / passes / focus of one cell (fixed off-axis), plus
        the swept image option(s) when an image option is on an axis."""
        st = {"power": round(self.power_min, 1), "speed": round(self.speed_min, 1),
              "interval": self.line_interval_mm, "passes": int(self.passes),
              "focus": 0.0}  # off-axis: no focus offset (keeps default grids byte-identical)
        st[self.column_param] = self.column_values()[column]
        st[self.row_param] = self.row_values()[row]
        return st

    def cell_image_values(self, row: int, column: int) -> dict:
        """Swept image options of one cell ({} without an image axis)."""
        out = {}
        if self.column_param in IMAGE_ALL_AXIS_PARAMS:
            out[self.column_param] = self.column_values()[column]
        if self.row_param in IMAGE_ALL_AXIS_PARAMS:
            out[self.row_param] = self.row_values()[row]
        return out

    def cell_layer_name(self, row: int, column: int) -> str:
        """Layer name of one cell; swept image values are appended."""
        st = self.cell_settings(row, column)
        name = f"Test P{st['power']:g}% F{st['speed']:g}"
        for k, v in self.cell_image_values(row, column).items():
            index = column if k == self.column_param else row
            name += (f" {IMAGE_OPTION_LABELS[k]} {self._value_label(k, index, v)}"
                     f"{IMAGE_AXIS_UNITS[k]}")
        return name

    def _value_label(self, param: str, index: int, value) -> str:
        """Label of the ``index``-th value of an axis (curve: short name / „Eigene N“
        numbered over the curves of the axis that are no preset)."""
        if param in IMAGE_CHOICE_AXIS_PARAMS:
            n = self.columns if param == self.column_param else self.rows
            vals = self.param_values(param, n)
            custom = sum(1 for c in vals[:index + 1] if c not in CURVE_AXIS_PRESETS)
            return curve_label(value, max(1, custom))
        return _label_text(param, value)

    def label_texts(self) -> tuple[list[str], list[str]]:
        """Column and row label texts."""
        return ([self._value_label(self.column_param, i, v)
                 for i, v in enumerate(self.column_values())],
                [self._value_label(self.row_param, i, v)
                 for i, v in enumerate(self.row_values())])

    def label_width(self) -> float:
        """Width of the row-label column left of the grid (0 without labels)."""
        if not self.labels:
            return 0.0
        lab = self.label_mm + 2
        if self.row_param == "speed":
            return lab
        widest = max(_label_w(t, self.label_mm) for t in self.label_texts()[1])
        return max(lab, round(widest + 2, 3))

    def size(self) -> tuple[float, float]:
        lab = (self.label_mm + 2) if self.labels else 0.0
        w = self.label_width() + self.columns * self.cell_mm + (self.columns - 1) * self.gap_mm
        h = lab + self.rows * self.cell_mm + (self.rows - 1) * self.gap_mm
        return w, h

    def validate(self) -> None:
        if self.column_param not in AXIS_PARAMS or self.row_param not in AXIS_PARAMS:
            raise ValueError("Unbekannter Testparameter")
        if self.column_param == self.row_param:
            raise ValueError("Spalten und Zeilen brauchen verschiedene Parameter")
        if not (1 <= self.columns <= 12 and 1 <= self.rows <= 12):
            raise ValueError("1..12 Spalten und Zeilen")
        axes = (self.column_param, self.row_param)
        if "interval" in axes:
            if not self.line_interval_mm:
                raise ValueError("Linienabstand-Test nur mit Füllen (Gravur)")
            if not INTERVAL_TEST_RANGE[0] <= self.interval_max <= INTERVAL_TEST_RANGE[1]:
                raise ValueError("Linienabstand 0.05..2 mm (oder 0)")
        if "passes" in axes and not PASSES_RANGE[0] <= self.passes_max <= PASSES_RANGE[1]:
            raise ValueError("Durchgänge außerhalb 1..30")
        if "focus" in axes:
            for v in (self.focus_min, self.focus_max):
                if not Z_OFFSET_RANGE[0] <= v <= Z_OFFSET_RANGE[1]:
                    raise ValueError(f"Fokus-Versatz außerhalb {Z_OFFSET_RANGE[0]:g}..{Z_OFFSET_RANGE[1]:g} mm")
            if self.focus_min == self.focus_max:
                raise ValueError("Fokus von und bis müssen verschieden sein")
        for p in (self.power_min, self.power_max, self.label_power):
            if not POWER_RANGE[0] <= p <= POWER_RANGE[1]:
                raise ValueError("Leistung außerhalb 1..100 %")
        for s in (self.speed_min, self.speed_max, self.label_speed):
            if not SPEED_RANGE[0] <= s <= SPEED_RANGE[1]:
                raise ValueError("Geschwindigkeit außerhalb 1..6000 mm/min")
        if not PASSES_RANGE[0] <= self.passes <= PASSES_RANGE[1]:
            raise ValueError("Durchgänge außerhalb 1..30")
        if self.image_mode:
            if self.image_mode not in TEST_IMAGE_MODES:
                raise ValueError(f"Unbekannter Bildmodus: {self.image_mode}")
            if not self.line_interval_mm:
                raise ValueError("Bild-Testzellen brauchen einen Linienabstand")
            if not 0 <= self.image_min_power <= self.power_min:
                raise ValueError("Min.-Leistung (Weiß) 0..kleinste Leistung")
            src = self.image_source or "ramp"
            if src not in IMAGE_SOURCES:
                raise ValueError(f"Unbekannte Bildquelle: {src}")
            if src == "photo":
                if not self.image_png:
                    raise ValueError("Eigenes Bild fehlt – bitte eine Bilddatei wählen")
                if not self.image_png.startswith(b"\x89PNG"):
                    raise ValueError("Eigenes Bild muss ein PNG sein")
            self._validate_image_options()
        self._validate_image_axes()
        if not 2 <= self.cell_mm <= 60 or not 0 <= self.gap_mm <= 30:
            raise ValueError("Zellgröße 2..60 mm, Abstand 0..30 mm")
        if self.line_interval_mm and not 0.05 <= self.line_interval_mm <= 2:
            raise ValueError("Linienabstand 0.05..2 mm (oder 0)")
        w, h = self.size()
        if self.x < 0 or self.y < 0 or self.x + w > WORK_WIDTH_MM or self.y + h > WORK_HEIGHT_MM:
            raise ValueError("Testraster passt nicht auf die Arbeitsfläche")

    def _validate_image_axes(self) -> None:
        ranges = self.image_axis_ranges or {}
        if not isinstance(ranges, dict):
            raise ValueError("Bild-Achsenbereiche müssen ein Wörterbuch sein")
        for k, rng in ranges.items():
            if k not in IMAGE_AXIS_PARAMS:
                raise ValueError(f"Unbekannte Bild-Achse: {k}")
            try:
                lo, hi = (float(v) for v in rng)
            except (TypeError, ValueError):
                raise ValueError(f"{IMAGE_OPTION_LABELS[k]}: von/bis-Zahlen erwartet") from None
        for k in self.image_axes():
            label = IMAGE_OPTION_LABELS[k]
            if not self.image_mode:
                raise ValueError(f"{label} als Achse nur mit Bild-Testzellen")
            mode = image_axis_mode(k)
            if mode and self.image_mode != mode:
                raise ValueError(f"{label}-Achse nur im Bildmodus "
                                 f"{IMAGE_AXIS_MODE_LABELS.get(mode, mode)}")
            if k in IMAGE_BOOL_AXIS_PARAMS:
                n = self.columns if k == self.column_param else self.rows
                if n != 2:
                    side = "Spalten" if k == self.column_param else "Zeilen"
                    raise ValueError(f"{label}-Achse braucht genau 2 {side} (aus / an)")
                continue
            if k in IMAGE_CHOICE_AXIS_PARAMS:
                self._validate_curve_axis(k)
                continue
            if k == "angle_increment" and self.max_passes() < 2:
                raise ValueError("Winkel-Schritt-Achse braucht mehr als einen Durchgang "
                                 "(dreht erst den 2. und jeden weiteren Durchgang)")
            lo, hi = self.image_axis_range(k)
            rlo, rhi = IMAGE_OPTION_RANGES[k]
            if not (rlo <= lo <= rhi and rlo <= hi <= rhi):
                raise ValueError(f"{label} außerhalb {rlo:g}..{rhi:g}")
            vals = self.param_values(k, self.columns if k == self.column_param else self.rows)
            if lo == hi or (len(vals) > 1 and len(set(vals)) < len(vals)):
                raise ValueError(f"{label} von und bis müssen verschieden sein")
        problem = self.image_cell_problem()
        if problem:
            raise ValueError(problem)

    def _validate_curve_axis(self, k: str) -> None:
        """Tone-curve axis: 2.. curves, one per column / row, each valid, no duplicates."""
        n = self.columns if k == self.column_param else self.rows
        side = "Spalten" if k == self.column_param else "Zeilen"
        if n < 2:
            raise ValueError(f"Kurven-Achse braucht mindestens 2 {side}")
        if self.image_axis_curves is None:
            if n > len(CURVE_AXIS_PRESETS):
                raise ValueError(f"Kurven-Achse: höchstens {len(CURVE_AXIS_PRESETS)} Vorlagen "
                                 f"– {n} {side}")
            return
        try:
            curves = list(self.image_axis_curves)
        except TypeError:
            raise ValueError("Kurven-Achse: Liste von Kurven erwartet") from None
        for c in curves:
            _validate_curve(c)
        if len(curves) != n:
            raise ValueError(f"Kurven-Achse: {len(curves)} Kurven für {n} {side}")
        norm = [normalize_curve(c) for c in curves]
        if len(set(norm)) < len(norm):
            raise ValueError("Kurven-Achse: jede Kurve nur einmal")

    def image_cell_problem(self) -> str:
        """German error for coupled image options that a swept value breaks in some
        cell (black point ≥ white point, dot width > the cell's line interval, 3D
        focus drop z_step × (levels − 1) > MAX_DEPTH_DROP_MM); "" = every cell is fine
        or no coupled option is on an axis."""
        swept = set(self.image_axes())
        if not self.image_mode or not swept & {"black_point", "white_point", "dot_width_mm",
                                               "depth_levels", "z_step_mm"}:
            return ""
        for r in range(self.rows):
            for c in range(self.columns):
                st = self.cell_settings(r, c)
                ov = _cell_overrides(self, st)
                bp, wp = ov.get("black_point", 0), ov.get("white_point", 255)
                if swept & {"black_point", "white_point"} and bp >= wp:
                    return (f"Schwarzpunkt {bp} muss kleiner als der Weißpunkt {wp} sein "
                            "(in jeder Testzelle)")
                dot = ov.get("dot_width_mm", 0.0)
                if "dot_width_mm" in swept and dot > st["interval"] + 1e-9:
                    return (f"Punktbreitenkorrektur {dot:g} mm > Linienabstand "
                            f"{st['interval']:g} mm der Testzelle")
                if swept & {"depth_levels", "z_step_mm"} and self.image_mode == "depth3d":
                    drop = ov.get("z_step_mm", 0.0) * (ov.get("depth_levels", 8) - 1)
                    if drop > MAX_DEPTH_DROP_MM + 1e-9:
                        return (f"Fokus-Absenkung {drop:.2f} mm > {MAX_DEPTH_DROP_MM:g} mm "
                                "(Z-Schritt × (Stufen − 1)) in einer Testzelle")
        return ""

    def _validate_image_options(self) -> None:
        opts = self.image_options or {}
        if not isinstance(opts, dict):
            raise ValueError("Bildoptionen müssen ein Wörterbuch sein")
        for k, v in opts.items():
            if k not in IMAGE_OPTION_KEYS:
                raise ValueError(f"Unbekannte Bildoption: {k}")
            if k in IMAGE_BOOL_OPTIONS:
                continue
            if k == "curve":
                _validate_curve(v)
                continue
            lo, hi = IMAGE_OPTION_RANGES[k]
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{IMAGE_OPTION_LABELS[k]}: keine Zahl") from None
            if not lo <= fv <= hi:
                raise ValueError(f"{IMAGE_OPTION_LABELS[k]} außerhalb {lo:g}..{hi:g}")
        ov = self.image_overrides()
        swept = set(self.image_axes())  # swept options: checked per cell instead
        if self.image_mode == "depth3d" and not swept & {"depth_levels", "z_step_mm"}:
            drop = ov.get("z_step_mm", 0.0) * (ov.get("depth_levels", 8) - 1)
            if drop > MAX_DEPTH_DROP_MM + 1e-9:
                raise ValueError(f"Fokus-Absenkung {drop:.2f} mm > {MAX_DEPTH_DROP_MM:g} mm "
                                 "(Z-Schritt × (Stufen − 1))")
        if (not swept & {"black_point", "white_point"}
                and ov.get("black_point", 0) >= ov.get("white_point", 255)):
            raise ValueError("Schwarzpunkt muss kleiner als der Weißpunkt sein")
        if ("dot_width_mm" not in swept
                and ov.get("dot_width_mm", 0.0) > self.min_interval() + 1e-9):
            raise ValueError(f"Punktbreitenkorrektur {ov['dot_width_mm']:g} mm > kleinster "
                             f"Linienabstand {self.min_interval():g} mm")


def _validate_curve(points) -> None:
    """Tone curve option: 2..CURVE_MAX_POINTS points (in, out) 0..255, inputs rising
    (empty = linear)."""
    try:
        pts = [(float(a), float(b)) for a, b in (points or ())]
    except (TypeError, ValueError):
        raise ValueError("Kurve: Punkte (Eingang, Ausgang) erwartet") from None
    if not pts:
        return
    xs = [a for a, _ in pts]
    if not 2 <= len(pts) <= CURVE_MAX_POINTS:
        raise ValueError(f"Kurve: 2..{CURVE_MAX_POINTS} Punkte")
    if any(not 0 <= v <= 255 for p in pts for v in p) or any(b <= a for a, b in zip(xs, xs[1:])):
        raise ValueError("Kurve: Punkte 0..255, Eingänge aufsteigend")


def _steps(lo: float, hi: float, n: int, digits: int = 1) -> list[float]:
    if n == 1:
        return [round(lo, digits)]
    return [round(lo + (hi - lo) * i / (n - 1), digits) for i in range(n)]


def _label_text(param: str, value: float) -> str:
    """Label of one column / row: power %, speed mm/s, interval mm, passes, focus mm,
    image option value (brightness / contrast signed)."""
    if param == "speed":
        return f"{value / 60:.0f}"
    if param == "passes":
        return f"{int(value)}x"
    if param in ("focus", "brightness", "contrast"):
        return f"{value:+g}"
    if param in IMAGE_BOOL_AXIS_PARAMS:
        return IMAGE_BOOL_LABELS[bool(value)]
    return f"{value:g}"


def _label_w(text: str, height: float) -> float:
    return round(max(1, len(text)) * height * _LABEL_CHAR_W, 3)


def hatch_points(x: float, y: float, w: float, h: float, interval: float) -> list[tuple[float, float]]:
    """Serpentine fill of a rectangle (one continuous open path)."""
    pts: list[tuple[float, float]] = []
    n = max(1, int(round(h / interval)))
    for i in range(n + 1):
        yy = y + h * i / n
        row = [(x, yy), (x + w, yy)]
        pts += row if i % 2 == 0 else row[::-1]
    return pts


def _grey_png(width: int, height: int, row: bytes) -> bytes:
    """Encode one repeated grey row as an 8-bit greyscale PNG."""
    if len(row) != width:
        raise ValueError("Graustufenzeile passt nicht zur Breite")
    raw = b"".join(b"\x00" + row for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ramp_png(width: int = RAMP_PX[0], height: int = RAMP_PX[1]) -> bytes:
    """8-bit grey PNG of a horizontal ramp, white (left) to black (right)."""
    row = bytes(255 - round(255 * x / (width - 1)) for x in range(width))
    return _grey_png(width, height, row)


def wedge_png(width: int = RAMP_PX[0], height: int = RAMP_PX[1],
              steps: int = WEDGE_STEPS) -> bytes:
    """8-bit grey PNG of a horizontal step wedge (equal bands, white → black)."""
    n = max(2, int(steps))
    row = bytearray(width)
    for x in range(width):
        step = min(n - 1, x * n // width)
        row[x] = 255 - round(255 * step / (n - 1))
    return _grey_png(width, height, bytes(row))


def png_size(png: bytes) -> tuple[int, int]:
    """Width and height from a PNG IHDR chunk."""
    if not png.startswith(b"\x89PNG") or len(png) < 24:
        raise ValueError("Eigenes Bild muss ein PNG sein")
    return struct.unpack(">II", png[16:24])


def cell_image_png(spec: MaterialTestSpec) -> tuple[bytes, int, int]:
    """Shared PNG + pixel size for every image cell of ``spec``."""
    src = spec.image_source or "ramp"
    if src == "wedge":
        png = wedge_png()
        return png, RAMP_PX[0], RAMP_PX[1]
    if src == "photo":
        if not spec.image_png:
            raise ValueError("Eigenes Bild fehlt – bitte eine Bilddatei wählen")
        png = spec.image_png
        return png, *png_size(png)
    png = ramp_png()
    return png, RAMP_PX[0], RAMP_PX[1]


def _cell_overrides(spec: MaterialTestSpec, settings: dict) -> dict:
    """Grid-wide image options with the cell's swept image values on top."""
    ov = spec.image_overrides()
    for k in spec.image_axes():
        if k in settings:
            v = settings[k]
            ov[k] = (bool(v) if k in IMAGE_BOOL_OPTIONS
                     else normalize_curve(v) if k == "curve"
                     else int(v) if k in IMAGE_INT_OPTIONS else float(v))
    return ov


def image_cell(spec: MaterialTestSpec, settings: dict, x: float, y: float,
               layer_id: str, png: bytes | None = None,
               px: tuple[int, int] | None = None) -> Shape:
    """Test-image object for one cell with the cell's laser settings."""
    st = ImageSettings(mode=spec.image_mode, line_interval_mm=settings["interval"],
                       power=settings["power"], min_power=spec.image_min_power,
                       speed_mm_min=settings["speed"], passes=settings["passes"],
                       **_cell_overrides(spec, settings)).normalized()
    if png is None or px is None:
        png, w, h = cell_image_png(spec)
    else:
        w, h = px
    img = RasterImage(png, w, h, st)
    return Shape("image", Geometry(x, y, spec.cell_mm, spec.cell_mm), layer_id, image=img)


def build_material_test(spec: MaterialTestSpec) -> tuple[list[Layer], list[Shape]]:
    """Layers and shapes for the grid (not yet added to a document).

    Layer order in the returned list = top to bottom in the layer panel; the
    bottom layer runs first, so the list is built so that the labels (first
    entry) run *last* and cells run row by row from the top-left.
    """
    spec.validate()
    layers: list[Layer] = []
    shapes: list[Shape] = []
    lab = (spec.label_mm + 2) if spec.labels else 0.0
    ox, oy = spec.x + spec.label_width(), spec.y + lab
    pitch = spec.cell_mm + spec.gap_mm
    interval_test = "interval" in (spec.column_param, spec.row_param)
    cell_layers: list[Layer] = []
    shared = cell_image_png(spec) if spec.image_mode else None
    for r in range(spec.rows):
        for c in range(spec.columns):
            st = spec.cell_settings(r, c)
            power, speed = st["power"], st["speed"]
            # "Test P…% F…" is parsed by lumacut_materials.testgrid (TEST_CELL_RE);
            # an image axis appends the swept value (cell_layer_name).
            layer = Layer(name=spec.cell_layer_name(r, c),
                          color=LAYER_COLORS[(r * spec.columns + c) % len(LAYER_COLORS)],
                          power=power, speed=speed, passes=st["passes"],
                          z_offset=float(st.get("focus", 0.0) or 0.0))
            if interval_test:
                # Recorded on the layer (fill stays off, so no effect on the G-code).
                layer.line_interval_mm = st["interval"]
            cell_layers.append(layer)
            x, y = ox + c * pitch, oy + r * pitch
            if spec.image_mode:
                png, pw, ph = shared
                shapes.append(image_cell(spec, st, x, y, layer.id, png, (pw, ph)))
            elif spec.line_interval_mm:
                shapes.append(Shape.from_points(
                    "path", hatch_points(x, y, spec.cell_mm, spec.cell_mm, st["interval"]),
                    layer.id))
            else:
                shapes.append(Shape("rect", Geometry(x, y, spec.cell_mm, spec.cell_mm), layer.id))
    if spec.labels:
        label = Layer(name="Test Beschriftung", color="#e8e36a", power=spec.label_power,
                      speed=spec.label_speed, passes=1)
        layers.append(label)
        th = spec.label_mm
        col_texts, row_texts = spec.label_texts()
        for c, text in enumerate(col_texts):
            w = th * 2.4 if spec.column_param in ("power", "speed") else _label_w(text, th)
            shapes.append(Shape("text", Geometry(ox + c * pitch, spec.y, min(spec.cell_mm, w), th),
                                label.id, text=text))
        row_vals = spec.row_values()
        for r, text in enumerate(row_texts):
            y = oy + r * pitch + (spec.cell_mm - th) / 2
            if spec.row_param == "speed":
                geo = Geometry(spec.x, y, th, th * 0.9 if row_vals[r] < 1000 else th)
            else:
                geo = Geometry(spec.x, y, _label_w(text, th), th)
            shapes.append(Shape("text", geo, label.id, text=text))
    # Bottom layer runs first: reverse so the top-left cell is the last entry.
    layers += list(reversed(cell_layers))
    return layers, shapes


def add_material_test(doc: Document, spec: MaterialTestSpec) -> list[Layer]:
    """Add the grid directly to ``doc`` (no undo). Returns the new layers."""
    layers, shapes = build_material_test(spec)
    doc.begin_batch()
    try:
        for layer in reversed(layers):
            doc.add_layer(layer, 0)
        for s in shapes:
            doc.add_shape(s)
    finally:
        doc.end_batch()
    return layers
