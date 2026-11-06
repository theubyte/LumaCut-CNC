import { applyM, boundsOf, cubicPoints, decodeBase64Loose, decodeText, IDENTITY_M, mat, type Matrix, movePolys, mul, Shapes, type Poly, type Pt } from './geom';
import { type EmbeddedImage, ImportError, vectorImport, type VectorImport } from './types';
import { attr, childByTag, parseXml, type XmlNode } from './xml';

/** What a file contains, recognised from its content (the extension is only a hint). Port of FileKinds. */
export type FileKind = 'SVG' | 'DXF' | 'XCS' | 'XS' | 'LBRN' | 'HPGL' | 'PDF' | 'IMAGE' | 'PROJECT' | 'UNKNOWN';
export const KIND_LABEL: Record<FileKind, string> = { SVG: 'SVG', DXF: 'DXF', XCS: 'xTool Creative Space', XS: 'xTool Studio', LBRN: 'LightBurn', HPGL: 'HPGL', PDF: 'PDF', IMAGE: 'Bild', PROJECT: 'LumaCut-Projekt', UNKNOWN: 'Unbekannt' };

export function detectKind(bytes: Uint8Array, isXs: (b: Uint8Array) => boolean): FileKind {
  if (bytes.length < 4) return 'UNKNOWN';
  const ascii = (from: number, n: number) => bytes.length >= from + n ? String.fromCharCode(...bytes.subarray(from, from + n)) : '';
  if (bytes[0] === 0x50 && bytes[1] === 0x4B) return isXs(bytes) ? 'XS' : 'UNKNOWN';
  if (ascii(0, 4) === '%PDF') return 'PDF';
  if (bytes[0] === 0x89 && ascii(1, 3) === 'PNG') return 'IMAGE';
  if (bytes[0] === 0xFF && bytes[1] === 0xD8 && bytes[2] === 0xFF) return 'IMAGE';
  if (ascii(0, 4) === 'GIF8') return 'IMAGE';
  if (ascii(0, 2) === 'BM' && bytes.length > 30) return 'IMAGE';
  if (ascii(0, 4) === 'RIFF' && ascii(8, 4) === 'WEBP') return 'IMAGE';
  if (ascii(4, 4) === 'ftyp' && /^(hei|mif|avi)/.test(ascii(8, 4))) return 'IMAGE';
  const head = new TextDecoder('utf-8').decode(bytes.subarray(0, 65536)).replace(/^[﻿ \t\r\n]+/, '');
  const lower = head.toLowerCase();
  if (lower.includes('<lightburnproject')) return 'LBRN';
  if (lower.includes('<svg')) return 'SVG';
  if (head.startsWith('{') && lower.includes('"layers"') && lower.includes('"title"')) return 'PROJECT';
  if (head.startsWith('{') && (lower.includes('"displays"') || lower.includes('"canvas"') || lower.includes('"dpath"'))) return 'XCS';
  if (/^0\s*\r?\n\s*SECTION/i.test(head) || /\r?\n\s*0\s*\r?\n\s*SECTION\s*\r?\n/.test(head)) return 'DXF';
  if (/^\s*(IN|SP\d?|PU|PD|PA)\b[;\d\s,-]/m.test(head.toUpperCase())) return 'HPGL';
  return 'UNKNOWN';
}

