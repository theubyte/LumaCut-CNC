"""Centre-line trace for line art (LightBurn "Centerline" / Inkscape "Centerline tracing").

Instead of the outline of every stroke (two parallel contours that the laser
would burn twice), the stroke's centre line is returned as an open polyline,
which is what one wants for sketches, handwriting and technical drawings.

Pipeline (numpy + OpenCV only, no new dependency):

1. foreground mask from the same threshold / smoothing as the outline trace;
   specks smaller than ``min_area_mm2`` are dropped (connected components);
2. thinning to a one-pixel 8-connected skeleton: Zhang-Suen via 256-entry
   lookup tables (neighbour code from one ``filter2D``), followed by a
   checkerboard pass that removes the remaining "staircase" pixels while
   keeping the topology (simple-point test);
3. skeleton graph: junction pixels (≥ 3 neighbours) are merged into clusters,
   the chains between clusters / end points become polylines, pure loops
   become closed polylines;
4. spurs (short branches ending in an end point) shorter than about the local
   stroke width are pruned, and chains meeting at a cluster with only two
   remaining branches are joined again;
5. Douglas-Peucker simplification (``tolerance_mm``, at least ½ pixel so the
   pixel staircase disappears).

Coordinates are image pixels with pixel centres at ``i + 0.5`` like the
outline trace. Runtime is bounded by the caller's deadline (checked once per
thinning iteration); filled areas are not line art and get refused when they
take too long.
"""

from __future__ import annotations

import time
from collections import defaultdict

import numpy as np

Line = list[tuple[float, float]]

# neighbour order P2..P9 (N, NE, E, SE, S, SW, W, NW) as (dy, dx) and bit weight
_NB = ((-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1))
_KERNEL = np.zeros((3, 3), np.float32)
for _bit, (_dy, _dx) in enumerate(_NB):
    _KERNEL[1 + _dy, 1 + _dx] = float(1 << _bit)


def _bits(code: int) -> list[int]:
    return [(code >> i) & 1 for i in range(8)]


def _zs_tables() -> tuple[np.ndarray, np.ndarray]:
    """Zhang-Suen deletion tables for sub-iteration 1 and 2."""
    t1 = np.zeros(256, np.uint8)
    t2 = np.zeros(256, np.uint8)
    for code in range(256):
        p = _bits(code)              # p[0]=P2 (N) … p[7]=P9 (NW)
        b = sum(p)
        a = sum(1 for i in range(8) if p[i] == 0 and p[(i + 1) % 8] == 1)
        if not (2 <= b <= 6 and a == 1):
            continue
        n, e, s, w = p[0], p[2], p[4], p[6]
        if n * e * s == 0 and e * s * w == 0:
            t1[code] = 1
        if n * e * w == 0 and n * s * w == 0:
            t2[code] = 1
    return t1, t2


def _components(cells: set[tuple[int, int]], eight: bool) -> list[set[tuple[int, int]]]:
    steps = _NB if eight else ((-1, 0), (0, 1), (1, 0), (0, -1))
    out, todo = [], set(cells)
    while todo:
        stack = [todo.pop()]
        comp = set(stack)
        while stack:
            y, x = stack.pop()
            for dy, dx in steps:
                q = (y + dy, x + dx)
                if q in todo:
                    todo.discard(q)
                    comp.add(q)
                    stack.append(q)
        out.append(comp)
    return out


def _simple_table() -> np.ndarray:
    """Pixels that can be deleted without changing the topology and that are
    not end points (≥ 2 neighbours): one 8-component of foreground neighbours
    and one 4-component of background touching the centre's 4-neighbours."""
    t = np.zeros(256, np.uint8)
    for code in range(256):
        p = _bits(code)
        if sum(p) < 2:
            continue
        fg = {_NB[i] for i in range(8) if p[i]}
        bg = {_NB[i] for i in range(8) if not p[i]}
        if len(_components(fg, eight=True)) != 1:
            continue
        four = {(-1, 0), (0, 1), (1, 0), (0, -1)}
        bg_comps = [c for c in _components(bg, eight=False) if c & four]
        if len(bg_comps) == 1:
            t[code] = 1
    return t


_ZS1, _ZS2 = _zs_tables()
_SIMPLE = _simple_table()


def _codes(img: np.ndarray) -> np.ndarray:
    import cv2
    return cv2.filter2D(img, cv2.CV_32F, _KERNEL, borderType=cv2.BORDER_CONSTANT).astype(np.uint8)


