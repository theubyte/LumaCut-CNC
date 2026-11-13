"""Manueller Startpunkt je Objekt (LightBurn *Set Start Point*).

Ein Startpunkt ist ein Punkt auf dem Umriss einer geschlossenen Kontur des
Objekts (``Shape.start``, normiert auf die ungedrehte Objektbox wie die
manuellen Stege – Verschieben, Skalieren, Drehen, Duplizieren und Arrays
nehmen ihn mit). Die Kontur, auf der er liegt, beginnt beim Senden genau dort:

* :func:`rotate_ring_to` dreht den Ring so, dass er im (auf ihn projizierten)
  Punkt beginnt – gleiche Laufrichtung, ein Punkt mehr, wenn der Start mitten
  auf einer Kante liegt;
* der Export (:func:`lumacut_canvas.export.job_layers`) dreht die Kontur der
  Zeichnung, der Planer (:mod:`lumacut_job.planner`) nach dem Kerf-Versatz die
  versetzte Kontur (:func:`apply_start_points`) und lässt ihren Start dann in
  Ruhe – auch mit „Besten Startpunkt wählen“ / „Möglichst an Ecken beginnen“
  (ein gesetzter Startpunkt ist eine ausdrückliche Wahl, LightBurn überschreibt
  ihn mit der Optimierung). Die Reihenfolge der Konturen plant er weiter wie
  bisher; An-/Abfahrt, Überschnitt, Stege und Perforation beginnen an diesem
  Punkt (die An-/Abfahrt darf nur die Laufrichtung wechseln, den Punkt nicht
  verlegen).

Ein Objekt trägt höchstens einen Startpunkt (für die Kontur, auf der er
liegt; weitere Konturen – Löcher, Buchstaben – behalten den Start des Planers).
Offene Pfade und Linien bekommen keinen (sie beginnen an einem Ende).

Hier nur die Rechnung (Qt nur über :func:`shape_paths.shape_polygons`); die
Bedienung (Werkzeug „Startpunkt“, Markierung, Menü) liegt in :mod:`startpoint_ui`.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Iterable

from .model import START_POINT_KINDS, Shape, tabs_from_world

Point = tuple[float, float]

#: Ein Startpunkt gehört zu einer Kontur höchstens so weit entfernt (mm, + |Kerf| beim Planen).
START_SNAP_MM = 1.5
#: Abstand (mm), unter dem der projizierte Punkt als vorhandener Knoten gilt.
NODE_EPS_MM = 1e-6


def closed_rings(shape: Shape) -> list[list[Point]]:
    """Geschlossene Ringe des Objekts in Arbeitsflächen-mm (Anfang = Ende)."""
    if shape is None or shape.kind not in START_POINT_KINDS:
        return []
    from .tabs import closed_rings as rings
    return rings(shape)


def can_have_start(shape: Shape) -> bool:
    return bool(closed_rings(shape))


def _project(p: Point, a: Point, b: Point) -> tuple[float, float, Point]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    ll = dx * dx + dy * dy
    t = 0.0 if ll <= 1e-18 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ll))
    q = (a[0] + dx * t, a[1] + dy * t)
    return math.dist(p, q), t, q


def nearest_on_ring(ring: list[Point], p: Point) -> tuple[float, int, Point]:
    """``(Abstand, Kantenindex, Punkt)`` des nächsten Punkts auf dem Ring (Anfang = Ende)."""
    best = (math.inf, -1, None)
    for i in range(len(ring) - 1):
        d, _t, q = _project(p, ring[i], ring[i + 1])
        if d < best[0]:
            best = (d, i, q)
    return best


def rotate_ring_to(ring: list[Point], p: Point) -> list[Point]:
    """Geschlossenen Ring (Anfang = Ende) so drehen, dass er am nächsten Punkt zu ``p`` beginnt.

    Laufrichtung bleibt; liegt der Punkt mitten auf einer Kante, wird er als
    Knoten eingefügt. Ein Ring, der schon dort beginnt, bleibt unverändert."""
    if len(ring) < 4:
        return list(ring)
    _d, i, q = nearest_on_ring(ring, p)
    if q is None:
        return list(ring)
    body = list(ring[:-1])
    n = len(body)
    if math.dist(q, body[i]) <= NODE_EPS_MM:
        k = i
    elif math.dist(q, ring[i + 1]) <= NODE_EPS_MM:
        k = (i + 1) % n
    else:
        out = [q] + body[i + 1:] + body[:i + 1]
        return out + [q]
    if k == 0:
        return list(ring)
    out = body[k:] + body[:k]
    return out + [out[0]]


def apply_start_points(polys: list[list[Point]], points: Iterable[Point], max_dist: float,
                       is_closed=None) -> tuple[list[list[Point]], list[Point], int]:
    """Startpunkte auf die jeweils nächste geschlossene Polylinie legen.

    Liefert ``(Polylinien, gesetzte Startpunkte, verworfen)``: jede geschlossene
    Polylinie, der ein Punkt (höchstens ``max_dist`` entfernt) gehört, beginnt
    danach an dessen Projektion (:func:`rotate_ring_to`); die gesetzten Punkte
    sind genau die neuen Anfangspunkte. Gehören mehrere Punkte zu einer Kontur,
    gilt der nächste. Verworfen = kein geschlossener Umriss in Reichweite.
    """
    pts = [(float(p[0]), float(p[1])) for p in points or ()]
    if not pts:
        return polys, [], 0
    if is_closed is None:
        def is_closed(poly):
            return len(poly) >= 4 and math.dist(poly[0], poly[-1]) <= 0.01
    closed = []
    for i, poly in enumerate(polys):
        if is_closed(poly):
            xs, ys = [q[0] for q in poly], [q[1] for q in poly]
            closed.append((i, (min(xs), min(ys), max(xs), max(ys))))
    chosen: dict[int, tuple[float, Point]] = {}
    dropped = 0
    for p in pts:
        best_i, best_d = None, max_dist
        for i, (x0, y0, x1, y1) in closed:
            if p[0] < x0 - best_d or p[0] > x1 + best_d or p[1] < y0 - best_d or p[1] > y1 + best_d:
                continue
            d = nearest_on_ring(polys[i], p)[0]
            if d <= best_d:
                best_i, best_d = i, d
        if best_i is None:
            dropped += 1
            continue
        if best_i not in chosen or best_d < chosen[best_i][0]:
            if best_i in chosen:
                dropped += 1
            chosen[best_i] = (best_d, p)
        else:
            dropped += 1
    if not chosen:
        return polys, [], dropped
    out = list(polys)
    placed = []
    for i, (_d, p) in chosen.items():
        ring = list(polys[i])
        if math.dist(ring[0], ring[-1]) > 0:
            ring[-1] = ring[0]          # fast geschlossen: exakt schließen
        out[i] = rotate_ring_to(ring, p)
        placed.append(out[i][0])
    return out, placed, dropped


def start_key(p: Point) -> tuple[float, float]:
    """Schlüssel für den Vergleich gesetzter Startpunkte mit Konturanfängen."""
    return (round(p[0], 6), round(p[1], 6))


# --- Objekt ----------------------------------------------------------------------

def with_start(shape: Shape, p: Point | None) -> Shape:
    """Kopie mit diesem Startpunkt (Arbeitsflächen-mm) bzw. ohne (``None``)."""
    start = tabs_from_world(shape.geom, [p])[0] if p is not None else ()
    return replace(shape, geom=shape.geom.copy(), start=start)


def nearest_outline(shape: Shape, p: Point) -> tuple[float, Point | None, int]:
    """``(Abstand, Punkt, Ring-Index)`` des nächsten Umrisspunkts des Objekts."""
    best = (math.inf, None, -1)
    for k, ring in enumerate(closed_rings(shape)):
        d, _i, q = nearest_on_ring(ring, p)
        if d < best[0]:
            best = (d, q, k)
    return best


def set_start(shape: Shape, p: Point, tol_mm: float) -> tuple[Shape | None, str]:
    """Startpunkt auf den nächsten Umrisspunkt zu ``p`` legen: ``(neue Form | None, Grund)``."""
    if shape is None or shape.kind not in START_POINT_KINDS:
        return None, "Nur geschlossene Konturen bekommen einen Startpunkt."
    d, q, _k = nearest_outline(shape, p)
    if q is None:
        return None, "Nur geschlossene Konturen bekommen einen Startpunkt."
    if d > tol_mm:
        return None, "Kein Umriss unter dem Zeiger – auf die Kontur tippen."
    return with_start(shape, q), ""


def clear_start(shape: Shape) -> Shape:
    return replace(shape, geom=shape.geom.copy(), start=())


def carry_start(new: Shape, p: Point | None, tol_mm: float = START_SNAP_MM) -> Shape:
    """Startpunkt (Arbeitsflächen-mm) auf ``new`` übertragen: liegt er höchstens
    ``tol_mm`` neben einer geschlossenen Kontur von ``new``, wird er auf sie
    gesetzt, sonst entfällt er (Knoten bearbeiten, Vereinfachen, Zerlegen …)."""
    if p is None:
        return new if not new.start else clear_start(new)
    d, q, _k = nearest_outline(new, p)
    if q is None or d > tol_mm:
        return clear_start(new) if new.start else new
    return with_start(new, q)


def start_direction(shape: Shape) -> Point | None:
    """Einheitsvektor der Laufrichtung am Startpunkt (Arbeitsflächen-mm), ``None`` ohne.

    Mit umgekehrter Laufrichtung (``Shape.reverse``, :mod:`direction`) zeigt er in
    die Gegenrichtung (zum vorigen Knoten)."""
    p = shape.start_point()
    if p is None:
        return None
    best = (math.inf, None)
    for ring in closed_rings(shape):
        r = rotate_ring_to(ring, p)
        if shape.reverse:
            r = r[::-1]
        d = math.dist(r[0], p)
        if d < best[0]:
            nxt = next((q for q in r[1:] if math.dist(q, r[0]) > 1e-9), None)
            if nxt is not None:
                ll = math.dist(r[0], nxt)
                best = (d, ((nxt[0] - r[0][0]) / ll, (nxt[1] - r[0][1]) / ll))
    return best[1]


def start_count(shapes: Iterable[Shape]) -> int:
    return sum(1 for s in shapes if s.start)


__all__ = ["START_SNAP_MM", "apply_start_points", "can_have_start", "carry_start", "clear_start",
           "closed_rings", "nearest_on_ring", "nearest_outline", "rotate_ring_to", "set_start",
           "start_count", "start_direction", "start_key", "with_start"]
