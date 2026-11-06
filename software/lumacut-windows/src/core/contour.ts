/** Port von Contour.kt: Umrisse über Abstandsfeld und Marching Squares. Ergebnis nur Polylinien. */
import { dist, polyClosed, simplify } from './geometry';
import { boundsOf, type Poly, type Pt } from './model';

export const DEFAULT_PX_PER_MM = 6;
const SIMPLIFY_MM = 0.05;
const fround = Math.fround;

export class Mask {
  w: number; h: number; data: Uint8Array; pxPerMm: number; x0: number; y0: number;
  constructor(w: number, h: number, data: Uint8Array, pxPerMm: number, x0 = 0, y0 = 0) {
    if (data.length !== w * h) throw new Error('Ungültige Maske');
    this.w = w; this.h = h; this.data = data; this.pxPerMm = pxPerMm; this.x0 = x0; this.y0 = y0;
  }
  get count() { let n = 0; for (let i = 0; i < this.data.length; i++) n += this.data[i]; return n; }

  /** Durchsichtige Pixel und alles, was mit dem Bildrand verbunden und randfarben ist, ist Hintergrund. argb wie Android. */
  static fromArgb(argb: Int32Array | Uint32Array, w: number, h: number, widthMm: number, heightMm: number, pxPerMm = DEFAULT_PX_PER_MM, tolerance = 40): Mask {
    if (argb.length !== w * h || !(w > 0 && h > 0)) throw new Error('Ungültige Bilddaten');
    const bg = background(argb, w, h, tolerance);
    const p = Math.min(pxPerMm, Math.min(3000 / widthMm, 3000 / heightMm));
    const gw = Math.max(1, Math.ceil(widthMm * p)), gh = Math.max(1, Math.ceil(heightMm * p));
    const out = new Uint8Array(gw * gh);
    for (let gy = 0; gy < gh; gy++) {
      const sy = Math.min(h - 1, Math.trunc((gy + 0.5) / gh * h));
      for (let gx = 0; gx < gw; gx++) {
        const sx = Math.min(w - 1, Math.trunc((gx + 0.5) / gw * w));
        out[gy * gw + gx] = bg[sy * w + sx] ? 0 : 1;
      }
    }
    return new Mask(gw, gh, out, gw / widthMm, 0, 0);
  }
  static fromRgba(rgba: Uint8ClampedArray | Uint8Array, w: number, h: number, widthMm: number, heightMm: number, pxPerMm = DEFAULT_PX_PER_MM, tolerance = 40): Mask {
    const argb = new Uint32Array(w * h);
    for (let i = 0, p = 0; i < argb.length; i++, p += 4) argb[i] = ((rgba[p + 3] << 24) | (rgba[p] << 16) | (rgba[p + 1] << 8) | rgba[p + 2]) >>> 0;
    return Mask.fromArgb(argb, w, h, widthMm, heightMm, pxPerMm, tolerance);
  }