/** HPGL plot files: IN, SP, PU, PD, PA, PR with 40 plotter units per mm, y flipped to point down. */
export function parseHpgl(bytes: Uint8Array): Poly[] {
  const UNITS = 40;
  const text = new TextDecoder('latin1').decode(bytes);
  const out: Poly[] = [];
  let cur: Pt[] = [], down = false, x = 0, y = 0, absolute = true;
  const flush = () => { if (cur.length >= 2) out.push(cur); cur = []; };
  const moves = (args: number[]) => {
    for (let i = 0; i + 1 < args.length; i += 2) {
      const nx = absolute ? args[i] : x + args[i], ny = absolute ? args[i + 1] : y + args[i + 1];
      if (down) { if (!cur.length) cur.push({ x: x / UNITS, y: -y / UNITS }); cur.push({ x: nx / UNITS, y: -ny / UNITS }); }
      else flush();
      x = nx; y = ny;
    }
  };
  for (const raw of text.split(/[;\n\r]/)) {
    const cmd = raw.trim().replace(/\u001b/g, '');
    if (cmd.length < 2) continue;
    const op = cmd.slice(0, 2).toUpperCase();
    const args = cmd.slice(2).split(/[, ]/).map((s) => parseFloat(s)).filter(Number.isFinite);
    if (op === 'IN') { flush(); down = false; absolute = true; }
    else if (op === 'PA') { absolute = true; moves(args); }
    else if (op === 'PR') { absolute = false; moves(args); }
    else if (op === 'PU') { flush(); down = false; moves(args); }
    else if (op === 'PD') { down = true; moves(args); }
  }
  flush();
  if (!out.length) throw new ImportError('Keine Linien in der HPGL-Datei gefunden');
  const b = boundsOf(out)!;
  return movePolys(out, -b.minX, -b.minY);
}

/**
 * LightBurn projects (.lbrn, .lbrn2, XML): Rect, Ellipse, Path (lines and Béziers), Bitmap, Group, XForm.
 * Text with a stored outline (BackupPath, written by newer versions) is taken over as paths.
 * Coordinates stay as in the file, as on Android.
 */
const LB_CURVE_MM = 0.15;
const NUM = '-?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eE][-+]?\\d+)?';

export function parseLbrn(bytes: Uint8Array): VectorImport {
  let root: XmlNode;
  try { root = parseXml(decodeText(bytes)); } catch { throw new ImportError('Die Datei konnte nicht gelesen werden'); }
  if (root.tag.toLowerCase() !== 'lightburnproject') throw new ImportError('Keine LightBurn-Datei');
  const ctx: LbCtx = { polys: [], images: [], skipped: new Map(), textPaths: 0 };
  const shapes = (parent: XmlNode, m: Matrix) => {
    for (const el of parent.children) {
      if (el.tag === 'Shape') lbShape(el, m, ctx);
      else if (el.tag !== 'XForm' && el.tag !== 'CutSetting' && el.tag !== 'Notes') shapes(el, m);
    }
  };
  shapes(root, IDENTITY_M);
  if (!ctx.polys.length && !ctx.images.length) {
    const what = ctx.skipped.size ? `Nur ${[...ctx.skipped.keys()].join(', ')} gefunden (nicht lesbar)` : 'Keine Formen gefunden';
    throw new ImportError(`${what}. In LightBurn Text in Pfade umwandeln (Rechtsklick) und erneut speichern.`);
  }
  const r = vectorImport(ctx.polys, ctx.images, [...ctx.skipped].map(([k, n]) => `${n}× ${k}`));
  return ctx.textPaths ? { ...r, notes: [`Text in Pfade umgewandelt (${ctx.textPaths})`] } : r;
}

interface LbCtx { polys: Poly[]; images: EmbeddedImage[]; skipped: Map<string, number>; textPaths: number }
const lbNum = (el: XmlNode, name: string) => { const v = parseFloat(attr(el, name)); return Number.isFinite(v) ? v : 0; };

function lbXform(el: XmlNode): Matrix {
  const x = childByTag(el, 'XForm');
  if (x) { const v = x.text.trim().split(/\s+/).map(parseFloat); if (v.length === 6 && v.every(Number.isFinite)) return mat(v[0], v[1], v[2], v[3], v[4], v[5]); }
  return IDENTITY_M;
}

