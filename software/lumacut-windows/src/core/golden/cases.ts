/**
 * Eingaben für den Zeichen-Vergleich mit Kotlin. Dieselben Dokumente gehen als JSON an GoldenGen.kt.txt,
 * dessen Ausgaben unter golden/ liegen. Nur erzeugen, nicht rechnen: kein Sinus, damit die Eingabe überall gleich ist.
 */
import { newLayer, type Doc, type Element, type ImageAdjust, type ImageMode, type Layer, type Poly, type Pt } from '../model';
import { encodeBase64 } from '../raster';

export interface GoldenCase { name: string; doc: Doc; motion?: { accel: number; speed: number }; bed?: [number, number, number, number] }

let seq = 0;
const layer = (name: string, mode: 'LINE' | 'FILL', over: Partial<Layer> = {}): Layer =>
  newLayer(name, 0xFF4FD8B4, mode, { id: `L${seq++}`, ...over });
const el = (layerId: string, kind: string, over: Partial<Element>): Element => ({
  id: `E${seq++}`, layerId, kind, transform: { x: 0, y: 0, scaleX: 1, scaleY: 1, rotation: 0 }, paths: [], text: null, fontSizeMm: 10, bold: false,
  fontFamily: 'sans-serif', raster: null, imageWidthMm: 0, imageHeightMm: 0, imageMode: 'GRAYSCALE', adjust: {}, groupId: null, plate: 0, ...over });
const doc = (title: string, layers: Layer[], elements: Element[]): Doc => ({ title, layers, elements, plateCount: 1, activePlate: 0 });
const T = (x: number, y: number, scaleX = 1, scaleY = 1, rotation = 0) => ({ x, y, scaleX, scaleY, rotation });
const rect = (w: number, h: number, x = 0, y = 0): Poly => [{ x, y }, { x: x + w, y }, { x: x + w, y: y + h }, { x, y: y + h }, { x, y }];
const octagon = (cx: number, cy: number, r: number): Poly => {
  const k = r * 0.41421356;
  const p: Pt[] = [[k, -r], [r, -k], [r, k], [k, r], [-k, r], [-r, k], [-r, -k], [-k, -r]].map(([a, b]) => ({ x: cx + a, y: cy + b }));
  return [...p, p[0]];
};
function gradient(w: number, h: number): { width: number; height: number; grayBase64: string } {
  const g = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const blob = (x - w / 2) * (x - w / 2) + (y - h / 2) * (y - h / 2) < (h * h) / 9 ? 0 : 1;
    g[y * w + x] = blob ? Math.min(255, Math.trunc(255 * x / (w - 1))) : (x * 7 + y * 13) % 256;
  }
  return { width: w, height: h, grayBase64: encodeBase64(g) };
}
const image = (layerId: string, x: number, y: number, wMm: number, hMm: number, mode: ImageMode, adjust: ImageAdjust = {}) =>
  el(layerId, 'Bild', { transform: T(x, y), raster: gradient(40, 30), imageWidthMm: wMm, imageHeightMm: hMm, imageMode: mode, adjust });

