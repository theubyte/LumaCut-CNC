import { parse, type Font, type PathCommand } from 'opentype.js';
import { boundsOf, type Poly, type Pt } from './model';
import { listSystemFonts, readSystemFont, type SystemFont } from '@/platform';

/**
 * Text as outlines. `sizeMm` is the em size, as on Android. Fonts come from the system in the
 * installed app; a browser or a missing font falls back to the bundled Liberation Sans (public/fonts,
 * SIL Open Font License). Output is in mm, y down, with the bounds' top-left at (0, 0).
 */
export const BUNDLED_FAMILY = 'Liberation Sans';
const TOL_MM = 0.02;

/** Android's generic family names and their closest Windows font. */
const GENERIC: Record<string, string[]> = {
  'sans-serif': ['Segoe UI', 'Arial'], serif: ['Times New Roman', 'Georgia'], monospace: ['Consolas', 'Courier New'],
};

let systemFonts: Promise<SystemFont[]> | null = null;
const fonts = () => (systemFonts ??= listSystemFonts().catch(() => []));
const cache = new Map<string, Promise<Font>>();

export async function listFamilies(): Promise<string[]> {
  const all = await fonts();
  const names = new Set(all.filter((f) => !f.italic).map((f) => f.family));
  names.add(BUNDLED_FAMILY);
  return [...names].sort((a, b) => a.localeCompare(b, 'de'));
}

async function bundled(bold: boolean): Promise<Font> {
  const r = await fetch(`${import.meta.env.BASE_URL}fonts/LiberationSans-${bold ? 'Bold' : 'Regular'}.ttf`);
  if (!r.ok) throw new Error('Mitgelieferte Schrift fehlt');
  return parse(await r.arrayBuffer());
}

async function load(family: string, bold: boolean): Promise<Font> {
  if (family !== BUNDLED_FAMILY) {
    const all = await fonts();
    for (const name of GENERIC[family] ?? [family]) {
      const same = all.filter((f) => f.family === name && !f.italic);
      const face = same.find((f) => f.bold === bold) ?? same[0];
      if (face) { try { return parse(await readSystemFont(face.file)); } catch { /* damaged font: try the next */ } }
    }
  }
  return bundled(bold);
}

export function loadFont(family: string, bold: boolean): Promise<Font> {
  const key = `${family}|${bold}`;
  let f = cache.get(key);
  if (!f) { f = load(family, bold); cache.set(key, f); f.catch(() => cache.delete(key)); }
  return f;
}

function quad(out: Pt[], a: Pt, b: Pt, c: Pt, tol: number) {
  const d = Math.hypot(a.x - 2 * b.x + c.x, a.y - 2 * b.y + c.y);
  const n = Math.max(1, Math.min(64, Math.ceil(Math.sqrt(d / (4 * tol)))));
  for (let i = 1; i <= n; i++) { const t = i / n, u = 1 - t; out.push({ x: u * u * a.x + 2 * u * t * b.x + t * t * c.x, y: u * u * a.y + 2 * u * t * b.y + t * t * c.y }); }
}
function cubic(out: Pt[], a: Pt, b: Pt, c: Pt, d: Pt, tol: number) {
  const m = Math.max(Math.hypot(a.x - 2 * b.x + c.x, a.y - 2 * b.y + c.y), Math.hypot(b.x - 2 * c.x + d.x, b.y - 2 * c.y + d.y));
  const n = Math.max(1, Math.min(64, Math.ceil(Math.sqrt(3 * m / (4 * tol)))));
  for (let i = 1; i <= n; i++) { const t = i / n, u = 1 - t;
    out.push({ x: u * u * u * a.x + 3 * u * u * t * b.x + 3 * u * t * t * c.x + t * t * t * d.x, y: u * u * u * a.y + 3 * u * u * t * b.y + 3 * u * t * t * c.y + t * t * t * d.y }); }
}
function flattenCommands(cmds: PathCommand[], tol: number): Poly[] {
  const out: Poly[] = [];
  let cur: Pt[] = [], last: Pt = { x: 0, y: 0 };
  const flush = () => { if (cur.length >= 2) out.push(cur); cur = []; };
  for (const c of cmds) {
    if (c.type === 'M') { flush(); last = { x: c.x, y: c.y }; cur = [last]; }
    else if (c.type === 'L') { last = { x: c.x, y: c.y }; cur.push(last); }
    else if (c.type === 'Q') { const to = { x: c.x, y: c.y }; quad(cur, last, { x: c.x1, y: c.y1 }, to, tol); last = to; }
    else if (c.type === 'C') { const to = { x: c.x, y: c.y }; cubic(cur, last, { x: c.x1, y: c.y1 }, { x: c.x2, y: c.y2 }, to, tol); last = to; }
    else if (c.type === 'Z' && cur.length) {
      const f = cur[0];
      if (Math.hypot(f.x - last.x, f.y - last.y) > 1e-9) cur.push({ ...f }); else cur[cur.length - 1] = { ...f };
      last = f; flush();
    }
  }
  flush();
  return out;
}

/** Lines are `\n` separated. An empty text gives no paths. */
export function layoutText(font: Pick<Font, 'getPath' | 'ascender' | 'descender' | 'unitsPerEm'>, text: string, sizeMm: number, tol = TOL_MM): Poly[] {
  const lead = (font.ascender - font.descender) / font.unitsPerEm * sizeMm * 1.05;
  const polys = text.split(/\r?\n/).flatMap((line, i) => line.trim() ? flattenCommands(font.getPath(line, 0, i * lead, sizeMm).commands, tol) : []);
  const b = boundsOf(polys);
  return b ? polys.map((p) => p.map((q) => ({ x: q.x - b.minX, y: q.y - b.minY }))) : [];
}

export async function textPaths(text: string, sizeMm: number, bold: boolean, family: string): Promise<Poly[]> {
  return layoutText(await loadFont(family, bold), text, sizeMm);
}
