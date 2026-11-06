import type { Box, Poly } from '../model';

export class ImportError extends Error {}

/** An image embedded in a design file, placed on the work plane (mm). */
export interface EmbeddedImage { bytes: Uint8Array; box: Box }
/** One drawable of a design file: paths, source layer (colour), filled or line, groups (outermost first). */
export interface ImportItem { polys: Poly[]; layerKey: string | null; fill: boolean; groups: string[]; name: string | null }
/** A layer of the source file in drawing order. */
export interface ImportLayerInfo { key: string; name: string; order: number; visible: boolean }
/** Vector geometry (mm, y down) plus embedded pictures; `skipped` says what could not be taken over. */
export interface VectorImport { polys: Poly[]; images: EmbeddedImage[]; skipped: string[]; items: ImportItem[]; layers: ImportLayerInfo[]; notes?: string[] }

export const vectorImport = (polys: Poly[], images: EmbeddedImage[] = [], skipped: string[] = [], items: ImportItem[] = [], layers: ImportLayerInfo[] = []): VectorImport =>
  ({ polys, images, skipped, items, layers });

export const skippedSentence = (r: Pick<VectorImport, 'skipped'>): string | null =>
  r.skipped.length ? `Übersprungen: ${r.skipped.join(', ')} (in Pfade bzw. Bild umwandeln)` : null;
