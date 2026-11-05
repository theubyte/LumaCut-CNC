"""Material test grid, like xTool's "Material Test Array" and LightBurn's
Material Test / Interval Test.

By default columns vary power and rows vary speed. Like LightBurn's Material
Test, the parameter of each axis can be chosen: power, speed, line interval
(interval test, engrave cells only) or passes; a parameter that is not on an
axis takes its fixed value (``power_min``, ``speed_min``, ``line_interval_mm``,
``passes``). Every cell gets its own canvas layer (one layer = one laser
setting in LumaCut), so the existing G-code path, layer panel and preview work
unchanged. Cells are either outlines or filled with a serpentine hatch at the
cell's line interval (engrave test). Optional labels go on a separate
low-power layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from lumacut_canvas.model import (LAYER_COLORS, PASSES_RANGE, POWER_RANGE, SPEED_RANGE,
                                  Document, Geometry, Layer, Shape)
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM


# Parameters that can vary along the columns / rows of the grid.
TEST_PARAMS = ("power", "speed", "interval", "passes")
TEST_PARAM_LABELS = {"power": "Leistung", "speed": "Geschwindigkeit",
                     "interval": "Linienabstand", "passes": "Durchgänge"}
INTERVAL_TEST_RANGE = (0.05, 2.0)   # mm
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
        raise ValueError(f"Unbekannter Testparameter: {param}")

    def column_values(self) -> list:
        return self.param_values(self.column_param, self.columns)

    def row_values(self) -> list:
        return self.param_values(self.row_param, self.rows)

    def cell_settings(self, row: int, column: int) -> dict:
        """power / speed / interval / passes of one cell (fixed values off-axis)."""
        st = {"power": round(self.power_min, 1), "speed": round(self.speed_min, 1),
              "interval": self.line_interval_mm, "passes": int(self.passes)}
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
        for p in (self.power_min, self.power_max, self.label_power):
            if not POWER_RANGE[0] <= p <= POWER_RANGE[1]:
                raise ValueError("Leistung außerhalb 1..100 %")
        for s in (self.speed_min, self.speed_max, self.label_speed):
            if not SPEED_RANGE[0] <= s <= SPEED_RANGE[1]:
                raise ValueError("Geschwindigkeit außerhalb 1..6000 mm/min")
        if not PASSES_RANGE[0] <= self.passes <= PASSES_RANGE[1]:
            raise ValueError("Durchgänge außerhalb 1..30")
        if not 2 <= self.cell_mm <= 60 or not 0 <= self.gap_mm <= 30:
            raise ValueError("Zellgröße 2..60 mm, Abstand 0..30 mm")
        if self.line_interval_mm and not 0.05 <= self.line_interval_mm <= 2:
            raise ValueError("Linienabstand 0.05..2 mm (oder 0)")
        w, h = self.size()
        if self.x < 0 or self.y < 0 or self.x + w > WORK_WIDTH_MM or self.y + h > WORK_HEIGHT_MM:
            raise ValueError("Testraster passt nicht auf die Arbeitsfläche")


def _steps(lo: float, hi: float, n: int, digits: int = 1) -> list[float]:
    if n == 1:
        return [round(lo, digits)]
    return [round(lo + (hi - lo) * i / (n - 1), digits) for i in range(n)]


def _label_text(param: str, value: float) -> str:
    """Label of one column / row: power %, speed mm/s, interval mm, passes."""
    if param == "speed":
        return f"{value / 60:.0f}"
    if param == "passes":
        return f"{int(value)}x"
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
    for r in range(spec.rows):
        for c in range(spec.columns):
            st = spec.cell_settings(r, c)
            power, speed = st["power"], st["speed"]
            # The name format is parsed by lumacut_materials.testgrid (TEST_CELL_RE).
            layer = Layer(name=f"Test P{power:g}% F{speed:g}",
                          color=LAYER_COLORS[(r * spec.columns + c) % len(LAYER_COLORS)],
                          power=power, speed=speed, passes=st["passes"])
            if interval_test:
                # Recorded on the layer (fill stays off, so no effect on the G-code).
                layer.line_interval_mm = st["interval"]
            cell_layers.append(layer)
            x, y = ox + c * pitch, oy + r * pitch
            if spec.line_interval_mm:
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
