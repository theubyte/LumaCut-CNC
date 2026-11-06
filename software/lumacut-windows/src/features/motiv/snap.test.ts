import { describe, expect, it } from 'vitest';
import { constrain45, snapBox, snapPoint, targetsOf } from './snap';

const other = { minX: 100, minY: 50, maxX: 140, maxY: 90 };
const t = targetsOf([other], 370, 360, true);

describe('snap', () => {
  it('edge catches an object edge, with a guide', () => {
    const h = snapBox({ minX: 141, minY: 200, maxX: 161, maxY: 220 }, t, { grid: null, tolMm: 2 });
    expect(h.dx).toBeCloseTo(-1); expect(h.guideX).toBe(140); expect(h.guideY).toBeNull();
  });
  it('centre catches a centre', () => {
    const h = snapBox({ minX: 111, minY: 200, maxX: 131, maxY: 220 }, t, { grid: null, tolMm: 2 });
    expect(h.dx).toBeCloseTo(-1); expect(h.guideX).toBe(120);
  });
  it('objects beat the grid', () => {
    expect(snapPoint({ x: 100.4, y: 300.3 }, t, { grid: 1, tolMm: 1 }).guideX).toBe(100);
  });
  it('grid works without objects and leaves no guide', () => {
    const h = snapPoint({ x: 33.4, y: 77.8 }, { xs: [], ys: [], points: [] }, { grid: 1, tolMm: 0.2 });
    expect(33.4 + h.dx).toBeCloseTo(33); expect(77.8 + h.dy).toBeCloseTo(78); expect(h.guideX).toBeNull();
  });
  it('nothing in reach, nothing moves', () => {
    expect(snapPoint({ x: 33.4, y: 77.8 }, t, { grid: null, tolMm: 0.2 }).dx).toBe(0);
  });
  it('45 degree steps keep the length', () => {
    const p = constrain45({ x: 0, y: 0 }, { x: 10, y: 1 });
    expect(p.y).toBeCloseTo(0); expect(p.x).toBeCloseTo(Math.hypot(10, 1));
  });
});
