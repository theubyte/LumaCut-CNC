import { applyM, boundsOf, decodeBase64Loose, mat, Shapes, type Poly } from './geom';
import { pathData } from './svg';
import { type EmbeddedImage, ImportError, type ImportItem, type ImportLayerInfo, vectorImport, type VectorImport } from './types';
import { isZip, readZip, zipNames } from './zip';

/**
 * Port of XTool.kt. The display objects of xTool Studio (.xs, a ZIP of JSON files) and xTool Creative
 * Space (.xcs, JSON) look the same. Each display is placed with the transforms the editor uses (PixiJS):
 * local skew, shift of the outline to 0/0, then scale/skew/rotation, then (x, y).
 */
type Json = Record<string, unknown>;
const isObj = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v);
const num = (o: Json, k: string) => { const v = o[k]; return typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v)) ? Number(v) : null; };
const str = (o: Json, k: string) => { const v = o[k]; return typeof v === 'string' ? v : typeof v === 'number' || typeof v === 'boolean' ? String(v) : null; };
const pair = (o: Json, k: string, dx: number, dy: number): [number, number] => {
  const s = o[k];
  return isObj(s) ? [num(s, 'x') ?? dx, num(s, 'y') ?? dy] : [dx, dy];
};

/** Local outline to work plane (mm, y down). With skew.x and localSkew.x both π the mirrors cancel and (x, y) is the lower edge. */
export function toPlane(local: Poly[], o: Json): Poly[] {
  const [lkx, lky] = pair(o, 'localSkew', 0, 0);
  const lm = mat(Math.cos(lky), Math.sin(lky), -Math.sin(-lkx), Math.cos(-lkx));
  const flat = local.map((p) => p.map((q) => applyM(lm, q)));
  const b = boundsOf(flat);
  if (!b) return [];
  const r = (num(o, 'angle') ?? 0) * Math.PI / 180;
  const [kx, ky] = pair(o, 'skew', 0, 0);
  const [sx, sy] = pair(o, 'scale', 1, 1);
  const dm = mat(Math.cos(r + ky) * sx, Math.sin(r + ky) * sx, -Math.sin(r - kx) * sy, Math.cos(r - kx) * sy);
  const x = num(o, 'x') ?? 0, y = num(o, 'y') ?? 0;
  return flat.map((p) => p.map((q) => { const m = applyM(dm, { x: q.x - b.minX, y: q.y - b.minY }); return { x: m.x + x, y: m.y + y }; }));
}

export function layerInfos(data: unknown): ImportLayerInfo[] {
  if (!isObj(data)) return [];
  const out: ImportLayerInfo[] = [];
  for (const [key, v] of Object.entries(data)) {
    if (!isObj(v)) continue;
    out.push({ key, name: str(v, 'name') ?? key, order: Math.trunc(num(v, 'order') ?? 0), visible: typeof v.visible === 'boolean' ? v.visible : true });
  }
  return out.sort((a, b) => a.order - b.order);
}

const IMAGE_KEYS = ['base64', 'src', 'data', 'image', 'url', 'resource', 'resourcePath', 'path'];
const label = (t: string) => t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();

function read(displays: Json[], layers: ImportLayerInfo[], resources: Map<string, Uint8Array>): VectorImport {
  const items: ImportItem[] = [], images: EmbeddedImage[] = [];
  const skipped = new Map<string, number>();
  const skip = (t: string) => { const k = label(t); skipped.set(k, (skipped.get(k) ?? 0) + 1); };
  for (const o of displays) {
    const type = (str(o, 'type') ?? '?').toUpperCase();
    if (o.visible === false || o.visibleState === false) continue;
    const w = num(o, 'width') ?? 0, h = num(o, 'height') ?? 0;
    const [sx, sy] = pair(o, 'scale', 1, 1);
    const lw = sx !== 0 ? w / Math.abs(sx) : w, lh = sy !== 0 ? h / Math.abs(sy) : h;
    if (type === 'BITMAP' || type === 'IMAGE') {
      let bytes: Uint8Array | null = null;
      for (const k of IMAGE_KEYS) {
        const v = str(o, k); if (!v) continue;
        bytes = resources.get(v) ?? resources.get('resources/' + v) ?? (v.length > 64 ? decodeBase64Loose(v) : null);
        if (bytes) break;
      }
      if (!bytes || lw <= 0 || lh <= 0) { skip(type); continue; }
      const box = boundsOf(toPlane([[{ x: 0, y: 0 }, { x: lw, y: 0 }, { x: lw, y: lh }, { x: 0, y: lh }, { x: 0, y: 0 }]], o));
      if (box) images.push({ bytes, box });
      continue;
    }
    const d = str(o, 'dPath');
    let local: Poly[] | null = null;
    if (d && d.trim()) { try { local = pathData(d); } catch { local = null; } }
    else if (type === 'RECT' && lw > 0 && lh > 0) local = [Shapes.rect(lw, lh, num(o, 'radius') ?? num(o, 'rx') ?? 0)];
    else if ((type === 'CIRCLE' || type === 'ELLIPSE') && lw > 0 && lh > 0) local = [Shapes.ellipse(lw, lh)];
    if (!local?.length) { skip(type); continue; }
    const polys = toPlane(local, o);
    if (!polys.length) { skip(type); continue; }
    const key = str(o, 'layerTag') ?? str(o, 'layerColor') ?? str(o, 'originColor') ?? '#000000';
    const tags = Array.isArray(o.groupTags) ? o.groupTags.filter((t): t is string => typeof t === 'string') : [];
    items.push({ polys, layerKey: key, fill: isObj(o.fill) && o.fill.visible === true, groups: [...tags].reverse(), name: str(o, 'name') });
  }
  const known = new Map(layers.map((l) => [l.key, l]));
  const used = [...new Set(items.map((i) => i.layerKey!))];
  const allLayers = used.map((k, i) => known.get(k) ?? { key: k, name: k, order: 1000 + i, visible: true }).sort((a, b) => a.order - b.order);
  return vectorImport(items.flatMap((i) => i.polys), images, [...skipped].map(([k, n]) => `${n}× ${k}`), items, allLayers);
}

