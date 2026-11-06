import { applyM, boundsOf, IDENTITY_M, mat, type Matrix, mul, type Poly, type Pt } from './geom';
import { ImportError } from './types';

/**
 * Port of DxfImport.kt: ASCII DXF to polylines in mm, Y pointing down like the work area.
 * LINE, LWPOLYLINE and POLYLINE (with bulge arcs), CIRCLE, ARC, ELLIPSE, SPLINE and INSERT of blocks.
 * Units from $INSUNITS (none = mm). Everything else is counted, so the operator is told what is missing.
 */
const SEG_MM = 0.25;
const MAX_POINTS = 400_000;
type Pair = [number, string];

class Entity {
  constructor(public type: string, public codes: Pair[]) {}
  d(code: number, dflt = 0) { const c = this.codes.find((p) => p[0] === code); const v = c ? parseFloat(c[1]) : NaN; return Number.isFinite(v) ? v : dflt; }
  i(code: number, dflt = 0) { return Math.trunc(this.d(code, dflt)); }
  s(code: number) { return this.codes.find((p) => p[0] === code)?.[1].trim() ?? null; }
  all(code: number) { return this.codes.filter((p) => p[0] === code).map((p) => parseFloat(p[1])).filter(Number.isFinite); }
}

export interface DxfResult { polys: Poly[]; skipped: string[] }
const IGNORED = new Set(['VERTEX', 'SEQEND', 'POINT', 'VIEWPORT', 'ATTDEF', 'ATTRIB', 'ENDBLK', 'BLOCK', 'SECTION', 'ENDSEC', 'EOF']);

export function parseDxf(bytes: Uint8Array): DxfResult {
  const text = new TextDecoder('utf-8').decode(bytes);
  if (!text) throw new ImportError('Leere Datei');
  if (text.startsWith('AutoCAD Binary DXF')) throw new ImportError('Binäres DXF wird nicht unterstützt, bitte als ASCII-DXF speichern');
  const lines = text.split(/\r?\n/);
  const pairs: Pair[] = [];
  for (let k = 0; k + 1 < lines.length; k += 2) {
    const code = lines[k].trim();
    if (!/^-?\d+$/.test(code)) throw new ImportError('Keine gültige DXF-Datei');
    pairs.push([parseInt(code, 10), lines[k + 1]]);
  }
  let units = 1, section = '', i = 0;
  const blocks = new Map<string, Entity[]>();
  const entities: Entity[] = [];
  let currentBlock: Entity[] | null = null;
  while (i < pairs.length) {
    const [code, value] = pairs[i];
    const v = value.trim();
    if (code === 0 && v === 'SECTION') { section = pairs[i + 1]?.[1].trim() ?? ''; i += 2; continue; }
    if (code === 0 && v === 'ENDSEC') { section = ''; i++; continue; }
    if (section === 'HEADER' && code === 9 && v === '$INSUNITS') {
      units = ({ 1: 25.4, 5: 10, 6: 1000, 2: 304.8 } as Record<number, number>)[parseInt(pairs[i + 1]?.[1] ?? '', 10)] ?? 1;
      i += 2; continue;
    }
    if (code === 0 && (section === 'ENTITIES' || section === 'BLOCKS')) {
      let j = i + 1; const body: Pair[] = [];
      while (j < pairs.length && pairs[j][0] !== 0) body.push(pairs[j++]);
      const e = new Entity(v, body);
      if (section === 'BLOCKS' && v === 'BLOCK') { currentBlock = []; blocks.set(e.s(2) ?? '', currentBlock); }
      else if (section === 'BLOCKS' && v === 'ENDBLK') currentBlock = null;
      else if (section === 'BLOCKS') currentBlock?.push(e);
      else entities.push(e);
      i = j; continue;
    }
    i++;
  }
  const out: Poly[] = [];
  const skipped = new Map<string, number>();
  emit(entities, IDENTITY_M, blocks, out, 0, skipped);
  if (!out.length) throw new ImportError('Keine unterstützten Zeichnungselemente gefunden');
  if (out.reduce((s, p) => s + p.length, 0) > MAX_POINTS) throw new ImportError('DXF zu komplex');
  const scaled = out.map((p) => p.map((q) => ({ x: q.x * units, y: q.y * units })));
  const b = boundsOf(scaled)!;
  return { polys: scaled.map((p) => p.map((q) => ({ x: q.x - b.minX, y: b.maxY - q.y }))), skipped: [...skipped].map(([k, n]) => `${n}× ${k}`) };
}