def thin(mask: np.ndarray, deadline: float | None = None) -> np.ndarray:
    """Binary mask (non-zero = foreground) → one-pixel skeleton (uint8 0/1)."""
    img = (np.asarray(mask) > 0).astype(np.uint8)
    if not img.any():
        return img
    # crop to the foreground (plus a 1 px zero border) – thinning is per iteration O(area)
    ys, xs = np.nonzero(img)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    work = np.zeros((y1 - y0 + 2, x1 - x0 + 2), np.uint8)
    work[1:-1, 1:-1] = img[y0:y1, x0:x1]
    while True:
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError
        changed = False
        for table in (_ZS1, _ZS2):
            kill = (table[_codes(work)] & work).astype(bool)
            if kill.any():
                work[kill] = 0
                changed = True
        if not changed:
            break
    # staircase cleanup: pixels of one parity class are never 8-neighbours,
    # so deleting simple points of one class in parallel is safe
    yy, xx = np.mgrid[0:work.shape[0], 0:work.shape[1]]
    classes = [((yy % 2) == a) & ((xx % 2) == b) for a in (0, 1) for b in (0, 1)]
    for _ in range(4):
        changed = False
        for cls in classes:
            kill = (_SIMPLE[_codes(work)] & work).astype(bool) & cls
            if kill.any():
                work[kill] = 0
                changed = True
        if not changed:
            break
    out = np.zeros_like(img)
    out[y0:y1, x0:x1] = work[1:-1, 1:-1]
    return out


def _dp(line: Line, eps: float, closed: bool) -> Line:
    import cv2
    if len(line) <= 2 or eps <= 0:
        return line
    arr = np.asarray(line[:-1] if closed else line, np.float32).reshape(-1, 1, 2)
    if closed and len(arr) < 3:
        return line
    out = [tuple(map(float, p)) for p in cv2.approxPolyDP(arr, eps, closed)[:, 0, :]]
    if closed:
        if len(out) < 3:
            return []
        out.append(out[0])
    return out


def skeleton_lines(skel: np.ndarray, dist: np.ndarray | None = None) -> list[tuple[Line, bool]]:
    """Skeleton → ``(polyline, closed)`` in pixel-centre coordinates (x, y).

    ``dist`` (distance to the background per pixel) sets the spur length that
    is pruned at junctions; without it only one-pixel spurs are removed.
    """
    import cv2
    sk = (np.asarray(skel) > 0).astype(np.uint8)
    h, w = sk.shape
    pad = np.zeros((h + 2, w + 2), np.uint8)
    pad[1:-1, 1:-1] = sk
    deg = cv2.filter2D(pad, cv2.CV_16S, np.ones((3, 3), np.float32),
                       borderType=cv2.BORDER_CONSTANT).astype(np.int16) - pad
    deg = np.where(pad > 0, deg, 0)
    junction = ((deg >= 3) & (pad > 0)).astype(np.uint8)
    n_lab, labels = cv2.connectedComponents(junction, connectivity=8)
    # node id of every non-chain pixel: clusters 1..n-1, end points / dots get own ids
    node = np.zeros(pad.shape, np.int64)
    node[junction > 0] = labels[junction > 0]
    centre: dict[int, tuple[float, float]] = {}
    jy, jx = np.nonzero(junction)
    if len(jy):
        lab = labels[jy, jx]
        cnt = np.bincount(lab, minlength=n_lab)
        sx = np.bincount(lab, weights=jx, minlength=n_lab)
        sy = np.bincount(lab, weights=jy, minlength=n_lab)
        for k in range(1, n_lab):
            centre[k] = (sx[k] / cnt[k] - 0.5, sy[k] / cnt[k] - 0.5)
    next_id = n_lab
    ends = np.argwhere((deg <= 1) & (pad > 0))
    for yv, xv in ends:
        node[yv, xv] = next_id
        centre[next_id] = (float(xv) - 0.5, float(yv) - 0.5)
        next_id += 1
    is_end = set(range(n_lab, next_id))

    def nbrs(y: int, x: int):
        for dy, dx in _NB:
            if pad[y + dy, x + dx]:
                yield y + dy, x + dx

    def pt(y: int, x: int) -> tuple[float, float]:
        return float(x) - 0.5, float(y) - 0.5     # padded index → pixel centre

    visited = np.zeros(pad.shape, bool)           # chain (degree-2) pixels
    used_pairs: set[tuple[int, int, int, int]] = set()
    edges: list[list] = []                        # [a, b, points]
    node_pixels = np.argwhere(node > 0)
    for yv, xv in node_pixels:
        a = int(node[yv, xv])
        for ny, nx in nbrs(yv, xv):
            b0 = int(node[ny, nx])
            if b0 == a:
                continue
            if b0 > 0:                            # node directly next to node
                key = (min(a, b0), max(a, b0), 0, 0)
                if key in used_pairs:
                    continue
                used_pairs.add(key)
                edges.append([a, b0, [centre[a], centre[b0]]])
                continue
            if visited[ny, nx]:
                continue
            pts = [centre[a], pt(ny, nx)]
            visited[ny, nx] = True
            py, px, cy, cx = yv, xv, ny, nx
            end = None
            while True:
                nxt = None
                for qy, qx in nbrs(cy, cx):
                    if (qy, qx) == (py, px):
                        continue
                    q = int(node[qy, qx])
                    # a pixel of the start cluster right at the start is not an end
                    if q > 0 and (q != a or len(pts) > 2):
                        end = q
                        break
                    if node[qy, qx] == 0 and not visited[qy, qx]:
                        nxt = (qy, qx)
                if end is not None:
                    break
                if nxt is None:
                    break
                py, px, cy, cx = cy, cx, *nxt
                visited[cy, cx] = True
                pts.append(pt(cy, cx))
            if end is None:
                continue                          # dead end inside a chain (should not happen)
            pts.append(centre[end])
            edges.append([a, end, pts])
    # pure loops (no node): every pixel has exactly two neighbours
    for yv, xv in np.argwhere((pad > 0) & (node == 0) & ~visited):
        if visited[yv, xv]:
            continue
        pts = [pt(yv, xv)]
        visited[yv, xv] = True
        cy, cx = yv, xv
        while True:
            nxt = next(((qy, qx) for qy, qx in nbrs(cy, cx) if not visited[qy, qx]
                        and node[qy, qx] == 0), None)
            if nxt is None:
                break
            cy, cx = nxt
            visited[cy, cx] = True
            pts.append(pt(cy, cx))
        if len(pts) >= 3:
            pts.append(pts[0])
            edges.append([-1, -1, pts])

    def length(p: Line) -> float:
        return float(sum(np.hypot(p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1])
                         for i in range(len(p) - 1)))

    # prune spurs: junction ↔ end point, shorter than ~ the stroke width there
    def limit(cluster: int) -> float:
        if dist is None:
            return 1.5
        cx, cy = centre[cluster]
        r = float(dist[min(h - 1, max(0, int(cy))), min(w - 1, max(0, int(cx)))])
        return max(1.5, 1.5 * r)

    for _ in range(3):
        count = defaultdict(int)
        for a, b, _p in edges:
            if a >= 0:
                count[a] += 1
                count[b] += 1
        keep = []
        pruned = False
        for e in edges:
            a, b, p = e
            if a >= 0 and (a in is_end) != (b in is_end):
                j = b if a in is_end else a
                if count[j] >= 3 and length(p) < limit(j):
                    count[j] -= 1
                    pruned = True
                    continue
            keep.append(e)
        edges = keep
        if not pruned:
            break

    return _stitch(edges, centre, dist, h, w)


