/**
 * Thin clipper-lib wrapper for the PCB code. Takes and returns millimetres. Output polygons are
 * closed (first point = last point), outers counter-clockwise, holes clockwise, so even-odd fill
 * and shoelace area both work directly.
 */
// @ts-ignore clipper-lib ships no types; the small surface used here is typed below.
import ClipperRaw from 'clipper-lib';
import type { Poly } from '@/core/model';

interface IntPt { X: number; Y: number }
type IntPath = IntPt[];
interface ClipperLibApi {
  Clipper: {
    new (): { AddPaths(p: IntPath[], t: number, closed: boolean): void; Execute(op: number, sol: unknown, a: number, b: number): boolean };
    OpenPathsFromPolyTree(t: unknown): IntPath[];
  };
  ClipperOffset: { new (miter: number, arc: number): { AddPaths(p: IntPath[], j: number, e: number): void; Execute(sol: IntPath[], d: number): void } };
  PolyTree: { new (): unknown };
  PolyType: { ptSubject: number; ptClip: number };
  ClipType: { ctIntersection: number; ctUnion: number; ctDifference: number };
  PolyFillType: { pftEvenOdd: number; pftNonZero: number };
  JoinType: { jtRound: number; jtMiter: number };
  EndType: { etClosedPolygon: number; etOpenRound: number };
}
const C = ClipperRaw as unknown as ClipperLibApi;

/** 0.1 µm. 600 mm stays below clipper's fast integer range. */
const SCALE = 1e4;
/** Curves stay within 2 µm of the true arc. */
const ARC_TOL_MM = 0.002;

const toInt = (polys: Poly[]): IntPath[] => polys.map((p) => p.map((q) => ({ X: Math.round(q.x * SCALE), Y: Math.round(q.y * SCALE) })));
const closeRing = (p: Poly): Poly => {
  if (p.length && (p[0].x !== p[p.length - 1].x || p[0].y !== p[p.length - 1].y)) p.push({ ...p[0] });
  return p;
};
const fromInt = (paths: IntPath[]): Poly[] => paths.filter((p) => p.length >= 3).map((p) => closeRing(p.map((q) => ({ x: q.X / SCALE, y: q.Y / SCALE }))));

function run(op: number, subject: Poly[], clip: Poly[], fill: number): Poly[] {
  const c = new C.Clipper();
  c.AddPaths(toInt(subject), C.PolyType.ptSubject, true);
  if (clip.length) c.AddPaths(toInt(clip), C.PolyType.ptClip, true);
  const sol: IntPath[] = [];
  c.Execute(op, sol, fill, fill);
  return fromInt(sol);
}
/** Union with winding rule: expects outers CCW and holes CW (or one self-consistent keyhole). */
export const unionPolys = (polys: Poly[]): Poly[] => polys.length ? run(C.ClipType.ctUnion, polys, [], C.PolyFillType.pftNonZero) : [];
/** Cleans one contour, or a set read as even-odd. Holes come back with the right orientation. */
export const cleanEvenOdd = (polys: Poly[]): Poly[] => polys.length ? run(C.ClipType.ctUnion, polys, [], C.PolyFillType.pftEvenOdd) : [];
export const addPolys = (a: Poly[], b: Poly[]): Poly[] => unionPolys([...a, ...b]);
export const subtractPolys = (a: Poly[], b: Poly[]): Poly[] => !a.length ? [] : !b.length ? a : run(C.ClipType.ctDifference, a, b, C.PolyFillType.pftNonZero);
export const intersectPolys = (a: Poly[], b: Poly[]): Poly[] => !a.length || !b.length ? [] : run(C.ClipType.ctIntersection, a, b, C.PolyFillType.pftNonZero);

/** Grow (delta > 0) or shrink closed polygons with round corners. */
export function offsetPolys(polys: Poly[], deltaMm: number): Poly[] {
  if (!polys.length) return [];
  if (deltaMm === 0) return polys;
  const co = new C.ClipperOffset(2, ARC_TOL_MM * SCALE);
  co.AddPaths(toInt(polys), C.JoinType.jtRound, C.EndType.etClosedPolygon);
  const sol: IntPath[] = [];
  co.Execute(sol, deltaMm * SCALE);
  return fromInt(sol);
}
/** The area covered by a round pen of this diameter along an open polyline. */
export function strokePolyline(line: Poly, diameterMm: number): Poly[] {
  const co = new C.ClipperOffset(2, ARC_TOL_MM * SCALE);
  co.AddPaths(toInt([line]), C.JoinType.jtRound, C.EndType.etOpenRound);
  const sol: IntPath[] = [];
  co.Execute(sol, (diameterMm / 2) * SCALE);
  return fromInt(sol);
}
/** Cuts lines to the inside of `region`. Result: open polylines. */
export function clipLines(lines: Poly[], region: Poly[]): Poly[] {
  if (!lines.length || !region.length) return [];
  const c = new C.Clipper();
  c.AddPaths(toInt(lines), C.PolyType.ptSubject, false);
  c.AddPaths(toInt(region), C.PolyType.ptClip, true);
  const tree = new C.PolyTree();
  c.Execute(C.ClipType.ctIntersection, tree, C.PolyFillType.pftNonZero, C.PolyFillType.pftNonZero);
  return C.Clipper.OpenPathsFromPolyTree(tree).filter((p) => p.length >= 2).map((p) => p.map((q) => ({ x: q.X / SCALE, y: q.Y / SCALE })));
}

/** Signed shoelace area. Works for closed and unclosed rings. */
export function ringArea(p: Poly): number {
  let a = 0;
  for (let i = 0, n = p.length; i < n; i++) { const u = p[i], v = p[(i + 1) % n]; a += u.x * v.y - v.x * u.y; }
  return a / 2;
}
/** Net area in mm²: holes count negative. */
export const polysArea = (polys: Poly[]) => polys.reduce((s, p) => s + ringArea(p), 0);

/** Even-odd point test over all rings. */
export function pointInPolys(x: number, y: number, polys: Poly[]): boolean {
  let inside = false;
  for (const p of polys) for (let i = 0, j = p.length - 1; i < p.length; j = i++) {
    const a = p[i], b = p[j];
    if ((a.y > y) !== (b.y > y) && x < a.x + ((y - a.y) * (b.x - a.x)) / (b.y - a.y)) inside = !inside;
  }
  return inside;
}

/** Regular polygon with enough corners for `tolMm` chord error, CCW. Not closed. */
export function circle(cx: number, cy: number, r: number, tolMm = 0.002): Poly {
  if (r <= 0) return [];
  // A multiple of 4 puts corners exactly on the extremes, so the bounds stay true.
  const n = 4 * Math.max(2, Math.min(180, Math.ceil(Math.PI / Math.acos(1 - Math.min(tolMm, r) / r) / 4)));
  const out: Poly = [];
  for (let i = 0; i < n; i++) { const a = (i / n) * 2 * Math.PI; out.push({ x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) }); }
  return out;
}
