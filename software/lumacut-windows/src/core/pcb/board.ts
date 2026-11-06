/** Turns a set of fabrication files into one board: copper, mask, silk, outline, drills, and design checks. */
import { boundsOf, type Box, type Poly, type Pt } from '@/core/model';
import { addPolys, polysArea, ringArea } from './clipper';
import { parseExcellon, type DrillHit, type DrillSlot, type ExcellonResult } from './excellon';
import { parseGerber, type GerberResult } from './gerber';
import { classifyLayer, type LayerKind } from './layers';

export interface PcbFile { id: string; name: string; text: string; kind: LayerKind; gerber?: GerberResult; drill?: ExcellonResult; error?: string }
export type Side = 'top' | 'bottom';

export interface SideArt { polys: Poly[]; minStroke: number | null; area: number }
export interface Board {
  copper: Partial<Record<Side, SideArt>>;
  mask: Partial<Record<Side, SideArt>>;
  silk: Partial<Record<Side, SideArt>>;
  /** Closed loops, largest first. The first one is the board edge. */
  outline: Poly[];
  outlineFromFile: boolean;
  drills: DrillHit[];
  slots: DrillSlot[];
  bounds: Box;
  warnings: string[];
}

let nextId = 1;
/** Reads one file. Parse errors are stored on the file, so the list can show them instead of failing. */
export function readPcbFile(name: string, text: string, kind?: LayerKind): PcbFile {
  const k = kind ?? classifyLayer(name, text);
  const file: PcbFile = { id: `f${nextId++}`, name, text, kind: k };
  return parseAs(file, k);
}
/** Same file read as another layer type: a drill file parses differently from Gerber. */
export function parseAs(file: PcbFile, kind: LayerKind): PcbFile {
  const out: PcbFile = { id: file.id, name: file.name, text: file.text, kind };
  if (kind === 'other') return out;
  try {
    if (kind === 'drill') out.drill = file.drill ?? parseExcellon(file.text);
    else out.gerber = file.gerber ?? parseGerber(file.text);
  } catch (e) { out.error = (e as Error).message; }
  return out;
}

/** Joins drawn lines end to end. Returns closed loops, largest first. */
export function stitchLoops(lines: Poly[], tolMm = 0.02): Poly[] {
  const open = lines.filter((l) => l.length >= 2).map((l) => [...l]);
  const same = (a: Pt, b: Pt) => Math.hypot(a.x - b.x, a.y - b.y) <= tolMm;
  const loops: Poly[] = [];
  while (open.length) {
    const cur = open.pop()!;
    let grew = true;
    while (grew && !same(cur[0], cur[cur.length - 1])) {
      grew = false;
      for (let i = open.length - 1; i >= 0; i--) {
        const c = open[i], end = cur[cur.length - 1];
        if (same(c[0], end)) cur.push(...c.slice(1));
        else if (same(c[c.length - 1], end)) cur.push(...[...c].reverse().slice(1));
        else continue;
        open.splice(i, 1); grew = true; break;
      }
    }
    if (cur.length >= 4 && same(cur[0], cur[cur.length - 1])) { cur[cur.length - 1] = { ...cur[0] }; loops.push(cur); }
  }
  return loops.sort((a, b) => Math.abs(ringArea(b)) - Math.abs(ringArea(a)));
}

const art = (files: PcbFile[], kind: LayerKind): SideArt | undefined => {
  const gs = files.filter((f) => f.kind === kind && f.gerber).map((f) => f.gerber!);
  if (!gs.length) return undefined;
  const polys = gs.length === 1 ? gs[0].polys : gs.reduce<Poly[]>((acc, g) => addPolys(acc, g.polys), []);
  const widths = gs.map((g) => g.minStrokeWidth).filter((w): w is number => w != null);
  return { polys, minStroke: widths.length ? Math.min(...widths) : null, area: polysArea(polys) };
};