  /** Jedes eingeschlossene Loch wird Teil des Motivs. */
  filled(): Mask {
    const { w, h, data } = this;
    const outside = new Uint8Array(w * h), queue = new Int32Array(w * h);
    let head = 0, tail = 0;
    const push = (i: number) => { if (!outside[i] && !data[i]) { outside[i] = 1; queue[tail++] = i; } };
    for (let x = 0; x < w; x++) { push(x); push((h - 1) * w + x); }
    for (let y = 0; y < h; y++) { push(y * w); push(y * w + w - 1); }
    while (head < tail) {
      const i = queue[head++], x = i % w, y = Math.trunc(i / w);
      if (x > 0) push(i - 1);
      if (x < w - 1) push(i + 1);
      if (y > 0) push(i - w);
      if (y < h - 1) push(i + w);
    }
    const out = new Uint8Array(w * h);
    for (let i = 0; i < out.length; i++) out[i] = outside[i] ? 0 : 1;
    return new Mask(w, h, out, this.pxPerMm, this.x0, this.y0);
  }
  /** Entfernt getrennte Flecken unter minAreaMm2. */
  withoutSpecks(minAreaMm2: number): Mask {
    const { w, h, data } = this;
    const minPx = Math.trunc(minAreaMm2 * this.pxPerMm * this.pxPerMm);
    if (minPx <= 1) return this;
    const seen = new Uint8Array(w * h), keep = new Uint8Array(w * h), queue = new Int32Array(w * h);
    for (let start = 0; start < w * h; start++) {
      if (!data[start] || seen[start]) continue;
      let head = 0, tail = 0;
      queue[tail++] = start; seen[start] = 1;
      const go = (j: number) => { if (data[j] && !seen[j]) { seen[j] = 1; queue[tail++] = j; } };
      while (head < tail) {
        const i = queue[head++], x = i % w, y = Math.trunc(i / w);
        if (x > 0) go(i - 1);
        if (x < w - 1) go(i + 1);
        if (y > 0) go(i - w);
        if (y < h - 1) go(i + w);
      }
      if (tail >= minPx) for (let k = 0; k < tail; k++) keep[queue[k]] = 1;
    }
    return new Mask(w, h, keep, this.pxPerMm, this.x0, this.y0);
  }
}

function background(argb: Int32Array | Uint32Array, w: number, h: number, tol: number): Uint8Array {
  const a = (c: number) => (c >>> 24) & 255, r = (c: number) => (c >>> 16) & 255, g = (c: number) => (c >>> 8) & 255, b = (c: number) => c & 255;
  const bins = new Map<number, { e: number[]; order: number }>();
  const border = (i: number) => {
    const c = argb[i];
    if (a(c) < 128) return;
    const key = ((r(c) >> 4) << 8) | ((g(c) >> 4) << 4) | (b(c) >> 4);
    let v = bins.get(key);
    if (!v) { v = { e: [0, 0, 0, 0], order: bins.size }; bins.set(key, v); }
    v.e[0]++; v.e[1] += r(c); v.e[2] += g(c); v.e[3] += b(c);
  };
  for (let x = 0; x < w; x++) { border(x); border((h - 1) * w + x); }
  for (let y = 1; y < h - 1; y++) { border(y * w); border(y * w + w - 1); }
  // Gleichstand wie bei Javas HashMap: Reihenfolge nach Bucket, dann nach Einfügen.
  let table = 16;
  while (bins.size > table * 0.75) table *= 2;
  const entries = [...bins.entries()].sort((p, q) => (p[0] & (table - 1)) - (q[0] & (table - 1)) || p[1].order - q[1].order);
  let top: number[] | null = null;
  for (const [, v] of entries) if (!top || v.e[0] > top[0]) top = v.e;
  const rr = top ? Math.trunc(top[1] / top[0]) : -1, rg = top ? Math.trunc(top[2] / top[0]) : -1, rb = top ? Math.trunc(top[3] / top[0]) : -1;
  const similar = (c: number) => {
    if (a(c) < 128) return true;
    if (!top) return false;
    return Math.abs(r(c) - rr) <= tol && Math.abs(g(c) - rg) <= tol && Math.abs(b(c) - rb) <= tol;
  };
  const bg = new Uint8Array(w * h), queue = new Int32Array(w * h);
  let head = 0, tail = 0;
  const push = (i: number) => { if (!bg[i] && similar(argb[i])) { bg[i] = 1; queue[tail++] = i; } };
  for (let x = 0; x < w; x++) { push(x); push((h - 1) * w + x); }
  for (let y = 0; y < h; y++) { push(y * w); push(y * w + w - 1); }
  while (head < tail) {
    const i = queue[head++], x = i % w, y = Math.trunc(i / w);
    if (x > 0) push(i - 1);
    if (x < w - 1) push(i + 1);
    if (y > 0) push(i - w);
    if (y < h - 1) push(i + w);
  }
  return bg;
}

