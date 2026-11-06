import { booleanShapes } from '@/core/boolean';
import { Contour, Mask } from '@/core/contour';
import { curvesFromPaths, ellipseCurve, flattenCurves, mapCurves, rectCurve } from '@/core/curves';
import { importFile, IMPORT_FILTERS } from '@/core/import';
import {
  applyT, Bed, boundsOf, boxCenter, boxH, boxUnion, boxW, type CurvePath, type Doc, type Element, IDENTITY, imageCorners, invertT,
  isImage, type Layer, Limits, newElement, newId, newLayer, plateElements, type Poly, type Pt, STANDARD_LAYERS, type Box, worldBounds, worldPaths,
} from '@/core/model';
import { splitParts } from '@/core/parts';
import { grayOf, rasterOf } from '@/core/raster';
import { textPaths } from '@/core/text';
import { vectorize, type VectorizeOptions } from '@/core/vectorize';
import { pickFiles, type FileFilter } from '@/platform';
import { useDoc } from '@/store/doc';
import { toast } from '@/ui/kit';
import { useEditor } from './editor';

/** Every function here is one user action and therefore one undo step. */
const docS = () => useDoc.getState();

export const selectedEls = (): Element[] => { const s = docS(), ids = new Set(s.selection); return s.doc.elements.filter((e) => ids.has(e.id)); };
export function selectionBox(els = selectedEls()): Box | null { let b: Box | null = null; for (const e of els) { const w = worldBounds(e); if (w) b = boxUnion(w, b); } return b; }
const withIds = (d: Doc, ids: Set<string>, f: (e: Element) => Element): Doc => ({ ...d, elements: d.elements.map((e) => (ids.has(e.id) ? f(e) : e)) });
const selIds = () => new Set(docS().selection);

export const editableLayer = (d: Doc, id: string) => { const l = d.layers.find((x) => x.id === id); return !!l && l.visible && !l.locked; };
/** The selection expands to whole groups; `single` picks one member. */
export function expandGroup(d: Doc, e: Element): string[] { return e.groupId ? d.elements.filter((x) => x.groupId === e.groupId && x.plate === e.plate).map((x) => x.id) : [e.id]; }
export const activeLayer = (): Layer => { const s = docS(); return s.doc.layers.find((l) => l.id === s.activeLayerId) ?? s.doc.layers[0]; };

/* ---- Moving and transforming ---- */
export const movedBy = (e: Element, dx: number, dy: number): Element => ({ ...e, transform: { ...e.transform, x: e.transform.x + dx, y: e.transform.y + dy } });
export function nudge(dx: number, dy: number) { const ids = selIds(); if (ids.size) docS().commit((d) => withIds(d, ids, (e) => movedBy(e, dx, dy))); }

const rotatePt = (p: Pt, c: Pt, deg: number): Pt => { const r = deg * Math.PI / 180, cs = Math.cos(r), s = Math.sin(r), dx = p.x - c.x, dy = p.y - c.y; return { x: c.x + dx * cs - dy * s, y: c.y + dx * s + dy * cs }; };
export function rotatedAbout(e: Element, c: Pt, deg: number): Element {
  const t = rotatePt(e.transform, c, deg);
  return { ...e, transform: { ...e.transform, x: t.x, y: t.y, rotation: norm180(e.transform.rotation + deg) } };
}
const norm180 = (a: number) => { let r = a % 360; if (r > 180) r -= 360; if (r <= -180) r += 360; return r; };

/** Paths in world coordinates, transform reduced to a translation. Curves follow. */
function baked(e: Element, map: (p: Pt) => Pt): Element {
  const world = e.paths.map((poly) => poly.map((p) => map(applyT(e.transform, p))));
  const b = boundsOf(world); if (!b) return e;
  const local = (p: Pt) => ({ x: p.x - b.minX, y: p.y - b.minY });
  const next: Element = { ...e, transform: { ...IDENTITY, x: b.minX, y: b.minY }, paths: world.map((poly) => poly.map(local)) };
  if (e.curves) next.curves = mapCurves(e.curves, (p) => local(map(applyT(e.transform, p))));
  return next;
}

