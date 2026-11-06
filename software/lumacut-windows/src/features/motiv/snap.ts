import type { Box, Pt } from '@/core/model';

/** Snapping is pure: lines to catch come from the other elements and the bed. */
export interface SnapTargets { xs: number[]; ys: number[]; points: Pt[] }
export interface SnapOptions { grid: number | null; tolMm: number }
export interface SnapHit { dx: number; dy: number; guideX: number | null; guideY: number | null }

export function targetsOf(boxes: Box[], bedW: number, bedH: number, withObjects: boolean): SnapTargets {
  const xs = [0, bedW / 2, bedW], ys = [0, bedH / 2, bedH], points: Pt[] = [];
  if (withObjects) for (const b of boxes) {
    const cx = (b.minX + b.maxX) / 2, cy = (b.minY + b.maxY) / 2;
    xs.push(b.minX, cx, b.maxX); ys.push(b.minY, cy, b.maxY);
    points.push({ x: b.minX, y: b.minY }, { x: b.maxX, y: b.minY }, { x: b.maxX, y: b.maxY }, { x: b.minX, y: b.maxY }, { x: cx, y: cy });
  }
  return { xs, ys, points };
}

/** Best correction of `probes` onto `lines`; objects beat the grid. */
function axis(probes: number[], lines: number[], gridProbes: number[], opt: SnapOptions): { d: number; guide: number | null } {
  let best = Infinity, d = 0, guide: number | null = null;
  for (const p of probes) for (const l of lines) {
    const q = Math.abs(l - p);
    if (q < best && q <= opt.tolMm) { best = q; d = l - p; guide = l; }
  }
  if (guide != null || !opt.grid) return { d, guide };
  for (const p of gridProbes) {
    const l = Math.round(p / opt.grid) * opt.grid, q = Math.abs(l - p);
    if (q < best && q <= Math.max(opt.tolMm, opt.grid / 2)) { best = q; d = l - p; }
  }
  return { d, guide: null };
}

export function snapBox(b: Box, t: SnapTargets, opt: SnapOptions): SnapHit {
  const x = axis([b.minX, (b.minX + b.maxX) / 2, b.maxX], t.xs, [b.minX, b.maxX], opt);
  const y = axis([b.minY, (b.minY + b.maxY) / 2, b.maxY], t.ys, [b.minY, b.maxY], opt);
  return { dx: x.d, dy: y.d, guideX: x.guide, guideY: y.guide };
}

export function snapPoint(p: Pt, t: SnapTargets, opt: SnapOptions): SnapHit {
  const x = axis([p.x], t.xs, [p.x], opt), y = axis([p.y], t.ys, [p.y], opt);
  return { dx: x.d, dy: y.d, guideX: x.guide, guideY: y.guide };
}

/** Direction from `a` to `b` limited to steps of 45 degrees, length kept. */
export function constrain45(a: Pt, b: Pt): Pt {
  const dx = b.x - a.x, dy = b.y - a.y, l = Math.hypot(dx, dy), s = Math.PI / 4, ang = Math.round(Math.atan2(dy, dx) / s) * s;
  return { x: a.x + Math.cos(ang) * l, y: a.y + Math.sin(ang) * l };
}
