"""Messen (Werkzeug „Messen“, M) – Abstand und Winkel zwischen zwei Punkten wie
LightBurns *Measure*-Werkzeug. Qt-frei; Bedienung in :mod:`measure_ui`.

Punkte kommen in Bildschirm-mm der Arbeitsfläche (``x`` nach rechts, ``y`` nach
unten). Angezeigt wird:

* **Abstand** – Länge der Strecke (immer positiv),
* **ΔX / ΔY** – Differenz der *angezeigten* Koordinaten Ende − Start, also mit
  dem Nullpunkt oben rechts (:func:`~.workarea.screen_to_user`: X zählt nach links,
  Y nach unten) – passend zu den X/Y-Feldern der Eigenschaftsleiste,
* **Winkel** – Richtung der Strecke auf dem Bildschirm wie mit einem Winkelmesser:
  0° = nach rechts, 90° = nach oben, gegen den Uhrzeigersinn positiv, −180°…180°.

Eine Messung ist kein Objekt des Dokuments: kein Undo-Schritt, nicht gespeichert,
kein Einfluss auf G-Code oder Pi-Prüfung.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import units
from .workarea import screen_to_user

#: Umschalt rastet die Richtung in diesen Schritten ein (wie das Drehen).
ANGLE_STEP_DEG = 15.0


def _norm_angle(a: float) -> float:
    """Winkel auf (−180°, 180°]."""
    a = math.fmod(a, 360.0)
    if a <= -180.0:
        a += 360.0
    elif a > 180.0:
        a -= 360.0
    return 0.0 if abs(a) < 1e-9 else a


@dataclass(frozen=True)
class Measurement:
    """Strecke von ``(x1, y1)`` nach ``(x2, y2)`` in Bildschirm-mm."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def start(self) -> tuple[float, float]:
        return (self.x1, self.y1)

    @property
    def end(self) -> tuple[float, float]:
        return (self.x2, self.y2)

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    @property
    def dx(self) -> float:
        """ΔX in angezeigten Koordinaten (Nullpunkt oben rechts: X zählt nach links)."""
        return screen_to_user(self.x2, self.y2)[0] - screen_to_user(self.x1, self.y1)[0]

    @property
    def dy(self) -> float:
        """ΔY in angezeigten Koordinaten (nach unten positiv)."""
        return screen_to_user(self.x2, self.y2)[1] - screen_to_user(self.x1, self.y1)[1]

    @property
    def angle(self) -> float:
        """Richtung auf dem Bildschirm: 0° rechts, 90° oben, −180°…180° (0 bei Länge 0)."""
        if self.length < 1e-12:
            return 0.0
        return _norm_angle(math.degrees(math.atan2(-(self.y2 - self.y1), self.x2 - self.x1)))

    @property
    def is_point(self) -> bool:
        return self.length < 1e-9

    def midpoint(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)


def constrain(start: tuple[float, float], end: tuple[float, float],
              step_deg: float = ANGLE_STEP_DEG) -> tuple[float, float]:
    """Endpunkt auf die nächste ``step_deg``-Richtung vom Start aus legen (Umschalt).

    Die Länge ist die Projektion des Endpunkts auf diese Richtung (wie die
    Polygonkante mit Umschalt) – der Punkt bleibt so nah wie möglich an der Maus.
    """
    sx, sy = start
    w, h = end[0] - sx, end[1] - sy
    if abs(w) < 1e-12 and abs(h) < 1e-12:
        return (sx, sy)
    step = math.radians(step_deg)
    ang = round(math.atan2(h, w) / step) * step
    length = w * math.cos(ang) + h * math.sin(ang)
    x, y = sx + length * math.cos(ang), sy + length * math.sin(ang)
    return (0.0 if abs(x) < 1e-12 else x, 0.0 if abs(y) < 1e-12 else y)


def _signed(mm: float, unit: str) -> str:
    """Länge mit Vorzeichen (echtes Minuszeichen, kein „−0.00“)."""
    d = units.DECIMALS[units.check(unit)]
    v = round(units.to_display(mm, unit), d)
    text = units.format_length(units.from_display(v, unit) if v != 0 else 0.0, unit)
    return text.replace("-", "\u2212")


def format_angle(deg: float) -> str:
    text = f"{deg:.1f}°"
    if text in ("-0.0°", "-180.0°"):
        text = text.lstrip("-")
    return text.replace("-", "\u2212")


def label_lines(m: Measurement, unit: str) -> list[str]:
    """Beschriftung auf der Zeichenfläche (drei Zeilen)."""
    return [units.format_length(m.length, unit),
            f"ΔX {_signed(m.dx, unit)}   ΔY {_signed(m.dy, unit)}",
            f"Winkel {format_angle(m.angle)}"]


def readout(m: Measurement, unit: str) -> str:
    """Eine Zeile für die Statusleiste."""
    return (f"Messen: Abstand {units.format_length(m.length, unit)} · ΔX {_signed(m.dx, unit)}"
            f" · ΔY {_signed(m.dy, unit)} · Winkel {format_angle(m.angle)}")


def clipboard_text(m: Measurement, unit: str) -> str:
    """Abstand mit Einheit („42.43 mm“) – lässt sich in jedes Längenfeld einfügen
    (:func:`~.units.parse_length` versteht die angehängte Einheit)."""
    return units.format_length(m.length, unit)


__all__ = ["ANGLE_STEP_DEG", "Measurement", "clipboard_text", "constrain", "format_angle",
           "label_lines", "readout"]