/** Axis-aligned scale about `a`. A rotated shape cannot express that in its transform, so it is baked; images stay proportional. */
export function scaledAbout(e: Element, a: Pt, kx: number, ky: number): Element {
  const t = e.transform, rotated = Math.abs(t.rotation % 180) > 1e-6, uneven = Math.abs(kx - ky) > 1e-9;
  if (rotated && uneven) {
    if (!isImage(e)) return baked(e, (p) => ({ x: a.x + (p.x - a.x) * kx, y: a.y + (p.y - a.y) * ky }));
    kx = ky = Math.max(kx, ky);
  }
  return { ...e, transform: { ...t, x: a.x + (t.x - a.x) * kx, y: a.y + (t.y - a.y) * ky, scaleX: t.scaleX * kx, scaleY: t.scaleY * ky } };
}
/** Scale in the element's own axes with `anchor` (world) staying where it is. */
export function scaledLocal(e: Element, anchor: Pt, kx: number, ky: number): Element {
  const t = e.transform, a = invertT(t, anchor), scaleX = t.scaleX * kx, scaleY = t.scaleY * ky;
  const moved = applyT({ ...t, x: 0, y: 0, scaleX, scaleY }, a);
  return { ...e, transform: { ...t, scaleX, scaleY, x: anchor.x - moved.x, y: anchor.y - moved.y } };
}

export function setPosition(x: number | null, y: number | null) {
  const b = selectionBox(); if (!b) return;
  const dx = x == null ? 0 : x - b.minX, dy = y == null ? 0 : y - b.minY, ids = selIds();
  docS().commit((d) => withIds(d, ids, (e) => movedBy(e, dx, dy)));
}
export const localSize = (e: Element): { w: number; h: number } | null => {
  if (isImage(e)) return { w: e.imageWidthMm * Math.abs(e.transform.scaleX), h: e.imageHeightMm * Math.abs(e.transform.scaleY) };
  const b = boundsOf(e.paths); return b ? { w: boxW(b) * Math.abs(e.transform.scaleX), h: boxH(b) * Math.abs(e.transform.scaleY) } : null;
};
/** Width and/or height of the selection; one rotated element keeps its own axes. */
export function setSize(w: number | null, h: number | null, keepAspect: boolean) {
  const els = selectedEls(), b = selectionBox(els); if (!b) return;
  const one = els.length === 1 ? els[0] : null, cur = one ? localSize(one) : { w: boxW(b), h: boxH(b) }; if (!cur) return;
  let kx = w != null && cur.w > 0 ? Math.max(w, 0.01) / cur.w : 1, ky = h != null && cur.h > 0 ? Math.max(h, 0.01) / cur.h : 1;
  if (keepAspect) { if (w != null) ky = kx; else kx = ky; }
  const ids = selIds(), a = { x: b.minX, y: b.minY };
  docS().commit((d) => withIds(d, ids, (e) => {
    if (!one) return scaledAbout(e, a, kx, ky);
    const next = scaledLocal(e, a, kx, ky), nb = worldBounds(next);
    return nb ? movedBy(next, b.minX - nb.minX, b.minY - nb.minY) : next;
  }));
}
export function setRotation(deg: number) {
  const els = selectedEls(), b = selectionBox(els); if (!b) return;
  const c = boxCenter(b), ids = selIds(), cur = els.length === 1 ? els[0].transform.rotation : 0;
  docS().commit((d) => withIds(d, ids, (e) => rotatedAbout(e, c, deg - cur)));
}

