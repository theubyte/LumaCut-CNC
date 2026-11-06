import { grayFromRgba, rasterOf } from '../raster';
import type { Raster } from '../model';
import { ImportError } from './types';

/** Long side of a raster taken into a project. Base64 in the project JSON stays well under the Pi's 32 MB limit. */
export const MAX_RASTER_SIDE = 1600;

export interface Rgba { data: Uint8ClampedArray | Uint8Array; width: number; height: number }

/** Nearest-area downscale of RGBA, pure so the import can be tested without a browser. */
export function scaleRgba(src: Rgba, maxSide: number): Rgba {
  const k = Math.min(1, maxSide / Math.max(src.width, src.height));
  if (k >= 1) return src;
  const w = Math.max(1, Math.round(src.width * k)), h = Math.max(1, Math.round(src.height * k));
  const out = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) {
    const y0 = Math.floor(y * src.height / h), y1 = Math.max(y0 + 1, Math.floor((y + 1) * src.height / h));
    for (let x = 0; x < w; x++) {
      const x0 = Math.floor(x * src.width / w), x1 = Math.max(x0 + 1, Math.floor((x + 1) * src.width / w));
      let r = 0, g = 0, b = 0, a = 0, n = 0;
      for (let v = y0; v < y1; v++) for (let u = x0; u < x1; u++) {
        const i = (v * src.width + u) * 4;
        r += src.data[i]; g += src.data[i + 1]; b += src.data[i + 2]; a += src.data[i + 3]; n++;
      }
      const o = (y * w + x) * 4;
      out[o] = r / n; out[o + 1] = g / n; out[o + 2] = b / n; out[o + 3] = a / n;
    }
  }
  return { data: out, width: w, height: h };
}

export function rasterFromRgba(img: Rgba, maxSide = MAX_RASTER_SIDE): Raster {
  const s = scaleRgba(img, maxSide);
  return rasterOf(s.width, s.height, grayFromRgba(s.data, s.width, s.height));
}

/** Browser decoder for PNG, JPG, WebP, BMP, GIF. Throws a sentence when the format is unreadable. */
export async function decodeImageBytes(bytes: Uint8Array): Promise<Rgba> {
  if (typeof createImageBitmap === 'undefined') throw new ImportError('Bilder lassen sich nur in der App lesen.');
  let bmp: ImageBitmap;
  try { bmp = await createImageBitmap(new Blob([bytes as BlobPart])); }
  catch { throw new ImportError('Dieses Bildformat lässt sich nicht lesen. Bitte als PNG oder JPG speichern.'); }
  const canvas = new OffscreenCanvas(bmp.width, bmp.height);
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new ImportError('Das Bild lässt sich nicht lesen.');
  ctx.drawImage(bmp, 0, 0);
  const d = ctx.getImageData(0, 0, bmp.width, bmp.height);
  bmp.close();
  return { data: d.data, width: d.width, height: d.height };
}

/**
 * Resolution stored in the file (PNG pHYs, JPEG JFIF) in dots per inch, or null when the file does
 * not say or claims the 72/96 dpi screen default, which is never a print size.
 */
export function readDpi(b: Uint8Array): number | null {
  const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  const accept = (dpi: number) => dpi >= 30 && dpi <= 4800 && Math.abs(dpi - 72) > 0.5 && Math.abs(dpi - 96) > 0.5 ? dpi : null;
  if (b[0] === 0x89 && b[1] === 0x50) {
    for (let p = 8; p + 12 <= b.length;) {
      const len = dv.getUint32(p);
      const type = String.fromCharCode(b[p + 4], b[p + 5], b[p + 6], b[p + 7]);
      if (type === 'pHYs' && len >= 9) return b[p + 16] === 1 ? accept(dv.getUint32(p + 8) * 0.0254) : null;
      if (type === 'IDAT') return null;
      p += 12 + len;
    }
    return null;
  }
  if (b[0] === 0xFF && b[1] === 0xD8) {
    for (let p = 2; p + 4 < b.length && b[p] === 0xFF;) {
      const marker = b[p + 1], len = dv.getUint16(p + 2);
      if (marker === 0xE0 && String.fromCharCode(b[p + 4], b[p + 5], b[p + 6], b[p + 7]) === 'JFIF') {
        const unit = b[p + 11], x = dv.getUint16(p + 12);
        return unit === 1 ? accept(x) : unit === 2 ? accept(x * 2.54) : null;
      }
      if (marker === 0xDA) return null;
      p += 2 + len;
    }
  }
  return null;
}
