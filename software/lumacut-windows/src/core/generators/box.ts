import { offsetPolys } from '../boolean';
import { boundsOf, Bed, parkBox, type Poly, type Pt } from '../model';
import { Shapes } from '../import/geom';
import { shelf } from '../import/layout';
import { GenError, type GenPart, type GenResult } from './types';

/** Finger-jointed box. Panels are ports of BoxMaker in Tools.kt; inner/outer sizes, kerf and the loose lid are additions. */
export type BoxLid = 'none' | 'joined' | 'loose';
export interface BoxSpec { w: number; d: number; h: number; t: number; finger: number; lid: BoxLid; inner?: boolean; kerf?: number }

/** Odd number of segments, each about `finger` long. */
export function boxSegments(len: number, finger: number): number {
  let n = Math.floor(len / finger);
  if (n % 2 === 0) n -= 1;
  return Math.max(1, n);
}

/** Rectangle walked clockwise; per edge A = fingers at the ends, B = notches at the ends, F = flat. */
function panel(w: number, h: number, t: number, finger: number, kinds: string): Poly {
  const corners: Pt[] = [{ x: 0, y: 0 }, { x: w, y: 0 }, { x: w, y: h }, { x: 0, y: h }];
  const dirs: Pt[] = [{ x: 1, y: 0 }, { x: 0, y: 1 }, { x: -1, y: 0 }, { x: 0, y: -1 }];
  const normals: Pt[] = [{ x: 0, y: 1 }, { x: -1, y: 0 }, { x: 0, y: -1 }, { x: 1, y: 0 }];
  const lengths = [w, h, w, h];
  const offsets = [0, 1, 2, 3].map((e) => {
    if (kinds[e] === 'F') return [0];
    const n = boxSegments(lengths[e], finger);
    return Array.from({ length: n }, (_, i) => (i % 2 === 0) === (kinds[e] === 'A') ? 0 : t);
  });
  const out: Pt[] = [];
  for (let e = 0; e < 4; e++) {
    const p = corners[e], u = dirs[e], v = normals[e], d = offsets[e], prev = offsets[(e + 3) % 4], prevLast = prev[prev.length - 1];
    const pt = (a: number, off: number): Pt => ({ x: p.x + u.x * a + v.x * off, y: p.y + u.y * a + v.y * off });
    out.push(pt(prevLast, d[0]));
    const seg = lengths[e] / d.length;
    for (let k = 1; k < d.length; k++) { out.push(pt(seg * k, d[k - 1])); out.push(pt(seg * k, d[k])); }
  }
  out.push(out[0]);
  return out.filter((q, i) => i === 0 || Math.hypot(q.x - out[i - 1].x, q.y - out[i - 1].y) > 1e-9);
}

/** Outer size from the spec. Inner size: walls add twice the material, the height the floor and a joined lid. */
export function boxOuter(s: BoxSpec) {
  if (!s.inner) return { w: s.w, d: s.d, h: s.h };
  return { w: s.w + 2 * s.t, d: s.d + 2 * s.t, h: s.h + (s.lid === 'joined' ? 2 : 1) * s.t };
}

export function boxPanels(s: BoxSpec): { name: string; poly: Poly }[] {
  const { w, d, h } = boxOuter(s);
  if (!(s.t > 0 && s.finger > 0 && Math.min(w, d, h) > 4 * s.t)) throw new GenError('Die Box ist zu klein für diese Materialstärke.');
  const bottom = panel(w, d, s.t, s.finger, 'AAAA');
  const top = s.lid === 'joined' ? 'B' : 'F';
  const front = panel(w, h, s.t, s.finger, top + 'ABA');
  const side = panel(d, h, s.t, s.finger, top + 'BBB');
  const list = [{ name: 'Boden', poly: bottom }, { name: 'Vorne', poly: front }, { name: 'Hinten', poly: front }, { name: 'Links', poly: side }, { name: 'Rechts', poly: side }];
  if (s.lid === 'joined') list.push({ name: 'Deckel', poly: bottom });
  if (s.lid === 'loose') {
    list.push({ name: 'Deckel', poly: Shapes.rect(w, d) });
    list.push({ name: 'Deckel-Einsatz', poly: Shapes.rect(w - 2 * s.t - 0.6, d - 2 * s.t - 0.6) });
  }
  return list;
}

const fmt = (v: number) => String(+v.toFixed(1)).replace('.', ',');

export function boxResult(s: BoxSpec, plateW = Bed.width, plateH = Bed.height): GenResult {
  const kerf = s.kerf ?? 0;
  const panels = boxPanels(s).map((p) => ({ name: p.name, polys: kerf > 0 ? offsetPolys([p.poly], kerf / 2, 'miter') : [p.poly] }));
  const boxes = panels.map((p) => boundsOf(p.polys)!);
  const parts: GenPart[] = [];
  let rest = boxes.map((_, i) => i), plate = 0;
  while (rest.length && plate < 20) {
    const packed = shelf(rest.map((i) => boxes[i]), plateW, plateH, 5, parkBox());
    const next: number[] = [];
    rest.forEach((i, k) => {
      const o = packed[k];
      if (!o) { next.push(i); return; }
      parts.push({ name: panels[i].name, layer: 'Schneiden', plate, group: 'box', paths: panels[i].polys.map((poly) => poly.map((q) => ({ x: q.x + o.x, y: q.y + o.y }))) });
    });
    if (next.length === rest.length) throw new GenError(`Das Teil „${panels[next[0]].name}“ ist größer als eine Platte.`);
    rest = next; plate++;
  }
  const o = boxOuter(s);
  const notes = [`Außenmaße ${fmt(o.w)} × ${fmt(o.d)} × ${fmt(o.h)} mm, ${parts.length} Teile${plate > 1 ? ` auf ${plate} Platten` : ''}.`,
    'Materialstärke genau messen: davon hängt die Passung ab.'];
  return { parts, notes, placement: 'keep' };
}
