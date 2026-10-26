"""Knotenbearbeitung: reine Geometrie auf Polygonen und Pfaden.

Alle Funktionen nehmen ein :class:`Shape` und liefern eine geänderte Kopie mit
derselben ID (für :class:`~lumacut_canvas.edit_commands.ReplaceShapeCommand`).
Knotenpositionen sind Arbeitsflächen-mm *nach* der Drehung (so wie sie auf dem
Canvas zu sehen sind). Nach jeder Änderung wird die Objektbox neu um die Punkte
gelegt; die Drehung bleibt erhalten, ohne dass die übrigen Knoten springen.

Intern wird ein Objekt als Liste von Ringen bearbeitet, jeder Ring eine Liste
``[x, y, kurve]`` – ``kurve`` gilt für das Segment von diesem Knoten zum
nächsten (wie ``Shape.curves``).
"""

from __future__ import annotations

import math
from dataclasses import replace

from PySide6.QtCore import QPointF

from .model import POINT_KINDS, Geometry, Shape, clean_curves, clean_rings
from .shape_paths import curve_controls, geometry_transform

EDITABLE_KINDS = ("polygon", "path")
CONVERTIBLE_KINDS = ("rect", "ellipse", "line")
ELLIPSE_NODES = 8            # Ellipse → 8 Kurvenknoten (Abweichung < 0,5 %)
CURVE_SAMPLES = 24           # Abtastung eines Kurvensegments für Treffer/Einfügen


class NodeError(ValueError):
    """Bearbeitung nicht möglich (Text für die Statuszeile)."""


Ring = list[list]  # [[x, y, curve], ...]


def is_editable(shape: Shape | None) -> bool:
    return shape is not None and shape.kind in EDITABLE_KINDS and len(shape.points) >= 2


def is_closed(shape: Shape) -> bool:
    return shape.kind == "polygon"


# --- Umwandlung Shape <-> Ringe -------------------------------------------
def scene_points(shape: Shape) -> list[tuple[float, float]]:
    """Knoten in Arbeitsflächen-mm (gedreht, wie sichtbar)."""
    t = geometry_transform(shape.geom)
    out = []
    for x, y in shape.abs_points():
        p = t.map(QPointF(x, y))
        out.append((p.x(), p.y()))
    return out


def to_rings(shape: Shape) -> list[Ring]:
    pts = scene_points(shape)
    curves = set(shape.curves)
    return [[[*pts[i], i in curves] for i in range(a, b)] for a, b in shape.ring_ranges()]


def from_rings(shape: Shape, rings: list[Ring], kind: str | None = None) -> Shape:
    """Neue Kopie aus Ringen (Szenen-mm). Box neu, Drehung und Mitte der
    Drehung so gewählt, dass die Knoten genau an ihren Positionen liegen."""
    kind = kind or shape.kind
    closed = kind == "polygon"
    rings = [r for r in rings if r]
    pts, starts, curves = [], [], []
    for r in rings:
        if pts:
            starts.append(len(pts))
        n = len(r)
        for k, (x, y, c) in enumerate(r):
            # Offene Ringe: der letzte Knoten hat kein Folgesegment.
            if c and (closed or k < n - 1):
                curves.append(len(pts))
            pts.append((float(x), float(y)))
    if len(pts) < POINT_KINDS[kind]:
        raise NodeError(f"Zu wenige Knoten für {'ein Polygon' if closed else 'einen Pfad'}.")
    rot = shape.geom.rot
    t = geometry_transform(shape.geom)
    inv, _ = t.inverted()
    local = [inv.map(QPointF(x, y)) for x, y in pts]
    xs, ys = [p.x() for p in local], [p.y() for p in local]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    if rot:
        # Neue Boxmitte m (im alten lokalen Rahmen) liegt in der Szene bei M;
        # um M gedreht landen die Punkte L - m + M genau auf den alten Stellen.
        m = QPointF((x0 + x1) / 2, (y0 + y1) / 2)
        big_m = t.map(m)
        dx, dy = big_m.x() - m.x(), big_m.y() - m.y()
        x0, y0, x1, y1 = x0 + dx, y0 + dy, x1 + dx, y1 + dy
        local = [QPointF(p.x() + dx, p.y() + dy) for p in local]
    w, h = x1 - x0, y1 - y0
    norm = tuple(((p.x() - x0) / w if w > 0 else 0.0, (p.y() - y0) / h if h > 0 else 0.0) for p in local)
    return replace(shape, kind=kind, geom=Geometry(x0, y0, w, h, rot), points=norm,
                   rings=clean_rings(len(norm), starts), curves=clean_curves(len(norm), curves),
                   text="", image=None)