/* ---- Align, distribute, mirror ---- */
const unitsOf = (els: Element[]) => { const m = new Map<string, Element[]>(); for (const e of els) { const k = e.groupId ?? e.id; m.set(k, [...(m.get(k) ?? []), e]); } return [...m.values()]; };
export type AlignMode = 'left' | 'centerX' | 'right' | 'top' | 'centerY' | 'bottom';
/** Against the selection; a single unit aligns to the work area. */
export function align(mode: AlignMode) {
  const els = selectedEls(), units = unitsOf(els); if (!units.length) return;
  const ref = units.length > 1 ? selectionBox(els)! : { minX: 0, minY: 0, maxX: Bed.width, maxY: Bed.height };
  const off = new Map<string, Pt>();
  for (const u of units) {
    const b = selectionBox(u); if (!b) continue;
    const d = ({ left: { x: ref.minX - b.minX, y: 0 }, centerX: { x: boxCenter(ref).x - boxCenter(b).x, y: 0 }, right: { x: ref.maxX - b.maxX, y: 0 },
      top: { x: 0, y: ref.minY - b.minY }, centerY: { x: 0, y: boxCenter(ref).y - boxCenter(b).y }, bottom: { x: 0, y: ref.maxY - b.maxY } } as Record<AlignMode, Pt>)[mode];
    for (const e of u) off.set(e.id, d);
  }
  applyOffsets(off);
}
function applyOffsets(off: Map<string, Pt>) {
  docS().commit((d) => ({ ...d, elements: d.elements.map((e) => { const o = off.get(e.id); return o ? movedBy(e, o.x, o.y) : e; }) }));
}
/** Equal gaps; the outermost two stay. */
export function distribute(horizontal: boolean) {
  const units = unitsOf(selectedEls()).map((u) => ({ u, b: selectionBox(u)! })).filter((x) => x.b);
  if (units.length < 3) { toast('Zum Verteilen mindestens drei Objekte wählen', 'info'); return; }
  const lo = (b: Box) => (horizontal ? b.minX : b.minY), size = (b: Box) => (horizontal ? boxW(b) : boxH(b));
  units.sort((a, b) => lo(a.b) - lo(b.b));
  const end = Math.max(...units.map((x) => lo(x.b) + size(x.b))), gap = (end - lo(units[0].b) - units.reduce((s, x) => s + size(x.b), 0)) / (units.length - 1);
  let at = lo(units[0].b); const off = new Map<string, Pt>();
  for (const x of units) { const d = at - lo(x.b); for (const e of x.u) off.set(e.id, horizontal ? { x: d, y: 0 } : { x: 0, y: d }); at += size(x.b) + gap; }
  applyOffsets(off);
}
function mirroredImage(e: Element, horizontal: boolean, m: (p: Pt) => Pt): Element {
  const r = e.raster!, src = grayOf(r), w = r.width, h = r.height, out = new Uint8Array(src.length);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) out[y * w + x] = src[horizontal ? y * w + (w - 1 - x) : (h - 1 - y) * w + x];
  const b = boundsOf([imageCorners(e)])!, c = m(boxCenter(b)), rotation = norm180(-e.transform.rotation), t = { ...e.transform, rotation, x: 0, y: 0 };
  const ctrLocal = applyT(t, { x: e.imageWidthMm / 2, y: e.imageHeightMm / 2 });
  return { ...e, raster: rasterOf(w, h, out), transform: { ...t, x: c.x - ctrLocal.x, y: c.y - ctrLocal.y } };
}
export function mirror(horizontal: boolean) {
  const b = selectionBox(), ids = selIds(); if (!b) return;
  const m = (q: Pt): Pt => (horizontal ? { x: b.minX + b.maxX - q.x, y: q.y } : { x: q.x, y: b.minY + b.maxY - q.y });
  docS().commit((d) => withIds(d, ids, (e) => (isImage(e) ? mirroredImage(e, horizontal, m) : baked(e, m))));
}

