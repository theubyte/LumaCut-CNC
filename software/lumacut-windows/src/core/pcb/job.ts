/**
 * From a board to laser work: one plan layer per process, in board coordinates (Y up, seen from the
 * top), then placed on the bed as document elements.
 *
 * What is computed where:
 *  - Raster negative: everything inside the board except copper grown by half a beam, so the beam edge
 *    stops at the copper edge instead of eating into it.
 *  - Isolation: closed lines around the copper at half a beam, then one step further per pass.
 *  - Exposure of negative dry film: the copper itself, shrunk by half a beam.
 * Power and speed here are STARTING VALUES and nothing more. The real values come from the owner's
 * material test on the same lacquer.
 */
import { Bed, boundsOf, boxH, boxUnion, boxW, insideWork, newElement, newId, newLayer, touchesPark, IDENTITY, type Box, type Doc, type Element, type Layer, type LayerMode, type Poly, type Pt } from '@/core/model';
import { circle, clipLines, offsetPolys, polysArea, subtractPolys, unionPolys } from './clipper';
import { minClearance, type Board, type ClearanceResult, type Side } from './board';

export type ResistMethod = 'raster' | 'isolation' | 'expose';
export type ProcessKey = 'resist' | 'drill' | 'fiducial' | 'outline' | 'mask' | 'silk';
export type Stage = 'resist' | 'mask' | 'silk';

export interface JobSettings {
  side: Side;
  /** Bottom layers are drawn seen through the board, so they must be mirrored to be lasered from above. */
  mirror: boolean;
  /** Bed position of the top left corner of the job, passmarks included. */
  x: number; y: number;
  beamMm: number;
  overlapPct: number;
  resist: boolean;
  method: ResistMethod;
  passes: number;
  removeRest: boolean;
  drillMarks: boolean;
  drillStyle: 'dot' | 'cross';
  drillMarkMm: number;
  mask: boolean;
  silk: boolean;
  fiducials: 0 | 2 | 4;
  fiducialDiaMm: number;
  fiducialOffsetMm: number;
  outlineMark: boolean;
  power: Record<ProcessKey, number>;
  speed: Record<ProcessKey, number>;
}

/** Starting values only, never presented as proven. Above the 8 % floor for burning work (STAND §4). */
export const START_VALUES: Record<ProcessKey, { power: number; speed: number }> = {
  resist: { power: 20, speed: 2000 },
  drill: { power: 20, speed: 2000 },
  fiducial: { power: 20, speed: 2000 },
  outline: { power: 12, speed: 2000 },
  mask: { power: 30, speed: 1500 },
  silk: { power: 12, speed: 3000 },
};

export const defaultSettings = (): JobSettings => ({
  side: 'top', mirror: false, x: 100, y: 100, beamMm: 0.15, overlapPct: 25, resist: true, method: 'raster', passes: 3, removeRest: false,
  drillMarks: true, drillStyle: 'dot', drillMarkMm: 0.5, mask: false, silk: false, fiducials: 4, fiducialDiaMm: 1, fiducialOffsetMm: 3, outlineMark: false,
  power: Object.fromEntries(Object.entries(START_VALUES).map(([k, v]) => [k, v.power])) as Record<ProcessKey, number>,
  speed: Object.fromEntries(Object.entries(START_VALUES).map(([k, v]) => [k, v.speed])) as Record<ProcessKey, number>,
});

export interface PlanLayer { key: ProcessKey; name: string; stage: Stage; mode: LayerMode; color: number; polys: Poly[]; intervalMm: number; powerPct: number; speed: number; output: boolean }
export interface Plan { layers: PlanLayer[]; bounds: Box; fiducials: Pt[]; warnings: string[] }

const META: Record<ProcessKey, { name: string; stage: Stage; color: number }> = {
  resist: { name: 'Platine Ätzresist', stage: 'resist', color: 0xFFE0824A },
  drill: { name: 'Platine Bohrmarken', stage: 'resist', color: 0xFF6CB6FF },
  fiducial: { name: 'Platine Passmarken', stage: 'resist', color: 0xFFB08CFF },
  outline: { name: 'Platine Umriss', stage: 'resist', color: 0xFF8A93A8 },
  mask: { name: 'Platine Lötstopp', stage: 'mask', color: 0xFF4FD8B4 },
  silk: { name: 'Platine Beschriftung', stage: 'silk', color: 0xFFF2C14E },
};
export const PLATINE_LAYER_NAMES = Object.values(META).map((m) => m.name);
export const STAGE_LABEL: Record<Stage, string> = { resist: 'Ätzresist', mask: 'Lötstopp', silk: 'Beschriftung' };