function emit(list: Entity[], m: Matrix, blocks: Map<string, Entity[]>, out: Poly[], depth: number, skipped: Map<string, number>) {
  if (depth > 8) return;
  for (let idx = 0; idx < list.length; idx++) {
    const e = list[idx];
    let local: Poly[] = [];
    switch (e.type) {
      case 'LINE': local = [[{ x: e.d(10), y: e.d(20) }, { x: e.d(11), y: e.d(21) }]]; break;
      case 'LWPOLYLINE': {
        const pts: [Pt, number][] = [];
        let cur: Pt | null = null, bulge = 0, x: number | null = null;
        for (const [code, value] of e.codes) {
          if (code === 10) { if (cur) pts.push([cur, bulge]); x = parseFloat(value); bulge = 0; cur = null; }
          else if (code === 20) cur = { x: x ?? 0, y: parseFloat(value) };
          else if (code === 42) bulge = parseFloat(value);
        }
        if (cur) pts.push([cur, bulge]);
        local = [bulgePath(pts, (e.i(70) & 1) === 1)];
        break;
      }
      case 'POLYLINE': {
        const pts: [Pt, number][] = [];
        let j = idx + 1;
        while (j < list.length && list[j].type === 'VERTEX') { pts.push([{ x: list[j].d(10), y: list[j].d(20) }, list[j].d(42)]); j++; }
        if (j < list.length && list[j].type === 'SEQEND') j++;
        idx = j - 1;
        local = [bulgePath(pts, (e.i(70) & 1) === 1)];
        break;
      }
      case 'CIRCLE': local = [arc({ x: e.d(10), y: e.d(20) }, e.d(40), 0, 2 * Math.PI)]; break;
      case 'ARC': {
        const a0 = e.d(50) * Math.PI / 180; let a1 = e.d(51) * Math.PI / 180;
        if (a1 <= a0) a1 += 2 * Math.PI;
        local = [arc({ x: e.d(10), y: e.d(20) }, e.d(40), a0, a1)];
        break;
      }
      case 'ELLIPSE': {
        const c = { x: e.d(10), y: e.d(20) }, major = { x: e.d(11), y: e.d(21) }, ratio = e.d(40, 1);
        const t0 = e.d(41, 0); let t1 = e.d(42, 2 * Math.PI);
        if (t1 <= t0) t1 += 2 * Math.PI;
        const a = Math.hypot(major.x, major.y), rot = Math.atan2(major.y, major.x);
        const n = Math.min(2000, Math.max(24, Math.ceil((t1 - t0) * a / SEG_MM)));
        const p: Pt[] = [];
        for (let s = 0; s <= n; s++) {
          const t = t0 + (t1 - t0) * s / n, ex = a * Math.cos(t), ey = a * ratio * Math.sin(t);
          p.push({ x: c.x + ex * Math.cos(rot) - ey * Math.sin(rot), y: c.y + ex * Math.sin(rot) + ey * Math.cos(rot) });
        }
        local = [p];
        break;
      }
      case 'SPLINE': local = [spline(e)]; break;
      case 'INSERT': {
        const block = blocks.get(e.s(2) ?? '');
        if (block) {
          const r = e.d(50) * Math.PI / 180;
          const t = mul(mul(mul(m, mat(1, 0, 0, 1, e.d(10), e.d(20))), mat(Math.cos(r), Math.sin(r), -Math.sin(r), Math.cos(r))), mat(e.d(41, 1), 0, 0, e.d(42, 1)));
          emit(block, t, blocks, out, depth + 1, skipped);
        }
        break;
      }
      default:
        if (!IGNORED.has(e.type)) { const name = entityLabel(e.type); skipped.set(name, (skipped.get(name) ?? 0) + 1); }
    }
    for (const p of local) if (p.length >= 2) out.push(p.map((q) => applyM(m, q)));
  }
}

