/** Port von Create.kt: Formen, Catmull-Rom, Personalisierung (Anhänger, Emblem, Rahmen, Lineal, Puzzle). */
import { Contour } from './contour';
import { ArcText, ShapeLib } from './extras';
import { dist, Shapes } from './geometry';
import { boundsOf, boxCenter, boxH, boxW, type Box, type Poly, type Pt } from './model';
import { Booleans } from './tools';

export type ShapeKind = 'STAR' | 'HEART' | 'ARROW' | 'BUBBLE' | 'CROSS' | 'DROP';

function fitBox(poly: Poly, w: number, h: number): Poly {
  const b = boundsOf([poly]);
  if (!b) return poly;
  return poly.map((p) => ({ x: (p.x - b.minX) / Math.max(boxW(b), 1e-9) * w, y: (p.y - b.minY) / Math.max(boxH(b), 1e-9) * h }));
}
const P = (x: number, y: number): Pt => ({ x, y });

export function makeShape(kind: ShapeKind, w: number, h: number): Poly {
  switch (kind) {
    case 'STAR': return fitBox(ShapeLib.star(5, w, h), w, h);
    case 'HEART': return fitBox(ShapeLib.heart(w, h), w, h);
    case 'ARROW': return fitBox([P(0, h * .3), P(w * .6, h * .3), P(w * .6, 0), P(w, h / 2), P(w * .6, h), P(w * .6, h * .7), P(0, h * .7), P(0, h * .3)], w, h);
    case 'CROSS': {
      const a = w / 3, b = h / 3;
      return fitBox([P(a, 0), P(2 * a, 0), P(2 * a, b), P(w, b), P(w, 2 * b), P(2 * a, 2 * b), P(2 * a, h), P(a, h), P(a, 2 * b), P(0, 2 * b), P(0, b), P(a, b), P(a, 0)], w, h);
    }
    case 'BUBBLE': {
      const body = Shapes.rect(w, h * .78, Math.min(w, h * .78) * .25);
      const tail = [P(w * .18, h * .7), P(w * .12, h), P(w * .42, h * .7)];
      const res = Booleans.apply([[body], [[...tail, tail[0]]]], 'UNION');
      let best: Poly | null = null, bestA = -Infinity;
      for (const q of res) { const b = boundsOf([q])!, a = boxW(b) * boxH(b); if (a > bestA) { bestA = a; best = q; } }
      return fitBox(best ?? body, w, h);
    }
    default: {
      const out: Poly = [];
      for (let k = 0; k <= 120; k++) { const t = 2 * Math.PI * k / 120; out.push(P(w / 2 + w / 2 * Math.sin(t) * Math.sin(t / 2), h - h * (1 + Math.cos(t)) / 2)); }
      return fitBox(out, w, h);
    }
  }
}

export const Curves = {
  /** Glatte Kurve durch getippte Punkte. */
  catmullRom(points: Pt[], closed: boolean, steps = 12): Poly {
    if (points.length < 3) return closed && points.length >= 2 ? [...points, points[0]] : points;
    const p = closed ? points : [points[0], ...points, points[points.length - 1]];
    const n = p.length, spans = closed ? n : n - 3;
    const out: Pt[] = [];
    for (let i = 0; i < spans; i++) {
      const p0 = closed ? p[(i + n - 1) % n] : p[i];
      const p1 = closed ? p[i] : p[i + 1];
      const p2 = closed ? p[(i + 1) % n] : p[i + 2];
      const p3 = closed ? p[(i + 2) % n] : p[i + 3];
      for (let s = 0; s < steps; s++) {
        const t = s / steps, t2 = t * t, t3 = t2 * t;
        const c = (a: number, b: number, cc: number, d: number) => 0.5 * (2 * b + (-a + cc) * t + (2 * a - 5 * b + 4 * cc - d) * t2 + (-a + 3 * b - 3 * cc + d) * t3);
        out.push(P(c(p0.x, p1.x, p2.x, p3.x), c(p0.y, p1.y, p2.y, p3.y)));
      }
    }
    out.push(closed ? out[0] : points[points.length - 1]);
    return out;
  },
};