function fail(r: VectorImport): never {
  const what = r.skipped.length ? `Nur ${r.skipped.join(', ')} gefunden (nicht lesbar)` : 'Keine Formen gefunden';
  throw new ImportError(`${what}. In xTool Text in Pfade umwandeln und erneut speichern.`);
}

export function parseXcs(bytes: Uint8Array): VectorImport {
  let root: unknown;
  try { root = JSON.parse(new TextDecoder('utf-8').decode(bytes)); } catch { throw new ImportError('Keine gültige xTool-Datei'); }
  const displays: Json[] = []; let layerData: unknown = null;
  const visit = (e: unknown) => {
    if (Array.isArray(e)) { e.forEach(visit); return; }
    if (!isObj(e)) return;
    if (layerData == null && isObj(e.layerData)) layerData = e.layerData;
    const isDisplay = str(e, 'type') != null && ('width' in e || 'dPath' in e);
    if (isDisplay) displays.push(e); else Object.values(e).forEach(visit);
  };
  visit(root);
  const r = read(displays, layerInfos(layerData), new Map());
  if (!r.polys.length && !r.images.length) fail(r);
  return r;
}

/** xTool Studio: a ZIP with project.json, canvases/<id>.json and canvases/<id>/displays-N.json. */
export function isXs(bytes: Uint8Array): boolean {
  if (!isZip(bytes)) return false;
  try { const names = zipNames(bytes); return names.includes('project.json') && names.some((n) => n.startsWith('canvases/')); }
  catch { return false; }
}

export async function parseXs(bytes: Uint8Array): Promise<VectorImport> {
  let files: Map<string, Uint8Array>;
  try { files = await readZip(bytes); }
  catch (e) { if (e instanceof ImportError) throw e; throw new ImportError('Keine gültige xTool-Studio-Datei'); }
  const obj = (name: string): Json | null => {
    const b = files.get(name); if (!b) return null;
    try { const v = JSON.parse(new TextDecoder('utf-8').decode(b)); return isObj(v) ? v : null; } catch { return null; }
  };
  const project = obj('project.json');
  if (!project) throw new ImportError('Keine gültige xTool-Studio-Datei (project.json fehlt)');
  const modules = project.modules;
  const canvases = isObj(modules) && Array.isArray(modules.canvases) ? modules.canvases.filter((c): c is string => typeof c === 'string') : [];
  const active = str(project, 'activeCanvasId') ?? canvases[0];
  if (!active) throw new ImportError('Die xTool-Datei enthält keine Zeichenfläche');
  const canvas = obj(`canvases/${active}.json`);
  const prefix = `canvases/${active}/displays-`;
  const chunks = [...files.keys()].filter((n) => n.startsWith(prefix) && /^\d+\.json$/.test(n.slice(prefix.length)))
    .sort((a, b) => parseInt(a.slice(prefix.length), 10) - parseInt(b.slice(prefix.length), 10));
  const displays = chunks.flatMap((name) => { const d = obj(name)?.displays; return Array.isArray(d) ? d.filter(isObj) : []; });
  const r = read(displays, layerInfos(canvas?.layerData), files);
  if (!r.polys.length && !r.images.length) fail(r);
  return r;
}
