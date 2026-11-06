import { PartSplitter } from '../parts';
import { boundsOf, boxCenter, boxH, boxUnion, boxW, Bed, type Box, type Pt } from '../model';
import type { EmbeddedImage, ImportItem, VectorImport } from './types';

/**
 * Port of ImportLayout.kt. Vector imports keep their original size. Fits as drawn: centred. Too big: the
 * top-level groups are packed in rows (5 mm apart, no rotating); if even that fails, the caller shrinks or spreads.
 */
export const GAP = 5;
const MARGIN = 1;

export interface ImportUnit { items: ImportItem[]; images: EmbeddedImage[]; box: Box }
export type FitKind = 'AS_IS' | 'PACKED' | 'PARTIAL';
export interface Layout { kind: FitKind; units: ImportUnit[]; offsets: (Pt | null)[] }
export interface Spread { plates: Layout[]; leftOut: number }
export const leftOut = (l: Layout) => l.offsets.filter((o) => o == null).length;

function unit(items: ImportItem[], images: EmbeddedImage[]): ImportUnit {
  let box = boundsOf(items.flatMap((i) => i.polys));
  for (const img of images) box = boxUnion(img.box, box);
  return { items, images, box: box! };
}

/** Items of `r`: the structured ones or the parts of PartSplitter; parts of one import share one group. */
export function itemsOf(r: VectorImport): ImportItem[] {
  if (r.items.length) return r.items;
  const parts = PartSplitter.split(r.polys).parts;
  const group = parts.length > 1 ? ['*'] : [];
  return parts.map((polys) => ({ polys, layerKey: null, fill: false, groups: group, name: null }));
}

export function unitsOf(r: VectorImport): ImportUnit[] {
  const byTop = new Map<string, ImportItem[]>();
  let single = 0;
  for (const item of itemsOf(r)) {
    const key = item.groups[0] ?? `#${single++}`;
    (byTop.get(key) ?? byTop.set(key, []).get(key)!).push(item);
  }
  const units = [...byTop.values()].map((items) => unit(items, []));
  for (const img of r.images) units.push(unit([], [img]));
  return units;
}

export const unionOf = (units: ImportUnit[]) => units.map((u) => u.box).reduce((a, b) => boxUnion(a, b));

/** One big group: its parts become the units. */
const explode = (units0: ImportUnit[]) => units0.length === 1
  ? [...units0[0].items.map((i) => unit([i], [])), ...units0[0].images.map((i) => unit([], [i]))]
  : units0;

export function arrange(units0: ImportUnit[], w = Bed.width, h = Bed.height): Layout {
  const all = unionOf(units0);
  if (boxW(all) <= w && boxH(all) <= h) {
    const c = boxCenter(all);
    const d = { x: w / 2 - c.x, y: h / 2 - c.y };
    return { kind: 'AS_IS', units: units0, offsets: units0.map(() => d) };
  }
  const units = explode(units0);
  const packed = shelf(units.map((u) => u.box), w, h);
  return { kind: packed.every((p) => p != null) ? 'PACKED' : 'PARTIAL', units, offsets: packed };
}

export function spread(units0: ImportUnit[], w = Bed.width, h = Bed.height, maxPlates = 20): Spread {
  const units = explode(units0);
  let rest = units.map((_, i) => i).filter((i) => boxW(units[i].box) <= w - 2 * MARGIN && boxH(units[i].box) <= h - 2 * MARGIN);
  const tooBig = units.length - rest.length;
  const plates: Layout[] = [];
  while (rest.length && plates.length < maxPlates) {
    const packed = shelf(rest.map((i) => units[i].box), w, h);
    const offsets: (Pt | null)[] = units.map(() => null);
    rest.forEach((i, k) => { offsets[i] = packed[k]; });
    plates.push({ kind: 'PACKED', units, offsets });
    rest = rest.filter((_, k) => packed[k] == null);
  }
  return { plates, leftOut: tooBig + rest.length };
}

/** Factor (at most 1) that shrinks everything into the work area with a 5 mm border. */
export function shrinkFactor(units: ImportUnit[], w = Bed.width, h = Bed.height, border = 5): number {
  const all = unionOf(units);
  return Math.min(1, (w - 2 * border) / Math.max(boxW(all), 1e-9), (h - 2 * border) / Math.max(boxH(all), 1e-9));
}

/**
 * Shelf packing, tallest first, rows from the top left; returns the translation per box or null.
 * `keepOut` (the park corner at the top right) shortens the rows that would run into it.
 */
export function shelf(boxes: Box[], w: number, h: number, gap = GAP, keepOut?: Box | null): (Pt | null)[] {
  const out: (Pt | null)[] = boxes.map(() => null);
  let x = MARGIN, y = MARGIN, rowH = 0;
  const right = (rowY: number, height: number) => keepOut && rowY < keepOut.maxY && rowY + height > keepOut.minY ? Math.min(w - MARGIN, keepOut.minX - MARGIN) : w - MARGIN;
  const order = boxes.map((_, i) => i).sort((a, b) => boxH(boxes[b]) - boxH(boxes[a]));
  for (const i of order) {
    const b = boxes[i], bw = boxW(b), bh = boxH(b);
    if (bw > w - 2 * MARGIN || bh > h - 2 * MARGIN) continue;
    let px = x, py = y, newRow = false;
    if (px + bw > right(py, Math.max(rowH, bh))) { px = MARGIN; py = y + rowH + gap; newRow = true; }
    if (py + bh > h - MARGIN) continue;
    if (px + bw > right(py, bh)) continue;
    out[i] = { x: px - b.minX, y: py - b.minY };
    x = px + bw + gap;
    if (newRow) { y = py; rowH = bh; } else rowH = Math.max(rowH, bh);
  }
  return out;
}