export function namedCases(): GoldenCase[] {
  seq = 0;
  const L = () => layer('Linie', 'LINE', { powerPct: 40, speed: 1500 });
  const F = (over: Partial<Layer> = {}) => layer('Gravieren', 'FILL', { powerPct: 25, speed: 3000, intervalMm: 0.2, ...over });
  const out: GoldenCase[] = [];
  const add = (name: string, l: Layer[], e: Element[], extra: Partial<GoldenCase> = {}, title = name) => out.push({ name, doc: doc(title, l, e), ...extra });

  let a = L();
  add('linie', [a], [
    el(a.id, 'Rechteck', { transform: T(50, 60), paths: [rect(40, 30)] }),
    el(a.id, 'Loch', { transform: T(60, 70), paths: [rect(5, 5), octagon(15, 3, 2)] }),
    el(a.id, 'Offen', { transform: T(120, 100), paths: [[{ x: 0, y: 0 }, { x: 10, y: 5 }, { x: 20, y: 0 }], [{ x: 30, y: 30 }, { x: 0, y: 30 }]] }),
    el(a.id, 'Text', { text: 'Hallo', transform: T(10.1234, 200.5678, 1.5, 0.75), paths: [rect(3.3333, 7.7777)] }),
  ]);
  a = L();
  add('gedreht', [a], [el(a.id, 'Rechteck', { transform: T(100, 100, 1.2, 0.8, 30), paths: [rect(40, 30), octagon(20, 15, 5)] })]);
  a = layer('Schneiden', 'LINE', { powerPct: 85, speed: 400, passes: 3, zStepMm: 0.5 });
  add('fokus_absenkung', [a], [el(a.id, 'Rechteck', { transform: T(30, 80), paths: [rect(20, 20)] })]);
  a = layer('Schneiden', 'LINE', { powerPct: 85, speed: 400, passes: 2 });
  add('zwei_durchgaenge', [a], [el(a.id, 'Rechteck', { transform: T(30, 80), paths: [rect(20, 20), rect(5, 5, 5, 5)] })]);
  a = F();
  add('fuellung', [a], [el(a.id, 'Ring', { transform: T(80, 80), paths: [octagon(20, 20, 20), octagon(20, 20, 9)] }), el(a.id, 'Offen zaehlt nicht', { transform: T(10, 50), paths: [[{ x: 0, y: 0 }, { x: 5, y: 5 }]] })]);
  a = F({ intervalMm: 0.13, overscanMm: 0 });
  add('fuellung_gedreht', [a], [el(a.id, 'Stern', { transform: T(150, 150, 1.3, 1.1, 17.5), paths: [octagon(0, 0, 18)] })]);
  a = F({ overscanMm: 8 });
  add('fuellung_kante', [a], [el(a.id, 'Am Rand', { transform: T(0, 100), paths: [rect(30, 10)] }), el(a.id, 'Rechts', { transform: T(345, 100), paths: [rect(25, 10)] })]);
  for (const mode of ['GRAYSCALE', 'DITHER', 'DITHER_JARVIS', 'DITHER_STUCKI', 'THRESHOLD'] as ImageMode[]) {
    a = F({ intervalMm: 0.25, powerPct: 60, speed: 2000 });
    add(`raster_${mode.toLowerCase()}`, [a], [image(a.id, 40, 50, 20, 15, mode)]);
  }
  a = F({ intervalMm: 0.25, powerPct: 60, minPowerPct: 12, speed: 2000 });
  add('raster_min_leistung', [a], [image(a.id, 40, 50, 20, 15, 'GRAYSCALE')]);
  a = F({ intervalMm: 0.25, powerPct: 70, speed: 2000, toneCurve: [0, 0.05, 0.1, 0.2, 0.3, 0.45, 0.55, 0.7, 0.8, 0.9, 1] });
  add('raster_tonkurve', [a], [image(a.id, 40, 50, 20, 15, 'GRAYSCALE')]);
  a = F({ intervalMm: 0.25, powerPct: 60, speed: 2000 });
  add('raster_anpassung', [a], [image(a.id, 40, 50, 20, 15, 'GRAYSCALE', { brightness: 15, contrast: 30, sharpen: 60 })]);
  a = F({ intervalMm: 0.25, powerPct: 60, speed: 2000 });
  add('raster_invertiert_dither', [a], [image(a.id, 40, 50, 20, 15, 'DITHER', { brightness: -20, contrast: -10, sharpen: 25, invert: true })]);
  a = F({ intervalMm: 0.5, powerPct: 60, speed: 6000, passes: 2, zStepMm: 0.25 });
  add('raster_bewegung', [a], [image(a.id, 2, 50, 20, 15, 'GRAYSCALE')], { motion: { accel: 300, speed: 120 } });
  a = F({ intervalMm: 0.25, powerPct: 60, speed: 2000 });
  add('raster_und_vektor', [a], [image(a.id, 40, 50, 20, 15, 'THRESHOLD'), el(a.id, 'Feld', { transform: T(70, 50), paths: [rect(10, 10)] })]);
  a = L();
  add('rundung', [a], [el(a.id, 'Halbe', { paths: [[{ x: 1.0005, y: 36.0015 }, { x: 2.0025, y: 36.0035 }, { x: 0.0005, y: 40.0005 }, { x: 100.1235, y: 50.4445 }, { x: 0.0004999, y: 38.1 }, { x: 370, y: 360 }]] })]);
  a = L();
  add('andere_maschine', [a], [el(a.id, 'Rechteck', { transform: T(10, 40), paths: [rect(300, 200)] })], { bed: [400, 300, 60, 30] });
  a = layer('Linie', 'LINE', { powerPct: 33.3, speed: 1234.5 });
  const hidden = layer('Weg', 'LINE', { visible: false }), off = layer('Aus', 'LINE', { output: false });
  add('titel_und_ebenen', [hidden, a, off], [el(a.id, 'R', { transform: T(20, 40), paths: [rect(5, 5)] }), el(hidden.id, 'R', { transform: T(20, 40), paths: [rect(5, 5)] }), el(off.id, 'R', { transform: T(20, 40), paths: [rect(5, 5)] })], {}, 'Mit\r\nUmbruch – Ä');

  a = L(); add('fehler_nichts', [a], []);
  a = L(); const h = layer('Unsichtbar', 'LINE', { visible: false }); add('fehler_nur_unsichtbar', [h], [el(h.id, 'R', { transform: T(20, 40), paths: [rect(5, 5)] })]);
  a = L(); add('fehler_ausserhalb', [a], [el(a.id, 'Rechteck', { transform: T(365, 100), paths: [rect(40, 30)] })]);
  a = L(); add('fehler_ausserhalb_text', [a], [el(a.id, 'Text', { text: 'Name', transform: T(-1, 100), paths: [rect(40, 30)] })]);
  a = L(); add('fehler_park', [a], [el(a.id, 'Rechteck', { transform: T(300, 5), paths: [rect(10, 10)] })]);
  a = layer('Schnell', 'LINE', { speed: 9001 }); add('fehler_zu_schnell', [a], [el(a.id, 'R', { transform: T(20, 40), paths: [rect(5, 5)] })]);
  a = layer('Schnell', 'LINE', { speed: 7500.5 }); add('fehler_zu_schnell_bewegung', [a], [el(a.id, 'R', { transform: T(20, 40), paths: [rect(5, 5)] })], { motion: { accel: 500, speed: 100 } });
  a = layer('Tief', 'LINE', { passes: 8, zStepMm: 0.5 }); add('fehler_fokus', [a], [el(a.id, 'R', { transform: T(20, 40), paths: [rect(5, 5)] })]);
  a = layer('Tief', 'LINE', { zStepMm: 2.5 }); add('fehler_zstep', [a], [el(a.id, 'R', { transform: T(20, 40), paths: [rect(5, 5)] })]);
  a = layer('Falsch', 'LINE', { powerPct: 101 }); add('fehler_leistung', [a], [el(a.id, 'R', { transform: T(20, 40), paths: [rect(5, 5)] })]);
  a = layer('Falsch', 'LINE', { passes: 31 }); add('fehler_durchgaenge', [a], [el(a.id, 'R', { transform: T(20, 40), paths: [rect(5, 5)] })]);
  a = F(); add('fehler_bild_gedreht', [a], [{ ...image(a.id, 40, 50, 20, 15, 'GRAYSCALE'), transform: T(40, 50, 1, 1, 5) }]);
  return out;
}