export interface Parts { engrave: Poly[]; cut: Poly[]; marks: Poly[]; labels: [Pt, string][] }
const parts = (engrave: Poly[], cut: Poly[], marks: Poly[] = [], labels: [Pt, string][] = []): Parts => ({ engrave, cut, marks, labels });
/** Dieselben Teile mit der Gesamt-Ecke oben links auf (0, 0). */
export function normalizeParts(q: Parts): Parts {
  const b = boundsOf([...q.engrave, ...q.cut, ...q.marks]);
  if (!b) return q;
  const mv = (l: Poly[]) => l.map((p) => p.map((v) => P(v.x - b.minX, v.y - b.minY)));
  return parts(mv(q.engrave), mv(q.cut), mv(q.marks), q.labels.map(([v, s]) => [P(v.x - b.minX, v.y - b.minY), s] as [Pt, string]));
}

const move = (l: Poly[], dx: number, dy: number) => l.map((p) => p.map((v) => P(v.x + dx, v.y + dy)));
const circle = (cx: number, cy: number, d: number) => move([Shapes.ellipse(d, d)], cx - d / 2, cy - d / 2)[0];

export type TagStyle = 'KEYCHAIN' | 'PLATE' | 'HEART' | 'ROUND';
export type FrameStyle = 'SIMPLE' | 'ROUNDED' | 'DOUBLE' | 'OVAL' | 'DASHED';

/** Kotlins Random(seed) (XorWow): Puzzle mit gleichem Startwert ergibt dieselben Knöpfe wie Android. */
export class KotlinRandom {
  private x: number; private y: number; private z = 0; private w = 0; private v: number; private addend: number;
  constructor(seed: number) {
    const s1 = seed | 0, s2 = s1 >> 31;
    this.x = s1; this.y = s2; this.v = ~s1; this.addend = (s1 << 10) ^ (s2 >>> 4);
    for (let i = 0; i < 64; i++) this.nextInt();
  }
  nextInt(): number {
    let t = this.x;
    t = t ^ (t >>> 2);
    this.x = this.y; this.y = this.z; this.z = this.w;
    const v0 = this.v;
    this.w = v0;
    t = (t ^ (t << 1)) ^ v0 ^ (v0 << 4);
    this.v = t;
    this.addend = (this.addend + 362437) | 0;
    return (t + this.addend) | 0;
  }
  nextBoolean(): boolean { return this.nextInt() >>> 31 !== 0; }
}