/** Euklidischer Abstand zum nächsten gesetzten Pixel (Felzenszwalb-Huttenlocher). */
function edt(feature: Uint8Array, w: number, h: number): Float32Array {
  const inf = 1e10, far = 1e20;
  const sq = new Float64Array(w * h);
  for (let i = 0; i < sq.length; i++) sq[i] = feature[i] ? 0 : inf;
  const n = Math.max(w, h);
  const f = new Float64Array(n), d = new Float64Array(n), v = new Int32Array(n), z = new Float64Array(n + 1);
  const line = (len: number) => {
    let k = 0;
    v[0] = 0; z[0] = -far; z[1] = far;
    for (let q = 1; q < len; q++) {
      let s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]);
      while (s <= z[k]) { k--; s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]); }
      k++; v[k] = q; z[k] = s; z[k + 1] = far;
    }
    k = 0;
    for (let q = 0; q < len; q++) {
      while (z[k + 1] < q) k++;
      d[q] = (q - v[k]) * (q - v[k]) + f[v[k]];
    }
  };
  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) f[y] = sq[y * w + x];
    line(h);
    for (let y = 0; y < h; y++) sq[y * w + x] = d[y];
  }
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) f[x] = sq[y * w + x];
    line(w);
    for (let x = 0; x < w; x++) sq[y * w + x] = d[x];
  }
  const out = new Float32Array(w * h);
  for (let i = 0; i < out.length; i++) out[i] = Math.sqrt(Math.min(sq[i], inf));
  return out;
}

function sdf(m: Mask, pad: number): Float32Array {
  const w = m.w + 2 * pad, h = m.h + 2 * pad;
  const fg = new Uint8Array(w * h);
  for (let y = 0; y < m.h; y++) for (let x = 0; x < m.w; x++) fg[(y + pad) * w + x + pad] = m.data[y * m.w + x];
  const toFg = edt(fg, w, h);
  const inv = new Uint8Array(w * h);
  for (let i = 0; i < inv.length; i++) inv[i] = fg[i] ? 0 : 1;
  const toBg = edt(inv, w, h);
  const out = new Float32Array(w * h);
  for (let i = 0; i < out.length; i++) out[i] = fg[i] ? -toBg[i] : toFg[i];
  return out;
}

