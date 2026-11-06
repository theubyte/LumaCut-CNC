import type { CurveNode, CurvePath, Poly, Pt } from './model';

/**
 * Editable cubic outlines (`Element.curves`, Windows-only) and their flattening into `paths`.
 * Handles are absolute coordinates in the element's local space: h1 arrives at the node, h2 leaves it.
 * `paths` stays the truth for output, so every edit here is followed by `flattenCurves`.
 */
export const FLATTEN_TOL_MM = 0.02;
const dist = (a: Pt, b: Pt) => Math.hypot(a.x - b.x, a.y - b.y);
const hasIn = (n: CurveNode) => n.hx1 != null && n.hy1 != null;
const hasOut = (n: CurveNode) => n.hx2 != null && n.hy2 != null;
export const handleIn = (n: CurveNode): Pt => (hasIn(n) ? { x: n.hx1!, y: n.hy1! } : { x: n.x, y: n.y });
export const handleOut = (n: CurveNode): Pt => (hasOut(n) ? { x: n.hx2!, y: n.hy2! } : { x: n.x, y: n.y });
const mid = (a: Pt, b: Pt): Pt => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });

function cubicInto(out: Pt[], a: Pt, b: Pt, c: Pt, d: Pt, tol: number, depth = 0) {
  const ux = 3 * b.x - 2 * a.x - d.x, uy = 3 * b.y - 2 * a.y - d.y;
  const vx = 3 * c.x - a.x - 2 * d.x, vy = 3 * c.y - a.y - 2 * d.y;
  const flat = Math.max(ux * ux, vx * vx) + Math.max(uy * uy, vy * vy);
  if (depth >= 12 || flat <= 16 * tol * tol) { out.push(d); return; }
  const ab = mid(a, b), bc = mid(b, c), cd = mid(c, d), abc = mid(ab, bc), bcd = mid(bc, cd), m = mid(abc, bcd);
  cubicInto(out, a, ab, abc, m, tol, depth + 1);
  cubicInto(out, m, bcd, cd, d, tol, depth + 1);
}

/** A closed path's flattening ends exactly on its first point, as `isClosed` expects. */
export function flattenCurve(path: CurvePath, tol = FLATTEN_TOL_MM): Poly {
  const n = path.nodes;
  if (n.length === 0) return [];
  const out: Pt[] = [{ x: n[0].x, y: n[0].y }];
  const spans = path.closed ? n.length : n.length - 1;
  for (let i = 0; i < spans; i++) {
    const a = n[i], d = n[(i + 1) % n.length];
    if (hasOut(a) || hasIn(d)) cubicInto(out, a, handleOut(a), handleIn(d), { x: d.x, y: d.y }, tol);
    else out.push({ x: d.x, y: d.y });
  }
  return out;
}
export const flattenCurves = (paths: CurvePath[], tol = FLATTEN_TOL_MM): Poly[] => paths.map((p) => flattenCurve(p, tol)).filter((p) => p.length >= 2);

/** Corner nodes for existing polylines (imports, booleans). Closed polylines lose their repeated last point. */
export function curvesFromPaths(polys: Poly[]): CurvePath[] {
  return polys.map((poly) => {
    const closed = poly.length > 2 && dist(poly[0], poly[poly.length - 1]) < 1e-6;
    const pts = closed ? poly.slice(0, -1) : poly;
    return { closed, nodes: pts.map((p) => ({ x: p.x, y: p.y })) };
  });
}

/** Handle length for a quarter circle. */
const K = 0.5522847498;
export function ellipseCurve(w: number, h: number): CurvePath {
  const rx = w / 2, ry = h / 2, kx = rx * K, ky = ry * K;
  return { closed: true, nodes: [
    { x: rx, y: 0, hx1: rx - kx, hy1: 0, hx2: rx + kx, hy2: 0, smooth: true },
    { x: w, y: ry, hx1: w, hy1: ry - ky, hx2: w, hy2: ry + ky, smooth: true },
    { x: rx, y: h, hx1: rx + kx, hy1: h, hx2: rx - kx, hy2: h, smooth: true },
    { x: 0, y: ry, hx1: 0, hy1: ry + ky, hx2: 0, hy2: ry - ky, smooth: true },
  ] };
}
export const rectCurve = (w: number, h: number): CurvePath => ({ closed: true, nodes: [{ x: 0, y: 0 }, { x: w, y: 0 }, { x: w, y: h }, { x: 0, y: h }] });

const mapNode = (n: CurveNode, f: (p: Pt) => Pt): CurveNode => {
  const p = f(n), out: CurveNode = { x: p.x, y: p.y };
  if (hasIn(n)) { const q = f(handleIn(n)); out.hx1 = q.x; out.hy1 = q.y; }
  if (hasOut(n)) { const q = f(handleOut(n)); out.hx2 = q.x; out.hy2 = q.y; }
  if (n.smooth) out.smooth = true;
  return out;
};
export const mapCurves = (paths: CurvePath[], f: (p: Pt) => Pt): CurvePath[] => paths.map((c) => ({ closed: c.closed, nodes: c.nodes.map((n) => mapNode(n, f)) }));

const replaceNode = (path: CurvePath, i: number, n: CurveNode): CurvePath => ({ closed: path.closed, nodes: path.nodes.map((q, k) => (k === i ? n : q)) });

