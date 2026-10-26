"""Geometrie-Grundlagen in Maschinenkoordinaten (mm).

Maschinen-Null X0/Y0 = Homing-Ecke, Arbeitsraum X 390 × Y 370 mm,
Safezone X < 30 oder Y < 30 (siehe docs/MASCHINE.md).
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence

Point = tuple[float, float]

#: Tasterspitze relativ zum Laserpunkt (docs/MASCHINE.md, Stand 25.10.2026).
PROBE_OFFSET_MM: Point = (-23.0, 15.0)
#: Marlin lässt G30 nur bis ``BED_SIZE − PROBING_MARGIN`` zu (Kopf X380/Y360).
PROBING_MARGIN_MM = 10.0


@dataclass(frozen=True)
class MachineLimits:
    """Fahrbereich des Kopfes (Laserpunkt) und Safezone für Bearbeitung."""
    x_max: float = 390.0
    y_max: float = 370.0
    x_min: float = 0.0
    y_min: float = 0.0
    safezone: float = 30.0

    def reachable(self, x: float, y: float, eps: float = 1e-6) -> bool:
        return (self.x_min - eps <= x <= self.x_max + eps
                and self.y_min - eps <= y <= self.y_max + eps)

    def probe_head_ok(self, x: float, y: float, eps: float = 1e-6) -> bool:
        """Kopfposition, an der der Pi ``G30`` zulässt (``transport._probe_head_ok``):
        X/Y ab Safezone 30 bis 380/360 (Marlin ``PROBING_MARGIN`` 10 mm, Anf. §2.4)."""
        return (self.safezone - eps <= x <= self.x_max - PROBING_MARGIN_MM + eps
                and self.safezone - eps <= y <= self.y_max - PROBING_MARGIN_MM + eps)

    def probe_laser_rect(self, offset: tuple[float, float]) -> "Rect":
        """Laserpunkte, die der Taster abtasten kann (Kopf = Punkt − Versatz),
        geschnitten mit der Bearbeitungszone. Mit −23/+15: X30–357, Y45–370."""
        dx, dy = offset
        return Rect(max(self.safezone + dx, self.safezone), max(self.safezone + dy, self.safezone),
                    min(self.x_max - PROBING_MARGIN_MM + dx, self.x_max),
                    min(self.y_max - PROBING_MARGIN_MM + dy, self.y_max))

    def in_work_zone(self, x: float, y: float, eps: float = 1e-6) -> bool:
        """Bearbeitungszone (außerhalb der Safezone)."""
        return (self.safezone - eps <= x <= self.x_max + eps
                and self.safezone - eps <= y <= self.y_max + eps)

    @property
    def work_rect(self) -> "Rect":
        return Rect(self.safezone, self.safezone, self.x_max, self.y_max)


DEFAULT_LIMITS = MachineLimits()


@dataclass(frozen=True)
class Rect:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.xmin, self.ymin, self.xmax, self.ymax)):
            raise ValueError("Rect needs finite coordinates")
        if self.xmax < self.xmin or self.ymax < self.ymin:
            raise ValueError("Rect max must be >= min")

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin

    @property
    def center(self) -> Point:
        return ((self.xmin + self.xmax) / 2, (self.ymin + self.ymax) / 2)

    @property
    def area(self) -> float:
        return self.width * self.height

    def contains(self, x: float, y: float, eps: float = 1e-9) -> bool:
        return (self.xmin - eps <= x <= self.xmax + eps
                and self.ymin - eps <= y <= self.ymax + eps)

    def inset(self, d: float) -> "Rect | None":
        if self.width < 2 * d or self.height < 2 * d:
            return None
        return Rect(self.xmin + d, self.ymin + d, self.xmax - d, self.ymax - d)

    def expand(self, d: float) -> "Rect":
        return Rect(self.xmin - d, self.ymin - d, self.xmax + d, self.ymax + d)

    def intersect(self, other: "Rect") -> "Rect | None":
        x0, y0 = max(self.xmin, other.xmin), max(self.ymin, other.ymin)
        x1, y1 = min(self.xmax, other.xmax), min(self.ymax, other.ymax)
        if x1 < x0 or y1 < y0:
            return None
        return Rect(x0, y0, x1, y1)

    def to_polygon(self) -> "Polygon":
        return Polygon(((self.xmin, self.ymin), (self.xmax, self.ymin),
                        (self.xmax, self.ymax), (self.xmin, self.ymax)))

    def to_list(self) -> list[float]:
        return [self.xmin, self.ymin, self.xmax, self.ymax]

    @classmethod
    def from_points(cls, pts: Iterable[Sequence[float]]) -> "Rect":
        pts = list(pts)
        if not pts:
            raise ValueError("No points")
        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
        return cls(min(xs), min(ys), max(xs), max(ys))


@dataclass(frozen=True)
class Polygon:
    """Einfaches Polygon (Punkte gegen den oder im Uhrzeigersinn)."""
    points: tuple[Point, ...]

    def __post_init__(self):
        pts = tuple((float(x), float(y)) for x, y in self.points)
        if len(pts) < 3:
            raise ValueError("Polygon needs at least 3 points")
        if not all(math.isfinite(v) for p in pts for v in p):
            raise ValueError("Polygon needs finite coordinates")
        object.__setattr__(self, "points", pts)

    @property
    def bounds(self) -> Rect:
        return Rect.from_points(self.points)

    @property
    def area(self) -> float:
        s = 0.0
        n = len(self.points)
        for i in range(n):
            x0, y0 = self.points[i]
            x1, y1 = self.points[(i + 1) % n]
            s += x0 * y1 - x1 * y0
        return abs(s) / 2

    @property
    def centroid(self) -> Point:
        a = 0.0
        cx = cy = 0.0
        n = len(self.points)
        for i in range(n):
            x0, y0 = self.points[i]
            x1, y1 = self.points[(i + 1) % n]
            c = x0 * y1 - x1 * y0
            a += c
            cx += (x0 + x1) * c
            cy += (y0 + y1) * c
        if abs(a) < 1e-12:
            return self.bounds.center
        a *= 0.5
        return (cx / (6 * a), cy / (6 * a))

    def contains(self, x: float, y: float) -> bool:
        """Ray-Casting; Punkte auf dem Rand gelten als innen."""
        if self.edge_distance(x, y) < 1e-9:
            return True
        inside = False
        pts = self.points
        n = len(pts)
        j = n - 1
        for i in range(n):
            xi, yi = pts[i]
            xj, yj = pts[j]
            if (yi > y) != (yj > y):
                xc = (xj - xi) * (y - yi) / (yj - yi) + xi
                if x < xc:
                    inside = not inside
            j = i
        return inside

    def edge_distance(self, x: float, y: float) -> float:
        best = math.inf
        n = len(self.points)
        for i in range(n):
            best = min(best, _seg_dist(x, y, self.points[i], self.points[(i + 1) % n]))
        return best

    def contains_with_margin(self, x: float, y: float, margin: float) -> bool:
        """Innen und mindestens ``margin`` mm vom Rand entfernt."""
        if not self.contains(x, y):
            return False
        return margin <= 0 or self.edge_distance(x, y) >= margin - 1e-9

    def to_list(self) -> list[list[float]]:
        return [[x, y] for x, y in self.points]


def _seg_dist(px: float, py: float, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def circle_polygon(cx: float, cy: float, r: float, segments: int = 48) -> Polygon:
    return Polygon(tuple((cx + r * math.cos(2 * math.pi * i / segments),
                          cy + r * math.sin(2 * math.pi * i / segments))
                         for i in range(segments)))


def path_length(points: Sequence[Point], start: Point | None = None) -> float:
    total = 0.0
    prev = start
    for p in points:
        if prev is not None:
            total += math.hypot(p[0] - prev[0], p[1] - prev[1])
        prev = p
    return total