export const lineInterval = (s: Pick<JobSettings, 'beamMm' | 'overlapPct'>) => Math.max(0.03, s.beamMm * (1 - s.overlapPct / 100));

/** Marks sit on or symmetric to the vertical centre line, so they still line up when the board is turned over. */
export function fiducialPoints(b: Box, count: number, off: number): Pt[] {
  const cx = (b.minX + b.maxX) / 2;
  if (count === 2) return [{ x: cx, y: b.maxY + off }, { x: cx, y: b.minY - off }];
  if (count === 4) return [{ x: b.minX - off, y: b.maxY + off }, { x: b.maxX + off, y: b.maxY + off }, { x: b.maxX + off, y: b.minY - off }, { x: b.minX - off, y: b.minY - off }];
  return [];
}

function drillMarkPolys(board: Board, s: JobSettings): Poly[] {
  const out: Poly[] = [];
  for (const h of board.drills) {
    const size = Math.min(s.drillMarkMm, h.dia > 0 ? h.dia * 0.8 : s.drillMarkMm);
    if (s.drillStyle === 'dot') out.push(circle(h.x, h.y, size / 2));
    else {
      const t = Math.max(s.beamMm, 0.1), l = Math.max(size, 2 * t);
      out.push(...unionPolys([
        [{ x: h.x - l / 2, y: h.y - t / 2 }, { x: h.x + l / 2, y: h.y - t / 2 }, { x: h.x + l / 2, y: h.y + t / 2 }, { x: h.x - l / 2, y: h.y + t / 2 }],
        [{ x: h.x - t / 2, y: h.y - l / 2 }, { x: h.x + t / 2, y: h.y - l / 2 }, { x: h.x + t / 2, y: h.y + l / 2 }, { x: h.x - t / 2, y: h.y + l / 2 }],
      ]));
    }
  }
  return unionPolys(out);
}

export function buildPlan(board: Board, s: JobSettings): Plan {
  const layers: PlanLayer[] = [];
  const warnings: string[] = [];
  const beam = s.beamMm, interval = lineInterval(s);
  const add = (key: ProcessKey, mode: LayerMode, polys: Poly[], output = true) => {
    if (!polys.length) return;
    const m = META[key];
    layers.push({ key, name: m.name, stage: m.stage, color: m.color, mode, polys, intervalMm: interval, powerPct: s.power[key], speed: s.speed[key], output });
  };
  const copper = board.copper[s.side]?.polys ?? [];
  const edge = offsetPolys([board.outline[0]], 0.5);
  const marks = fiducialPoints(board.bounds, s.fiducials, s.fiducialOffsetMm);

  if (s.resist) {
    if (!copper.length) warnings.push(`Für diese Seite gibt es keine Kupferlage: kein Ätzresist möglich.`);
    else if (s.method === 'raster') {
      add('resist', 'FILL', subtractPolys(edge, offsetPolys(copper, beam / 2)));
    } else if (s.method === 'isolation') {
      const step = interval, lines: Poly[] = [];
      const passes = Math.max(1, Math.round(s.passes));
      for (let k = 0; k < passes; k++) lines.push(...offsetPolys(copper, beam / 2 + k * step));
      add('resist', 'LINE', clipLines(lines, edge));
      if (s.removeRest) {
        const rest = subtractPolys(edge, offsetPolys(copper, beam / 2 + passes * step));
        if (rest.length) layers.push({ key: 'resist', name: `${META.resist.name} Rest`, stage: 'resist', color: META.resist.color, mode: 'FILL', polys: rest, intervalMm: interval, powerPct: s.power.resist, speed: s.speed.resist, output: true });
      }
    } else {
      // Negative film: light hardens what stays. Copper is exposed, drill centres stay dark and etch free.
      const shrunk = offsetPolys(copper, -beam / 2);
      add('resist', 'FILL', s.drillMarks ? subtractPolys(shrunk, drillMarkPolys(board, s)) : shrunk);
    }
    if (copper.length && s.method !== 'expose' && s.drillMarks) add('drill', 'FILL', drillMarkPolys(board, s));
    if (copper.length && marks.length) {
      const d = s.fiducialDiaMm;
      // Removing resist etches a dot. With negative film a ring of copper must stay instead, with the dot free inside it.
      const shape = s.method === 'expose'
        ? marks.flatMap((m) => subtractPolys([circle(m.x, m.y, d / 2 + 1)], [circle(m.x, m.y, d / 2)]))
        : marks.map((m) => [...circle(m.x, m.y, d / 2), circle(m.x, m.y, d / 2)[0]]);
      add('fiducial', 'FILL', shape);
    }
    add('outline', 'LINE', board.outline, s.outlineMark);
  }
  if (s.mask) {
    const m = board.mask[s.side]?.polys ?? [];
    if (!m.length) warnings.push('Für diese Seite gibt es keine Lötstopp-Datei.');
    add('mask', 'FILL', offsetPolys(m, -beam / 2));
  }
  if (s.silk) {
    const sk = board.silk[s.side]?.polys ?? [];
    if (!sk.length) warnings.push('Für diese Seite gibt es keine Beschriftungs-Datei.');
    // Text on a pad would burn the opening; print files often overlap, fabs clip it the same way.
    add('silk', 'FILL', subtractPolys(sk, board.mask[s.side]?.polys ?? []));
  }
  const fid = marks.map((m) => ({ x: m.x, y: m.y }));
  const b0 = board.bounds;
  const r = s.fiducialDiaMm / 2 + (s.method === 'expose' ? 1 : 0);
  const fidBox = fid.length ? { minX: Math.min(...fid.map((f) => f.x)) - r, minY: Math.min(...fid.map((f) => f.y)) - r, maxX: Math.max(...fid.map((f) => f.x)) + r, maxY: Math.max(...fid.map((f) => f.y)) + r } : null;
  const bounds = boxUnion(b0, fidBox);
  return { layers, bounds, fiducials: fid, warnings };
}

