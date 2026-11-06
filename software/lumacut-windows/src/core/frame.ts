/** Port von Frame.kt: Rahmenfahrt ohne Laser (Pi op=frame) und Materialtest. */
import { fmt3 } from './fmt';
import { Shapes } from './geometry';
import { Bed, boundsOf, newElement, newLayer, type Doc, type Element, type Layer, type LayerMode, type Poly, type Pt } from './model';
import type { CompactToolpath, Toolpath } from './toolpath';

export type FrameMode = 'box' | 'hull';
const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v);

/** Andrews Monotone Chain, gegen den Uhrzeigersinn, ohne wiederholten Endpunkt. */
export function convexHull(points: Pt[]): Pt[] {
  const sorted = points.slice().sort((a, b) => a.x - b.x || a.y - b.y);
  const pts: Pt[] = [];
  for (const p of sorted) { const q = pts[pts.length - 1]; if (!q || q.x !== p.x || q.y !== p.y) pts.push(p); }
  if (pts.length < 3) return pts;
  const cross = (o: Pt, a: Pt, b: Pt) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lower: Pt[] = [], upper: Pt[] = [];
  for (const p of pts) { while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop(); lower.push(p); }
  for (let i = pts.length - 1; i >= 0; i--) { const p = pts[i]; while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop(); upper.push(p); }
  lower.pop(); upper.pop();
  return lower.concat(upper);
}

/** Nur G21/G90/M5 I und absolute G0: das akzeptiert frame_program() auf dem Pi. Punkte in Maschinen-mm. */
export function frameProgram(points: Pt[], mode: FrameMode, feed = 3000): string {
  if (points.length === 0) throw new Error('Kein Motiv für den Rahmen');
  let outline: Pt[];
  if (mode === 'box') {
    const b = boundsOf([points])!;
    outline = [{ x: b.minX, y: b.minY }, { x: b.maxX, y: b.minY }, { x: b.maxX, y: b.maxY }, { x: b.minX, y: b.maxY }];
  } else outline = convexHull(points);
  const f = clamp(Math.trunc(feed), 300, 9000);
  const out = ['G21', 'G90', 'M5 I'];
  for (const p of [...outline, outline[0]]) out.push(`G0 X${fmt3(clamp(p.x, 0, Bed.width))} Y${fmt3(clamp(p.y, 0, Bed.height))} F${f}`);
  out.push('');
  return out.join('\n');
}

/** Punkte, an denen wirklich gebrannt wird (Maschinen-mm), in 32-Bit-Genauigkeit wie Android. */
export function framePoints(tp: CompactToolpath | Toolpath): Pt[] {
  const out: Pt[] = [];
  if ('segments' in tp) {
    for (const s of tp.segments) if (s.cut) out.push({ x: s.x0, y: s.y0 }, { x: s.x1, y: s.y1 });
    return out;
  }
  for (let i = 0; i < tp.count; i++) if (tp.power[i] > 0) {
    const o = i * 4;
    out.push({ x: tp.xy[o], y: tp.xy[o + 1] }, { x: tp.xy[o + 2], y: tp.xy[o + 3] });
  }
  return out;
}

export interface MaterialTestSpec {
  powerFrom?: number; powerTo?: number; powerSteps?: number; speedFrom?: number; speedTo?: number; speedSteps?: number;
  mode?: LayerMode; cellMm?: number; gapMm?: number; passes?: number; intervalMm?: number; originX?: number; originY?: number;
}
const PALETTE = [0xFF4FD8B4, 0xFF6CB6FF, 0xFFFFB45C, 0xFFB98CFF, 0xFFFF8AD8, 0xFF9BE15D];
export const testSteps = (from: number, to: number, n: number) =>
  n <= 1 ? [from] : Array.from({ length: n }, (_, i) => from + (to - from) * i / (n - 1));

/** Raster Leistung × Tempo, eine Ebene je Feld; `label` wandelt Text in Umrisse. */
export function buildMaterialTest(spec: MaterialTestSpec, label: (text: string, heightMm: number) => Poly[]): Doc {
  const s = { powerFrom: 20, powerTo: 100, powerSteps: 5, speedFrom: 300, speedTo: 3000, speedSteps: 5, mode: 'FILL' as LayerMode,
    cellMm: 10, gapMm: 4, passes: 1, intervalMm: 0.1, originX: 10, originY: 10, ...spec };
  if (!(s.powerSteps >= 1 && s.powerSteps <= 10 && s.speedSteps >= 1 && s.speedSteps <= 10)) throw new Error('Höchstens 10 × 10 Felder');
  if (!(s.powerFrom >= 0 && s.powerFrom <= 100 && s.powerTo >= 0 && s.powerTo <= 100)) throw new Error('Leistung 0–100 %');
  if (!(s.speedFrom >= 10 && s.speedFrom <= 30000 && s.speedTo >= 10 && s.speedTo <= 30000)) throw new Error('Tempo 10–30000 mm/min');
  const powers = testSteps(s.powerFrom, s.powerTo, s.powerSteps), speeds = testSteps(s.speedFrom, s.speedTo, s.speedSteps);
  const labelH = 3, left = s.originX + 14, top = s.originY + labelH + 3, pitch = s.cellMm + s.gapMm;
  const text = newLayer('Beschriftung', 0xFFEEF3F8, 'LINE', { powerPct: 20, speed: 1500 });
  const layers: Layer[] = [], elements: Element[] = [];
  const place = (t: string, x: number, y: number) => {
    const g = label(t, labelH), b = boundsOf(g);
    if (!b) return;
    elements.push(newElement(text.id, 'Beschriftung', { text: t, transform: { x, y, scaleX: 1, scaleY: 1, rotation: 0 },
      paths: g.map((p) => p.map((q) => ({ x: q.x - b.minX, y: q.y - b.minY }))) }));
  };
  powers.forEach((p, i) => place(`${Math.trunc(p)}%`, left + i * pitch, s.originY));
  speeds.forEach((v, j) => place(`${Math.trunc(v)}`, s.originX, top + j * pitch + s.cellMm / 2 - labelH / 2));
  speeds.forEach((v, j) => powers.forEach((p, i) => {
    const layer = newLayer(`${Math.trunc(p)} % · ${Math.trunc(v)} mm/min`, PALETTE[(i + j) % PALETTE.length], s.mode, { powerPct: p, speed: v, passes: s.passes, intervalMm: s.intervalMm });
    layers.push(layer);
    elements.push(newElement(layer.id, 'Testfeld', { transform: { x: left + i * pitch, y: top + j * pitch, scaleX: 1, scaleY: 1, rotation: 0 }, paths: [Shapes.rect(s.cellMm, s.cellMm)] }));
  }));
  return { title: 'Materialtest', layers: [text, ...layers], elements, plateCount: 1, activePlate: 0 };
}
