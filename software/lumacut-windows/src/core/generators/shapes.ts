import { boundsOf, type Poly } from '../model';

/** Ready-made closed outlines in the box 0..w x 0..h. Port of ShapeLib in Extras.kt. */
function fit(raw: Poly, w: number, h: number): Poly {
  const b = boundsOf([raw])!;
  return raw.map((p) => ({ x: (p.x - b.minX) / (b.maxX - b.minX) * w, y: (p.y - b.minY) / (b.maxY - b.minY) * h }));
}
export function heart(w: number, h: number): Poly {
  const raw: Poly = [];
  for (let k = 0; k <= 120; k++) {
    const t = 2 * Math.PI * k / 120;
    raw.push({ x: 16 * Math.sin(t) ** 3, y: -(13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t)) });
  }
  raw[120] = raw[0];
  return fit(raw, w, h);
}
export function star(points: number, w: number, h: number, inner = 0.45): Poly {
  const raw: Poly = [];
  for (let k = 0; k <= 2 * points; k++) {
    const a = -Math.PI / 2 + Math.PI * k / points, r = k % 2 === 0 ? 1 : inner;
    raw.push({ x: r * Math.cos(a), y: r * Math.sin(a) });
  }
  raw[2 * points] = raw[0];
  return fit(raw, w, h);
}
export function drop(w: number, h: number): Poly {
  const raw: Poly = [];
  for (let k = 0; k <= 120; k++) {
    const t = 2 * Math.PI * k / 120;
    raw.push({ x: Math.sin(t) * Math.sin(t / 2), y: -Math.cos(t) });
  }
  raw[120] = raw[0];
  return fit(raw, w, h);
}