def _direction(p: Line, reach: float) -> tuple[float, float]:
    """Unit direction of polyline ``p`` leaving ``p[0]``, measured ``reach`` px away."""
    x0, y0 = p[0]
    far = p[-1]
    for q in p[1:]:
        if np.hypot(q[0] - x0, q[1] - y0) >= reach:
            far = q
            break
    dx, dy = far[0] - x0, far[1] - y0
    n = float(np.hypot(dx, dy)) or 1.0
    return dx / n, dy / n


STRAIGHT_COS = -0.85     # branches within ~32° of a straight continuation are joined


def _stitch(edges: list[list], centre: dict, dist, h: int, w: int) -> list[tuple[Line, bool]]:
    """Join chains through nodes: always where only two branches meet, and at
    crossings / T-junctions the pairs that continue (nearly) straight, so a
    crossing stroke stays one line instead of four pieces."""
    at = defaultdict(list)                      # node → [(edge, end)]
    for i, (a, b, _p) in enumerate(edges):
        if a >= 0:
            at[a].append((i, 0))
            at[b].append((i, 1))
    partner: dict[tuple[int, int], tuple[int, int]] = {}
    for n, lst in at.items():
        if len(lst) == 2:
            partner[lst[0]], partner[lst[1]] = lst[1], lst[0]
            continue
        if len(lst) < 2:
            continue
        cx, cy = centre[n]
        r = 1.0 if dist is None else float(dist[min(h - 1, max(0, int(cy))),
                                                 min(w - 1, max(0, int(cx)))])
        reach = max(3.0, 2.5 * r)
        dirs = {}
        for i, e in lst:
            p = edges[i][2]
            dirs[(i, e)] = _direction(p if e == 0 else p[::-1], reach)
        cand = sorted((dirs[u][0] * dirs[v][0] + dirs[u][1] * dirs[v][1], u, v)
                      for k, u in enumerate(lst) for v in lst[k + 1:])
        for c, u, v in cand:
            if c > STRAIGHT_COS:
                break
            if u in partner or v in partner or u[0] == v[0]:
                continue
            partner[u], partner[v] = v, u
    used = [False] * len(edges)
    out: list[tuple[Line, bool]] = []
    for i0, (a, _b, p) in enumerate(edges):
        if used[i0]:
            continue
        if a < 0:                                # pure loop
            used[i0] = True
            out.append((p, True))
            continue
        # walk backwards (through end 0) to the free start of the chain
        i, e = i0, 0
        cycle = False
        while (i, e) in partner:
            j, f = partner[(i, e)]
            if j == i0:
                cycle = True
                i, e = i0, 0
                break
            i, e = j, 1 - f
        start = (i, e)
        pts: Line = []
        closed = False
        while True:
            used[i] = True
            seg = edges[i][2] if e == 0 else edges[i][2][::-1]
            pts = seg if not pts else pts + seg[1:]
            nxt = partner.get((i, 1 - e))
            if nxt is None:
                break
            if used[nxt[0]]:
                closed = cycle and nxt == start
                break
            i, e = nxt
        if len(pts) >= 2:
            closed = closed and len(pts) > 3
            if closed and pts[0] != pts[-1]:
                pts = pts + [pts[0]]
            out.append((pts, closed))
    return out


