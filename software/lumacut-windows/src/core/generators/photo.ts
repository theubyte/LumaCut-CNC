import { type ImageMode, Limits, type Raster } from '../model';
import { rasterOf } from '../raster';
import { MAX_RASTER_SIDE } from '../import/image';
import { GenError, type GenResult } from './types';

/**
 * Photo engraving preparation. Brightness, contrast, sharpen and invert stay as `adjust` on the element, as on
 * Android, so they can be changed later; the tone curve and the resolution are baked into the raster.
 */
export interface PhotoMaterial { key: string; label: string; intervalMm: number; mode: ImageMode; gamma: number; hint: string }
/** Guide values, not measurements: only plywood was measured on this machine (docs/MATERIAL_KALIBRIERUNG.md). */
export const PHOTO_MATERIALS: PhotoMaterial[] = [
  { key: 'sperrholz', label: 'Sperrholz', intervalMm: 0.12, mode: 'DITHER', gamma: 1.2, hint: 'Gemessen: Sperrholz kippt zwischen 4,5 und 8,5 % von hell nach fast schwarz, Zwischentöne werden fleckig. Deshalb Punkte statt Graustufen.' },
  { key: 'massivholz', label: 'Massivholz, hell', intervalMm: 0.12, mode: 'DITHER', gamma: 1.2, hint: 'Richtwert, nicht gemessen. Maserung schlägt durch, ruhiges Holz wählen.' },
  { key: 'mdf', label: 'MDF', intervalMm: 0.1, mode: 'DITHER', gamma: 1.1, hint: 'Richtwert, nicht gemessen. Gleichmäßige Fläche, gut für feine Punkte.' },
  { key: 'leder', label: 'Leder', intervalMm: 0.12, mode: 'GRAYSCALE', gamma: 1.3, hint: 'Richtwert, nicht gemessen. Nur echtes, chromfrei gegerbtes Leder.' },
  { key: 'karton', label: 'Karton, Papier', intervalMm: 0.15, mode: 'DITHER', gamma: 1.3, hint: 'Richtwert, nicht gemessen. Wenig Leistung, brennt schnell durch. Danebenbleiben.' },
  { key: 'eloxal', label: 'Eloxiertes Aluminium', intervalMm: 0.08, mode: 'THRESHOLD', gamma: 1, hint: 'Richtwert, nicht gemessen. Die Färbung kennt nur dunkel oder hell: Schwellwert oder feine Punkte.' },
];
export const photoMaterial = (key: string) => PHOTO_MATERIALS.find((m) => m.key === key) ?? PHOTO_MATERIALS[0];

export interface PhotoSource { gray: Uint8Array; width: number; height: number }
export interface PhotoSpec { widthMm: number; intervalMm: number; mode: ImageMode; gamma: number; brightness: number; contrast: number; sharpen: number; invert: boolean; materialKey: string }

/** Box-filter resample of gray values. */
export function resampleGray(src: PhotoSource, w: number, h: number): Uint8Array {
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    const y0 = Math.floor(y * src.height / h), y1 = Math.max(y0 + 1, Math.ceil((y + 1) * src.height / h));
    for (let x = 0; x < w; x++) {
      const x0 = Math.floor(x * src.width / w), x1 = Math.max(x0 + 1, Math.ceil((x + 1) * src.width / w));
      let sum = 0, n = 0;
      for (let v = y0; v < y1 && v < src.height; v++) for (let u = x0; u < x1 && u < src.width; u++) { sum += src.gray[v * src.width + u]; n++; }
      out[y * w + x] = n ? Math.round(sum / n) : 255;
    }
  }
  return out;
}
/** gamma above 1 lightens the midtones, which a burn otherwise renders too dark. */
export function applyGamma(g: Uint8Array, gamma: number): Uint8Array {
  if (gamma === 1) return g;
  const lut = new Uint8Array(256);
  for (let i = 0; i < 256; i++) lut[i] = Math.round(255 * Math.pow(i / 255, 1 / gamma));
  return g.map((v) => lut[v]);
}

export function preparePhoto(src: PhotoSource, s: PhotoSpec): Raster {
  if (!(s.intervalMm >= 0.05 && s.intervalMm <= 1)) throw new GenError('Zeilenabstand: 0,05 bis 1 mm.');
  const heightMm = s.widthMm * src.height / src.width;
  let w = Math.round(s.widthMm / s.intervalMm), h = Math.round(heightMm / s.intervalMm);
  const k = Math.min(1, MAX_RASTER_SIDE / Math.max(w, h));
  w = Math.max(1, Math.round(w * k)); h = Math.max(1, Math.round(h * k));
  return rasterOf(w, h, applyGamma(resampleGray(src, w, h), s.gamma));
}

export function photoResult(src: PhotoSource, s: PhotoSpec): GenResult {
  if (!(s.widthMm >= 5 && s.widthMm <= 350)) throw new GenError('Breite: 5 bis 350 mm.');
  const raster = preparePhoto(src, s);
  const heightMm = s.widthMm * src.height / src.width;
  const iv = String(+s.intervalMm.toFixed(3)).replace('.', ',');
  const notes = [`${Math.round(s.widthMm)} × ${Math.round(heightMm)} mm, ${Math.round(heightMm / s.intervalMm)} Zeilen bei ${iv} mm Zeilenabstand.`, photoMaterial(s.materialKey).hint];
  const warnings: string[] = [];
  const pxPerMm = src.width / s.widthMm;
  if (pxPerMm * s.intervalMm < 0.7) warnings.push(`Das Foto hat bei dieser Größe nur ${pxPerMm.toFixed(1).replace('.', ',')} Pixel je mm und wird weich. Kleiner gravieren oder ein größeres Foto wählen.`);
  return {
    parts: [{ name: 'Foto', layer: 'foto', paths: [], x: 0, y: 0, image: { raster, widthMm: s.widthMm, heightMm, mode: s.mode, adjust: { brightness: s.brightness, contrast: s.contrast, sharpen: s.sharpen, invert: s.invert } } }],
    layers: [{ key: 'foto', name: `Foto ${iv} mm`, base: 'Gravieren', over: { mode: 'FILL', intervalMm: s.intervalMm, minPowerPct: s.mode === 'GRAYSCALE' ? Limits.MIN_RELIABLE_POWER_PCT : 0 } }],
    notes, warnings,
  };
}

/** A soft gradient with a few shapes, so the assistant can be tried without a photo at hand. */
export function samplePhoto(width = 480, height = 320): PhotoSource {
  const gray = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    let v = 40 + 200 * x / width;
    const d = Math.hypot(x - width * 0.32, y - height * 0.5);
    if (d < height * 0.3) v = 235 - 200 * d / (height * 0.3);
    if (x > width * 0.62 && x < width * 0.9 && y > height * 0.25 && y < height * 0.75) v = ((Math.floor(x / 16) + Math.floor(y / 16)) % 2) ? 30 : 225;
    gray[y * width + x] = Math.max(0, Math.min(255, v));
  }
  return { gray, width, height };
}
