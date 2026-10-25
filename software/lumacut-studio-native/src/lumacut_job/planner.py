"""Cut planner: inner shapes first, reduced travel, best start point.

Mirrors LightBurn's Cut Planner defaults ("Cut inner shapes first",
"Reduce travel moves", "Choose best starting point") for one layer at a
time; layer order (bottom layer first) is left unchanged.

Polylines are in machine mm. A polyline is *closed* when its first and last
points coincide (rectangles, ellipses, polygons and text outlines are all
exported that way by ``job_layers``).
"""

from __future__ import annotations

import math
from dataclasses import replace

Point = tuple[float, float]
Poly = list[Point]

CLOSE_EPS = 0.01  # mm


def is_closed(poly: Poly) -> bool:
    return len(poly) >= 4 and math.dist(poly[0], poly[-1]) <= CLOSE_EPS


def _bbox(poly: Poly) -> tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def point_in_polygon(pt: Point, poly: Poly) -> bool:
    """Even-odd ray casting (poly closed or not)."""
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            xc = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xc:
                inside = not inside
        j = i
    return inside


def _contains(outer: Poly, obox, inner: Poly, ibox) -> bool:
    if not (obox[0] <= ibox[0] and obox[1] <= ibox[1]
            and obox[2] >= ibox[2] and obox[3] >= ibox[3]):
        return False
    if obox == ibox:
        return False  # identical boxes: treat as siblings (no forced order)
    # Majority vote of a few sample points is robust to shared vertices.
    step = max(1, len(inner) // 8)
    samples = inner[::step]
    hits = sum(point_in_polygon(p, outer) for p in samples)
    return hits * 2 > len(samples)


def containment(polys: list[Poly]) -> list[set[int]]:
    """For each polyline the indices of the *closed* polylines that contain it."""
    boxes = [_bbox(p) for p in polys]
    closed = [i for i, p in enumerate(polys) if is_closed(p)]
    parents: list[set[int]] = [set() for _ in polys]
    for i, p in enumerate(polys):
        for j in closed:
            if i != j and _contains(polys[j], boxes[j], p, boxes[i]):
                parents[i].add(j)
    return parents


def _best_entry(poly: Poly, pos: Point, best_start: bool) -> tuple[float, Poly]:
    """Distance from ``pos`` and the polyline oriented/rotated for that entry."""
    if is_closed(poly):
        if not best_start:
            return math.dist(pos, poly[0]), poly
        ring = poly[:-1]
        k = min(range(len(ring)), key=lambda i: math.dist(pos, ring[i]))
        rotated = ring[k:] + ring[:k]
        return math.dist(pos, ring[k]), rotated + [rotated[0]]
    d0 = math.dist(pos, poly[0])
    d1 = math.dist(pos, poly[-1])
    if d1 < d0:
        return d1, list(reversed(poly))
    return d0, poly


def order_polylines(polys: list[Poly], start: Point = (30.0, 30.0), inside_first: bool = True,
                    reduce_travel: bool = True, best_start: bool = True) -> list[Poly]:
    """Return the polylines in cutting order (each possibly reversed/rotated).

    Greedy nearest-neighbour over the shapes that are *ready*: with
    ``inside_first`` a closed shape becomes ready only after every shape it
    contains has been cut, so parts never drop out before their holes and
    engravings are done.
    """
    polys = [list(p) for p in polys if len(p) >= 2]
    n = len(polys)
    if n == 0:
        return []
    if not inside_first and not reduce_travel:
        return polys
    waiting: list[int] = [0] * n  # number of uncut children per shape
    parents_of = containment(polys) if inside_first else [set() for _ in polys]
    for parents in parents_of:
        for j in parents:
            waiting[j] += 1
    done = [False] * n
    out: list[Poly] = []
    pos = start
    for _ in range(n):
        ready = [i for i in range(n) if not done[i] and waiting[i] == 0]
        if not ready:  # cyclic containment (degenerate geometry): fall back
            ready = [i for i in range(n) if not done[i]]
        if reduce_travel:
            best = min(ready, key=lambda i: _best_entry(polys[i], pos, best_start)[0])
            _, oriented = _best_entry(polys[best], pos, best_start)
        else:
            best = ready[0]
            oriented = polys[best]
        done[best] = True
        for j in parents_of[best]:
            waiting[j] -= 1
        out.append(oriented)
        pos = oriented[-1]
    return out


def travel_length(polys: list[Poly], start: Point = (30.0, 30.0)) -> float:
    total, pos = 0.0, start
    for p in polys:
        total += math.dist(pos, p[0])
        pos = p[-1]
    return total


def optimize_layers(layers, start: Point = (30.0, 30.0), **options):
    """Copy of ``JobLayer`` list with each layer's polylines reordered.

    The end position of one layer is the start position of the next.
    """
    out = []
    pos = start
    for layer in layers:
        ordered = order_polylines(layer.polylines, pos, **options)
        if ordered:
            pos = ordered[-1][-1]
        out.append(replace(layer, polylines=ordered))
    return out


def optimized_document_gcode(doc, **options) -> str:
    """Like ``lumacut_canvas.gcode.document_to_gcode`` but with the cut planner."""
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import layers_to_gcode
    return layers_to_gcode(optimize_layers(job_layers(doc), **options))
