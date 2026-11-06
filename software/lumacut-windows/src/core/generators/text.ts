import opentype from 'opentype.js';
import { boundsOf, type Poly, type Pt } from '../model';
import { cubicPoints, movePolys } from '../import/geom';

/**
 * Text to closed outlines (mm, y down). The shaper is passed into the generators, so they stay pure:
 * the view loads a font, the tests use a fake one. `capHeightMm` is the height of a capital letter,
 * y = 0 the top of the capitals, x = 0 the start of the text.
 */
export type TextShaper = (text: string, capHeightMm: number, opts?: { bold?: boolean }) => Poly[];

const SEG_MM = 0.12;
export function outlinesOf(font: opentype.Font, text: string, capHeightMm: number): Poly[] {
  const os2 = font.tables.os2 as { sCapHeight?: number } | undefined;
  const capUnits = os2?.sCapHeight || font.unitsPerEm * 0.7;
  const fontSize = capHeightMm * font.unitsPerEm / capUnits;
  const out: Poly[] = [];
  let cur: Pt[] = [];
  for (const c of font.getPath(text, 0, capHeightMm, fontSize).commands) {
    if (c.type === 'M') { if (cur.length >= 2) out.push(cur); cur = [{ x: c.x, y: c.y }]; }
    else if (c.type === 'L') cur.push({ x: c.x, y: c.y });
    else if (c.type === 'C') cur.push(...cubicPoints(cur[cur.length - 1], { x: c.x1, y: c.y1 }, { x: c.x2, y: c.y2 }, { x: c.x, y: c.y }, SEG_MM, 40));
    else if (c.type === 'Q') {
      const p0 = cur[cur.length - 1], q = { x: c.x1, y: c.y1 }, p = { x: c.x, y: c.y };
      cur.push(...cubicPoints(p0, { x: p0.x + (q.x - p0.x) * 2 / 3, y: p0.y + (q.y - p0.y) * 2 / 3 }, { x: p.x + (q.x - p.x) * 2 / 3, y: p.y + (q.y - p.y) * 2 / 3 }, p, SEG_MM, 40));
    } else if (c.type === 'Z') {
      if (cur.length >= 2) { const a = cur[0], b = cur[cur.length - 1]; if (a.x !== b.x || a.y !== b.y) cur.push(a); out.push(cur); }
      cur = [];
    }
  }
  if (cur.length >= 2) out.push(cur);
  return out;
}
export function shaperFromFonts(regular: opentype.Font, bold?: opentype.Font): TextShaper {
  return (text, h, opts) => text.trim() ? outlinesOf(opts?.bold && bold ? bold : regular, text, h) : [];
}

/** The text with its middle at x = cx and the top of the capitals at `top`. */
export function centeredText(shape: TextShaper, text: string, h: number, cx: number, top: number, opts?: { bold?: boolean }): Poly[] {
  const polys = shape(text, h, opts);
  const b = boundsOf(polys);
  return b ? movePolys(polys, cx - (b.minX + b.maxX) / 2, top) : [];
}
/** Largest cap height up to `h` at which the text is at most `maxW` wide. */
export function fitText(shape: TextShaper, text: string, h: number, maxW: number, opts?: { bold?: boolean }): number {
  const b = boundsOf(shape(text, h, opts));
  if (!b) return h;
  const w = b.maxX - b.minX;
  return w > maxW ? h * maxW / w : h;
}
