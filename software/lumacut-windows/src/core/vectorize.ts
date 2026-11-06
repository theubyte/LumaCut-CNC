/**
 * Bild zu Vektoren: Schwellwert, Rissverfolgung entlang der Pixelkanten, Douglas-Peucker.
 * Außenkonturen und Löcher liegen als eigene geschlossene Linien vor (even-odd), Außenkontur vor Loch.
 * An Diagonalen bleiben Pixel getrennt (4-Nachbarschaft), so kreuzt sich nie eine Kontur.
 */
import { polyArea } from './contour';
import { simplify } from './geometry';
import type { Poly, Pt, Raster } from './model';
import { grayOf } from './raster';

export interface VectorizeOptions {
  /** Pixel dunkler als dieser Wert (1..255) sind Motiv. Standard 128. */
  threshold?: number;
  /** Helles statt Dunkles ist Motiv. */
  invert?: boolean;
  /** Größe des Ergebnisses; ohne Angabe 1 Pixel = 1 mm. */
  widthMm?: number; heightMm?: number;
  /** Vereinfachung; Standard 0,75 Pixel (nimmt die Pixeltreppen heraus). */
  toleranceMm?: number;
  /** Kleinere Flecken und Löcher entfallen. Standard 4 Pixel. */
  minAreaMm2?: number;
  /** Nur Außenkonturen. */
  outerOnly?: boolean;
  /** Ecken leicht abrunden (ein Chaikin-Durchgang). */
  smooth?: boolean;
}

const RIGHT = 1, DOWN = 2, LEFT = 4, UP = 8;
const rightOf = (d: number) => (d === RIGHT ? DOWN : d === DOWN ? LEFT : d === LEFT ? UP : RIGHT);
const leftOf = (d: number) => (d === RIGHT ? UP : d === UP ? LEFT : d === LEFT ? DOWN : RIGHT);

/** Geschlossene Schleifen in Pixelkoordinaten, nur Eckpunkte. Das Motiv liegt in Fahrtrichtung rechts: außen positive Fläche, Loch negative. */
function traceLoops(ink: Uint8Array, w: number, h: number): number[][] {
  const vw = w + 1, orig = new Uint8Array(vw * (h + 1));
  const at = (x: number, y: number) => x >= 0 && y >= 0 && x < w && y < h && ink[y * w + x] === 1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    if (!ink[y * w + x]) continue;
    if (!at(x, y - 1)) orig[y * vw + x] |= RIGHT;
    if (!at(x + 1, y)) orig[y * vw + x + 1] |= DOWN;
    if (!at(x, y + 1)) orig[(y + 1) * vw + x + 1] |= LEFT;
    if (!at(x - 1, y)) orig[(y + 1) * vw + x] |= UP;
  }
  const open = orig.slice();
  const loops: number[][] = [];
  for (let start = 0; start < open.length; start++) {
    while (open[start]) {
      const sx = start % vw, sy = Math.trunc(start / vw), startDir = open[start] & -open[start];
      const pts: number[] = [];
      let x = sx, y = sy, dir = startDir, prev = 0;
      for (;;) {
        if (dir !== prev) pts.push(x, y);
        open[y * vw + x] &= ~dir;
        if (dir === RIGHT) x++; else if (dir === DOWN) y++; else if (dir === LEFT) x--; else y--;
        prev = dir;
        // Am Sattelpunkt rechts abbiegen: Diagonale Pixel bleiben getrennt.
        const f = orig[y * vw + x], right = rightOf(prev), left = leftOf(prev);
        dir = f & right ? right : f & prev ? prev : left;
        if (x === sx && y === sy && dir === startDir) break;
      }
      if (pts.length >= 6) loops.push(pts);
    }
  }
  return loops;
}

/** Douglas-Peucker für geschlossene Ringe: am fernsten Punkt teilen, damit der Startpunkt keine Sonderrolle hat. */
function simplifyRing(ring: Pt[], tol: number): Pt[] {
  const n = ring.length;
  if (n < 4) return ring;
  let far = 0, best = -1;
  for (let i = 1; i < n; i++) {
    const d = (ring[i].x - ring[0].x) ** 2 + (ring[i].y - ring[0].y) ** 2;
    if (d > best) { best = d; far = i; }
  }
  const a = simplify(ring.slice(0, far + 1), tol);
  const b = simplify([...ring.slice(far), ring[0]], tol);
  return [...a.slice(0, -1), ...b.slice(0, -1)];
}

function chaikin(ring: Pt[]): Pt[] {
  const out: Pt[] = [];
  for (let i = 0; i < ring.length; i++) {
    const p = ring[i], q = ring[(i + 1) % ring.length];
    out.push({ x: 0.75 * p.x + 0.25 * q.x, y: 0.75 * p.y + 0.25 * q.y }, { x: 0.25 * p.x + 0.75 * q.x, y: 0.25 * p.y + 0.75 * q.y });
  }
  return out;
}

export function vectorize(gray: Uint8Array, w: number, h: number, opts: VectorizeOptions = {}): Poly[] {
  if (gray.length !== w * h || !(w > 0 && h > 0)) throw new Error('Ungültige Bilddaten');
  const threshold = opts.threshold ?? 128;
  const ink = new Uint8Array(w * h);
  for (let i = 0; i < ink.length; i++) ink[i] = (opts.invert ? gray[i] >= threshold : gray[i] < threshold) ? 1 : 0;
  const sx = (opts.widthMm ?? w) / w, sy = (opts.heightMm ?? h) / h;
  const tol = opts.toleranceMm ?? 0.75 * Math.min(sx, sy);
  const minArea = opts.minAreaMm2 ?? 4 * sx * sy;
  const found: { poly: Poly; area: number }[] = [];
  for (const loop of traceLoops(ink, w, h)) {
    const ring: Pt[] = [];
    for (let i = 0; i < loop.length; i += 2) ring.push({ x: loop[i] * sx, y: loop[i + 1] * sy });
    let s = simplifyRing(ring, tol);
    if (s.length < 3) s = ring;
    if (opts.smooth) s = chaikin(s);
    const closed: Poly = [...s, { ...s[0] }];
    const area = polyArea(closed);
    if (Math.abs(area) < minArea) continue;
    if (opts.outerOnly && area < 0) continue;
    found.push({ poly: closed, area });
  }
  // Größte zuerst: jede Außenkontur steht vor den Löchern, die in ihr liegen.
  found.sort((a, b) => Math.abs(b.area) - Math.abs(a.area));
  return found.map((f) => f.poly);
}

export const vectorizeRaster = (r: Raster, opts: VectorizeOptions = {}): Poly[] => vectorize(grayOf(r), r.width, r.height, opts);
