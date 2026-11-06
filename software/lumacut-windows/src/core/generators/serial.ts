import { Bed, boundsOf, parkBox, type Box, type Poly } from '../model';
import { movePoly, movePolys, Shapes } from '../import/geom';
import { shelf } from '../import/layout';
import { fitText, type TextShaper } from './text';
import { GenError, type GenPart, type GenResult } from './types';

/** Serial numbers: a template such as `SN-{0001}`; the digits say the start value and the width. */
export interface Template { before: string; after: string; start: number; width: number }
export function parseTemplate(t: string): Template {
  const m = /\{(\d{1,9})\}/.exec(t);
  if (!m) throw new GenError('Die Vorlage braucht einen Platzhalter wie {0001}.');
  return { before: t.slice(0, m.index), after: t.slice(m.index + m[0].length), start: parseInt(m[1], 10), width: m[1].length };
}
export const serialText = (tpl: Template, i: number, step = 1) => tpl.before + String(tpl.start + i * step).padStart(tpl.width, '0') + tpl.after;

export interface SerialSpec {
  template: string; count: number; step?: number; textHeightMm: number;
  /** Plate around each number; 0 x 0 = text only. */
  tagWidthMm: number; tagHeightMm: number; holeMm: number; gapMm: number;
}
export const MAX_SERIALS = 500;

export function serialResult(s: SerialSpec, shape: TextShaper, plateW = Bed.width, plateH = Bed.height): GenResult {
  const tpl = parseTemplate(s.template);
  if (!(s.count >= 1 && s.count <= MAX_SERIALS && Number.isInteger(s.count))) throw new GenError(`Anzahl: 1 bis ${MAX_SERIALS}.`);
  const tagged = s.tagWidthMm > 0 && s.tagHeightMm > 0;
  interface Piece { text: Poly[]; cut: Poly[]; box: Box; name: string }
  const pieces: Piece[] = [];
  for (let i = 0; i < s.count; i++) {
    const label = serialText(tpl, i, s.step ?? 1);
    if (!tagged) {
      const text = shape(label, s.textHeightMm);
      const b = boundsOf(text);
      if (!b) throw new GenError('Die Vorlage ergibt keinen Text.');
      pieces.push({ text, cut: [], box: b, name: label });
    } else {
      const holeSpace = s.holeMm > 0 ? s.holeMm + 3 : 0;
      const h = fitText(shape, label, s.textHeightMm, s.tagWidthMm - holeSpace - 4);
      const raw = shape(label, h);
      const b = boundsOf(raw);
      if (!b) throw new GenError('Die Vorlage ergibt keinen Text.');
      const text = movePolys(raw, holeSpace + (s.tagWidthMm - holeSpace) / 2 - (b.minX + b.maxX) / 2, s.tagHeightMm / 2 - (b.minY + b.maxY) / 2);
      const cut: Poly[] = [Shapes.rect(s.tagWidthMm, s.tagHeightMm, Math.min(s.tagWidthMm, s.tagHeightMm) * 0.15)];
      if (s.holeMm > 0) cut.push(movePoly(Shapes.ellipse(s.holeMm, s.holeMm), 2.5, s.tagHeightMm / 2 - s.holeMm / 2));
      pieces.push({ text, cut, box: { minX: 0, minY: 0, maxX: s.tagWidthMm, maxY: s.tagHeightMm }, name: label });
    }
  }
  const parts: GenPart[] = [];
  let rest = pieces.map((_, i) => i), plate = 0;
  while (rest.length && plate < 50) {
    const packed = shelf(rest.map((i) => pieces[i].box), plateW, plateH, s.gapMm, parkBox());
    const next: number[] = [];
    rest.forEach((i, k) => {
      const o = packed[k], p = pieces[i];
      if (!o) { next.push(i); return; }
      const group = p.cut.length ? `s${i}` : undefined;
      parts.push({ name: p.name, layer: 'Gravieren', plate, group, paths: movePolys(p.text, o.x, o.y) });
      if (p.cut.length) parts.push({ name: `${p.name} Umriss`, layer: 'Schneiden', plate, group, paths: movePolys(p.cut, o.x, o.y) });
    });
    if (next.length === rest.length) throw new GenError('Ein Stück ist größer als eine Platte.');
    rest = next; plate++;
  }
  const first = serialText(tpl, 0, s.step ?? 1), last = serialText(tpl, s.count - 1, s.step ?? 1);
  return { parts, placement: 'keep', notes: [`${first} bis ${last}: ${s.count} Stück ${plate > 1 ? `auf ${plate} Platten` : 'auf einer Platte'}. Die Park-Ecke bleibt frei.`] };
}