def _is_tip(skel: np.ndarray, x: float, y: float) -> bool:
    """True if (x, y) is the centre of a skeleton pixel with exactly one neighbour."""
    cx, cy = x - 0.5, y - 0.5
    ix, iy = int(round(cx)), int(round(cy))
    if abs(cx - ix) > 1e-6 or abs(cy - iy) > 1e-6:
        return False                              # cluster centroid (junction)
    h, w = skel.shape
    if not (0 <= iy < h and 0 <= ix < w) or not skel[iy, ix]:
        return False
    win = skel[max(0, iy - 1):iy + 2, max(0, ix - 1):ix + 2]
    return int(win.sum()) - 1 == 1


def _extend_ends(pts: Line, skel: np.ndarray, fg: np.ndarray, dist: np.ndarray) -> Line:
    """Thinning eats about half a stroke width at free ends; continue each free
    end along its direction up to the stroke's edge so the laser line has the
    drawn length."""
    h, w = fg.shape
    out = list(pts)
    for at_start in (True, False):
        seq = out if at_start else out[::-1]
        x0, y0 = seq[0]
        if not _is_tip(skel, x0, y0):
            continue
        r = float(dist[int(y0 - 0.5), int(x0 - 0.5)])
        dx, dy = _direction(seq, max(3.0, 2.0 * r))
        if dx == 0 and dy == 0:
            continue
        best = None
        step = 0.5
        for k in range(1, int((3.0 * r + 3.0) / step) + 1):
            x, y = x0 - dx * step * k, y0 - dy * step * k
            ix, iy = int(np.floor(x)), int(np.floor(y))
            if not (0 <= iy < h and 0 <= ix < w) or not fg[iy, ix]:
                break
            best = (x, y)
        if best is None:
            continue
        # stop half a pixel inside the edge
        bx, by = best[0] + dx * 0.5 * step, best[1] + dy * 0.5 * step
        if at_start:
            out.insert(0, (float(bx), float(by)))
        else:
            out.append((float(bx), float(by)))
    return out


def trace_centerline(mask: np.ndarray, eps_px: float, min_area_px: float,
                     deadline: float | None) -> tuple[list[Line], int]:
    """Mask (uint8, 255 = stroke) → centre-line polylines and number of dropped specks."""
    import cv2
    fg = (mask > 0).astype(np.uint8)
    removed = 0
    n, labels, stats, _c = cv2.connectedComponentsWithStats(fg, connectivity=8)
    if n > 1 and min_area_px > 0:
        small = np.nonzero(stats[1:, cv2.CC_STAT_AREA] < min_area_px)[0] + 1
        if len(small):
            removed = int(len(small))
            fg[np.isin(labels, small)] = 0
    if not fg.any():
        return [], removed
    padded = cv2.copyMakeBorder(fg, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    dist = cv2.distanceTransform(padded, cv2.DIST_L2, 3)[1:-1, 1:-1]
    try:
        skel = thin(fg, deadline)
    except TimeoutError:
        raise ValueError("Mittellinie dauert zu lange – das Bild enthält große Flächen; für "
                         "Flächen „Kontur“ verwenden oder Schwellwert anpassen") from None
    lines: list[Line] = []
    eps = max(float(eps_px), 0.5)
    for pts, closed in skeleton_lines(skel, dist):
        if not closed:
            pts = _extend_ends(pts, skel, fg, dist)
        pts = _dp(pts, eps, closed)
        if len(pts) >= 2:
            lines.append(pts)
    return lines, removed


__all__ = ["thin", "skeleton_lines", "trace_centerline"]
