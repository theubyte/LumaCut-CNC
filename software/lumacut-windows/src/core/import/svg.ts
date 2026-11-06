import { PartSplitter } from '../parts';
import { applyM, cubicPoints, decodeBase64Loose, decodeText, dist, IDENTITY_M, isClosed, mat, type Matrix, mul, Shapes, type Poly, type Pt } from './geom';
import { type EmbeddedImage, ImportError, type ImportItem, type ImportLayerInfo, type VectorImport } from './types';
import { allByTag, attr, localName, parseXml, type XmlNode, XmlError } from './xml';

/**
 * Port of SvgImport.kt: visible geometry as polylines in mm, origin at the SVG's top-left.
 * Keeps the structure: every drawable is its own part, <g> become groups, colours become layers,
 * embedded pictures come along.
 */
const CURVE_MM = 0.2;
const MAX_POINTS = 400_000;
const PX_MM = 25.4 / 96;

export class SvgError extends ImportError {}

interface Paint { fill: string | null; stroke: string | null }
export interface RawDrawable { polys: Poly[]; colour: string | null; fill: boolean; groups: string[]; name: string | null }
interface Walk { css: Map<string, Map<string, string>>; items: RawDrawable[]; images: EmbeddedImage[]; texts: number; linkedImages: number; clones: number; ids: number }

export function parseSvg(bytes: Uint8Array): VectorImport {
  let root: XmlNode;
  try { root = parseXml(decodeText(bytes)); }
  catch (e) { if (e instanceof XmlError) throw new SvgError('SVG konnte nicht gelesen werden'); throw e; }
  if (localName(root.tag) !== 'svg') throw new SvgError('Keine SVG-Datei');
  const st: Walk = { css: cssRules(root), items: [], images: [], texts: 0, linkedImages: 0, clones: 0, ids: 0 };
  walk(root, rootMatrix(root), { fill: '#000000', stroke: 'none' }, [], st);
  const polys = st.items.flatMap((i) => i.polys);
  if (!polys.length && !st.images.length) throw new SvgError('Keine Vektoren gefunden (Text vorher in Pfade umwandeln)');
  if (polys.reduce((s, p) => s + p.length, 0) > MAX_POINTS) throw new SvgError('SVG zu komplex');
  const skipped: string[] = [];
  if (st.texts > 0) skipped.push(`Text (${st.texts})`);
  if (st.linkedImages > 0) skipped.push(`verlinkte Bilder (${st.linkedImages})`);
  if (st.clones > 0) skipped.push(`Klone (${st.clones})`);
  const { items, layers } = finishDrawables(st.items);
  return { polys, images: st.images, skipped, items, layers };
}

/**
 * Groups: a group around everything says nothing and is dropped, a file without groups becomes one group.
 * Colours: at least two different ones become layers, a file in one colour goes on the layer the operator chose.
 * White is usually a background and starts hidden, so it never burns.
 */
export function finishDrawables(raw: RawDrawable[]): { items: ImportItem[]; layers: ImportLayerInfo[] } {
  let groups = raw.map((r) => r.groups);
  while (groups.length && groups.every((g) => g.length) && new Set(groups.map((g) => g[0])).size === 1) groups = groups.map((g) => g.slice(1));
  if (raw.length > 1 && groups.every((g) => !g.length)) groups = groups.map(() => ['*']);
  const kinds = new Set(raw.filter((r) => r.colour != null).map((r) => `${r.colour}|${r.fill}`));
  const colours = kinds.size >= 2 ? [...new Set(raw.filter((r) => r.colour != null).map((r) => r.colour!))] : [];
  const names = new Map(colours.map((c) => [c, colourName(c)]));
  const layers = colours.map((c, i): ImportLayerInfo => {
    const n = names.get(c)!;
    const dup = [...names.values()].filter((x) => x === n).length > 1;
    return { key: c, name: dup ? `${n} ${c}` : n, order: i, visible: c !== '#ffffff' };
  });
  const items = raw.map((r, i): ImportItem => ({ polys: r.polys, layerKey: r.colour != null && colours.includes(r.colour) ? r.colour : null, fill: r.fill, groups: groups[i], name: r.name }));
  return { items, layers };
}

const COLOUR_NAMES: [string, string][] = [['Schwarz', '000000'], ['Weiß', 'ffffff'], ['Grau', '808080'], ['Rot', 'ff0000'], ['Grün', '00a000'], ['Blau', '0000ff'],
  ['Gelb', 'ffff00'], ['Orange', 'ff8000'], ['Violett', '8000c0'], ['Rosa', 'ff80c0'], ['Türkis', '00c0c0'], ['Braun', '804000']];