/** Moves a node with its handles. */
export function moveNode(path: CurvePath, i: number, to: Pt): CurvePath {
  const n = path.nodes[i], dx = to.x - n.x, dy = to.y - n.y;
  return replaceNode(path, i, mapNode(n, (p) => ({ x: p.x + dx, y: p.y + dy })));
}

/** Moves one handle. A smooth node keeps the opposite handle in line, at its own length. */
export function moveHandle(path: CurvePath, i: number, which: 'in' | 'out', to: Pt): CurvePath {
  const n: CurveNode = { ...path.nodes[i] };
  if (which === 'in') { n.hx1 = to.x; n.hy1 = to.y; } else { n.hx2 = to.x; n.hy2 = to.y; }
  const other = which === 'in' ? handleOut(n) : handleIn(n);
  const otherLen = dist(other, n), len = dist(to, n);
  if (n.smooth && otherLen > 1e-9 && len > 1e-9) {
    const ox = n.x - (to.x - n.x) / len * otherLen, oy = n.y - (to.y - n.y) / len * otherLen;
    if (which === 'in') { n.hx2 = ox; n.hy2 = oy; } else { n.hx1 = ox; n.hy1 = oy; }
  }
  return replaceNode(path, i, n);
}

/** Corner without handles, or smooth with handles along the neighbours. */
export function toggleSmooth(path: CurvePath, i: number): CurvePath {
  const n = path.nodes[i], N = path.nodes.length;
  if (hasIn(n) || hasOut(n)) return replaceNode(path, i, { x: n.x, y: n.y });
  const prev = path.closed || i > 0 ? path.nodes[(i - 1 + N) % N] : null;
  const next = path.closed || i < N - 1 ? path.nodes[(i + 1) % N] : null;
  const from = prev ?? n, to = next ?? n;
  const dx = to.x - from.x, dy = to.y - from.y, l = Math.hypot(dx, dy) || 1;
  const a = prev ? dist(prev, n) / 3 : 0, b = next ? dist(next, n) / 3 : 0;
  return replaceNode(path, i, { x: n.x, y: n.y, hx1: n.x - dx / l * a, hy1: n.y - dy / l * a, hx2: n.x + dx / l * b, hy2: n.y + dy / l * b, smooth: true });
}

/** Keeps at least two nodes on an open path and three on a closed one; null when that would be violated. */
export function deleteNode(path: CurvePath, i: number): CurvePath | null {
  if (path.nodes.length <= (path.closed ? 3 : 2)) return null;
  return { closed: path.closed, nodes: path.nodes.filter((_, k) => k !== i) };
}

function spanPoint(a: CurveNode, d: CurveNode, t: number): Pt {
  const b = handleOut(a), c = handleIn(d), u = 1 - t;
  return { x: u * u * u * a.x + 3 * u * u * t * b.x + 3 * u * t * t * c.x + t * t * t * d.x, y: u * u * u * a.y + 3 * u * u * t * b.y + 3 * u * t * t * c.y + t * t * t * d.y };
}

/** Closest point on the outline: span index (node i to i+1), parameter, distance. */
export function nearestOnPath(path: CurvePath, p: Pt): { span: number; t: number; dist: number } | null {
  const n = path.nodes; let best: { span: number; t: number; dist: number } | null = null;
  const spans = path.closed ? n.length : n.length - 1;
  for (let s = 0; s < spans; s++) {
    const a = n[s], d = n[(s + 1) % n.length];
    if (!hasOut(a) && !hasIn(d)) {
      const dx = d.x - a.x, dy = d.y - a.y, l2 = dx * dx + dy * dy;
      const t = l2 > 0 ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2)) : 0;
      const q = dist(p, { x: a.x + dx * t, y: a.y + dy * t });
      if (!best || q < best.dist) best = { span: s, t, dist: q };
    } else for (let k = 0; k <= 32; k++) {
      const t = k / 32, q = dist(p, spanPoint(a, d, t));
      if (!best || q < best.dist) best = { span: s, t, dist: q };
    }
  }
  return best;
}

/** Splits a span at `t` without changing the outline's shape (de Casteljau). */
export function insertNode(path: CurvePath, span: number, t: number): CurvePath {
  const n = path.nodes, a = n[span], ib = (span + 1) % n.length, d = n[ib];
  const nodes = n.slice();
  if (!hasOut(a) && !hasIn(d)) {
    nodes.splice(span + 1, 0, { x: a.x + (d.x - a.x) * t, y: a.y + (d.y - a.y) * t });
    return { closed: path.closed, nodes };
  }
  const b = handleOut(a), c = handleIn(d), lerp = (p: Pt, q: Pt): Pt => ({ x: p.x + (q.x - p.x) * t, y: p.y + (q.y - p.y) * t });
  const ab = lerp(a, b), bc = lerp(b, c), cd = lerp(c, d), abc = lerp(ab, bc), bcd = lerp(bc, cd), m = lerp(abc, bcd);
  nodes[span] = { ...a, hx2: ab.x, hy2: ab.y };
  nodes[ib] = { ...d, hx1: cd.x, hy1: cd.y };
  nodes.splice(span + 1, 0, { x: m.x, y: m.y, hx1: abc.x, hy1: abc.y, hx2: bcd.x, hy2: bcd.y, smooth: true });
  return { closed: path.closed, nodes };
}

export const nodeCount = (paths: CurvePath[]) => paths.reduce((s, p) => s + p.nodes.length, 0);
