import { boundsOf, isClosed, type Box, type Poly, type Pt } from '../model';

/** 2D affine matrix (a b c d e f) as in SVG. Port of `Matrix` in SvgImport.kt. */
export interface Matrix { a: number; b: number; c: number; d: number; e: number; f: number }
export const IDENTITY_M: Matrix = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 };
export const mat = (a = 1, b = 0, c = 0, d = 1, e = 0, f = 0): Matrix => ({ a, b, c, d, e, f });
export const mul = (m: Matrix, o: Matrix): Matrix => ({
  a: m.a * o.a + m.c * o.b, b: m.b * o.a + m.d * o.b,
  c: m.a * o.c + m.c * o.d, d: m.b * o.c + m.d * o.d,
  e: m.a * o.e + m.c * o.f + m.e, f: m.b * o.e + m.d * o.f + m.f,
});
export const applyM = (m: Matrix, p: Pt): Pt => ({ x: m.a * p.x + m.c * p.y + m.e, y: m.b * p.x + m.d * p.y + m.f });

export const dist = (a: Pt, b: Pt) => Math.hypot(a.x - b.x, a.y - b.y);
export const movePoly = (p: Poly, dx: number, dy: number): Poly => p.map((q) => ({ x: q.x + dx, y: q.y + dy }));
export const movePolys = (l: Poly[], dx: number, dy: number): Poly[] => l.map((p) => movePoly(p, dx, dy));

/** Closed outlines with the origin at the top-left of their box. Same point layout as `Shapes` in Geometry.kt. */
export const Shapes = {
  rect(w: number, h: number, radius = 0): Poly {
    if (radius <= 0) return [{ x: 0, y: 0 }, { x: w, y: 0 }, { x: w, y: h }, { x: 0, y: h }, { x: 0, y: 0 }];
    const r = Math.min(radius, Math.min(w, h) / 2);
    const out: Pt[] = [];
    const arc = (cx: number, cy: number, from: number) => {
      for (let k = 0; k <= 8; k++) {
        const a = (from + 90 * k / 8) * Math.PI / 180;
        out.push({ x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) });
      }
    };
    arc(w - r, r, 270); arc(w - r, h - r, 0); arc(r, h - r, 90); arc(r, r, 180);
    out.push(out[0]);
    return out;
  },
  ellipse(w: number, h: number, segmentMm = 0.4): Poly {
    const rx = w / 2, ry = h / 2;
    const n = Math.max(24, Math.trunc(Math.PI * (rx + ry) / segmentMm));
    const out: Pt[] = [];
    for (let k = 0; k <= n; k++) { const a = 2 * Math.PI * k / n; out.push({ x: rx + rx * Math.cos(a), y: ry + ry * Math.sin(a) }); }
    out[n] = out[0];
    return out;
  },
};

/** Cubic Bézier without its start point, flattened with chords of about `segMm`. */
export function cubicPoints(p0: Pt, c1: Pt, c2: Pt, p1: Pt, segMm: number, maxN = 400): Pt[] {
  const approx = dist(p0, c1) + dist(c1, c2) + dist(c2, p1);
  const n = Math.min(maxN, Math.max(2, Math.ceil(approx / segMm)));
  const out: Pt[] = [];
  for (let k = 1; k <= n; k++) {
    const t = k / n, u = 1 - t;
    out.push({
      x: u * u * u * p0.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * p1.x,
      y: u * u * u * p0.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * p1.y,
    });
  }
  return out;
}

export { boundsOf, isClosed };
export type { Box, Poly, Pt };

/** Standard base64 with whitespace allowed and an optional data-URL prefix; null when broken or too short to be a file. */
export function decodeBase64Loose(text: string): Uint8Array | null {
  try {
    const i = text.indexOf('base64,');
    const clean = (i >= 0 ? text.slice(i + 7) : text).replace(/\s+/g, '');
    const bin = atob(clean);
    if (bin.length <= 8) return null;
    const out = new Uint8Array(bin.length);
    for (let k = 0; k < bin.length; k++) out[k] = bin.charCodeAt(k);
    return out;
  } catch { return null; }
}

/** Bytes to text; honours a BOM and the encoding of an XML declaration. */
export function decodeText(bytes: Uint8Array): string {
  if (bytes[0] === 0xFF && bytes[1] === 0xFE) return new TextDecoder('utf-16le').decode(bytes);
  if (bytes[0] === 0xFE && bytes[1] === 0xFF) return new TextDecoder('utf-16be').decode(bytes);
  const head = new TextDecoder('latin1').decode(bytes.subarray(0, 120));
  const m = /^\s*<\?xml[^>]*encoding=["']([^"']+)["']/i.exec(head);
  try { return new TextDecoder(m ? m[1].toLowerCase() : 'utf-8').decode(bytes).replace(/^﻿/, ''); }
  catch { return new TextDecoder('utf-8').decode(bytes).replace(/^﻿/, ''); }
}
