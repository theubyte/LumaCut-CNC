import { boundsOf, type Box, type Poly, type Pt } from '../model';
import { movePoly, Shapes } from '../import/geom';
import { centeredText, fitText, type TextShaper } from './text';
import { GenError, type GenPart, type GenResult } from './types';

const circleAt = (cx: number, cy: number, d: number) => movePoly(Shapes.ellipse(d, d), cx - d / 2, cy - d / 2);
const num = (v: number) => String(+v.toFixed(2)).replace('.', ',');

/** Ruler: outline cut, mm/5 mm/cm ticks marked, cm numbers engraved. Port of Personalize.ruler. */
export interface RulerSpec { lengthMm: number; widthMm: number; holeMm: number; title?: string }
export function rulerResult(s: RulerSpec, shape: TextShaper): GenResult {
  if (!(s.lengthMm >= 30 && s.lengthMm <= 340)) throw new GenError('Messlänge: 30 bis 340 mm.');
  if (!(s.widthMm >= 15 && s.widthMm <= 80)) throw new GenError('Breite: 15 bis 80 mm.');
  const x0 = 5, hole = s.holeMm > 0 ? s.holeMm : 0, len = Math.round(s.lengthMm);
  const w = len + 2 * x0 + (hole ? hole + 4 : 0);
  const cut: Poly[] = [Shapes.rect(w, s.widthMm, 2)];
  if (hole) cut.push(circleAt(w - x0 / 2 - hole / 2 - 1, s.widthMm / 2, hole));
  const ticks: Poly[] = [], numbers: Poly[] = [];
  const numH = Math.min(4, s.widthMm * 0.16);
  for (let i = 0; i <= len; i++) {
    const t = i % 10 === 0 ? s.widthMm * 0.42 : i % 5 === 0 ? s.widthMm * 0.3 : s.widthMm * 0.18;
    ticks.push([{ x: x0 + i, y: 0 }, { x: x0 + i, y: t }]);
    if (i % 10 === 0) numbers.push(...centeredText(shape, String(i / 10), numH, x0 + i, s.widthMm * 0.42 + 1.5));
  }
  const parts: GenPart[] = [
    { name: 'Lineal Umriss', layer: 'Schneiden', paths: cut, group: 'lineal' },
    { name: 'Lineal Striche', layer: 'Linie', paths: ticks, group: 'lineal' },
    { name: 'Lineal Zahlen', layer: 'Gravieren', paths: numbers, group: 'lineal' },
  ];
  if (s.title?.trim()) {
    const h = fitText(shape, s.title, Math.min(5, s.widthMm * 0.2), len - 4);
    parts.push({ name: 'Lineal Text', layer: 'Gravieren', paths: centeredText(shape, s.title, h, x0 + len / 2, s.widthMm - h - 2), group: 'lineal' });
  }
  return { parts, notes: [`Gesamtlänge ${w} mm. Striche werden markiert, Zahlen graviert, der Umriss geschnitten.`] };
}

/** Scale bar for a plan: alternating filled fields, real lengths as labels. */
export interface ScaleBarSpec { scale: number; realLengthM: number; segments: number; heightMm: number }
export function scaleBarResult(s: ScaleBarSpec, shape: TextShaper): GenResult {
  if (!(s.scale >= 1 && s.scale <= 100000)) throw new GenError('Maßstab: 1 bis 100 000.');
  if (!(s.segments >= 1 && s.segments <= 20 && Number.isInteger(s.segments))) throw new GenError('Felder: 1 bis 20.');
  const lengthMm = s.realLengthM * 1000 / s.scale;
  if (!(lengthMm >= 5 && lengthMm <= 340)) throw new GenError(`Der Balken wäre ${Math.round(lengthMm)} mm lang: Länge oder Maßstab ändern (5 bis 340 mm).`);
  const seg = lengthMm / s.segments, h = s.heightMm, numH = Math.max(2.2, Math.min(4, h)), top = numH + 1.5;
  const fields: Poly[] = [];
  for (let i = 0; i < s.segments; i += 2) fields.push(movePoly(Shapes.rect(seg, h), i * seg, top));
  const labels: Poly[] = [];
  for (let i = 0; i <= s.segments; i++) {
    const v = s.realLengthM * i / s.segments;
    labels.push(...centeredText(shape, i === s.segments ? `${num(v)} m` : num(v), numH, i * seg, 0));
  }
  return { parts: [
    { name: 'Maßstab Felder', layer: 'Gravieren', paths: fields, group: 'massstab' },
    { name: 'Maßstab Rahmen', layer: 'Linie', paths: [movePoly(Shapes.rect(lengthMm, h), 0, top)], group: 'massstab' },
    { name: 'Maßstab Zahlen', layer: 'Gravieren', paths: labels, group: 'massstab' },
    { name: 'Maßstab Text', layer: 'Gravieren', paths: centeredText(shape, `1:${s.scale}`, numH, lengthMm / 2, top + h + 1.5), group: 'massstab' },
  ], notes: [`${num(s.realLengthM)} m im Maßstab 1:${s.scale} sind ${num(lengthMm)} mm auf dem Material.`] };
}

