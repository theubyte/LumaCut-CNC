import { create } from 'zustand';
import { type Doc, type Element, type Layer, newDoc, normalize, STANDARD_LAYERS } from '@/core/model';

/**
 * The open project, undo history, selection. One store for everything that edits the design:
 * editor, importers, generators, PCB, workshop all add through `addElements` / `commit`.
 * Every user-visible change is one `commit` and therefore one undo step.
 */
const HISTORY = 200;
interface DocState {
  doc: Doc; past: Doc[]; future: Doc[]; selection: string[]; activeLayerId: string; dirty: boolean; filePath: string | null;
  /** Replace the document as one undo step. `fn` gets the current doc. */
  commit(fn: (d: Doc) => Doc): void;
  /** Change without a new undo step (while dragging). Call `checkpoint()` once before the drag. */
  mutate(fn: (d: Doc) => Doc): void;
  checkpoint(): void;
  undo(): void; redo(): void;
  select(ids: string[]): void;
  setActiveLayer(id: string): void;
  /** Add to the active plate; selects the new elements. */
  addElements(els: Element[]): void;
  /** Layer by internal name; a missing standard layer is created. */
  layerByName(name: string): Layer;
  load(doc: Doc, filePath?: string | null): void;
  reset(): void;
  markSaved(filePath?: string | null): void;
}
const firstLayer = (d: Doc) => d.layers.find((l) => l.name === 'Gravieren')?.id ?? d.layers[0].id;

export const useDoc = create<DocState>((set, get) => {
  const init = newDoc();
  return {
    doc: init, past: [], future: [], selection: [], activeLayerId: firstLayer(init), dirty: false, filePath: null,
    commit: (fn) => { const s = get(); const doc = fn(s.doc); if (doc !== s.doc) set({ doc, past: [...s.past.slice(-HISTORY + 1), s.doc], future: [], dirty: true }); },
    mutate: (fn) => set((s) => ({ doc: fn(s.doc), dirty: true })),
    checkpoint: () => set((s) => ({ past: [...s.past.slice(-HISTORY + 1), s.doc], future: [] })),
    undo: () => { const s = get(); const prev = s.past[s.past.length - 1]; if (!prev) return;
      set({ doc: prev, past: s.past.slice(0, -1), future: [s.doc, ...s.future], dirty: true, selection: s.selection.filter((id) => prev.elements.some((e) => e.id === id)) }); },
    redo: () => { const s = get(); const next = s.future[0]; if (!next) return;
      set({ doc: next, future: s.future.slice(1), past: [...s.past, s.doc], dirty: true, selection: s.selection.filter((id) => next.elements.some((e) => e.id === id)) }); },
    select: (selection) => set({ selection }),
    setActiveLayer: (activeLayerId) => set({ activeLayerId }),
    addElements: (els) => { const s = get(); s.commit((d) => ({ ...d, elements: [...d.elements, ...els.map((e) => ({ ...e, plate: d.activePlate }))] })); set({ selection: els.map((e) => e.id) }); },
    layerByName: (name) => { const d = get().doc; const hit = d.layers.find((l) => l.name === name); if (hit) return hit;
      if (!STANDARD_LAYERS.has(name)) return d.layers[0]; const fresh = newDoc().layers.find((l) => l.name === name)!;
      get().commit((x) => ({ ...x, layers: [...x.layers, fresh] })); return fresh; },
    load: (doc, filePath = null) => { const n = normalize(doc); set({ doc: n, past: [], future: [], selection: [], activeLayerId: firstLayer(n), dirty: false, filePath }); },
    reset: () => { const n = newDoc(); set({ doc: n, past: [], future: [], selection: [], activeLayerId: firstLayer(n), dirty: false, filePath: null }); },
    markSaved: (filePath) => set((s) => ({ dirty: false, filePath: filePath === undefined ? s.filePath : filePath })),
  };
});