export const Personalize = {
  fitHeight(paths: Poly[], h: number): Poly[] {
    const b = boundsOf(paths);
    if (!b) return paths;
    const k = h / Math.max(boxH(b), 1e-9);
    return paths.map((p) => p.map((v) => P(b.minX + (v.x - b.minX) * k, b.minY + (v.y - b.minY) * k)));
  },
  /** Namensschild: Text wird graviert, Umriss und Loch werden geschnitten. */
  tag(text: Poly[], style: TagStyle, holeMm: number | null): Parts {
    const tb = boundsOf(text);
    if (!tb) return parts([], []);
    const hole = holeMm != null && holeMm > 0 ? holeMm : null;
    const c = boxCenter(tb), tw = boxW(tb), th = boxH(tb);
    let r: Parts;
    switch (style) {
      case 'KEYCHAIN': {
        const m = Math.max(3, th * 0.3);
        let outline = Contour.fromPolys(text, m, 8, true);
        const cut: Poly[] = [];
        if (hole != null) {
          const ring = hole + 6, cx = tb.minX - m - ring / 2 + 2, cy = c.y;
          outline = Booleans.apply([outline, [circle(cx, cy, ring)]], 'UNION');
          cut.push(circle(cx, cy, hole));
        }
        r = parts(text, [...outline, ...cut]);
        break;
      }
      case 'PLATE': {
        const pad = Math.max(4, th * 0.4), extra = hole != null ? hole + 4 : 0;
        const w = tw + 2 * pad + extra, h = th + 2 * pad, x0 = tb.minX - pad - extra, y0 = tb.minY - pad;
        const cut = [move([Shapes.rect(w, h, Math.min(w, h) * 0.25)], x0, y0)[0]];
        if (hole != null) cut.push(circle(x0 + pad / 2 + hole / 2 + 1, c.y, hole));
        r = parts(text, cut);
        break;
      }
      case 'HEART': {
        const w = Math.max(tw * 1.55, th * 3), h = w * 0.9, x0 = c.x - w / 2, y0 = c.y - h * 0.42;
        const cut = [move([ShapeLib.heart(w, h)], x0, y0)[0]];
        if (hole != null) cut.push(circle(x0 + w * 0.27, y0 + h * 0.2, hole));
        r = parts(text, cut);
        break;
      }
      default: {
        const d = Math.max(tw + 2 * Math.max(5, th * 0.5), th * 3) + (hole != null ? hole * 2 : 0);
        const cut = [circle(c.x, c.y, d)];
        if (hole != null) cut.push(circle(c.x, c.y - d / 2 + hole, hole));
        r = parts(text, cut);
      }
    }
    return normalizeParts(r);
  },
  /** Rundes Emblem: Initialen groß, optional Text oben und unten am Rand. Außenkreis geschnitten, Ringe markiert. */
  emblem(initials: Poly[], top: Poly[] | null, bottom: Poly[] | null, diameter: number): Parts {
    const r = diameter / 2, c = P(r, r), arcs = top != null || bottom != null;
    const mid = Personalize.fitHeight(initials, diameter * (arcs ? 0.28 : 0.42));
    const mb = boundsOf(mid);
    const engrave: Poly[] = [];
    if (mb) {
      const k = Math.min(1, (arcs ? diameter * 0.55 : diameter * 0.7) / boxW(mb)), mc = boxCenter(mb);
      for (const p of mid) engrave.push(p.map((v) => P(c.x + (v.x - mc.x) * k, c.y + (v.y - mc.y) * k)));
    }
    const band = diameter * 0.09;
    const arc = (text: Poly[] | null, upper: boolean) => {
      if (!text) return;
      const t = Personalize.fitHeight(text, band), b = boundsOf(t);
      if (!b) return;
      const r0 = upper ? diameter * 0.335 : diameter * 0.425, maxLen = Math.PI * r0 * 0.85, bw = boxW(b);
      const flat = bw > maxLen ? t.map((p) => p.map((v) => P(b.minX + (v.x - b.minX) * maxLen / bw, b.maxY - (b.maxY - v.y) * maxLen / bw))) : t;
      const bent = ArcText.bend(flat, upper ? r0 : -r0);
      engrave.push(...(upper ? move(bent, c.x, c.y - r0) : move(bent, c.x, c.y + r0)));
    };
    arc(top, true); arc(bottom, false);
    const marks = [circle(c.x, c.y, diameter - 6)];
    if (arcs) marks.push(circle(c.x, c.y, diameter * 0.62));
    return parts(engrave, [circle(c.x, c.y, diameter)], marks);
  },
  /** Rahmen mit Abstand um box. */
  frame(box: Box, style: FrameStyle, marginMm: number): Poly[] {
    const x = box.minX - marginMm, y = box.minY - marginMm, w = boxW(box) + 2 * marginMm, h = boxH(box) + 2 * marginMm;
    const rect = (dx: number, r: number) => move([Shapes.rect(w + 2 * dx, h + 2 * dx, r)], x - dx, y - dx)[0];
    switch (style) {
      case 'SIMPLE': return [rect(0, 0)];
      case 'ROUNDED': return [rect(0, Math.min(w, h) * 0.12)];
      case 'DOUBLE': return [rect(0, 0), rect(2.5, 0)];
      case 'OVAL': {
        const ew = boxW(box) * 1.4142 + 2 * marginMm, eh = boxH(box) * 1.4142 + 2 * marginMm, c = boxCenter(box);
        return move([Shapes.ellipse(ew, eh)], c.x - ew / 2, c.y - eh / 2);
      }
      default: return Personalize.dashes(rect(0, 0), 4, 2.5);
    }
  },
  /** Stücke von dash mm mit gap mm dazwischen. */
  dashes(poly: Poly, dash: number, gap: number): Poly[] {
    const out: Poly[] = [];
    let cur: Pt[] = [poly[0]], on = true, left = dash;
    for (let i = 1; i < poly.length; i++) {
      const a = poly[i - 1], b = poly[i], total = dist(a, b);
      let from = a, segLeft = total;
      while (segLeft > 1e-9) {
        const step = Math.min(segLeft, left), k = step / total;
        const to = P(from.x + (b.x - a.x) * k, from.y + (b.y - a.y) * k);
        if (on) cur.push(to);
        from = to; segLeft -= step; left -= step;
        if (left <= 1e-9) {
          if (on && cur.length > 1) out.push(cur);
          on = !on; left = on ? dash : gap;
          cur = [from];
        }
      }
    }
    if (on && cur.length > 1) out.push(cur);
    return out;
  },
  /** Lineal: Umriss (schneiden), Striche (markieren), Positionen der cm-Zahlen. */
  ruler(lengthMm: number, widthMm: number, holeMm: number | null): Parts {
    const x0 = 5, w = lengthMm + 2 * x0 + (holeMm != null ? holeMm + 4 : 0);
    const cut = [Shapes.rect(w, widthMm, 2)];
    if (holeMm != null) cut.push(circle(w - x0 / 2 - holeMm / 2 - 1, widthMm / 2, holeMm));
    const marks: Poly[] = [], labels: [Pt, string][] = [];
    for (let i = 0; i <= lengthMm; i++) {
      const len = i % 10 === 0 ? widthMm * 0.42 : i % 5 === 0 ? widthMm * 0.3 : widthMm * 0.18;
      marks.push([P(x0 + i, 0), P(x0 + i, len)]);
      if (i % 10 === 0) labels.push([P(x0 + i, widthMm * 0.42 + 1.5), String(Math.trunc(i / 10))]);
    }
    return parts([], cut, marks, labels);
  },
  /** Puzzle: Umriss plus innere Schnittlinien mit Knöpfen. */
  puzzle(w: number, h: number, cols: number, rows: number, seed = 7): Poly[] {
    const rnd = new KotlinRandom(seed);
    const profile = [[0, 0], [0.34, 0], [0.40, 0.02], [0.38, 0.10], [0.35, 0.18], [0.40, 0.25], [0.50, 0.27], [0.60, 0.25], [0.65, 0.18], [0.62, 0.10], [0.60, 0.02], [0.66, 0], [1, 0]];
    const cw = w / cols, ch = h / rows, knob = Math.min(cw, ch);
    const edge = (a: Pt, b: Pt): Poly => {
      const sign = rnd.nextBoolean() ? 1 : -1, dx = b.x - a.x, dy = b.y - a.y, nx = -dy / dist(a, b), ny = dx / dist(a, b);
      return Curves.catmullRom(profile.map(([u, v]) => P(a.x + dx * u + nx * v * knob * sign, a.y + dy * u + ny * v * knob * sign)), false, 8);
    };
    const out: Poly[] = [Shapes.rect(w, h)];
    for (let i = 1; i < cols; i++) {
      const line: Pt[] = [];
      for (let j = 0; j < rows; j++) { const e = edge(P(i * cw, j * ch), P(i * cw, (j + 1) * ch)); line.push(...(line.length === 0 ? e : e.slice(1))); }
      out.push(line);
    }
    for (let j = 1; j < rows; j++) {
      const line: Pt[] = [];
      for (let i = 0; i < cols; i++) { const e = edge(P(i * cw, j * ch), P((i + 1) * cw, j * ch)); line.push(...(line.length === 0 ? e : e.slice(1))); }
      out.push(line);
    }
    return out;
  },
};