/* ---- Combine and take apart ---- */
export const BOOL_LABEL = { union: 'Verschweißen', subtract: 'Abziehen', intersect: 'Schnittmenge' } as const;
export function booleanSel(op: keyof typeof BOOL_LABEL) {
  const shapes = selectedEls().filter((e) => !isImage(e));
  if (shapes.length < 2) { toast('Mindestens zwei Formen wählen, Bilder gehen nicht', 'info'); return; }
  let res: Poly[];
  try { res = booleanShapes(op, shapes.map(worldPaths)); } catch (e) { toast(`${BOOL_LABEL[op]} ging nicht: ${(e as Error).message}`, 'bad'); return; }
  const b = boundsOf(res);
  if (!res.length || !b) { toast('Kein Ergebnis: die Formen überschneiden sich nicht', 'info'); return; }
  const el = newElement(shapes[0].layerId, BOOL_LABEL[op], { transform: { ...IDENTITY, x: b.minX, y: b.minY }, paths: res.map((p) => p.map((q) => ({ x: q.x - b.minX, y: q.y - b.minY }))), plate: shapes[0].plate });
  const gone = new Set(shapes.map((e) => e.id));
  docS().commit((d) => ({ ...d, elements: [...d.elements.filter((e) => !gone.has(e.id)), el] }));
  docS().select([el.id]);
}
export const canSplit = (els: Element[]) => els.some((e) => !isImage(e) && e.text == null && e.paths.length >= 2);
export function splitSel() {
  const pieces = new Map(selectedEls().map((e) => [e.id, splitParts(e).map((p) => { const { curves: _c, ...rest } = p; return rest as Element; })]));
  const made = [...pieces.values()].filter((p) => p.length > 1).reduce((s, p) => s + p.length, 0);
  if (!made) { toast('Besteht nur aus einem Teil', 'info'); return; }
  docS().commit((d) => ({ ...d, elements: d.elements.flatMap((e) => pieces.get(e.id) ?? [e]) }));
  docS().select([...pieces.values()].flat().map((e) => e.id));
  toast(`In ${made} Teile aufgeteilt`, 'ok');
}
export function textToPaths() {
  const ids = selIds();
  docS().commit((d) => withIds(d, ids, (e) => (e.text != null ? { ...e, text: null, kind: 'Pfade' } : e)));
}
export function group() {
  const ids = selIds(); if (ids.size < 2) return; const gid = newId();
  docS().commit((d) => withIds(d, ids, (e) => ({ ...e, groupId: gid })));
}
export function ungroup() {
  const ids = selIds();
  if (selectedEls().some((e) => e.groupId)) docS().commit((d) => withIds(d, ids, (e) => ({ ...e, groupId: null })));
}
/** Outline of the dark parts of a picture, computed in its own pixels and then placed like the picture. */
function imageContour(im: Element, offsetMm: number, outerOnly: boolean): Poly[] {
  const r = im.raster!, gray = grayOf(r), data = new Uint8Array(gray.length);
  for (let i = 0; i < gray.length; i++) data[i] = gray[i] < 128 ? 1 : 0;
  const pxPerMm = r.width / Math.max(im.imageWidthMm, 0.01), k = Math.abs(im.transform.scaleX) || 1;
  const local = Contour.fromMask(new Mask(r.width, r.height, data, pxPerMm, 0, 0), offsetMm / k, 0, outerOnly);
  return local.map((p) => p.map((q) => applyT(im.transform, q)));
}
export function makeContour(offsetMm: number, removeSource: boolean, outerOnly: boolean): boolean {
  const els = selectedEls(), src = els.filter((e) => !isImage(e)), images = els.filter(isImage);
  let polys: Poly[] = [];
  try {
    if (src.length) polys = Contour.fromPolys(src.flatMap(worldPaths), offsetMm, 8, outerOnly);
    for (const im of images) polys.push(...imageContour(im, offsetMm, outerOnly));
  } catch (e) { toast(`Kontur ging nicht: ${(e as Error).message}`, 'bad'); return false; }
  const b = boundsOf(polys);
  if (!b) { toast('Keine Kontur gefunden', 'info'); return false; }
  const cutLayer = docS().layerByName('Schneiden');
  const gid = removeSource ? null : els[0].groupId ?? newId();
  const contour = newElement(cutLayer.id, 'Kontur', { transform: { ...IDENTITY, x: b.minX, y: b.minY }, paths: polys.map((p) => p.map((q) => ({ x: q.x - b.minX, y: q.y - b.minY }))), groupId: gid, plate: els[0].plate });
  const ids = selIds();
  docS().commit((d) => ({ ...d, elements: [...(removeSource ? d.elements.filter((e) => !ids.has(e.id)) : d.elements.map((e) => (ids.has(e.id) ? { ...e, groupId: gid } : e))), contour] }));
  docS().select(removeSource ? [contour.id] : [...ids, contour.id]);
  return true;
}
export function vectorizeSel(opts: VectorizeOptions, removeSource: boolean): boolean {
  const im = selectedEls().find(isImage); if (!im) return false;
  let polys: Poly[];
  try { polys = vectorize(grayOf(im.raster!), im.raster!.width, im.raster!.height, { widthMm: im.imageWidthMm, heightMm: im.imageHeightMm, ...opts }); }
  catch (e) { toast(`Vektorisieren ging nicht: ${(e as Error).message}`, 'bad'); return false; }
  if (!polys.length) { toast('Nichts gefunden. Schwellwert ändern.', 'info'); return false; }
  const el = newElement(im.layerId, 'Vektor', { transform: { ...im.transform }, paths: polys, plate: im.plate });
  docS().commit((d) => ({ ...d, elements: [...(removeSource ? d.elements.filter((e) => e.id !== im.id) : d.elements), el] }));
  docS().select([el.id]);
  toast(`${polys.length} Pfade erzeugt`, 'ok');
  return true;
}

