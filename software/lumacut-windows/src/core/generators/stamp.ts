import type { Poly } from '../model';
import { movePoly, Shapes } from '../import/geom';
import { drop, heart, star } from './shapes';
import { centeredText, fitText, type TextShaper } from './text';
import { GenError, type GenResult } from './types';

/**
 * Rubber stamp: the laser burns everything except letters, motif and border, so they stay raised.
 * The fill rule is even-odd: background outline plus letter contours leaves the letters unburned.
 * Mirrored, so the print reads the right way round.
 */
export type StampMotif = 'none' | 'star' | 'heart' | 'drop';
export type StampShape = 'rect' | 'round';
export interface StampSpec { widthMm: number; heightMm: number; shape: StampShape; lines: string[]; bold: boolean; motif: StampMotif; borderMm: number; inverted: boolean; mirrored: boolean }

const motifPoly = (m: StampMotif, s: number): Poly | null => m === 'star' ? star(5, s, s) : m === 'heart' ? heart(s, s * 0.92) : m === 'drop' ? drop(s * 0.75, s) : null;

export function stampResult(s: StampSpec, shape: TextShaper): GenResult {
  if (!(s.widthMm >= 10 && s.widthMm <= 300 && s.heightMm >= 10 && s.heightMm <= 300)) throw new GenError('Größe: 10 bis 300 mm.');
  const lines = s.lines.map((l) => l.trim()).filter(Boolean);
  if (!lines.length && s.motif === 'none') throw new GenError('Text oder Motiv fehlt.');
  const round = s.shape === 'round';
  const W = s.widthMm, H = round ? s.widthMm : s.heightMm;
  const outline: Poly = round ? Shapes.ellipse(W, W) : Shapes.rect(W, H, 1.5);
  const inset = (d: number): Poly => round ? movePoly(Shapes.ellipse(W - 2 * d, W - 2 * d), d, d) : movePoly(Shapes.rect(W - 2 * d, H - 2 * d, Math.max(0, 1.5 - d / 2)), d, d);
  const pad = 2 + s.borderMm + (s.borderMm > 0 ? 1.5 : 0);
  const ink: Poly[] = [];
  if (s.borderMm > 0) ink.push(inset(1.5), inset(1.5 + s.borderMm));
  // In a circle the corners of the text block must stay inside: use the middle part only.
  const areaW = (W - 2 * pad) * (round ? 0.8 : 1), areaH = (H - 2 * pad) * (round ? 0.72 : 1), areaTop = (H - areaH) / 2;
  let textX = W / 2, textW = areaW, textTop = areaTop, textH = areaH;
  if (s.motif !== 'none') {
    const beside = lines.length > 0 && !round && areaW > areaH * 1.3;
    if (beside) {
      const m = Math.min(areaH * 0.8, areaW * 0.3);
      ink.push(movePoly(motifPoly(s.motif, m)!, pad, H / 2 - m / 2));
      textX = pad + m + 2 + (areaW - m - 2) / 2; textW = areaW - m - 2;
    } else {
      const m = lines.length ? areaH * 0.42 : Math.min(areaH, areaW) * 0.8;
      const pw = s.motif === 'drop' ? m * 0.75 : m;
      ink.push(movePoly(motifPoly(s.motif, m)!, W / 2 - pw / 2, lines.length ? areaTop : H / 2 - m / 2));
      textTop = areaTop + m + 1.5; textH = areaH - m - 1.5;
    }
  }
  if (lines.length) {
    const gap = 0.35;
    let h = textH / (lines.length + (lines.length - 1) * gap);
    for (const l of lines) h = Math.min(h, fitText(shape, l, h, textW, { bold: s.bold }));
    const block = h * lines.length + h * gap * (lines.length - 1);
    const start = textTop + (textH - block) / 2;
    lines.forEach((l, i) => ink.push(...centeredText(shape, l, h, textX, start + i * h * (1 + gap), { bold: s.bold })));
  }
  // Inverted: burn the background. Otherwise: burn the letters themselves.
  const engrave = s.inverted ? [outline, ...ink] : ink;
  const flip = (l: Poly[]) => s.mirrored ? l.map((p) => p.map((q) => ({ x: W - q.x, y: q.y }))) : l;
  const warnings = ['Nur laserfähigen Stempelgummi verwenden, ohne PVC und ohne Chlor. Andere Gummis geben giftige Dämpfe ab.'];
  if (!s.inverted) warnings.push('Nicht invertiert: die Schrift wird vertieft. Das ergibt eine Gravur, keinen Stempel.');
  if (!s.mirrored) warnings.push('Nicht gespiegelt: als Stempel läse sich der Abdruck verkehrt.');
  return { parts: [
    { name: 'Stempel', layer: 'Gravieren', paths: flip(engrave), group: 'stempel' },
    { name: 'Stempel Umriss', layer: 'Schneiden', paths: flip([outline]), group: 'stempel' },
  ], notes: [`Stempelplatte ${W} × ${H} mm.${s.mirrored ? ' Gespiegelt, damit der Abdruck richtig lesbar ist.' : ''}`], warnings };
}