const rgb = (h: string) => [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
export function colourName(c: string): string {
  const want = rgb(c.replace('#', ''));
  let best = COLOUR_NAMES[0][0], bestD = Infinity;
  for (const [n, h] of COLOUR_NAMES) {
    const v = rgb(h); const d = (v[0] - want[0]) ** 2 + (v[1] - want[1]) ** 2 + (v[2] - want[2]) ** 2;
    if (d < bestD) { bestD = d; best = n; }
  }
  return best;
}

const CSS_NAMES: Record<string, string> = { black: '#000000', white: '#ffffff', red: '#ff0000', green: '#008000', lime: '#00ff00', blue: '#0000ff', yellow: '#ffff00', orange: '#ffa500', purple: '#800080',
  magenta: '#ff00ff', fuchsia: '#ff00ff', cyan: '#00ffff', aqua: '#00ffff', gray: '#808080', grey: '#808080', silver: '#c0c0c0', brown: '#a52a2a', pink: '#ffc0cb', navy: '#000080', maroon: '#800000', teal: '#008080' };

/** A CSS paint value in our form ("#rrggbb", "none"), null when it is not a plain colour (gradient, currentColor). */
export function colour(value: string, inherited: string | null): string | null {
  const v = value.trim().toLowerCase();
  if (v === 'none' || v === 'transparent') return 'none';
  if (v === 'inherit') return inherited;
  if (CSS_NAMES[v]) return CSS_NAMES[v];
  let m = /^#([0-9a-f]{6})$/.exec(v);
  if (m) return '#' + m[1];
  m = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/.exec(v);
  if (m) return '#' + m[1] + m[1] + m[2] + m[2] + m[3] + m[3];
  m = /^rgba?\(([^)]*)\)$/.exec(v);
  if (m) {
    const parts = m[1].split(/[\s,/]+/).filter(Boolean);
    if (parts.length < 3) return null;
    let out = '#';
    for (const p of parts.slice(0, 3)) {
      const n = parseFloat(p);
      if (!Number.isFinite(n)) return null;
      const c = Math.max(0, Math.min(255, Math.trunc(p.endsWith('%') ? n * 2.55 : n)));
      out += c.toString(16).padStart(2, '0');
    }
    return out;
  }
  return null;
}

const declarations = (s: string) => {
  const out = new Map<string, string>();
  for (const d of s.split(';')) {
    const i = d.indexOf(':'); if (i < 0) continue;
    const k = d.slice(0, i).trim().toLowerCase();
    if (k) out.set(k, d.slice(i + 1).trim());
  }
  return out;
};

/** Rules of the <style> blocks by selector (".name" or a tag); Illustrator writes its colours this way. */
function cssRules(root: XmlNode) {
  const rules = new Map<string, Map<string, string>>();
  for (const block of allByTag(root, 'style')) {
    for (const m of block.text.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const props = declarations(m[2]);
      for (const sel of m[1].split(',')) {
        const key = sel.trim(); const cur = rules.get(key) ?? new Map<string, string>();
        props.forEach((v, k) => cur.set(k, v)); rules.set(key, cur);
      }
    }
  }
  return rules;
}

/** Attributes, then <style> rules, then style="": later wins, as in CSS. */
function properties(node: XmlNode, css: Walk['css']) {
  const out = new Map<string, string>();
  for (const k of ['fill', 'stroke', 'stroke-width', 'display', 'visibility']) { const v = attr(node, k); if (v.trim()) out.set(k, v); }
  css.get(localName(node.tag))?.forEach((v, k) => out.set(k, v));
  for (const c of attr(node, 'class').split(/\s+/)) if (c) css.get('.' + c)?.forEach((v, k) => out.set(k, v));
  declarations(attr(node, 'style')).forEach((v, k) => out.set(k, v));
  return out;
}

function length(v: string): number | null {
  const m = /^\s*([-+]?[0-9.]+(?:e[-+]?\d+)?)\s*(mm|cm|in|pt|pc|px)?\s*$/i.exec(v);
  if (!m) return null;
  const n = parseFloat(m[1]);
  if (!Number.isFinite(n)) return null;
  switch ((m[2] ?? '').toLowerCase()) {
    case 'mm': return n; case 'cm': return n * 10; case 'in': return n * 25.4; case 'pt': return n * 25.4 / 72; case 'pc': return n * 25.4 / 6;
    default: return n * PX_MM;
  }
}

