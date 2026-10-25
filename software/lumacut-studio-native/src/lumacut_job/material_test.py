"""Material test grid (power x speed), like xTool's "Material Test Array"
and LightBurn's Material Test.

Columns vary power, rows vary speed. Every cell gets its own canvas layer
(one layer = one laser setting in LumaCut), so the existing G-code path,
layer panel and preview work unchanged. Cells are either outlines or filled
with a serpentine hatch at ``line_interval_mm`` (engrave test). Optional
labels go on a separate low-power layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from lumacut_canvas.model import (LAYER_COLORS, PASSES_RANGE, POWER_RANGE, SPEED_RANGE,
                                  Document, Geometry, Layer, Shape)
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM


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

    def powers(self) -> list[float]:
        return _steps(self.power_min, self.power_max, self.columns)

    def speeds(self) -> list[float]:
        return _steps(self.speed_min, self.speed_max, self.rows)

    def size(self) -> tuple[float, float]:
        lab = (self.label_mm + 2) if self.labels else 0.0
        w = lab + self.columns * self.cell_mm + (self.columns - 1) * self.gap_mm
        h = lab + self.rows * self.cell_mm + (self.rows - 1) * self.gap_mm
        return w, h

    def validate(self) -> None:
        if not (1 <= self.columns <= 12 and 1 <= self.rows <= 12):
            raise ValueError("1..12 Spalten und Zeilen")
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


def _steps(lo: float, hi: float, n: int) -> list[float]:
    if n == 1:
        return [round(lo, 1)]
    return [round(lo + (hi - lo) * i / (n - 1), 1) for i in range(n)]


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
    ox, oy = spec.x + lab, spec.y + lab
    pitch = spec.cell_mm + spec.gap_mm
    cell_layers: list[Layer] = []
    for r, speed in enumerate(spec.speeds()):
        for c, power in enumerate(spec.powers()):
            layer = Layer(name=f"Test P{power:g}% F{speed:g}",
                          color=LAYER_COLORS[(r * spec.columns + c) % len(LAYER_COLORS)],
                          power=power, speed=speed, passes=spec.passes)
            cell_layers.append(layer)
            x, y = ox + c * pitch, oy + r * pitch
            if spec.line_interval_mm:
                shapes.append(Shape.from_points(
                    "path", hatch_points(x, y, spec.cell_mm, spec.cell_mm, spec.line_interval_mm),
                    layer.id))
            else:
                shapes.append(Shape("rect", Geometry(x, y, spec.cell_mm, spec.cell_mm), layer.id))
    if spec.labels:
        label = Layer(name="Test Beschriftung", color="#e8e36a", power=spec.label_power,
                      speed=spec.label_speed, passes=1)
        layers.append(label)
        th = spec.label_mm
        for c, power in enumerate(spec.powers()):
            shapes.append(Shape("text", Geometry(ox + c * pitch, spec.y, min(spec.cell_mm, th * 2.4), th),
                                label.id, text=f"{power:g}"))
        for r, speed in enumerate(spec.speeds()):
            shapes.append(Shape("text", Geometry(spec.x, oy + r * pitch + (spec.cell_mm - th) / 2,
                                                 th, th * 0.9 if speed < 1000 else th),
                                label.id, text=f"{speed / 60:.0f}"))
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
