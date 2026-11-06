import { deleteNode, flattenCurves, handleIn, handleOut, insertNode, moveHandle, moveNode, nearestOnPath, nodeCount, toggleSmooth } from '@/core/curves';
import { applyT, Bed, boxH, boxW, type Box, type CurveNode, type CurvePath, type Doc, type Element, invertT, isImage, layerCss, plateElements, type Pt, worldBounds } from '@/core/model';
import { useMachine } from '@/pi/machine';
import { useDoc } from '@/store/doc';
import { toast } from '@/ui/kit';
import { RULER, snapStep, toWorld, useEditor } from './editor';
import * as ops from './ops';
import { drawNodes, drawRulers, drawScene, fmt, geoOf, type Palette, pill, readPalette, setImageReadyListener, type View, WARN_TEXT, warningsOf } from './render';
import { constrain45, snapBox, snapPoint, type SnapTargets, targetsOf } from './snap';

type HandleId = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | 'rot';
interface Frame { corners: Pt[]; rot: number; center: Pt; single: Element | null }
const mid = (a: Pt, b: Pt): Pt => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
const NODE_LIMIT = 5000;
const GHOST_FROM = 400;

function frameOf(els: Element[]): Frame | null {
  if (!els.length) return null;
  if (els.length === 1) {
    const e = els[0], s = ops.localBox(e);
    if (!s) return null;
    const corners = [{ x: s.minX, y: s.minY }, { x: s.maxX, y: s.minY }, { x: s.maxX, y: s.maxY }, { x: s.minX, y: s.maxY }].map((p) => applyT(e.transform, p));
    return { corners, rot: e.transform.rotation, center: mid(corners[0], corners[2]), single: e };
  }
  const b = ops.selectionBox(els); if (!b) return null;
  const corners = [{ x: b.minX, y: b.minY }, { x: b.maxX, y: b.minY }, { x: b.maxX, y: b.maxY }, { x: b.minX, y: b.maxY }];
  return { corners, rot: 0, center: mid(corners[0], corners[2]), single: null };
}
function handlePoints(f: Frame): Record<Exclude<HandleId, 'rot'>, Pt> {
  const [a, b, c, d] = f.corners;
  return { nw: a, n: mid(a, b), ne: b, e: mid(b, c), se: c, s: mid(c, d), sw: d, w: mid(d, a) };
}
const OPPOSITE: Record<Exclude<HandleId, 'rot'>, Exclude<HandleId, 'rot'>> = { nw: 'se', n: 's', ne: 'sw', e: 'w', se: 'nw', s: 'n', sw: 'ne', w: 'e' };
const CURSORS = ['ew-resize', 'nwse-resize', 'ns-resize', 'nesw-resize'];
const HANDLE_ANGLE: Record<Exclude<HandleId, 'rot'>, number> = { e: 0, se: 45, s: 90, sw: 135, w: 180, nw: 225, n: 270, ne: 315 };

type Drag =
  | { t: 'pan'; x: number; y: number }
  | { t: 'move'; base: Map<string, Element>; box: Box; start: Pt; startPx: Pt; started: boolean; targets: SnapTargets; dup: boolean; clickId: string | null; shift: boolean; ghost: boolean; dx: number; dy: number }
  | { t: 'scale'; handle: Exclude<HandleId, 'rot'>; base: Map<string, Element>; frame: Frame; started: boolean; targets: SnapTargets }
  | { t: 'rotate'; base: Map<string, Element>; frame: Frame; a0: number; started: boolean; angle: number }
  | { t: 'band'; a: Pt; b: Pt; add: boolean }
  | { t: 'shape'; kind: 'rect' | 'ellipse'; a: Pt; b: Pt; startPx: Pt; moved: boolean; targets: SnapTargets }
  | { t: 'penNode'; startPx: Pt; moved: boolean; targets: SnapTargets }
  | { t: 'node'; el: string; path: number; node: number; which: 'node' | 'in' | 'out'; curves: CurvePath[]; started: boolean; startPx: Pt; targets: SnapTargets }
  | { t: 'measure'; targets: SnapTargets };

const inputFocused = () => { const a = document.activeElement; return !!a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || a.tagName === 'SELECT' || (a as HTMLElement).isContentEditable); };

/** The drawing surface: two stacked canvases (scene, overlay) and everything the mouse does on them. */
export class Stage {
  private drag: Drag | null = null;
  private sceneDirty = true; private overlayDirty = true; private raf = 0;
  private pal: Palette = readPalette(); private dpr = 1;
  private sctx: CanvasRenderingContext2D; private octx: CanvasRenderingContext2D;
  private hit = document.createElement('canvas').getContext('2d')!;
  private hover: Element | null = null;
  private space = false; private guides: { x: number | null; y: number | null } = { x: null, y: null };
  private rotFrame: Frame | null = null; private measurePending = false;
  private cleanups: (() => void)[] = [];
  /** Left out of the scene while they move as a ghost on the overlay. */
  private hidden: Set<string> | null = null;
  lastSceneMs = 0;