function rng(seed: number) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

/** Zufällige kleine Dokumente; ein Teil davon endet absichtlich in Fehlern. */
export function fuzzCases(count: number): GoldenCase[] {
  seq = 100000;
  const r = rng(20261106);
  const int = (lo: number, hi: number) => lo + Math.floor(r() * (hi - lo + 1));
  const pick = <V,>(l: V[]) => l[int(0, l.length - 1)];
  // Teils auf einem 0,0005-Raster: dort liegen die Rundungs-Grenzfälle.
  const num = (lo: number, hi: number) => { const v = lo + r() * (hi - lo); const m = r(); return m < 0.3 ? Math.round(v * 2000) / 2000 : m < 0.5 ? Math.round(v * 10) / 10 : v; };
  const out: GoldenCase[] = [];
  for (let c = 0; c < count; c++) {
    const layers: Layer[] = [], elements: Element[] = [];
    const nl = int(1, 3);
    for (let i = 0; i < nl; i++) {
      const mode = r() < 0.5 ? 'LINE' : 'FILL' as const;
      layers.push(layer(`Ebene ${i}`, mode, {
        powerPct: num(0, 100), minPowerPct: r() < 0.3 ? num(0, 30) : 0, speed: r() < 0.03 ? 12000 : num(100, 6000), passes: int(1, 3),
        intervalMm: pick([0.1, 0.13, 0.2, 0.25, 0.5, 1, 0.03]) * (r() < 0.5 ? 1 : 3), overscanMm: num(0, 12), zStepMm: r() < 0.3 ? num(0, 1) : 0,
        output: r() > 0.05, visible: r() > 0.05, toneCurve: r() < 0.2 ? Array.from({ length: int(2, 11) }, () => r()) : [],
      }));
    }
    const ne = int(1, 5);
    for (let i = 0; i < ne; i++) {
      const l = pick(layers);
      const far = r() < 0.04;
      const x = far ? num(280, 372) : num(0, 250), y = far ? num(0, 40) : num(36, 300);
      const kind = r();
      if (kind < 0.25) {
        const w = int(1, 24), h = int(1, 24), g = new Uint8Array(w * h);
        for (let k = 0; k < g.length; k++) g[k] = r() < 0.2 ? 255 : int(0, 255);
        const mm = num(1, 25), mh = num(1, 25);
        elements.push(el(l.id, 'Bild', { transform: T(x, y, r() < 0.2 ? num(0.5, 1.5) : 1, 1, r() < 0.02 ? 5 : 0), raster: { width: w, height: h, grayBase64: encodeBase64(g) },
          imageWidthMm: mm, imageHeightMm: mh, imageMode: pick(['GRAYSCALE', 'DITHER', 'THRESHOLD', 'DITHER_JARVIS', 'DITHER_STUCKI'] as ImageMode[]),
          adjust: r() < 0.5 ? {} : { brightness: int(-120, 120), contrast: int(-120, 120), sharpen: int(0, 100), invert: r() < 0.5 } }));
      } else {
        const paths: Poly[] = [];
        const np = int(1, 6);
        for (let p = 0; p < np; p++) {
          const pts: Pt[] = [];
          const n = int(1, 9);
          for (let k = 0; k < n; k++) pts.push({ x: num(0, 40), y: num(0, 40) });
          if (r() < 0.6 && n >= 3) pts.push({ ...pts[0] });
          paths.push(pts);
        }
        elements.push(el(l.id, r() < 0.5 ? 'Form' : 'Linien', { transform: T(x, y, r() < 0.3 ? num(0.3, 2) : 1, r() < 0.3 ? num(0.3, 2) : 1, r() < 0.3 ? num(-180, 180) : 0), paths, text: r() < 0.1 ? 'Wort' : null }));
      }
    }
    out.push({ name: `f${c}`, doc: doc(`Fuzz ${c}`, layers, elements), motion: r() < 0.3 ? { accel: num(200, 3000), speed: num(50, 300) } : undefined });
  }
  return out;
}

