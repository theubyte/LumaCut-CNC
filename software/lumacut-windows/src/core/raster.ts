/** Bilder: Base64, Graustufen, Raster aus ImageData, Vorschau mit Modus und Anpassungen. */
import { adjustGray, binarize, sampleGray } from './imageTools';
import type { ImageAdjust, ImageMode, Raster } from './model';

const A = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
const LUT = new Int16Array(256).fill(-1);
for (let i = 0; i < 64; i++) LUT[A.charCodeAt(i)] = i;

export function decodeBase64(b64: string): Uint8Array {
  let n = b64.length;
  while (n > 0 && b64.charCodeAt(n - 1) === 61) n--;
  const out = new Uint8Array(Math.floor(n * 3 / 4));
  let o = 0, buf = 0, bits = 0;
  for (let i = 0; i < n; i++) {
    const v = LUT[b64.charCodeAt(i) & 255];
    if (v < 0) throw new Error('Ungültige Bilddaten');
    buf = (buf << 6) | v; bits += 6;
    if (bits >= 8) { bits -= 8; out[o++] = (buf >> bits) & 255; buf &= (1 << bits) - 1; }
  }
  return out;
}
export function encodeBase64(bytes: Uint8Array): string {
  const parts: string[] = [];
  const CHUNK = 3 * 8192;
  for (let s = 0; s < bytes.length; s += CHUNK) {
    const e = Math.min(bytes.length, s + CHUNK);
    let str = '';
    for (let i = s; i < e; i += 3) {
      const a = bytes[i], b = i + 1 < e ? bytes[i + 1] : 0, c = i + 2 < e ? bytes[i + 2] : 0;
      str += A[a >> 2] + A[((a & 3) << 4) | (b >> 4)] + (i + 1 < e ? A[((b & 15) << 2) | (c >> 6)] : '=') + (i + 2 < e ? A[c & 63] : '=');
    }
    parts.push(str);
  }
  return parts.join('');
}

export function rasterOf(width: number, height: number, gray: Uint8Array): Raster {
  if (!(width > 0 && height > 0) || gray.length !== width * height) throw new Error('Ungültige Bilddaten');
  return { width, height, grayBase64: encodeBase64(gray) };
}

let lastB64 = '', lastGray: Uint8Array | null = null;
/** Dekodiert das Raster; das letzte Ergebnis bleibt gemerkt, weil Vorschau und Auftrag es oft wiederholt brauchen. Nicht verändern. */
export function grayOf(r: Raster): Uint8Array {
  if (lastGray && r.grayBase64 === lastB64) return lastGray;
  lastGray = decodeBase64(r.grayBase64);
  lastB64 = r.grayBase64;
  return lastGray;
}

/** Helligkeit wie Importers.toRaster auf Android: Durchsichtiges zählt als weiß (kein Laser). */
export function grayFromRgba(rgba: Uint8ClampedArray | Uint8Array, w: number, h: number): Uint8Array {
  const out = new Uint8Array(w * h);
  for (let i = 0, p = 0; i < out.length; i++, p += 4) {
    const a = rgba[p + 3] / 255, l = 0.2126 * rgba[p] + 0.7152 * rgba[p + 1] + 0.0722 * rgba[p + 2];
    out[i] = Math.round(l * a + 255 * (1 - a));
  }
  return out;
}
export const rasterFromImageData = (img: { data: Uint8ClampedArray; width: number; height: number }): Raster =>
  rasterOf(img.width, img.height, grayFromRgba(img.data, img.width, img.height));

export interface PreviewOptions {
  mode?: ImageMode; adjust?: ImageAdjust;
  /** Raster so abtasten wie der Auftrag (Spalten/Zeilen = Maß / Zeilenabstand). Ohne: ganzes Bild, höchstens maxPixels. */
  cols?: number; rows?: number; maxPixels?: number;
  /** Weiß durchsichtig, Dunkles als Deckkraft: für die Vorschau auf der Arbeitsfläche. */
  transparentWhite?: boolean;
}
/** Vorschau als RGBA, ohne Browser-Abhängigkeit. */
export function previewRgba(r: Raster, opts: PreviewOptions = {}): { data: Uint8ClampedArray<ArrayBuffer>; width: number; height: number } {
  let cols = opts.cols ?? r.width, rows = opts.rows ?? r.height;
  const cap = opts.maxPixels ?? 4_000_000;
  if (cols * rows > cap) { const k = Math.sqrt(cap / (cols * rows)); cols = Math.max(1, Math.floor(cols * k)); rows = Math.max(1, Math.floor(rows * k)); }
  const gray = grayOf(r);
  const sampled = cols === r.width && rows === r.height ? gray : sampleGray(gray, r.width, r.height, cols, rows);
  const levels = binarize(adjustGray(sampled, cols, rows, opts.adjust), cols, rows, opts.mode ?? 'GRAYSCALE');
  const data = new Uint8ClampedArray(new ArrayBuffer(cols * rows * 4));
  for (let i = 0, p = 0; i < levels.length; i++, p += 4) {
    const g = levels[i];
    if (opts.transparentWhite) { data[p + 3] = 255 - g; }
    else { data[p] = g; data[p + 1] = g; data[p + 2] = g; data[p + 3] = 255; }
  }
  return { data, width: cols, height: rows };
}
export function previewImageData(r: Raster, opts?: PreviewOptions): ImageData {
  const p = previewRgba(r, opts);
  return new ImageData(p.data, p.width, p.height);
}
/** Zeichnet die Vorschau in ein Canvas; dessen Größe wird auf das Bild gesetzt (Skalierung per CSS). */
export function drawRasterPreview(canvas: HTMLCanvasElement | OffscreenCanvas, r: Raster, opts?: PreviewOptions): void {
  const img = previewImageData(r, opts);
  canvas.width = img.width; canvas.height = img.height;
  const ctx = canvas.getContext('2d') as CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null;
  ctx?.putImageData(img, 0, 0);
}
