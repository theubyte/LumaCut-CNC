/**
 * Gerber RS-274X reader. Pure: text in, polygons in millimetres out, in the file's coordinates
 * (Y up, seen from the top of the board).
 *
 * Supported: %FS (L/T, A/I), %MO, %AD with C, R, O, P and macros, %AM with primitives 1, 20, 21, 22,
 * 4, 5, 6, 7, variables and arithmetic, D01/D02/D03, G01/G02/G03 with G74 and G75, G36/G37, %LP,
 * %LM/%LR/%LS on flashes, %SR, %OF, G70/G71, G90/G91, modal coordinates and D codes.
 * Not supported, reported as a warning: %AB block apertures, %IP negative images, %MI, %SF, %IR.
 */
import type { Box, Poly, Pt } from '@/core/model';
import { boundsOf } from '@/core/model';
import { addPolys, circle, cleanEvenOdd, polysArea, strokePolyline, subtractPolys, unionPolys } from './clipper';

export interface GerberFlash { x: number; y: number; w: number; h: number; code: number }
export interface GerberStroke { pts: Poly; width: number }
export interface GerberResult {
  units: 'mm' | 'inch';
  /** Final image: closed rings, outers CCW, holes CW. */
  polys: Poly[];
  bounds: Box | null;
  /** mm². */
  area: number;
  flashes: GerberFlash[];
  /** Centre lines of everything drawn dark, for finding the board outline. */
  strokes: GerberStroke[];
  /** Smallest drawn line width (dark strokes), the design's trace width. */
  minStrokeWidth: number | null;
  regionCount: number;
  warnings: string[];
  /** X2 attribute %TF.FileFunction, if the file carries one. */
  fileFunction: string | null;
}

export class GerberError extends Error {}

const TOL = 0.002;
const rad = (deg: number) => (deg * Math.PI) / 180;
const rotatePts = (poly: Poly, deg: number): Poly => {
  if (!deg) return poly;
  const c = Math.cos(rad(deg)), s = Math.sin(rad(deg));
  return poly.map((p) => ({ x: p.x * c - p.y * s, y: p.x * s + p.y * c }));
};
const rectPoly = (cx: number, cy: number, w: number, h: number): Poly => [
  { x: cx - w / 2, y: cy - h / 2 }, { x: cx + w / 2, y: cy - h / 2 }, { x: cx + w / 2, y: cy + h / 2 }, { x: cx - w / 2, y: cy + h / 2 }];
const hole = (d: number): Poly => circle(0, 0, d / 2, TOL).reverse();
function obround(w: number, h: number): Poly {
  if (Math.abs(w - h) < 1e-9) return circle(0, 0, w / 2, TOL);
  const r = Math.min(w, h) / 2, n = Math.max(6, Math.ceil(circle(0, 0, r, TOL).length / 2));
  const out: Poly = [];
  const arc = (cx: number, cy: number, a0: number) => { for (let i = 0; i <= n; i++) { const a = a0 + (i / n) * Math.PI; out.push({ x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) }); } };
  if (w > h) { arc(w / 2 - r, 0, -Math.PI / 2); arc(-w / 2 + r, 0, Math.PI / 2); }
  else { arc(0, h / 2 - r, 0); arc(0, -h / 2 + r, Math.PI); }
  return out;
}

/* ---- Aperture macros ---- */
type MacroLine = { assign: number; expr: string } | { prim: number; args: string[] };
interface Macro { name: string; lines: MacroLine[] }

/** Macro arithmetic: + - x X / with parentheses, unary sign and $n. */
export function evalMacroExpr(src: string, vars: Map<number, number>): number {
  const s = src.replace(/\s+/g, ''); let i = 0;
  const num = (): number => {
    const c = s[i];
    if (c === '-') { i++; return -num(); }
    if (c === '+') { i++; return num(); }
    if (c === '(') { i++; const v = sum(); if (s[i] === ')') i++; return v; }
    if (c === '$') { const m = /^\$(\d+)/.exec(s.slice(i)); if (!m) throw new GerberError(`Makro-Ausdruck: ${src}`); i += m[0].length; return vars.get(+m[1]) ?? 0; }
    const m = /^(\d+\.?\d*|\.\d+)/.exec(s.slice(i));
    if (!m) throw new GerberError(`Makro-Ausdruck: ${src}`);
    i += m[0].length; return parseFloat(m[0]);
  };
  const prod = (): number => {
    let v = num();
    for (;;) { const c = s[i]; if (c === 'x' || c === 'X') { i++; v *= num(); } else if (c === '/') { i++; v /= num(); } else return v; }
  };
  const sum = (): number => {
    let v = prod();
    for (;;) { const c = s[i]; if (c === '+') { i++; v += prod(); } else if (c === '-') { i++; v -= prod(); } else return v; }
  };
  return sum();
}

