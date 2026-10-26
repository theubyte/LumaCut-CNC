"""Curve fitting for traced outlines and centre lines ("Glätten", like potrace / LightBurn).

Traced rings run along pixel edges and centre lines along pixel centres, so
both are polygons with a pixel staircase. This module turns them into smooth
curves while sharp corners stay sharp:

1. **corner detection** – at every vertex the turn angle is measured between
   the points ``CORNER_SCALE_PX`` of arc length behind and ahead (so single
   staircase steps do not count); vertices turning more than
   ``CORNER_ANGLE_DEG`` that are the strongest turn within that distance are
   corners;
2. the polyline is split at the corners; each piece is resampled every ½ pixel
   and lightly smoothed (Gaussian, σ = 1 px, ends pinned) – that removes the
   short-period staircase;
3. **cubic Bézier fitting** (Schneider, *Graphics Gems* 1990: least-squares
   control points with fixed end tangents, Newton reparameterisation, split at
   the worst point) to within ``fit_px`` of the smoothed points – that removes
   the long-period staircase of shallow edges, which smoothing alone cannot;
4. **flattening** of every Bézier to a polyline with at most ``flat_px``
   chord deviation (the traced shapes stay ``polygon`` / ``path`` objects that
   G-code, hatch, kerf and the planner already handle; the Pi's height map
   accepts only G1 anyway).

Pure numpy, no new dependency. Units are pixels.
"""

from __future__ import annotations

import bisect
import math

import numpy as np

Pts = list[tuple[float, float]]

CORNER_SCALE_PX = 4.0        # arc length for the turn-angle test
CORNER_ANGLE_DEG = 70.0      # turn above this = corner (a square's 90° stays sharp)
SAMPLE_PX = 0.5              # resampling step before fitting
PRESMOOTH_PX = 1.5           # Gaussian sigma along the curve (arc length)
FIT_PX = 0.3                 # default Bézier fit tolerance
MIN_RING_PX = 12.0           # rings shorter than this (tiny dots / holes) stay as they are


def _cumlen(p: np.ndarray) -> np.ndarray:
    d = np.hypot(*(np.diff(p, axis=0).T))
    return np.concatenate([[0.0], np.cumsum(d)])


