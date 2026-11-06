import { create } from 'zustand';
import { pi } from './client';
import { useMachine } from './machine';
import { PiError } from './types';

/**
 * The shared working state on the Pi (docs/PI_API_REFERENZ.md, "Arbeitsstand"). The current material
 * lives here: no job starts without it, because its thickness sets the travel height.
 * Read it anywhere with `useWorkspace(s => s.material)`. The store follows `status.sync` by itself.
 */
export interface WorkMaterial { name: string; thickness_mm: number }
export interface PiWorkspace {
  revision: number; material: WorkMaterial | null; areas: number[][]; probe_points: number[][];
  heights: unknown; settings: Record<string, unknown>; updated_at?: string; updated_by?: string;
}
interface WorkspaceState {
  /** The material chosen on any device; null until someone chose one. */
  material: WorkMaterial | null;
  revision: number; loaded: boolean; areas: number[][]; probePoints: number[][];
  /** Revision of the scan image on the Pi (0 = none stored yet). */
  scanRevision: number;
}
export const useWorkspace = create<WorkspaceState>(() => ({ material: null, revision: -1, loaded: false, areas: [], probePoints: [], scanRevision: 0 }));

const DEVICE = 'Windows';
const take = (w: PiWorkspace) => useWorkspace.setState({ material: w.material ?? null, revision: w.revision, loaded: true, areas: w.areas ?? [], probePoints: w.probe_points ?? [] });

let inFlight: Promise<void> | null = null;
export function loadWorkspace(): Promise<void> {
  inFlight ??= pi.get<PiWorkspace>('/api/workspace').then(take).finally(() => { inFlight = null; });
  return inFlight;
}

/** Writes fields on top of what the Pi has. A change from another device in between is taken first, then this one goes on top. */
export async function saveWorkspace(fields: Partial<Pick<PiWorkspace, 'material' | 'areas' | 'probe_points' | 'settings'>>): Promise<void> {
  const body = (base: number) => ({ ...fields, base_revision: base, updated_by: DEVICE });
  if (useWorkspace.getState().revision < 0) await loadWorkspace();
  try {
    take(await pi.putJson<PiWorkspace>('/api/workspace', body(useWorkspace.getState().revision)));
  } catch (e) {
    if (!(e instanceof PiError) || e.status !== 409) throw e;
    await loadWorkspace();
    take(await pi.putJson<PiWorkspace>('/api/workspace', body(useWorkspace.getState().revision)));
  }
}

export const setWorkMaterial = (material: WorkMaterial | null) => saveWorkspace({ material });

/** The workplace scan (PNG, whole work area, row 0 = work Y 0) as a blob, for the editor background. Null when none is stored. */
export async function fetchScanBlob(): Promise<{ blob: Blob; revision: number } | null> {
  try {
    const r = await pi.getBytes('/api/workspace/scan', 30000);
    return { blob: new Blob([r.body as BlobPart], { type: 'image/png' }), revision: useWorkspace.getState().scanRevision };
  } catch (e) {
    if (e instanceof PiError && e.status === 404) return null;
    throw e;
  }
}

// Every device sees the revisions in /api/status; fetch only when ours is behind.
useMachine.subscribe((m) => {
  const sync = m.status.sync;
  if (!m.online || !sync) return;
  const s = useWorkspace.getState();
  if ((sync.scan ?? 0) !== s.scanRevision) useWorkspace.setState({ scanRevision: sync.scan ?? 0 });
  if ((sync.workspace ?? 0) !== s.revision && !inFlight) void loadWorkspace().catch(() => { /* next status retries */ });
});
