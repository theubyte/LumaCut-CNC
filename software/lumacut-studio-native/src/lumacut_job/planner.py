"""Cut planner: inner shapes first, reduced travel, best start point.

Mirrors LightBurn's Cut Planner defaults ("Cut inner shapes first",
"Reduce travel moves", "Choose best starting point", "Choose best
direction") for one layer at a time; layer order (bottom layer first) is
left unchanged. The project's „Optimierung…“ settings
(:class:`lumacut_canvas.model.CutOrder`, carried in ``JobLayer.cut_order``)
switch each of them off, add "Choose corners, if possible" and "Cut in
direction order", or turn the re-ordering off entirely (drawing order).

Fill blocks (``JobLayer.fills``, one per object / group / layer) are put
in nearest-neighbour order too when ``reduce_travel`` is on (the default),
starting where the head is when the layer begins; hatch blocks may run
backwards, offset blocks (``fill_fixed_order``) always run forwards so
their ring order is kept. A deterministic 2-opt / Or-opt pass
(``improve_fill_block_order``, bounded work budget) then shortens the
nearest-neighbour tour; block entry follows the same rule the G-code writer
uses (enter at the nearer end – for hatch at the nearest of the four block
corners, ``JobLayer.fill_free_corner``), so the planned order is exactly
what pass 1 lasers. The contours then start from the end of the fill, because the G-code
lasers each pass fill first.

Scanning offset (:mod:`.scan_offset`): :func:`optimized_document_gcode`
applies the speed table – by default the process-wide active table – to the
hatch fills and the image rasters after planning; an inactive table changes
nothing.

Cancellation: the canvas fill preview plans in a background thread and passes
``should_stop`` (a callable) to :func:`optimize_layers`; it is polled between
blocks / shapes and :class:`PlanCancelled` is raised once it returns true.
Without it (send, save, estimate) nothing changes.

Polylines are in machine mm. A polyline is *closed* when its first and last
points coincide (rectangles, ellipses, polygons and text outlines are all
exported that way by ``job_layers``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

Point = tuple[float, float]
Poly = list[Point]

CLOSE_EPS = 0.01  # mm


class PlanCancelled(Exception):
    """Raised by the planner when ``should_stop()`` asks to give up (preview worker)."""


def _check(should_stop) -> None:
    if should_stop is not None and should_stop():
        raise PlanCancelled()


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


#: „Ecken bevorzugen“: ein Punkt gilt als Ecke ab dieser Richtungsänderung.
CORNER_MIN_TURN_DEG = 40.0
#: „In Richtung schneiden“: Mindesthöhe einer Zeile (mm); sonst die halbe Ausdehnung
#: der vordersten Kontur in Schnittrichtung.
DIRECTION_ROW_MM = 0.5
DIRECTIONS = ("top_bottom", "bottom_top", "left_right", "right_left")


def corner_indices(ring: Poly, min_turn_deg: float = CORNER_MIN_TURN_DEG) -> list[int]:
    """Indizes der Ecken eines Rings (ohne doppelten Endpunkt).

    Ecke = Richtungsänderung ≥ ``min_turn_deg`` zwischen dem vorigen und dem
    nächsten *verschiedenen* Punkt. Fein zerlegte Bögen (Kreise, runde Ecken)
    haben keine Ecken."""
    n = len(ring)
    if n < 3:
        return []
    out = []
    limit = math.radians(min_turn_deg)
    for i in range(n):
        p = ring[i]
        a = next((ring[(i - k) % n] for k in range(1, n) if math.dist(ring[(i - k) % n], p) > 1e-6),
                 None)
        b = next((ring[(i + k) % n] for k in range(1, n) if math.dist(ring[(i + k) % n], p) > 1e-6),
                 None)
        if a is None or b is None:
            continue
        ux, uy = p[0] - a[0], p[1] - a[1]
        vx, vy = b[0] - p[0], b[1] - p[1]
        turn = abs(math.atan2(ux * vy - uy * vx, ux * vx + uy * vy))
        if turn >= limit - 1e-9:
            out.append(i)
    return out


def _best_entry(poly: Poly, pos: Point, best_start: bool, best_direction: bool = True,
                corners: bool = False) -> tuple[float, Poly]:
    """Distance from ``pos`` and the polyline oriented/rotated for that entry.

    ``corners``: closed shapes start at the nearest corner
    (:func:`corner_indices`) when they have one, else at the nearest point.
    ``best_direction`` off: open paths keep their drawn direction."""
    if is_closed(poly):
        if not best_start:
            return math.dist(pos, poly[0]), poly
        ring = poly[:-1]
        cand = corner_indices(ring) if corners else []
        k = min(cand or range(len(ring)), key=lambda i: math.dist(pos, ring[i]))
        rotated = ring[k:] + ring[:k]
        return math.dist(pos, ring[k]), rotated + [rotated[0]]
    d0 = math.dist(pos, poly[0])
    d1 = math.dist(pos, poly[-1])
    if best_direction and d1 < d0:
        return d1, list(reversed(poly))
    return d0, poly


def _direction_span(poly: Poly, direction: str) -> tuple[float, float]:
    """Vorderkante und Hinterkante der Kontur in Schnittrichtung (kleiner = früher).

    Maschinen-mm: Y wächst nach unten (Bildschirm oben = kleines Y), X wächst
    nach links (Nullpunkt oben rechts, :mod:`lumacut_canvas.workarea`)."""
    x0, y0, x1, y1 = _bbox(poly)
    if direction == "top_bottom":
        return y0, y1
    if direction == "bottom_top":
        return -y1, -y0
    if direction == "left_right":
        return -x1, -x0
    return x0, x1   # right_left


def order_polylines(polys: list[Poly], start: Point = (30.0, 30.0), inside_first: bool = True,
                    reduce_travel: bool = True, best_start: bool = True,
                    should_stop=None, best_direction: bool = True, corners: bool = False,
                    direction: str = "") -> list[Poly]:
    """Return the polylines in cutting order (each possibly reversed/rotated).

    Greedy nearest-neighbour over the shapes that are *ready*: with
    ``inside_first`` a closed shape becomes ready only after every shape it
    contains has been cut, so parts never drop out before their holes and
    engravings are done.

    ``direction`` (LightBurn „Cut in direction order“, one of
    :data:`DIRECTIONS`): among the ready shapes only the front *row* is
    eligible – shapes whose front edge lies within half the extent (at least
    :data:`DIRECTION_ROW_MM`) of the frontmost one; inside the row the
    nearest one (``reduce_travel``) or the frontmost one is cut next.
    ``best_start`` / ``best_direction`` / ``corners`` choose the entry of the
    chosen shape whenever ``reduce_travel`` or ``direction`` is on;
    with neither, shapes keep their drawn start and direction.
    """
    polys = [list(p) for p in polys if len(p) >= 2]
    n = len(polys)
    if n == 0:
        return []
    if direction not in DIRECTIONS:
        direction = ""
    if not inside_first and not reduce_travel and not direction:
        return polys
    waiting: list[int] = [0] * n  # number of uncut children per shape
    parents_of = containment(polys) if inside_first else [set() for _ in polys]
    for parents in parents_of:
        for j in parents:
            waiting[j] += 1
    spans = [_direction_span(p, direction) for p in polys] if direction else []
    orient = reduce_travel or bool(direction)
    done = [False] * n
    out: list[Poly] = []
    pos = start

    def entry(i):
        return _best_entry(polys[i], pos, best_start, best_direction, corners)

    for _ in range(n):
        _check(should_stop)
        ready = [i for i in range(n) if not done[i] and waiting[i] == 0]
        if not ready:  # cyclic containment (degenerate geometry): fall back
            ready = [i for i in range(n) if not done[i]]
        if direction:
            front = min(ready, key=lambda i: (spans[i][0], i))
            f0, f1 = spans[front]
            limit = f0 + max(DIRECTION_ROW_MM, 0.5 * (f1 - f0))
            ready = [i for i in ready if spans[i][0] <= limit + 1e-9]
        if reduce_travel:
            best = min(ready, key=lambda i: entry(i)[0])
        elif direction:
            best = min(ready, key=lambda i: (spans[i][0], i))
        else:
            best = ready[0]
        oriented = entry(best)[1] if orient else polys[best]
        done[best] = True
        for j in parents_of[best]:
            waiting[j] -= 1
        out.append(oriented)
        pos = oriented[-1]
    return out


def _entries(blocks, reversible: bool, corners: bool):
    from lumacut_canvas.hatch import fill_block_entries
    return [fill_block_entries(b, reversible, corners) for b in blocks]


def _apply_variant(block, variant):
    from lumacut_canvas.hatch import fill_block_variant
    return fill_block_variant(block, variant)


def order_fill_blocks_nearest(blocks, start: Point, reversible: bool = True,
                              corners: bool = False, should_stop=None):
    """Fill blocks in greedy nearest-neighbour order (each possibly reversed).

    A reversed block runs its segments in reverse order and direction (like
    ``lumacut_canvas.gcode.order_fill_blocks``); with ``reversible=False``
    every block keeps its internal order and is entered at its first point.
    ``corners`` (hatch, ``JobLayer.fill_free_corner``) also allows the other
    two corners of a block (rows in reverse order, or every row flipped –
    ``lumacut_canvas.hatch.fill_block_entries``).
    Ties keep the object order, so a single block or blocks that are already
    in the best order stay unchanged.
    """
    todo = [b for b in blocks if b]
    opts = _entries(todo, reversible, corners)
    out = []
    pos = start
    while todo:
        _check(should_stop)
        best_i, best_d, best_v = 0, math.inf, 0
        for i, entries in enumerate(opts):
            for entry, _exit, v in entries:
                d = math.dist(pos, entry)
                if d < best_d:
                    best_i, best_d, best_v = i, d, v
        block = _apply_variant(todo.pop(best_i), best_v)
        opts.pop(best_i)
        out.append(block)
        pos = block[-1][1]
    return out


FILL_OPT_BUDGET = 1_000_000   # block steps evaluated per layer (deterministic work cap)
FILL_OPT_NEIGHBOURS = 8       # candidate moves only towards the k nearest blocks
FILL_OPT_MAX_BLOCKS = 2000    # above this the nearest-neighbour order is kept
_FILL_OPT_EPS = 1e-9


def _block_neighbours(opts, k: int) -> list[list[int]]:
    """For each block the ``k`` nearest other blocks (any exit of one to any entry of the other)."""
    import numpy as np
    n = len(opts)
    width = max(len(o) for o in opts)
    # pad every block to the same number of entry/exit options (repeat the first)
    ent = np.array([[o[min(v, len(o) - 1)][0] for v in range(width)] for o in opts], float)
    ext = np.array([[o[min(v, len(o) - 1)][1] for v in range(width)] for o in opts], float)
    dist = None
    for vi in range(width):
        e = ext[:, vi]
        for vj in range(width):
            s = ent[:, vj]
            d = np.hypot(e[:, None, 0] - s[None, :, 0], e[:, None, 1] - s[None, :, 1])
            dist = d if dist is None else np.minimum(dist, d)
    np.fill_diagonal(dist, np.inf)
    k = min(k, n - 1)
    out = []
    for i in range(n):
        idx = np.argpartition(dist[i], k - 1)[:k] if k < n - 1 else np.arange(n)
        idx = [int(j) for j in idx if j != i]
        idx.sort(key=lambda j: (dist[i, j], j))   # stable, deterministic
        out.append(idx)
    return out


def improve_fill_block_order(blocks, start: Point, reversible: bool = True,
                             budget: int = FILL_OPT_BUDGET,
                             neighbours: int = FILL_OPT_NEIGHBOURS,
                             corners: bool = False, should_stop=None):
    """Shorten the travel of an ordered fill-block list with 2-opt and Or-opt moves.

    Works on top of :func:`order_fill_blocks_nearest`: blocks stay whole (fill
    grouping and the ring order inside an offset block are untouched), only
    their order changes. Each block is entered at its nearer end (``reversible``)
    exactly like ``lumacut_canvas.gcode.order_fill_blocks`` decides, so the
    G-code writer reproduces the planned tour; with ``reversible=False`` every
    block keeps its direction; with ``corners`` (hatch) a block is entered at
    the nearest of its four corners, again exactly like the writer. Moves: reverse a stretch of the tour (2-opt) and
    move a run of 1–3 blocks elsewhere, optionally reversed (Or-opt), each only
    towards the ``neighbours`` nearest blocks. The search is first-improvement
    in a fixed scan order and stops after ``budget`` evaluated block steps, so
    the result is deterministic and the runtime bounded; it is never longer
    than the input order.
    """
    blocks = [b for b in blocks if b]
    n = len(blocks)
    if n < 2 or n > FILL_OPT_MAX_BLOCKS or budget <= 0:
        return blocks
    opts = _entries(blocks, reversible, corners)
    dist = math.dist
    order = list(range(n))
    left = budget

    def enter(pos, k):
        """(travel, exit, variant) of block ``k`` entered from ``pos`` (writer rule)."""
        best_d, best_x, best_v = math.inf, pos, 0
        for entry, exit_, v in opts[k]:
            d = dist(pos, entry)
            if d < best_d:
                best_d, best_x, best_v = d, exit_, v
        return best_d, best_x, best_v

    def states(seq):
        pos, c, ps, cs, vs = start, 0.0, [], [], []
        for k in seq:
            d, pos, v = enter(pos, k)
            c += d
            vs.append(v)
            ps.append(pos)
            cs.append(c)
        return ps, cs, vs

    pos_after, cum, _ = states(order)

    def evaluate(cand, t0, t1):
        """Travel of ``cand`` (differs from ``order`` only in positions t0..t1)."""
        nonlocal left
        total = cum[-1]
        pos = start if t0 == 0 else pos_after[t0 - 1]
        c = 0.0 if t0 == 0 else cum[t0 - 1]
        for t in range(t0, n):
            left -= 1
            k = cand[t]
            d, pos, _ = enter(pos, k)
            c += d
            if c >= total - _FILL_OPT_EPS:
                return math.inf
            if t >= t1 and k == order[t] and pos == pos_after[t]:
                return c + total - cum[t]   # rest of the tour is unchanged
        return c

    near = _block_neighbours(opts, neighbours)
    improved = True
    while improved and left > 0:
        improved = False
        at = [0] * n
        for t, k in enumerate(order):
            at[k] = t
        for i in range(n):
            if left <= 0:
                break
            _check(should_stop)
            accepted = None
            # 2-opt: reverse order[i..j] so that a near neighbour of the
            # predecessor (or of order[i] itself at the tour start) comes next.
            anchor = order[i - 1] if i else order[i]
            for m in near[anchor]:
                j = at[m]
                if j <= i:
                    continue
                cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                if evaluate(cand, i, j) < cum[-1] - _FILL_OPT_EPS:
                    accepted = cand
                    break
                if left <= 0:
                    break
            # Or-opt: move order[i..i+L-1] (optionally reversed) behind a near
            # neighbour of its first block, or to the front of the tour.
            for length in (1, 2, 3):
                if accepted is not None or left <= 0 or i + length > n:
                    break
                seg = order[i:i + length]
                rest = order[:i] + order[i + length:]
                targets = [m for m in near[seg[0]] if m not in seg]
                for m in [None] + targets:
                    p = 0 if m is None else rest.index(m) + 1
                    if p == i:
                        continue
                    for piece in (seg, seg[::-1]) if length > 1 else (seg,):
                        cand = rest[:p] + piece + rest[p:]
                        lo = min(i, p)
                        hi = max(i + length, p + length) - 1
                        if evaluate(cand, lo, hi) < cum[-1] - _FILL_OPT_EPS:
                            accepted = cand
                            break
                    if accepted is not None or left <= 0:
                        break
            if accepted is not None:
                order = accepted
                pos_after, cum, _ = states(order)
                for t, k in enumerate(order):
                    at[k] = t
                improved = True
    _, _, variants = states(order)
    return [_apply_variant(blocks[k], v) for k, v in zip(order, variants)]


def fill_travel_length(blocks, start: Point) -> float:
    """Travel between fill segments (laser off), in the given order and direction."""
    total, pos = 0.0, start
    for block in blocks:
        for a, b in block:
            total += math.dist(pos, a)
            pos = b
    return total


def travel_length(polys: list[Poly], start: Point = (30.0, 30.0)) -> float:
    total, pos = 0.0, start
    for p in polys:
        total += math.dist(pos, p[0])
        pos = p[-1]
    return total


@dataclass
class PlanReport:
    """Was der Planer angepasst hat – für eine kurze Meldung in der UI."""

    skipped_leads: int = 0
    moved_leads: int = 0
    layers_with_skipped: list[str] = field(default_factory=list)
    scan_offset: str = ""   # kurze Beschreibung des angewandten Scan-Versatzes
    # Überlappende Linien (lumacut_job.overlap): entfernte Länge je Ebene und
    # Ebenen, auf denen die Option wegen Kerf/Stegen/An-/Abfahrt nicht wirkt.
    overlap_removed: dict = field(default_factory=dict)   # Ebenenname -> mm
    overlap_skipped: list[str] = field(default_factory=list)
    # Offene Pfade/Linien auf Füll-Ebenen (werden als Linie geschnitten, nicht gefüllt).
    open_on_fill: dict = field(default_factory=dict)      # Ebenenname -> Anzahl
    open_on_fill_joinable: int = 0
    # Manuelle Stege (Shape.tabs): gesetzt bzw. ohne passende Kontur weggelassen.
    manual_tabs: int = 0
    dropped_tabs: int = 0

    def overlap_message(self) -> str:
        parts = []
        if self.overlap_removed:
            total = sum(self.overlap_removed.values())
            where = ", ".join(self.overlap_removed)
            parts.append(f"Überlappende Linien entfernt: {total:.1f} mm".replace(".", ",")
                         + f" – Ebene {where}")
        if self.overlap_skipped:
            parts.append("Überlappungen nicht entfernt (Kerf / Stege / An-/Abfahrt / "
                         "Überschnitt aktiv) – Ebene " + ", ".join(self.overlap_skipped))
        return ". ".join(parts)

    def open_fill_message(self) -> str:
        if not self.open_on_fill:
            return ""
        n = sum(self.open_on_fill.values())
        where = ", ".join(self.open_on_fill)
        text = (f"Achtung: {n} offene Kontur{'en' if n != 1 else ''} auf Füll-Ebene {where} "
                "wird nur als Linie geschnitten, nicht gefüllt")
        if self.open_on_fill_joinable:
            text += f" ({self.open_on_fill_joinable} verbindbar)"
        return text + " – Pfad › „Pfade verbinden“ (Alt+J) oder „Pfade schließen“ (Alt+Shift+J)"

    def message(self) -> str:
        """Kurzer Hinweis (leer, wenn nichts zu melden ist)."""
        parts = []
        if self.skipped_leads:
            where = ", ".join(self.layers_with_skipped)
            n = self.skipped_leads
            parts.append(f"Anfahrt bei {n} Kontur{'en' if n != 1 else ''} weggelassen "
                         f"(kein Platz / Kollision mit anderen Teilen) – Ebene {where}")
        if self.dropped_tabs:
            n = self.dropped_tabs
            parts.append(f"{n} manuelle{'r' if n == 1 else ''} Steg{'e' if n != 1 else ''} "
                         "weggelassen (keine geschlossene Kontur in der Nähe oder Kontur zu kurz)")
        for extra in (self.open_fill_message(), self.overlap_message(), self.scan_offset):
            if extra:
                parts.append(extra)
        return ". ".join(parts)


def optimize_layers(layers, start: Point = (30.0, 30.0), report: PlanReport | None = None,
                    should_stop=None, **options):
    """Copy of ``JobLayer`` list with each layer's polylines reordered.

    The end position of one layer is the start position of the next.
    Per-layer cut options (kerf offset, tabs, lead-in/out, see
    :mod:`.cutpath`) are applied here: kerf before ordering, tabs and leads
    after ordering (they depend on the chosen start point). Leads are
    checked against the contours of *all* layers (no lead may cut into
    another part); what had to be dropped is counted in ``report``.
    The order options (``inside_first``, ``reduce_travel``, ``best_start``,
    ``best_direction``, ``corners``, ``direction``) come from each layer's
    ``cut_order`` (the project's „Optimierung…“ settings,
    :class:`lumacut_canvas.model.CutOrder`); keywords in ``options`` override them.
    ``should_stop``: optional callable polled during planning; raises
    :class:`PlanCancelled` when it returns true (background preview).
    Overlapping lines (``overlap_tol_mm`` > 0, :mod:`.overlap`) are removed
    after ordering – a later line loses what an earlier one already cut, so
    inside-first is kept; never on layers with kerf / tabs / leads / overcut
    (reported in ``report.overlap_skipped``), fills are never touched.
    """
    from .overlap import remove_overlaps
    from .cutpath import (CutOptions, LeadObstacles, apply_cut_options, nesting_depth,
                          offset_closed)
    prepared = []
    for layer in layers:
        opts = CutOptions.of(layer)
        polys = layer.polylines
        if opts.kerf_mm:
            polys, _ = offset_closed(polys, opts.kerf_mm)
        prepared.append((layer, opts, polys))
    obstacles = None
    if any(o.lead_in_mm > 0 or o.lead_out_mm > 0 for _, o, _ in prepared):
        obstacles = LeadObstacles([p for _, _, polys in prepared for p in polys])
    out = []
    pos = start
    for layer, opts, polys in prepared:
        _check(should_stop)
        order = getattr(layer, "cut_order", None)
        layer_options = {**(order.planner_options() if order is not None else {}), **options}
        fills = getattr(layer, "fills", None) or []
        reversible = not getattr(layer, "fill_fixed_order", False)
        corners = reversible and getattr(layer, "fill_free_corner", False)
        reorder = layer_options.get("reduce_travel", True)
        pass_fills = list(getattr(layer, "pass_fills", None) or [])
        if len(pass_fills) != int(layer.passes) or len(pass_fills) < 2:
            pass_fills = []
        if fills and reorder:
            fills = improve_fill_block_order(
                order_fill_blocks_nearest(fills, pos, reversible, corners, should_stop),
                pos, reversible, corners=corners, should_stop=should_stop)
            layer = replace(layer, fills=fills)
        if pass_fills:
            pass_fills[0] = fills
        if fills:
            pos = fills[-1][-1][1]   # contours follow the fill in every pass
        ordered = order_polylines(polys, pos, should_stop=should_stop, **layer_options)
        if opts.overlap_tol_mm > 0 and ordered:
            if opts.removes_overlaps:
                dedup = remove_overlaps(ordered, opts.overlap_tol_mm)
                ordered = dedup.polylines
                if report is not None and dedup.removed_mm > 0:
                    name = getattr(layer, "name", "?")
                    report.overlap_removed[name] = (report.overlap_removed.get(name, 0.0)
                                                    + dedup.removed_mm)
            elif report is not None:
                report.overlap_skipped.append(getattr(layer, "name", "?"))
        if opts.active and ordered:
            res = apply_cut_options(ordered, opts, nesting_depth(ordered), obstacles)
            if report is not None:
                report.moved_leads += res.moved_leads
                report.manual_tabs += res.manual_tabs
                report.dropped_tabs += res.dropped_tabs
                if res.skipped_leads:
                    report.skipped_leads += res.skipped_leads
                    report.layers_with_skipped.append(getattr(layer, "name", "?"))
            new = replace(layer, polylines=res.polylines, poly_kinds=tuple(res.kinds))
        else:
            new = replace(layer, polylines=ordered)
        if pass_fills:
            # Winkel-Schritt: jeder weitere Durchgang hat eigene Schraffurblöcke – jeweils
            # ab dem Ende des vorigen Durchgangs (Konturen bzw. dessen Füllung) ordnen.
            end = pos
            for p in range(1, len(pass_fills)):
                end = new.polylines[-1][-1] if new.polylines else end
                blocks = pass_fills[p]
                if blocks and reorder:
                    blocks = improve_fill_block_order(
                        order_fill_blocks_nearest(blocks, end, reversible, corners,
                                                  should_stop),
                        end, reversible, corners=corners, should_stop=should_stop)
                    pass_fills[p] = blocks
                if blocks:
                    end = blocks[-1][-1][1]
            new = replace(new, pass_fills=pass_fills)
            if not new.polylines:
                pos = end
        if new.polylines:
            pos = new.polylines[-1][-1]
        out.append(new)
    return out


def open_paths_on_fill_layers(doc, report: PlanReport | None = None) -> dict:
    """Offene Pfade/Linien auf sichtbaren Füll-Ebenen: ``{Ebenenname: Anzahl}``.

    Eine Füllung braucht geschlossene Formen – offene Pfade (DXF-Einzelstrecken,
    fast geschlossene Konturen) werden dort nur als Linie geschnitten
    (LightBurn warnt beim Start ebenso). Mit ``report`` werden Anzahl und die
    mit „Pfade verbinden“ schließbaren Konturen eingetragen.
    """
    from lumacut_canvas.pathjoin import is_open, join_preview
    out: dict = {}
    joinable = 0
    for layer in doc.layers:
        if not layer.visible or getattr(layer, "fill_mode", "none") == "none":
            continue
        shapes = [s for s in doc.shapes_in_layer(layer.id) if is_open(s)]
        if shapes:
            out[layer.name] = len(shapes)
            try:
                joinable += join_preview(shapes)[1]
            except Exception:   # Vorschau ist nur ein Zusatz zum Hinweis
                pass
    if report is not None:
        report.open_on_fill = dict(out)
        report.open_on_fill_joinable = joinable
    return out


_ACTIVE = object()


def optimized_document_gcode(doc, scan_offsets=_ACTIVE, **options) -> str:
    """Like ``lumacut_canvas.gcode.document_to_gcode`` but with the cut planner.

    Bildobjekte werden zuerst graviert (Raster/3D, unterste Ebene zuerst),
    danach folgen die Vektorebenen – Gravieren vor Schneiden, damit sich
    ausgeschnittene Teile nicht verschieben. Ohne Bilder ist die Ausgabe
    identisch mit der reinen Vektor-Planung.

    ``scan_offsets``: ``ScanOffsetTable`` für Schraffur und Bilder; Standard
    = die aktive Tabelle der App (:func:`.scan_offset.active_table`), ``None``
    = ohne Scan-Versatz.
    """
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import layers_to_gcode

    from .scan_offset import active_table, apply_to_layers
    table = active_table() if scan_offsets is _ACTIVE else scan_offsets
    if table is not None and not table.active:
        table = None
    layers = apply_to_layers(optimize_layers(job_layers(doc), **options), table)
    report = options.get("report")
    if report is not None:
        open_paths_on_fill_layers(doc, report)
    has_images = any(s.kind == "image" for s in doc.shapes)
    if report is not None and table is not None and (
            has_images or any(getattr(l, "fill_scan_offset_mm", 0.0) for l in layers)):
        report.scan_offset = table.summary()
    if not has_images:
        return layers_to_gcode(layers)
    from .images import document_image_jobs
    jobs = document_image_jobs(doc, table)
    # Füllung allein (Kontur aus) zählt auch als Vektor-Auftrag.
    has_vector = any(l.polylines or getattr(l, "fills", None) for l in layers)
    if not jobs and not has_vector:
        raise ValueError("Keine sichtbaren Objekte zum Lasern")
    if not has_vector:
        vector = ["; LUMACUT STUDIO NATIVE CANVAS JOB (homing, focus and park run on the Pi)",
                  "G21", "G90", "M5 I", "M3 I", "M5 I", "M400"]
    else:
        vector = layers_to_gcode(layers).strip().splitlines()
    out = vector[:5]
    for job in jobs:
        out += job.lines
    out += vector[5:]
    return "\n".join(out) + "\n"
