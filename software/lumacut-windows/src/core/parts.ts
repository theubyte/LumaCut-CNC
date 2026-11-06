/** Port von Parts.kt und Element.splitParts aus Design.kt. */
import { boxContains, polyClosed } from './geometry';
import { boundsOf, isImage, newId, worldPaths, type Element, type Poly, type Pt } from './model';

export interface Split { parts: Poly[][]; tooMany: boolean }
const MAX_PARTS = 500, MAX_CLOSED = 2000;

function signedArea(p: Poly): number {
  let s = 0;
  for (let i = 1; i < p.length; i++) s += p[i - 1].x * p[i].y - p[i].x * p[i - 1].y;
  return s / 2;
}
function contains(poly: Poly, p: Pt): boolean {
  let c = false;
  for (let i = 1; i < poly.length; i++) {
    const a = poly[i - 1], b = poly[i];
    if ((a.y > p.y) !== (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x) c = !c;
  }
  return c;
}
function inside(inner: Poly, outer: Poly): boolean {
  const step = Math.max(1, Math.trunc(inner.length / 8));
  let n = 0, hit = 0;
  for (let i = 0; i < inner.length; i += step) { n++; if (contains(outer, inner[i])) hit++; }
  return hit * 2 > n;
}

export const PartSplitter = {
  MAX_PARTS,
  /** Jede äußere geschlossene Kontur mit den Löchern darin ist ein Teil, jeder offene Pfad auch. Ein O bleibt ganz. */
  split(polys: Poly[]): Split {
    const usable = polys.filter((p) => p.length >= 2);
    const isC = usable.map((p) => p.length >= 4 && polyClosed(p));
    const closed = usable.filter((_, i) => isC[i]);
    if (closed.length > MAX_CLOSED) return { parts: [usable], tooMany: true };
    const boxes = closed.map((p) => boundsOf([p])!);
    const area = closed.map((p) => Math.abs(signedArea(p)));
    const containers = closed.map((_, i) => {
      const out: number[] = [];
      for (let j = 0; j < closed.length; j++) {
        if (j !== i && area[j] > area[i] && boxContains(boxes[j], boxes[i].minX, boxes[i].minY) && boxContains(boxes[j], boxes[i].maxX, boxes[i].maxY) && inside(closed[i], closed[j])) out.push(j);
      }
      return out;
    });
    const depth = containers.map((c) => c.length);
    const holesOf = new Map<number, number[]>();
    closed.forEach((_, i) => {
      if (depth[i] % 2 !== 1 || containers[i].length === 0) return;
      let parent = containers[i][0];
      for (const c of containers[i]) if (depth[c] > depth[parent]) parent = c;
      const l = holesOf.get(parent);
      if (l) l.push(i); else holesOf.set(parent, [i]);
    });
    const parts: Poly[][] = [];
    let ci = 0;
    usable.forEach((poly, k) => {
      if (isC[k]) {
        const i = ci++;
        if (depth[i] % 2 === 0) parts.push([poly, ...(holesOf.get(i) ?? []).map((h) => closed[h])]);
      } else parts.push([poly]);
    });
    if (parts.length > MAX_PARTS) return { parts: [usable], tooMany: true };
    return { parts, tooMany: false };
  },
};

/** Das Element als kleinere Teile, an Ort und Stelle. Text und Bilder bleiben ganz. Ergebnis 1 = nichts zu teilen. */
export function splitParts(e: Element): Element[] {
  if (isImage(e) || e.text != null || e.paths.length < 2) return [e];
  const world = worldPaths(e);
  const split = PartSplitter.split(world);
  const parts = split.tooMany || split.parts.length < 2 ? world.map((p) => [p]) : split.parts;
  const out: Element[] = [];
  for (const part of parts) {
    const box = boundsOf(part);
    if (!box) continue;
    const { curves: _curves, ...rest } = e;
    void _curves;
    out.push({ ...rest, id: newId(), transform: { x: box.minX, y: box.minY, scaleX: 1, scaleY: 1, rotation: 0 },
      paths: part.map((poly) => poly.map((p) => ({ x: p.x - box.minX, y: p.y - box.minY }))) });
  }
  return out;
}
