/** Port von Geometry.kt und orderForCutting aus ImportLayout.kt. */
import { boundsOf, type Box, type Poly, type Pt } from './model';

const f64 = new Float64Array(1);
const u32 = new Uint32Array(f64.buffer);
const HI = new Uint8Array(new Uint32Array([1]).buffer)[0] === 1 ? 1 : 0;
const withHigh = (hi: number) => { u32[HI] = hi; u32[1 - HI] = 0; return f64[0]; };

/**
 * Javas Math.hypot (fdlibm). `Math.hypot` von JS weicht im letzten Bit ab, und das kippt
 * Gleichstände in der Pfadreihenfolge: dann wäre der G-Code nicht mehr gleich.
 */
export function hypot(x: number, y: number): number {
  let a = Math.abs(x), b = Math.abs(y);
  if (b > a) { const t = a; a = b; b = t; }
  if (!(a < Infinity)) return Math.hypot(x, y);
  if (b === 0) return a;
  f64[0] = a; const ha = u32[HI];
  f64[0] = b; const hb = u32[HI];
  if (ha - hb > 0x3c00000) return a + b;
  if (a > 1e150 || b < 3e-151) return Math.hypot(x, y);
  const w = a - b;
  if (w > b) {
    const t1 = withHigh(ha), t2 = a - t1;
    return Math.sqrt(t1 * t1 - (b * -b - t2 * (a + t1)));
  }
  a = a + a;
  const y1 = withHigh(hb), y2 = b - y1, t1 = withHigh(ha + 0x00100000), t2 = a - t1;
  return Math.sqrt(t1 * y1 - (w * -w - (t1 * y2 + t2 * b)));
}

export const dist = (a: Pt, b: Pt) => hypot(a.x - b.x, a.y - b.y);
export const polyClosed = (p: Poly, eps = 1e-6) => p.length > 2 && dist(p[0], p[p.length - 1]) < eps;
export function polyLength(p: Poly): number {
  let s = 0;
  for (let i = 1; i < p.length; i++) s += dist(p[i - 1], p[i]);
  return s;
}
export const boxContains = (b: Box, x: number, y: number) => x >= b.minX && x <= b.maxX && y >= b.minY && y <= b.maxY;

/** Horizontale Schraffur (even-odd), abwechselnde Richtung. Gleiche Werte wie Kotlin, aber Kanten je Zeile vorsortiert. */
export function hatch(polys: Poly[], spacing: number): Poly[] {
  if (!(spacing > 0.01)) throw new Error('Zeilenabstand zu klein');
  const closed = polys.filter((p) => p.length >= 3);
  const box = boundsOf(closed);
  if (!box) return [];
  const ys: number[] = [];
  for (let y = box.minY + spacing / 2; y <= box.maxY; y += spacing) ys.push(y);
  const rows: number[][] = ys.map(() => []);
  const edge = (a: Pt, b: Pt) => {
    if (a.y === b.y) return;
    const lo = a.y < b.y ? a.y : b.y, hi = a.y < b.y ? b.y : a.y;
    let l = 0, r = ys.length;
    while (l < r) { const m = (l + r) >> 1; if (ys[m] < lo) l = m + 1; else r = m; }
    for (let i = l; i < ys.length && ys[i] < hi; i++) rows[i].push(a.x + (ys[i] - a.y) * (b.x - a.x) / (b.y - a.y));
  };
  for (const poly of closed) {
    for (let i = 1; i < poly.length; i++) edge(poly[i - 1], poly[i]);
    if (!polyClosed(poly)) edge(poly[poly.length - 1], poly[0]);
  }
  const result: Poly[] = [];
  for (let row = 0; row < ys.length; row++) {
    const y = ys[row], xs = rows[row];
    if (xs.length < 2) continue;
    xs.sort((p, q) => p - q);
    const pairs: number[] = [];
    for (let k = 0; k + 1 < xs.length; k += 2) if (xs[k + 1] - xs[k] > 1e-6) pairs.push(k);
    if (row % 2 === 0) for (const k of pairs) result.push([{ x: xs[k], y }, { x: xs[k + 1], y }]);
    else for (let i = pairs.length - 1; i >= 0; i--) { const k = pairs[i]; result.push([{ x: xs[k + 1], y }, { x: xs[k], y }]); }
  }
  return result;
}

/** Nächster-Nachbar-Reihenfolge: offene Pfade dürfen umgedreht werden, geschlossene beginnen, wo sie beginnen. */
export function orderPaths(paths: Poly[], start: Pt = { x: 0, y: 0 }): Poly[] {
  const items = paths.filter((p) => p.length >= 2);
  let n = items.length;
  const out: Poly[] = new Array(n);
  const fx = new Float64Array(n), fy = new Float64Array(n), lx = new Float64Array(n), ly = new Float64Array(n);
  const closed = new Uint8Array(n), idx = new Int32Array(n);
  items.forEach((p, i) => {
    const a = p[0], b = p[p.length - 1];
    fx[i] = a.x; fy[i] = a.y; lx[i] = b.x; ly[i] = b.y; closed[i] = polyClosed(p) ? 1 : 0; idx[i] = i;
  });
  let atX = start.x, atY = start.y, count = 0;
  while (n > 0) {
    let best = 0, bestDist = Number.MAX_VALUE, bestSq = Infinity, reverse = false;
    for (let i = 0; i < n; i++) {
      // Quadrat zuerst: hypot nur für Kandidaten, die wirklich näher sein können.
      let dx = atX - fx[i], dy = atY - fy[i], sq = dx * dx + dy * dy;
      if (sq <= bestSq) {
        const d = hypot(dx, dy);
        if (d < bestDist) { bestDist = d; best = i; reverse = false; bestSq = d * d * 1.000000001; }
      }
      if (closed[i] === 0) {
        dx = atX - lx[i]; dy = atY - ly[i]; sq = dx * dx + dy * dy;
        if (sq <= bestSq) {
          const d = hypot(dx, dy);
          if (d < bestDist) { bestDist = d; best = i; reverse = true; bestSq = d * d * 1.000000001; }
        }
      }
    }
    const p = items[idx[best]];
    const chosen = reverse ? p.slice().reverse() : p;
    out[count++] = chosen;
    const e = chosen[chosen.length - 1];
    atX = e.x; atY = e.y;
    fx.copyWithin(best, best + 1, n); fy.copyWithin(best, best + 1, n);
    lx.copyWithin(best, best + 1, n); ly.copyWithin(best, best + 1, n);
    closed.copyWithin(best, best + 1, n); idx.copyWithin(best, best + 1, n);
    n--;
  }
  return out;
}