const entityLabel = (t: string) => ({ TEXT: 'Text', MTEXT: 'Text', HATCH: 'Schraffur', DIMENSION: 'Bemaßung', LEADER: 'Hinweislinie', IMAGE: 'Bild', SOLID: 'Fläche' } as Record<string, string>)[t] ?? t;

/** Polyline with bulge arcs (bulge = tan(angle / 4), positive counter-clockwise). */
function bulgePath(pts: [Pt, number][], closed: boolean): Poly {
  if (!pts.length) return [];
  const out: Pt[] = [pts[0][0]];
  const count = closed ? pts.length : pts.length - 1;
  for (let k = 0; k < count; k++) {
    const [p0, bulge] = pts[k];
    const p1 = pts[(k + 1) % pts.length][0];
    if (Math.abs(bulge) < 1e-9) { out.push(p1); continue; }
    const theta = 4 * Math.atan(bulge);
    const chord = Math.hypot(p1.x - p0.x, p1.y - p0.y);
    const r = chord / (2 * Math.sin(Math.abs(theta) / 2));
    const h = r * Math.cos(theta / 2);
    const nx = -(p1.y - p0.y) / chord, ny = (p1.x - p0.x) / chord;
    const sgn = bulge > 0 ? 1 : -1;
    const c = { x: (p0.x + p1.x) / 2 + nx * h * sgn, y: (p0.y + p1.y) / 2 + ny * h * sgn };
    const a0 = Math.atan2(p0.y - c.y, p0.x - c.x);
    const n = Math.min(720, Math.max(4, Math.ceil(Math.abs(theta) * r / SEG_MM)));
    for (let s = 1; s <= n; s++) {
      const a = a0 + theta * s / n;
      out.push(s === n ? p1 : { x: c.x + r * Math.cos(a), y: c.y + r * Math.sin(a) });
    }
  }
  if (closed && (out[0].x !== out[out.length - 1].x || out[0].y !== out[out.length - 1].y)) out.push(out[0]);
  return out;
}

function arc(c: Pt, r: number, a0: number, a1: number): Poly {
  const n = Math.min(2000, Math.max(12, Math.ceil((a1 - a0) * r / SEG_MM)));
  const out: Pt[] = [];
  for (let s = 0; s <= n; s++) { const a = a0 + (a1 - a0) * s / n; out.push({ x: c.x + r * Math.cos(a), y: c.y + r * Math.sin(a) }); }
  return out;
}

/** B-spline (de Boor) from control points and knots; fit points as fallback. */
function spline(e: Entity): Poly {
  const degree = e.i(71, 3), knots = e.all(40), cx = e.all(10), cy = e.all(20);
  const ctrl = cx.slice(0, Math.min(cx.length, cy.length)).map((x, i) => ({ x, y: cy[i] }));
  if (ctrl.length < 2 || knots.length !== ctrl.length + degree + 1) {
    const fx = e.all(11), fy = e.all(21);
    const fit = fx.slice(0, Math.min(fx.length, fy.length)).map((x, i) => ({ x, y: fy[i] }));
    return fit.length ? fit : ctrl;
  }
  const t0 = knots[degree], t1 = knots[ctrl.length];
  let approx = 0;
  for (let i = 1; i < ctrl.length; i++) approx += Math.hypot(ctrl[i].x - ctrl[i - 1].x, ctrl[i].y - ctrl[i - 1].y);
  const n = Math.min(4000, Math.max(16, Math.ceil(approx / SEG_MM)));
  const out: Pt[] = [];
  for (let s = 0; s <= n; s++) {
    const t = s === n ? t1 - 1e-9 * (t1 - t0) : t0 + (t1 - t0) * s / n;
    let span = degree;
    while (span < ctrl.length - 1 && t >= knots[span + 1]) span++;
    const d = Array.from({ length: degree + 1 }, (_, j) => ctrl[span - degree + j]);
    for (let r = 1; r <= degree; r++) for (let j = degree; j >= r; j--) {
      const i = span - degree + j;
      const denom = knots[i + degree - r + 1] - knots[i];
      const alpha = denom === 0 ? 0 : (t - knots[i]) / denom;
      d[j] = { x: (1 - alpha) * d[j - 1].x + alpha * d[j].x, y: (1 - alpha) * d[j - 1].y + alpha * d[j].y };
    }
    out.push(d[degree]);
  }
  return out;
}