function lbShape(el: XmlNode, parent: Matrix, ctx: LbCtx) {
  const m = mul(parent, lbXform(el));
  const add = (local: Poly[]) => { for (const p of local) ctx.polys.push(p.map((q) => applyM(m, q))); };
  const skip = (t: string) => ctx.skipped.set(t, (ctx.skipped.get(t) ?? 0) + 1);
  const type = attr(el, 'Type');
  switch (type) {
    case 'Rect': { const w = lbNum(el, 'W'), h = lbNum(el, 'H'); add([Shapes.rect(w, h, lbNum(el, 'Cr')).map((p) => ({ x: p.x - w / 2, y: p.y - h / 2 }))]); break; }
    case 'Ellipse': { const rx = lbNum(el, 'Rx'), ry = lbNum(el, 'Ry'); add([Shapes.ellipse(2 * rx, 2 * ry).map((p) => ({ x: p.x - rx, y: p.y - ry }))]); break; }
    case 'Path': add(lbPath(childByTag(el, 'VertList')?.text ?? '', childByTag(el, 'PrimList')?.text ?? '')); break;
    case 'Bitmap': {
      const data = decodeBase64Loose(attr(el, 'Data')); const w = lbNum(el, 'W'), h = lbNum(el, 'H');
      if (!data || w <= 0 || h <= 0) { skip('Bitmap'); return; }
      const box = boundsOf([[{ x: -w / 2, y: -h / 2 }, { x: w / 2, y: -h / 2 }, { x: w / 2, y: h / 2 }, { x: -w / 2, y: h / 2 }].map((p) => applyM(m, p))])!;
      ctx.images.push({ bytes: data, box });
      break;
    }
    case 'Group': for (const k of childByTag(el, 'Children')?.children ?? []) if (k.tag === 'Shape') lbShape(k, m, ctx); break;
    case 'Text': {
      const backup = childByTag(el, 'BackupPath');
      if (backup) { ctx.textPaths++; add(lbPath(childByTag(backup, 'VertList')?.text ?? '', childByTag(backup, 'PrimList')?.text ?? '')); }
      else skip('Text');
      break;
    }
    default: skip(type || 'Element');
  }
}

interface Vert { p: Pt; c0?: Pt; c1?: Pt }
function lbPath(vertText: string, primText: string): Poly[] {
  const verts: Vert[] = [];
  let c0x: number | null = null, c0y: number | null = null, c1x: number | null = null, c1y: number | null = null;
  const flush = () => {
    const v = verts[verts.length - 1]; if (!v) return;
    if (c0x != null && c0y != null) v.c0 = { x: c0x, y: c0y };
    if (c1x != null && c1y != null) v.c1 = { x: c1x, y: c1y };
    c0x = c0y = c1x = c1y = null;
  };
  for (const t of vertText.matchAll(new RegExp(`V(${NUM})\\s+(${NUM})|c0x(${NUM})|c0y(${NUM})|c1x(${NUM})|c1y(${NUM})`, 'g'))) {
    if (t[1] !== undefined) { flush(); verts.push({ p: { x: Number(t[1]), y: Number(t[2]) } }); }
    else if (t[3] !== undefined) c0x = Number(t[3]);
    else if (t[4] !== undefined) c0y = Number(t[4]);
    else if (t[5] !== undefined) c1x = Number(t[5]);
    else if (t[6] !== undefined) c1y = Number(t[6]);
  }
  flush();
  // Short forms of .lbrn2: all points one after the other.
  const short = primText.trim();
  if (short === 'LineClosed' || short === 'Line') {
    const pts = verts.map((v) => v.p);
    if (short === 'LineClosed' && pts.length) pts.push(pts[0]);
    return pts.length >= 2 ? [pts] : [];
  }
  const out: Poly[] = [];
  let cur: Pt[] = [], last = -1;
  for (const m of primText.matchAll(/([LB])\s*(\d+)\s+(\d+)/g)) {
    const i = Number(m[2]), j = Number(m[3]);
    if (!verts[i] || !verts[j]) continue;
    if (i !== last) { if (cur.length >= 2) out.push(cur); cur = [verts[i].p]; }
    if (m[1] === 'L') cur.push(verts[j].p);
    else cur.push(...cubicPoints(verts[i].p, verts[i].c1 ?? verts[i].p, verts[j].c0 ?? verts[j].p, verts[j].p, LB_CURVE_MM * 4));
    last = j;
  }
  if (cur.length >= 2) out.push(cur);
  return out;
}
