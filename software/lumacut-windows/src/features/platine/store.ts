import { create } from 'zustand';
import { buildBoard, parseAs, readPcbFile, type Board, type PcbFile } from '@/core/pcb/board';
import { defaultSettings, type JobSettings, type Stage } from '@/core/pcb/job';
import type { LayerKind } from '@/core/pcb/layers';
import { isZip, readZip } from '@/core/pcb/zip';

export type LayerToggle = 'copper' | 'resist' | 'drill' | 'marks' | 'fiducial' | 'mask' | 'silk' | 'outline';

interface PlatineState {
  step: number;
  files: PcbFile[];
  board: Board | null;
  settings: JobSettings;
  stage: Stage;
  viewFrom: 'top' | 'bottom';
  hidden: Partial<Record<LayerToggle, boolean>>;
  placed: boolean;
  setStep(n: number): void;
  setFiles(f: PcbFile[]): void;
  addFiles(entries: { name: string; text: string }[]): void;
  removeFile(id: string): void;
  setKind(id: string, kind: LayerKind): void;
  clear(): void;
  set(p: Partial<JobSettings>): void;
  setStage(s: Stage): void;
  setViewFrom(v: 'top' | 'bottom'): void;
  toggle(k: LayerToggle): void;
  markPlaced(): void;
}

/** Lives outside the view on purpose: going to another section and back keeps the work. */
export const usePlatine = create<PlatineState>((set, get) => ({
  step: 0, files: [], board: null, settings: defaultSettings(), stage: 'resist', viewFrom: 'top', hidden: {}, placed: false,
  setStep: (step) => set({ step }),
  setFiles: (files) => set({ files, board: buildBoard(files) }),
  addFiles: (entries) => {
    const known = new Set(entries.map((e) => e.name));
    const files = [...get().files.filter((f) => !known.has(f.name)), ...entries.map((e) => readPcbFile(e.name, e.text))];
    set({ files, board: buildBoard(files), placed: false });
  },
  removeFile: (id) => { const files = get().files.filter((f) => f.id !== id); set({ files, board: buildBoard(files) }); },
  setKind: (id, kind) => { const files = get().files.map((f) => f.id === id ? parseAs(f, kind) : f); set({ files, board: buildBoard(files) }); },
  clear: () => set({ files: [], board: null, step: 0, placed: false }),
  set: (p) => set((s) => {
    const settings = { ...s.settings, ...p };
    // The side decides the view and, unless changed afterwards by hand, the mirroring.
    if (p.side && p.side !== s.settings.side) { settings.mirror = p.side === 'bottom'; return { settings, viewFrom: p.side }; }
    return { settings };
  }),
  setStage: (stage) => set({ stage }),
  setViewFrom: (viewFrom) => set({ viewFrom }),
  toggle: (k) => set((s) => ({ hidden: { ...s.hidden, [k]: !s.hidden[k] } })),
  markPlaced: () => set({ placed: true }),
}));

const SKIP = /\.(pdf|png|jpe?g|gbrjob|rpt|csv|pos|html|md|zip|step|stp|kicad_\w+)$/i;

/** Unpacks ZIP archives, decodes text, and skips what cannot be fabrication data. */
export async function loadPicked(picked: { name: string; bytes: Uint8Array }[]): Promise<{ name: string; text: string }[]> {
  const dec = new TextDecoder('latin1');
  const out: { name: string; text: string }[] = [];
  for (const p of picked) {
    if (isZip(p.bytes)) {
      for (const e of await readZip(p.bytes)) if (!SKIP.test(e.name)) out.push({ name: e.name.split('/').pop() ?? e.name, text: dec.decode(e.bytes) });
    } else if (!SKIP.test(p.name)) out.push({ name: p.name, text: dec.decode(p.bytes) });
  }
  return out;
}

export const FILE_FILTERS = [{ name: 'Gerber und Bohrdaten', extensions: ['zip', 'gbr', 'ger', 'pho', 'art', 'gtl', 'gbl', 'gts', 'gbs', 'gto', 'gbo', 'gtp', 'gbp', 'gko', 'gm1', 'gm2', 'gml', 'drl', 'xln', 'exc', 'txt', 'nc', 'cmp', 'sol', 'stc', 'sts', 'plc', 'pls', 'dim'] }];
