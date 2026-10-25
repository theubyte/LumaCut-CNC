"""Planung der Abtastpunkte – nur dort, wo Werkstücke liegen.

* Raster je Bereich mit Randabstand (Tasterspitze fährt nie über die Kante)
* Tasterversatz X −23 / Y +15: Punkte, deren Kopfposition außerhalb des
  Fahrbereichs läge, werden übersprungen und gemeldet
* Reihenfolge: Bereiche per Nächster-Nachbar, innerhalb eines Bereichs eine
  Serpentine mit der günstigsten Einstiegsecke -> minimale Leerfahrt
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable, Optional, Sequence

from .geometry import (Polygon, Rect, MachineLimits, DEFAULT_LIMITS, PROBE_OFFSET_MM,
                       path_length)


@dataclass
class ProbeSettings:
    spacing_mm: float = 15.0          # Rasterabstand
    margin_mm: float = 4.0            # Abstand zur Werkstückkante
    safe_z: float = 20.0              # Rückzughöhe zwischen Bereichen (abs. Z)
    hop_mm: float = 3.0               # Anheben über letzte Oberfläche innerhalb eines Bereichs
    probe_feed: float = 216.0         # G30 langsam (mm/min)
    max_depth: float = -1.0           # tiefstes Z für G30 (abs.), darunter = kein Kontakt
    retries: int = 2
    retry_offset_mm: float = 1.0      # Wiederholung leicht versetzt (Span, Loch, Staub)
    outlier_mm: float = 0.8           # Abweichung vom Nachbar-Median, ab der nachgemessen wird
    max_points_per_area: int = 150
    adaptive: bool = True             # Zellen mit Krümmung nachverdichten
    adaptive_threshold_mm: float = 0.12
    adaptive_max_points: int = 40
    probe_offset_mm: tuple[float, float] = PROBE_OFFSET_MM
    xy_speed_mm_s: float = 150.0
    z_speed_mm_s: float = 10.0        # Z-Fahrten des Pi (600 mm/min)

    def validate(self) -> None:
        if not (1.0 <= self.spacing_mm <= 200):
            raise ValueError("spacing_mm must be 1..200")
        if self.margin_mm < 0 or self.hop_mm <= 0 or self.probe_feed <= 0:
            raise ValueError("invalid probe settings")
        if self.safe_z <= self.max_depth:
            raise ValueError("safe_z must be above max_depth")
        if self.retries < 0:
            raise ValueError("retries must be >= 0")


@dataclass
class ProbeArea:
    id: str
    polygon: Polygon
    kind: str = "rectangle"           # rectangle | circle | polygon | design | manual
    source: str = "detected"          # detected | design | manual
    spacing_mm: Optional[float] = None

    @property
    def bounds(self) -> Rect:
        return self.polygon.bounds

    @classmethod
    def from_rect(cls, id: str, rect: Rect, source: str = "manual", **kw) -> "ProbeArea":
        return cls(id, rect.to_polygon(), "rectangle", source, **kw)


@dataclass(frozen=True)
class ProbePoint:
    area_id: str
    i: int          # Spalte im Raster
    j: int          # Zeile im Raster
    x: float
    y: float


@dataclass
class AreaGrid:
    area: ProbeArea
    xs: list[float]
    ys: list[float]
    points: list[ProbePoint]          # in Fahrreihenfolge
    skipped: list[tuple[float, float, str]] = field(default_factory=list)


@dataclass
class ProbeJob:
    settings: ProbeSettings
    grids: list[AreaGrid]
    warnings: list[str] = field(default_factory=list)

    @property
    def points(self) -> list[ProbePoint]:
        return [p for g in self.grids for p in g.points]

    def travel_mm(self, start=(0.0, 0.0)) -> float:
        return path_length([(p.x, p.y) for p in self.points], start)

    def estimate_seconds(self, start=(0.0, 0.0), expected_surface_z: float = 3.0) -> float:
        """Dauer: XY-Fahrten + Z-Hub + G30 (schnell 432, langsam 216 mm/min)."""
        s = self.settings
        t = 0.0
        prev = start
        for g in self.grids:
            first = True
            for p in g.points:
                d = math.hypot(p.x - prev[0], p.y - prev[1])
                t += d / s.xy_speed_mm_s + 0.2  # Beschleunigung
                lift = (s.safe_z - expected_surface_z) if first else s.hop_mm
                t += lift / s.z_speed_mm_s            # anheben
                t += lift / (432 / 60)                # G30 schnell runter
                t += 2.0 / (s.z_speed_mm_s) + 2.0 / (s.probe_feed / 60)  # zurück + langsam
                t += 2 * 23.0 / s.xy_speed_mm_s * 0.5  # Tasterversatz hin/zurück
                prev = (p.x, p.y)
                first = False
        return t


def areas_from_objects(objects: Iterable, spacing_mm: Optional[float] = None) -> list[ProbeArea]:
    """Erkannte Objekte (``DetectedObject``) -> Abtastbereiche."""
    return [ProbeArea(o.id, o.polygon, o.kind, "detected", spacing_mm) for o in objects]


def areas_from_design_bounds(design_bounds: Sequence[Rect], objects: Sequence = (),
                             pad_mm: float = 3.0, include_unused_objects: bool = False
                             ) -> tuple[list[ProbeArea], list[str]]:
    """Bereichsvorschlag aus den Design-Bounding-Boxen des Canvas.

    Liegt ein Design auf einem erkannten Werkstück, wird der Umriss des
    Werkstücks genommen (nur dieser Teil wird geprobt, sauberer Rand). Ohne
    Werkstück wird die Design-Box + ``pad_mm`` vorgeschlagen und gewarnt.
    """
    areas: list[ProbeArea] = []
    notes: list[str] = []
    used: set[str] = set()
    for k, rect in enumerate(design_bounds, 1):
        hits = [o for o in objects if o.bounds.intersect(rect) is not None]
        if hits:
            for o in hits:
                if o.id not in used:
                    used.add(o.id)
                    areas.append(ProbeArea(o.id, o.polygon, o.kind, "detected"))
        else:
            areas.append(ProbeArea(f"design{k}", rect.expand(pad_mm).to_polygon(), "design", "design"))
            notes.append(f"Design {k}: kein Werkstück darunter erkannt – Design-Box wird geprobt.")
    if include_unused_objects:
        for o in objects:
            if o.id not in used:
                areas.append(ProbeArea(o.id, o.polygon, o.kind, "detected"))
    return areas, notes


def _grid_axis(lo: float, hi: float, spacing: float) -> list[float]:
    if hi - lo < 1e-9:
        return [(lo + hi) / 2]
    n = max(2, math.ceil((hi - lo) / spacing) + 1)
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def grid_for_area(area: ProbeArea, settings: ProbeSettings,
                  limits: MachineLimits = DEFAULT_LIMITS) -> AreaGrid:
    spacing = area.spacing_mm or settings.spacing_mm
    poly = area.polygon
    b = poly.bounds
    margin = settings.margin_mm
    inner = b.inset(margin)
    if inner is None:
        margin = min(b.width, b.height) / 4  # kleines Teil: Rand halbieren
        inner = b.inset(margin) or Rect(*b.center, *b.center)
    xs = _grid_axis(inner.xmin, inner.xmax, spacing)
    ys = _grid_axis(inner.ymin, inner.ymax, spacing)
    while len(xs) * len(ys) > settings.max_points_per_area:
        spacing *= 1.25
        xs = _grid_axis(inner.xmin, inner.xmax, spacing)
        ys = _grid_axis(inner.ymin, inner.ymax, spacing)
    ox, oy = settings.probe_offset_mm
    pts: dict[tuple[int, int], ProbePoint] = {}
    skipped: list[tuple[float, float, str]] = []
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            if not poly.contains_with_margin(x, y, margin):
                continue
            head = (x - ox, y - oy)
            if not limits.reachable(*head):
                skipped.append((x, y, "Taster erreicht Punkt nicht (Versatz)"))
                continue
            pts[(i, j)] = ProbePoint(area.id, i, j, x, y)
    if not pts:
        cx, cy = poly.centroid
        if poly.contains(cx, cy) and limits.reachable(cx - ox, cy - oy):
            xs, ys = [cx], [cy]
            pts[(0, 0)] = ProbePoint(area.id, 0, 0, cx, cy)
    return AreaGrid(area, xs, ys, list(pts.values()), skipped)


def _serpentine(grid: AreaGrid, start: tuple[float, float]) -> list[ProbePoint]:
    """Beste von 8 Serpentinen-Varianten (Ecke × Zeilen/Spalten zuerst)."""
    by = {(p.i, p.j): p for p in grid.points}
    if not by:
        return []
    ni, nj = len(grid.xs), len(grid.ys)
    best, best_len = None, math.inf
    for rows_first in (True, False):
        for flip_i in (False, True):
            for flip_j in (False, True):
                order = []
                outer = range(nj) if rows_first else range(ni)
                inner_n = ni if rows_first else nj
                for k, a in enumerate(outer):
                    inner = list(range(inner_n))
                    if k % 2:
                        inner.reverse()
                    for b in inner:
                        i, j = (b, a) if rows_first else (a, b)
                        if flip_i:
                            i = ni - 1 - i
                        if flip_j:
                            j = nj - 1 - j
                        if (i, j) in by:
                            order.append(by[(i, j)])
                ln = path_length([(p.x, p.y) for p in order], start)
                if ln < best_len:
                    best, best_len = order, ln
    return best


def plan_probe_job(areas: Sequence[ProbeArea], settings: Optional[ProbeSettings] = None,
                   start: tuple[float, float] = (0.0, 0.0),
                   limits: MachineLimits = DEFAULT_LIMITS) -> ProbeJob:
    settings = settings or ProbeSettings()
    settings.validate()
    grids = [grid_for_area(a, settings, limits) for a in areas]
    warnings = []
    for g in grids:
        if not g.points:
            warnings.append(f"Bereich {g.area.id}: kein abtastbarer Punkt (zu klein oder außer Reichweite).")
        elif g.skipped:
            warnings.append(f"Bereich {g.area.id}: {len(g.skipped)} Punkt(e) wegen Tasterversatz übersprungen.")
    remaining = [g for g in grids if g.points]
    ordered: list[AreaGrid] = []
    pos = start
    while remaining:
        # nächster Bereich = kleinste Distanz zu irgendeinem seiner Punkte
        g = min(remaining, key=lambda g: min(math.hypot(p.x - pos[0], p.y - pos[1]) for p in g.points))
        remaining.remove(g)
        g.points = _serpentine(g, pos)
        pos = (g.points[-1].x, g.points[-1].y)
        ordered.append(g)
    ordered += [g for g in grids if not g.points]
    return ProbeJob(settings, ordered, warnings)
