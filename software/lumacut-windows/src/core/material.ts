import { type DarknessCurve, type Doc, type Layer, type LayerMode, Limits } from './model';

/** Material as the Pi stores it (docs/PI_API_REFERENZ.md §4.14, android/core/.../PiMaterials.kt). Unknown fields stay untouched. */
export type Process = 'Gravieren' | 'Markieren' | 'Schneiden';
export const PROCESSES: Process[] = ['Gravieren', 'Markieren', 'Schneiden'];

export interface ToneCurve extends DarknessCurve {
  points?: { power: number; speed: number; tone: number; clean?: boolean }[];
  min_power_pct?: number; interval_mm?: number; speed_min?: number; speed_max?: number;
}
export interface PiMaterial {
  id: string; name: string; thickness_mm: number; process: string; mode: 'line' | 'fill';
  power_pct: number; speed_mm_min: number; passes: number; interval_mm: number; depth_per_pass_mm: number; z_step_mm: number;
  builtin?: boolean; updated?: string; tone_curve?: ToneCurve | null;
  [extra: string]: unknown;
}
export type NewMaterial = Omit<PiMaterial, 'id'>;

export interface MaterialGroup { key: string; name: string; thicknessMm: number; entries: PiMaterial[] }
export const groupKey = (name: string, thicknessMm: number) => `${name}|${thicknessMm}`;
export const entryOf = (g: MaterialGroup, process: string) => g.entries.find((e) => e.process.toLowerCase() === process.toLowerCase());

/** One physical material (name and thickness) with its processes, sorted, optionally filtered by name or process. */
export function groupMaterials(list: PiMaterial[], query = ''): MaterialGroup[] {
  const q = query.trim().toLowerCase();
  const map = new Map<string, MaterialGroup>();
  for (const m of list) {
    if (q && !m.name.toLowerCase().includes(q) && !m.process.toLowerCase().includes(q)) continue;
    const key = groupKey(m.name, m.thickness_mm);
    const g = map.get(key);
    if (g) g.entries.push(m); else map.set(key, { key, name: m.name, thicknessMm: m.thickness_mm, entries: [m] });
  }
  return [...map.values()].sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase(), 'de') || a.thicknessMm - b.thicknessMm);
}

/** Passes from thickness / depth per pass when set, otherwise the stored passes. Same as Material.effectivePasses. */
export function effectivePasses(m: Pick<PiMaterial, 'thickness_mm' | 'depth_per_pass_mm' | 'passes'>): number {
  if (m.depth_per_pass_mm > 0) {
    if (m.thickness_mm <= 0) return 1;
    return Math.min(Limits.PASSES[1], Math.max(Limits.PASSES[0], Math.ceil(m.thickness_mm / m.depth_per_pass_mm - 1e-9)));
  }
  return m.passes;
}

/** Material.applyTo in Design.kt: the focus drop over all passes stays within the limit. */
export function applyMaterial(m: PiMaterial, layer: Layer): Layer {
  const passes = effectivePasses(m);
  const zStepMm = passes > 1 ? Math.min(m.z_step_mm, Limits.MAX_FOCUS_DROP_MM / (passes - 1)) : 0;
  const mode: LayerMode = m.mode === 'fill' ? 'FILL' : 'LINE';
  return { ...layer, mode, powerPct: m.power_pct, speed: m.speed_mm_min, passes, intervalMm: m.interval_mm, zStepMm,
    materialName: m.name, thicknessMm: m.thickness_mm, depthPerPassMm: m.depth_per_pass_mm, darkness: m.tone_curve ?? null };
}

const PROCESS_OF_LAYER: Record<string, Process> = { Gravieren: 'Gravieren', Linie: 'Markieren', Schneiden: 'Schneiden' };

/** EditorViewModel.selectMaterial: every process goes to its standard layer; other layers keep their values. Returns the same doc when nothing applies. */
export function applyGroupToDoc(doc: Doc, g: MaterialGroup): Doc {
  let touched = false;
  const layers = doc.layers.map((l) => {
    const process = PROCESS_OF_LAYER[l.name];
    const m = process && entryOf(g, process);
    if (!m) return l;
    touched = true;
    return applyMaterial(m, l);
  });
  return touched ? { ...doc, layers } : doc;
}

export const defaultMode = (p: string): 'line' | 'fill' => p === 'Gravieren' ? 'fill' : 'line';
/** Start values for a new process. Never meant as tested values; the UI says so. */
export function newProcess(name: string, thickness: number, process: Process): NewMaterial {
  const base = { name, thickness_mm: thickness, process, mode: defaultMode(process), passes: 1, interval_mm: 0.1, depth_per_pass_mm: 0, z_step_mm: 0 };
  if (process === 'Gravieren') return { ...base, power_pct: 25, speed_mm_min: 3000 };
  if (process === 'Markieren') return { ...base, power_pct: 40, speed_mm_min: 1500 };
  return { ...base, power_pct: 85, speed_mm_min: 400 };
}

/** A burning power below this does not fire reliably (STAND.md §4). */
export const lowPower = (m: Pick<PiMaterial, 'power_pct'>) => m.power_pct > 0 && m.power_pct < Limits.MIN_RELIABLE_POWER_PCT;
/** The Pi refuses a focus drop over 3 mm. */
export const focusDropOk = (passes: number, zStep: number) => (passes - 1) * zStep <= Limits.MAX_FOCUS_DROP_MM + 1e-9;
