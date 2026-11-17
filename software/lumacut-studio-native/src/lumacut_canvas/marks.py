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
* **Drei Paare** (Schalter „Passmarken: drei Marken“) gleichen aus: ohne
  „Maßstab angleichen“ die starre Bewegung mit der kleinsten Abweichung über
  alle drei Marken (Ausgleich nach kleinsten Quadraten, größte Rest-Abweichung in
  :attr:`MarkFit.error_mm`); mit „Maßstab angleichen“ zusätzlich **getrennte
  Maßstäbe in X und Y** des Designs (ein Drucker, der quer etwas anders druckt als
  längs – ein Fall, den zwei Marken nicht erkennen). Eine Scherung (schief
  eingezogenes Blatt) bleibt als Rest-Abweichung stehen und wird gemeldet –
  Formen bleiben formtreu wie beim Skalieren auf der Zeichenfläche.
* Gedrehte Objekte, Text, Bilder, Linien, Stege und Startpunkte gehen über die
  vorhandene Geometrie (:meth:`~model.Geometry.mapped` / ``rotated`` /
  ``translated``) mit – keine Scherung, kein neuer Projekt-Schlüssel.

Unplausible Eingaben werden abgelehnt (:func:`fit_marks` wirft
:class:`MarkError` mit deutscher Meldung): Marken näher als :data:`MIN_SPAN_MM`
beieinander, ein Ist-Abstand, der mehr als :data:`MAX_SCALE_DEVIATION` vom
Soll-Abstand abweicht (falscher Punkt angetippt), nicht endliche Zahlen.
"""

from __future__ import annotations

import dataclasses
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
#: Höchstzahl der Passmarken-Paare.
MAX_PAIRS = 3


class MarkError(ValueError):
    """Passmarken passen nicht zusammen (Text für die Statusleiste)."""


@dataclass(frozen=True)
class MarkFit:
    """Bewegung Soll → Ist: um ``pivot`` skalieren und drehen, dann ``pivot`` → ``target``.

    ``angle_deg`` dreht wie :func:`model.rotate_point` (positiv = im Uhrzeigersinn
    auf dem Bildschirm). ``ratio`` ist Ist-Abstand / Soll-Abstand (1 bei einem Paar),
    ``scale`` der angewandte Faktor (1 = maßhaltig). ``error_mm`` ist die größte
    verbleibende Abweichung einer Marke nach der Bewegung.

    ``scales`` (nur drei Paare mit „Maßstab angleichen“) sind getrennte Faktoren
    für X und Y des Designs (vor der Drehung); ``scale`` ist dann ihr Mittel.
    """

    pivot: Point
    target: Point
    angle_deg: float = 0.0
    scale: float = 1.0
    ratio: float = 1.0
    error_mm: float = 0.0
    pairs: int = 1
    scales: tuple[float, float] | None = None

    @property
    def scale_xy(self) -> tuple[float, float]:
        """Faktoren (X, Y) im Design vor der Drehung."""
        return self.scales if self.scales is not None else (self.scale, self.scale)

    @property
    def scaled(self) -> bool:
        sx, sy = self.scale_xy
        return abs(sx - 1.0) > 1e-12 or abs(sy - 1.0) > 1e-12

    @property
    def dx(self) -> float:
        return self.target[0] - self.pivot[0]

    @property
    def dy(self) -> float:
        return self.target[1] - self.pivot[1]

    @property
    def is_identity(self) -> bool:
        return (abs(self.dx) < 1e-9 and abs(self.dy) < 1e-9 and abs(self.angle_deg) < 1e-9
                and not self.scaled)

    def map_point(self, p: Point) -> Point:
        """Punkt bewegen (für Vorschau und Tests)."""
        px, py = self.pivot
        r = math.radians(self.angle_deg)
        c, s = math.cos(r), math.sin(r)
        sx, sy = self.scale_xy
        dx, dy = (p[0] - px) * sx, (p[1] - py) * sy
        return (self.target[0] + dx * c - dy * s, self.target[1] + dx * s + dy * c)

    def map_geometry(self, g: Geometry) -> Geometry:
        """Geometrie bewegen: skalieren und drehen um ``pivot``, verschieben.

        Getrennte X/Y-Faktoren gehen über :meth:`~model.Geometry.mapped` – ungedrehte
        Objekte exakt, gedrehte formtreu (ohne Scherung) wie beim Skalieren am Rahmen.
        """
        px, py = self.pivot
        out = g.copy()
        if self.scaled:
            sx, sy = self.scale_xy
            out = out.mapped(Rect(px, py, 1.0, 1.0), Rect(px, py, sx, sy))
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
    """Bewegung aus einem, zwei oder drei Passmarken-Paaren (``soll[i]`` gehört zu ``ist[i]``)."""
    n = min(len(soll), len(ist), MAX_PAIRS)
    if n < 1:
        raise MarkError("Passmarken: mindestens ein Soll- und ein Ist-Punkt nötig")
    soll = [tuple(map(float, p)) for p in soll[:n]]
    ist = [tuple(map(float, p)) for p in ist[:n]]
    if not _finite(soll + ist):
        raise MarkError("Passmarken: ungültige Koordinate")
    if n == 1:
        return MarkFit(pivot=soll[0], target=ist[0], pairs=1)
    if n == 3:
        return _fit_three(soll, ist, scale)
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


def _check_pair(a1: Point, a2: Point, b1: Point, b2: Point, names: str = "") -> float:
    """Abstände eines Markenpaars prüfen; gibt Ist / Soll zurück."""
    la, lb = math.dist(a1, a2), math.dist(b1, b2)
    tag = f" ({names})" if names else ""
    if la < MIN_SPAN_MM:
        raise MarkError(f"Passmarken: die Soll-Punkte{tag} liegen zu dicht beieinander "
                        f"({la:.1f} mm, mindestens {MIN_SPAN_MM:.0f} mm – Marken weit auseinander wählen)")
    if lb < MIN_SPAN_MM:
        raise MarkError(f"Passmarken: die Ist-Punkte{tag} liegen zu dicht beieinander "
                        f"({lb:.1f} mm, mindestens {MIN_SPAN_MM:.0f} mm)")
    ratio = lb / la
    if abs(ratio - 1.0) > MAX_SCALE_DEVIATION:
        raise MarkError(f"Passmarken: der Ist-Abstand{tag} ({lb:.1f} mm) weicht um "
                        f"{(ratio - 1.0) * 100:+.1f} % vom Soll-Abstand ({la:.1f} mm) ab – "
                        "falsche Marke angetippt oder Punkte vertauscht?")
    return ratio


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _centroid(pts: Sequence[Point]) -> Point:
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)


def _min_height(pts: Sequence[Point]) -> float:
    """Kleinste Höhe des Dreiecks (0 = alle auf einer Linie)."""
    area2 = abs(_cross(*pts))
    longest = max(math.dist(pts[i], pts[(i + 1) % 3]) for i in range(3))
    return area2 / longest if longest > 0 else 0.0


def _rotate(v: Point, deg: float) -> Point:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def _axis_scales(u: Sequence[Point], w: Sequence[Point], deg: float) -> tuple[float, float, float]:
    """Für Drehung ``deg``: beste X/Y-Faktoren und Fehlerquadratsumme."""
    back = [_rotate(q, -deg) for q in w]
    sxx = sum(p[0] * p[0] for p in u)
    syy = sum(p[1] * p[1] for p in u)
    sx = sum(p[0] * q[0] for p, q in zip(u, back)) / sxx if sxx > 1e-12 else 1.0
    sy = sum(p[1] * q[1] for p, q in zip(u, back)) / syy if syy > 1e-12 else 1.0
    err = sum((q[0] - p[0] * sx) ** 2 + (q[1] - p[1] * sy) ** 2 for p, q in zip(u, back))
    return sx, sy, err


def _fit_three(soll: list[Point], ist: list[Point], scale: bool) -> MarkFit:
    """Drei Paare: starrer Ausgleich (kleinste Quadrate) oder mit X/Y-Maßstab."""
    for i, j in ((0, 1), (0, 2), (1, 2)):
        _check_pair(soll[i], soll[j], ist[i], ist[j], f"Marke {i + 1} und {j + 1}")
    h_soll, h_ist = _min_height(soll), _min_height(ist)
    if h_soll >= MIN_SPAN_MM and h_ist >= MIN_SPAN_MM and _cross(*soll) * _cross(*ist) < 0:
        raise MarkError("Passmarken: die Ist-Marken liegen gespiegelt zu den Soll-Marken – "
                        "Reihenfolge der Marken vertauscht?")
    cs, ci = _centroid(soll), _centroid(ist)
    u = [(p[0] - cs[0], p[1] - cs[1]) for p in soll]
    w = [(p[0] - ci[0], p[1] - ci[1]) for p in ist]
    dot = sum(a[0] * b[0] + a[1] * b[1] for a, b in zip(u, w))
    crs = sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(u, w))
    angle = math.degrees(math.atan2(crs, dot))       # starrer Ausgleich (Procrustes)
    ratio = sum(math.hypot(*b) for b in w) / max(sum(math.hypot(*a) for a in u), 1e-12)
    scales = None
    if scale:
        xs, ys = [p[0] for p in soll], [p[1] for p in soll]
        if (h_soll < MIN_SPAN_MM or max(xs) - min(xs) < MIN_SPAN_MM
                or max(ys) - min(ys) < MIN_SPAN_MM):
            raise MarkError("Passmarken: für getrennte Maßstäbe in X und Y müssen die drei Marken "
                            "über Eck liegen (nicht auf einer Linie, z. B. drei Ecken des Bogens)")
        # Drehung mit der kleinsten Rest-Abweichung: grob ±15° um die starre Drehung, dann
        # Goldener Schnitt; die Maßstäbe liegen je Drehung geschlossen fest.
        err_at = lambda a: _axis_scales(u, w, a)[2]  # noqa: E731
        best = min((angle + 0.25 * k for k in range(-60, 61)), key=err_at)
        lo, hi = best - 0.25, best + 0.25
        g = (math.sqrt(5.0) - 1.0) / 2.0
        for _ in range(60):
            m1, m2 = hi - g * (hi - lo), lo + g * (hi - lo)
            if err_at(m1) <= err_at(m2):
                hi = m2
            else:
                lo = m1
        angle = (lo + hi) / 2.0
        sx, sy, _ = _axis_scales(u, w, angle)
        for name, f in (("X", sx), ("Y", sy)):
            if abs(f - 1.0) > MAX_SCALE_DEVIATION:
                raise MarkError(f"Passmarken: der Maßstab in {name} ({f * 100:.1f} %) weicht mehr als "
                                f"{MAX_SCALE_DEVIATION * 100:.0f} % ab – falsche Marke angetippt?")
        scales = (sx, sy)
    fit = MarkFit(pivot=cs, target=ci, angle_deg=_norm(angle),
                  scale=1.0 if scales is None else (scales[0] + scales[1]) / 2.0,
                  ratio=ratio, pairs=3, scales=scales)
    err = max(math.dist(fit.map_point(a), b) for a, b in zip(soll, ist))
    return dataclasses.replace(fit, error_mm=0.0 if err < 1e-9 else err)


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
    if fit.pairs == 3:
        parts.append(f"gedreht {-fit.angle_deg:+.2f}°")
        if fit.scales is not None:
            parts.append(f"Maßstab X {fit.scales[0] * 100:.2f} %, Y {fit.scales[1] * 100:.2f} %")
        else:
            parts.append(f"Abstände Ist/Soll {fit.ratio * 100:.2f} %")
        parts.append(f"größte Rest-Abweichung {fit.error_mm:.2f} mm (drei Marken ausgeglichen)")
    elif fit.pairs == 2:
        # Anzeige: gegen den Uhrzeigersinn positiv wie „Messen“
        parts.append(f"gedreht {-fit.angle_deg:+.2f}°")
        if fit.scale != 1.0:
            parts.append(f"Maßstab {fit.scale * 100:.2f} %")
        else:
            parts.append(f"Abstand Ist/Soll {fit.ratio * 100:.2f} %, Abweichung je Marke "
                         f"{fit.error_mm:.2f} mm")
    return ", ".join(parts)


__all__ = ["MAX_PAIRS", "MAX_SCALE_DEVIATION", "MIN_SPAN_MM", "MarkError", "MarkFit", "WARN_ERROR_MM",
           "bounds_of", "fit_marks", "inside_work_area", "map_geometries", "summary"]