/** Innere Pfade vor den geschlossenen Konturen um sie herum: ein Teil fällt nie vor seinen Innenschnitten heraus. */
export function orderForCutting(paths: Poly[], start: Pt): Poly[] {
  const p = paths.filter((q) => q.length >= 2);
  if (p.length < 2 || p.length > 1500) return orderPaths(p, start);
  const closed = p.map((q) => q.length >= 4 && polyClosed(q));
  const boxes = p.map((q) => boundsOf([q])!);
  const area = boxes.map((b) => (b.maxX - b.minX) * (b.maxY - b.minY));
  const inside = (poly: Poly, pt: Pt) => {
    let c = false;
    for (let i = 1; i < poly.length; i++) {
      const a = poly[i - 1], b = poly[i];
      if ((a.y > pt.y) !== (b.y > pt.y) && pt.x < (b.x - a.x) * (pt.y - a.y) / (b.y - a.y) + a.x) c = !c;
    }
    return c;
  };
  const height = new Int32Array(p.length);
  const byArea = p.map((_, i) => i).sort((a, b) => area[a] - area[b]);
  for (const i of byArea) {
    if (!closed[i]) continue;
    let h = 0;
    for (let j = 0; j < p.length; j++) {
      if (j === i || area[j] >= area[i]) continue;
      const bj = boxes[j];
      if (!boxContains(boxes[i], bj.minX, bj.minY) || !boxContains(boxes[i], bj.maxX, bj.maxY)) continue;
      if (inside(p[i], p[j][0])) h = Math.max(h, height[j] + 1);
    }
    height[i] = h;
  }
  const out: Poly[] = [];
  let at = start;
  for (const level of [...new Set(height)].sort((a, b) => a - b)) {
    const tier = orderPaths(p.filter((_, i) => height[i] === level), at);
    if (tier.length) { const last = tier[tier.length - 1]; at = last[last.length - 1]; }
    out.push(...tier);
  }
  return out;
}

const rad = (deg: number) => deg * 0.017453292519943295;

export const Shapes = {
  rect(w: number, h: number, radius = 0): Poly {
    if (radius <= 0) return [{ x: 0, y: 0 }, { x: w, y: 0 }, { x: w, y: h }, { x: 0, y: h }, { x: 0, y: 0 }];
    const r = Math.min(radius, Math.min(w, h) / 2);
    const out: Pt[] = [];
    const arc = (cx: number, cy: number, from: number) => {
      for (let k = 0; k <= 8; k++) { const a = rad(from + 90 * k / 8); out.push({ x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) }); }
    };
    arc(w - r, r, 270); arc(w - r, h - r, 0); arc(r, h - r, 90); arc(r, r, 180);
    out.push(out[0]);
    return out;
  },
  ellipse(w: number, h: number, segmentMm = 0.4): Poly {
    const rx = w / 2, ry = h / 2, n = Math.max(24, Math.trunc(Math.PI * (rx + ry) / segmentMm));
    const out: Pt[] = [];
    for (let k = 0; k <= n; k++) { const a = 2 * Math.PI * k / n; out.push({ x: rx + rx * Math.cos(a), y: ry + ry * Math.sin(a) }); }
    return out;
  },
  polygon(sides: number, w: number, h: number): Poly {
    const n = Math.min(64, Math.max(3, sides));
    const out: Pt[] = [];
    for (let k = 0; k <= n; k++) { const a = -Math.PI / 2 + 2 * Math.PI * k / n; out.push({ x: w / 2 + w / 2 * Math.cos(a), y: h / 2 + h / 2 * Math.sin(a) }); }
    return out;
  },
};

/** Douglas-Peucker. */
export function simplify(points: Poly, tolerance: number): Poly {
  if (points.length < 3) return points;
  const keep = new Uint8Array(points.length);
  keep[0] = 1; keep[points.length - 1] = 1;
  const stack: number[] = [0, points.length - 1];
  while (stack.length) {
    const b = stack.pop()!, a = stack.pop()!;
    let maxD = 0, idx = -1;
    const pa = points[a], pb = points[b], len = dist(pa, pb);
    for (let i = a + 1; i < b; i++) {
      const p = points[i];
      const d = len < 1e-12 ? dist(p, pa) : Math.abs((pb.x - pa.x) * (pa.y - p.y) - (pa.x - p.x) * (pb.y - pa.y)) / len;
      if (d > maxD) { maxD = d; idx = i; }
    }
    if (idx >= 0 && maxD > tolerance) { keep[idx] = 1; stack.push(a, idx, idx, b); }
  }
  return points.filter((_, i) => keep[i] === 1);
}
