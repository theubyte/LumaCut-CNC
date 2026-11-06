import { Bed, boundsOf, type Box, type Element, type ImageAdjust, type ImageMode, type Layer, newElement, type Poly, type Raster } from '../model';

/** Generators are pure: settings in, geometry out. The workshop view turns a result into document elements. */
export class GenError extends Error {}

/** A process layer of the document ("Gravieren", "Linie", "Schneiden") or the key of a layer in `GenResult.layers`. */
export type LayerRef = string;
export interface GenImage { raster: Raster; widthMm: number; heightMm: number; mode: ImageMode; adjust: ImageAdjust }
export interface GenPart { name: string; layer: LayerRef; paths: Poly[]; plate?: number; group?: string; image?: GenImage; x?: number; y?: number }
export interface GenLayer { key: string; name: string; base: 'Gravieren' | 'Linie' | 'Schneiden'; color?: number; over: Partial<Layer> }
export interface GenResult {
  parts: GenPart[];
  /** Layers the result brings along; reused by name when the document already has them. */
  layers?: GenLayer[];
  /** What the operator should know about the result. */
  notes?: string[];
  warnings?: string[];
  /** `center` puts each plate's content in the middle of the work area, `keep` uses the coordinates as they are. */
  placement?: 'center' | 'keep';
}

export const partBounds = (p: GenPart): Box | null => {
  if (p.image) { const x = p.x ?? 0, y = p.y ?? 0; return { minX: x, minY: y, maxX: x + p.image.widthMm, maxY: y + p.image.heightMm }; }
  return boundsOf(p.paths);
};
export function resultBounds(parts: GenPart[]): Box | null {
  let b: Box | null = null;
  for (const p of parts) {
    const q = partBounds(p); if (!q) continue;
    b = b ? { minX: Math.min(b.minX, q.minX), minY: Math.min(b.minY, q.minY), maxX: Math.max(b.maxX, q.maxX), maxY: Math.max(b.maxY, q.maxY) } : q;
  }
  return b;
}
export const plateCountOf = (r: GenResult) => r.parts.reduce((n, p) => Math.max(n, (p.plate ?? 0) + 1), r.parts.length ? 1 : 0);

/** Work-area offset per plate for `center`, zero for `keep`. */
export function plateOffset(r: GenResult, plate: number): { x: number; y: number } {
  if (r.placement === 'keep') return { x: 0, y: 0 };
  const b = resultBounds(r.parts.filter((p) => (p.plate ?? 0) === plate));
  return b ? { x: Bed.width / 2 - (b.minX + b.maxX) / 2, y: Bed.height / 2 - (b.minY + b.maxY) / 2 } : { x: 0, y: 0 };
}

/** Elements in work-area coordinates, the same structure as on Android: local paths from 0/0, position in the transform. */
export function resultElements(r: GenResult, layerId: (ref: LayerRef) => string, firstPlate = 0): Element[] {
  const groups = new Map<string, string>();
  const out: Element[] = [];
  const offsets = new Map<number, { x: number; y: number }>();
  for (const p of r.parts) {
    const plate = p.plate ?? 0;
    if (!offsets.has(plate)) offsets.set(plate, plateOffset(r, plate));
    const o = offsets.get(plate)!;
    const b = partBounds(p);
    if (!b) continue;
    const key = p.group ? `${plate}|${p.group}` : null;
    const groupId = key ? groups.get(key) ?? (groups.set(key, crypto.randomUUID()), groups.get(key)!) : null;
    const transform = { x: b.minX + o.x, y: b.minY + o.y, scaleX: 1, scaleY: 1, rotation: 0 };
    if (p.image) out.push(newElement(layerId(p.layer), p.name, { transform, raster: p.image.raster, imageWidthMm: p.image.widthMm, imageHeightMm: p.image.heightMm, imageMode: p.image.mode, adjust: p.image.adjust, groupId, plate: firstPlate + plate }));
    else out.push(newElement(layerId(p.layer), p.name, { transform, paths: p.paths.map((poly) => poly.map((q) => ({ x: q.x - b.minX, y: q.y - b.minY }))), groupId, plate: firstPlate + plate }));
  }
  return out;
}