/* ---- Clipboard, duplicate, delete, order ---- */
let clipboard: Element[] = [];
let pasteShift = 0;
function copies(els: Element[], dx: number, dy: number, plate?: number): Element[] {
  const groups = new Map<string, string>();
  return els.map((e) => {
    const groupId = e.groupId ? groups.get(e.groupId) ?? (groups.set(e.groupId, newId()), groups.get(e.groupId)!) : null;
    return { ...movedBy(e, dx, dy), id: newId(), groupId, plate: plate ?? e.plate };
  });
}
export function duplicate(dx = 5, dy = 5) {
  const c = copies(selectedEls(), dx, dy); if (!c.length) return;
  docS().commit((d) => ({ ...d, elements: [...d.elements, ...c] }));
  docS().select(c.map((e) => e.id));
}
export function copySel() { clipboard = selectedEls(); pasteShift = 0; }
export function cutSel() { const s = selectedEls(); if (!s.length) return; clipboard = s; pasteShift = -5; deleteSel(); }
export function paste() {
  if (!clipboard.length) return;
  pasteShift += 5;
  const d0 = docS().doc, known = new Set(d0.layers.map((l) => l.id));
  const c = copies(clipboard, pasteShift, pasteShift, d0.activePlate).map((e) => (known.has(e.layerId) ? e : { ...e, layerId: activeLayer().id }));
  docS().commit((d) => ({ ...d, elements: [...d.elements, ...c] }));
  docS().select(c.map((e) => e.id));
}
export function deleteSel() {
  const ids = selIds(); if (!ids.size) return;
  docS().commit((d) => ({ ...d, elements: d.elements.filter((e) => !ids.has(e.id)) }));
  docS().select([]);
}
export function selectAll() { const d = docS().doc; docS().select(plateElements(d).filter((e) => editableLayer(d, e.layerId)).map((e) => e.id)); }
export function toFront(front: boolean) {
  const ids = selIds(); if (!ids.size) return;
  docS().commit((d) => { const on = d.elements.filter((e) => ids.has(e.id)), off = d.elements.filter((e) => !ids.has(e.id)); return { ...d, elements: front ? [...off, ...on] : [...on, ...off] }; });
}
export function centerInWork() {
  const b = selectionBox(); if (!b) return; const c = boxCenter(b), dx = Bed.width / 2 - c.x, dy = Bed.height / 2 - c.y, ids = selIds();
  docS().commit((d) => withIds(d, ids, (e) => movedBy(e, dx, dy)));
}
/** Pushes the selection into the work area, out of the park corner where that is possible. */
export function keepInside() {
  const b = selectionBox(); if (!b) return;
  let dx = 0, dy = 0;
  if (boxW(b) <= Bed.width) { if (b.minX < 0) dx = -b.minX; else if (b.maxX > Bed.width) dx = Bed.width - b.maxX; }
  if (boxH(b) <= Bed.height) { if (b.minY < 0) dy = -b.minY; else if (b.maxY > Bed.height) dy = Bed.height - b.maxY; }
  const parkLeft = Bed.width - Bed.parkX;
  if (b.maxX + dx > parkLeft && b.minY + dy < Bed.parkY) {
    if (boxW(b) <= parkLeft && (b.maxX + dx - parkLeft) <= (Bed.parkY - b.minY - dy)) dx -= b.maxX + dx - parkLeft;
    else if (b.maxY + (Bed.parkY - b.minY - dy) + dy <= Bed.height) dy += Bed.parkY - b.minY - dy;
  }
  if (!dx && !dy) { toast('Passt nicht auf die Arbeitsfläche. Erst verkleinern.', 'warn'); return; }
  const ids = selIds(); docS().commit((d) => withIds(d, ids, (e) => movedBy(e, dx, dy)));
}

