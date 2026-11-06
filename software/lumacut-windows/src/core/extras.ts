/** Port von Extras.kt. */
import { Shapes } from './geometry';
import { boundsOf, insideWork, type Box, type Poly, type Pt } from './model';

export const ArcText = {
  /** radiusMm > 0: Text oben auf dem Kreis; < 0: unten am Kreis, Buchstaben zur Mitte. Bogenlänge der Grundlinie = flache Länge. */
  bend(paths: Poly[], radiusMm: number): Poly[] {
    if (!(Math.abs(radiusMm) >= 1)) throw new Error('Radius mindestens 1 mm');
    const box = boundsOf(paths);
    if (!box) return paths;
    const r0 = Math.abs(radiusMm), cx = (box.minX + box.maxX) / 2, base = box.maxY;
    return paths.map((poly) => poly.map((p) => {
      const theta = (p.x - cx) / r0, above = base - p.y;
      if (radiusMm > 0) { const r = r0 + above; return { x: r * Math.sin(theta), y: r0 - r * Math.cos(theta) }; }
      const r = Math.max(0.01, r0 - above);
      return { x: r * Math.sin(theta), y: r * Math.cos(theta) - r0 };
    }));
  },
};

export const Arrange = {
  /** Versätze aller Kopien außer dem Original. */
  gridOffsets(piece: Box, nx: number, ny: number, gapX: number, gapY: number): Pt[] {
    if (!(nx >= 1 && nx <= 50 && ny >= 1 && ny <= 50)) throw new Error('Höchstens 50 Stück je Richtung');
    const out: Pt[] = [], w = piece.maxX - piece.minX, h = piece.maxY - piece.minY;
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      if (i === 0 && j === 0) continue;
      out.push({ x: i * (w + gapX), y: j * (h + gapY) });
    }
    return out;
  },
  /** Versätze, bei denen das Stück in der Arbeitsfläche bleibt. */
  inside(piece: Box, offsets: Pt[]): Pt[] {
    return offsets.filter((o) => insideWork({ minX: piece.minX + o.x, minY: piece.minY + o.y, maxX: piece.maxX + o.x, maxY: piece.maxY + o.y }));
  },
};

const stretch = (raw: Poly, w: number, h: number): Poly => {
  const b = boundsOf([raw])!, bw = b.maxX - b.minX, bh = b.maxY - b.minY;
  return raw.map((p) => ({ x: (p.x - b.minX) / bw * w, y: (p.y - b.minY) / bh * h }));
};

export const ShapeLib = {
  heart(w: number, h: number): Poly {
    const n = 120, raw: Poly = [];
    for (let k = 0; k <= n; k++) {
      const t = 2 * Math.PI * k / n, s = Math.sin(t);
      raw.push({ x: 16 * (s * s * s), y: -(13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t)) });
    }
    return stretch(raw, w, h);
  },
  star(points: number, w: number, h: number, innerRatio = 0.45): Poly {
    const n = Math.min(24, Math.max(3, points)), raw: Poly = [];
    const inner = Math.min(0.9, Math.max(0.1, innerRatio));
    for (let k = 0; k <= 2 * n; k++) {
      const a = -Math.PI / 2 + Math.PI * k / n, r = k % 2 === 0 ? 1 : inner;
      raw.push({ x: r * Math.cos(a), y: r * Math.sin(a) });
    }
    return stretch(raw, w, h);
  },
  /** Umriss und Loch als zwei geschlossene Linien. */
  pendant(w: number, h: number, holeDiameter = 4): Poly[] {
    const outline = Shapes.rect(w, h, Math.min(w, h) * 0.25);
    const hole = Shapes.ellipse(holeDiameter, holeDiameter).map((p) => ({ x: p.x + (w - holeDiameter) / 2, y: p.y + holeDiameter * 0.8 }));
    return [outline, hole];
  },
};