/** Board coordinates to job coordinates: Y down like the bed; mirrored about the job's centre if asked. */
export function toJob(p: Pt, b: Box, mirror: boolean): Pt {
  return { x: mirror ? b.maxX - p.x : p.x - b.minX, y: b.maxY - p.y };
}
export const jobSize = (plan: Plan) => ({ w: boxW(plan.bounds), h: boxH(plan.bounds) });
export const placedBox = (plan: Plan, s: Pick<JobSettings, 'x' | 'y'>): Box => ({ minX: s.x, minY: s.y, maxX: s.x + boxW(plan.bounds), maxY: s.y + boxH(plan.bounds) });
export const centeredOnBed = (plan: Plan) => ({
  x: Math.round(Math.max(0, (Bed.width - boxW(plan.bounds)) / 2)),
  y: Math.round(Math.max(0, (Bed.height - boxH(plan.bounds)) / 2)),
});

export type CheckTone = 'ok' | 'warn' | 'bad';
export interface DesignCheck { id: string; tone: CheckTone; title: string; text: string }
export interface DesignFacts { minTrace: number | null; clearance: ClearanceResult | null; copperArea: number }

export const designFacts = (board: Board, side: Side): DesignFacts => {
  const c = board.copper[side];
  return { minTrace: c?.minStroke ?? null, clearance: c ? minClearance(c.polys) : null, copperArea: c?.area ?? 0 };
};

const mm = (v: number) => v.toFixed(2).replace('.', ',');

/** Compares the design with the beam width and the machine's work area. */
export function designChecks(f: DesignFacts, s: JobSettings, plan: Plan): DesignCheck[] {
  const out: DesignCheck[] = [];
  if (f.clearance) {
    const c = f.clearance.mm;
    if (c < s.beamMm) out.push({ id: 'clearance', tone: 'bad', title: `Kleinster Abstand ${mm(c)} mm`, text: `Enger als der Strahl (${mm(s.beamMm)} mm). An dieser Stelle bleibt Lack stehen, das ergibt nach dem Ätzen eine Brücke. Die Stelle ist in der Vorschau markiert.` });
    else if (c < s.beamMm * 1.5) out.push({ id: 'clearance', tone: 'warn', title: `Kleinster Abstand ${mm(c)} mm`, text: `Knapp über der Strahlbreite. Mit dem Materialtest prüfen, ob der Lack dort sauber frei wird.` });
    else out.push({ id: 'clearance', tone: 'ok', title: `Kleinster Abstand ${mm(c)} mm`, text: `Passt zur Strahlbreite ${mm(s.beamMm)} mm.` });
  } else if (f.copperArea > 0) out.push({ id: 'clearance', tone: 'ok', title: 'Kleinster Abstand über 2 mm', text: 'Unkritisch für den Strahl.' });
  if (f.minTrace != null) {
    if (f.minTrace < s.beamMm) out.push({ id: 'trace', tone: 'bad', title: `Kleinste Leiterbreite ${mm(f.minTrace)} mm`, text: `Schmaler als der Strahl (${mm(s.beamMm)} mm). Diese Leiter wird nicht zuverlässig stehen bleiben.` });
    else if (f.minTrace < Math.max(0.3, s.beamMm * 2)) out.push({ id: 'trace', tone: 'warn', title: `Kleinste Leiterbreite ${mm(f.minTrace)} mm`, text: 'Beim Ätzen wird die Leiter auch von der Seite angegriffen. Dünne Bahnen vorab auf einem Reststück testen.' });
    else out.push({ id: 'trace', tone: 'ok', title: `Kleinste Leiterbreite ${mm(f.minTrace)} mm`, text: 'Aus den Zeichenbefehlen der Datei, ohne Flächen.' });
  }
  const box = placedBox(plan, s);
  if (!insideWork(box)) out.push({ id: 'bed', tone: 'bad', title: 'Außerhalb der Arbeitsfläche', text: 'Position in Schritt 2 ändern.' });
  else if (touchesPark(box)) out.push({ id: 'bed', tone: 'bad', title: 'Berührt die Parkecke', text: 'Position in Schritt 2 ändern: die Parkecke bleibt frei.' });
  if (s.side === 'bottom' && !s.mirror) out.push({ id: 'mirror', tone: 'warn', title: 'Unterseite nicht gespiegelt', text: 'Gerber zeigt die Unterseite von oben durch die Platine. Ungespiegelt passt sie nicht zu den Bohrungen der Oberseite.' });
  if (s.side === 'top' && s.mirror) out.push({ id: 'mirror', tone: 'warn', title: 'Oberseite gespiegelt', text: 'Die Oberseite wird normalerweise nicht gespiegelt.' });
  return out;
}