/* ---- Creating ---- */
export function addCurveElement(kind: string, curves: CurvePath[], origin: Pt) {
  const paths = flattenCurves(curves);
  const el = newElement(activeLayer().id, kind, { transform: { ...IDENTITY, x: origin.x, y: origin.y }, paths, curves });
  docS().addElements([el]);
  return el;
}
export const addRect = (b: Box) => addCurveElement('Rechteck', [rectCurve(boxW(b), boxH(b))], { x: b.minX, y: b.minY });
export const addEllipse = (b: Box) => addCurveElement('Ellipse', [ellipseCurve(boxW(b), boxH(b))], { x: b.minX, y: b.minY });
/** Nodes in world coordinates; the element's origin becomes their top-left corner. */
export function addDrawn(kind: string, path: CurvePath) {
  const flat = flattenCurves([path]); const b = boundsOf(flat); if (!b) return;
  const shifted = mapCurves([path], (p) => ({ x: p.x - b.minX, y: p.y - b.minY }));
  addCurveElement(kind, shifted, { x: b.minX, y: b.minY });
}
export async function addText(at: Pt, text = 'Text', sizeMm = 10) {
  const family = 'sans-serif';
  const paths = await textPaths(text, sizeMm, false, family);
  const el = newElement(activeLayer().id, 'Text', { transform: { ...IDENTITY, x: at.x, y: at.y }, paths, text, fontSizeMm: sizeMm, fontFamily: family });
  docS().addElements([el]);
  useEditor.getState().set({ focusTextId: el.id });
}
/** Live text edit: the caller checkpoints once, each keystroke mutates. Newest wins when font loading overlaps. */
let textGen = 0;
export async function updateText(id: string, patch: Partial<Pick<Element, 'text' | 'fontSizeMm' | 'bold' | 'fontFamily'>>, undoStep: boolean) {
  const e = docS().doc.elements.find((x) => x.id === id); if (!e) return;
  const next = { ...e, ...patch }, gen = ++textGen;
  const paths = await textPaths(next.text ?? '', next.fontSizeMm, next.bold, next.fontFamily);
  if (gen !== textGen) return;
  const apply = (d: Doc) => withIds(d, new Set([id]), (x) => ({ ...x, ...patch, paths }));
  if (undoStep) docS().commit(apply); else docS().mutate(apply);
}

