/**
 * Project model. The JSON is compatible with the Android app's `Document`
 * (android/core/.../Design.kt, Geometry.kt): the same project opens on tablet and PC via the Pi.
 * Keep field names and enum values identical. Windows-only additions must be optional:
 * Android ignores unknown keys, and `paths` always stays the flattened truth for output.
 * Unknown keys from a loaded file are kept (see `normalize`).
 */
export interface Pt { x: number; y: number }
export type Poly = Pt[];

export interface Box { minX: number; minY: number; maxX: number; maxY: number }
export const boxW = (b: Box) => b.maxX - b.minX;
export const boxH = (b: Box) => b.maxY - b.minY;
export const boxCenter = (b: Box): Pt => ({ x: (b.minX + b.maxX) / 2, y: (b.minY + b.maxY) / 2 });
export const boxUnion = (a: Box, b: Box | null): Box => !b ? a : ({
  minX: Math.min(a.minX, b.minX), minY: Math.min(a.minY, b.minY), maxX: Math.max(a.maxX, b.maxX), maxY: Math.max(a.maxY, b.maxY) });

export function boundsOf(polys: Iterable<Poly>): Box | null {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const poly of polys) for (const p of poly) {
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.y > maxY) maxY = p.y;
  }
  return minX === Infinity ? null : { minX, minY, maxX, maxY };
}
export const isClosed = (p: Poly, eps = 1e-6) => p.length > 2 && Math.hypot(p[0].x - p[p.length - 1].x, p[0].y - p[p.length - 1].y) < eps;

/** Scale, then rotate (degrees, around origin), then translate. Same order as Transform in Geometry.kt. */
export interface Transform { x: number; y: number; scaleX: number; scaleY: number; rotation: number }
export const IDENTITY: Transform = { x: 0, y: 0, scaleX: 1, scaleY: 1, rotation: 0 };
export function applyT(t: Transform, p: Pt): Pt {
  const sx = p.x * t.scaleX, sy = p.y * t.scaleY, r = t.rotation * Math.PI / 180, c = Math.cos(r), s = Math.sin(r);
  return { x: sx * c - sy * s + t.x, y: sx * s + sy * c + t.y };
}
export function invertT(t: Transform, p: Pt): Pt {
  const dx = p.x - t.x, dy = p.y - t.y, r = -t.rotation * Math.PI / 180, c = Math.cos(r), s = Math.sin(r);
  return { x: (dx * c - dy * s) / (t.scaleX || 1), y: (dx * s + dy * c) / (t.scaleY || 1) };
}

export type LayerMode = 'LINE' | 'FILL';
export type ImageMode = 'GRAYSCALE' | 'DITHER' | 'THRESHOLD' | 'DITHER_JARVIS' | 'DITHER_STUCKI';

export const Limits = {
  POWER: [0, 100], SPEED: [1, 30000], PASSES: [1, 30], Z_STEP: [0, 2], MAX_FOCUS_DROP_MM: 3,
  THICKNESS: [0, 60], Z_MAX_MM: 80, DEPTH_PER_PASS: [0, 10],
  /** Laser does not fire reliably below ~6 % (STAND.md §4): lower bound for a burning layer. */
  MIN_RELIABLE_POWER_PCT: 8,
} as const;

export type DarknessCurve = Record<string, unknown>;
export interface Layer {
  id: string; name: string;
  /** ARGB as in Kotlin (0xFF4FD8B4). Use `layerCss()` for drawing. */
  color: number;
  mode: LayerMode; powerPct: number; minPowerPct: number; speed: number; passes: number;
  intervalMm: number; overscanMm: number; zStepMm: number;
  output: boolean; visible: boolean; locked: boolean;
  materialName: string | null; thicknessMm: number; depthPerPassMm: number;
  toneCurve: number[]; darkness: DarknessCurve | null;
}
export const layerCss = (l: Pick<Layer, 'color'>) => '#' + (l.color % 0x1000000).toString(16).padStart(6, '0');
/** The standard "Linie" layer is shown as "Markieren", as in the Android app. */
export const layerLabel = (l: Pick<Layer, 'name'>) => l.name === 'Linie' ? 'Markieren' : l.name;
export const STANDARD_LAYERS = new Set(['Gravieren', 'Linie', 'Schneiden']);

export interface Raster { width: number; height: number; grayBase64: string }
export type ImageAdjust = Record<string, unknown>;

/** Windows-only: cubic curve node for the path editor. `paths` is its flattening. */
export interface CurveNode { x: number; y: number; hx1?: number; hy1?: number; hx2?: number; hy2?: number; smooth?: boolean }
export interface CurvePath { nodes: CurveNode[]; closed: boolean }

/** kind: free text as on Android ("Rechteck", "Text", "Bild", "SVG", ...). */
export interface Element {
  id: string; layerId: string; kind: string; transform: Transform;
  paths: Poly[]; text: string | null; fontSizeMm: number; bold: boolean; fontFamily: string;
  raster: Raster | null; imageWidthMm: number; imageHeightMm: number; imageMode: ImageMode; adjust: ImageAdjust;
  groupId: string | null; plate: number;
  /** Windows-only, optional. */
  curves?: CurvePath[];
  /** Keep unknown fields from other app versions. */
  [extra: string]: unknown;
}
export interface Doc {
  title: string; layers: Layer[]; elements: Element[]; plateCount: number; activePlate: number;
  [extra: string]: unknown;
}

