import { create } from 'zustand';
import type { NewMaterial, PiMaterial } from '@/core/material';
import { pi } from './client';
import { PiError } from './types';

/**
 * The Pi's material database. The Pi is the source; only a copy for the time without connection stays here,
 * and that copy cannot be changed. Every write names the revision it builds on (409 = reload, ask again).
 */
interface MaterialsState {
  items: PiMaterial[]; revision: number; fromPi: boolean; loading: boolean; error: string | null;
}
const CACHE = 'lc.materials';
const cached = (): PiMaterial[] => { try { return JSON.parse(localStorage.getItem(CACHE) ?? '[]'); } catch { return []; } };
export const useMaterials = create<MaterialsState>(() => ({ items: cached(), revision: 0, fromPi: false, loading: false, error: null }));

export async function loadMaterials(): Promise<void> {
  useMaterials.setState({ loading: true });
  try {
    const r = await pi.get<{ revision: number; materials: PiMaterial[] }>('/api/materials');
    try { localStorage.setItem(CACHE, JSON.stringify(r.materials)); } catch { /* copy only */ }
    useMaterials.setState({ items: r.materials, revision: r.revision, fromPi: true, loading: false, error: null });
  } catch (e) {
    useMaterials.setState({ fromPi: false, loading: false, error: (e as Error).message });
  }
}

async function write<T>(what: string, fn: (rev: number) => Promise<T>): Promise<T> {
  const s = useMaterials.getState();
  if (!s.fromPi) throw new Error('Materialien ändern geht nur mit Verbindung zum Pi');
  try {
    const r = await fn(s.revision);
    await loadMaterials();
    return r;
  } catch (e) {
    if (e instanceof PiError && e.status === 409) {
      await loadMaterials();
      throw new Error(`Die Liste wurde inzwischen geändert und neu geladen. Bitte noch einmal ${what}.`);
    }
    throw e;
  }
}

export const createMaterial = (m: NewMaterial) =>
  write('anlegen', (base_revision) => pi.postJson<{ material: PiMaterial }>('/api/materials', { ...m, base_revision })).then((r) => r.material);
/** Only the fields given change; `tone_curve` stays on the Pi unless it is sent. */
export const updateMaterial = (id: string, patch: Partial<NewMaterial>) =>
  write('speichern', (base_revision) => pi.putJson<{ material: PiMaterial }>(`/api/materials/${encodeURIComponent(id)}`, { ...patch, base_revision })).then((r) => r.material);
export const deleteMaterial = (id: string) =>
  write('löschen', (rev) => pi.del(`/api/materials/${encodeURIComponent(id)}?base_revision=${rev}`));