/* ---- Layers ---- */
export function updateLayer(id: string, patch: Partial<Layer> | ((l: Layer) => Partial<Layer>)) {
  docS().commit((d) => ({ ...d, layers: d.layers.map((l) => (l.id === id ? { ...l, ...(typeof patch === 'function' ? patch(l) : patch) } : l)) }));
}
/** Keeps the per-pass focus drop within the machine limit, as on Android. */
export function safeZStep(passes: number, z: number) { return passes > 1 ? Math.max(0, Math.min(z, Limits.Z_STEP[1], Limits.MAX_FOCUS_DROP_MM / (passes - 1))) : 0; }
const PALETTE = [0xFFFFB45C, 0xFFB98CFF, 0xFFFF8AD8, 0xFF9BE15D, 0xFF5CE1E6];
export function addLayer() {
  const d = docS().doc, taken = new Set(d.layers.map((l) => l.name));
  let k = 1; while (taken.has(`Ebene ${k}`)) k++;
  const l = newLayer(`Ebene ${k}`, PALETTE[d.layers.length % PALETTE.length], 'LINE', { powerPct: 50, speed: 1200 });
  docS().commit((x) => ({ ...x, layers: [...x.layers, l] }));
  docS().setActiveLayer(l.id);
}
/** Layers nothing lies on go away, except the standard ones, which only hide. Like `withoutEmptyLayers` on Android. */
export const shownLayers = (d: Doc, keep: string): Layer[] => { const used = new Set(d.elements.map((e) => e.layerId)); return d.layers.filter((l) => used.has(l.id) || (l.id === keep && !STANDARD_LAYERS.has(l.name))); };
export function deleteLayer(id: string) {
  const s = docS();
  s.commit((d) => {
    const left = d.layers.filter((l) => l.id !== id || STANDARD_LAYERS.has(l.name));
    return { ...d, layers: left, elements: d.elements.filter((e) => e.layerId !== id) };
  });
  if (s.activeLayerId === id) { const d = docS().doc; docS().setActiveLayer(d.layers.find((l) => l.name === 'Gravieren')?.id ?? d.layers[0].id); }
  docS().select(docS().selection.filter((x) => docS().doc.elements.some((e) => e.id === x)));
}
/** Layer `id` before the layer `before` (null = at the end). */
export function moveLayer(id: string, before: string | null) {
  docS().commit((d) => {
    const l = d.layers.find((x) => x.id === id); if (!l || id === before) return d;
    const rest = d.layers.filter((x) => x.id !== id), at = before ? rest.findIndex((x) => x.id === before) : rest.length;
    const layers = [...rest.slice(0, at), l, ...rest.slice(at)];
    return layers.every((x, i) => x === d.layers[i]) ? d : { ...d, layers };
  });
}
export function moveSelectionToLayer(id: string) {
  const ids = selIds(); if (!ids.size) return;
  docS().commit((d) => (d.elements.some((e) => ids.has(e.id) && e.layerId !== id) ? withIds(d, ids, (e) => ({ ...e, layerId: id })) : d));
}
export type Process = 'Gravieren' | 'Linie' | 'Schneiden';
/** What the layer does. Own layers remember it in an optional field. */
export const processOf = (l: Layer): Process => (STANDARD_LAYERS.has(l.name) ? l.name as Process : l.mode === 'FILL' ? 'Gravieren' : (l as Layer & { process?: Process }).process ?? 'Linie');
/** A standard layer is its process: changing it moves the content to the other standard layer. An own layer changes itself. */
export function setProcess(l: Layer, p: Process) {
  if (processOf(l) === p) return;
  if (!STANDARD_LAYERS.has(l.name)) { updateLayer(l.id, { mode: p === 'Gravieren' ? 'FILL' : 'LINE', process: p } as Partial<Layer>); return; }
  const n = docS().doc.elements.filter((e) => e.layerId === l.id).length, target = docS().layerByName(p);
  docS().commit((d) => ({ ...d, elements: d.elements.map((e) => (e.layerId === l.id ? { ...e, layerId: target.id } : e)) }));
  docS().setActiveLayer(target.id);
  toast(`${n} ${n === 1 ? 'Teil' : 'Teile'} liegen jetzt auf ${p === 'Linie' ? 'Markieren' : p}`, 'info');
}