/** Marching Squares: geschlossene Schleifen (Rasterkoordinaten), wo das Feld iso kreuzt. */
function trace(f: Float32Array, w: number, h: number, iso: number): Pt[][] {
  const k0: number[] = [], k1: number[] = [], px: number[] = [], py: number[] = [];
  const hk = (x: number, y: number) => (y * w + x) * 2, vk = (x: number, y: number) => (y * w + x) * 2 + 1;
  const t = (p: number, q: number) => fround(fround(iso - p) / fround(q - p));
  for (let j = 0; j < h - 1; j++) for (let i = 0; i < w - 1; i++) {
    const a = f[j * w + i], b = f[j * w + i + 1], c = f[(j + 1) * w + i + 1], d = f[(j + 1) * w + i];
    const code = (a < iso ? 1 : 0) | (b < iso ? 2 : 0) | (c < iso ? 4 : 0) | (d < iso ? 8 : 0);
    if (code === 0 || code === 15) continue;
    const key = (e: string) => (e === 'T' ? hk(i, j) : e === 'B' ? hk(i, j + 1) : e === 'L' ? vk(i, j) : vk(i + 1, j));
    const seg = (from: string, to: string) => {
      k0.push(key(from)); k1.push(key(to));
      if (from === 'T') { px.push(i + t(a, b)); py.push(j); }
      else if (from === 'B') { px.push(i + t(d, c)); py.push(j + 1); }
      else if (from === 'L') { px.push(i); py.push(j + t(a, d)); }
      else { px.push(i + 1); py.push(j + t(b, c)); }
    };
    const centreInside = fround(fround(fround(fround(a + b) + c) + d) / 4) < iso;
    switch (code) {
      case 1: seg('T', 'L'); break; case 2: seg('R', 'T'); break; case 4: seg('B', 'R'); break; case 8: seg('L', 'B'); break;
      case 3: seg('R', 'L'); break; case 6: seg('B', 'T'); break; case 12: seg('L', 'R'); break; case 9: seg('T', 'B'); break;
      case 7: seg('B', 'L'); break; case 11: seg('R', 'B'); break; case 13: seg('T', 'R'); break; case 14: seg('L', 'T'); break;
      case 5: if (centreInside) { seg('T', 'R'); seg('B', 'L'); } else { seg('T', 'L'); seg('B', 'R'); } break;
      case 10: if (centreInside) { seg('L', 'T'); seg('R', 'B'); } else { seg('R', 'T'); seg('L', 'B'); } break;
    }
  }
  const byStart = new Map<number, number>();
  for (let i = 0; i < k0.length; i++) byStart.set(k0[i], i);
  const used = new Uint8Array(k0.length);
  const loops: Pt[][] = [];
  for (let first = 0; first < k0.length; first++) {
    if (used[first]) continue;
    const pts: Pt[] = [];
    let cur: number | undefined = first;
    while (cur !== undefined && !used[cur]) {
      used[cur] = 1;
      pts.push({ x: px[cur], y: py[cur] });
      cur = byStart.get(k1[cur]);
    }
    if (pts.length >= 3) { pts.push(pts[0]); loops.push(pts); }
  }
  return loops;
}

export function polyArea(poly: Poly): number {
  let s = 0;
  for (let i = 1; i < poly.length; i++) s += poly[i - 1].x * poly[i].y - poly[i].x * poly[i - 1].y;
  return s / 2;
}

function finish(loops: Pt[][], base: Mask, padPx: number, p: number, outerOnly: boolean, minAreaMm2: number): Poly[] {
  const out: Poly[] = [];
  for (const loop of loops) {
    const n = loop.length - 1, mm: Pt[] = new Array(n + 1);
    for (let i = 0; i < n; i++) {
      const a = loop[(i + n - 1) % n], b = loop[i], c = loop[(i + 1) % n];
      mm[i] = { x: base.x0 + (0.25 * a.x + 0.5 * b.x + 0.25 * c.x - padPx + 0.5) / p, y: base.y0 + (0.25 * a.y + 0.5 * b.y + 0.25 * c.y - padPx + 0.5) / p };
    }
    mm[n] = mm[0];
    const s = simplify(mm, SIMPLIFY_MM);
    if (s.length >= 4 && Math.abs(polyArea(s)) >= minAreaMm2) out.push(dist(s[0], s[s.length - 1]) < 1e-9 ? s : [...s, s[0]]);
  }
  if (!outerOnly || out.length === 0) return out;
  let largest = out[0];
  for (const q of out) if (Math.abs(polyArea(q)) > Math.abs(polyArea(largest))) largest = q;
  const sign = polyArea(largest) > 0;
  return out.filter((q) => polyArea(q) > 0 === sign);
}