/** Burn length and travel for a time estimate. Rough on purpose: no acceleration. */
export function estimateSeconds(layer: Pick<PlanLayer, 'mode' | 'polys' | 'intervalMm' | 'speed'>, overscanMm = 2.5): number {
  const perMm = 60 / Math.max(1, layer.speed);
  if (layer.mode === 'LINE') {
    let len = 0;
    for (const p of layer.polys) for (let i = 1; i < p.length; i++) len += Math.hypot(p[i].x - p[i - 1].x, p[i].y - p[i - 1].y);
    return len * perMm;
  }
  const b = boundsOf(layer.polys);
  if (!b) return 0;
  let burn = 0, runs = 0;
  for (let y = b.minY + layer.intervalMm / 2; y <= b.maxY; y += layer.intervalMm) {
    const xs: number[] = [];
    for (const p of layer.polys) for (let i = 1; i < p.length; i++) {
      const u = p[i - 1], v = p[i];
      if ((u.y <= y && v.y > y) || (v.y <= y && u.y > y)) xs.push(u.x + ((y - u.y) * (v.x - u.x)) / (v.y - u.y));
    }
    xs.sort((m, n) => m - n);
    for (let i = 0; i + 1 < xs.length; i += 2) { burn += xs[i + 1] - xs[i]; runs++; }
  }
  return (burn + runs * 2 * overscanMm) * perMm;
}

export interface ApplyOptions { stage: Stage; replace: boolean }

/**
 * Adds the plan to the document's active plate. All layers are created; only the chosen work stage has
 * output on, so a later stage cannot be burned before its turn (mask lacquer does not exist yet then).
 */
export function applyPlanToDoc(doc: Doc, plan: Plan, s: JobSettings, opt: ApplyOptions): { doc: Doc; ids: string[] } {
  const groupId = newId();
  const layers: Layer[] = [...doc.layers];
  const ids: string[] = [];
  const created: Element[] = [];
  const replaced = new Set<string>();
  for (const pl of plan.layers) {
    const over = {
      mode: pl.mode, color: pl.color, powerPct: pl.powerPct, speed: pl.speed, intervalMm: pl.intervalMm, passes: 1,
      output: pl.stage === opt.stage && pl.output, visible: true,
    };
    let idx = layers.findIndex((l) => l.name === pl.name);
    if (idx >= 0) layers[idx] = { ...layers[idx], ...over };
    else { layers.push(newLayer(pl.name, pl.color, pl.mode, over)); idx = layers.length - 1; }
    replaced.add(layers[idx].id);
    const paths = pl.polys.map((p) => p.map((q) => toJob(q, plan.bounds, s.mirror)));
    const el = newElement(layers[idx].id, 'Platine', { paths, groupId, plate: doc.activePlate, transform: { ...IDENTITY, x: s.x, y: s.y } });
    created.push(el);
    ids.push(el.id);
  }
  const kept = opt.replace ? doc.elements.filter((e) => !(e.plate === doc.activePlate && layers.some((l) => l.id === e.layerId && PLATINE_LAYER_NAMES.some((n) => l.name.startsWith(n))))) : doc.elements;
  return { doc: { ...doc, layers, elements: [...kept, ...created] }, ids };
}

export const hasPlatineElements = (doc: Doc) => doc.elements.some((e) => e.plate === doc.activePlate && doc.layers.some((l) => l.id === e.layerId && PLATINE_LAYER_NAMES.some((n) => l.name.startsWith(n))));

export const planArea = (l: PlanLayer) => l.mode === 'FILL' ? polysArea(l.polys) : 0;
