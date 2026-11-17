"""Passmarken ausrichten (Werkzeug „Passmarken“, Alt+Umschalt+M) – Design an zwei
Punkten auf das echte Werkstück legen wie LightBurns *Print and Cut* / *Align to
two points*. Qt-frei; Bedienung in :mod:`marks_ui`.

Ein Passmarken-Paar besteht aus einem **Soll-Punkt** (wo die Marke im Design
liegt, z. B. die Mitte eines gedruckten Fadenkreuzes) und einem **Ist-Punkt**
(wo sie wirklich auf dem Bett liegt – auf dem Kamerascan angetippt oder als
Zahl gemessen). Alle Punkte sind Bildschirm-mm der Arbeitsfläche (``x`` nach
rechts, ``y`` nach unten).

* **Ein Paar** verschiebt nur: der Soll-Punkt landet genau auf dem Ist-Punkt.
* **Zwei Paare** verschieben und drehen. Ohne „Maßstab angleichen“ (Vorgabe)
  bleibt das Design maßhaltig (starre Bewegung): die Mitte der Soll-Punkte
  landet auf der Mitte der Ist-Punkte, die Richtung Soll 1 → Soll 2 auf der
  Richtung Ist 1 → Ist 2 – passt der gemessene Abstand nicht genau, verteilt
  sich die Abweichung zur Hälfte auf beide Marken (:attr:`MarkFit.error_mm`).
  Mit „Maßstab angleichen“ wird zusätzlich gleichmäßig skaliert, beide Marken
  treffen dann genau (für einen Druck, der etwas größer / kleiner kam).
* Gedrehte Objekte, Text, Bilder, Linien, Stege und Startpunkte gehen über die
  vorhandene Geometrie (:meth:`~model.Geometry.mapped` / ``rotated`` /
  ``translated``) mit – keine Scherung, kein neuer Projekt-Schlüssel.

Unplausible Eingaben werden abgelehnt (:func:`fit_marks` wirft
:class:`MarkError` mit deutscher Meldung): Marken näher als :data:`MIN_SPAN_MM`
beieinander, ein Ist-Abstand, der mehr als :data:`MAX_SCALE_DEVIATION` vom
Soll-Abstand abweicht (falscher Punkt angetippt), nicht endliche Zahlen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from .model import Geometry
from .workarea import Rect, is_inside_work_area

Point = tuple[float, float]

#: Mindestabstand der beiden Soll- bzw. Ist-Punkte (darunter ist die Drehung zu ungenau).
MIN_SPAN_MM = 5.0
#: Größte erlaubte Abweichung Ist-Abstand / Soll-Abstand (0.1 = ±10 %).
MAX_SCALE_DEVIATION = 0.1
#: Ab dieser Abweichung je Marke (starr) weist die Meldung darauf hin.
WARN_ERROR_MM = 0.5


class MarkError(ValueError):
    """Passmarken passen nicht zusammen (Text für die Statusleiste)."""


@dataclass(frozen=True)
class MarkFit:
    """Bewegung Soll → Ist: um ``pivot`` skalieren und drehen, dann ``pivot`` → ``target``.

    ``angle_deg`` dreht wie :func:`model.rotate_point` (positiv = im Uhrzeigersinn
    auf dem Bildschirm). ``ratio`` ist Ist-Abstand / Soll-Abstand (1 bei einem Paar),
    ``scale`` der angewandte Faktor (1 = maßhaltig). ``error_mm`` ist die größte
    verbleibende Abweichung einer Marke nach der Bewegung.
    """

    pivot: Point
    target: Point
    angle_deg: float = 0.0
    scale: float = 1.0
    ratio: float = 1.0
    error_mm: float = 0.0
    pairs: int = 1

    @property
    def dx(self) -> float:
        return self.target[0] - self.pivot[0]

    @property
    def dy(self) -> float:
        return self.target[1] - self.pivot[1]

    @property
    def is_identity(self) -> bool:
        return (abs(self.dx) < 1e-9 and abs(self.dy) < 1e-9 and abs(self.angle_deg) < 1e-9
                and abs(self.scale - 1.0) < 1e-12)

    def map_point(self, p: Point) -> Point:
        """Punkt bewegen (für Vorschau und Tests)."""
        px, py = self.pivot
        r = math.radians(self.angle_deg)
        c, s = math.cos(r), math.sin(r)
        dx, dy = (p[0] - px) * self.scale, (p[1] - py) * self.scale
        return (self.target[0] + dx * c - dy * s, self.target[1] + dx * s + dy * c)

    def map_geometry(self, g: Geometry) -> Geometry:
        """Geometrie bewegen: gleichmäßig skalieren und drehen um ``pivot``, verschieben."""
        px, py = self.pivot
        out = g.copy()
        if abs(self.scale - 1.0) > 1e-12:
            out = out.mapped(Rect(px, py, 1.0, 1.0), Rect(px, py, self.scale, self.scale))
        if self.angle_deg:
            out = out.rotated(self.angle_deg, px, py)
        return out.translated(self.dx, self.dy)


def _finite(points: Iterable[Point]) -> bool:
    return all(math.isfinite(float(c)) for p in points for c in p)


def _angle(v: Point) -> float:
    return math.degrees(math.atan2(v[1], v[0]))


def _norm(a: float) -> float:
    a = math.fmod(a, 360.0)
    if a <= -180.0:
        a += 360.0
    elif a > 180.0:
        a -= 360.0
    return 0.0 if abs(a) < 1e-9 else a


def fit_marks(soll: Sequence[Point], ist: Sequence[Point], scale: bool = False) -> MarkFit:
    """Bewegung aus einem oder zwei Passmarken-Paaren (``soll[i]`` gehört zu ``ist[i]``)."""
    n = min(len(soll), len(ist))
    if n < 1:
        raise MarkError("Passmarken: mindestens ein Soll- und ein Ist-Punkt nötig")
    soll = [tuple(map(float, p)) for p in soll[:2]]
    ist = [tuple(map(float, p)) for p in ist[:2]]
    if len(soll) != len(ist):
        n = min(len(soll), len(ist))
        soll, ist = soll[:n], ist[:n]
    if not _finite(soll + ist):
        raise MarkError("Passmarken: ungültige Koordinate")
    if n == 1:
        return MarkFit(pivot=soll[0], target=ist[0], pairs=1)
    (a1, a2), (b1, b2) = soll, ist
    va = (a2[0] - a1[0], a2[1] - a1[1])
    vb = (b2[0] - b1[0], b2[1] - b1[1])
    la, lb = math.hypot(*va), math.hypot(*vb)
    if la < MIN_SPAN_MM:
        raise MarkError(f"Passmarken: die Soll-Punkte liegen zu dicht beieinander "
                        f"({la:.1f} mm, mindestens {MIN_SPAN_MM:.0f} mm – Marken weit auseinander wählen)")
    if lb < MIN_SPAN_MM:
        raise MarkError(f"Passmarken: die Ist-Punkte liegen zu dicht beieinander "
                        f"({lb:.1f} mm, mindestens {MIN_SPAN_MM:.0f} mm)")
    ratio = lb / la
    if abs(ratio - 1.0) > MAX_SCALE_DEVIATION:
        raise MarkError(f"Passmarken: der Ist-Abstand ({lb:.1f} mm) weicht um "
                        f"{(ratio - 1.0) * 100:+.1f} % vom Soll-Abstand ({la:.1f} mm) ab – "
                        "falsche Marke angetippt oder Punkte vertauscht?")
    pivot = ((a1[0] + a2[0]) / 2, (a1[1] + a2[1]) / 2)
    target = ((b1[0] + b2[0]) / 2, (b1[1] + b2[1]) / 2)
    angle = _norm(_angle(vb) - _angle(va))
    s = ratio if scale else 1.0
    error = 0.0 if scale else abs(lb - la) / 2
    return MarkFit(pivot=pivot, target=target, angle_deg=angle, scale=s, ratio=ratio,
                   error_mm=error, pairs=2)


def map_geometries(geoms: dict[str, Geometry], fit: MarkFit) -> dict[str, Geometry]:
    """Alle Geometrien bewegen (gemeinsam, ohne in die Fläche zu schieben)."""
    return {k: fit.map_geometry(g) for k, g in geoms.items()}


def bounds_of(geoms: Iterable[Geometry]) -> Rect | None:
    r: Rect | None = None
    for g in geoms:
        b = g.bounds()
        r = b if r is None else r.united(b)
    return r


def inside_work_area(geoms: Iterable[Geometry]) -> bool:
    """Liegt alles nach der Bewegung in der Arbeitsfläche?"""
    r = bounds_of(geoms)
    return r is None or is_inside_work_area(r, eps=1e-3)


def summary(fit: MarkFit) -> str:
    """Kurztext der Bewegung für Statusleiste / Dialog (Anzeige-Richtung: X nach links)."""
    from .workarea import screen_to_user
    u0, v0 = screen_to_user(*fit.pivot)
    u1, v1 = screen_to_user(*fit.target)
    parts = [f"ΔX {u1 - u0:+.2f} mm, ΔY {v1 - v0:+.2f} mm"]
    if fit.pairs == 2:
        # Anzeige: gegen den Uhrzeigersinn positiv wie „Messen“
        parts.append(f"gedreht {-fit.angle_deg:+.2f}°")
        if fit.scale != 1.0:
            parts.append(f"Maßstab {fit.scale * 100:.2f} %")
        else:
            parts.append(f"Abstand Ist/Soll {fit.ratio * 100:.2f} %, Abweichung je Marke "
                         f"{fit.error_mm:.2f} mm")
    return ", ".join(parts)


__all__ = ["MAX_SCALE_DEVIATION", "MIN_SPAN_MM", "MarkError", "MarkFit", "WARN_ERROR_MM",
           "bounds_of", "fit_marks", "inside_work_area", "map_geometries", "summary"]
