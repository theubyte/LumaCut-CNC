import { Limits, type Poly } from '../model';
import { movePoly, movePolys, Shapes } from '../import/geom';
import type { TextShaper } from './text';
import { GenError, type GenLayer, type GenPart, type GenResult } from './types';

/** Test grid power against speed, every field on its own layer. Port of MaterialTest in Frame.kt. */
export interface MatGridSpec {
  powerFrom: number; powerTo: number; powerSteps: number;
  speedFrom: number; speedTo: number; speedSteps: number;
  mode: 'FILL' | 'LINE'; cellMm: number; gapMm: number; passes: number; intervalMm: number;
}
const PALETTE = [0xFF4FD8B4, 0xFF6CB6FF, 0xFFFFB45C, 0xFFB98CFF, 0xFFFF8AD8, 0xFF9BE15D];
export const steps = (from: number, to: number, n: number) => n <= 1 ? [from] : Array.from({ length: n }, (_, i) => from + (to - from) * i / (n - 1));

export function matGridResult(s: MatGridSpec, shape: TextShaper): GenResult {
  if (!(s.powerSteps >= 1 && s.powerSteps <= 10 && s.speedSteps >= 1 && s.speedSteps <= 10)) throw new GenError('Höchstens 10 × 10 Felder.');
  if (Math.min(s.powerFrom, s.powerTo) < Limits.MIN_RELIABLE_POWER_PCT) throw new GenError(`Unter ${Limits.MIN_RELIABLE_POWER_PCT} % zündet der Laser nicht sicher. Untere Leistung anheben.`);
  if (Math.max(s.powerFrom, s.powerTo) > 100) throw new GenError('Leistung höchstens 100 %.');
  if (Math.min(s.speedFrom, s.speedTo) < 10 || Math.max(s.speedFrom, s.speedTo) > Limits.SPEED[1]) throw new GenError(`Tempo 10 bis ${Limits.SPEED[1]} mm/min.`);
  const powers = steps(s.powerFrom, s.powerTo, s.powerSteps), speeds = steps(s.speedFrom, s.speedTo, s.speedSteps);
  const labelH = 3, left = 24, top = labelH + 5.5, pitch = s.cellMm + s.gapMm;
  const labels: Poly[] = [];
  const place = (t: string, x: number, y: number, right = false) => {
    const g = shape(t, labelH);
    if (!g.length) return;
    let maxX = 0; for (const p of g) for (const q of p) if (q.x > maxX) maxX = q.x;
    labels.push(...movePolys(g, right ? x - maxX : x, y));
  };
  place('mm/min', left - 3, 0, true);
  powers.forEach((p, i) => place(`${Math.trunc(p)} %`, left + i * pitch, 0));
  speeds.forEach((v, j) => place(String(Math.trunc(v)), left - 3, top + j * pitch + s.cellMm / 2 - labelH / 2, true));
  const layers: GenLayer[] = [{ key: 'beschriftung', name: 'Beschriftung', base: 'Linie', color: 0xFF8A93A8, over: { mode: 'FILL', powerPct: 20, speed: 1500, intervalMm: 0.1 } }];
  const parts: GenPart[] = [{ name: 'Beschriftung', layer: 'beschriftung', paths: labels, group: 'test' }];
  speeds.forEach((v, j) => powers.forEach((p, i) => {
    const key = `f${i}-${j}`;
    layers.push({ key, name: `${Math.trunc(p)} % · ${Math.trunc(v)} mm/min`, base: 'Gravieren', color: PALETTE[(i + j) % PALETTE.length],
      over: { mode: s.mode, powerPct: p, speed: v, passes: s.passes, intervalMm: s.intervalMm, minPowerPct: 0 } });
    parts.push({ name: 'Testfeld', layer: key, group: 'test', paths: [movePoly(Shapes.rect(s.cellMm, s.cellMm), left + i * pitch, top + j * pitch)] });
  }));
  const w = left + s.powerSteps * pitch - s.gapMm, h = top + s.speedSteps * pitch - s.gapMm;
  return {
    parts, layers,
    notes: [`${s.powerSteps * s.speedSteps} Felder, zusammen ${Math.ceil(w)} × ${Math.ceil(h)} mm. Jedes Feld hat eine eigene Ebene mit seinen Werten.`],
    warnings: ['Nur auf Material, das sich sicher lasern lässt. Kunststoff zuerst prüfen: PVC und Vinyl gar nicht.'],
  };
}