export const Contour = {
  /** Geschlossene Umrisse, um offsetMm verschoben (positiv = außen). Lücken bis etwa 2 × closeGapMm werden geschlossen. */
  fromMask(mask: Mask, offsetMm: number, closeGapMm = 0, outerOnly = true, minAreaMm2 = 1): Poly[] {
    const base = outerOnly ? mask.filled() : mask;
    if (base.count === 0) return [];
    const p = base.pxPerMm, gap = Math.max(0, closeGapMm);
    const pad = Math.ceil((Math.max(offsetMm, 0) + gap) * p) + 4;
    let field = sdf(base, pad);
    let pw = base.w + 2 * pad, ph = base.h + 2 * pad;
    if (gap > 0) {
      const limit = (offsetMm + gap) * p;
      const grown = new Uint8Array(pw * ph);
      for (let i = 0; i < grown.length; i++) grown[i] = field[i] <= limit ? 1 : 0;
      let gm = new Mask(pw, ph, grown, p);
      if (outerOnly) gm = gm.filled();
      field = sdf(gm, 4); pw += 8; ph += 8;
      return finish(trace(field, pw, ph, fround(-gap * p)), base, pad + 4, p, outerOnly, minAreaMm2);
    }
    return finish(trace(field, pw, ph, fround(offsetMm * p)), base, pad, p, outerOnly, minAreaMm2);
  },
  /** Umrisse geschlossener Formen (even-odd, Löcher bleiben, außer outerOnly). */
  fromPolys(polys: Poly[], offsetMm: number, pxPerMm = 8, outerOnly = false): Poly[] {
    const closed = polys.filter((q) => q.length >= 3);
    const box = boundsOf(closed);
    if (!box) return [];
    const bw = box.maxX - box.minX, bh = box.maxY - box.minY;
    const p = Math.min(pxPerMm, 3000 / Math.max(Math.max(bw, bh), 1));
    const m = 2, x0 = box.minX - m, y0 = box.minY - m;
    const w = Math.ceil((bw + 2 * m) * p) + 1, h = Math.ceil((bh + 2 * m) * p) + 1;
    return Contour.fromMask(new Mask(w, h, Contour.rasterize(closed, x0, y0, w, h, p), p, x0, y0), offsetMm, 0, outerOnly, 0);
  },
  /** Even-odd-Füllung auf einem w × h-Raster ab (x0, y0) mm mit p Pixeln je mm. */
  rasterize(polys: Poly[], x0: number, y0: number, w: number, h: number, p: number): Uint8Array {
    const rows: number[][] = Array.from({ length: h }, () => []);
    for (const poly of polys) {
      if (poly.length < 3) continue;
      const pts = polyClosed(poly) ? poly : [...poly, poly[0]];
      for (let e = 1; e < pts.length; e++) {
        const a = pts[e - 1], b = pts[e];
        if (a.y === b.y) continue;
        const ja = Math.max(0, Math.ceil((Math.min(a.y, b.y) - y0) * p - 0.5));
        const jb = Math.min(h - 1, Math.floor((Math.max(a.y, b.y) - y0) * p - 0.5));
        for (let j = ja; j <= jb; j++) {
          const y = y0 + (j + 0.5) / p;
          if ((a.y <= y && b.y > y) || (b.y <= y && a.y > y)) rows[j].push(a.x + (y - a.y) * (b.x - a.x) / (b.y - a.y));
        }
      }
    }
    const data = new Uint8Array(w * h);
    for (let j = 0; j < h; j++) {
      const xs = rows[j];
      xs.sort((u, v) => u - v);
      for (let k = 0; k + 1 < xs.length; k += 2) {
        const i0 = Math.max(0, Math.ceil((xs[k] - x0) * p - 0.5));
        const i1 = Math.min(w - 1, Math.floor((xs[k + 1] - x0) * p - 0.5));
        if (i1 >= i0) data.fill(1, j * w + i0, j * w + i1 + 1);
      }
    }
    return data;
  },
  /** Aufkleber: Umriss außerhalb des Motivs, kleine Lücken geschlossen. */
  sticker(mask: Mask, offsetMm: number, join = false): Poly[] {
    return Contour.fromMask(mask.withoutSpecks(0.5), offsetMm, join ? 8 : 2, true);
  },
  /** Folgt der Kante; insetMm zieht die Linie nach innen. */
  edge(mask: Mask, insetMm = 0): Poly[] {
    return Contour.fromMask(mask.withoutSpecks(0.5), -Math.max(0, insetMm), 0, true);
  },
};