function parseMacro(blocks: string[]): Macro {
  const name = blocks[0].slice(2);
  const lines: MacroLine[] = [];
  for (const b of blocks.slice(1)) {
    if (!b) continue;
    const asg = /^\$(\d+)=(.+)$/.exec(b);
    if (asg) { lines.push({ assign: +asg[1], expr: asg[2] }); continue; }
    const parts = b.split(',');
    const prim = parseInt(parts[0], 10);
    if (!Number.isFinite(prim) || prim === 0 || !/^\d+$/.test(parts[0])) continue; // primitive 0: comment
    lines.push({ prim, args: parts.slice(1) });
  }
  return { name, lines };
}

function expandMacro(m: Macro, params: number[], unit: number, warn: (s: string) => void): Poly[] {
  const vars = new Map<number, number>(params.map((v, i) => [i + 1, v]));
  const sc = (p: Poly): Poly => p.map((q) => ({ x: q.x * unit, y: q.y * unit }));
  let acc: Poly[] = [];
  for (const line of m.lines) {
    if ('assign' in line) { vars.set(line.assign, evalMacroExpr(line.expr, vars)); continue; }
    const a = line.args.map((e) => evalMacroExpr(e, vars));
    let shape: Poly[] = [];
    let on = true;
    const expo = (v: number) => { on = v !== 0; };
    switch (line.prim) {
      case 1: // circle: exposure, diameter, x, y, rotation
        expo(a[0]);
        shape = [sc(rotatePts(circle(a[2], a[3], a[1] / 2, TOL / unit), a[4] ?? 0))];
        break;
      case 2: case 20: { // vector line: exposure, width, x0, y0, x1, y1, rotation
        expo(a[0]);
        const dx = a[4] - a[2], dy = a[5] - a[3], len = Math.hypot(dx, dy) || 1e-9;
        const nx = (-dy / len) * (a[1] / 2), ny = (dx / len) * (a[1] / 2);
        const pts: Poly = [{ x: a[2] + nx, y: a[3] + ny }, { x: a[2] - nx, y: a[3] - ny }, { x: a[4] - nx, y: a[5] - ny }, { x: a[4] + nx, y: a[5] + ny }];
        shape = cleanEvenOdd([sc(rotatePts(pts, a[6] ?? 0))]);
        break;
      }
      case 21: // centre rectangle: exposure, w, h, cx, cy, rotation
        expo(a[0]);
        shape = [sc(rotatePts(rectPoly(a[3], a[4], a[1], a[2]), a[5] ?? 0))];
        break;
      case 22: // lower-left rectangle: exposure, w, h, x, y, rotation
        expo(a[0]);
        shape = [sc(rotatePts(rectPoly(a[3] + a[1] / 2, a[4] + a[2] / 2, a[1], a[2]), a[5] ?? 0))];
        break;
      case 4: { // outline: exposure, n, x0, y0, ... xn, yn, rotation
        expo(a[0]);
        const n = Math.round(a[1]), pts: Poly = [];
        for (let i = 0; i <= n; i++) pts.push({ x: a[2 + 2 * i], y: a[3 + 2 * i] });
        shape = cleanEvenOdd([sc(rotatePts(pts, a[4 + 2 * n] ?? 0))]);
        break;
      }
      case 5: { // regular polygon: exposure, corners, x, y, diameter, rotation
        expo(a[0]);
        const n = Math.max(3, Math.round(a[1])), pts: Poly = [], r = a[4] / 2;
        for (let i = 0; i < n; i++) { const t = (2 * Math.PI * i) / n; pts.push({ x: a[2] + r * Math.cos(t), y: a[3] + r * Math.sin(t) }); }
        shape = cleanEvenOdd([sc(rotatePts(pts, a[5] ?? 0))]);
        break;
      }
      case 6: { // moire: x, y, outer d, ring thickness, gap, max rings, cross thickness, cross length, rotation
        const [cx, cy, od, th, gap, maxRings, ct, cl, rot] = a;
        let rings: Poly[] = [];
        let d = od;
        for (let i = 0; i < maxRings && d > 0; i++) {
          rings = addPolys(rings, subtractPolys([circle(cx, cy, d / 2, TOL / unit)], d - 2 * th > 0 ? [circle(cx, cy, d / 2 - th, TOL / unit)] : []));
          d -= 2 * (th + gap);
        }
        const cross = unionPolys([rectPoly(cx, cy, cl, ct), rectPoly(cx, cy, ct, cl)]);
        shape = addPolys(rings, cross).map((p) => sc(rotatePts(p, rot ?? 0)));
        break;
      }
      case 7: { // thermal: x, y, outer d, inner d, gap, rotation
        const [cx, cy, od, id, gap, rot] = a;
        const ring = subtractPolys([circle(cx, cy, od / 2, TOL / unit)], [circle(cx, cy, id / 2, TOL / unit)]);
        const bars = unionPolys([rectPoly(cx, cy, od + 1, gap), rectPoly(cx, cy, gap, od + 1)]);
        shape = subtractPolys(ring, bars).map((p) => sc(rotatePts(p, rot ?? 0)));
        break;
      }
      default:
        warn(`Makro ${m.name}: Grundform ${line.prim} ist unbekannt und fehlt im Bild.`);
        continue;
    }
    acc = on ? addPolys(acc, shape) : subtractPolys(acc, shape);
  }
  return acc;
}

