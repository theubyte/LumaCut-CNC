import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Maximize, Minus, Plus } from 'lucide-react';
import type { Box, Poly } from '@/core/model';
import type { Board, ClearanceResult } from '@/core/pcb/board';
import type { Plan, PlanLayer, ProcessKey } from '@/core/pcb/job';
import { Button } from '@/ui/kit';
import { useUi } from '@/store/ui';
import type { LayerToggle } from './store';

const toPath = (polys: Poly[], close = true) => {
  const path = new Path2D();
  for (const p of polys) {
    if (p.length < 2) continue;
    path.moveTo(p[0].x, p[0].y);
    for (let i = 1; i < p.length; i++) path.lineTo(p[i].x, p[i].y);
    if (close) path.closePath();
  }
  return path;
};

interface Props {
  board: Board; plan: Plan; beamMm: number;
  side: 'top' | 'bottom'; viewFrom: 'top' | 'bottom';
  hidden: Partial<Record<LayerToggle, boolean>>;
  marker: ClearanceResult | null;
}

const TOGGLE_OF: Partial<Record<ProcessKey, LayerToggle>> = { resist: 'resist', drill: 'marks', fiducial: 'fiducial', mask: 'mask', silk: 'silk' };

/** Board preview on a canvas. Wheel zooms around the pointer, dragging pans, + - 0 work when focused. */
export function BoardPreview({ board, plan, beamMm, side, viewFrom, hidden, marker }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [cam, setCam] = useState<{ s: number; ox: number; oy: number } | null>(null);
  const theme = useUi((u) => u.theme);
  const flip = viewFrom === 'bottom';
  const paths = useMemo(() => ({
    outline: toPath(board.outline),
    copper: toPath(board.copper[side]?.polys ?? []),
    layers: plan.layers.map((l: PlanLayer) => ({ l, path: toPath(l.polys, l.mode === 'FILL') })),
  }), [board, plan, side]);

  const box: Box = plan.bounds;
  const fit = useCallback(() => {
    const c = ref.current; if (!c) return;
    const r = c.getBoundingClientRect(); if (!r.width) return;
    const s = Math.min(r.width / (box.maxX - box.minX + 8), r.height / (box.maxY - box.minY + 8));
    setCam({ s, ox: r.width / 2, oy: r.height / 2 });
  }, [box]);
  useEffect(() => { fit(); }, [fit]);

  const toScreen = useCallback((c: { s: number; ox: number; oy: number }) => {
    const cx = (box.minX + box.maxX) / 2, cy = (box.minY + box.maxY) / 2;
    return { sx: flip ? -c.s : c.s, sy: -c.s, tx: c.ox - (flip ? -c.s : c.s) * cx, ty: c.oy + c.s * cy };
  }, [box, flip]);

  const draw = useCallback(() => {
    const canvas = ref.current; if (!canvas || !cam) return;
    const dpr = devicePixelRatio || 1;
    const r = canvas.getBoundingClientRect();
    const W = Math.round(r.width * dpr), H = Math.round(r.height * dpr);
    if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    const css = getComputedStyle(canvas);
    const col = (n: string) => css.getPropertyValue(n).trim();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const t = toScreen(cam);
    ctx.setTransform(t.sx * dpr, 0, 0, t.sy * dpr, t.tx * dpr, t.ty * dpr);
    const hair = 1 / cam.s;

    ctx.fillStyle = col('--pcb-fr4');
    ctx.fill(paths.outline, 'evenodd');
    if (!hidden.copper) { ctx.fillStyle = col('--pcb-copper'); ctx.fill(paths.copper, 'evenodd'); }

    const paint = (keep: (k: ProcessKey) => boolean) => {
      for (const { l, path } of paths.layers) {
        const tog = TOGGLE_OF[l.key];
        if (!keep(l.key) || (tog && hidden[tog])) continue;
        const colour = l.key === 'mask' ? col('--pcb-mask') : l.key === 'silk' ? col('--pcb-silk') : l.key === 'resist' ? col('--pcb-laser') : col('--pcb-mark');
        ctx.fillStyle = colour; ctx.strokeStyle = colour;
        if (l.mode === 'FILL') {
          ctx.globalAlpha = l.key === 'resist' ? 0.32 : l.key === 'silk' ? 1 : 0.7;
          ctx.fill(path, 'evenodd');
        } else {
          ctx.globalAlpha = 0.85; ctx.lineWidth = beamMm; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
          ctx.stroke(path);
        }
        ctx.globalAlpha = 1;
      }
    };
    paint((k) => k === 'resist' || k === 'mask' || k === 'silk');
    if (!hidden.drill) {
      ctx.fillStyle = col('--canvas'); ctx.strokeStyle = col('--pcb-drill'); ctx.lineWidth = hair;
      for (const d of board.drills) {
        ctx.beginPath(); ctx.arc(d.x, d.y, Math.max(d.dia / 2, hair), 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
      }
      ctx.lineCap = 'round'; ctx.strokeStyle = col('--canvas');
      for (const s of board.slots) { ctx.lineWidth = s.dia; ctx.beginPath(); ctx.moveTo(s.a.x, s.a.y); ctx.lineTo(s.b.x, s.b.y); ctx.stroke(); }
    }
    // Marks last: they sit inside the holes and would be hidden otherwise.
    paint((k) => k === 'drill' || k === 'fiducial');
    if (!hidden.outline) { ctx.strokeStyle = col('--pcb-edge'); ctx.lineWidth = 1.2 * hair; ctx.stroke(paths.outline); }
    if (marker) {
      ctx.strokeStyle = col('--bad'); ctx.lineWidth = 2 * hair;
      ctx.beginPath(); ctx.arc(marker.at.x, marker.at.y, 12 * hair, 0, 2 * Math.PI); ctx.stroke();
    }
  }, [cam, paths, hidden, board, beamMm, marker, toScreen]);

  useEffect(() => { draw(); }, [draw, theme]);
  useEffect(() => {
    const c = ref.current; if (!c) return;
    const obs = new ResizeObserver(() => { if (!cam) fit(); else draw(); });
    obs.observe(c);
    return () => obs.disconnect();
  }, [cam, fit, draw]);

  const zoomAt = useCallback((factor: number, px?: number, py?: number) => {
    setCam((c) => {
      if (!c || !ref.current) return c;
      const r = ref.current.getBoundingClientRect();
      const x = px ?? r.width / 2, y = py ?? r.height / 2;
      const s = Math.min(400, Math.max(0.5, c.s * factor)), k = s / c.s;
      return { s, ox: x - (x - c.ox) * k, oy: y - (y - c.oy) * k };
    });
  }, []);
  useEffect(() => {
    const c = ref.current; if (!c) return;
    const h = (e: WheelEvent) => { e.preventDefault(); const r = c.getBoundingClientRect(); zoomAt(e.deltaY < 0 ? 1.2 : 1 / 1.2, e.clientX - r.left, e.clientY - r.top); };
    c.addEventListener('wheel', h, { passive: false });
    return () => c.removeEventListener('wheel', h);
  }, [zoomAt]);

  const drag = useRef<{ x: number; y: number } | null>(null);
  return <>
    <canvas ref={ref} data-testid="pcb-canvas" tabIndex={0} aria-label="Vorschau der Platine. Mausrad zoomt, Ziehen verschiebt, Tasten plus, minus und null."
      data-zoom={cam ? cam.s.toFixed(2) : ''}
      onPointerDown={(e) => { drag.current = { x: e.clientX, y: e.clientY }; e.currentTarget.setPointerCapture(e.pointerId); }}
      onPointerMove={(e) => { const d = drag.current; if (!d) return; const dx = e.clientX - d.x, dy = e.clientY - d.y; drag.current = { x: e.clientX, y: e.clientY }; setCam((c) => c && { ...c, ox: c.ox + dx, oy: c.oy + dy }); }}
      onPointerUp={() => { drag.current = null; }}
      onKeyDown={(e) => {
        if (e.key === '+' ) zoomAt(1.25); else if (e.key === '-') zoomAt(0.8); else if (e.key === '0') fit();
      }} />
    <div className="pcb-view-zoom">
      <Button size="sm" variant="ghost" iconOnly aria-label="Verkleinern" title="Verkleinern (−)" icon={<Minus size={14} />} onClick={() => zoomAt(0.8)} />
      <Button size="sm" variant="ghost" iconOnly aria-label="Vergrößern" title="Vergrößern (+)" icon={<Plus size={14} />} onClick={() => zoomAt(1.25)} />
      <Button size="sm" variant="ghost" iconOnly aria-label="Einpassen" title="Einpassen (0)" data-testid="pcb-fit" icon={<Maximize size={14} />} onClick={fit} />
    </div>
  </>;
}
