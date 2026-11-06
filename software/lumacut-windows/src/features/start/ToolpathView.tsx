import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Maximize, Minus, Pause, Play, Plus, SkipBack } from 'lucide-react';
import { Bed, type Pt } from '@/core/model';
import { type CompactToolpath, formatDuration } from '@/core/toolpath';
import { Button, Check } from '@/ui/kit';
import { type Ink, PathRaster, type ViewXf } from './raster';

const PAD = 34;
const MAX_SCALE = 240;
const PLAY_SECONDS = 14;

interface Theme { canvas: string; sheet: string; grid: string; gridMajor: string; park: string; bad: string; muted: string; faint: string; accent: string; line: string; ink: Ink }
function rgb(el: HTMLElement, value: string): [number, number, number] {
  const probe = document.createElement('span'); probe.style.color = value; el.appendChild(probe);
  const m = getComputedStyle(probe).color.match(/[\d.]+/g) ?? ['0', '0', '0']; probe.remove();
  return [+m[0], +m[1], +m[2]];
}
function readTheme(el: HTMLElement): Theme {
  const v = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  return { canvas: v('--canvas'), sheet: v('--sheet'), grid: v('--grid'), gridMajor: v('--grid-major'), park: v('--park'), bad: v('--bad'), muted: v('--muted'), faint: v('--faint'), accent: v('--accent'), line: v('--line-2'),
    ink: { cut: rgb(el, v('--text')), travel: rgb(el, v('--faint')) } };
}

/** Starts of the laser paths, for stepping through a job path by path. */
function pathStarts(tp: CompactToolpath) {
  const out: number[] = [];
  for (let i = 0, was = false; i < tp.count; i++) { const on = tp.power[i] > 0; if (on && !was) out.push(i); was = on; }
  return out;
}

export interface ToolpathViewProps {
  toolpath: CompactToolpath | null;
  /** While a job runs: its share 0..1 drives the view, the slider follows and is locked. */
  liveFraction?: number | null;
  /** Head position in machine mm. */
  head?: readonly number[] | null;
  overlay?: React.ReactNode;
}