export type FrameStyle = 'SIMPLE' | 'ROUNDED' | 'DOUBLE' | 'OVAL' | 'DASHED';
export const FRAME_LABEL: Record<FrameStyle, string> = { SIMPLE: 'Rechteck', ROUNDED: 'Abgerundet', DOUBLE: 'Doppelt', OVAL: 'Oval', DASHED: 'Gestrichelt' };
/** Frame `margin` mm around `box`. Port of Personalize.frame. */
export function framePolys(box: Box, style: FrameStyle, margin: number): Poly[] {
  const bw = box.maxX - box.minX, bh = box.maxY - box.minY;
  const x = box.minX - margin, y = box.minY - margin, w = bw + 2 * margin, h = bh + 2 * margin;
  const rect = (dx: number, r: number) => movePoly(Shapes.rect(w + 2 * dx, h + 2 * dx, r), x - dx, y - dx);
  switch (style) {
    case 'SIMPLE': return [rect(0, 0)];
    case 'ROUNDED': return [rect(0, Math.min(w, h) * 0.12)];
    case 'DOUBLE': return [rect(0, 0), rect(2.5, 0)];
    case 'OVAL': {
      const ew = bw * 1.4142 + 2 * margin, eh = bh * 1.4142 + 2 * margin;
      return [movePoly(Shapes.ellipse(ew, eh), (box.minX + box.maxX) / 2 - ew / 2, (box.minY + box.maxY) / 2 - eh / 2)];
    }
    case 'DASHED': return dashes(rect(0, 0), 4, 2.5);
  }
}
/** Pieces of `dash` mm with `gap` mm between them along a polyline. */
export function dashes(poly: Poly, dash: number, gap: number): Poly[] {
  const out: Poly[] = [];
  let cur: Pt[] = [poly[0]], on = true, left = dash;
  for (let i = 1; i < poly.length; i++) {
    const a = poly[i - 1], b = poly[i], len = Math.hypot(b.x - a.x, b.y - a.y);
    let from = a, segLeft = len;
    while (segLeft > 1e-9) {
      const step = Math.min(segLeft, left), k = step / len;
      const to = { x: from.x + (b.x - a.x) * k, y: from.y + (b.y - a.y) * k };
      if (on) cur.push(to);
      from = to; segLeft -= step; left -= step;
      if (left <= 1e-9) {
        if (on && cur.length > 1) out.push(cur);
        on = !on; left = on ? dash : gap; cur = [from];
      }
    }
  }
  if (on && cur.length > 1) out.push(cur);
  return out;
}
export interface FrameSpec { around: Box | null; widthMm: number; heightMm: number; style: FrameStyle; marginMm: number; cut: boolean }
export function frameResult(s: FrameSpec): GenResult {
  if (!s.around && !(s.widthMm >= 5 && s.heightMm >= 5)) throw new GenError('Rahmen: mindestens 5 × 5 mm.');
  const box = s.around ?? { minX: 0, minY: 0, maxX: s.widthMm, maxY: s.heightMm };
  const paths = framePolys(box, s.style, s.around ? s.marginMm : 0);
  const b = boundsOf(paths)!;
  return { parts: [{ name: 'Rahmen', layer: s.cut ? 'Schneiden' : 'Linie', paths }], placement: s.around ? 'keep' : 'center',
    notes: [`Rahmen außen ${num(b.maxX - b.minX)} × ${num(b.maxY - b.minY)} mm.`] };
}
