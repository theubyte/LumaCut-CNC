"""Scanning offset adjustment: speed table for bidirectional scan lines.

LightBurn "Scanning Offset Adjustment" (and xTool's bidirectional
calibration): a moving head fires the laser slightly late, so every scan
line burns a little *in its direction of travel*. Lines going one way and
lines coming back are therefore displaced against each other – vertical
edges of a bidirectional fill or image look jagged / blurred, and the effect
grows with the speed. The offset measured on the burn (distance between the
edges of forward and reverse lines) is entered per speed in a table; values
in between are interpolated linearly, outside the table the nearest entry
is used.

Compensation model (one rule for images and vector fills): every scan line
is shifted by **half** the offset *against* its own direction of travel, so
forward and reverse lines meet and the engraving stays centred on the
contour – also when scanning is unidirectional. The image engine
(:mod:`.raster`) and the hatch / cross-hatch G-code
(``JobLayer.fill_scan_offset_mm`` in :mod:`lumacut_canvas.gcode`) apply it;
contours and offset fill (rings) are traced paths and stay as they are.

The table is a machine property: it is stored once in the app settings
(:mod:`.scan_offset_qt`) and becomes the process-wide :func:`active_table`
that :func:`lumacut_job.planner.optimized_document_gcode` uses by default,
so send, save, estimate, frame and the path preview all see the same job.
An empty or switched-off table leaves every program byte for byte unchanged.

:func:`test_pattern_gcode` builds the calibration job: one row per speed,
one patch per trial offset, labelled; the patch with straight edges gives
the value for that speed. Pure Python apart from the optional labels.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

SPEED_RANGE = (1.0, 6000.0)       # mm/min, like the layer speed
OFFSET_RANGE = (-2.0, 2.0)        # mm, like raster.RasterSettings
MAX_ENTRIES = 32
FORMAT_VERSION = 1


def _num(v, what: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"Scan-Versatz: {what} ist keine Zahl") from None
    if not math.isfinite(x):
        raise ValueError(f"Scan-Versatz: {what} ist keine Zahl")
    return x


@dataclass
class ScanOffsetTable:
    """Speed (mm/min) → offset (mm) between forward and reverse lines."""

    enabled: bool = True
    entries: list[tuple[float, float]] = field(default_factory=list)

    def normalized(self) -> "ScanOffsetTable":
        """Validated copy, sorted by speed (``ValueError`` in German)."""
        if len(self.entries) > MAX_ENTRIES:
            raise ValueError(f"Scan-Versatz: höchstens {MAX_ENTRIES} Einträge")
        rows: dict[float, float] = {}
        for item in self.entries:
            try:
                speed, offset = item
            except (TypeError, ValueError):
                raise ValueError("Scan-Versatz: Eintrag braucht Geschwindigkeit und Versatz") from None
            speed = round(_num(speed, "Geschwindigkeit"), 3)
            offset = round(_num(offset, "Versatz"), 4)
            if not SPEED_RANGE[0] <= speed <= SPEED_RANGE[1]:
                raise ValueError("Scan-Versatz: Geschwindigkeit 1..6000 mm/min")
            if not OFFSET_RANGE[0] <= offset <= OFFSET_RANGE[1]:
                raise ValueError("Scan-Versatz: Versatz −2..2 mm")
            if speed in rows:
                raise ValueError(f"Scan-Versatz: Geschwindigkeit {speed:g} mm/min doppelt")
            rows[speed] = offset
        return ScanOffsetTable(bool(self.enabled), sorted(rows.items()))

    @property
    def active(self) -> bool:
        return bool(self.enabled) and any(abs(o) > 1e-9 for _, o in self.entries)

    def offset_for(self, speed_mm_min: float) -> float:
        """Offset (mm) at ``speed_mm_min``; 0 when off or empty.

        Linear between neighbouring entries, the nearest entry outside the
        table (no extrapolation – a guess beyond the measured speeds would be
        worse than the last measured value)."""
        if not self.enabled or not self.entries:
            return 0.0
        rows = sorted(self.entries)
        v = float(speed_mm_min)
        if v <= rows[0][0]:
            return rows[0][1]
        if v >= rows[-1][0]:
            return rows[-1][1]
        for (s0, o0), (s1, o1) in zip(rows, rows[1:]):
            if s0 <= v <= s1:
                t = (v - s0) / (s1 - s0) if s1 > s0 else 0.0
                return round(o0 + (o1 - o0) * t, 4)
        return 0.0  # pragma: no cover

    # --- storage -----------------------------------------------------------
    def to_dict(self) -> dict:
        return {"version": FORMAT_VERSION, "enabled": bool(self.enabled),
                "entries": [[s, o] for s, o in sorted(self.entries)]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, data) -> "ScanOffsetTable":
        if not isinstance(data, dict):
            raise ValueError("Scan-Versatz: ungültige Einstellung")
        entries = data.get("entries") or []
        if not isinstance(entries, list):
            raise ValueError("Scan-Versatz: ungültige Einstellung")
        return cls(bool(data.get("enabled", True)),
                   [tuple(e) if isinstance(e, (list, tuple)) else e for e in entries]).normalized()

    @classmethod
    def from_json(cls, text: str) -> "ScanOffsetTable":
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            raise ValueError("Scan-Versatz: ungültige Einstellung") from None
        return cls.from_dict(data)

    def summary(self) -> str:
        """Short German description for the status bar / planner note."""
        if not self.active:
            return ""
        parts = [f"{o:+.2f} mm @ {s:g}" for s, o in sorted(self.entries)]
        if len(parts) > 3:
            parts = parts[:1] + ["…"] + parts[-1:]
        return "Scan-Versatz " + ", ".join(parts).replace(".", ",") + " mm/min"


# --- process-wide table (machine property) ----------------------------------
_ACTIVE = ScanOffsetTable(enabled=False)


def active_table() -> ScanOffsetTable:
    return _ACTIVE


def set_active_table(table: ScanOffsetTable | None) -> ScanOffsetTable:
    """Make ``table`` (validated) the table used by the planner; returns the old one."""
    global _ACTIVE
    old = _ACTIVE
    _ACTIVE = table.normalized() if table is not None else ScanOffsetTable(enabled=False)
    return old


# --- geometry -----------------------------------------------------------------
def shift_segment(a, b, offset_mm: float):
    """Scan line ``a → b`` (machine mm) moved by ``offset_mm / 2`` against its
    direction, kept inside the machine area (see ``gcode.scan_offset_segment``)."""
    from lumacut_canvas.gcode import scan_offset_segment
    return scan_offset_segment(a, b, offset_mm)


def apply_to_layers(layers, table: ScanOffsetTable | None):
    """Copy of the ``JobLayer`` list with ``fill_scan_offset_mm`` set.

    Only line fills (hatch / cross-hatch: fills present and not
    ``fill_fixed_order``) get the offset at the layer speed; layers are
    returned unchanged (same objects) when the table is inactive."""
    from dataclasses import replace
    if table is None or not table.active:
        return list(layers)
    out = []
    for layer in layers:
        if getattr(layer, "fills", None) and not getattr(layer, "fill_fixed_order", False):
            off = table.offset_for(layer.speed_mm_min)
            if abs(off) > 1e-9:
                layer = replace(layer, fill_scan_offset_mm=off)
        out.append(layer)
    return out


# --- calibration pattern ------------------------------------------------------
@dataclass
class ScanTestSpec:
    """Calibration job: rows = speeds, columns = trial offsets."""

    speeds: list[float] = field(default_factory=lambda: [1000.0, 2000.0, 3000.0, 4000.0, 6000.0])
    offset_min: float = 0.0          # mm
    offset_max: float = 0.4
    offset_step: float = 0.1
    power: float = 40.0              # %
    line_interval_mm: float = 0.3
    patch_w_mm: float = 8.0
    patch_h_mm: float = 5.0
    gap_mm: float = 3.0
    x: float = 20.0                  # top-left, work-area mm
    y: float = 20.0
    overscan_mm: float = 2.0
    labels: bool = True
    label_mm: float = 2.5
    label_power: float = 15.0
    label_speed: float = 3000.0

    def offsets(self) -> list[float]:
        n = int(math.floor((self.offset_max - self.offset_min) / self.offset_step + 1e-6)) + 1
        return [round(self.offset_min + i * self.offset_step, 4) for i in range(n)]

    def label_w(self) -> float:
        return self.label_mm * 3.2 + 2 if self.labels else 0.0

    def size(self) -> tuple[float, float]:
        cols, rows = len(self.offsets()), len(self.speeds)
        top = self.label_mm + 2 if self.labels else 0.0
        w = self.label_w() + cols * self.patch_w_mm + (cols - 1) * self.gap_mm
        h = top + rows * self.patch_h_mm + (rows - 1) * self.gap_mm
        return w, h

    def validate(self) -> None:
        from lumacut_canvas.model import POWER_RANGE
        from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM
        if not 1 <= len(self.speeds) <= 10:
            raise ValueError("Scan-Test: 1..10 Geschwindigkeiten")
        if len(set(round(float(s), 3) for s in self.speeds)) != len(self.speeds):
            raise ValueError("Scan-Test: Geschwindigkeit doppelt")
        for s in list(self.speeds) + [self.label_speed]:
            if not SPEED_RANGE[0] <= float(s) <= SPEED_RANGE[1]:
                raise ValueError("Scan-Test: Geschwindigkeit 1..6000 mm/min")
        if not (OFFSET_RANGE[0] <= self.offset_min <= self.offset_max <= OFFSET_RANGE[1]):
            raise ValueError("Scan-Test: Versatz −2..2 mm, von ≤ bis")
        if not 0.01 <= self.offset_step <= 1.0:
            raise ValueError("Scan-Test: Schrittweite 0,01..1 mm")
        if not 1 <= len(self.offsets()) <= 12:
            raise ValueError("Scan-Test: 1..12 Versatz-Spalten")
        for p in (self.power, self.label_power):
            if not POWER_RANGE[0] <= p <= POWER_RANGE[1]:
                raise ValueError("Scan-Test: Leistung 1..100 %")
        if not 0.05 <= self.line_interval_mm <= 2.0:
            raise ValueError("Scan-Test: Linienabstand 0,05..2 mm")
        if not (2 <= self.patch_w_mm <= 50 and 1 <= self.patch_h_mm <= 50 and 0 <= self.gap_mm <= 30):
            raise ValueError("Scan-Test: Feld 2..50 × 1..50 mm, Abstand 0..30 mm")
        if not 0 <= self.overscan_mm <= 20:
            raise ValueError("Scan-Test: Overscan 0..20 mm")
        w, h = self.size()
        if self.x < 0 or self.y < 0 or self.x + w > WORK_WIDTH_MM or self.y + h > WORK_HEIGHT_MM:
            raise ValueError("Scan-Test passt nicht auf die Arbeitsfläche")


def _patch_segments(x: float, y: float, w: float, h: float, interval: float):
    """Horizontal bidirectional lines of one patch (work-area mm)."""
    n = max(1, int(round(h / interval)))
    segs = []
    for i in range(n + 1):
        yy = y + h * i / n
        a, b = (x, yy), (x + w, yy)
        segs.append((a, b) if i % 2 == 0 else (b, a))
    return segs


def _fmt_offset(o: float) -> str:
    return f"{o:+.2f}".replace("+0.00", "0").replace(".", ",")


def test_pattern_layers(spec: ScanTestSpec):
    """``JobLayer`` list of the calibration job (labels last)."""
    from lumacut_canvas.export import JobLayer
    from lumacut_canvas.workarea import to_machine
    spec.validate()
    top = spec.label_mm + 2 if spec.labels else 0.0
    ox, oy = spec.x + spec.label_w(), spec.y + top
    layers = []
    for r, speed in enumerate(spec.speeds):
        for c, off in enumerate(spec.offsets()):
            x = ox + c * (spec.patch_w_mm + spec.gap_mm)
            y = oy + r * (spec.patch_h_mm + spec.gap_mm)
            segs = [(to_machine(*a), to_machine(*b))
                    for a, b in _patch_segments(x, y, spec.patch_w_mm, spec.patch_h_mm,
                                                spec.line_interval_mm)]
            layers.append(JobLayer(f"scan{r}_{c}", f"Scan-Test F{speed:g} V{off:+.2f}",
                                   spec.power, float(speed), 1, [], fills=[segs],
                                   fill_fixed_order=True, fill_overscan_mm=spec.overscan_mm,
                                   fill_scan_offset_mm=off))
    if spec.labels:
        layers += _label_layers(spec, ox, oy)
    return layers


def _label_layers(spec: ScanTestSpec, ox: float, oy: float):
    """Text outlines: offsets above the columns, speeds left of the rows."""
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.model import Document, Geometry, Layer, Shape
    doc = Document(with_default_layer=False)
    label = Layer(name="Scan-Test Beschriftung", color="#e8e36a", power=spec.label_power,
                  speed=spec.label_speed, passes=1)
    doc.add_layer(label, 0)
    th = spec.label_mm
    for c, off in enumerate(spec.offsets()):
        text = _fmt_offset(off)
        doc.add_shape(Shape("text", Geometry(ox + c * (spec.patch_w_mm + spec.gap_mm), spec.y,
                                             min(spec.patch_w_mm, th * 0.62 * len(text)), th),
                            label.id, text=text))
    for r, speed in enumerate(spec.speeds):
        text = f"{float(speed):g}"
        y = oy + r * (spec.patch_h_mm + spec.gap_mm) + (spec.patch_h_mm - th) / 2
        doc.add_shape(Shape("text", Geometry(spec.x, y, min(spec.label_w() - 2, th * 0.62 * len(text)), th),
                            label.id, text=text))
    return job_layers(doc)


def test_pattern_gcode(spec: ScanTestSpec) -> str:
    """G-code of the calibration job (Pi-safe like every canvas job)."""
    from lumacut_canvas.gcode import layers_to_gcode
    lines = layers_to_gcode(test_pattern_layers(spec)).splitlines()
    head = [lines[0], "; SCAN OFFSET TEST rows=speed mm/min, columns=offset mm "
            + " ".join(f"{o:+.2f}" for o in spec.offsets())]
    return "\n".join(head + lines[1:]) + "\n"


# pytest must not collect the two public helpers above as tests
test_pattern_layers.__test__ = False  # type: ignore[attr-defined]
test_pattern_gcode.__test__ = False   # type: ignore[attr-defined]