/* ---- Apertures ---- */
interface Aperture { kind: 'C' | 'R' | 'O' | 'P' | 'M'; polys: Poly[]; d?: number; w?: number; h?: number }

function makeAperture(tpl: string, params: number[], unit: number, macros: Map<string, Macro>, warn: (s: string) => void): Aperture {
  const u = params.map((p) => p * unit);
  const withHole = (outer: Poly, d?: number): Poly[] => d && d > 0 ? [outer, hole(d)] : [outer];
  const m = macros.get(tpl);
  if (m) return { kind: 'M', polys: expandMacro(m, params, unit, warn) };
  switch (tpl) {
    case 'C': return { kind: 'C', d: u[0], polys: withHole(circle(0, 0, u[0] / 2, TOL), u[1]) };
    case 'R': return { kind: 'R', w: u[0], h: u[1], polys: withHole(rectPoly(0, 0, u[0], u[1]), u[2]) };
    case 'O': return { kind: 'O', w: u[0], h: u[1], polys: withHole(obround(u[0], u[1]), u[2]) };
    case 'P': {
      const n = Math.max(3, Math.round(params[1])), rot = params[2] ?? 0, r = u[0] / 2, pts: Poly = [];
      for (let i = 0; i < n; i++) { const t = (2 * Math.PI * i) / n + rad(rot); pts.push({ x: r * Math.cos(t), y: r * Math.sin(t) }); }
      return { kind: 'P', d: u[0], polys: withHole(pts, params[3] != null ? params[3] * unit : undefined) };
    }
  }
  warn(`Blende mit unbekanntem Makro ${tpl}: fehlt im Bild.`);
  return { kind: 'M', polys: [] };
}

/* ---- Main parser ---- */
interface Op { dark: boolean; polys: Poly[] }
interface Format { xi: number; xd: number; yi: number; yd: number; trailing: boolean }