/** Work area to scale with park corner, the job toned by power, zoom, pan and a layer-by-layer playback. */
export function ToolpathView({ toolpath: tp, liveFraction, head, overlay }: ToolpathViewProps) {
  const host = useRef<HTMLDivElement>(null), cv = useRef<HTMLCanvasElement>(null);
  const raster = useRef(new PathRaster());
  const view = useRef<{ scale: number; x: number; y: number } | null>(null); // CSS px; null = fitted
  const [showTravel, setShowTravel] = useState(true);
  const [pos, setPos] = useState<number | null>(null); // playback segment; null = whole job
  const [playing, setPlaying] = useState(false);
  const [zoomPct, setZoomPct] = useState(100);
  const live = liveFraction != null;
  const count = tp?.count ?? 0;
  const upto = live ? Math.round((liveFraction ?? 0) * count) : pos ?? count;
  const starts = useMemo(() => tp ? pathStarts(tp) : [], [tp]);

  useEffect(() => { setPos(null); setPlaying(false); view.current = null; }, [tp]);

  const state = useRef({ tp, upto, head, showTravel });
  state.current = { tp, upto, head, showTravel };
  const theme = useRef<Theme | null>(null);
  const frame = useRef(0);

  const fit = useCallback((w: number, h: number) => {
    const scale = Math.min((w - PAD * 2) / Bed.width, (h - PAD * 2) / Bed.height);
    return { scale, x: (w - Bed.width * scale) / 2, y: (h - Bed.height * scale) / 2 };
  }, []);

  const draw = useCallback(() => {
    frame.current = 0;
    const c = cv.current, el = host.current;
    if (!c || !el) return;
    const t0 = performance.now();
    const dpr = window.devicePixelRatio || 1, W = el.clientWidth, H = el.clientHeight;
    if (W < 2 || H < 2) return;
    const pw = Math.round(W * dpr), ph = Math.round(H * dpr);
    if (c.width !== pw || c.height !== ph) { c.width = pw; c.height = ph; }
    const th = theme.current ??= readTheme(el);
    const v = view.current ?? fit(W, H);
    const ctx = c.getContext('2d')!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = th.canvas; ctx.fillRect(0, 0, W, H);
    drawBed(ctx, v, th, W, H);
    const { tp, upto, head } = state.current;
    if (tp && tp.count) {
      const xf: ViewXf = { scale: v.scale * dpr, ox: v.x * dpr, oy: v.y * dpr };
      const bmp = raster.current.render(tp, upto, xf, pw, ph, th.ink, { showTravel: state.current.showTravel, bedWidth: Bed.width });
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.drawImage(bmp, 0, 0);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (tp.bounds) drawBounds(ctx, v, tp, th);
    }
    const at = headPoint(tp, upto, head);
    if (at) drawHead(ctx, v, at, th);
    c.dataset.renderMs = (performance.now() - t0).toFixed(1);
    c.dataset.upto = String(upto);
  }, [fit]);

  const redraw = useCallback(() => { if (!frame.current) frame.current = requestAnimationFrame(draw); }, [draw]);
  useEffect(redraw, [redraw, tp, upto, head, showTravel]);

  useEffect(() => {
    const el = host.current!;
    const ro = new ResizeObserver(redraw); ro.observe(el);
    const mo = new MutationObserver(() => { theme.current = null; redraw(); });
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => { ro.disconnect(); mo.disconnect(); if (frame.current) cancelAnimationFrame(frame.current); frame.current = 0; };
  }, [redraw]);

  const zoomAt = useCallback((cx: number, cy: number, factor: number) => {
    const el = host.current!, f = fit(el.clientWidth, el.clientHeight);
    const v = view.current ?? f;
    const scale = Math.min(MAX_SCALE, Math.max(f.scale * 0.6, v.scale * factor));
    const k = scale / v.scale;
    view.current = { scale, x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k };
    setZoomPct(Math.round(100 * scale / f.scale));
    redraw();
  }, [fit, redraw]);

  const resetView = () => { view.current = null; setZoomPct(100); redraw(); };

  useEffect(() => {
    const el = host.current!;
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0016));
    };
    el.addEventListener('wheel', wheel, { passive: false });
    return () => el.removeEventListener('wheel', wheel);
  }, [zoomAt]);

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const el = host.current!;
    const start = { px: e.clientX, py: e.clientY, v: view.current ?? fit(el.clientWidth, el.clientHeight) };
    e.currentTarget.setPointerCapture(e.pointerId);
    e.currentTarget.classList.add('dragging');
    const target = e.currentTarget;
    const move = (m: PointerEvent) => { view.current = { scale: start.v.scale, x: start.v.x + m.clientX - start.px, y: start.v.y + m.clientY - start.py }; redraw(); };
    const up = () => { target.classList.remove('dragging'); target.removeEventListener('pointermove', move); target.removeEventListener('pointerup', up); target.removeEventListener('pointercancel', up); };
    target.addEventListener('pointermove', move); target.addEventListener('pointerup', up); target.addEventListener('pointercancel', up);
  };

  // Playback: time-independent, the whole job takes the same few seconds.
  useEffect(() => {
    if (!playing || live || !count) return;
    let raf = 0, last = performance.now();
    let at = pos != null && pos < count ? pos : 0;
    const tick = (now: number) => {
      at = Math.min(count, at + (now - last) / 1000 * count / PLAY_SECONDS);
      last = now;
      setPos(Math.floor(at));
      if (at >= count) { setPlaying(false); return; }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, live, count]); // eslint-disable-line react-hooks/exhaustive-deps

  const step = (dir: 1 | -1) => {
    setPlaying(false);
    const cur = pos ?? (dir < 0 ? count : 0);
    if (dir > 0) { const n = starts.find((s) => s > cur); setPos(n ?? count); }
    else { let hit = 0; for (const s of starts) { if (s >= cur) break; hit = s; } setPos(hit); }
  };

  const fraction = count ? upto / count : 0;
  const seconds = tp?.stats.seconds ?? 0;
  const pathNo = useMemo(() => { let lo = 0, hi = starts.length; while (lo < hi) { const m = (lo + hi) >> 1; if (starts[m] < upto) lo = m + 1; else hi = m; } return lo; }, [starts, upto]);

  return <div className="preview">
    <div className="preview-stage" ref={host}>
      <canvas ref={cv} data-testid="preview-canvas" onPointerDown={onPointerDown} onDoubleClick={resetView} aria-label="Vorschau des Auftrags auf der Arbeitsfläche" />
      <div className="preview-zoom">
        <Button size="sm" iconOnly title="Verkleinern (Mausrad)" aria-label="Verkleinern" icon={<Minus size={14} />} onClick={() => { const el = host.current!; zoomAt(el.clientWidth / 2, el.clientHeight / 2, 1 / 1.4); }} />
        <span className="tnum muted preview-zoom-value" data-testid="zoom-value">{zoomPct} %</span>
        <Button size="sm" iconOnly title="Vergrößern (Mausrad)" aria-label="Vergrößern" icon={<Plus size={14} />} onClick={() => { const el = host.current!; zoomAt(el.clientWidth / 2, el.clientHeight / 2, 1.4); }} />
        <Button size="sm" iconOnly title="Ganze Fläche (Doppelklick)" aria-label="Ganze Fläche" icon={<Maximize size={14} />} onClick={resetView} />
      </div>
      {overlay && <div className="preview-overlay">{overlay}</div>}
    </div>
    <div className="preview-bar">
      <div className="row" style={{ gap: 2 }}>
        <Button variant="ghost" size="sm" iconOnly title="Zum Anfang" aria-label="Zum Anfang" disabled={!count || live} icon={<SkipBack size={14} />} onClick={() => { setPlaying(false); setPos(0); }} />
        <Button variant="ghost" size="sm" iconOnly title="Eine Bahn zurück" aria-label="Eine Bahn zurück" data-testid="step-back" disabled={!count || live} icon={<ChevronLeft size={15} />} onClick={() => step(-1)} />
        <Button variant="ghost" size="sm" iconOnly title={playing ? 'Anhalten' : 'Abspielen'} aria-label={playing ? 'Anhalten' : 'Abspielen'} data-testid="play" disabled={!count || live} icon={playing ? <Pause size={14} /> : <Play size={14} />} onClick={() => setPlaying(!playing)} />
        <Button variant="ghost" size="sm" iconOnly title="Eine Bahn vor" aria-label="Eine Bahn vor" data-testid="step-forward" disabled={!count || live} icon={<ChevronRight size={15} />} onClick={() => step(1)} />
      </div>
      <input type="range" className="preview-slider grow" aria-label="Fortschritt entlang des Auftrags" data-testid="preview-slider" min={0} max={Math.max(1, count)} step={1} value={upto} disabled={!count || live}
        style={{ '--fill': `${(fraction * 100).toFixed(2)}%` } as React.CSSProperties}
        onChange={(e) => { setPlaying(false); const v = +e.target.value; setPos(v >= count ? null : v); }} />
      <span className="tnum muted preview-readout" data-testid="preview-readout">
        {count ? <>Bahn {pathNo} von {starts.length} · {formatDuration(seconds * fraction)}</> : 'Kein Auftrag'}
      </span>
      <Check checked={showTravel} onChange={setShowTravel}>Leerfahrten</Check>
    </div>
  </div>;
}

