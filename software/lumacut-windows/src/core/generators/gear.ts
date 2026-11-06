import { offsetPolys } from '../boolean';
import type { Poly, Pt } from '../model';
import { movePoly, Shapes } from '../import/geom';
import { GenError, type GenResult } from './types';

/** Involute spur gear, own implementation. No undercut correction: under 17 teeth the root is a plain radial line. */
export interface GearSpec { module: number; teeth: number; pressureDeg: number; boreMm: number; kerf?: number }
const inv = (a: number) => Math.tan(a) - a;

export function gearDims(s: GearSpec) {
  const pitch = s.module * s.teeth;
  return { pitch, outer: pitch + 2 * s.module, root: pitch - 2.5 * s.module, base: pitch * Math.cos(s.pressureDeg * Math.PI / 180) };
}

/** Closed outline, gear centre at (outer/2, outer/2), one tooth pointing up. */
export function gearOutline(s: GearSpec): Poly {
  const z = s.teeth, a = s.pressureDeg * Math.PI / 180, d = gearDims(s);
  const ra = d.outer / 2, rf = d.root / 2, rb = d.base / 2;
  const halfAt = (r: number) => Math.PI / (2 * z) + inv(a) - inv(Math.acos(Math.min(1, rb / r)));
  const polar = (r: number, t: number): Pt => ({ x: ra + r * Math.cos(t), y: ra + r * Math.sin(t) });
  const startR = Math.max(rb, rf), FLANK = 10;
  const rs = Array.from({ length: FLANK + 1 }, (_, i) => startR + (ra - startR) * i / FLANK);
  const pts: Pt[] = [];
  for (let k = 0; k < z; k++) {
    const c = 2 * Math.PI * k / z - Math.PI / 2, atBase = halfAt(startR), tip = halfAt(ra);
    pts.push(polar(rf, c - atBase));
    for (const r of rs) pts.push(polar(r, c - halfAt(r)));
    for (let i = 1; i < 4; i++) pts.push(polar(ra, c - tip + 2 * tip * i / 4));
    for (const r of [...rs].reverse()) pts.push(polar(r, c + halfAt(r)));
    pts.push(polar(rf, c + atBase));
    const next = c + 2 * Math.PI / z - atBase;
    for (let i = 1; i < 4; i++) pts.push(polar(rf, c + atBase + (next - c - atBase) * i / 4));
  }
  pts.push(pts[0]);
  return pts.filter((q, i) => i === 0 || Math.hypot(q.x - pts[i - 1].x, q.y - pts[i - 1].y) > 1e-6);
}

export function gearResult(s: GearSpec): GenResult {
  if (!(s.teeth >= 6 && s.teeth <= 200 && Number.isInteger(s.teeth))) throw new GenError('Zähne: ganze Zahl von 6 bis 200.');
  if (!(s.module >= 0.5 && s.module <= 20)) throw new GenError('Modul: 0,5 bis 20 mm.');
  const d = gearDims(s), kerf = s.kerf ?? 0;
  if (d.root <= 0) throw new GenError('Für dieses Modul sind es zu wenige Zähne.');
  if (s.boreMm >= d.root - 2) throw new GenError('Die Bohrung ist größer als der Zahnfuß.');
  const outline = gearOutline(s);
  const paths: Poly[] = kerf > 0 ? offsetPolys([outline], kerf / 2, 'round') : [outline];
  if (s.boreMm > 0) {
    const b = Math.max(0.2, s.boreMm - kerf);
    paths.push(movePoly(Shapes.ellipse(b, b), d.outer / 2 - b / 2, d.outer / 2 - b / 2));
  }
  const n = (v: number) => String(+v.toFixed(2)).replace('.', ',');
  return {
    parts: [{ name: 'Zahnrad', layer: 'Schneiden', paths }],
    notes: [`Teilkreis ${n(d.pitch)} mm, außen ${n(d.outer)} mm, Fuß ${n(d.root)} mm.`, `Achsabstand zu einem Rad mit z Zähnen: ${n(s.module)} × (${s.teeth} + z) ÷ 2. Beide Räder brauchen dasselbe Modul.`],
    warnings: s.teeth < 17 ? ['Unter 17 Zähnen fehlt der Unterschnitt-Ausgleich, die Räder können leicht klemmen. Etwas mehr Achsabstand einplanen.'] : [],
  };
}