def locate(shape: Shape, index: int) -> tuple[int, int]:
    """(Ring, Position im Ring) für einen Knotenindex."""
    for r, (a, b) in enumerate(shape.ring_ranges()):
        if a <= index < b:
            return r, index - a
    raise NodeError("Knoten gibt es nicht.")


def flat_index(shape_rings: list[Ring], ring: int, k: int) -> int:
    return sum(len(r) for r in shape_rings[:ring]) + k


# --- Abtastung --------------------------------------------------------------
def _bezier(p0, c1, c2, p1, t: float) -> tuple[float, float]:
    u = 1.0 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (a * p0[0] + b * c1[0] + c * c2[0] + d * p1[0],
            a * p0[1] + b * c1[1] + c * c2[1] + d * p1[1])


def segment_count(ring: Ring, closed: bool) -> int:
    n = len(ring)
    return n if closed and n > 2 else n - 1


def segment_point(ring: Ring, k: int, closed: bool, t: float) -> tuple[float, float]:
    """Punkt bei Parameter ``t`` auf dem Segment k→k+1 (wie gezeichnet)."""
    n = len(ring)
    p1, p2 = ring[k][:2], ring[(k + 1) % n][:2]
    if not ring[k][2]:
        return p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t
    if closed:
        p0, p3 = ring[(k - 1) % n][:2], ring[(k + 2) % n][:2]
    else:
        p0 = ring[k - 1][:2] if k > 0 else p1
        p3 = ring[k + 2][:2] if k + 2 < n else p2
    c1, c2 = curve_controls(p0, p1, p2, p3)
    return _bezier(p1, c1, c2, p2, t)


def segment_samples(ring: Ring, k: int, closed: bool) -> list[tuple[float, float]]:
    steps = CURVE_SAMPLES if ring[k][2] else 1
    return [segment_point(ring, k, closed, i / steps) for i in range(steps + 1)]


def _dist_to_seg(p, a, b) -> tuple[float, tuple[float, float]]:
    vx, vy = b[0] - a[0], b[1] - a[1]
    ll = vx * vx + vy * vy
    t = 0.0 if ll <= 0 else max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / ll))
    q = (a[0] + vx * t, a[1] + vy * t)
    return math.hypot(p[0] - q[0], p[1] - q[1]), q


def node_at(shape: Shape, pos: tuple[float, float], tol_mm: float) -> int | None:
    """Nächster Knoten innerhalb ``tol_mm`` (Szenen-mm) oder None."""
    best, best_d = None, tol_mm
    for i, (x, y) in enumerate(scene_points(shape)):
        d = math.hypot(x - pos[0], y - pos[1])
        if d <= best_d:
            best, best_d = i, d
    return best


def segment_at(shape: Shape, pos: tuple[float, float], tol_mm: float) -> tuple[int, tuple[float, float]] | None:
    """(Segmentindex = Index des Startknotens, nächster Punkt auf dem
    Segment) innerhalb ``tol_mm`` oder None."""
    rings, closed = to_rings(shape), is_closed(shape)
    best, best_d = None, tol_mm
    for r, ring in enumerate(rings):
        for k in range(segment_count(ring, closed)):
            s = segment_samples(ring, k, closed)
            for a, b in zip(s, s[1:]):
                d, q = _dist_to_seg(pos, a, b)
                if d <= best_d:
                    best, best_d = (flat_index(rings, r, k), q), d
    return best


# --- Bearbeiten ---------------------------------------------------------------
def move_node(shape: Shape, index: int, pos: tuple[float, float]) -> Shape:
    rings = to_rings(shape)
    r, k = locate(shape, index)
    rings[r][k][0], rings[r][k][1] = float(pos[0]), float(pos[1])
    return from_rings(shape, rings)


def insert_node(shape: Shape, segment: int, pos: tuple[float, float] | None = None) -> tuple[Shape, int]:
    """Knoten im Segment ``segment`` einfügen (an ``pos`` oder in der Mitte).
    Ein Kurvensegment wird zu zwei Kurvensegmenten. Liefert (Objekt, neuer Index)."""
    rings, closed = to_rings(shape), is_closed(shape)
    r, k = locate(shape, segment)
    ring = rings[r]
    if k >= segment_count(ring, closed):
        if k == 0:
            raise NodeError("Kein Segment zum Einfügen.")
        k -= 1  # letzter Knoten eines offenen Pfads: davorliegendes Segment
    if pos is None:
        pos = segment_point(ring, k, closed, 0.5)
    ring.insert(k + 1, [float(pos[0]), float(pos[1]), ring[k][2]])
    return from_rings(shape, rings), flat_index(rings, r, k + 1)