function headPoint(tp: CompactToolpath | null, upto: number, head?: readonly number[] | null): Pt | null {
  if (head && head.length >= 2) return { x: Bed.width - head[0], y: head[1] };
  if (tp && upto > 0 && upto < tp.count) { const k = (upto - 1) * 4; return { x: Bed.width - tp.xy[k + 2], y: tp.xy[k + 3] }; }
  return null;
}

function drawBed(ctx: CanvasRenderingContext2D, v: { scale: number; x: number; y: number }, th: Theme, W: number, H: number) {
  const { scale: s, x, y } = v, bw = Bed.width * s, bh = Bed.height * s;
  ctx.fillStyle = th.sheet; ctx.fillRect(x, y, bw, bh);
  const left = Math.max(0, Math.ceil(-x / s)), right = Math.min(Bed.width, Math.floor((W - x) / s));
  const top = Math.max(0, Math.ceil(-y / s)), bottom = Math.min(Bed.height, Math.floor((H - y) / s));
  const minor = s >= 12 ? 1 : s >= 1.2 ? 10 : 50;
  const pick = (mm: number) => mm % 50 === 0 ? th.gridMajor : th.grid;
  ctx.lineWidth = 1;
  const lines = (color: string, keep: (mm: number) => boolean) => {
    ctx.strokeStyle = color; ctx.beginPath();
    for (let m = Math.ceil(left / minor) * minor; m <= right; m += minor) if (keep(m)) { const p = Math.round(x + m * s) + .5; ctx.moveTo(p, Math.max(y, 0)); ctx.lineTo(p, Math.min(y + bh, H)); }
    for (let m = Math.ceil(top / minor) * minor; m <= bottom; m += minor) if (keep(m)) { const p = Math.round(y + m * s) + .5; ctx.moveTo(Math.max(x, 0), p); ctx.lineTo(Math.min(x + bw, W), p); }
    ctx.stroke();
  };
  lines(th.grid, (m) => pick(m) === th.grid);
  lines(th.gridMajor, (m) => pick(m) === th.gridMajor);

  // Park corner: never lasered there.
  const kw = Bed.parkX * s, kh = Bed.parkY * s, kx = x + bw - kw;
  ctx.fillStyle = th.park; ctx.fillRect(kx, y, kw, kh);
  ctx.save(); ctx.beginPath(); ctx.rect(kx, y, kw, kh); ctx.clip();
  ctx.strokeStyle = th.park; ctx.lineWidth = 1; ctx.beginPath();
  for (let d = -kh; d < kw; d += 8) { ctx.moveTo(kx + d, y + kh); ctx.lineTo(kx + d + kh, y); }
  ctx.stroke(); ctx.restore();
  if (kw > 58 && kh > 16) {
    ctx.fillStyle = th.bad; ctx.font = '500 11px "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('Park-Ecke', kx + kw / 2, y + kh / 2);
  }
  ctx.strokeStyle = th.line; ctx.lineWidth = 1; ctx.strokeRect(Math.round(x) + .5, Math.round(y) + .5, Math.round(bw), Math.round(bh));

  // Scale along the top and left edge, in work mm.
  ctx.fillStyle = th.faint; ctx.font = '11px "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif';
  const tick = [10, 20, 50, 100].find((t) => t * s >= 44) ?? 200;
  const topY = Math.max(y, 18) - 8, leftX = Math.max(x, 26) - 7;
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  for (let m = Math.ceil(left / tick) * tick; m <= right; m += tick) ctx.fillText(String(m), x + m * s, topY);
  ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  for (let m = Math.ceil(top / tick) * tick; m <= bottom; m += tick) if (m > 0) ctx.fillText(String(m), leftX, y + m * s);
}

