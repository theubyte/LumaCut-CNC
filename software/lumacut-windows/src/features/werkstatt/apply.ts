import { newDoc, newLayer, type Doc, type Element, type Layer, plateElements } from '@/core/model';
import { applyNest, type GenResult, resultElements, nestUnits, nest } from '@/core/generators';
import { useDoc } from '@/store/doc';
import { nestPool } from './tools';

/**
 * Puts a result into the open project as one undo step. Layers of the result are created from the
 * standard layer they are based on, or reused by name. Plate 0 of the result lands on the active plate
 * (with `freshPlate` on a new one if that is busy), further plates after the last one.
 */
export function layerMapFor(r: GenResult, doc: Doc): { layers: Layer[]; lookup(ref: string): string } {
  const layers = [...doc.layers];
  const byRef = new Map<string, string>();
  const standard = (name: string) => {
    let hit = layers.find((l) => l.name === name);
    if (!hit) { hit = newDoc().layers.find((l) => l.name === name) ?? layers[0]; if (!layers.includes(hit)) layers.push(hit); }
    return hit;
  };
  for (const g of r.layers ?? []) {
    const existing = layers.find((l) => l.name === g.name);
    if (existing) { byRef.set(g.key, existing.id); continue; }
    const base = standard(g.base);
    const layer: Layer = { ...base, ...newLayer(g.name, g.color ?? base.color, g.over.mode ?? base.mode), powerPct: base.powerPct, minPowerPct: base.minPowerPct, speed: base.speed, passes: base.passes, intervalMm: base.intervalMm, overscanMm: base.overscanMm, zStepMm: base.zStepMm, materialName: base.materialName, thicknessMm: base.thicknessMm, depthPerPassMm: base.depthPerPassMm, toneCurve: base.toneCurve, darkness: base.darkness, ...g.over };
    layers.push(layer);
    byRef.set(g.key, layer.id);
  }
  return { layers, lookup: (ref) => byRef.get(ref) ?? standard(ref).id };
}

export function applyResult(r: GenResult, opts: { freshPlate?: boolean } = {}): { count: number; plates: number; firstPlate: number } {
  const s = useDoc.getState();
  const doc = s.doc;
  const { layers, lookup } = layerMapFor(r, doc);
  const raw = resultElements(r, lookup);
  const plates = new Set(raw.map((e) => e.plate)).size;
  const busy = plateElements(doc).length > 0;
  const start = opts.freshPlate && busy ? doc.plateCount : doc.activePlate;
  const place = (p: number) => p === 0 ? start : start === doc.activePlate ? doc.plateCount + p - 1 : start + p;
  if (plates <= 1 && start === doc.activePlate && layers.length === doc.layers.length) {
    s.addElements(raw);
    return { count: raw.length, plates: 1, firstPlate: start };
  }
  const elements: Element[] = raw.map((e) => ({ ...e, plate: place(e.plate) }));
  s.commit((d) => ({ ...d, layers, elements: [...d.elements, ...elements], plateCount: Math.max(d.plateCount, ...elements.map((e) => e.plate + 1)), activePlate: start }));
  useDoc.getState().select(elements.filter((e) => e.plate === start).map((e) => e.id));
  return { count: elements.length, plates, firstPlate: start };
}

/** Rearranges the parts in the open project as one undo step. */
export function applyNesting(scope: string, gap: number): { moved: number; plates: number; leftOut: number } {
  const s = useDoc.getState();
  const plan = nest(nestUnits(nestPool(s.doc, scope)), gap);
  const base = scope === 'all' ? 0 : s.doc.activePlate;
  // Spilling over from one plate must not land on another plate that is in use.
  const shifted = scope === 'all' || plan.plates <= 1 ? plan : { ...plan, placements: new Map([...plan.placements].map(([id, q]) => [id, { ...q, plate: q.plate === 0 ? 0 : s.doc.plateCount - base + q.plate - 1 }])) };
  s.commit((d) => ({ ...applyNest(d, shifted, base), activePlate: base }));
  return { moved: plan.placements.size, plates: plan.plates, leftOut: plan.leftOut };
}
