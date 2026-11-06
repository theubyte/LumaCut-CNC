/** Port von Tools.kt (Ausrichten, Verschweißen auf Raster, Haltestege, Schachteln, Fingerzinken-Box) und ImportLayout.shelf. */
import { Contour, Mask } from './contour';
import { dist, polyClosed, polyLength } from './geometry';
import { Bed, boundsOf, boxCenter, boxH, boxW, type Box, type Poly, type Pt } from './model';

export type AlignMode = 'LEFT' | 'CENTER_X' | 'RIGHT' | 'TOP' | 'CENTER_Y' | 'BOTTOM';
export const Align = {
  /** Verschiebt jede Box auf die Kante oder Mittellinie von ref. */
  offsets(boxes: Box[], mode: AlignMode, ref: Box): Pt[] {
    const rc = boxCenter(ref);
    return boxes.map((b) => {
      const c = boxCenter(b);
      switch (mode) {
        case 'LEFT': return { x: ref.minX - b.minX, y: 0 };
        case 'CENTER_X': return { x: rc.x - c.x, y: 0 };
        case 'RIGHT': return { x: ref.maxX - b.maxX, y: 0 };
        case 'TOP': return { x: 0, y: ref.minY - b.minY };
        case 'CENTER_Y': return { x: 0, y: rc.y - c.y };
        default: return { x: 0, y: ref.maxY - b.maxY };
      }
    });
  },
  /** Gleiche Abstände; die äußeren beiden bleiben. */
  distribute(boxes: Box[], horizontal: boolean): Pt[] {
    if (boxes.length < 3) return boxes.map(() => ({ x: 0, y: 0 }));
    const lo = (b: Box) => (horizontal ? b.minX : b.minY), size = (b: Box) => (horizontal ? boxW(b) : boxH(b));
    const order = boxes.map((_, i) => i).sort((a, b) => lo(boxes[a]) - lo(boxes[b]));
    const first = boxes[order[0]];
    let end = -Infinity, sum = 0;
    for (const i of order) end = Math.max(end, lo(boxes[i]) + size(boxes[i]));
    for (const b of boxes) sum += size(b);
    const gap = (end - lo(first) - sum) / (boxes.length - 1);
    const out: Pt[] = new Array(boxes.length);
    let at = lo(first);
    for (const i of order) {
      const d = at - lo(boxes[i]);
      out[i] = horizontal ? { x: d, y: 0 } : { x: 0, y: d };
      at += size(boxes[i]) + gap;
    }
    return out;
  },
};

export type RasterBooleanOp = 'UNION' | 'SUBTRACT' | 'INTERSECT';
/** Android-Verfahren auf 0,1-mm-Raster. Für exakte Kanten: boolean.ts (clipper). */
export const Booleans = {
  apply(shapes: Poly[][], op: RasterBooleanOp, pxPerMm = 10): Poly[] {
    const closed = shapes.map((s) => s.filter((q) => q.length >= 3)).filter((s) => s.length > 0);
    if (closed.length < 2) return closed.flat();
    const box = boundsOf(closed.flat());
    if (!box) return [];
    const bw = boxW(box), bh = boxH(box);
    const p = Math.min(pxPerMm, 3000 / Math.max(Math.max(bw, bh), 1));
    const m = 2, x0 = box.minX - m, y0 = box.minY - m;
    const w = Math.ceil((bw + 2 * m) * p) + 1, h = Math.ceil((bh + 2 * m) * p) + 1;
    const masks = closed.map((s) => Contour.rasterize(s, x0, y0, w, h, p));
    const out = new Uint8Array(w * h);
    for (let i = 0; i < out.length; i++) {
      if (op === 'UNION') { for (const q of masks) if (q[i]) { out[i] = 1; break; } }
      else if (op === 'SUBTRACT') { let v = masks[0][i]; for (let k = 1; v && k < masks.length; k++) if (masks[k][i]) v = 0; out[i] = v; }
      else { let v = 1; for (const q of masks) if (!q[i]) { v = 0; break; } out[i] = v; }
    }
    return Contour.fromMask(new Mask(w, h, out, p, x0, y0), 0, 0, false, 0.05);
  },
};

function slice(poly: Poly, from: number, to: number, len: number): Poly {
  const at = (s0: number): Pt => {
    let s = s0 % len;
    for (let i = 1; i < poly.length; i++) {
      const a = poly[i - 1], b = poly[i], d = dist(a, b);
      if (s <= d && d > 0) return { x: a.x + (b.x - a.x) * s / d, y: a.y + (b.y - a.y) * s / d };
      s -= d;
    }
    return poly[poly.length - 1];
  };
  const out: Pt[] = [at(from)];
  let s = 0;
  const verts: [number, Pt][] = [];
  for (let i = 1; i < poly.length; i++) { s += dist(poly[i - 1], poly[i]); verts.push([s, poly[i]]); }
  for (let lap = 0; lap <= 1; lap++) for (const [sv, v] of verts) {
    const t = sv + lap * len;
    if (t > from && t < to) out.push(v);
  }
  out.push(at(to));
  return out;
}
export const Tabs = {
  /** Geschlossene Pfade bekommen count Lücken der Breite widthMm; offene oder zu kurze bleiben. */
  apply(polys: Poly[], count: number, widthMm: number): Poly[] {
    return polys.flatMap((poly) => {
      const len = polyLength(poly);
      if (!polyClosed(poly) || count < 1 || widthMm <= 0 || len < count * widthMm * 3) return [poly];
      const step = len / count, out: Poly[] = [];
      for (let k = 0; k < count; k++) out.push(slice(poly, (k + 0.5) * step + widthMm / 2, (k + 1.5) * step - widthMm / 2, len));
      return out;
    });
  },
};

