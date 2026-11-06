import { handleIn, handleOut } from '@/core/curves';
import {
  applyT, Bed, boxH, boxUnion, boxW, type Box, type CurvePath, type Doc, type Element, type ImageAdjust, type ImageMode, insideWork, isClosed, isImage,
  layerCss, type Layer, parkBox, type Poly, type Pt, type Raster, touchesPark, worldBounds,
} from '@/core/model';
import { previewImageData } from '@/core/raster';
import { gridSteps, RULER } from './editor';

/** Canvas drawing. Geometry is cached per object identity, so only what changed is rebuilt. */
export interface Palette {
  canvas: string; sheet: string; grid: string; gridMajor: string; line: string; line2: string; surface: string; surface2: string; text: string; muted: string; faint: string;
  accent: string; accentInk: string; accentSoft: string; bad: string; warn: string; park: string; font: string; mono: string;
}
export function readPalette(): Palette {
  const c = getComputedStyle(document.documentElement), v = (k: string) => c.getPropertyValue(k).trim();
  return { canvas: v('--canvas'), sheet: v('--sheet'), grid: v('--grid'), gridMajor: v('--grid-major'), line: v('--line'), line2: v('--line-2'), surface: v('--surface'), surface2: v('--surface-2'),
    text: v('--text'), muted: v('--muted'), faint: v('--faint'), accent: v('--accent'), accentInk: v('--accent-ink'), accentSoft: v('--accent-soft'), bad: v('--bad'), warn: v('--warn'), park: v('--park'), font: v('--font'), mono: v('--mono') };
}

interface LocalGeo { all: Path2D; closed: Path2D | null }
export interface Geo { box: Box; all: Path2D; closed: Path2D | null }
const localCache = new WeakMap<Poly[], LocalGeo>();
const geoCache = new WeakMap<Element, Geo>();

function localGeo(paths: Poly[]): LocalGeo {
  let g = localCache.get(paths);
  if (!g) {
    const all = new Path2D(); let closed: Path2D | null = null;
    for (const poly of paths) {
      if (poly.length < 2) continue;
      const c = isClosed(poly), target = new Path2D();
      target.moveTo(poly[0].x, poly[0].y);
      for (let i = 1; i < poly.length; i++) target.lineTo(poly[i].x, poly[i].y);
      if (c) { target.closePath(); (closed ??= new Path2D()).addPath(target); }
      all.addPath(target);
    }
    g = { all, closed }; localCache.set(paths, g);
  }
  return g;
}
const matrixOf = (e: Element) => {
  const t = e.transform, r = t.rotation * Math.PI / 180, c = Math.cos(r), s = Math.sin(r);
  return new DOMMatrix([t.scaleX * c, t.scaleX * s, -t.scaleY * s, t.scaleY * c, t.x, t.y]);
};
export function geoOf(e: Element): Geo {
  let g = geoCache.get(e);
  if (!g) {
    const l = localGeo(e.paths), all = new Path2D(), m = matrixOf(e);
    all.addPath(l.all, m);
    let closed: Path2D | null = null;
    if (l.closed) { closed = new Path2D(); closed.addPath(l.closed, m); }
    g = { box: worldBounds(e) ?? { minX: 0, minY: 0, maxX: 0, maxY: 0 }, all, closed };
    geoCache.set(e, g);
  }
  return g;
}

/* ---- Images: the bitmap shows what the laser would burn. The newest wanted version is computed off the frame. ---- */
interface Preview { key: string; bmp: ImageBitmap | null; wanted: string; busy: boolean }
const previews = new WeakMap<Raster, Preview>();
let onImageReady: () => void = () => {};
export const setImageReadyListener = (f: () => void) => { onImageReady = f; };

function computePreview(r: Raster, p: Preview, mode: ImageMode, adjust: ImageAdjust) {
  p.busy = true;
  const key = p.wanted;
  setTimeout(async () => {
    try {
      const img = previewImageData(r, { mode, adjust, maxPixels: 6_000_000 });
      const bmp = await createImageBitmap(img);
      p.bmp?.close(); p.bmp = bmp; p.key = key;
    } catch { p.key = key; }
    p.busy = false;
    onImageReady();
  }, 0);
}
function imageOf(e: Element): ImageBitmap | null {
  const r = e.raster!, key = e.imageMode + JSON.stringify(e.adjust ?? {});
  let p = previews.get(r);
  if (!p) { p = { key: '', bmp: null, wanted: key, busy: false }; previews.set(r, p); }
  p.wanted = key;
  if (p.key !== key && !p.busy) computePreview(r, p, e.imageMode, e.adjust);
  return p.bmp;
}

