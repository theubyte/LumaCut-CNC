import { Bed, type Box, boxH, boxUnion, boxW, type Doc, type Element, parkBox, worldBounds } from '../model';
import { shelf } from '../import/layout';

/**
 * Space-saving arrangement. Deliberately simple: bounding boxes on shelves ("Regal"), tallest first,
 * no rotating and no interlocking of shapes. Groups stay together.
 */
export interface NestUnit { key: string; ids: string[]; box: Box }
export interface NestPlan { placements: Map<string, { plate: number; dx: number; dy: number }>; plates: number; leftOut: number; usagePct: number; units: number }

export function nestUnits(elements: Element[]): NestUnit[] {
  const units = new Map<string, NestUnit>();
  for (const e of elements) {
    const b = worldBounds(e); if (!b) continue;
    const key = e.groupId ?? e.id;
    const u = units.get(key);
    if (u) { u.ids.push(e.id); u.box = boxUnion(b, u.box); } else units.set(key, { key, ids: [e.id], box: b });
  }
  return [...units.values()];
}

export function nest(units: NestUnit[], gap = 3, w = Bed.width, h = Bed.height, keepOut: Box | null = parkBox(), maxPlates = 20): NestPlan {
  const placements: NestPlan['placements'] = new Map();
  let rest = units.map((_, i) => i).filter((i) => boxW(units[i].box) <= w - 2 && boxH(units[i].box) <= h - 2);
  let plate = 0;
  while (rest.length && plate < maxPlates) {
    const packed = shelf(rest.map((i) => units[i].box), w, h, gap, keepOut);
    const next: number[] = [];
    rest.forEach((i, k) => {
      const o = packed[k];
      if (!o) { next.push(i); return; }
      for (const id of units[i].ids) placements.set(id, { plate, dx: o.x, dy: o.y });
    });
    if (next.length === rest.length) break;
    rest = next; plate++;
  }
  const placed = units.filter((u) => u.ids.every((id) => placements.has(id)));
  const used = placed.reduce((s, u) => s + boxW(u.box) * boxH(u.box), 0);
  return { placements, plates: plate, leftOut: units.length - placed.length, usagePct: plate ? 100 * used / (plate * w * h) : 0, units: units.length };
}

/** New document with the plan applied. Elements that are not in the plan stay where they are. */
export function applyNest(doc: Doc, plan: NestPlan, basePlate: number): Doc {
  const elements = doc.elements.map((e) => {
    const p = plan.placements.get(e.id);
    return p ? { ...e, plate: basePlate + p.plate, transform: { ...e.transform, x: e.transform.x + p.dx, y: e.transform.y + p.dy } } : e;
  });
  return { ...doc, elements, plateCount: Math.max(doc.plateCount, basePlate + plan.plates, ...elements.map((e) => e.plate + 1)) };
}
