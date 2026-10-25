"""Arbeitsfläche und (unsichtbare) Safezone.

Die Benutzeroberfläche arbeitet ausschließlich in Arbeitsflächen-Koordinaten:
Ursprung oben links, X nach rechts, Y nach unten, Einheit Millimeter,
0..360 × 0..340 mm.

Die Maschine hat eine L-förmige 30-mm-Safezone (X < 30 oder Y < 30), in der
nicht geschnitten werden darf (siehe docs/MASCHINE.md). Diese Zone wird in der
UI bewusst nicht gezeigt: Die sichtbare Arbeitsfläche *ist* bereits der
erlaubte Schneidbereich X 30–390 / Y 30–370. Die Umrechnung in
Maschinenkoordinaten passiert nur an dieser einen Stelle.

Dieses Modul ist Qt-frei, damit es auch von Job-/Export-Code ohne GUI
benutzt werden kann.
"""

from __future__ import annotations

from dataclasses import dataclass

# Sichtbare Arbeitsfläche in mm.
WORK_WIDTH_MM: float = 360.0
WORK_HEIGHT_MM: float = 340.0

# Interne Safezone: Versatz der Arbeitsfläche im Maschinenkoordinatensystem.
_SAFEZONE_X_MM: float = 30.0
_SAFEZONE_Y_MM: float = 30.0


@dataclass(frozen=True)
class Rect:
    """Achsparalleles Rechteck in mm (w, h immer >= 0)."""

    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @staticmethod
    def from_points(x1: float, y1: float, x2: float, y2: float) -> "Rect":
        return Rect(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))

    def united(self, other: "Rect") -> "Rect":
        return Rect.from_points(
            min(self.x, other.x), min(self.y, other.y),
            max(self.right, other.right), max(self.bottom, other.bottom),
        )


WORK_RECT = Rect(0.0, 0.0, WORK_WIDTH_MM, WORK_HEIGHT_MM)


def is_inside_work_area(r: Rect, eps: float = 1e-6) -> bool:
    """True, wenn ``r`` komplett innerhalb der Arbeitsfläche liegt."""
    return (r.x >= -eps and r.y >= -eps
            and r.right <= WORK_WIDTH_MM + eps and r.bottom <= WORK_HEIGHT_MM + eps)


def clamp_offset(r: Rect) -> tuple[float, float]:
    """Verschiebung (dx, dy), die ``r`` in die Arbeitsfläche schiebt.

    Ist ``r`` größer als die Fläche, wird an der linken/oberen Kante
    ausgerichtet; das Verkleinern übernimmt :func:`fit_scale`.
    """
    dx = 0.0
    dy = 0.0
    if r.right > WORK_WIDTH_MM:
        dx = WORK_WIDTH_MM - r.right
    if r.x + dx < 0.0:
        dx = -r.x
    if r.bottom > WORK_HEIGHT_MM:
        dy = WORK_HEIGHT_MM - r.bottom
    if r.y + dy < 0.0:
        dy = -r.y
    return dx, dy


def fit_scale(r: Rect) -> float:
    """Gleichmäßiger Faktor (<= 1), damit ``r`` in die Arbeitsfläche passt."""
    sx = WORK_WIDTH_MM / r.w if r.w > WORK_WIDTH_MM else 1.0
    sy = WORK_HEIGHT_MM / r.h if r.h > WORK_HEIGHT_MM else 1.0
    return min(sx, sy)


def to_machine(x: float, y: float) -> tuple[float, float]:
    """Arbeitsflächen-mm → Maschinen-mm (Safezone-Versatz).

    Annahme: Die Maschinen-Y-Achse läuft in dieselbe Richtung wie die
    Canvas-Y-Achse. Das ist an der echten Maschine noch nicht verifiziert;
    falls Y gespiegelt werden muss, ist das ausschließlich hier zu ändern.
    """
    return x + _SAFEZONE_X_MM, y + _SAFEZONE_Y_MM


def from_machine(x: float, y: float) -> tuple[float, float]:
    """Maschinen-mm → Arbeitsflächen-mm (Umkehrung von :func:`to_machine`)."""
    return x - _SAFEZONE_X_MM, y - _SAFEZONE_Y_MM
