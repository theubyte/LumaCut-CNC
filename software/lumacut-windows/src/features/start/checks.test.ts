import { describe, expect, it } from 'vitest';
import { newDoc, newElement, Bed } from '@/core/model';
import type { MachineStatus } from '@/pi/types';
import { blocksStart, computeChecks, machineBlocker } from './checks';

const READY: MachineStatus = { connected: true, owner: 'Frei', homed: true, config: { validated: true } };
const bed = { width: Bed.width, height: Bed.height };
const square = [{ x: 0, y: 0 }, { x: 20, y: 0 }, { x: 20, y: 20 }, { x: 0, y: 20 }, { x: 0, y: 0 }];

function docWith(at: { x: number; y: number }, over: { power?: number; speed?: number; image?: boolean; rotation?: number } = {}) {
  const d = newDoc();
  const l = d.layers.find((x) => x.name === 'Linie')!;
  if (over.power != null) l.powerPct = over.power;
  if (over.speed != null) l.speed = over.speed;
  d.elements.push(newElement(l.id, over.image ? 'Bild' : 'Rechteck', {
    paths: over.image ? [] : [square], transform: { ...at, scaleX: 1, scaleY: 1, rotation: over.rotation ?? 0 },
    ...(over.image ? { raster: { width: 1, height: 1, grayBase64: 'AA==' }, imageWidthMm: 20, imageHeightMm: 20 } : {}),
  }));
  return d;
}
const run = (doc: ReturnType<typeof newDoc>, more: Partial<Parameters<typeof computeChecks>[0]> = {}) =>
  computeChecks({ doc, toolpath: null, status: READY, online: true, material: { name: 'Pappel', thickness_mm: 4 }, materialTested: true, motion: { accel: 1000, speed: 300 }, bed, ...more });
const ids = (c: { id: string }[]) => c.map((x) => x.id);

describe('Prüfungen vor dem Start', () => {
  it('nennt nur den Hinweis zum Neuscannen, wenn alles passt', () => {
    const c = run(docWith({ x: 60, y: 60 }));
    expect(ids(c)).toEqual(['moved']);
    expect(blocksStart(c)).toBe(false);
  });
  it('sperrt ohne Material', () => {
    const c = run(docWith({ x: 60, y: 60 }), { material: null });
    expect(ids(c)).toContain('material');
    expect(blocksStart(c)).toBe(true);
  });
  it('sagt nichts zum Material, solange der Arbeitsstand unbekannt ist', () => {
    expect(ids(run(docWith({ x: 60, y: 60 }), { material: undefined }))).not.toContain('material');
  });
  it('erkennt außerhalb und Park-Ecke', () => {
    expect(ids(run(docWith({ x: Bed.width - 5, y: 100 })))).toContain('outside');
    expect(ids(run(docWith({ x: Bed.width - 30, y: 2 })))).toContain('park');
  });
  it('gedrehtes Bild sperrt und verdrängt den gleichen Satz des Schreibers', () => {
    const c = run(docWith({ x: 100, y: 100 }, { image: true, rotation: 15 }), { buildError: 'Gedrehte Bilder werden noch nicht unterstützt' });
    expect(ids(c)).toContain('rotated');
    expect(ids(c)).not.toContain('build');
  });
  it('zeigt jeden anderen Fehler des Schreibers als Prüfung', () => {
    const c = run(docWith({ x: 60, y: 60 }), { buildError: 'Ungültige Werte auf Ebene „Linie“' });
    expect(c.find((x) => x.id === 'build')?.text).toContain('Ungültige Werte');
    expect(blocksStart(c)).toBe(true);
  });
  it('warnt unter 8 % und sperrt nicht', () => {
    const c = run(docWith({ x: 60, y: 60 }, { power: 7 }));
    expect(c.some((x) => x.id.startsWith('weak-') && x.tone === 'warn')).toBe(true);
    expect(blocksStart(c)).toBe(false);
    expect(run(docWith({ x: 60, y: 60 }, { power: 8 })).some((x) => x.id.startsWith('weak-'))).toBe(false);
  });
  it('sperrt, wenn eine Ebene schneller ist als die Maschine', () => {
    const c = run(docWith({ x: 60, y: 60 }, { speed: 18001 }));
    expect(c.some((x) => x.id.startsWith('fast-') && x.tone === 'bad')).toBe(true);
  });
  it('warnt bei ungetestetem Material', () => {
    expect(ids(run(docWith({ x: 60, y: 60 }), { materialTested: false }))).toContain('untested');
  });
  it('die Ablehnung des Pi steht ganz oben', () => {
    expect(run(docWith({ x: 60, y: 60 }), { rejection: 'G-Code Zeile 3: …' })[0].id).toBe('rejected');
  });
});

describe('Maschine nicht bereit', () => {
  it('nennt den Grund', () => {
    expect(machineBlocker(READY, false)).toContain('nicht erreichbar');
    expect(machineBlocker({ ...READY, emergency_latched: true }, true)).toContain('Not-Aus');
    expect(machineBlocker({ ...READY, connected: false }, true)).toContain('USB');
    expect(machineBlocker({ ...READY, owner: 'LightBurn' }, true)).toContain('LightBurn');
    expect(machineBlocker({ ...READY, config: { validated: false } }, true)).toContain('freigegeben');
    expect(machineBlocker(READY, true)).toBeNull();
  });
});