export const SHELF_GAP = 5;
const MARGIN = 1;
/** Regal-Packung, höchste zuerst, Reihen von oben links. Verschiebung je Box oder null. */
export function shelf(boxes: Box[], w: number, h: number, gap = SHELF_GAP): (Pt | null)[] {
  const out: (Pt | null)[] = boxes.map(() => null);
  let x = MARGIN, y = MARGIN, rowH = 0;
  const order = boxes.map((_, i) => i).sort((a, b) => boxH(boxes[b]) - boxH(boxes[a]));
  for (const i of order) {
    const b = boxes[i], bw = boxW(b), bh = boxH(b);
    if (bw > w - 2 * MARGIN || bh > h - 2 * MARGIN) continue;
    let px = x, py = y, newRow = false;
    if (px + bw > w - MARGIN) { px = MARGIN; py = y + rowH + gap; newRow = true; }
    if (py + bh > h - MARGIN) continue;
    out[i] = { x: px - b.minX, y: py - b.minY };
    x = px + bw + gap;
    if (newRow) { y = py; rowH = bh; } else rowH = Math.max(rowH, bh);
  }
  return out;
}

export const Nest = {
  /** Platte und Verschiebung je Box; null = zu groß oder zu viele Platten. */
  place(boxes: Box[], w = Bed.width, h = Bed.height, maxPlates = 20): ({ plate: number; offset: Pt } | null)[] {
    const out: ({ plate: number; offset: Pt } | null)[] = boxes.map(() => null);
    let rest = boxes.map((_, i) => i).filter((i) => boxW(boxes[i]) <= w - 2 && boxH(boxes[i]) <= h - 2);
    let plate = 0;
    while (rest.length > 0 && plate < maxPlates) {
      const packed = shelf(rest.map((i) => boxes[i]), w, h);
      rest.forEach((i, k) => { const o = packed[k]; if (o) out[i] = { plate, offset: o }; });
      rest = rest.filter((_, k) => packed[k] == null);
      plate++;
    }
    return out;
  },
};

export interface BoxSpec { w: number; d: number; h: number; t: number; finger: number; closed?: boolean }
export const BoxMaker = {
  /** Ungerade Anzahl Stücke, je etwa finger lang. */
  segments(len: number, finger: number): number {
    let n = Math.floor(len / finger);
    if (n % 2 === 0) n -= 1;
    return Math.max(1, n);
  },
  /** Teile als geschlossene Linien mit Namen, Ursprung oben links je Teil. */
  panels(s: BoxSpec): [string, Poly][] {
    if (!(s.t > 0 && s.finger > 0 && Math.min(s.w, Math.min(s.d, s.h)) > 4 * s.t)) throw new Error('Box zu klein für diese Materialstärke');
    const bottom = panel(s.w, s.d, s.t, s.finger, 'AAAA');
    const top = s.closed ? 'B' : 'F';
    const front = panel(s.w, s.h, s.t, s.finger, top + 'A' + 'B' + 'A');
    const side = panel(s.d, s.h, s.t, s.finger, top + 'B' + 'B' + 'B');
    const list: [string, Poly][] = [['Boden', bottom], ['Vorne', front], ['Hinten', front], ['Links', side], ['Rechts', side]];
    if (s.closed) list.push(['Deckel', bottom]);
    return list;
  },
};
function panel(w: number, h: number, t: number, finger: number, kinds: string): Poly {
  const corners: Pt[] = [{ x: 0, y: 0 }, { x: w, y: 0 }, { x: w, y: h }, { x: 0, y: h }];
  const dirs: Pt[] = [{ x: 1, y: 0 }, { x: 0, y: 1 }, { x: -1, y: 0 }, { x: 0, y: -1 }];
  const normals: Pt[] = [{ x: 0, y: 1 }, { x: -1, y: 0 }, { x: 0, y: -1 }, { x: 1, y: 0 }];
  const lengths = [w, h, w, h];
  const offsets = [0, 1, 2, 3].map((e) => {
    if (kinds[e] === 'F') return [0];
    const n = BoxMaker.segments(lengths[e], finger);
    return Array.from({ length: n }, (_, i) => ((i % 2 === 0) === (kinds[e] === 'A') ? 0 : t));
  });
  const out: Pt[] = [];
  for (let e = 0; e < 4; e++) {
    const p = corners[e], u = dirs[e], v = normals[e], d = offsets[e], prev = offsets[(e + 3) % 4];
    const pt = (a: number, off: number): Pt => ({ x: p.x + u.x * a + v.x * off, y: p.y + u.y * a + v.y * off });
    out.push(pt(prev[prev.length - 1], d[0]));
    const seg = lengths[e] / d.length;
    for (let k = 1; k < d.length; k++) { out.push(pt(seg * k, d[k - 1])); out.push(pt(seg * k, d[k])); }
  }
  out.push(out[0]);
  return out.filter((q, i) => i === 0 || dist(q, out[i - 1]) > 1e-9);
}
