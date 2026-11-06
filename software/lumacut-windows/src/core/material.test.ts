import { describe, expect, it } from 'vitest';
import { applyGroupToDoc, applyMaterial, effectivePasses, focusDropOk, groupMaterials, lowPower, type PiMaterial } from './material';
import { newDoc, newLayer } from './model';

const mk = (o: Partial<PiMaterial>): PiMaterial => ({ id: 'x', name: 'MDF', thickness_mm: 3, process: 'Schneiden', mode: 'line', power_pct: 90, speed_mm_min: 300, passes: 1, interval_mm: 0.1, depth_per_pass_mm: 0, z_step_mm: 0, ...o });

describe('Material', () => {
  it('groups by name and thickness, sorted, with search over name and process', () => {
    const list = [mk({ id: '1', name: 'Zirbe' }), mk({ id: '2', process: 'Gravieren' }), mk({ id: '3' }), mk({ id: '4', thickness_mm: 6 })];
    const g = groupMaterials(list);
    expect(g.map((x) => x.key)).toEqual(['MDF|3', 'MDF|6', 'Zirbe|3']);
    expect(g[0].entries).toHaveLength(2);
    expect(groupMaterials(list, 'gravier').map((x) => x.key)).toEqual(['MDF|3']);
    expect(groupMaterials(list, 'zir').map((x) => x.key)).toEqual(['Zirbe|3']);
  });
  it('derives passes from depth per pass like the Android app', () => {
    expect(effectivePasses(mk({ thickness_mm: 3, depth_per_pass_mm: 1.5, passes: 9 }))).toBe(2);
    expect(effectivePasses(mk({ thickness_mm: 3.1, depth_per_pass_mm: 1.5 }))).toBe(3);
    expect(effectivePasses(mk({ passes: 4 }))).toBe(4);
  });
  it('limits the focus drop over all passes to 3 mm when applied', () => {
    const l = applyMaterial(mk({ passes: 4, z_step_mm: 2 }), newLayer('Schneiden', 0, 'LINE'));
    expect(l.passes).toBe(4);
    expect(l.zStepMm).toBeCloseTo(1);
    expect(applyMaterial(mk({ passes: 1, z_step_mm: 2 }), newLayer('Schneiden', 0, 'LINE')).zStepMm).toBe(0);
  });
  it('applies each process to its layer, Markieren to the layer named Linie, others stay', () => {
    const doc = newDoc();
    doc.layers.push(newLayer('Eigene', 0, 'LINE', { powerPct: 11 }));
    const entries = [mk({ id: 'g', process: 'Gravieren', mode: 'fill', power_pct: 20, tone_curve: { points: [] } }), mk({ id: 'm', process: 'Markieren', power_pct: 30 })];
    const out = applyGroupToDoc(doc, { key: 'k', name: 'MDF', thicknessMm: 3, entries });
    const by = (n: string) => out.layers.find((l) => l.name === n)!;
    expect(by('Gravieren').powerPct).toBe(20);
    expect(by('Gravieren').mode).toBe('FILL');
    expect(by('Gravieren').darkness).toEqual({ points: [] });
    expect(by('Linie').powerPct).toBe(30);
    expect(by('Linie').materialName).toBe('MDF');
    expect(by('Schneiden').powerPct).toBe(doc.layers.find((l) => l.name === 'Schneiden')!.powerPct);
    expect(by('Eigene').powerPct).toBe(11);
  });
  it('returns the same document when no process fits, so no undo step is created', () => {
    const doc = newDoc();
    doc.layers = [newLayer('Eigene', 0, 'LINE')];
    expect(applyGroupToDoc(doc, { key: 'k', name: 'MDF', thicknessMm: 3, entries: [mk({})] })).toBe(doc);
  });
  it('warns below the reliable power and over the focus limit', () => {
    expect(lowPower({ power_pct: 5 })).toBe(true);
    expect(lowPower({ power_pct: 8 })).toBe(false);
    expect(focusDropOk(4, 1)).toBe(true);
    expect(focusDropOk(4, 1.1)).toBe(false);
  });
});
