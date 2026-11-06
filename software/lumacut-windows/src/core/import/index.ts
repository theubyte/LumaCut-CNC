import type { Element, Layer } from '../model';

export interface ImportContext {
  /** Layer for a standard process ("Gravieren", "Linie", "Schneiden"); created if missing. */
  layerByName(name: string): Layer;
  /** Active layer for content that has no process of its own. */
  activeLayer: Layer;
}
export interface ImportResult { elements: Element[]; warnings: string[]; layers?: Layer[] }
export const IMPORT_FILTERS = [{ name: 'Alle Motive', extensions: ['svg', 'dxf', 'pdf', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'lbrn', 'lbrn2', 'xs', 'gcode', 'nc'] }];
/** Implemented by the import module. Elements come fitted into the work area, centered. */
export async function importFile(_name: string, _bytes: Uint8Array, _ctx: ImportContext): Promise<ImportResult> {
  throw new Error('noch nicht portiert');
}
