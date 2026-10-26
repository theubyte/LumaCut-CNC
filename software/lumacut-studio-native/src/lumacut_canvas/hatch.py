"""Schraffur (Vektor-Füllung) geschlossener Konturen – ohne Qt.

:func:`hatch_lines` legt parallele Linien im Abstand ``interval_mm`` unter
dem Winkel ``angle_deg`` (0° = waagerecht, gegen den Uhrzeigersinn auf dem
Bildschirm gemessen) über eine Menge geschlossener Polygone und schneidet sie
nach der **Gerade-Ungerade-Regel** zu: Löcher (z. B. in „O“, „A“ oder einem
Rahmen aus zwei Rechtecken) bleiben frei. :func:`fill_segments` setzt die
Ebenen-Einstellung um (``"hatch"`` = eine Richtung, ``"crosshatch"`` =
zusätzlich um 90° gedreht).

Die Linien liegen auf einem festen Raster ``(k + ½) · interval`` (in der
gedrehten Lage, gemessen vom Ursprung; der halbe Versatz vermeidet Linien
genau auf achsparallelen Kanten), damit benachbarte Objekte derselben Ebene
lückenlos ineinander übergehen. Ergebnis: Liste von Strecken
``((x0, y0), (x1, y1))`` in denselben Koordinaten wie die Eingabe, in
Fahr-Reihenfolge (bidirektional: jede zweite Rasterzeile rückwärts).

Laufzeit ~ O(Kanten + Schnittpunkte): jede Kante trägt sich nur in die
Rasterzeilen ein, die sie überspannt.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

Point = tuple[float, float]
Segment = tuple[Point, Point]

FILL_MODES = ("none", "hatch", "crosshatch")
FILL_LABELS = {"none": "Keine", "hatch": "Schraffur", "crosshatch": "Kreuzschraffur"}
INTERVAL_RANGE = (0.05, 20.0)   # mm
DEFAULT_INTERVAL_MM = 0.2
MAX_LINES_PER_PASS = 20000      # Schutz vor versehentlich winzigen Abständen
_MIN_SEG = 1e-6


def normalize_angle_180(deg: float) -> float:
    """Schraffurwinkel auf [0, 180) (180° ergibt dieselben Linien wie 0°)."""
    a = math.fmod(float(deg), 180.0)
    if a < 0:
        a += 180.0
    return 0.0 if abs(a - 180.0) < 1e-9 else round(a, 3)


def _rot(p: Point, c: float, s: float) -> Point:
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def hatch_lines(polygons: Iterable[Sequence[Point]], interval_mm: float, angle_deg: float = 0.0,
                bidirectional: bool = True) -> list[Segment]:
    """Schraffurstrecken innerhalb von ``polygons`` (Gerade-Ungerade-Regel).

    Polygone gelten als geschlossen (der letzte Punkt muss nicht wiederholt
    werden); Polygone mit weniger als drei Punkten werden ignoriert.
    """
    interval = float(interval_mm)
    if not interval > 0 or not math.isfinite(interval):
        raise ValueError("Linienabstand muss > 0 sein")
    # Linien unter +angle (Bildschirm, y nach unten) = in Weltkoordinaten
    # waagerecht, nachdem um +angle gedreht wurde; Rückdrehung um -angle.
    # Bildschirm-y zeigt nach unten, daher entspricht "gegen den Uhrzeigersinn
    # auf dem Bildschirm" einer Drehung um -angle in mathematischer Lage.
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)          # Welt -> gedreht (um +a)
    edges: list[tuple[float, float, float, float]] = []
    ymin = math.inf
    ymax = -math.inf
    for poly in polygons:
        pts = [_rot((float(x), float(y)), c, s) for x, y in poly]
        if len(pts) >= 2 and pts[0] == pts[-1]:
            pts.pop()
        if len(pts) < 3:
            continue
        for i, p in enumerate(pts):
            q = pts[i - 1]
            if p[1] == q[1]:
                continue  # waagerechte Kanten schneiden keine Rasterzeile sauber
            edges.append((q[0], q[1], p[0], p[1]))
            ymin = min(ymin, p[1], q[1])
            ymax = max(ymax, p[1], q[1])
    if not edges:
        return []
    k0 = math.ceil(ymin / interval - 0.5 - 1e-9)
    k1 = math.floor(ymax / interval - 0.5 + 1e-9)
    if k1 - k0 + 1 > MAX_LINES_PER_PASS:
        raise ValueError(f"Zu viele Schraffurlinien ({k1 - k0 + 1}); Linienabstand vergrößern")
    rows: dict[int, list[float]] = {}
    for x0, y0, x1, y1 in edges:
        lo, hi = (y0, y1) if y0 < y1 else (y1, y0)
        # halboffen [lo, hi): Ecken werden genau einmal gezählt
        ka = math.ceil(lo / interval - 0.5 - 1e-12)
        kb = math.ceil(hi / interval - 0.5 - 1e-12) - 1
        if kb < ka:
            continue
        inv = (x1 - x0) / (y1 - y0)
        for k in range(max(ka, k0), min(kb, k1) + 1):
            y = (k + 0.5) * interval
            if lo <= y < hi:
                rows.setdefault(k, []).append(x0 + (y - y0) * inv)
    ci, si = c, -s                           # gedreht -> Welt (um -a)
    out: list[Segment] = []
    forward = True
    for k in sorted(rows):
        xs = sorted(rows[k])
        y = (k + 0.5) * interval
        row: list[Segment] = []
        for i in range(0, len(xs) - 1, 2):
            xa, xb = xs[i], xs[i + 1]
            if xb - xa > _MIN_SEG:
                row.append((_rot((xa, y), ci, si), _rot((xb, y), ci, si)))
        if not row:
            continue
        if not forward:
            row = [(b, a) for a, b in reversed(row)]
        out.extend(row)
        if bidirectional:
            forward = not forward
    return out


def fill_segments(polygons: Sequence[Sequence[Point]], mode: str, interval_mm: float,
                  angle_deg: float = 0.0, bidirectional: bool = True) -> list[Segment]:
    """Schraffur nach Füllmodus (``none`` / ``hatch`` / ``crosshatch``)."""
    if mode not in FILL_MODES:
        raise ValueError(f"Unbekannter Füllmodus: {mode}")
    if mode == "none":
        return []
    segs = hatch_lines(polygons, interval_mm, angle_deg, bidirectional)
    if mode == "crosshatch":
        segs += hatch_lines(polygons, interval_mm, angle_deg + 90.0, bidirectional)
    return segs


def segments_length(segs: Iterable[Segment]) -> float:
    return sum(math.dist(a, b) for a, b in segs)
