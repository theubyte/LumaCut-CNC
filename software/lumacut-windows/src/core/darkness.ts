/** Port von Darkness.kt und Layer.powerShare/focusDropMm aus Design.kt. */
import { fmtFixed } from './fmt';
import type { DarknessCurve, Layer } from './model';

export const RELIABLE_POWER_PCT = 8;
export const SPEED_FLOOR = 300;
const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v);

export const focusDropMm = (l: Pick<Layer, 'zStepMm' | 'passes'>) => l.zStepMm * (l.passes - 1);

/** Anteil der Leistung für relative Dunkelheit (0 = weiß, 1 = schwarz) über die Tonkurve. */
export function powerShare(l: Pick<Layer, 'toneCurve'>, dark: number): number {
  const d = clamp(dark, 0, 1), tc = l.toneCurve ?? [];
  if (tc.length < 2) return d;
  const x = d * (tc.length - 1), i = Math.min(Math.trunc(x), tc.length - 2);
  return clamp(tc[i] + (tc[i + 1] - tc[i]) * (x - i), 0, 1);
}

const minP = (c: DarknessCurve) => c.min_power_pct ?? RELIABLE_POWER_PCT;
const intervalOf = (c: DarknessCurve) => c.interval_mm ?? 0.1;
const speedMinOf = (c: DarknessCurve) => c.speed_min ?? 1500;
const speedMaxOf = (c: DarknessCurve) => c.speed_max ?? 6000;

/** (ln Energie, Ton) nach Energie, der Ton fällt nie. */
function curveOf(c: DarknessCurve): [number, number][] {
  let top = 0;
  return (c.points ?? []).filter((p) => p.power > 0 && p.speed > 0)
    .sort((a, b) => a.power / a.speed - b.power / b.speed)
    .map((p) => { top = Math.max(top, p.tone); return [Math.log(p.power / p.speed), top] as [number, number]; });
}
export function curveUsable(c: DarknessCurve): boolean {
  const k = curveOf(c);
  return k.length >= 2 && k[k.length - 1][1] > k[0][1];
}
export function toneRange(c: DarknessCurve): [number, number] {
  const k = curveOf(c);
  return [k[0][1], k[k.length - 1][1]];
}
/** Ton für die Energie je Fläche; auf den gemessenen Bereich begrenzt. */
export function curveTone(c: DarknessCurve, energy: number): number {
  const k = curveOf(c), x = Math.log(energy);
  if (x <= k[0][0]) return k[0][1];
  if (x >= k[k.length - 1][0]) return k[k.length - 1][1];
  let i = -1;
  for (let j = k.length - 1; j >= 0; j--) if (k[j][0] <= x) { i = j; break; }
  i = Math.min(i, k.length - 2);
  const [x0, t0] = k[i], [x1, t1] = k[i + 1];
  return x1 - x0 < 1e-9 ? t1 : t0 + (t1 - t0) * (x - x0) / (x1 - x0);
}
export function curveEnergyFor(c: DarknessCurve, tone: number): number {
  const k = curveOf(c), t = clamp(tone, k[0][1], k[k.length - 1][1]);
  const i = Math.max(k.findIndex((e) => e[1] >= t), 1);
  const [x0, t0] = k[i - 1], [x1, t1] = k[i];
  return Math.exp(t1 - t0 < 1e-9 ? x0 : x0 + (x1 - x0) * (t - t0) / (t1 - t0));
}

export interface DarknessResult { layer: Layer; limit: string | null }
const minPower = (l: Layer) => (l.darkness ? minP(l.darkness) : RELIABLE_POWER_PCT);

export const Darkness = {
  speedRange(l: Layer, maxFeed: number): [number, number] {
    const ratio = l.powerPct / l.speed, c = l.darkness;
    const lo = Math.max(minPower(l) / ratio, c ? speedMinOf(c) : SPEED_FLOOR);
    const hi = Math.min(100 / ratio, c ? speedMaxOf(c) : maxFeed, maxFeed);
    return lo <= hi ? [lo, hi] : [hi, hi];
  },
  atSpeed(l: Layer, speed: number, maxFeed: number): DarknessResult {
    const [lo, hi] = Darkness.speedRange(l, maxFeed), v = clamp(speed, lo, hi);
    let limit: string | null = null;
    if (speed < lo - 0.5) limit = l.powerPct * lo / l.speed <= minPower(l) + 0.05
      ? `Langsamer geht nicht: der Laser zündet unter ${fmtFixed(minPower(l), 0)} % nicht sicher.` : 'Langsamer ist nicht kalibriert.';
    else if (speed > hi + 0.5) limit = 'Schneller geht nicht.';
    return { layer: { ...l, speed: v, powerPct: l.powerPct * v / l.speed }, limit };
  },
  speedPosition(l: Layer, maxFeed: number): number {
    const [lo, hi] = Darkness.speedRange(l, maxFeed);
    if (hi - lo < 1) return 0.5;
    return clamp(Math.log(l.speed / lo) / Math.log(hi / lo), 0, 1);
  },
  speedAt(l: Layer, position: number, maxFeed: number): number {
    const [lo, hi] = Darkness.speedRange(l, maxFeed);
    return lo * Math.exp(clamp(position, 0, 1) * Math.log(hi / lo));
  },
  /** Ton der Ebene; null ohne Kurve oder bei Linien. */
  tone(l: Layer): number | null {
    const c = l.darkness;
    if (!c || !curveUsable(c) || l.mode !== 'FILL') return null;
    return curveTone(c, l.powerPct / l.speed * intervalOf(c) / l.intervalMm);
  },
  atTone(l: Layer, tone: number, maxFeed: number): DarknessResult {
    const c = l.darkness;
    if (!c || !curveUsable(c) || l.mode !== 'FILL') return { layer: l, limit: 'Für diese Ebene gibt es keine Schwärze-Kurve.' };
    const ratio = curveEnergyFor(c, tone) * l.intervalMm / intervalOf(c);
    let v = l.speed, limit: string | null = null;
    if (ratio * v < minP(c)) v = minP(c) / ratio;
    if (ratio * v > 100) v = 100 / ratio;
    if (v > maxFeed) { v = maxFeed; limit = `Heller geht nicht: der Laser zündet unter ${fmtFixed(minP(c), 0)} % nicht sicher und ist schon am schnellsten.`; }
    const p = clamp(ratio * v, minP(c), 100);
    const [a, b] = toneRange(c);
    if (limit == null && !(tone >= a && tone <= b)) limit = `Außerhalb der gemessenen Töne (${fmtFixed(a, 2, ',')}–${fmtFixed(b, 2, ',')}).`;
    return { layer: { ...l, speed: v, powerPct: p }, limit };
  },
};
