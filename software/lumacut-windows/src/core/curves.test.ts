import { describe, expect, it } from 'vitest';
import { curvesFromPaths, deleteNode, ellipseCurve, flattenCurve, insertNode, mapCurves, moveHandle, moveNode, nearestOnPath, rectCurve, toggleSmooth } from './curves';
import { boundsOf, isClosed } from './model';

describe('curves', () => {
  it('closed rectangle flattens to a closed polyline', () => {
    const p = flattenCurve(rectCurve(10, 5));
    expect(p).toHaveLength(5);
    expect(isClosed(p)).toBe(true);
  });
  it('ellipse stays inside its box and hits the extremes', () => {
    const b = boundsOf([flattenCurve(ellipseCurve(40, 20))])!;
    expect(b.minX).toBeCloseTo(0, 2); expect(b.maxX).toBeCloseTo(40, 2);
    expect(b.minY).toBeCloseTo(0, 2); expect(b.maxY).toBeCloseTo(20, 2);
  });
  it('flatness: points on a circle stay within tolerance', () => {
    const p = flattenCurve(ellipseCurve(100, 100), 0.02);
    for (const q of p) expect(Math.abs(Math.hypot(q.x - 50, q.y - 50) - 50)).toBeLessThan(0.05);
  });
  it('paths round trip keeps closed flag without a duplicate node', () => {
    const [c] = curvesFromPaths([[{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 0 }]]);
    expect(c.closed).toBe(true); expect(c.nodes).toHaveLength(3);
    expect(flattenCurve(c)).toHaveLength(4);
  });
  it('moving a node takes its handles along', () => {
    const c = moveNode(ellipseCurve(10, 10), 0, { x: 6, y: 1 });
    expect(c.nodes[0].hx2! - c.nodes[0].x).toBeCloseTo(ellipseCurve(10, 10).nodes[0].hx2! - 5);
    expect(c.nodes[0].y).toBe(1);
  });
  it('smooth handle mirrors direction, keeps own length', () => {
    const n = moveHandle(ellipseCurve(10, 10), 0, 'out', { x: 5, y: 3 }).nodes[0];
    expect(n.hx1).toBeCloseTo(5); expect(n.hy1).toBeLessThan(0);
  });
  it('insert keeps the shape of a curved span', () => {
    const e = ellipseCurve(100, 60);
    const before = flattenCurve(e, 0.005);
    const after = flattenCurve(insertNode(e, 1, 0.3), 0.005);
    expect(insertNode(e, 1, 0.3).nodes).toHaveLength(5);
    expect(before.length).toBeGreaterThan(8);
    for (const q of after) expect(Math.abs(((q.x - 50) / 50) ** 2 + ((q.y - 30) / 30) ** 2 - 1)).toBeLessThan(0.01);
  });
  it('nearest finds the span', () => {
    const hit = nearestOnPath(rectCurve(10, 10), { x: 11, y: 5 })!;
    expect(hit.span).toBe(1); expect(hit.dist).toBeCloseTo(1); expect(hit.t).toBeCloseTo(0.5);
  });
  it('delete respects the minimum', () => {
    expect(deleteNode({ closed: true, nodes: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }] }, 0)).toBeNull();
    expect(deleteNode(rectCurve(1, 1), 0)!.nodes).toHaveLength(3);
  });
  it('toggle makes a corner smooth and back', () => {
    const s = toggleSmooth(rectCurve(10, 10), 1);
    expect(s.nodes[1].smooth).toBe(true);
    expect(toggleSmooth(s, 1).nodes[1].hx1).toBeUndefined();
  });
  it('map applies to handles too', () => {
    const c = mapCurves([ellipseCurve(10, 10)], (p) => ({ x: p.x + 1, y: p.y }))[0];
    expect(c.nodes[0].x).toBe(6); expect(c.nodes[0].hx2).toBeCloseTo(ellipseCurve(10, 10).nodes[0].hx2! + 1);
  });
});