/* ---- Scene: sheet, grid, background, elements ---- */
export interface View { zoom: number; panX: number; panY: number; w: number; h: number; dpr: number }

function drawGrid(ctx: CanvasRenderingContext2D, v: View, pal: Palette, sx0: number, sy0: number, sx1: number, sy1: number) {
  const { minor, major } = gridSteps(v.zoom);
  const lines = (step: number, color: string, skipMajor: boolean) => {
    ctx.strokeStyle = color; ctx.lineWidth = 1 / v.dpr; ctx.beginPath();
    const crisp = (a: number) => (Math.round(a * v.dpr) + 0.5) / v.dpr;
    const x0 = Math.ceil(Math.max(0, (sx0 - v.panX) / v.zoom) / step), x1 = Math.floor(Math.min(Bed.width, (sx1 - v.panX) / v.zoom) / step);
    const y0 = Math.ceil(Math.max(0, (sy0 - v.panY) / v.zoom) / step), y1 = Math.floor(Math.min(Bed.height, (sy1 - v.panY) / v.zoom) / step);
    const yA = Math.max(sy0, v.panY), yB = Math.min(sy1, v.panY + Bed.height * v.zoom), xA = Math.max(sx0, v.panX), xB = Math.min(sx1, v.panX + Bed.width * v.zoom);
    const ratio = Math.round(major / minor);
    for (let i = x0; i <= x1; i++) { if (skipMajor && i % ratio === 0) continue; const x = crisp(i * step * v.zoom + v.panX); ctx.moveTo(x, yA); ctx.lineTo(x, yB); }
    for (let i = y0; i <= y1; i++) { if (skipMajor && i % ratio === 0) continue; const y = crisp(i * step * v.zoom + v.panY); ctx.moveTo(xA, y); ctx.lineTo(xB, y); }
    ctx.stroke();
  };
  lines(minor, pal.grid, true);
  lines(major, pal.gridMajor, false);
}