/* ---- Plates ---- */
export function setPlate(i: number) {
  const d = docS().doc; if (i < 0 || i >= d.plateCount || i === d.activePlate) return;
  useDoc.setState({ doc: { ...d, activePlate: i }, selection: [] });
}
export function addPlate() { docS().commit((d) => ({ ...d, plateCount: d.plateCount + 1, activePlate: d.plateCount })); docS().select([]); }
export function deletePlate(i: number) {
  docS().commit((d) => {
    if (d.plateCount <= 1) return d;
    return { ...d, elements: d.elements.filter((e) => e.plate !== i).map((e) => (e.plate > i ? { ...e, plate: e.plate - 1 } : e)), plateCount: d.plateCount - 1,
      activePlate: d.activePlate >= i ? Math.max(0, d.activePlate - 1) : d.activePlate };
  });
  docS().select([]);
}
export function moveSelectionToPlate(target: number) {
  const ids = selIds(), d0 = docS().doc; if (!ids.size || target === d0.activePlate) return;
  docS().commit((d) => { const q = target >= d.plateCount ? { ...d, plateCount: d.plateCount + 1 } : d; const t = Math.min(target, q.plateCount - 1); return { ...withIds(q, ids, (e) => ({ ...e, plate: t })), activePlate: t }; });
  docS().select([...ids]);
}

/* ---- Files ---- */
export const IMAGE_FILTERS: FileFilter[] = [{ name: 'Bilder', extensions: ['png', 'jpg', 'jpeg', 'webp', 'bmp'] }];
export async function importBytes(name: string, bytes: Uint8Array) {
  const s = docS(), before = s.past.length;
  const r = await importFile(name, bytes, { layerByName: s.layerByName, activeLayer: activeLayer() });
  if (r.layers?.length) docS().commit((d) => ({ ...d, layers: [...d.layers, ...r.layers!.filter((l) => !d.layers.some((x) => x.id === l.id))] }));
  if (!r.elements.length) { toast(r.warnings[0] ?? `In ${name} wurde nichts Verwendbares gefunden`, 'warn'); return; }
  docS().addElements(r.elements);
  // Layers created on the way and the new elements are one step for the user.
  const past = docS().past; if (past.length > before + 1) useDoc.setState({ past: past.slice(0, before + 1) });
  for (const w of r.warnings.slice(0, 2)) toast(w, 'warn');
  toast(`${name}: ${r.elements.length} ${r.elements.length === 1 ? 'Objekt' : 'Objekte'} eingefügt`, 'ok');
}
export async function importDialog(filters: FileFilter[] = IMPORT_FILTERS) {
  const files = await pickFiles(filters, true);
  for (const f of files) {
    try { await importBytes(f.name, f.bytes); } catch (e) { toast(`${f.name}: ${(e as Error).message}`, 'bad'); }
  }
}

export const curvesOf = (e: Element): CurvePath[] => e.curves ?? curvesFromPaths(e.paths);

/** Copies of the selection in place, already selected. For Alt+drag: the caller has set the undo checkpoint. */
export function spawnCopies(): Element[] {
  const c = copies(selectedEls(), 0, 0);
  docS().mutate((d) => ({ ...d, elements: [...d.elements, ...c] }));
  docS().select(c.map((e) => e.id));
  return c;
}
/** Bounds in the element's local coordinates. */
export const localBox = (e: Element): Box | null => (isImage(e) ? { minX: 0, minY: 0, maxX: e.imageWidthMm, maxY: e.imageHeightMm } : boundsOf(e.paths));