/** Splits into blocks. Extended (%) commands stay together, whitespace goes. */
function* blocksOf(text: string): Generator<{ ext: boolean; blocks: string[] }> {
  let i = 0;
  while (i < text.length) {
    if (text[i] === '%') {
      const end = text.indexOf('%', i + 1);
      if (end < 0) return;
      yield { ext: true, blocks: text.slice(i + 1, end).replace(/\s+/g, '').split('*').filter(Boolean) };
      i = end + 1;
    } else {
      const star = text.indexOf('*', i);
      if (star < 0) return;
      const next = text.indexOf('%', i);
      // A comment may contain a percent sign; only outside comments does it open an extended command.
      if (next >= 0 && next < star && !/^\s*G0?4(?!\d)/.test(text.slice(i, next))) { i = next; continue; }
      yield { ext: false, blocks: [text.slice(i, star).replace(/\s+/g, '')] };
      i = star + 1;
    }
  }
}

export function parseGerber(text: string): GerberResult {
  const warnings = new Set<string>();
  const warn = (s: string) => { warnings.add(s); };
  let fmt: Format | null = null;
  let unit = 1; let unitName: 'mm' | 'inch' = 'mm'; let unitSeen = false;
  const macros = new Map<string, Macro>();
  const apertures = new Map<number, Aperture>();
  let cur: Aperture | null = null, curCode = 0;
  let x = 0, y = 0;
  let interp = 1;
  let quadrant: 'single' | 'multi' | null = null;
  let lastD = 0;
  let inRegion = false;
  let contour: Poly = [];
  let regionOut: Poly[] = [];
  let regionCount = 0;
  let dark = true;
  let chain: Poly | null = null;
  let chainAp: Aperture | null = null;
  let offX = 0, offY = 0;
  let mirror = '', rotateDeg = 0, scaleBy = 1;
  let incremental = false;
  const ops: Op[] = [];
  const flashes: GerberFlash[] = [];
  const strokes: GerberStroke[] = [];
  let minStroke: number | null = null;
  let fileFunction: string | null = null;
  let sr: { x: number; y: number; i: number; j: number; opStart: number; flashStart: number } | null = null;

  const push = (polys: Poly[]) => { if (polys.length) ops.push({ dark, polys }); };

  const flushChain = () => {
    const line = chain, ap = chainAp;
    chain = null; chainAp = null;
    if (!line || !ap) return;
    const w = (ap.d ?? Math.min(ap.w ?? 0, ap.h ?? 0)) * scaleBy;
    if (dark) {
      strokes.push({ pts: line, width: w });
      if (w > 0.001 && (minStroke == null || w < minStroke)) minStroke = w;
    }
    if (ap.kind === 'C' || ap.kind === 'P' || ap.kind === 'O') {
      if (ap.kind !== 'C') warn('Linien mit nicht runder Blende sind als runder Stift genähert.');
      if (w > 0) push(strokePolyline(line, w));
    } else if (ap.kind === 'R') {
      const out: Poly[] = [];
      const hw = ((ap.w ?? 0) / 2) * scaleBy, hh = ((ap.h ?? 0) / 2) * scaleBy;
      for (let i = 1; i < line.length; i++) {
        const a = line[i - 1], b = line[i];
        out.push(...cleanEvenOdd([convexHull([
          { x: a.x - hw, y: a.y - hh }, { x: a.x + hw, y: a.y - hh }, { x: a.x + hw, y: a.y + hh }, { x: a.x - hw, y: a.y + hh },
          { x: b.x - hw, y: b.y - hh }, { x: b.x + hw, y: b.y - hh }, { x: b.x + hw, y: b.y + hh }, { x: b.x - hw, y: b.y + hh }])]));
      }
      push(unionPolys(out));
    } else warn('Linien mit Makro-Blende sind laut Gerber nicht erlaubt und fehlen im Bild.');
  };

  const parseCoord = (raw: string, axis: 'x' | 'y'): number => {
    if (raw.includes('.')) return parseFloat(raw) * unit;
    const f: Format = fmt ?? (fmt = { xi: 2, xd: 4, yi: 2, yd: 4, trailing: false });
    if (!unitSeen && !warnings.size) warn('Koordinaten ohne Formatangabe: als 2.4 gelesen.');
    const neg = raw.startsWith('-');
    let digits = raw.replace(/^[+-]/, '');
    const ints = axis === 'x' ? f.xi : f.yi, decs = axis === 'x' ? f.xd : f.yd;
    if (f.trailing) digits = digits.padEnd(ints + decs, '0');
    const v = parseInt(digits || '0', 10) / 10 ** decs;
    return (neg ? -v : v) * unit;
  };

  const applyObj = (polys: Poly[]): Poly[] => {
    if (!mirror && !rotateDeg && scaleBy === 1) return polys;
    const flipX = mirror.includes('X'), flipY = mirror.includes('Y');
    return polys.map((p) => {
      let q = p.map((v) => ({ x: (flipX ? -v.x : v.x) * scaleBy, y: (flipY ? -v.y : v.y) * scaleBy }));
      if (rotateDeg) q = rotatePts(q, rotateDeg);
      return flipX !== flipY ? q.reverse() : q;
    });
  };

  const arcPoints = (sx: number, sy: number, ex: number, ey: number, i: number, j: number, cw: boolean): Poly => {
    let cx = sx + i, cy = sy + j;
    if (quadrant === 'single') {
      // Offsets are unsigned here: the centre is the candidate with a sweep up to 90 degrees.
      let best = Infinity;
      for (const [a, b] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) {
        const ccx = sx + a * Math.abs(i), ccy = sy + b * Math.abs(j);
        const sw = Math.abs(sweep(Math.atan2(sy - ccy, sx - ccx), Math.atan2(ey - ccy, ex - ccx), cw, false));
        const err = Math.abs(Math.hypot(sx - ccx, sy - ccy) - Math.hypot(ex - ccx, ey - ccy)) + (sw > Math.PI / 2 + 1e-3 ? 1000 : 0);
        if (err < best) { best = err; cx = ccx; cy = ccy; }
      }
    }
    const r0 = Math.hypot(sx - cx, sy - cy), r1 = Math.hypot(ex - cx, ey - cy), r = (r0 + r1) / 2;
    if (r < 1e-9) return [{ x: ex, y: ey }];
    if (Math.abs(r0 - r1) > 0.05) warn(`Bogen bei X${ex.toFixed(2)} Y${ey.toFixed(2)}: Mittelpunkt passt nicht zu Anfang und Ende, Form kann abweichen.`);
    const full = quadrant !== 'single' && Math.hypot(sx - ex, sy - ey) < 1e-6;
    const a0 = Math.atan2(sy - cy, sx - cx);
    const sw = sweep(a0, Math.atan2(ey - cy, ex - cx), cw, full);
    const stepRad = 2 * Math.acos(1 - Math.min(TOL, r) / r);
    const n = Math.max(1, Math.ceil(Math.abs(sw) / stepRad));
    const out: Poly = [];
    for (let k = 1; k < n; k++) { const t = a0 + (sw * k) / n, rr = r0 + ((r1 - r0) * k) / n; out.push({ x: cx + rr * Math.cos(t), y: cy + rr * Math.sin(t) }); }
    out.push({ x: ex, y: ey });
    return out;
  };

  const closeContour = () => {
    if (contour.length >= 3) { regionOut.push(...cleanEvenOdd([contour])); regionCount++; }
    contour = [];
  };

  const dataBlock = (b: string) => {
    if (!b || /^G0?4(?!\d)/.test(b)) return;
    const re = /([GMXYIJD])([+-]?[\d.]+)/g;
    let m: RegExpExecArray | null;
    let cx: string | null = null, cy: string | null = null, ci: string | null = null, cj: string | null = null, d: number | null = null;
    while ((m = re.exec(b))) {
      const v = m[2];
      switch (m[1]) {
        case 'G': {
          const g = parseInt(v, 10);
          if (g === 1 || g === 2 || g === 3) interp = g;
          else if (g === 36) { flushChain(); inRegion = true; regionOut = []; contour = []; }
          else if (g === 37) { closeContour(); push(regionOut); regionOut = []; inRegion = false; }
          else if (g === 74) quadrant = 'single';
          else if (g === 75) quadrant = 'multi';
          else if (g === 70) { unit = 25.4; unitName = 'inch'; unitSeen = true; }
          else if (g === 71) { unit = 1; unitName = 'mm'; unitSeen = true; }
          else if (g === 90) incremental = false;
          else if (g === 91) incremental = true;
          break;
        }
        case 'X': cx = v; break;
        case 'Y': cy = v; break;
        case 'I': ci = v; break;
        case 'J': cj = v; break;
        case 'D': d = parseInt(v, 10); break;
      }
    }
    if (d != null && d >= 10) {
      flushChain();
      curCode = d;
      cur = apertures.get(d) ?? null;
      if (!cur) warn(`Blende D${d} ist nicht definiert: was sie zeichnet, fehlt im Bild.`);
      return;
    }
    const hasCoord = cx != null || cy != null;
    if (d == null) { if (!hasCoord) return; d = lastD || 2; }
    lastD = d;
    const nx = cx != null ? (incremental ? x : offX) + parseCoord(cx, 'x') : x;
    const ny = cy != null ? (incremental ? y : offY) + parseCoord(cy, 'y') : y;
    const i = ci != null ? parseCoord(ci, 'x') : 0, j = cj != null ? parseCoord(cj, 'y') : 0;

    if (d === 2) {
      flushChain();
      if (inRegion) { closeContour(); contour = [{ x: nx, y: ny }]; }
    } else if (d === 1) {
      if (interp !== 1 && quadrant == null) warn('Bogen ohne G74/G75: als G75 gelesen.');
      const seg: Poly = interp === 1 ? [{ x: nx, y: ny }] : arcPoints(x, y, nx, ny, i, j, interp === 2);
      if (inRegion) {
        if (!contour.length) contour.push({ x, y });
        contour.push(...seg);
      } else if (cur) {
        if (!chain || chainAp !== cur) { flushChain(); chain = [{ x, y }]; chainAp = cur; }
        chain.push(...seg);
      }
    } else if (d === 3) {
      flushChain();
      if (inRegion) warn('D03 innerhalb einer Region ist nicht erlaubt und wurde übergangen.');
      else if (cur) {
        const local = applyObj(cur.polys);
        push(local.map((p) => p.map((q) => ({ x: q.x + nx, y: q.y + ny }))));
        const bb = boundsOf(local);
        if (dark && bb) flashes.push({ x: nx, y: ny, w: bb.maxX - bb.minX, h: bb.maxY - bb.minY, code: curCode });
      }
    }
    x = nx; y = ny;
  };

  const closeStepRepeat = () => {
    if (!sr) return;
    flushChain();
    const baseOps = ops.slice(sr.opStart), baseFlash = flashes.slice(sr.flashStart);
    for (let ix = 0; ix < sr.x; ix++) for (let iy = 0; iy < sr.y; iy++) {
      if (!ix && !iy) continue;
      const dx = ix * sr.i, dy = iy * sr.j;
      for (const o of baseOps) ops.push({ dark: o.dark, polys: o.polys.map((p) => p.map((q) => ({ x: q.x + dx, y: q.y + dy }))) });
      for (const f of baseFlash) flashes.push({ ...f, x: f.x + dx, y: f.y + dy });
    }
    sr = null;
  };

  const extended = (blocks: string[]) => {
    if (blocks[0]?.startsWith('AM')) { const mac = parseMacro(blocks); macros.set(mac.name, mac); return; }
    for (const b of blocks) {
      const code = b.slice(0, 2);
      switch (code) {
        case 'FS': {
          const m = /^FS([LTD]?)([AI]?)(?:N\d+)?(?:G\d+)?X(\d)(\d)Y(\d)(\d)/.exec(b);
          if (!m) { warn(`Format nicht lesbar: ${b}`); break; }
          fmt = { xi: +m[3], xd: +m[4], yi: +m[5], yd: +m[6], trailing: m[1] === 'T' };
          incremental = m[2] === 'I';
          break;
        }
        case 'MO':
          if (b.startsWith('MOIN')) { unit = 25.4; unitName = 'inch'; } else { unit = 1; unitName = 'mm'; }
          unitSeen = true;
          break;
        case 'AD': {
          const m = /^ADD(\d+)([A-Za-z_.$][^,]*?)(?:,(.*))?$/.exec(b);
          if (!m) { warn(`Blende nicht lesbar: ${b}`); break; }
          const params = (m[3] ?? '').split('X').filter(Boolean).map(parseFloat);
          apertures.set(+m[1], makeAperture(m[2], params, unit, macros, warn));
          break;
        }
        case 'LP': flushChain(); dark = b[2] !== 'C'; break;
        case 'LM': flushChain(); mirror = b.slice(2) === 'N' ? '' : b.slice(2); break;
        case 'LR': flushChain(); rotateDeg = parseFloat(b.slice(2)) || 0; break;
        case 'LS': flushChain(); scaleBy = parseFloat(b.slice(2)) || 1; break;
        case 'SR': {
          closeStepRepeat();
          flushChain();
          const m = /^SR(?:X(\d+))?(?:Y(\d+))?(?:I([-\d.]+))?(?:J([-\d.]+))?/.exec(b);
          const nx = +(m?.[1] ?? 1), ny = +(m?.[2] ?? 1);
          if (nx > 1 || ny > 1) sr = { x: nx, y: ny, i: parseFloat(m?.[3] ?? '0') * unit, j: parseFloat(m?.[4] ?? '0') * unit, opStart: ops.length, flashStart: flashes.length };
          break;
        }
        case 'OF': {
          const m = /^OF(?:A([-\d.]+))?(?:B([-\d.]+))?/.exec(b);
          offX = parseFloat(m?.[1] ?? '0') * unit; offY = parseFloat(m?.[2] ?? '0') * unit;
          break;
        }
        case 'TF': {
          const m = /^TF\.FileFunction,(.*)$/.exec(b);
          if (m) fileFunction = m[1];
          break;
        }
        case 'AB': warn('Blockblenden (%AB) werden nicht unterstützt: was sie zeichnen, fehlt im Bild.'); break;
        case 'IP': if (b !== 'IPPOS') warn('Negatives Gesamtbild (%IPNEG) wird nicht unterstützt: das Bild ist nicht invertiert.'); break;
        case 'MI': case 'SF': case 'IR': warn(`Veralteter Befehl %${code} wird nicht unterstützt, Maße können abweichen.`); break;
        default: break; // TA, TO, TD, LN, AS, IN: no effect on the image
      }
    }
  };

  for (const { ext, blocks } of blocksOf(text)) {
    if (ext) { extended(blocks); continue; }
    const b = blocks[0];
    if (b === 'M02' || b === 'M00' || b === 'M2') break;
    dataBlock(b);
  }
  flushChain();
  closeStepRepeat();
  if (inRegion) { closeContour(); push(regionOut); warn('Region ohne Abschluss G37.'); }
  if (!fmt && !unitSeen && !ops.length) throw new GerberError('Keine Gerber-Daten erkannt.');
  if (!unitSeen) warn('Keine Einheit angegeben: als Millimeter gelesen.');

  let acc: Poly[] = [];
  for (let k = 0; k < ops.length;) {
    const isDark = ops[k].dark;
    const batch: Poly[] = [];
    while (k < ops.length && ops[k].dark === isDark) { batch.push(...ops[k].polys); k++; }
    const solid = unionPolys(batch);
    acc = isDark ? addPolys(acc, solid) : subtractPolys(acc, solid);
  }
  return {
    units: unitName, polys: acc, bounds: boundsOf(acc), area: polysArea(acc), flashes, strokes,
    minStrokeWidth: minStroke, regionCount, warnings: [...warnings], fileFunction,
  };
}

function sweep(a0: number, a1: number, cw: boolean, full: boolean): number {
  if (full) return cw ? -2 * Math.PI : 2 * Math.PI;
  let s = a1 - a0;
  if (cw) { while (s > 0) s -= 2 * Math.PI; while (s <= -2 * Math.PI) s += 2 * Math.PI; }
  else { while (s < 0) s += 2 * Math.PI; while (s >= 2 * Math.PI) s -= 2 * Math.PI; }
  return s;
}

function convexHull(pts: Pt[]): Poly {
  const s = [...pts].sort((a, b) => a.x - b.x || a.y - b.y);
  const cross = (o: Pt, a: Pt, b: Pt) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lo: Pt[] = [], up: Pt[] = [];
  for (const p of s) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p); }
  for (const p of s.reverse()) { while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop(); up.push(p); }
  lo.pop(); up.pop();
  return [...lo, ...up];
}