export function buildBoard(files: PcbFile[]): Board | null {
  const warnings: string[] = [];
  const copper = { top: art(files, 'copper-top'), bottom: art(files, 'copper-bottom') };
  const mask = { top: art(files, 'mask-top'), bottom: art(files, 'mask-bottom') };
  const silk = { top: art(files, 'silk-top'), bottom: art(files, 'silk-bottom') };
  const drillFiles = files.filter((f) => f.kind === 'drill' && f.drill).map((f) => f.drill!);
  const drills = drillFiles.flatMap((d) => d.hits), slots = drillFiles.flatMap((d) => d.slots);

  const outlineFiles = files.filter((f) => f.kind === 'outline' && f.gerber).map((f) => f.gerber!);
  let outline = stitchLoops(outlineFiles.flatMap((g) => g.strokes.map((s) => s.pts)));
  if (!outline.length) outline = outlineFiles.flatMap((g) => g.polys.filter((p) => ringArea(p) > 0)).sort((a, b) => ringArea(b) - ringArea(a));
  const outlineFromFile = outline.length > 0;
  if (outlineFiles.length && !outlineFromFile) warnings.push('Die Umrissdatei ergibt keine geschlossene Kontur. Der Umriss ist aus dem Kupfer geschätzt.');

  const box = outlineFromFile ? boundsOf([outline[0]]) : boundsOf([
    ...(copper.top?.polys ?? []), ...(copper.bottom?.polys ?? []), ...(mask.top?.polys ?? []), ...(mask.bottom?.polys ?? []), ...(silk.top?.polys ?? []), ...(silk.bottom?.polys ?? []),
    ...drills.map((d) => [{ x: d.x, y: d.y }]),
  ]);
  if (!box) return null;
  if (!outlineFromFile) {
    const m = 1;
    const b = { minX: box.minX - m, minY: box.minY - m, maxX: box.maxX + m, maxY: box.maxY + m };
    outline = [[{ x: b.minX, y: b.minY }, { x: b.maxX, y: b.minY }, { x: b.maxX, y: b.maxY }, { x: b.minX, y: b.maxY }, { x: b.minX, y: b.minY }]];
    if (!outlineFiles.length) warnings.push('Keine Umrissdatei: als Umriss gilt ein Rechteck 1 mm um das Kupfer.');
    return { copper, mask, silk, outline, outlineFromFile, drills, slots, bounds: b, warnings };
  }
  return { copper, mask, silk, outline, outlineFromFile, drills, slots, bounds: box, warnings };
}

export interface ClearanceResult { mm: number; at: Pt }

/**
 * Smallest gap between separate copper edges, looking up to `limitMm` far.
 * Rings have copper on their left (outers CCW, holes CW), so a line across copper can be told from a line
 * across a gap at both ends, locally. A line that leaves copper and later crosses some in the middle needs
 * no test: the piece up to that crossing is a shorter real gap and is found by itself.
 * Returns null when everything is further apart than the limit.
 */
export function minClearance(polys: Poly[], limitMm = 2): ClearanceResult | null {
  const cell = 0.5;
  const grid = new Map<number, number[]>();
  const key = (x: number, y: number) => (x + 32768) * 65536 + (y + 32768);
  interface Edge { ax: number; ay: number; bx: number; by: number; loop: number }
  const edges: Edge[] = [];
  polys.forEach((p, loop) => {
    for (let i = 1; i < p.length; i++) {
      const a = p[i - 1], b = p[i];
      if (a.x === b.x && a.y === b.y) continue;
      const id = edges.push({ ax: a.x, ay: a.y, bx: b.x, by: b.y, loop }) - 1;
      const x0 = Math.floor(Math.min(a.x, b.x) / cell), x1 = Math.floor(Math.max(a.x, b.x) / cell);
      const y0 = Math.floor(Math.min(a.y, b.y) / cell), y1 = Math.floor(Math.max(a.y, b.y) / cell);
      for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) {
        const k = key(x, y); const l = grid.get(k);
        if (l) l.push(id); else grid.set(k, [id]);
      }
    }
  });
  let best = limitMm, at: Pt | null = null;
  polys.forEach((p, loop) => {
    const n = p.length - 1; // closed ring: last point repeats the first
    for (let i = 0; i < n; i++) {
      const v = p[i], prev = p[(i + n - 1) % n], next = p[(i + 1) % n];
      const e1x = v.x - prev.x, e1y = v.y - prev.y, e2x = next.x - v.x, e2y = next.y - v.y;
      const convex = e1x * e2y - e1y * e2x >= 0;
      const gx = Math.floor(v.x / cell), gy = Math.floor(v.y / cell);
      const reach = Math.ceil(best / cell);
      for (let dx = -reach; dx <= reach; dx++) for (let dy = -reach; dy <= reach; dy++) {
        const list = grid.get(key(gx + dx, gy + dy));
        if (!list) continue;
        for (const id of list) {
          const e = edges[id];
          if (e.loop === loop) continue;
          const ex = e.bx - e.ax, ey = e.by - e.ay;
          const t = Math.max(0, Math.min(1, ((v.x - e.ax) * ex + (v.y - e.ay) * ey) / (ex * ex + ey * ey)));
          const qx = e.ax + t * ex, qy = e.ay + t * ey;
          const cx = qx - v.x, cy = qy - v.y;
          const d = Math.hypot(cx, cy);
          if (d >= best || d < 1e-6) continue;
          if (ex * (v.y - e.ay) - ey * (v.x - e.ax) > 0) continue; // v lies on the copper side of that edge
          const r1 = e1x * cy - e1y * cx < 0, r2 = e2x * cy - e2y * cx < 0;
          if (!(convex ? r1 || r2 : r1 && r2)) continue;           // the line leaves v into its own copper
          best = d; at = { x: v.x + cx / 2, y: v.y + cy / 2 };
        }
      }
    }
  });
  return at ? { mm: best, at } : null;
}
