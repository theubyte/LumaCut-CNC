import { booleanOp } from '../boolean';
import type { Poly } from '../model';
import { movePoly, Shapes } from '../import/geom';
import { centeredText, fitText, type TextShaper } from './text';
import { GenError, type GenResult } from './types';

/** Built-in motifs, generated here: no third-party graphics. All are cut outline plus engraved or marked content. */
export type TemplateKind = 'schild' | 'untersetzer' | 'anhaenger' | 'etikett';
export const TEMPLATE_LABEL: Record<TemplateKind, string> = { schild: 'Namensschild', untersetzer: 'Untersetzer', anhaenger: 'Schlüsselanhänger', etikett: 'Kisten-Etikett' };
export interface TemplateSpec { kind: TemplateKind; text: string; second: string; widthMm: number; heightMm: number }
const circle = (cx: number, cy: number, d: number) => movePoly(Shapes.ellipse(d, d), cx - d / 2, cy - d / 2);

export function templateResult(s: TemplateSpec, shape: TextShaper): GenResult {
  if (!s.text.trim()) throw new GenError('Text fehlt.');
  if (!(s.widthMm >= 15 && s.widthMm <= 340 && s.heightMm >= 8 && s.heightMm <= 340)) throw new GenError('Maße: mindestens 15 × 8 mm, höchstens 340 mm.');
  return { schild, untersetzer, anhaenger, etikett }[s.kind](s, shape);
}

function schild(s: TemplateSpec, shape: TextShaper): GenResult {
  const W = s.widthMm, H = s.heightMm, pad = Math.min(W, H) * 0.14, second = s.second.trim();
  const h1 = fitText(shape, s.text, H * (second ? 0.32 : 0.42), W - 2 * pad, { bold: true });
  const h2 = second ? fitText(shape, second, H * 0.15, W - 2 * pad) : 0;
  const gap = second ? H * 0.08 : 0, top = (H - h1 - gap - h2) / 2;
  const text = centeredText(shape, s.text, h1, W / 2, top, { bold: true });
  if (second) text.push(...centeredText(shape, second, h2, W / 2, top + h1 + gap));
  return { parts: [
    { name: 'Name', layer: 'Gravieren', group: 'v', paths: text },
    { name: 'Zierlinie', layer: 'Linie', group: 'v', paths: [movePoly(Shapes.rect(W - 6, H - 6, Math.min(W, H) * 0.08), 3, 3)] },
    { name: 'Umriss', layer: 'Schneiden', group: 'v', paths: [Shapes.rect(W, H, Math.min(W, H) * 0.12)] },
  ], notes: ['Name graviert, Zierlinie markiert, Umriss geschnitten.'] };
}

function untersetzer(s: TemplateSpec, shape: TextShaper): GenResult {
  const D = s.widthMm, c = D / 2, second = s.second.trim();
  if (!(D >= 40 && D <= 200)) throw new GenError('Durchmesser: 40 bis 200 mm.');
  const pattern: Poly[] = [circle(c, c, D - 8), circle(c, c, D * 0.62)];
  for (let i = 0; i < 36; i++) {
    const a = 2 * Math.PI * i / 36, r0 = D * 0.33, r1 = D / 2 - 6;
    pattern.push([{ x: c + r0 * Math.cos(a), y: c + r0 * Math.sin(a) }, { x: c + r1 * Math.cos(a), y: c + r1 * Math.sin(a) }]);
  }
  const room = D * 0.5;
  const h1 = fitText(shape, s.text, D * 0.13, room, { bold: true }), h2 = second ? fitText(shape, second, D * 0.05, room) : 0;
  const gap = second ? D * 0.03 : 0, top = c - (h1 + gap + h2) / 2;
  const text = centeredText(shape, s.text, h1, c, top, { bold: true });
  if (second) text.push(...centeredText(shape, second, h2, c, top + h1 + gap));
  return { parts: [
    { name: 'Text', layer: 'Gravieren', group: 'v', paths: text },
    { name: 'Muster', layer: 'Linie', group: 'v', paths: pattern },
    { name: 'Umriss', layer: 'Schneiden', group: 'v', paths: [Shapes.ellipse(D, D)] },
  ], notes: [`Untersetzer ${D} mm. Für Holz oder Filz; heiße Tassen hinterlassen auf Acryl Spuren.`] };
}

function anhaenger(s: TemplateSpec, shape: TextShaper): GenResult {
  const W = s.widthMm, H = s.heightMm, hole = 4, tab = hole + 6;
  const body = Shapes.rect(W, H, H * 0.28);
  const merged = booleanOp('union', [body], [circle(0, H / 2, tab)]);
  const h = fitText(shape, s.text, H * 0.45, W - 8, { bold: true });
  return { parts: [
    { name: 'Name', layer: 'Gravieren', group: 'v', paths: centeredText(shape, s.text, h, W / 2 + 1, H / 2 - h / 2, { bold: true }) },
    { name: 'Umriss', layer: 'Schneiden', group: 'v', paths: [...(merged.length ? merged : [body]), circle(0, H / 2, hole)] },
  ], notes: ['Mit Loch 4 mm für den Ring. Innere Konturen werden vor dem Umriss geschnitten.'] };
}

function etikett(s: TemplateSpec, shape: TextShaper): GenResult {
  const W = s.widthMm, H = s.heightMm, head = H * 0.34, hole = 3.5, free = H - head - 6, rows = 2;
  const text = centeredText(shape, s.text, fitText(shape, s.text, head * 0.55, W - 20, { bold: true }), W / 2, head * 0.22, { bold: true });
  const lines: Poly[] = [[{ x: 3, y: head }, { x: W - 3, y: head }]];
  for (let i = 1; i <= rows; i++) { const y = head + free * i / (rows + 0.2); lines.push([{ x: 8, y }, { x: W - 8, y }]); }
  if (s.second.trim()) {
    const h = fitText(shape, s.second, free * 0.16, W - 20);
    text.push(...centeredText(shape, s.second, h, W / 2, head + free / (rows + 0.2) - h - 2.5));
  }
  return { parts: [
    { name: 'Titel', layer: 'Gravieren', group: 'v', paths: text },
    { name: 'Linien', layer: 'Linie', group: 'v', paths: lines },
    { name: 'Umriss', layer: 'Schneiden', group: 'v', paths: [Shapes.rect(W, H, 2), circle(5, 5, hole), circle(W - 5, 5, hole), circle(5, H - 5, hole), circle(W - 5, H - 5, hole)] },
  ], notes: ['Vier Löcher zum Annageln. Die freien Linien sind zum Beschriften von Hand.'] };
}