/** Scales user units to mm from width/height and viewBox (96 px per inch default). */
function rootMatrix(svg: XmlNode): Matrix {
  const vb = attr(svg, 'viewBox').split(/[\s,]+/).map(parseFloat).filter(Number.isFinite);
  const w = length(attr(svg, 'width')), h = length(attr(svg, 'height'));
  if (vb.length === 4 && vb[2] > 0 && vb[3] > 0) {
    const sx = (w ?? vb[2] * PX_MM) / vb[2], sy = (h ?? vb[3] * PX_MM) / vb[3];
    const k = w != null && h != null ? Math.min(sx, sy) : w != null ? sx : h != null ? sy : PX_MM;
    return mat(k, 0, 0, k, -vb[0] * k, -vb[1] * k);
  }
  return mat(PX_MM, 0, 0, PX_MM);
}

const SKIP = new Set(['defs', 'clipPath', 'mask', 'symbol', 'marker', 'pattern', 'title', 'desc', 'metadata', 'style', 'script', 'text', 'linearGradient', 'radialGradient', 'filter']);
const num = (e: XmlNode, name: string) => { const v = parseFloat(attr(e, name).trim().replace(/px$/, '')); return Number.isFinite(v) ? v : 0; };
const NUMBER = /[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g;
const numbers = (s: string) => (s.match(NUMBER) ?? []).map(Number);

function walk(node: XmlNode, parent: Matrix, inherited: Paint, parentGroups: string[], st: Walk) {
  const tag = localName(node.tag);
  if (tag === 'text') st.texts++;
  if (SKIP.has(tag)) return;
  const props = properties(node, st.css);
  if (props.get('display')?.trim() === 'none' || props.get('visibility')?.trim() === 'hidden') return;
  const m = mul(parent, svgTransform(attr(node, 'transform')));
  if (tag === 'image') { image(node, m, st); return; }
  if (tag === 'use') { st.clones++; return; }
  const paint: Paint = {
    fill: props.has('fill') ? colour(props.get('fill')!, inherited.fill) : inherited.fill,
    stroke: props.has('stroke') ? colour(props.get('stroke')!, inherited.stroke) : inherited.stroke,
  };
  const groups = tag === 'g' ? [...parentGroups, `g${st.ids++}`] : parentGroups;
  const local = shapeOf(tag, node);
  const world = local.filter((p) => p.length >= 2).map((p) => p.map((q) => applyM(m, q)));
  if (world.length) addDrawable(world, node, props, paint, groups, st);
  for (const c of node.children) walk(c, m, paint, groups, st);
}

function shapeOf(tag: string, node: XmlNode): Poly[] {
  switch (tag) {
    case 'path': return pathData(attr(node, 'd'));
    case 'rect': {
      const x = num(node, 'x'), y = num(node, 'y'), w = num(node, 'width'), h = num(node, 'height');
      return w > 0 && h > 0 ? [Shapes.rect(w, h, Math.max(num(node, 'rx'), num(node, 'ry'))).map((p) => ({ x: p.x + x, y: p.y + y }))] : [];
    }
    case 'circle': {
      const r = num(node, 'r');
      return r > 0 ? [Shapes.ellipse(2 * r, 2 * r, CURVE_MM).map((p) => ({ x: p.x + num(node, 'cx') - r, y: p.y + num(node, 'cy') - r }))] : [];
    }
    case 'ellipse': {
      const rx = num(node, 'rx'), ry = num(node, 'ry');
      return rx > 0 && ry > 0 ? [Shapes.ellipse(2 * rx, 2 * ry, CURVE_MM).map((p) => ({ x: p.x + num(node, 'cx') - rx, y: p.y + num(node, 'cy') - ry }))] : [];
    }
    case 'line': return [[{ x: num(node, 'x1'), y: num(node, 'y1') }, { x: num(node, 'x2'), y: num(node, 'y2') }]];
    case 'polyline': case 'polygon': {
      const n = numbers(attr(node, 'points')); const pts: Pt[] = [];
      for (let i = 0; i + 1 < n.length; i += 2) pts.push({ x: n[i], y: n[i + 1] });
      return pts.length < 2 ? [] : [tag === 'polygon' ? [...pts, pts[0]] : pts];
    }
    default: return [];
  }
}

/** One drawable: a stroke makes it a line in the stroke colour, else a closed shape is a fill. Letters keep their holes. */
function addDrawable(world: Poly[], node: XmlNode, props: Map<string, string>, paint: Paint, groups: string[], st: Walk) {
  const sw = props.get('stroke-width')?.trim().replace(/px$/, '');
  const noWidth = sw !== undefined && parseFloat(sw) === 0;
  const stroked = paint.stroke !== 'none' && !noWidth;
  const filled = !stroked && paint.fill !== 'none' && world.every((p) => p.length >= 4 && isClosed(p));
  const col = stroked ? paint.stroke : filled ? paint.fill : null;
  const parts = PartSplitter.split(world).parts;
  const own = parts.length > 1 ? [...groups, `p${st.ids++}`] : groups;
  const name = attr(node, 'inkscape:label') || attr(node, 'data-name') || null;
  for (const part of parts) st.items.push({ polys: part, colour: col, fill: filled, groups: own, name: name?.trim() ? name : null });
}

function image(node: XmlNode, m: Matrix, st: Walk) {
  const href = attr(node, 'href').trim() || attr(node, 'xlink:href');
  const bytes = href.startsWith('data:image') ? decodeBase64Loose(href) : null;
  const w = num(node, 'width'), h = num(node, 'height');
  if (!bytes || w <= 0 || h <= 0) { st.linkedImages++; return; }
  const a = applyM(m, { x: num(node, 'x'), y: num(node, 'y') }), b = applyM(m, { x: num(node, 'x') + w, y: num(node, 'y') + h });
  st.images.push({ bytes, box: { minX: Math.min(a.x, b.x), minY: Math.min(a.y, b.y), maxX: Math.max(a.x, b.x), maxY: Math.max(a.y, b.y) } });
}

export function svgTransform(s: string): Matrix {
  let m = IDENTITY_M;
  for (const t of s.matchAll(/(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)/g)) {
    const v = numbers(t[2]);
    const deg = (d: number) => d * Math.PI / 180;
    let o: Matrix;
    switch (t[1]) {
      case 'matrix': o = v.length === 6 ? mat(v[0], v[1], v[2], v[3], v[4], v[5]) : IDENTITY_M; break;
      case 'translate': o = mat(1, 0, 0, 1, v[0] ?? 0, v[1] ?? 0); break;
      case 'scale': o = mat(v[0] ?? 1, 0, 0, v[1] ?? v[0] ?? 1); break;
      case 'rotate': {
        const r = deg(v[0] ?? 0), cx = v[1] ?? 0, cy = v[2] ?? 0;
        o = mul(mul(mat(1, 0, 0, 1, cx, cy), mat(Math.cos(r), Math.sin(r), -Math.sin(r), Math.cos(r))), mat(1, 0, 0, 1, -cx, -cy));
        break;
      }
      case 'skewX': o = mat(1, 0, Math.tan(deg(v[0] ?? 0))); break;
      default: o = mat(1, Math.tan(deg(v[0] ?? 0)));
    }
    m = mul(m, o);
  }
  return m;
}

const isLetter = (c: string) => /[a-zA-Z]/.test(c);

/** SVG path data to polylines (curves flattened in user units). The arc flags may be written without separators. */
export function pathData(d: string): Poly[] {
  const tokens = d.match(/[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g) ?? [];
  const out: Poly[] = [];
  let cur: Pt[] = [];
  let pos: Pt = { x: 0, y: 0 }, start = pos;
  let lastCtrl: Pt | null = null, lastCmd = ' ';
  let i = 0, cmd = ' ';
  const bad = () => new SvgError('Ungültige Pfaddaten');
  const n = () => { const t = tokens[i++]; const v = t === undefined ? NaN : Number(t); if (!Number.isFinite(v)) throw bad(); return v; };
  const flush = () => { if (cur.length >= 2) out.push(cur); cur = []; };
  const to = (p: Pt) => { if (!cur.length) cur.push(pos); cur.push(p); pos = p; };
  /** "a1 1 0 01 2 2": flags are single digits and may stick to the next number. */
  const flag = () => {
    const t = tokens[i];
    if (t === undefined) throw bad();
    if (t === '0' || t === '1') { i++; return t === '1'; }
    if (t[0] === '0' || t[0] === '1') { tokens[i] = t.slice(1); return t[0] === '1'; }
    throw bad();
  };
  while (i < tokens.length) {
    if (isLetter(tokens[i][0])) cmd = tokens[i++][0];
    else if (cmd === ' ') throw bad();
    const rel = cmd === cmd.toLowerCase();
    const pt = (): Pt => { const x = n(), y = n(); return rel ? { x: pos.x + x, y: pos.y + y } : { x, y }; };
    const up = cmd.toUpperCase();
    switch (up) {
      case 'M': flush(); pos = pt(); start = pos; cur.push(pos); cmd = rel ? 'l' : 'L'; lastCtrl = null; break;
      case 'L': to(pt()); lastCtrl = null; break;
      case 'H': { const x = n(); to({ x: rel ? pos.x + x : x, y: pos.y }); lastCtrl = null; break; }
      case 'V': { const y = n(); to({ x: pos.x, y: rel ? pos.y + y : y }); lastCtrl = null; break; }
      case 'C': case 'S': {
        const c1: Pt = up === 'C' ? pt() : lastCtrl && 'CS'.includes(lastCmd.toUpperCase()) ? { x: 2 * pos.x - lastCtrl.x, y: 2 * pos.y - lastCtrl.y } : pos;
        const c2 = pt(), p = pt();
        cubicPoints(pos, c1, c2, p, CURVE_MM).forEach(to); lastCtrl = c2;
        break;
      }
      case 'Q': case 'T': {
        const c: Pt = up === 'Q' ? pt() : lastCtrl && 'QT'.includes(lastCmd.toUpperCase()) ? { x: 2 * pos.x - lastCtrl.x, y: 2 * pos.y - lastCtrl.y } : pos;
        const p = pt();
        const c1 = { x: pos.x + (c.x - pos.x) * 2 / 3, y: pos.y + (c.y - pos.y) * 2 / 3 }, c2 = { x: p.x + (c.x - p.x) * 2 / 3, y: p.y + (c.y - p.y) * 2 / 3 };
        cubicPoints(pos, c1, c2, p, CURVE_MM).forEach(to); lastCtrl = c;
        break;
      }
      case 'A': {
        const rx = n(), ry = n(), rot = n(), large = flag(), sweep = flag(), p = pt();
        arcPoints(pos, rx, ry, rot, large, sweep, p).forEach(to); lastCtrl = null;
        break;
      }
      case 'Z': if (cur.length) { to(start); flush(); } pos = start; lastCtrl = null; break;
      default: throw new SvgError(`Unbekannter Pfadbefehl ${cmd}`);
    }
    lastCmd = cmd;
    if (up === 'Z' && i < tokens.length && !isLetter(tokens[i][0])) throw bad();
  }
  flush();
  return out;
}

/** Endpoint to centre parameterisation (SVG spec F.6.5). */
function arcPoints(p0: Pt, rxIn: number, ryIn: number, rotDeg: number, large: boolean, sweep: boolean, p1: Pt): Pt[] {
  if (dist(p0, p1) < 1e-9) return [];
  let rx = Math.abs(rxIn), ry = Math.abs(ryIn);
  if (rx < 1e-9 || ry < 1e-9) return [p1];
  const phi = rotDeg * Math.PI / 180, cp = Math.cos(phi), sp = Math.sin(phi);
  const dx = (p0.x - p1.x) / 2, dy = (p0.y - p1.y) / 2;
  const x1 = cp * dx + sp * dy, y1 = -sp * dx + cp * dy;
  const lambda = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry);
  if (lambda > 1) { rx *= Math.sqrt(lambda); ry *= Math.sqrt(lambda); }
  const numer = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1;
  const den = rx * rx * y1 * y1 + ry * ry * x1 * x1;
  const coef = (large === sweep ? -1 : 1) * Math.sqrt(Math.max(0, numer / den));
  const cx1 = coef * rx * y1 / ry, cy1 = -coef * ry * x1 / rx;
  const cx = cp * cx1 - sp * cy1 + (p0.x + p1.x) / 2, cy = sp * cx1 + cp * cy1 + (p0.y + p1.y) / 2;
  const angle = (ux: number, uy: number, vx: number, vy: number) => {
    const dot = ux * vx + uy * vy, len = Math.sqrt((ux * ux + uy * uy) * (vx * vx + vy * vy));
    const a = Math.acos(Math.max(-1, Math.min(1, dot / len)));
    return ux * vy - uy * vx < 0 ? -a : a;
  };
  const t1 = angle(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry);
  let dt = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry);
  if (!sweep && dt > 0) dt -= 2 * Math.PI; else if (sweep && dt < 0) dt += 2 * Math.PI;
  const steps = Math.min(720, Math.max(2, Math.ceil(Math.abs(dt) * Math.max(rx, ry) / CURVE_MM)));
  const out: Pt[] = [];
  for (let k = 1; k <= steps; k++) {
    if (k === steps) { out.push(p1); break; }
    const t = t1 + dt * k / steps;
    out.push({ x: cx + rx * Math.cos(t) * cp - ry * Math.sin(t) * sp, y: cy + rx * Math.cos(t) * sp + ry * Math.sin(t) * cp });
  }
  return out;
}