export const newId = () => crypto.randomUUID();
export function newLayer(name: string, color: number, mode: LayerMode, over: Partial<Layer> = {}): Layer {
  return { id: newId(), name, color, mode, powerPct: 50, minPowerPct: 0, speed: 1500, passes: 1, intervalMm: 0.1, overscanMm: 2.5, zStepMm: 0,
    output: true, visible: true, locked: false, materialName: null, thicknessMm: 0, depthPerPassMm: 0, toneCurve: [], darkness: null, ...over };
}
export const defaultLayers = (): Layer[] => [
  newLayer('Gravieren', 0xFF4FD8B4, 'FILL', { powerPct: 25, speed: 3000, intervalMm: 0.1 }),
  newLayer('Linie', 0xFF6CB6FF, 'LINE', { powerPct: 40, speed: 1500 }),
  newLayer('Schneiden', 0xFFFF6B70, 'LINE', { powerPct: 85, speed: 400, passes: 2 }),
];
export const newDoc = (title = 'Neues Projekt'): Doc => ({ title, layers: defaultLayers(), elements: [], plateCount: 1, activePlate: 0 });
export function newElement(layerId: string, kind: string, over: Partial<Element> = {}): Element {
  return { id: newId(), layerId, kind, transform: { ...IDENTITY }, paths: [], text: null, fontSizeMm: 10, bold: false, fontFamily: 'sans-serif',
    raster: null, imageWidthMm: 0, imageHeightMm: 0, imageMode: 'GRAYSCALE', adjust: {}, groupId: null, plate: 0, ...over };
}

export const isImage = (e: Element) => e.raster != null;
export const worldPaths = (e: Element): Poly[] => e.paths.map((poly) => poly.map((p) => applyT(e.transform, p)));
export const imageCorners = (e: Element): Pt[] =>
  [{ x: 0, y: 0 }, { x: e.imageWidthMm, y: 0 }, { x: e.imageWidthMm, y: e.imageHeightMm }, { x: 0, y: e.imageHeightMm }].map((p) => applyT(e.transform, p));
export const worldBounds = (e: Element): Box | null => isImage(e) ? boundsOf([imageCorners(e)]) : boundsOf(worldPaths(e));
export function docBounds(els: Element[]): Box | null {
  let b: Box | null = null;
  for (const e of els) { const w = worldBounds(e); if (w) b = boxUnion(w, b); }
  return b;
}
export const plateElements = (d: Doc, plate = d.activePlate) => d.elements.filter((e) => e.plate === plate);

/** Old or hand-edited files: indices in range, missing values filled, unknown keys kept. */
export function normalize(raw: Partial<Doc>): Doc {
  const layers = (raw.layers?.length ? raw.layers : defaultLayers()).map((l) => ({ ...newLayer(l.name, l.color, l.mode ?? 'LINE'), ...l }));
  const elements = (raw.elements ?? []).map((e) => ({ ...newElement(e.layerId, e.kind), ...e, plate: Math.max(0, e.plate ?? 0) }));
  const plateCount = Math.max(raw.plateCount ?? 1, 1, ...elements.map((e) => e.plate + 1));
  return { ...raw, title: raw.title ?? 'Neues Projekt', layers, elements, plateCount, activePlate: Math.min(Math.max(raw.activePlate ?? 0, 0), plateCount - 1) };
}
export const toJson = (d: Doc) => JSON.stringify(d);
export const fromJson = (text: string): Doc => normalize(JSON.parse(text));

/**
 * Bed geometry. Machine 0/0 is the limit-switch corner; on screen the work area has origin
 * top-left as seen from the door. machine_x = WIDTH - x, machine_y = y. This is the ONLY conversion.
 * Values come from the Pi (`configureBed` with each status), defaults are the measured ones.
 */
export const Bed = { width: 370, height: 360, parkX: 78, parkY: 35 };
export function configureBed(w?: number, h?: number, px?: number, py?: number) {
  if (w != null && w >= 100 && w <= 600) Bed.width = w;
  if (h != null && h >= 100 && h <= 600) Bed.height = h;
  if (px != null && px >= 0 && px <= 200) Bed.parkX = px;
  if (py != null && py >= 0 && py <= 200) Bed.parkY = py;
}
export const toMachine = (p: Pt): Pt => ({ x: Bed.width - p.x, y: p.y });
export const fromMachine = (p: Pt): Pt => ({ x: Bed.width - p.x, y: p.y });
export const parkBox = (): Box => ({ minX: Bed.width - Bed.parkX, minY: 0, maxX: Bed.width, maxY: Bed.parkY });
const EPS = 1e-6;
export const touchesPark = (b: Box) => { const k = parkBox(); return b.maxX > k.minX + EPS && b.minY < k.maxY - EPS; };
export const insideWork = (b: Box) => b.minX >= -EPS && b.minY >= -EPS && b.maxX <= Bed.width + EPS && b.maxY <= Bed.height + EPS;
