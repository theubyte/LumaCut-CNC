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
brightness / contrast / gamma / negative (all modes). Keys that do not apply to
the chosen mode are ignored; ``None`` (default) = ImageSettings defaults, so
existing grids stay byte-identical.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from lumacut_canvas.model import (IMAGE_MODES, LAYER_COLORS, PASSES_RANGE, POWER_RANGE,
                                  SPEED_RANGE, Z_OFFSET_RANGE, Document, Geometry,
                                  ImageSettings, Layer, RasterImage, Shape)
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

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
IMAGE_OPTION_KEYS = ("threshold", "halftone_cpi", "halftone_angle", "depth_levels",
                     "z_step_mm") + IMAGE_ADJUST_OPTIONS
# Allowed range of each numeric option (same limits as ImageSettings.normalized()).
IMAGE_OPTION_RANGES = {"threshold": (0, 255), "halftone_cpi": (5.0, 150.0),
                       "halftone_angle": (-90.0, 90.0), "depth_levels": (2, 64),
                       "z_step_mm": (0.0, 2.0), "brightness": (-100.0, 100.0),
                       "contrast": (-100.0, 100.0), "gamma": (0.2, 5.0)}
IMAGE_OPTION_LABELS = {"threshold": "Schwellwert", "halftone_cpi": "Halbton-Zellen",
                       "halftone_angle": "Rasterwinkel", "depth_levels": "3D-Stufen",
                       "z_step_mm": "Z-Schritt", "brightness": "Helligkeit",
                       "contrast": "Kontrast", "gamma": "Gamma", "negative": "Negativ"}
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

    def image_overrides(self) -> dict:
        """ImageSettings overrides for the image cells: only the keys that apply to
        ``image_mode`` (mode-specific + adjustments); {} without options."""
        if not self.image_mode or not self.image_options:
            return {}
        keys = IMAGE_MODE_OPTIONS.get(self.image_mode, ()) + IMAGE_ADJUST_OPTIONS
        out = {}
        for k in keys:
            if k not in self.image_options:
                continue
            v = self.image_options[k]
            if k == "negative":
                out[k] = bool(v)
            elif k in ("threshold", "depth_levels"):
                out[k] = int(v)
            else:
                out[k] = float(v)
        return out

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
        raise ValueError(f"Unbekannter Testparameter: {param}")

    def column_values(self) -> list:
        return self.param_values(self.column_param, self.columns)

    def row_values(self) -> list:
        return self.param_values(self.row_param, self.rows)

    def cell_settings(self, row: int, column: int) -> dict:
        """power / speed / interval / passes / focus of one cell (fixed off-axis)."""
        st = {"power": round(self.power_min, 1), "speed": round(self.speed_min, 1),
              "interval": self.line_interval_mm, "passes": int(self.passes),
              "focus": 0.0}  # off-axis: no focus offset (keeps default grids byte-identical)
        st[self.column_param] = self.column_values()[column]
        st[self.row_param] = self.row_values()[row]
        return st

    def label_texts(self) -> tuple[list[str], list[str]]:
        """Column and row label texts."""
        return ([_label_text(self.column_param, v) for v in self.column_values()],
                [_label_text(self.row_param, v) for v in self.row_values()])

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
        if self.column_param not in TEST_PARAMS or self.row_param not in TEST_PARAMS:
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
        if not 2 <= self.cell_mm <= 60 or not 0 <= self.gap_mm <= 30:
            raise ValueError("Zellgröße 2..60 mm, Abstand 0..30 mm")
        if self.line_interval_mm and not 0.05 <= self.line_interval_mm <= 2:
            raise ValueError("Linienabstand 0.05..2 mm (oder 0)")
        w, h = self.size()
        if self.x < 0 or self.y < 0 or self.x + w > WORK_WIDTH_MM or self.y + h > WORK_HEIGHT_MM:
            raise ValueError("Testraster passt nicht auf die Arbeitsfläche")

    def _validate_image_options(self) -> None:
        opts = self.image_options or {}
        if not isinstance(opts, dict):
            raise ValueError("Bildoptionen müssen ein Wörterbuch sein")
        for k, v in opts.items():
            if k not in IMAGE_OPTION_KEYS:
                raise ValueError(f"Unbekannte Bildoption: {k}")
            if k == "negative":
                continue
            lo, hi = IMAGE_OPTION_RANGES[k]
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{IMAGE_OPTION_LABELS[k]}: keine Zahl") from None
            if not lo <= fv <= hi:
                raise ValueError(f"{IMAGE_OPTION_LABELS[k]} außerhalb {lo:g}..{hi:g}")
        ov = self.image_overrides()
        if self.image_mode == "depth3d":
            drop = ov.get("z_step_mm", 0.0) * (ov.get("depth_levels", 8) - 1)
            if drop > MAX_DEPTH_DROP_MM + 1e-9:
                raise ValueError(f"Fokus-Absenkung {drop:.2f} mm > {MAX_DEPTH_DROP_MM:g} mm "
                                 "(Z-Schritt × (Stufen − 1))")


def _steps(lo: float, hi: float, n: int, digits: int = 1) -> list[float]:
    if n == 1:
        return [round(lo, digits)]
    return [round(lo + (hi - lo) * i / (n - 1), digits) for i in range(n)]


def _label_text(param: str, value: float) -> str:
    """Label of one column / row: power %, speed mm/s, interval mm, passes, focus mm."""
    if param == "speed":
        return f"{value / 60:.0f}"
    if param == "passes":
        return f"{int(value)}x"
    if param == "focus":
        return f"{value:+g}"
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


def image_cell(spec: MaterialTestSpec, settings: dict, x: float, y: float,
               layer_id: str, png: bytes | None = None,
               px: tuple[int, int] | None = None) -> Shape:
    """Test-image object for one cell with the cell's laser settings."""
    st = ImageSettings(mode=spec.image_mode, line_interval_mm=settings["interval"],
                       power=settings["power"], min_power=spec.image_min_power,
                       speed_mm_min=settings["speed"], passes=settings["passes"],
                       **spec.image_overrides()).normalized()
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
            # The name format is parsed by lumacut_materials.testgrid (TEST_CELL_RE).
            layer = Layer(name=f"Test P{power:g}% F{speed:g}",
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