def delete_node(shape: Shape, index: int) -> Shape:
    """Knoten löschen. Ein Ring, der zu klein würde, verschwindet ganz,
    solange noch ein anderer Ring übrig bleibt."""
    rings, closed = to_rings(shape), is_closed(shape)
    r, k = locate(shape, index)
    ring = rings[r]
    need = POINT_KINDS[shape.kind]
    if len(ring) - 1 < need:
        if len(rings) == 1:
            raise NodeError(f"Mindestens {need} Knoten nötig – ganzes Objekt mit „Löschen“ entfernen.")
        del rings[r]
        return from_rings(shape, rings)
    n = len(ring)
    prev = (k - 1) % n if closed else k - 1
    if prev >= 0 and (closed or k < n - 1):
        ring[prev][2] = ring[prev][2] or ring[k][2]  # zusammengelegtes Segment bleibt Kurve
    del ring[k]
    return from_rings(shape, rings)


def has_segment(shape: Shape, index: int) -> bool:
    rings = to_rings(shape)
    r, k = locate(shape, index)
    return k < segment_count(rings[r], is_closed(shape))


def toggle_curve(shape: Shape, segment: int) -> Shape:
    """Segment ab Knoten ``segment`` zwischen Gerade und Kurve umschalten."""
    if not has_segment(shape, segment):
        raise NodeError("Am Endknoten eines offenen Pfads beginnt kein Segment.")
    curves = set(shape.curves)
    curves ^= {segment}
    return replace(shape, curves=clean_curves(len(shape.points), curves))


def set_closed(shape: Shape, closed: bool, at: int | None = None) -> tuple[Shape, int | None]:
    """Pfad schließen (→ Polygon) oder öffnen (→ Pfad). Beim Öffnen mit
    ``at`` wird das Segment nach diesem Knoten aufgetrennt (der Ring beginnt
    danach beim folgenden Knoten), sonst das Schlusssegment. Liefert
    (Objekt, neuer Index des Knotens ``at``)."""
    if closed == is_closed(shape):
        return shape, at
    rings = to_rings(shape)
    if closed:
        if any(len(r) < POINT_KINDS["polygon"] for r in rings):
            raise NodeError("Zum Schließen braucht jeder Teilpfad mindestens 3 Knoten.")
        return from_rings(shape, rings, "polygon"), at
    new_at = at
    if at is not None:
        r, k = locate(shape, at)
        ring = rings[r]
        rings[r] = ring[k + 1:] + ring[:k + 1]
        new_at = flat_index(rings, r, len(ring) - 1)
    return from_rings(shape, rings, "path"), new_at


def to_editable(shape: Shape) -> Shape:
    """Rechteck, Ellipse, Linie → Polygon/Pfad mit gleicher Form und Drehung."""
    if is_editable(shape):
        return shape
    g = shape.geom
    if shape.kind == "line":
        b = g.local_bounds()
        x0, y0, x1, y1 = g.x, g.y, g.x + g.w, g.y + g.h
        pts = ((0.0 if b.w <= 0 else (x0 - b.x) / b.w, 0.0 if b.h <= 0 else (y0 - b.y) / b.h),
               (0.0 if b.w <= 0 else (x1 - b.x) / b.w, 0.0 if b.h <= 0 else (y1 - b.y) / b.h))
        return replace(shape, kind="path", geom=Geometry(b.x, b.y, b.w, b.h, g.rot), points=pts,
                       rings=(), curves=())
    if shape.kind == "rect":
        return replace(shape, kind="polygon", geom=g.copy(),
                       points=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)), rings=(), curves=())
    if shape.kind == "ellipse":
        n = ELLIPSE_NODES
        pts = tuple((0.5 + 0.5 * math.cos(2 * math.pi * i / n), 0.5 + 0.5 * math.sin(2 * math.pi * i / n))
                    for i in range(n))
        return replace(shape, kind="polygon", geom=g.copy(), points=pts, rings=(), curves=tuple(range(n)))
    raise NodeError("Text zuerst mit „In Pfade“ umwandeln." if shape.kind == "text"
                    else "Dieses Objekt hat keine Knoten.")