function drawPark(ctx: CanvasRenderingContext2D, v: View, pal: Palette) {
  const k = parkBox(), x = k.minX * v.zoom + v.panX, y = k.minY * v.zoom + v.panY, w = boxW(k) * v.zoom, h = boxH(k) * v.zoom;
  ctx.save();
  ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
  ctx.fillStyle = pal.park; ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = pal.park; ctx.lineWidth = 1.25; ctx.beginPath();
  for (let d = -h; d < w; d += 8) { ctx.moveTo(x + d, y + h); ctx.lineTo(x + d + h, y); }
  ctx.stroke();
  ctx.restore();
  ctx.strokeStyle = pal.bad; ctx.globalAlpha = 0.45; ctx.lineWidth = 1; ctx.strokeRect(Math.round(x) + 0.5, Math.round(y) + 0.5, Math.round(w) - 1, Math.round(h) - 1); ctx.globalAlpha = 1;
  if (w > 76 && h > 22) {
    ctx.fillStyle = pal.bad; ctx.font = `500 11px ${pal.font}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('Park-Ecke', x + w / 2, y + h / 2); ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  }
}

export interface SceneOpts { doc: Doc; showGrid: boolean; bg: ImageBitmap | null; bgOn: boolean; bgAlpha: number; selection: Set<string>; hidden?: Set<string> | null }
export function drawScene(ctx: CanvasRenderingContext2D, v: View, pal: Palette, o: SceneOpts) {
  ctx.setTransform(v.dpr, 0, 0, v.dpr, 0, 0);
  ctx.fillStyle = pal.canvas; ctx.fillRect(0, 0, v.w, v.h);
  const sx = v.panX, sy = v.panY, sw = Bed.width * v.zoom, sh = Bed.height * v.zoom;
  // Sheet with a soft edge, so it reads as the machine's bed lying on the desk.
  ctx.save(); ctx.shadowColor = 'rgba(16,20,48,.16)'; ctx.shadowBlur = 18; ctx.shadowOffsetY = 3; ctx.fillStyle = pal.sheet; ctx.fillRect(sx, sy, sw, sh); ctx.restore();
  ctx.save(); ctx.beginPath(); ctx.rect(sx, sy, sw, sh); ctx.clip();
  if (o.bgOn && o.bg) { ctx.globalAlpha = o.bgAlpha; ctx.imageSmoothingEnabled = true; ctx.drawImage(o.bg, sx, sy, sw, sh); ctx.globalAlpha = 1; }
  ctx.restore();
  if (o.showGrid) drawGrid(ctx, v, pal, RULER, RULER, v.w, v.h);
  drawPark(ctx, v, pal);
  ctx.strokeStyle = pal.line2; ctx.lineWidth = 1; ctx.strokeRect(Math.round(sx) - 0.5, Math.round(sy) - 0.5, Math.round(sw) + 1, Math.round(sh) + 1);

  // Elements in mm, stroke width constant on screen.
  const d = o.doc, layers = new Map(d.layers.map((l) => [l.id, l]));
  const wx0 = (RULER - v.panX) / v.zoom, wy0 = (RULER - v.panY) / v.zoom, wx1 = (v.w - v.panX) / v.zoom, wy1 = (v.h - v.panY) / v.zoom;
  ctx.setTransform(v.dpr * v.zoom, 0, 0, v.dpr * v.zoom, v.dpr * v.panX, v.dpr * v.panY);
  const px = 1 / v.zoom;
  ctx.lineJoin = 'round'; ctx.lineCap = 'round';
  // The whole layer fills even-odd, exactly like the hatching in the job: overlapping shapes leave a hole.
  const fills = new Map<string, Path2D>();
  for (const e of d.elements) {
    if (e.plate !== d.activePlate || o.hidden?.has(e.id) || isImage(e)) continue;
    const l = layers.get(e.layerId); if (!l || !l.visible || l.mode !== 'FILL') continue;
    const closed = geoOf(e).closed; if (!closed) continue;
    let path = fills.get(l.id); if (!path) fills.set(l.id, path = new Path2D());
    path.addPath(closed);
  }
  for (const [id, path] of fills) {
    const l = layers.get(id)!;
    ctx.globalAlpha = 0.42 * (l.output ? 1 : 0.4); ctx.fillStyle = layerCss(l); ctx.fill(path, 'evenodd');
  }
  for (const e of d.elements) {
    if (e.plate !== d.activePlate || o.hidden?.has(e.id)) continue;
    const l = layers.get(e.layerId); if (!l || !l.visible) continue;
    const g = geoOf(e); if (g.box.maxX < wx0 || g.box.minX > wx1 || g.box.maxY < wy0 || g.box.minY > wy1) continue;
    const dim = l.output ? 1 : 0.4;
    if (isImage(e)) {
      const bmp = imageOf(e);
      ctx.save(); ctx.globalAlpha = dim;
      const m = matrixOf(e); ctx.transform(m.a, m.b, m.c, m.d, m.e, m.f);
      if (bmp) { ctx.imageSmoothingEnabled = v.zoom * e.imageWidthMm * Math.abs(e.transform.scaleX) < bmp.width; ctx.drawImage(bmp, 0, 0, e.imageWidthMm, e.imageHeightMm); }
      else { ctx.fillStyle = pal.surface2; ctx.fillRect(0, 0, e.imageWidthMm, e.imageHeightMm); }
      ctx.restore();
      continue;
    }
    const color = layerCss(l);
    ctx.globalAlpha = dim; ctx.strokeStyle = color; ctx.lineWidth = (o.selection.has(e.id) ? 1.75 : 1.25) * px; ctx.stroke(g.all);
  }
  ctx.globalAlpha = 1;
  ctx.setTransform(v.dpr, 0, 0, v.dpr, 0, 0);
  // Size of the work area under the sheet.
  ctx.fillStyle = pal.faint; ctx.font = `11px ${pal.font}`; ctx.textBaseline = 'top';
  ctx.fillText(`Arbeitsfläche ${fmt(Bed.width)} × ${fmt(Bed.height)} mm`, sx, sy + sh + 8);
  ctx.textBaseline = 'alphabetic';
}
export const fmt = (n: number, digits = 1) => String(+n.toFixed(digits)).replace('.', ',');

/* ---- Overlay pieces, all in CSS pixels ---- */
export function drawRulers(ctx: CanvasRenderingContext2D, v: View, pal: Palette, mouse: Pt | null, sel: Box | null) {
  ctx.fillStyle = pal.surface; ctx.fillRect(0, 0, v.w, RULER); ctx.fillRect(0, 0, RULER, v.h);
  ctx.fillStyle = pal.line; ctx.fillRect(0, RULER - 1, v.w, 1); ctx.fillRect(RULER - 1, 0, 1, v.h);
  const major = [1, 5, 10, 20, 50, 100, 200, 500].find((s) => s * v.zoom >= 56) ?? 500;
  const minor = major / (major === 20 || major === 200 ? 4 : major === 5 || major === 50 || major === 500 ? 5 : 10);
  ctx.font = `10px ${pal.font}`; ctx.fillStyle = pal.muted; ctx.textBaseline = 'alphabetic';
  // Selection extent as a soft band on both rulers.
  if (sel) {
    ctx.fillStyle = pal.accentSoft;
    ctx.fillRect(Math.max(RULER, sel.minX * v.zoom + v.panX), 0, (sel.maxX - sel.minX) * v.zoom, RULER - 1);
    ctx.fillRect(0, Math.max(RULER, sel.minY * v.zoom + v.panY), RULER - 1, (sel.maxY - sel.minY) * v.zoom);
  }
  const tick = ctx.fillRect.bind(ctx);
  const color = pal.faint;
  const x0 = Math.floor((RULER - v.panX) / v.zoom / minor), x1 = Math.ceil((v.w - v.panX) / v.zoom / minor), ratioX = Math.round(major / minor);
  for (let i = x0; i <= x1; i++) {
    const mm = i * minor, x = Math.round(mm * v.zoom + v.panX); if (x < RULER) continue;
    const big = i % ratioX === 0; ctx.fillStyle = color; tick(x, big ? 10 : 18, 1, big ? 13 : 5);
    if (big) { ctx.fillStyle = pal.muted; ctx.fillText(fmt(mm), x + 3, 12); }
  }
  const y0 = Math.floor((RULER - v.panY) / v.zoom / minor), y1 = Math.ceil((v.h - v.panY) / v.zoom / minor);
  for (let i = y0; i <= y1; i++) {
    const mm = i * minor, y = Math.round(mm * v.zoom + v.panY); if (y < RULER) continue;
    const big = i % ratioX === 0; ctx.fillStyle = color; tick(big ? 10 : 18, y, big ? 13 : 5, 1);
    if (big) { ctx.save(); ctx.translate(11, y + 3); ctx.rotate(-Math.PI / 2); ctx.fillStyle = pal.muted; ctx.textAlign = 'right'; ctx.fillText(fmt(mm), 0, 0); ctx.restore(); }
  }
  if (mouse) {
    ctx.fillStyle = pal.accent;
    const mx = Math.round(mouse.x * v.zoom + v.panX), my = Math.round(mouse.y * v.zoom + v.panY);
    if (mx >= RULER) ctx.fillRect(mx, 0, 1, RULER - 1);
    if (my >= RULER) ctx.fillRect(0, my, RULER - 1, 1);
  }
  ctx.fillStyle = pal.surface; ctx.fillRect(0, 0, RULER - 1, RULER - 1);
  ctx.fillStyle = pal.faint; ctx.font = `10px ${pal.font}`; ctx.textAlign = 'center'; ctx.fillText('mm', RULER / 2 - 0.5, RULER / 2 + 3.5); ctx.textAlign = 'left';
}

export function pill(ctx: CanvasRenderingContext2D, pal: Palette, text: string, x: number, y: number, tone: 'accent' | 'bad' | 'warn' | 'plain') {
  ctx.font = `500 11px ${pal.font}`;
  const w = ctx.measureText(text).width + 14, h = 20;
  const px = Math.round(x), py = Math.round(y);
  ctx.fillStyle = tone === 'accent' ? pal.accent : pal.surface;
  ctx.beginPath(); ctx.roundRect(px, py, w, h, 5); ctx.fill();
  if (tone !== 'accent') { ctx.strokeStyle = tone === 'bad' ? pal.bad : tone === 'warn' ? pal.warn : pal.line2; ctx.lineWidth = 1; ctx.beginPath(); ctx.roundRect(px + 0.5, py + 0.5, w - 1, h - 1, 4.5); ctx.stroke(); }
  ctx.fillStyle = tone === 'accent' ? pal.accentInk : tone === 'bad' ? pal.bad : tone === 'warn' ? pal.warn : pal.text;
  ctx.textBaseline = 'middle'; ctx.fillText(text, px + 7, py + h / 2 + 0.5); ctx.textBaseline = 'alphabetic';
  return w;
}

/* ---- Warnings on the object ---- */
export interface Warned { box: Box; kind: 'outside' | 'park' }
const warnCache = new WeakMap<Element, 'outside' | 'park' | null>();
let warnBed = '';
function warningOf(e: Element, layers: Map<string, Layer>): 'outside' | 'park' | null {
  const l = layers.get(e.layerId); if (!l || !l.output || !l.visible) return null;
  let w = warnCache.get(e);
  if (w === undefined) {
    const b = worldBounds(e);
    w = !b ? null : !insideWork(b) ? 'outside' : touchesPark(b) ? 'park' : null;
    warnCache.set(e, w);
  }
  return w;
}
/** Per object or group; many at once collapse into one note around all of them. */
export function warningsOf(doc: Doc): Warned[] {
  const key = `${Bed.width}|${Bed.height}|${Bed.parkX}|${Bed.parkY}`;
  if (key !== warnBed) { warnBed = key; for (const e of doc.elements) warnCache.delete(e); }
  const layers = new Map(doc.layers.map((l) => [l.id, l]));
  const units = new Map<string, Warned>();
  for (const e of doc.elements) {
    if (e.plate !== doc.activePlate) continue;
    const w = warningOf(e, layers); if (!w) continue;
    const box = worldBounds(e)!, k = (e.groupId ?? e.id), u = units.get(k);
    if (u) { u.box = boxUnion(box, u.box); if (w === 'outside') u.kind = 'outside'; } else units.set(k, { box, kind: w });
  }
  const list = [...units.values()];
  if (list.length <= 6) return list;
  return (['outside', 'park'] as const).flatMap((kind) => {
    const same = list.filter((x) => x.kind === kind); if (!same.length) return [];
    return [{ kind, box: same.reduce<Box>((a, x) => boxUnion(x.box, a), same[0].box) }];
  });
}
export const WARN_TEXT = { outside: 'Ragt über die Arbeitsfläche', park: 'Liegt in der Park-Ecke' };

/* ---- Node editing ---- */
export function drawNodes(ctx: CanvasRenderingContext2D, v: View, pal: Palette, e: Element, curves: CurvePath[], sel: { path: number; node: number } | null) {
  const s = (p: Pt) => { const q = applyT(e.transform, p); return { x: q.x * v.zoom + v.panX, y: q.y * v.zoom + v.panY }; };
  ctx.lineWidth = 1;
  curves.forEach((c, pi) => {
    c.nodes.forEach((n, ni) => {
      const active = sel?.path === pi && sel.node === ni;
      const near = sel?.path === pi && (Math.abs(sel.node - ni) === 1 || Math.abs(sel.node - ni) === c.nodes.length - 1);
      const show = active || near || (n.smooth && c.nodes.length <= 12);
      if (!show) return;
      const p = s(n);
      for (const h of [handleIn(n), handleOut(n)]) {
        if (Math.hypot(h.x - n.x, h.y - n.y) < 1e-6) continue;
        const q = s(h);
        ctx.strokeStyle = pal.accent; ctx.globalAlpha = 0.6; ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke(); ctx.globalAlpha = 1;
        ctx.fillStyle = pal.surface; ctx.strokeStyle = pal.accent; ctx.beginPath(); ctx.arc(q.x, q.y, 3.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      }
    });
    c.nodes.forEach((n, ni) => {
      const p = s(n), active = sel?.path === pi && sel.node === ni, r = 3.5;
      ctx.fillStyle = active ? pal.accent : pal.surface; ctx.strokeStyle = pal.accent;
      if (n.smooth) { ctx.beginPath(); ctx.arc(p.x, p.y, r + 0.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); }
      else { const x = Math.round(p.x) - r + 0.5, y = Math.round(p.y) - r + 0.5; ctx.fillRect(x, y, r * 2, r * 2); ctx.strokeRect(x, y, r * 2, r * 2); }
    });
  });
}