function drawBounds(ctx: CanvasRenderingContext2D, v: { scale: number; x: number; y: number }, tp: CompactToolpath, th: Theme) {
  const b = tp.bounds!;
  const x0 = v.x + (Bed.width - b.maxX) * v.scale, y0 = v.y + b.minY * v.scale, w = (b.maxX - b.minX) * v.scale, h = (b.maxY - b.minY) * v.scale;
  ctx.strokeStyle = th.faint; ctx.lineWidth = 1; ctx.setLineDash([4, 5]);
  ctx.strokeRect(Math.round(x0) - 2.5, Math.round(y0) - 2.5, Math.round(w) + 5, Math.round(h) + 5);
  ctx.setLineDash([]);
}

function drawHead(ctx: CanvasRenderingContext2D, v: { scale: number; x: number; y: number }, p: Pt, th: Theme) {
  const x = v.x + p.x * v.scale, y = v.y + p.y * v.scale;
  ctx.strokeStyle = th.accent; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(x - 11, y); ctx.lineTo(x - 3, y); ctx.moveTo(x + 3, y); ctx.lineTo(x + 11, y); ctx.moveTo(x, y - 11); ctx.lineTo(x, y - 3); ctx.moveTo(x, y + 3); ctx.lineTo(x, y + 11); ctx.stroke();
}
