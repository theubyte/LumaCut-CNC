/** Port von ImageTools.kt. Grauwerte 0..255 (0 = schwarz = volle Leistung) in Uint8Array, Ausgabe gleich Kotlin. */
import type { ImageAdjust, ImageMode } from './model';

const clampI = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v);
export const isDefaultAdjust = (a: ImageAdjust | null | undefined) =>
  !a || (!(a.brightness ?? 0) && !(a.contrast ?? 0) && !(a.sharpen ?? 0) && !a.invert);

/** Unschärfemaske mit 3x3-Box; amount 0..1 (bis zum Doppelten des Details). */
export function sharpen(src: Uint8Array, w: number, h: number, amount: number): Uint8Array {
  const out = new Uint8Array(src.length);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let sum = 0, n = 0;
    for (let dy = -1; dy <= 1; dy++) {
      const yy = y + dy;
      if (yy < 0 || yy >= h) continue;
      for (let dx = -1; dx <= 1; dx++) {
        const xx = x + dx;
        if (xx >= 0 && xx < w) { sum += src[yy * w + xx]; n++; }
      }
    }
    const blur = sum / n, c = src[y * w + x];
    out[y * w + x] = clampI(Math.round(c + (c - blur) * amount * 2), 0, 255);
  }
  return out;
}

/** Schärfe, Kontrast, Helligkeit, Invertieren in dieser Reihenfolge. */
export function adjustGray(gray: Uint8Array, w: number, h: number, a: ImageAdjust | null | undefined): Uint8Array {
  if (!a || isDefaultAdjust(a)) return gray;
  const sharp = a.sharpen ?? 0;
  const v = sharp > 0 ? sharpen(gray, w, h, sharp / 100) : gray;
  const factor = (100 + clampI(a.contrast ?? 0, -100, 100)) / 100;
  const shift = clampI(a.brightness ?? 0, -100, 100) * 2.55;
  const lut = new Uint8Array(256);
  for (let g = 0; g < 256; g++) {
    const x = clampI((g - 128) * factor + 128 + shift, 0, 255);
    lut[g] = clampI(Math.round(a.invert ? 255 - x : x), 0, 255);
  }
  const out = new Uint8Array(v.length);
  for (let i = 0; i < v.length; i++) out[i] = lut[v[i]];
  return out;
}

interface Kernel { dx: Int8Array; dy: Int8Array; wt: Uint8Array; div: number }
const kernel = (t: number[][], div: number): Kernel => ({
  dx: Int8Array.from(t.map((r) => r[0])), dy: Int8Array.from(t.map((r) => r[1])), wt: Uint8Array.from(t.map((r) => r[2])), div });
const FLOYD = kernel([[1, 0, 7], [-1, 1, 3], [0, 1, 5], [1, 1, 1]], 16);
const JARVIS = kernel([[1, 0, 7], [2, 0, 5], [-2, 1, 3], [-1, 1, 5], [0, 1, 7], [1, 1, 5], [2, 1, 3], [-2, 2, 1], [-1, 2, 3], [0, 2, 5], [1, 2, 3], [2, 2, 1]], 48);
const STUCKI = kernel([[1, 0, 8], [2, 0, 4], [-2, 1, 2], [-1, 1, 4], [0, 1, 8], [1, 1, 4], [2, 1, 2], [-2, 2, 1], [-1, 2, 2], [0, 2, 4], [1, 2, 2], [2, 2, 1]], 42);

/** Fehlerverteilung in 32-Bit-Float wie Kotlin (FloatArray): jedes Zwischenergebnis wird gerundet. */
function diffuse(src: Uint8Array, w: number, h: number, k: Kernel): Uint8Array {
  const v = new Float32Array(src);
  const out = new Uint8Array(src.length);
  const n = k.dx.length, fround = Math.fround;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    const q = v[i] < 128 ? 0 : 255;
    out[i] = q;
    const err = fround(v[i] - q);
    for (let t = 0; t < n; t++) {
      const xx = x + k.dx[t], yy = y + k.dy[t];
      if (xx >= 0 && xx < w && yy < h) v[yy * w + xx] += fround(fround(err * k.wt[t]) / k.div);
    }
  }
  return out;
}

export function binarize(src: Uint8Array, w: number, h: number, mode: ImageMode): Uint8Array {
  switch (mode) {
    case 'THRESHOLD': { const out = new Uint8Array(src.length); for (let i = 0; i < src.length; i++) out[i] = src[i] < 128 ? 0 : 255; return out; }
    case 'DITHER': return diffuse(src, w, h, FLOYD);
    case 'DITHER_JARVIS': return diffuse(src, w, h, JARVIS);
    case 'DITHER_STUCKI': return diffuse(src, w, h, STUCKI);
    default: return src;
  }
}

/** Nächster-Nachbar-Abtastung wie im Raster-Teil von MarlinWriter.kt. */
export function sampleGray(gray: Uint8Array, width: number, height: number, cols: number, rows: number): Uint8Array {
  const out = new Uint8Array(rows * cols);
  const px = new Int32Array(cols);
  for (let c = 0; c < cols; c++) px[c] = Math.min(width - 1, Math.trunc((c + 0.5) * width / cols));
  for (let r = 0; r < rows; r++) {
    const py = Math.min(height - 1, Math.trunc((r + 0.5) * height / rows)) * width, o = r * cols;
    for (let c = 0; c < cols; c++) out[o + c] = gray[py + px[c]];
  }
  return out;
}
