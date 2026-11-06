import { create } from 'zustand';
import { Bed, type Box, type CurveNode, type Pt } from '@/core/model';

/** Editor state that is not part of the project: tool, view, snapping, background. Never saved into the document. */
export type Tool = 'select' | 'node' | 'rect' | 'ellipse' | 'poly' | 'pen' | 'text' | 'image' | 'measure';

export const RULER = 24;
const PX_PER_MM_100 = 96 / 25.4;
const ZOOM_MIN = 0.3, ZOOM_MAX = 400;

const pref = <T,>(k: string, d: T): T => { try { const v = localStorage.getItem('lc.motiv.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } };
const savePref = (k: string, v: unknown) => { try { localStorage.setItem('lc.motiv.' + k, JSON.stringify(v)); } catch { /* per-device convenience only */ } };

export interface NodeRef { el: string; path: number; node: number }
export interface Draft { nodes: CurveNode[]; open: boolean }
export type MotivDialog = 'contour' | 'vectorize' | 'rename' | 'export' | null;

interface EditorState {
  tool: Tool;
  zoom: number; panX: number; panY: number; canvasW: number; canvasH: number;
  snapGrid: boolean; snapObjects: boolean; showGrid: boolean; lockAspect: boolean;
  bgOn: boolean; bgAlpha: number; bgImage: ImageBitmap | null;
  mouse: Pt | null;
  node: NodeRef | null;
  draft: Draft | null;
  measure: { a: Pt; b: Pt } | null;
  menu: { x: number; y: number } | null;
  dialog: MotivDialog;
  /** Element whose text field in the properties panel should take the keyboard focus. */
  focusTextId: string | null;
  setTool(t: Tool): void;
  setCanvasSize(w: number, h: number): void;
  fit(box?: Box | null): void;
  zoomAt(px: number, py: number, factor: number): void;
  zoomCentered(factor: number): void;
  panBy(dx: number, dy: number): void;
  setPref(k: 'snapGrid' | 'snapObjects' | 'showGrid' | 'lockAspect', v: boolean): void;
  set(p: Partial<EditorState>): void;
}

export const useEditor = create<EditorState>((set, get) => ({
  tool: 'select', zoom: 2, panX: 40, panY: 40, canvasW: 0, canvasH: 0,
  snapGrid: pref('snapGrid', true), snapObjects: pref('snapObjects', true), showGrid: pref('showGrid', true), lockAspect: pref('lockAspect', true),
  bgOn: false, bgAlpha: 0.7, bgImage: null, mouse: null, node: null, draft: null, measure: null, menu: null, dialog: null, focusTextId: null,
  setTool: (tool) => set((s) => ({ tool, draft: null, node: tool === 'node' ? s.node : null, measure: tool === 'measure' ? s.measure : null })),
  setCanvasSize: (canvasW, canvasH) => { const first = get().canvasW === 0; set({ canvasW, canvasH }); if (first) get().fit(); },
  fit: (box) => {
    const s = get(); if (!s.canvasW) return;
    const b = box ?? { minX: 0, minY: 0, maxX: Bed.width, maxY: Bed.height };
    const pad = box ? 56 : 30, w = Math.max(b.maxX - b.minX, 1), h = Math.max(b.maxY - b.minY, 1);
    const availW = s.canvasW - RULER - 2 * pad, availH = s.canvasH - RULER - 2 * pad;
    const zoom = clampZoom(Math.min(availW / w, availH / h));
    set({ zoom, panX: RULER + (s.canvasW - RULER - w * zoom) / 2 - b.minX * zoom, panY: RULER + (s.canvasH - RULER - h * zoom) / 2 - b.minY * zoom });
  },
  zoomAt: (px, py, f) => {
    const s = get(), zoom = clampZoom(s.zoom * f), k = zoom / s.zoom;
    set({ zoom, panX: px - (px - s.panX) * k, panY: py - (py - s.panY) * k });
  },
  zoomCentered: (f) => { const s = get(); s.zoomAt((s.canvasW + RULER) / 2, (s.canvasH + RULER) / 2, f); },
  panBy: (dx, dy) => set((s) => ({ panX: s.panX + dx, panY: s.panY + dy })),
  setPref: (k, v) => { savePref(k, v); set({ [k]: v } as Partial<EditorState>); },
  set: (p) => set(p),
}));
const clampZoom = (z: number) => Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));

export const zoomPercent = (zoom: number) => Math.round(zoom / PX_PER_MM_100 * 100);
export const toScreen = (p: Pt, s = useEditor.getState()): Pt => ({ x: p.x * s.zoom + s.panX, y: p.y * s.zoom + s.panY });
export const toWorld = (px: number, py: number, s = useEditor.getState()): Pt => ({ x: (px - s.panX) / s.zoom, y: (py - s.panY) / s.zoom });

/** Visible grid for a zoom: spacing never closer than about 7 px. */
export function gridSteps(zoom: number): { minor: number; major: number } {
  if (zoom >= 70) return { minor: 0.1, major: 1 };
  if (zoom >= 7) return { minor: 1, major: 10 };
  if (zoom >= 3) return { minor: 5, major: 50 };
  if (zoom >= 1) return { minor: 10, major: 50 };
  return { minor: 50, major: 100 };
}
/** Snap spacing is finer than the visible grid: at the usual zoom shapes land on whole millimetres. */
export const snapStep = (zoom: number) => (zoom >= 25 ? 0.1 : zoom >= 1 ? 1 : 5);