  constructor(private scene: HTMLCanvasElement, private overlay: HTMLCanvasElement, private host: HTMLElement) {
    this.sctx = scene.getContext('2d', { alpha: false })!;
    this.octx = overlay.getContext('2d')!;
    const ro = new ResizeObserver(() => this.resize()); ro.observe(host); this.cleanups.push(() => ro.disconnect());
    this.resize();
    const on = <K extends keyof HTMLElementEventMap>(k: K, f: (e: HTMLElementEventMap[K]) => void, o?: AddEventListenerOptions) => { overlay.addEventListener(k, f as EventListener, o); this.cleanups.push(() => overlay.removeEventListener(k, f as EventListener)); };
    on('pointerdown', (e) => this.down(e)); on('pointermove', (e) => this.move(e)); on('pointerup', (e) => this.up(e)); on('pointercancel', () => this.cancelDrag());
    on('pointerleave', () => { useEditor.getState().set({ mouse: null }); this.hover = null; this.overlayDirty = true; this.kick(); });
    on('wheel', (e) => this.wheel(e), { passive: false }); on('dblclick', (e) => this.dbl(e));
    on('contextmenu', (e) => this.context(e));
    const key = (e: KeyboardEvent) => { if (e.code === 'Space' && !inputFocused()) { if (e.type === 'keydown') e.preventDefault(); this.space = e.type === 'keydown'; this.setCursor(); } };
    window.addEventListener('keydown', key); window.addEventListener('keyup', key);
    this.cleanups.push(() => { window.removeEventListener('keydown', key); window.removeEventListener('keyup', key); });
    this.cleanups.push(useDoc.subscribe((s, p) => { if (s.doc !== p.doc) { this.hover = null; this.invalidate(); } else if (s.selection !== p.selection) this.invalidate(); }));
    this.cleanups.push(useEditor.subscribe((s, p) => {
      if (s.zoom !== p.zoom || s.panX !== p.panX || s.panY !== p.panY || s.showGrid !== p.showGrid || s.bgOn !== p.bgOn || s.bgAlpha !== p.bgAlpha || s.bgImage !== p.bgImage) this.sceneDirty = true;
      this.overlayDirty = true; this.kick(); if (s.tool !== p.tool) this.setCursor();
    }));
    let bedKey = '';
    this.cleanups.push(useMachine.subscribe(() => { const k = `${Bed.width}|${Bed.height}|${Bed.parkX}|${Bed.parkY}`; if (k !== bedKey) { bedKey = k; this.invalidate(); } }));
    const mo = new MutationObserver(() => { this.pal = readPalette(); this.invalidate(); });
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] }); this.cleanups.push(() => mo.disconnect());
    setImageReadyListener(() => this.invalidate());
    this.invalidate();
  }
  destroy() { cancelAnimationFrame(this.raf); this.cleanups.forEach((f) => f()); }
  invalidate() { this.sceneDirty = true; this.overlayDirty = true; this.kick(); }
  private kick() { if (!this.raf) this.raf = requestAnimationFrame(() => { this.raf = 0; this.paint(); }); }

  private resize() {
    const r = this.host.getBoundingClientRect(), w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
    this.dpr = window.devicePixelRatio || 1;
    for (const c of [this.scene, this.overlay]) { c.width = Math.round(w * this.dpr); c.height = Math.round(h * this.dpr); }
    useEditor.getState().setCanvasSize(w, h);
    this.invalidate();
  }
  private view(): View { const s = useEditor.getState(); return { zoom: s.zoom, panX: s.panX, panY: s.panY, w: s.canvasW, h: s.canvasH, dpr: this.dpr }; }

  /* ---- Painting ---- */
  private paint() {
    const v = this.view(), st = useDoc.getState(), ed = useEditor.getState();
    if (this.sceneDirty) {
      this.sceneDirty = false;
      const t0 = performance.now();
      drawScene(this.sctx, v, this.pal, { doc: st.doc, showGrid: ed.showGrid, bg: ed.bgImage, bgOn: ed.bgOn, bgAlpha: ed.bgAlpha, selection: new Set(st.selection), hidden: this.hidden });
      this.lastSceneMs = performance.now() - t0;
    }
    if (this.overlayDirty) { this.overlayDirty = false; this.paintOverlay(v); }
  }
  private sx(p: Pt, v: View): Pt { return { x: p.x * v.zoom + v.panX, y: p.y * v.zoom + v.panY }; }

  private paintOverlay(v: View) {
    const ctx = this.octx, pal = this.pal, st = useDoc.getState(), ed = useEditor.getState(), d = this.drag;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, v.w, v.h);
    const sel = ops.selectedEls();

    // Warnings sit on the object itself.
    ctx.save(); ctx.beginPath(); ctx.rect(RULER, RULER, v.w - RULER, v.h - RULER); ctx.clip();
    for (const w of warningsOf(st.doc)) {
      const a = this.sx({ x: w.box.minX, y: w.box.minY }, v), b = this.sx({ x: w.box.maxX, y: w.box.maxY }, v), tone = w.kind === 'outside' ? pal.bad : pal.warn;
      ctx.strokeStyle = tone; ctx.lineWidth = 1; ctx.setLineDash([5, 3]);
      ctx.strokeRect(Math.round(a.x) - 3.5, Math.round(a.y) - 3.5, Math.round(b.x - a.x) + 7, Math.round(b.y - a.y) + 7); ctx.setLineDash([]);
      pill(ctx, pal, WARN_TEXT[w.kind], Math.max(RULER + 4, Math.min(a.x - 3, v.w - 190)), Math.min(b.y + 10, v.h - 26), w.kind === 'outside' ? 'bad' : 'warn');
    }
    // Hover and selection
    if (this.hover && !d && ed.tool === 'select' && !st.selection.includes(this.hover.id) && !isImage(this.hover)) {
      ctx.save(); ctx.setTransform(this.dpr * v.zoom, 0, 0, this.dpr * v.zoom, this.dpr * v.panX, this.dpr * v.panY);
      ctx.strokeStyle = pal.accent; ctx.lineWidth = 2 / v.zoom; ctx.lineJoin = 'round'; ctx.globalAlpha = 0.7; ctx.stroke(geoOf(this.hover).all); ctx.restore();
    }
    if (d?.t === 'move' && d.ghost) this.paintGhost(ctx, v, d);
    else if (ed.tool === 'select' && d?.t !== 'band') this.paintFrame(ctx, v, sel);
    if (ed.tool === 'node') this.paintNodeEdit(ctx, v, sel);

    // Guides
    ctx.strokeStyle = pal.accent; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
    if (this.guides.x != null) { const x = Math.round(this.guides.x * v.zoom + v.panX) + 0.5; ctx.beginPath(); ctx.moveTo(x, RULER); ctx.lineTo(x, v.h); ctx.stroke(); }
    if (this.guides.y != null) { const y = Math.round(this.guides.y * v.zoom + v.panY) + 0.5; ctx.beginPath(); ctx.moveTo(RULER, y); ctx.lineTo(v.w, y); ctx.stroke(); }
    ctx.setLineDash([]);

    if (d?.t === 'band') {
      const a = this.sx(d.a, v), b = this.sx(d.b, v), crossing = b.x < a.x;
      ctx.fillStyle = pal.accentSoft; ctx.fillRect(a.x, a.y, b.x - a.x, b.y - a.y);
      ctx.strokeStyle = pal.accent; ctx.setLineDash(crossing ? [4, 3] : []); ctx.strokeRect(Math.round(a.x) + 0.5, Math.round(a.y) + 0.5, Math.round(b.x - a.x), Math.round(b.y - a.y)); ctx.setLineDash([]);
    }
    if (d?.t === 'shape' && d.moved) {
      const b = this.shapeBox(d), a = this.sx({ x: b.minX, y: b.minY }, v), w = boxW(b) * v.zoom, h = boxH(b) * v.zoom;
      ctx.strokeStyle = pal.accent; ctx.lineWidth = 1.5; ctx.fillStyle = pal.accentSoft; ctx.beginPath();
      if (d.kind === 'rect') ctx.rect(a.x, a.y, w, h); else ctx.ellipse(a.x + w / 2, a.y + h / 2, w / 2, h / 2, 0, 0, Math.PI * 2);
      ctx.fill(); ctx.stroke();
      pill(ctx, pal, `${fmt(boxW(b))} × ${fmt(boxH(b))} mm`, a.x, a.y + h + 8, 'accent');
    }
    if (ed.draft) this.paintDraft(ctx, v, ed.draft.nodes, ed.tool === 'pen');
    if (ed.measure) this.paintMeasure(ctx, v, ed.measure.a, ed.measure.b);
    ctx.restore();

    drawRulers(ctx, v, pal, ed.mouse, sel.length ? ops.selectionBox(sel) : null);
  }

  private paintGhost(ctx: CanvasRenderingContext2D, v: View, d: Extract<Drag, { t: 'move' }>) {
    const layers = new Map(useDoc.getState().doc.layers.map((l) => [l.id, l]));
    ctx.save(); ctx.setTransform(this.dpr * v.zoom, 0, 0, this.dpr * v.zoom, this.dpr * (v.panX + d.dx * v.zoom), this.dpr * (v.panY + d.dy * v.zoom));
    ctx.lineWidth = 1.25 / v.zoom; ctx.lineJoin = 'round';
    for (const e of d.base.values()) {
      const l = layers.get(e.layerId), g = geoOf(e);
      ctx.strokeStyle = l ? layerCss(l) : this.pal.accent;
      if (isImage(e)) ctx.strokeRect(g.box.minX, g.box.minY, boxW(g.box), boxH(g.box)); else ctx.stroke(g.all);
    }
    ctx.restore();
    const a = this.sx({ x: d.box.minX + d.dx, y: d.box.minY + d.dy }, v), w = boxW(d.box) * v.zoom, h = boxH(d.box) * v.zoom;
    ctx.strokeStyle = this.pal.accent; ctx.lineWidth = 1; ctx.strokeRect(Math.round(a.x) + 0.5, Math.round(a.y) + 0.5, Math.round(w), Math.round(h));
    pill(ctx, this.pal, `X ${fmt(d.box.minX + d.dx)}   Y ${fmt(d.box.minY + d.dy)} mm`, Math.max(a.x, RULER + 4), a.y + h + 10, 'accent');
  }
  private paintFrame(ctx: CanvasRenderingContext2D, v: View, sel: Element[]) {
    const f = this.rotFrame ?? frameOf(sel); if (!f) return;
    const pal = this.pal, c = f.corners.map((p) => this.sx(p, v));
    ctx.strokeStyle = pal.accent; ctx.lineWidth = 1; ctx.beginPath();
    c.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y))); ctx.closePath(); ctx.stroke();
    const d = this.drag;
    if (d?.t === 'move' && d.started) {
      const b = ops.selectionBox(sel);
      if (b) pill(ctx, pal, `X ${fmt(b.minX)}   Y ${fmt(b.minY)} mm`, Math.max(c[3].x, RULER + 4), c[2].y + 10, 'accent');
      return;
    }
    if (d?.t === 'rotate') { pill(ctx, pal, `${fmt(d.angle)}°`, c[0].x, Math.max(c[3].y, c[2].y) + 10, 'accent'); }
    if (d?.t === 'scale') {
      const s = f.single ? ops.localSize(f.single) : (() => { const b = ops.selectionBox(sel); return b ? { w: boxW(b), h: boxH(b) } : null; })();
      if (s) pill(ctx, pal, `${fmt(s.w)} × ${fmt(s.h)} mm`, c[3].x, Math.max(c[2].y, c[3].y) + 10, 'accent');
    }
    const hp = this.screenHandles(f, v);
    // Rotation handle with its stem
    ctx.strokeStyle = pal.accent; ctx.beginPath(); ctx.moveTo(hp.n.x, hp.n.y); ctx.lineTo(hp.rot.x, hp.rot.y); ctx.stroke();
    ctx.fillStyle = pal.surface; ctx.beginPath(); ctx.arc(hp.rot.x, hp.rot.y, 4.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    const small = Math.hypot(c[1].x - c[0].x, c[1].y - c[0].y) < 28 || Math.hypot(c[3].x - c[0].x, c[3].y - c[0].y) < 28;
    ctx.save();
    for (const k of Object.keys(hp) as HandleId[]) {
      if (k === 'rot') continue;
      if (small && k.length === 1) continue;
      const p = hp[k], s = 7;
      ctx.setTransform(this.dpr, 0, 0, this.dpr, this.dpr * Math.round(p.x), this.dpr * Math.round(p.y)); ctx.rotate(f.rot * Math.PI / 180);
      ctx.fillStyle = pal.surface; ctx.fillRect(-s / 2, -s / 2, s, s); ctx.strokeRect(-s / 2 + 0.5, -s / 2 + 0.5, s - 1, s - 1);
    }
    ctx.restore();
  }
  private screenHandles(f: Frame, v: View): Record<HandleId, Pt> {
    const h = handlePoints(f), out = {} as Record<HandleId, Pt>;
    for (const k of Object.keys(h) as Exclude<HandleId, 'rot'>[]) out[k] = this.sx(h[k], v);
    const r = (f.rot - 90) * Math.PI / 180;
    out.rot = { x: out.n.x + Math.cos(r) * 24, y: out.n.y + Math.sin(r) * 24 };
    return out;
  }
  private handleAt(px: Pt, sel: Element[]): HandleId | null {
    const f = frameOf(sel); if (!f) return null;
    const v = this.view(), hp = this.screenHandles(f, v), c = f.corners.map((p) => this.sx(p, v));
    const small = Math.hypot(c[1].x - c[0].x, c[1].y - c[0].y) < 28 || Math.hypot(c[3].x - c[0].x, c[3].y - c[0].y) < 28;
    for (const k of ['rot', 'nw', 'ne', 'se', 'sw', 'n', 'e', 's', 'w'] as HandleId[]) {
      if (small && k.length === 1) continue;
      if (Math.hypot(hp[k].x - px.x, hp[k].y - px.y) <= 7) return k;
    }
    return null;
  }

  private paintNodeEdit(ctx: CanvasRenderingContext2D, v: View, sel: Element[]) {
    const e = this.nodeElement(sel); if (!e) return;
    const ed = useEditor.getState(), curves = ops.curvesOf(e);
    ctx.save(); ctx.setTransform(this.dpr * v.zoom, 0, 0, this.dpr * v.zoom, this.dpr * v.panX, this.dpr * v.panY);
    ctx.strokeStyle = this.pal.accent; ctx.lineWidth = 1.25 / v.zoom; ctx.stroke(geoOf(e).all); ctx.restore();
    if (nodeCount(curves) > NODE_LIMIT) return;
    drawNodes(ctx, v, this.pal, e, curves, ed.node?.el === e.id ? ed.node : null);
  }
  private nodeElement(sel: Element[]): Element | null { return sel.length === 1 && !isImage(sel[0]) && sel[0].text == null ? sel[0] : null; }

  private paintDraft(ctx: CanvasRenderingContext2D, v: View, nodes: CurveNode[], pen: boolean) {
    const pal = this.pal; if (!nodes.length) return;
    ctx.strokeStyle = pal.accent; ctx.lineWidth = 1.5; ctx.beginPath();
    nodes.forEach((n, i) => {
      const p = this.sx(n, v);
      if (!i) { ctx.moveTo(p.x, p.y); return; }
      const a = this.sx(handleOut(nodes[i - 1]), v), b = this.sx(handleIn(n), v); ctx.bezierCurveTo(a.x, a.y, b.x, b.y, p.x, p.y);
    });
    ctx.stroke();
    const ed = useEditor.getState();
    if (ed.mouse && this.drag?.t !== 'penNode') {
      const last = nodes[nodes.length - 1], a = this.sx(handleOut(last), v), m = this.sx(this.cursorWorld ?? ed.mouse, v), l = this.sx(last, v);
      ctx.globalAlpha = 0.6; ctx.setLineDash([4, 3]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(l.x, l.y); ctx.bezierCurveTo(a.x, a.y, m.x, m.y, m.x, m.y); ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
      const len = Math.hypot((this.cursorWorld ?? ed.mouse).x - last.x, (this.cursorWorld ?? ed.mouse).y - last.y);
      pill(ctx, pal, `${fmt(len)} mm`, m.x + 12, m.y + 12, 'plain');
    }
    nodes.forEach((n, i) => {
      const p = this.sx(n, v), r = i === 0 ? 4.5 : 3.5;
      if (pen && i === nodes.length - 1) for (const h of [handleIn(n), handleOut(n)]) {
        if (Math.hypot(h.x - n.x, h.y - n.y) < 1e-6) continue;
        const q = this.sx(h, v);
        ctx.lineWidth = 1; ctx.strokeStyle = pal.accent; ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke();
        ctx.fillStyle = pal.surface; ctx.beginPath(); ctx.arc(q.x, q.y, 3, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      }
      ctx.fillStyle = pal.surface; ctx.strokeStyle = pal.accent; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    });
  }
  private paintMeasure(ctx: CanvasRenderingContext2D, v: View, a: Pt, b: Pt) {
    const pal = this.pal, p = this.sx(a, v), q = this.sx(b, v);
    ctx.strokeStyle = pal.accent; ctx.lineWidth = 1.25; ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke();
    for (const s of [p, q]) { ctx.fillStyle = pal.surface; ctx.beginPath(); ctx.arc(s.x, s.y, 3.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); }
    const dx = b.x - a.x, dy = b.y - a.y;
    pill(ctx, pal, `${fmt(Math.hypot(dx, dy), 2)} mm   ΔX ${fmt(Math.abs(dx), 2)}   ΔY ${fmt(Math.abs(dy), 2)}`, (p.x + q.x) / 2 + 10, (p.y + q.y) / 2 + 10, 'accent');
  }

  /* ---- Input helpers ---- */
  private cursorWorld: Pt | null = null;
  private px(e: PointerEvent | MouseEvent): Pt { const r = this.overlay.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
  private setCursor(px?: Pt, ev?: { altKey: boolean }) {

    const t = useEditor.getState().tool;
    let c = 'default';
    if (this.drag?.t === 'pan') c = 'grabbing';
    else if (this.space) c = 'grab';
    else if (t === 'text') c = 'text';
    else if (t === 'measure' || t === 'rect' || t === 'ellipse' || t === 'poly' || t === 'pen') c = 'crosshair';
    else if (t === 'select' && px) {
      const sel = ops.selectedEls(), h = this.drag ? null : this.handleAt(px, sel);
      if (h === 'rot') c = 'alias';
      else if (h) { const f = frameOf(sel)!, a = (HANDLE_ANGLE[h] + f.rot + 360 + 22.5) % 180; c = CURSORS[Math.floor(a / 45) % 4]; }
      else if (this.hover) c = 'move';
    } else if (t === 'node') c = this.hover ? 'pointer' : 'default';
    if (this.overlay.style.cursor !== c) this.overlay.style.cursor = c;
  }
  private targetsFor(excluded: Set<string>): SnapTargets {
    const d = useDoc.getState().doc, ed = useEditor.getState(), boxes: Box[] = [];
    if (ed.snapObjects) for (const e of plateElements(d)) {
      if (excluded.has(e.id) || boxes.length > 3000) continue;
      const l = d.layers.find((x) => x.id === e.layerId); if (!l?.visible) continue;
      const b = worldBounds(e); if (b) boxes.push(b);
    }
    return targetsOf(boxes, Bed.width, Bed.height, ed.snapObjects);
  }
  private snapOpts(ctrl: boolean) { const ed = useEditor.getState(); return { grid: ed.snapGrid && !ctrl ? snapStep(ed.zoom) : null, tolMm: 6 / ed.zoom }; }
  private snapped(p: Pt, t: SnapTargets, ctrl: boolean): Pt {
    const ed = useEditor.getState();
    if (ctrl || (!ed.snapGrid && !ed.snapObjects)) { this.guides = { x: null, y: null }; return p; }
    const opt = this.snapOpts(ctrl), h = snapPoint(p, ed.snapObjects ? t : { xs: [], ys: [], points: [] }, opt);
    this.guides = { x: h.guideX, y: h.guideY };
    return { x: p.x + h.dx, y: p.y + h.dy };
  }

  /** Top-most element under a point: outlines win over fills, among fills the smallest. */
  private hitTest(w: Pt, ignoreLocked = true): Element | null {
    const d = useDoc.getState().doc, zoom = useEditor.getState().zoom, tol = 5 / zoom, els = plateElements(d);
    this.hit.setTransform(1, 0, 0, 1, 0, 0); this.hit.lineWidth = tol * 2; this.hit.lineJoin = 'round';
    let inside: Element | null = null, area = Infinity;
    for (let i = els.length - 1; i >= 0; i--) {
      const e = els[i];
      if (ignoreLocked && !ops.editableLayer(d, e.layerId)) continue;
      const g = geoOf(e), b = g.box;
      if (w.x < b.minX - tol || w.x > b.maxX + tol || w.y < b.minY - tol || w.y > b.maxY + tol) continue;
      const a = Math.max(boxW(b) * boxH(b), 0.01);
      if (isImage(e)) {
        const q = invertT(e.transform, w);
        if (q.x >= 0 && q.y >= 0 && q.x <= e.imageWidthMm && q.y <= e.imageHeightMm && a < area) { inside = e; area = a; }
        continue;
      }
      if (this.hit.isPointInStroke(g.all, w.x, w.y)) return e;
      if (g.closed && a < area && this.hit.isPointInPath(g.closed, w.x, w.y, 'evenodd')) { inside = e; area = a; }
    }
    return inside;
  }

  /* ---- Pointer ---- */
  private down(e: PointerEvent) {
    (document.activeElement as HTMLElement | null)?.blur?.();
    this.overlay.setPointerCapture(e.pointerId);
    const px = this.px(e), ed = useEditor.getState();
    if (e.button === 1 || (e.button === 0 && this.space)) { e.preventDefault(); this.drag = { t: 'pan', x: e.clientX, y: e.clientY }; this.setCursor(); return; }
    if (e.button !== 0) return;
    if (px.x < RULER || px.y < RULER) return;
    const w = toWorld(px.x, px.y);
    switch (ed.tool) {
      case 'select': this.downSelect(e, px, w); break;
      case 'node': this.downNode(e, px, w); break;
      case 'rect': case 'ellipse': {
        const targets = this.targetsFor(new Set()), a = this.snapped(w, targets, e.ctrlKey);
        this.drag = { t: 'shape', kind: ed.tool, a, b: a, startPx: px, moved: false, targets }; break;
      }
      case 'poly': case 'pen': this.downDraw(e, px, w); break;
      case 'text': void ops.addText(this.snapped(w, this.targetsFor(new Set()), e.ctrlKey)).catch((x) => toast(`Text ging nicht: ${(x as Error).message}`, 'bad')); ed.setTool('select'); break;
      case 'measure': {
        const targets = this.targetsFor(new Set()), p = this.snapMeasure(w, targets);
        if (this.measurePending && ed.measure) { ed.set({ measure: { a: ed.measure.a, b: p } }); this.measurePending = false; }
        else { ed.set({ measure: { a: p, b: p } }); this.drag = { t: 'measure', targets }; }
        break;
      }
      default: break;
    }
  }
  private snapMeasure(w: Pt, t: SnapTargets): Pt {
    const tol = 8 / useEditor.getState().zoom; let best: Pt | null = null, q = tol;
    for (const p of t.points) { const d = Math.hypot(p.x - w.x, p.y - w.y); if (d < q) { q = d; best = p; } }
    return best ?? w;
  }
  private downSelect(e: PointerEvent, px: Pt, w: Pt) {
    const st = useDoc.getState(), sel = ops.selectedEls();
    const h = sel.length ? this.handleAt(px, sel) : null;
    const base = new Map(sel.map((x) => [x.id, x]));
    if (h === 'rot') {
      const f = frameOf(sel)!;
      this.drag = { t: 'rotate', base, frame: f, a0: Math.atan2(w.y - f.center.y, w.x - f.center.x), started: false, angle: 0 };
      return;
    }
    if (h) { this.drag = { t: 'scale', handle: h, base, frame: frameOf(sel)!, started: false, targets: this.targetsFor(new Set(base.keys())) }; return; }
    const target = this.hitTest(w);
    if (!target) { this.drag = { t: 'band', a: w, b: w, add: e.shiftKey }; if (!e.shiftKey) st.select([]); return; }
    const inSel = st.selection.includes(target.id);
    const ids = e.ctrlKey ? [target.id] : ops.expandGroup(st.doc, target);
    if (e.shiftKey) {
      if (inSel) { st.select(st.selection.filter((x) => !ids.includes(x))); return; }
      st.select([...st.selection, ...ids]);
    } else if (!inSel || e.ctrlKey) st.select(ids);
    const now = ops.selectedEls(), box = ops.selectionBox(now);
    if (!box) return;
    this.drag = { t: 'move', base: new Map(now.map((x) => [x.id, x])), box, start: w, startPx: px, started: false, targets: this.targetsFor(new Set(now.map((x) => x.id))), dup: e.altKey,
      clickId: inSel && !e.shiftKey && !e.ctrlKey ? target.id : null, shift: e.shiftKey, ghost: false, dx: 0, dy: 0 };
  }
  private downNode(e: PointerEvent, px: Pt, w: Pt) {
    const st = useDoc.getState(), ed = useEditor.getState(), el = this.nodeElement(ops.selectedEls());
    if (el) {
      const curves = ops.curvesOf(el), hit = nodeCount(curves) <= NODE_LIMIT ? this.nodeHit(el, curves, px) : null;
      if (hit) {
        ed.set({ node: { el: el.id, path: hit.path, node: hit.node } });
        this.drag = { t: 'node', el: el.id, path: hit.path, node: hit.node, which: hit.which, curves, started: false, startPx: px, targets: this.targetsFor(new Set([el.id])) };
        return;
      }
    }
    const target = this.hitTest(w);
    if (!target) { st.select([]); ed.set({ node: null }); return; }
    if (isImage(target)) { toast('Bilder haben keine Knoten. Erst vektorisieren.', 'info'); return; }
    if (target.text != null) { toast('Text hat keine Knoten. Rechtsklick: In Pfade umwandeln.', 'info'); return; }
    st.select([target.id]); ed.set({ node: null });

  }
  private nodeHit(el: Element, curves: CurvePath[], px: Pt): { path: number; node: number; which: 'node' | 'in' | 'out' } | null {
    const v = this.view(), ed = useEditor.getState(), s = (p: Pt) => this.sx(applyT(el.transform, p), v), near = (p: Pt, r: number) => { const q = s(p); return Math.hypot(q.x - px.x, q.y - px.y) <= r; };
    for (let pi = 0; pi < curves.length; pi++) for (let ni = 0; ni < curves[pi].nodes.length; ni++) if (near(curves[pi].nodes[ni], 6)) return { path: pi, node: ni, which: 'node' };
    for (let pi = 0; pi < curves.length; pi++) {
      const c = curves[pi];
      for (let ni = 0; ni < c.nodes.length; ni++) {
        const n = c.nodes[ni], active = ed.node?.el === el.id && ed.node.path === pi && (ed.node.node === ni || Math.abs(ed.node.node - ni) === 1 || Math.abs(ed.node.node - ni) === c.nodes.length - 1);
        if (!active && !(n.smooth && c.nodes.length <= 12)) continue;
        if (n.hx1 != null && near(handleIn(n), 6)) return { path: pi, node: ni, which: 'in' };
        if (n.hx2 != null && near(handleOut(n), 6)) return { path: pi, node: ni, which: 'out' };
      }
    }
    return null;
  }
  private downDraw(e: PointerEvent, px: Pt, w: Pt) {
    const ed = useEditor.getState(), draft = ed.draft, targets = this.targetsFor(new Set());
    if (draft?.nodes.length) {
      const f = draft.nodes[0], s = this.sx(f, this.view());
      if (draft.nodes.length >= 2 && Math.hypot(s.x - px.x, s.y - px.y) <= 8) { this.finishDraft(true); return; }
    }
    let p = this.snapped(w, targets, e.ctrlKey);
    const last = draft?.nodes[draft.nodes.length - 1];
    if (e.shiftKey && last) p = constrain45(last, p);
    const nodes = [...(draft?.nodes ?? []), { x: p.x, y: p.y }];
    ed.set({ draft: { nodes, open: true } });
    this.drag = { t: 'penNode', startPx: px, moved: false, targets };

  }
  finishDraft(closed: boolean) {
    const ed = useEditor.getState(), d = ed.draft; ed.set({ draft: null }); this.guides = { x: null, y: null };
    if (!d || d.nodes.length < 2) return;
    const pen = ed.tool === 'pen', kind = pen ? 'Kurve' : d.nodes.length === 2 && !closed ? 'Linie' : closed ? 'Polygon' : 'Linienzug';
    ops.addDrawn(kind, { closed: closed && d.nodes.length >= 3, nodes: d.nodes });
    ed.setTool('select');
  }

  private move(e: PointerEvent) {
    const px = this.px(e), w = toWorld(px.x, px.y), ed = useEditor.getState(), d = this.drag;
    if (!d) {
      if (px.x < RULER || px.y < RULER) { ed.set({ mouse: null }); return; }
      ed.set({ mouse: w });
      this.hover = ed.tool === 'select' || ed.tool === 'node' ? this.hitTest(w) : null;
      if (ed.tool === 'poly' || ed.tool === 'pen') {
        let p = this.snapped(w, this.targetsFor(new Set()), e.ctrlKey);
        const last = ed.draft?.nodes[ed.draft.nodes.length - 1];
        if (e.shiftKey && last) p = constrain45(last, p);
        this.cursorWorld = p;
      } else if (ed.tool === 'rect' || ed.tool === 'ellipse') { this.snapped(w, this.targetsFor(new Set()), e.ctrlKey); }
      this.setCursor(px, e);
      this.overlayDirty = true; this.kick();
      return;
    }
    ed.set({ mouse: w });
    switch (d.t) {
      case 'pan': ed.panBy(e.clientX - d.x, e.clientY - d.y); d.x = e.clientX; d.y = e.clientY; break;
      case 'band': d.b = w; break;
      case 'move': this.dragMove(d, e, px, w); break;
      case 'scale': this.dragScale(d, e, w); break;
      case 'rotate': this.dragRotate(d, e, w); break;
      case 'shape': if (Math.hypot(px.x - d.startPx.x, px.y - d.startPx.y) > 3) d.moved = true; d.b = this.snapped(w, d.targets, e.ctrlKey); break;
      case 'penNode': this.dragPen(d, e, px, w); break;
      case 'node': this.dragNode(d, e, px, w); break;
      case 'measure': if (ed.measure) ed.set({ measure: { a: ed.measure.a, b: this.snapMeasure(w, d.targets) } }); break;
    }
    this.overlayDirty = true; this.kick();
  }
  private dragMove(d: Extract<Drag, { t: 'move' }>, e: PointerEvent, px: Pt, w: Pt) {
    if (!d.started) {
      if (Math.hypot(px.x - d.startPx.x, px.y - d.startPx.y) < 3) return;
      d.started = true;
      useDoc.getState().checkpoint();
      if (d.dup) d.base = new Map(ops.spawnCopies().map((x) => [x.id, x]));
      // Very large selections move as a picture and land in the document on release.
      d.ghost = d.base.size >= GHOST_FROM;
      if (d.ghost) this.hidden = new Set(d.base.keys());
      this.sceneDirty = true;
    }
    let dx = w.x - d.start.x, dy = w.y - d.start.y;
    if (e.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }
    const ed = useEditor.getState();
    if (!e.ctrlKey && (ed.snapGrid || ed.snapObjects)) {
      const h = snapBox({ minX: d.box.minX + dx, minY: d.box.minY + dy, maxX: d.box.maxX + dx, maxY: d.box.maxY + dy }, ed.snapObjects ? d.targets : { xs: [], ys: [], points: [] }, this.snapOpts(false));
      if (!e.shiftKey || dx) { dx += h.dx; this.guides.x = h.guideX; } else this.guides.x = null;
      if (!e.shiftKey || dy) { dy += h.dy; this.guides.y = h.guideY; } else this.guides.y = null;
    } else this.guides = { x: null, y: null };
    d.dx = dx; d.dy = dy;
    if (!d.ghost) this.applyMove(d);
  }
  private applyMove(d: Extract<Drag, { t: 'move' }>) {
    useDoc.getState().mutate((doc) => ({ ...doc, elements: doc.elements.map((x) => { const b = d.base.get(x.id); return b ? ops.movedBy(b, d.dx, d.dy) : x; }) }));
  }
  private dragScale(d: Extract<Drag, { t: 'scale' }>, e: PointerEvent, w: Pt) {
    const h = handlePoints(d.frame), single = d.frame.single, r = d.frame.rot * Math.PI / 180, u = { x: Math.cos(r), y: Math.sin(r) }, n = { x: -u.y, y: u.x };
    const anchor = e.altKey ? d.frame.center : h[OPPOSITE[d.handle]], grab = h[d.handle];
    const p = Math.abs(d.frame.rot % 90) < 1e-6 ? this.snapped(w, d.targets, e.ctrlKey) : w;
    const dot = (a: Pt, b: Pt) => a.x * b.x + a.y * b.y, o = { x: grab.x - anchor.x, y: grab.y - anchor.y }, c = { x: p.x - anchor.x, y: p.y - anchor.y };
    const hasX = d.handle.includes('e') || d.handle.includes('w'), hasY = d.handle.includes('n') || d.handle.includes('s');
    const ox = dot(o, u), oy = dot(o, n);
    let kx = hasX && Math.abs(ox) > 1e-6 ? Math.max(dot(c, u) / ox, 0.005) : 1, ky = hasY && Math.abs(oy) > 1e-6 ? Math.max(dot(c, n) / oy, 0.005) : 1;
    const corner = hasX && hasY, ed = useEditor.getState();
    if (corner && ed.lockAspect !== e.shiftKey) { const k = Math.max(kx, ky); kx = ky = k; }
    if (!d.started) { d.started = true; useDoc.getState().checkpoint(); }
    useDoc.getState().mutate((doc) => ({ ...doc, elements: doc.elements.map((x) => {
      const b = d.base.get(x.id); if (!b) return x;
      return single ? ops.scaledLocal(b, anchor, kx, ky) : ops.scaledAbout(b, anchor, kx, ky);
    }) }));
  }
  private dragRotate(d: Extract<Drag, { t: 'rotate' }>, e: PointerEvent, w: Pt) {
    let deg = (Math.atan2(w.y - d.frame.center.y, w.x - d.frame.center.x) - d.a0) * 180 / Math.PI;
    if (e.shiftKey) deg = Math.round(deg / 15) * 15;
    deg = ((deg + 540) % 360) - 180;
    if (!d.started) { if (Math.abs(deg) < 0.2) return; d.started = true; useDoc.getState().checkpoint(); }
    d.angle = d.frame.single ? ((d.frame.single.transform.rotation + deg + 540) % 360) - 180 : deg;
    const c = d.frame.center, rad = deg * Math.PI / 180, cs = Math.cos(rad), s = Math.sin(rad);
    this.rotFrame = { ...d.frame, rot: d.frame.rot + deg, corners: d.frame.corners.map((p) => ({ x: c.x + (p.x - c.x) * cs - (p.y - c.y) * s, y: c.y + (p.x - c.x) * s + (p.y - c.y) * cs })) };
    useDoc.getState().mutate((doc) => ({ ...doc, elements: doc.elements.map((x) => { const b = d.base.get(x.id); return b ? ops.rotatedAbout(b, c, deg) : x; }) }));
  }
  private dragPen(d: Extract<Drag, { t: 'penNode' }>, e: PointerEvent, px: Pt, w: Pt) {
    const ed = useEditor.getState(), draft = ed.draft; if (!draft) return;
    if (Math.hypot(px.x - d.startPx.x, px.y - d.startPx.y) > 3) d.moved = true;
    if (!d.moved) return;
    if (ed.tool === 'poly') { this.cursorWorld = this.snapped(w, d.targets, e.ctrlKey); return; }
    const nodes = draft.nodes.slice(), n = nodes[nodes.length - 1], p = e.shiftKey ? constrain45(n, w) : w;
    nodes[nodes.length - 1] = { x: n.x, y: n.y, hx2: p.x, hy2: p.y, hx1: 2 * n.x - p.x, hy1: 2 * n.y - p.y, smooth: true };
    ed.set({ draft: { ...draft, nodes } });
  }
  private dragNode(d: Extract<Drag, { t: 'node' }>, e: PointerEvent, px: Pt, w: Pt) {
    if (!d.started) { if (Math.hypot(px.x - d.startPx.x, px.y - d.startPx.y) < 2) return; d.started = true; useDoc.getState().checkpoint(); }
    const el = useDoc.getState().doc.elements.find((x) => x.id === d.el); if (!el) return;
    const local = invertT(el.transform, this.snapped(w, d.targets, e.ctrlKey));
    const curves = d.curves.map((c, i) => (i !== d.path ? c : d.which === 'node' ? moveNode(c, d.node, local) : moveHandle(c, d.node, d.which, local)));
    this.applyCurves(d.el, curves, false);
  }
  private applyCurves(id: string, curves: CurvePath[], undoStep: boolean) {
    const f = (doc: Doc): Doc => ({ ...doc, elements: doc.elements.map((x) => (x.id === id ? { ...x, curves, paths: flattenCurves(curves) } : x)) });
    if (undoStep) useDoc.getState().commit(f); else useDoc.getState().mutate(f);
  }

  private up(e: PointerEvent) {
    const d = this.drag, ed = useEditor.getState(), st = useDoc.getState(); this.drag = null; this.guides = { x: null, y: null }; this.rotFrame = null;
    if (this.overlay.hasPointerCapture(e.pointerId)) this.overlay.releasePointerCapture(e.pointerId);
    if (this.hidden) { this.hidden = null; this.sceneDirty = true; }
    if (d) switch (d.t) {
      case 'band': this.finishBand(d); break;
      case 'move':
        if (d.ghost) this.applyMove(d);
        if (!d.started && d.clickId) {
          const clicked = st.doc.elements.find((x) => x.id === d.clickId), ids = clicked ? ops.expandGroup(st.doc, clicked) : [];
          if (ids.length && ids.length < st.selection.length) st.select(ids);
        }
        break;
      case 'shape': {
        const b = d.moved ? this.shapeBox(d) : { minX: d.a.x, minY: d.a.y, maxX: d.a.x + 30, maxY: d.a.y + 30 };
        if (boxW(b) > 0.05 && boxH(b) > 0.05) { if (d.kind === 'rect') ops.addRect(b); else ops.addEllipse(b); }
        ed.setTool('select');
        break;
      }
      case 'penNode':
        if (ed.tool === 'poly' && d.moved && ed.draft?.nodes.length === 1 && this.cursorWorld) {
          ed.set({ draft: { open: true, nodes: [...ed.draft.nodes, { x: this.cursorWorld.x, y: this.cursorWorld.y }] } });
          this.finishDraft(false);
        }
        break;
      case 'measure':
        if (ed.measure && Math.hypot(ed.measure.a.x - ed.measure.b.x, ed.measure.a.y - ed.measure.b.y) * ed.zoom < 3) this.measurePending = true;
        break;
      default: break;
    }
    if (d?.t === 'pan') this.setCursor();
    this.overlayDirty = true; this.kick();
  }
  private shapeBox(d: Extract<Drag, { t: 'shape' }>): Box {
    const ev = this.lastKeys; let w = d.b.x - d.a.x, h = d.b.y - d.a.y;
    if (ev.shift) { const s = Math.max(Math.abs(w), Math.abs(h)); w = Math.sign(w || 1) * s; h = Math.sign(h || 1) * s; }
    if (ev.alt) return { minX: d.a.x - Math.abs(w), minY: d.a.y - Math.abs(h), maxX: d.a.x + Math.abs(w), maxY: d.a.y + Math.abs(h) };
    return { minX: Math.min(d.a.x, d.a.x + w), minY: Math.min(d.a.y, d.a.y + h), maxX: Math.max(d.a.x, d.a.x + w), maxY: Math.max(d.a.y, d.a.y + h) };
  }
  private lastKeys = { shift: false, alt: false };
  trackKeys(e: { shiftKey: boolean; altKey: boolean }) { this.lastKeys = { shift: e.shiftKey, alt: e.altKey }; if (this.drag?.t === 'shape') { this.overlayDirty = true; this.kick(); } }
  private finishBand(d: Extract<Drag, { t: 'band' }>) {
    const st = useDoc.getState(), doc = st.doc, crossing = d.b.x < d.a.x;
    const x0 = Math.min(d.a.x, d.b.x), x1 = Math.max(d.a.x, d.b.x), y0 = Math.min(d.a.y, d.b.y), y1 = Math.max(d.a.y, d.b.y);
    if ((x1 - x0) * useEditor.getState().zoom < 2 && (y1 - y0) * useEditor.getState().zoom < 2) return;
    const ids = new Set<string>(d.add ? st.selection : []);
    for (const e of plateElements(doc)) {
      if (!ops.editableLayer(doc, e.layerId)) continue;
      const b = worldBounds(e); if (!b) continue;
      const hit = crossing ? b.maxX >= x0 && b.minX <= x1 && b.maxY >= y0 && b.minY <= y1 : b.minX >= x0 && b.maxX <= x1 && b.minY >= y0 && b.maxY <= y1;
      if (hit) for (const id of ops.expandGroup(doc, e)) ids.add(id);
    }
    st.select([...ids]);
  }
  private cancelDrag() {
    if (this.drag && 'started' in this.drag && this.drag.started) { const st = useDoc.getState(); st.undo(); useDoc.setState({ future: useDoc.getState().future.slice(1) }); }
    this.drag = null; this.hidden = null; this.rotFrame = null; this.guides = { x: null, y: null }; this.invalidate();
  }
  /** Esc during a drag restores the state before it. */
  escape(): boolean {
    if (this.drag) { this.cancelDrag(); return true; }
    const ed = useEditor.getState();
    if (ed.draft) { ed.set({ draft: null }); return true; }
    if (ed.measure) { ed.set({ measure: null }); this.measurePending = false; return true; }
    if (ed.tool !== 'select') { ed.setTool('select'); return true; }
    if (useDoc.getState().selection.length) { useDoc.getState().select([]); return true; }
    return false;
  }

  private wheel(e: WheelEvent) {
    e.preventDefault();
    const px = this.px(e);
    useEditor.getState().zoomAt(px.x, px.y, Math.exp(-e.deltaY * (e.ctrlKey ? 0.006 : 0.0016)));
  }
  private dbl(e: MouseEvent) {
    const px = this.px(e), w = toWorld(px.x, px.y), ed = useEditor.getState(), st = useDoc.getState();
    if (ed.tool === 'poly' || ed.tool === 'pen') {
      const d = ed.draft;
      if (d && d.nodes.length >= 2) {
        // The second click of the double click already added a node on the same spot.
        const a = d.nodes[d.nodes.length - 1], b = d.nodes[d.nodes.length - 2];
        if (Math.hypot(a.x - b.x, a.y - b.y) * ed.zoom < 6) ed.set({ draft: { ...d, nodes: d.nodes.slice(0, -1) } });
      }
      this.finishDraft(false);
      return;
    }
    if (ed.tool === 'select') {
      const hit = this.hitTest(w); if (!hit) return;
      if (hit.text != null) { st.select([hit.id]); ed.set({ focusTextId: hit.id }); return; }
      if (!isImage(hit)) { st.select([hit.id]); ed.setTool('node'); }
      return;
    }
    if (ed.tool === 'node') {
      const el = this.nodeElement(ops.selectedEls()); if (!el) return;
      const curves = ops.curvesOf(el), hit = this.nodeHit(el, curves, px);
      if (hit?.which === 'node') { this.applyCurves(el.id, curves.map((c, i) => (i === hit.path ? toggleSmooth(c, hit.node) : c)), true); return; }
      const q = invertT(el.transform, w);
      let best: { path: number; span: number; t: number; dist: number } | null = null;
      curves.forEach((c, i) => { const h = nearestOnPath(c, q); if (h && (!best || h.dist < best.dist)) best = { path: i, ...h }; });
      const b = best as { path: number; span: number; t: number; dist: number } | null;
      if (b && b.dist * ed.zoom * Math.abs(el.transform.scaleX) < 8) {
        const next = curves.map((c, i) => (i === b.path ? insertNode(c, b.span, b.t) : c));
        this.applyCurves(el.id, next, true);
        ed.set({ node: { el: el.id, path: b.path, node: b.span + 1 } });
      }
    }
  }
  private context(e: MouseEvent) {
    e.preventDefault();
    const px = this.px(e), w = toWorld(px.x, px.y), st = useDoc.getState(), hit = this.hitTest(w);
    if (hit && !st.selection.includes(hit.id)) st.select(ops.expandGroup(st.doc, hit));
    useEditor.getState().set({ menu: { x: e.clientX, y: e.clientY } });
  }
  /** Del in the node tool removes the active node. */
  deleteActiveNode(): boolean {
    const ed = useEditor.getState(), st = useDoc.getState(), ref = ed.node, el = ref && st.doc.elements.find((x) => x.id === ref.el);
    if (!ref || !el) return false;
    const curves = ops.curvesOf(el), c = curves[ref.path] && deleteNode(curves[ref.path], ref.node);
    if (!c) { toast('Weniger Knoten geht bei dieser Form nicht', 'info'); return true; }
    this.applyCurves(el.id, curves.map((x, i) => (i === ref.path ? c : x)), true);
    ed.set({ node: null });
    return true;
  }
}