/** Bekannte Formen für die Geometrie-Vergleiche. */
export function geoInput() {
  return {
    nested: [rect(60, 40), rect(20, 20, 5, 5), rect(6, 6, 8, 8), octagon(45, 20, 8), rect(30, 10, 80, 5)],
    ring: [octagon(20, 20, 20), octagon(20, 20, 9)],
    open: [[{ x: 0, y: 0 }, { x: 10, y: 5 }, { x: 20, y: 0 }], [{ x: 30, y: 30 }, { x: 0, y: 30 }], rect(10, 10, 50, 50), [{ x: 15, y: 5 }, { x: 40, y: 45 }]],
    dense: Array.from({ length: 200 }, (_, i) => ({ x: i * 0.25, y: ((i * 37) % 11) * 0.02 + (i > 100 ? 200 - i : i) * 0.1 })),
    text: [octagon(5, 5, 5), octagon(5, 5, 2), rect(4, 10, 14, 0), rect(10, 3, 22, 7)],
    boxes: [{ minX: 0, minY: 0, maxX: 10, maxY: 20 }, { minX: 30, minY: 5, maxX: 35, maxY: 8 }, { minX: 15, minY: 40, maxX: 40, maxY: 45 }, { minX: 100, minY: 100, maxX: 500, maxY: 120 }, { minX: 60, minY: 60, maxX: 360, maxY: 200 }, { minX: 60, minY: 60, maxX: 360, maxY: 220 }],
    points: [{ x: 50, y: 60 }, { x: 120, y: 90 }, { x: 80, y: 140 }, { x: 90, y: 90 }, { x: 50, y: 60 }, { x: 121.5, y: 141.25 }],
    toolpath: 'G21\nG90\nM3 I\nG0 X10 Y10\nG1 X20 Y10 F600 S128\nG2 X30 Y20 I0 J10\nG3 X10 Y40 I-10 J10 F1200\nG1 X0 Y0\nG0 X50 Y50 F3000 (Kommentar)\ng1 x60 y50 s2000 ; klein\nG91\nG1 X5 Y5\nG90\nG20\nG1 X1 Y1 F10\nG21\nM5 I\nG1 X100 Y100 S10\nM3 I\nG0 X5 Y5\nG1 X6 Y6\n',
    curve: { points: [{ x: 50, y: 60 }, { x: 80, y: 60 }, { x: 80, y: 100 }, { x: 50, y: 100 }], min_power_pct: 8, interval_mm: 0.1, speed_min: 1500, speed_max: 6000 },
  };
}
export const maskArgb = (w: number, h: number) => {
  const a = new Int32Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const inBlob = (x - 20) * (x - 20) + (y - 20) * (y - 20) < 144 && (x - 20) * (x - 20) + (y - 20) * (y - 20) > 25;
    const bar = x > 40 && x < 55 && y > 10 && y < 30;
    const speck = x === 50 && y === 36;
    const trans = x < 3 && y < 3;
    a[y * w + x] = trans ? 0 : inBlob || bar || speck ? (0xFF102030 | 0) : (0xFFF0F0E8 | 0);
  }
  return a;
};