def _at(p: np.ndarray, s: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Points at arc lengths ``q`` on polyline ``p`` with cumulative lengths ``s``."""
    return np.stack([np.interp(q, s, p[:, 0]), np.interp(q, s, p[:, 1])], axis=1)


def find_corners(p: np.ndarray, closed: bool, scale: float = CORNER_SCALE_PX,
                 angle_deg: float = CORNER_ANGLE_DEG) -> list[int]:
    """Indices of corner vertices of polyline ``p`` (N×2, closed rings without repeat)."""
    n = len(p)
    if n < 3:
        return []
    if closed:
        ext = np.concatenate([p, p, p, p[:1]])
        s = _cumlen(ext)
        per = s[n]
        if per <= 0:
            return []
        sc = min(scale, per / 4)
        si = s[n:2 * n]
        idx = np.arange(n, 2 * n)
    else:
        ext = p
        s = _cumlen(ext)
        if s[-1] <= 0:
            return []
        sc = min(scale, s[-1] / 4)
        idx = np.arange(1, n - 1)
        si = s[idx]
    back = _at(ext, s, si - sc)
    fwd = _at(ext, s, si + sc)
    v = ext[idx]
    a = v - back
    b = fwd - v
    na = np.hypot(a[:, 0], a[:, 1])
    nb = np.hypot(b[:, 0], b[:, 1])
    ok = (na > 1e-9) & (nb > 1e-9)
    cos = np.where(ok, (a * b).sum(1) / np.where(ok, na * nb, 1.0), 1.0)
    turn = np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))
    cand = np.nonzero(turn > angle_deg)[0]
    if not len(cand):
        return []
    # non-maximum suppression within ``sc`` of arc length (strongest first, index tie-break)
    order = cand[np.lexsort((cand, -turn[cand]))]
    taken: list[int] = []
    taken_s: list[float] = []          # kept sorted → neighbour test via bisect
    per = float(s[n]) if closed else 0.0
    for k in order:
        sk = float(si[k])
        j = bisect.bisect_left(taken_s, sk)
        near = [taken_s[i] for i in (j - 1, j) if 0 <= i < len(taken_s)]
        if closed and taken_s:
            near += [taken_s[0], taken_s[-1]]
        clash = False
        for t in near:
            d = abs(sk - t)
            if closed:
                d = min(d, per - d)
            if d < sc:
                clash = True
                break
        if not clash:
            taken.append(int(k))
            bisect.insort(taken_s, sk)
    return sorted(int(idx[k]) - (n if closed else 0) for k in taken)


def _resample(p: np.ndarray, step: float) -> np.ndarray:
    s = _cumlen(p)
    total = s[-1]
    if total <= 0:
        return p[:1].copy()
    m = max(2, int(math.ceil(total / step)) + 1)
    return _at(p, s, np.linspace(0.0, total, m))


def _gauss_kernel(sigma: float, step: float) -> np.ndarray:
    r = max(1, int(math.ceil(3 * sigma / step)))
    x = np.arange(-r, r + 1) * step
    k = np.exp(-0.5 * (x / sigma) ** 2)
    return k / k.sum()


def _smooth_open(q: np.ndarray, sigma: float, step: float) -> np.ndarray:
    """Gaussian smoothing with both ends pinned (odd reflection keeps the end tangent)."""
    if sigma <= 0 or len(q) < 3:
        return q
    full = _gauss_kernel(sigma, step)
    c = len(full) // 2
    r = min(c, len(q) - 1)
    k = full[c - r:c + r + 1]
    k = k / k.sum()
    head = 2 * q[0] - q[r:0:-1]
    tail = 2 * q[-1] - q[-2:-r - 2:-1]
    ext = np.concatenate([head, q, tail])
    out = np.stack([np.convolve(ext[:, 0], k, "valid"), np.convolve(ext[:, 1], k, "valid")], axis=1)
    out[0], out[-1] = q[0], q[-1]
    return out


def _smooth_closed(q: np.ndarray, sigma: float, step: float) -> np.ndarray:
    if sigma <= 0 or len(q) < 4:
        return q
    k = _gauss_kernel(sigma, step)
    r = len(k) // 2
    if r >= len(q):
        return q
    ext = np.concatenate([q[-r:], q, q[:r]])
    return np.stack([np.convolve(ext[:, 0], k, "valid"), np.convolve(ext[:, 1], k, "valid")], axis=1)


# ----------------------------------------------------------------- Schneider fit


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.hypot(v[0], v[1]))
    return v / n if n > 1e-12 else np.zeros(2)


def _bez(ctrl: np.ndarray, u: np.ndarray) -> np.ndarray:
    mu = 1 - u
    b = np.stack([mu ** 3, 3 * mu * mu * u, 3 * mu * u * u, u ** 3], axis=1)
    return b @ ctrl


def _chord_params(d: np.ndarray) -> np.ndarray:
    s = _cumlen(d)
    return s / s[-1] if s[-1] > 0 else np.linspace(0, 1, len(d))


def _generate(d: np.ndarray, u: np.ndarray, t1: np.ndarray, t2: np.ndarray) -> np.ndarray:
    p0, p3 = d[0], d[-1]
    mu = 1 - u
    b0, b1, b2, b3 = mu ** 3, 3 * mu * mu * u, 3 * mu * u * u, u ** 3
    a1 = b1[:, None] * t1
    a2 = b2[:, None] * t2
    c00 = float((a1 * a1).sum())
    c01 = float((a1 * a2).sum())
    c11 = float((a2 * a2).sum())
    tmp = d - np.outer(b0 + b1, p0) - np.outer(b2 + b3, p3)
    x0 = float((a1 * tmp).sum())
    x1 = float((a2 * tmp).sum())
    det = c00 * c11 - c01 * c01
    seg = float(np.hypot(*(p3 - p0)))
    eps = 1e-6 * max(seg, 1e-9)
    if abs(det) > 1e-12:
        al1 = (x0 * c11 - x1 * c01) / det
        al2 = (c00 * x1 - c01 * x0) / det
    else:
        al1 = al2 = 0.0
    if al1 < eps or al2 < eps or al1 > 3 * seg + 1 or al2 > 3 * seg + 1:
        al1 = al2 = seg / 3
    return np.array([p0, p0 + al1 * t1, p3 + al2 * t2, p3])


def _reparam(ctrl: np.ndarray, d: np.ndarray, u: np.ndarray) -> np.ndarray:
    q = _bez(ctrl, u)
    d1 = 3 * (ctrl[1:] - ctrl[:-1])
    d2 = 2 * (d1[1:] - d1[:-1])
    mu = 1 - u
    q1 = np.outer(mu * mu, d1[0]) + np.outer(2 * mu * u, d1[1]) + np.outer(u * u, d1[2])
    q2 = np.outer(mu, d2[0]) + np.outer(u, d2[1])
    diff = q - d
    num = (diff * q1).sum(1)
    den = (q1 * q1).sum(1) + (diff * q2).sum(1)
    step = np.where(np.abs(den) > 1e-12, num / np.where(np.abs(den) > 1e-12, den, 1.0), 0.0)
    nu = np.clip(u - step, 0.0, 1.0)
    nu[0], nu[-1] = 0.0, 1.0
    return np.maximum.accumulate(nu)


def fit_beziers(d: np.ndarray, t1: np.ndarray, t2: np.ndarray, tol: float) -> list[np.ndarray]:
    """Cubic Béziers through points ``d`` (ends fixed) within ``tol`` (max distance).
    ``t1`` points from ``d[0]`` into the curve, ``t2`` from ``d[-1]`` back into it."""
    out: list[np.ndarray] = []
    tol2 = tol * tol
    stack = [(0, len(d) - 1, t1, t2)]
    while stack:
        first, last, a, b = stack.pop()
        seg = d[first:last + 1]
        if len(seg) == 2 or not a.any() or not b.any():
            dist = float(np.hypot(*(seg[-1] - seg[0]))) / 3
            ta = a if a.any() else _unit(seg[-1] - seg[0])
            tb = b if b.any() else _unit(seg[0] - seg[-1])
            if len(seg) == 2:
                out.append(np.array([seg[0], seg[0] + ta * dist, seg[-1] + tb * dist, seg[-1]]))
                continue
            a, b = ta, tb
        u = _chord_params(seg)
        ctrl = _generate(seg, u, a, b)
        err = ((_bez(ctrl, u) - seg) ** 2).sum(1)
        k = int(np.argmax(err))
        if err[k] > tol2 and err[k] < 16 * tol2:
            for _ in range(4):
                u = _reparam(ctrl, seg, u)
                ctrl = _generate(seg, u, a, b)
                err = ((_bez(ctrl, u) - seg) ** 2).sum(1)
                k = int(np.argmax(err))
                if err[k] <= tol2:
                    break
        if err[k] <= tol2:
            out.append(ctrl)
            continue
        if k <= 0 or k >= len(seg) - 1:
            k = len(seg) // 2
        split = first + k
        tc = _unit(d[split - 1] - d[split + 1])
        if not tc.any():
            tc = _unit(d[split - 1] - d[split])
        stack.append((split, last, -tc, b))      # right half (processed after the left)
        stack.append((first, split, a, tc))
    return out


def flatten(beziers: list[np.ndarray], tol: float) -> np.ndarray:
    """Béziers → polyline (start point once) with chord deviation ≤ ``tol``."""
    pts = [beziers[0][0][None, :]]
    for c in beziers:
        m = max(float(np.hypot(*(c[0] - 2 * c[1] + c[2]))), float(np.hypot(*(c[1] - 2 * c[2] + c[3]))))
        n = max(1, int(math.ceil(math.sqrt(0.75 * m / max(tol, 1e-9)))))
        pts.append(_bez(c, np.arange(1, n + 1) / n))
    return np.concatenate(pts)


def _end_tangent(q: np.ndarray, reach: float) -> np.ndarray:
    """Direction from ``q[0]`` into the curve, measured ``reach`` px along it."""
    s = _cumlen(q)
    if s[-1] <= 0:
        return np.zeros(2)
    tgt = _at(q, s, np.array([min(reach, s[-1])]))[0]
    return _unit(tgt - q[0])


def _edge_midpoints(q: np.ndarray, keep_ends: bool) -> np.ndarray:
    """Pixel-edge staircase → midpoints of its unit edges (the boundary of a
    rasterised shape passes there, not through the pixel corners)."""
    a, b = q[:-1], q[1:]
    n = np.maximum(1, np.rint(np.hypot(*(b - a).T)).astype(int))
    rep = np.repeat(np.arange(len(a)), n)
    k = np.concatenate([np.arange(m) for m in n]) + 0.5
    f = (k / n[rep])[:, None]
    mid = a[rep] + (b[rep] - a[rep]) * f
    if keep_ends:
        mid = np.concatenate([q[:1], mid, q[-1:]])
    return mid


def _fit_piece(q: np.ndarray, fit_px: float, flat_px: float, mids: bool) -> np.ndarray:
    """Open piece (ends pinned) → flattened smooth polyline."""
    if len(q) < 2:
        return q
    if mids and len(q) > 2:
        q = _edge_midpoints(q, keep_ends=True)
    r = _resample(q, SAMPLE_PX)
    if len(r) < 3:
        return np.array([q[0], q[-1]])
    r = _smooth_open(r, PRESMOOTH_PX, SAMPLE_PX)
    reach = min(2.0, _cumlen(r)[-1] / 3)
    t1 = _end_tangent(r, reach)
    t2 = _end_tangent(r[::-1], reach)
    return flatten(fit_beziers(r, t1, t2, fit_px), flat_px)


def _line_fit(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    if len(pts) < 3:
        return None
    c = pts.mean(axis=0)
    _u, sv, vt = np.linalg.svd(pts - c, full_matrices=False)
    if sv[0] < 1e-9:
        return None
    return c, vt[0]


def _refine_corner(ext: np.ndarray, s: np.ndarray, sc: float, lo: float, hi: float) -> np.ndarray | None:
    """Corner position as the intersection of straight lines fitted to the
    stretches just before and after arc length ``sc`` (``lo``/``hi`` = limits
    of the neighbouring pieces). On a staircase the vertex at the tip is up to
    ~0.7 px off the true corner; the fitted sides meet where the corner is."""
    reach_b = min(3 * CORNER_SCALE_PX, (sc - lo) * 0.6)
    reach_f = min(3 * CORNER_SCALE_PX, (hi - sc) * 0.6)
    if reach_b < 2.0 or reach_f < 2.0:
        return None
    vb = _at(ext, s, sc - np.arange(1.0, reach_b, 0.25))
    vf = _at(ext, s, sc + np.arange(1.0, reach_f, 0.25))
    lb, lf = _line_fit(vb), _line_fit(vf)
    if lb is None or lf is None:
        return None
    (cb, db), (cf_, df) = lb, lf
    cross = db[0] * df[1] - db[1] * df[0]
    if abs(cross) < math.sin(math.radians(25)):
        return None
    t = ((cf_[0] - cb[0]) * df[1] - (cf_[1] - cb[1]) * df[0]) / cross
    pt = cb + t * db
    v = _at(ext, s, np.array([sc]))[0]
    if float(np.hypot(*(pt - v))) > 1.5:
        return None
    return pt


def smooth_polyline(pts: Pts, closed: bool, fit_px: float = FIT_PX, flat_px: float = 0.1,
                    pinned: tuple[int, ...] = (), edge_midpoints: bool = False) -> Pts:
    """Smooth a traced polyline, keeping corners (and ``pinned`` vertices) as sharp vertices.

    ``closed`` rings are given without repeating the first point and returned the
    same way; open lines keep both end points exactly. ``edge_midpoints``: the
    input runs along pixel edges (outline trace), fit through the edge midpoints.
    """
    p = np.asarray(pts, float)
    if len(p) < 3:
        return [tuple(map(float, v)) for v in p]
    if closed:
        s = _cumlen(np.concatenate([p, p[:1]]))
        if s[-1] < MIN_RING_PX:
            return [tuple(map(float, v)) for v in p]
    corners = sorted(set(find_corners(p, closed)) | {i for i in pinned if 0 <= i < len(p)})
    pieces: list[np.ndarray] = []
    if closed:
        if not corners:
            loop = np.concatenate([p, p[:1]])
            if edge_midpoints:
                loop = _edge_midpoints(loop, keep_ends=False)
                loop = np.concatenate([loop, loop[:1]])
            r = _resample(loop, SAMPLE_PX)[:-1]
            if len(r) < 4:
                return [tuple(map(float, v)) for v in p]
            r = _smooth_closed(r, PRESMOOTH_PX, SAMPLE_PX)
            m = 4
            t = _unit(r[m] - r[-m])
            loop = np.concatenate([r, r[:1]])
            out = flatten(fit_beziers(loop, t, -t, fit_px), flat_px)[:-1]
            return [(float(x), float(y)) for x, y in out]
        n = len(p)
        ext = np.concatenate([p, p, p, p[:1]])
        s = _cumlen(ext)
        cs = corners + [corners[0] + n]
        fixed = {}
        for j, c in enumerate(corners):
            prev_c = cs[j - 1] if j > 0 else corners[-1] - n
            if c in pinned:
                continue
            q = _refine_corner(ext, s, s[c + n], s[prev_c + n], s[cs[j + 1] + n])
            if q is not None:
                fixed[c] = q
        for a, b in zip(corners, corners[1:] + [corners[0] + n]):
            idx = [i % n for i in range(a, b + 1)]
            piece = p[idx].copy()
            if a % n in fixed:
                piece[0] = fixed[a % n]
            if b % n in fixed:
                piece[-1] = fixed[b % n]
            pieces.append(piece)
    else:
        cuts = sorted({0, len(p) - 1, *corners})
        s = _cumlen(p)
        fixed = {}
        for j in range(1, len(cuts) - 1):
            c = cuts[j]
            if c in pinned:
                continue
            q = _refine_corner(p, s, s[c], s[cuts[j - 1]], s[cuts[j + 1]])
            if q is not None:
                fixed[c] = q
        for a, b in zip(cuts, cuts[1:]):
            piece = p[a:b + 1].copy()
            if a in fixed:
                piece[0] = fixed[a]
            if b in fixed:
                piece[-1] = fixed[b]
            pieces.append(piece)
    out_pts: list[np.ndarray] = []
    for k, q in enumerate(pieces):
        f = _fit_piece(q, fit_px, flat_px, edge_midpoints)
        out_pts.append(f if k == 0 else f[1:])
    out = np.concatenate(out_pts)
    if closed:
        out = out[:-1]
    return [(float(x), float(y)) for x, y in out]


__all__ = ["smooth_polyline", "find_corners", "fit_beziers", "flatten",
           "CORNER_SCALE_PX", "CORNER_ANGLE_DEG", "FIT_PX"]
