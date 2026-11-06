/**
 * Exakte boolesche Operationen und Offset mit clipper-lib. Eingaben sind geschlossene Polygone (even-odd:
 * ein Loch ist einfach ein weiterer Ring). Ergebnis: geschlossene Polygone mit wiederholtem ersten Punkt,
 * jede Außenkontur direkt vor ihren Löchern.
 */
import ClipperLib from 'clipper-lib';
import type { Poly } from './model';

export type BooleanOp = 'union' | 'intersect' | 'subtract' | 'xor';
export type JoinKind = 'round' | 'miter' | 'square';

/** 1 Einheit = 0,1 µm: weit genauer als der Laser, und die Arbeitsfläche passt locker in den Ganzzahlbereich. */
const SCALE = 10000;
const ARC_TOLERANCE_MM = 0.01;
const CLEAN_MM = 0.0005;
const OPS: Record<BooleanOp, unknown> = {
  union: ClipperLib.ClipType.ctUnion, intersect: ClipperLib.ClipType.ctIntersection,
  subtract: ClipperLib.ClipType.ctDifference, xor: ClipperLib.ClipType.ctXor,
};
const JOINS: Record<JoinKind, unknown> = {
  round: ClipperLib.JoinType.jtRound, miter: ClipperLib.JoinType.jtMiter, square: ClipperLib.JoinType.jtSquare,
};
type IntPath = { X: number; Y: number }[];

function toPaths(polys: Poly[]): IntPath[] {
  const out: IntPath[] = [];
  for (const poly of polys) {
    const path: IntPath = [];
    for (const p of poly) {
      const X = Math.round(p.x * SCALE), Y = Math.round(p.y * SCALE), q = path[path.length - 1];
      if (!q || q.X !== X || q.Y !== Y) path.push({ X, Y });
    }
    if (path.length > 1 && path[0].X === path[path.length - 1].X && path[0].Y === path[path.length - 1].Y) path.pop();
    if (path.length >= 3) out.push(path);
  }
  return out;
}
function fromTree(tree: unknown): Poly[] {
  const paths: IntPath[] = ClipperLib.Clipper.CleanPolygons(ClipperLib.Clipper.PolyTreeToPaths(tree), CLEAN_MM * SCALE);
  const out: Poly[] = [];
  for (const path of paths) {
    if (path.length < 3) continue;
    const poly: Poly = path.map((p) => ({ x: p.X / SCALE, y: p.Y / SCALE }));
    poly.push({ ...poly[0] });
    out.push(poly);
  }
  return out;
}
const EVEN_ODD = ClipperLib.PolyFillType.pftEvenOdd;

function run(op: BooleanOp, subject: IntPath[], clip: IntPath[]): unknown {
  const c = new ClipperLib.Clipper();
  c.AddPaths(subject, ClipperLib.PolyType.ptSubject, true);
  if (clip.length) c.AddPaths(clip, ClipperLib.PolyType.ptClip, true);
  const tree = new ClipperLib.PolyTree();
  c.Execute(OPS[op], tree, EVEN_ODD, EVEN_ODD);
  return tree;
}

/** Subjekt und Clip als je eine Form (even-odd in sich). */
export function booleanOp(op: BooleanOp, subject: Poly[], clip: Poly[]): Poly[] {
  const s = toPaths(subject), c = toPaths(clip);
  if (s.length === 0 && (op === 'intersect' || op === 'subtract')) return [];
  return fromTree(run(op, s, c));
}

/** Mehrere Formen: Vereinigen alle, Abziehen alle anderen von der ersten, Schneiden und Exklusiv der Reihe nach. */
export function booleanShapes(op: BooleanOp, shapes: Poly[][]): Poly[] {
  const list = shapes.filter((s) => s.length > 0);
  if (list.length === 0) return [];
  let acc = fromTree(run('union', toPaths(list[0]), []));
  if (op === 'subtract') return booleanOp('subtract', acc, booleanShapes('union', list.slice(1)));
  for (let i = 1; i < list.length; i++) acc = booleanOp(op, acc, list[i]);
  return acc;
}

/** Positiv wächst die Fläche, negativ schrumpft sie; Löcher verhalten sich umgekehrt. Offene Pfade werden ignoriert. */
export function offsetPolys(polys: Poly[], deltaMm: number, join: JoinKind = 'round'): Poly[] {
  const paths = toPaths(polys);
  if (paths.length === 0) return [];
  const normal: IntPath[] = ClipperLib.Clipper.PolyTreeToPaths(run('union', paths, []));
  const co = new ClipperLib.ClipperOffset(2, ARC_TOLERANCE_MM * SCALE);
  co.AddPaths(normal, JOINS[join], ClipperLib.EndType.etClosedPolygon);
  const tree = new ClipperLib.PolyTree();
  co.Execute(tree, deltaMm * SCALE);
  return fromTree(tree);
}
