"""Eckenradius für Rechtecke (LightBurn *Shape Properties › Corner Radius*,
xTool Creative Space „Eckenradius“).

Ein Rechteck bleibt ein Rechteck mit der Eigenschaft ``Shape.corner_radius``
(mm): > 0 rundet alle vier Ecken ab, < 0 wölbt sie nach innen (Viertelkreis um
die Ecke, LightBurns „Biss“). Der Radius bleibt beim Skalieren in mm gleich –
das Rechteck wird mit dem gewünschten Radius neu aufgebaut, wie in LightBurn –
und wird beim Zeichnen auf die halbe kürzere Seite begrenzt. Die Box des
Objekts ist immer die Umrissbox (auch bei negativem Radius liegen Punkte auf
allen vier Kanten), darum bleiben Ausrichten, Raster, Park-Ecke und
Platzierung unverändert.

Qt-frei bis auf das Übertragen manueller Stege (über :mod:`tabs`, das für den
Umriss :mod:`shape_paths` nutzt).
"""

from __future__ import annotations

import math
from dataclasses import replace

from .model import Shape

# Eingabebereich des Felds (mm); das Rechteck begrenzt zusätzlich auf ±halbe kürzere Seite.
RADIUS_LIMIT_MM = 180.0
_EPS = 1e-9


def max_radius(shape: Shape) -> float:
    """Größter wirksamer Betrag des Radius: halbe kürzere Seite (mm)."""
    g = shape.geom
    return min(abs(g.w), abs(g.h)) / 2.0


def effective_radius(shape: Shape) -> float:
    """Wirksamer Radius (mm, mit Vorzeichen) – 0 für alles außer Rechtecken."""
    if shape.kind != "rect":
        return 0.0
    r = float(shape.corner_radius or 0.0)
    if not math.isfinite(r) or abs(r) < _EPS:
        return 0.0
    m = max_radius(shape)
    return max(-m, min(m, r))


def is_rounded(shape: Shape) -> bool:
    return effective_radius(shape) != 0.0


def clamp_radius(shape: Shape, r: float) -> float:
    """Eingabe ``r`` auf das Feld und die halbe kürzere Seite von ``shape`` begrenzen."""
    r = float(r) if math.isfinite(float(r)) else 0.0
    r = max(-RADIUS_LIMIT_MM, min(RADIUS_LIMIT_MM, r))
    m = max_radius(shape)
    r = max(-m, min(m, r))
    return 0.0 if abs(r) < 1e-6 else round(r, 6)


def with_corner_radius(shape: Shape, r: float) -> Shape:
    """Kopie von ``shape`` (Rechteck) mit Eckenradius ``r`` (begrenzt).

    Manuelle Stege bleiben am Umriss: jeder wird auf die neue Kontur gesetzt
    (an einer Ecke wandert er auf den Bogen)."""
    if shape.kind != "rect":
        raise ValueError("Eckenradius gibt es nur für Rechtecke")
    new = replace(shape, geom=shape.geom.copy(), corner_radius=clamp_radius(shape, r))
    if shape.tabs:
        from .tabs import carry_tabs
        delta = abs(effective_radius(new) - effective_radius(shape))
        new = carry_tabs(new, shape.tab_points(), tol_mm=1.5 + delta)
    return new


def corner_geometry(x: float, y: float, w: float, h: float, r: float):
    """Ecken eines Rechtecks (ungedreht, w, h > 0) mit Radius ``r`` (wirksam):
    Liste von (Eintritt, Austritt, Mittelpunkt) im Uhrzeigersinn ab oben rechts
    (Bildschirm-y nach unten), Start des Umrisses = Eintritt der ersten Ecke
    rückwärts gesehen = (x + |r|, y)."""
    a = abs(r)
    out = []
    for (cx, cy), (sx, sy), entry, exit_ in (
            ((x + w, y), (-1, 1), (x + w - a, y), (x + w, y + a)),
            ((x + w, y + h), (-1, -1), (x + w, y + h - a), (x + w - a, y + h)),
            ((x, y + h), (1, -1), (x + a, y + h), (x, y + h - a)),
            ((x, y), (1, 1), (x, y + a), (x + a, y))):
        centre = (cx + sx * a, cy + sy * a) if r > 0 else (cx, cy)
        out.append((entry, exit_, centre))
    return out


def arc_sweep(entry, exit_, centre) -> tuple[float, float]:
    """(Startwinkel, Überstreichung) in rad für den Viertelbogen entry → exit."""
    a0 = math.atan2(entry[1] - centre[1], entry[0] - centre[0])
    a1 = math.atan2(exit_[1] - centre[1], exit_[0] - centre[0])
    d = a1 - a0
    while d <= -math.pi:
        d += 2 * math.pi
    while d > math.pi:
        d -= 2 * math.pi
    return a0, d


def describe(shapes) -> str:
    """Statuszeile nach dem Ändern: wirksamer Radius, Hinweis bei Begrenzung."""
    shapes = list(shapes)
    if not shapes:
        return ""
    rs = sorted({round(effective_radius(s), 3) for s in shapes})
    if rs == [0.0]:
        text = "Eckenradius 0 – scharfe Ecken"
    elif len(rs) == 1:
        r = rs[0]
        text = (f"Eckenradius {r:g} mm – abgerundete Ecken" if r > 0
                else f"Eckenradius {r:g} mm – nach innen gewölbte Ecken")
    else:
        text = f"Eckenradius {rs[0]:g} … {rs[-1]:g} mm"
    if len(shapes) > 1:
        text += f" · {len(shapes)} Rechtecke"
    return text
