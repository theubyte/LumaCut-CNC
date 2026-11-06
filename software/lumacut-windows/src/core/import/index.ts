import { Bed, boundsOf, type Element, type Layer, newElement, newLayer, type Pt, type Raster } from '../model';
import { parseDxf } from './dxf';
import { detectKind, type FileKind, KIND_LABEL, parseHpgl, parseLbrn } from './formats';
import { decodeImageBytes, rasterFromRgba, readDpi } from './image';
import { arrange, type ImportUnit, type Layout, shrinkFactor, spread, unionOf, unitsOf } from './layout';
import { parsePdf } from './pdf';
import { parseSvg } from './svg';
import { ImportError, skippedSentence, vectorImport, type EmbeddedImage, type VectorImport } from './types';
import { isXs, parseXcs, parseXs } from './xtool';

export { ImportError } from './types';

export interface ImportContext {
  /** Layer for a standard process ("Gravieren", "Linie", "Schneiden"); created if missing. */
  layerByName(name: string): Layer;
  /** Active layer for content that has no process of its own. */
  activeLayer: Layer;
}
export interface ImportResult { elements: Element[]; warnings: string[]; layers?: Layer[] }

export const IMPORT_FILTERS = [{ name: 'Alle Motive', extensions: ['svg', 'dxf', 'pdf', 'ai', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif', 'lbrn', 'lbrn2', 'xs', 'xcs', 'hpgl', 'plt'] }];
const SUPPORTED = 'SVG, DXF, PDF, xTool (.xs, .xcs), LightBurn (.lbrn, .lbrn2), HPGL und Bilder (PNG, JPG, WebP, BMP, GIF)';
/** Without a resolution in the file a picture starts 80 mm wide, as on Android. */
const DEFAULT_IMAGE_WIDTH_MM = 80;

/** Elements come fitted into the work area, centered. Throws `ImportError` with one sentence and the next step. */
export async function importFile(_name: string, bytes: Uint8Array, ctx: ImportContext): Promise<ImportResult> {
  if (!bytes.length) throw new ImportError('Die Datei ist leer oder lässt sich nicht lesen.');
  const kind = detectKind(bytes, isXs);
  switch (kind) {
    case 'IMAGE': return importImage(bytes, ctx);
    case 'PDF': return importPdf(bytes, ctx);
    case 'PROJECT': throw new ImportError('Das ist ein LumaCut-Projekt. Bitte über „Projekt öffnen“ laden.');
    case 'UNKNOWN': throw new ImportError(`Dieses Format kenne ich nicht. Unterstützt: ${SUPPORTED}.`);
    default: return placeVector(kind, await parseVector(kind, bytes), ctx);
  }
}

export async function parseVector(kind: FileKind, bytes: Uint8Array): Promise<VectorImport> {
  switch (kind) {
    case 'SVG': return parseSvg(bytes);
    case 'DXF': { const r = parseDxf(bytes); return vectorImport(r.polys, [], r.skipped); }
    case 'XCS': return parseXcs(bytes);
    case 'XS': return parseXs(bytes);
    case 'LBRN': return parseLbrn(bytes);
    case 'HPGL': return vectorImport(parseHpgl(bytes));
    default: throw new ImportError('Dieses Format wird nicht als Vektor gelesen');
  }
}

async function importImage(bytes: Uint8Array, ctx: ImportContext): Promise<ImportResult> {
  const img = await decodeImageBytes(bytes);
  const raster = rasterFromRgba(img);
  const dpi = readDpi(bytes);
  const width = dpi ? img.width / dpi * 25.4 : DEFAULT_IMAGE_WIDTH_MM;
  const warnings: string[] = [];
  if (raster.width !== img.width) warnings.push(`Das Bild wurde von ${img.width} auf ${raster.width} Pixel Breite verkleinert.`);
  return { elements: [placedImage(raster, width, ctx)], warnings };
}

function placedImage(raster: Raster, widthMm: number, ctx: ImportContext): Element {
  let w = widthMm, h = w * raster.height / raster.width;
  const k = Math.min(1, (Bed.width - 10) / w, (Bed.height - 10) / h);
  w *= k; h *= k;
  return newElement(ctx.layerByName('Gravieren').id, 'Bild', {
    transform: { x: Bed.width / 2 - w / 2, y: Bed.height / 2 - h / 2, scaleX: 1, scaleY: 1, rotation: 0 },
    raster, imageWidthMm: w, imageHeightMm: h,
  });
}

async function importPdf(bytes: Uint8Array, ctx: ImportContext): Promise<ImportResult> {
  const r = await parsePdf(bytes);
  const notes: string[] = [];
  if (r.pages > 1) notes.push(`Von ${r.pages} Seiten wurde nur Seite 1 übernommen.`);
  if (r.vector) {
    if (r.texts) notes.push(`Text im PDF wurde nicht übernommen (${r.texts} Stellen). Im Ursprungsprogramm in Pfade umwandeln.`);
    if (r.images) notes.push(`Bilder im PDF wurden nicht übernommen (${r.images}). Als Bild extra importieren.`);
    const res = await placeVector('PDF', r.vector, ctx);
    return { ...res, warnings: [...notes, ...res.warnings] };
  }
  const pxPerMm = Math.min(10, 1600 / Math.max(r.widthMm, r.heightMm));
  const img = await r.render(pxPerMm);
  if (!img) throw new ImportError('Dieses PDF enthält keine Vektorpfade.');
  notes.push('Das PDF enthält keine Vektorpfade und wurde als Bild übernommen. Zum Schneiden die Datei als SVG oder DXF speichern.');
  return { elements: [placedImage(rasterFromRgba(img), r.widthMm, ctx)], warnings: notes };
}

/** "#rrggbb" of a source layer as ARGB; xTool keys that are no colour fall back to the base layer's colour. */
const parseColour = (key: string, fallback: number) => /^#[0-9a-f]{6}$/i.test(key) ? (0xFF000000 + parseInt(key.slice(1), 16)) : fallback;

async function placeVector(kind: FileKind, r: VectorImport, ctx: ImportContext): Promise<ImportResult> {
  const units = unitsOf(r);
  if (!units.length) throw new ImportError('Nichts Lasertaugliches gefunden.');
  const warnings: string[] = [];
  if (r.notes) warnings.push(...r.notes);
  const sentence = skippedSentence(r);
  if (sentence) warnings.push(sentence);

  const rasters = new Map<EmbeddedImage, Raster>();
  for (const img of r.images) {
    try { rasters.set(img, rasterFromRgba(await decodeImageBytes(img.bytes))); }
    catch { warnings.push('Ein eingebettetes Bild ließ sich nicht lesen und fehlt.'); }
  }

  let plates: { layout: Layout; scale: number }[];
  const layout = arrange(units);
  if (layout.kind === 'AS_IS') plates = [{ layout, scale: 1 }];
  else if (layout.kind === 'PACKED') {
    plates = [{ layout, scale: 1 }];
    warnings.push('Das Motiv ist größer als die Arbeitsfläche. Die Teile wurden in Originalgröße nebeneinander angeordnet.');
  } else {
    const s = spread(units);
    if (s.plates.length > 1 && s.leftOut === 0) {
      plates = s.plates.map((l) => ({ layout: l, scale: 1 }));
      warnings.push(`Die Teile passen nicht auf eine Platte und wurden in Originalgröße auf ${s.plates.length} Platten verteilt.`);
    } else {
      const k = shrinkFactor(units);
      plates = [{ layout: { kind: 'AS_IS', units, offsets: units.map(() => ({ x: 0, y: 0 })) }, scale: k }];
      warnings.push(`Das Motiv ist größer als die Arbeitsfläche und wurde auf ${Math.trunc(k * 100)} % verkleinert. Maße prüfen.`);
    }
  }
  const { elements, layers } = buildElements(KIND_LABEL[kind], kind, plates, r, rasters, ctx);
  if (!elements.length) throw new ImportError('Nichts Lasertaugliches gefunden.');
  const hidden = layers.filter((l) => !l.visible);
  if (hidden.length) warnings.push(`Weiß gilt als Hintergrund: die Ebene „${hidden.map((l) => l.name).join(', ')}“ ist ausgeblendet und brennt nicht.`);
  return { elements, warnings, layers: layers.length ? layers : undefined };
}

/** Port of addImported in EditorViewModel.kt. New colour layers take the values of the standard layers. */
function buildElements(label: string, kind: FileKind, plates: { layout: Layout; scale: number }[], r: VectorImport, rasters: Map<EmbeddedImage, Raster>, ctx: ImportContext) {
  // SVG and PDF colours say nothing about cutting: their lines start with the gentle marking values.
  const lineBase = ctx.layerByName(kind === 'SVG' || kind === 'PDF' ? 'Linie' : 'Schneiden');
  const fillBase = ctx.layerByName('Gravieren');
  const info = new Map(r.layers.map((l) => [l.key, l]));
  const fresh = new Map<string, Layer>();
  const layerIdFor = (key: string, fill: boolean) => {
    const id = `${key}|${fill}`;
    const hit = fresh.get(id);
    if (hit) return hit.id;
    const i = info.get(key);
    const base = fill ? fillBase : lineBase;
    const layer: Layer = { ...base, ...newLayer((i?.name ?? key) + (fill ? ' (Füllen)' : ''), parseColour(key, base.color), fill ? 'FILL' : 'LINE'), powerPct: base.powerPct, minPowerPct: base.minPowerPct, speed: base.speed, passes: base.passes, intervalMm: base.intervalMm, overscanMm: base.overscanMm, zStepMm: base.zStepMm, materialName: base.materialName, thicknessMm: base.thicknessMm, depthPerPassMm: base.depthPerPassMm, toneCurve: base.toneCurve, darkness: base.darkness, visible: i?.visible ?? true };
    fresh.set(id, layer);
    return layer.id;
  };
  const elements: Element[] = [];
  const groupSize = new Map<string, number>();
  plates.forEach(({ layout }) => layout.units.forEach((u, i) => { if (layout.offsets[i]) for (const item of u.items) if (item.groups[0]) groupSize.set(item.groups[0], (groupSize.get(item.groups[0]) ?? 0) + 1); }));
  const groupIds = new Map<string, string>();
  const groupOf = (tag?: string) => {
    if (!tag || (groupSize.get(tag) ?? 0) < 2) return null;
    return groupIds.get(tag) ?? (groupIds.set(tag, crypto.randomUUID()), groupIds.get(tag)!);
  };
  plates.forEach(({ layout, scale }, plate) => {
    const all = centerOf(layout.units);
    const map = (p: Pt, i: number): Pt => {
      const o = layout.offsets[i] ?? { x: 0, y: 0 };
      return scale === 1 ? { x: p.x + o.x, y: p.y + o.y } : { x: Bed.width / 2 + (p.x - all.x) * scale, y: Bed.height / 2 + (p.y - all.y) * scale };
    };
    layout.units.forEach((unit, u) => {
      if (!layout.offsets[u]) return;
      for (const item of unit.items) {
        const polys = item.polys.map((poly) => poly.map((q) => map(q, u)));
        const b = boundsOf(polys);
        if (!b) continue;
        const layerId = item.layerKey != null ? layerIdFor(item.layerKey, item.fill) : ctx.activeLayer.id;
        elements.push(newElement(layerId, item.name?.trim() ? item.name : label, {
          transform: { x: b.minX, y: b.minY, scaleX: 1, scaleY: 1, rotation: 0 },
          paths: polys.map((poly) => poly.map((q) => ({ x: q.x - b.minX, y: q.y - b.minY }))),
          groupId: groupOf(item.groups[0]), plate,
        }));
      }
      for (const img of unit.images) {
        const raster = rasters.get(img);
        if (!raster) continue;
        const a = map({ x: img.box.minX, y: img.box.minY }, u), c = map({ x: img.box.maxX, y: img.box.maxY }, u);
        elements.push(newElement(fillBase.id, 'Bild', { transform: { x: a.x, y: a.y, scaleX: 1, scaleY: 1, rotation: 0 }, raster, imageWidthMm: c.x - a.x, imageHeightMm: c.y - a.y, plate }));
      }
    });
  });
  return { elements, layers: [...fresh.values()] };
}

const centerOf = (units: ImportUnit[]) => { const b = unionOf(units); return { x: (b.minX + b.maxX) / 2, y: (b.minY + b.maxY) / 2 }; };
