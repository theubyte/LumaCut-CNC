import { beforeEach, describe, expect, it } from 'vitest';
import { booleanOp, booleanShapes, offsetPolys } from './boolean';
import { polyArea } from './contour';
import { fmt3, fmtFixed } from './fmt';
import { writeMarlin } from './gcode';
import { hatch, hypot, polyClosed, Shapes } from './geometry';
import { binarize } from './imageTools';
import { buildJob, cancelJob, JobAborted } from './jobClient';
import { computeJob } from './job';
import { boundsOf, configureBed, newDoc, newElement, newLayer, type Poly } from './model';
import { splitParts } from './parts';
import { decodeBase64, encodeBase64, grayFromRgba, grayOf, previewRgba, rasterOf } from './raster';
import { expandToolpath, formatDuration, parseToolpath, parseToolpathCompact } from './toolpath';
import { vectorize } from './vectorize';

const rect = (x: number, y: number, w: number, h: number): Poly => [{ x, y }, { x: x + w, y }, { x: x + w, y: y + h }, { x, y: y + h }, { x, y }];
const totalArea = (l: Poly[]) => l.reduce((s, p) => s + polyArea(p), 0);
beforeEach(() => configureBed(370, 360, 78, 35));

describe('fmt wie Java', () => {
  it('rundet HALF_UP auf den kürzesten Ziffern', () => {
    expect(fmt3(1.0005)).toBe('1.001');          // toFixed ergäbe 1.000
    expect(fmt3(2.0015)).toBe('2.002');
    expect(fmt3(0.0005)).toBe('0.001');
    expect(fmt3(0.00049)).toBe('0.000');
    expect(fmt3(9.9995)).toBe('10.000');
    expect(fmt3(369.9999)).toBe('370.000');
    expect(fmt3(5)).toBe('5.000');
    expect(fmt3(5.5)).toBe('5.500');
  });
  it('Vorzeichen und sehr kleine Zahlen', () => {
    expect(fmt3(-0)).toBe('-0.000');
    expect(fmt3(-0.0001)).toBe('-0.000');
    expect(fmt3(-0.5)).toBe('-0.500');
    expect(fmt3(1e-7)).toBe('0.000');
    expect(fmt3(6e-4)).toBe('0.001');
    expect(fmt3(1e21)).toBe('1000000000000000000000.000');
  });
  it('Dezimalkomma und ohne Stellen', () => {
    expect(fmtFixed(3.5, 2, ',')).toBe('3,50');
    expect(fmtFixed(9000.5, 0)).toBe('9001');
    expect(fmtFixed(0.4, 0)).toBe('0');
  });
});

describe('hypot wie fdlibm', () => {
  it('stimmt und ist symmetrisch', () => {
    expect(hypot(3, 4)).toBe(5);
    expect(hypot(4, 3)).toBe(5);
    expect(hypot(-3, 4)).toBe(5);
    expect(hypot(0, 7)).toBe(7);
    expect(hypot(0, 0)).toBe(0);
    expect(hypot(1e-5, 1e5)).toBeCloseTo(1e5, 6);
    for (let i = 1; i < 500; i++) expect(hypot(i * 0.37, i * 1.13)).toBe(hypot(i * 1.13, i * 0.37));
  });
});

describe('raster', () => {
  it('Base64 hin und zurück', () => {
    for (const n of [0, 1, 2, 3, 4, 100, 30000]) {
      const b = new Uint8Array(n).map((_, i) => (i * 31) & 255);
      const s = encodeBase64(b);
      expect(s).toBe(Buffer.from(b).toString('base64'));
      expect([...decodeBase64(s)]).toEqual([...b]);
    }
  });
  it('Graustufen wie Android, Durchsichtiges wird weiß', () => {
    const g = grayFromRgba(new Uint8Array([255, 0, 0, 255, 0, 0, 0, 0, 0, 0, 0, 128, 255, 255, 255, 255]), 2, 2);
    expect([...g]).toEqual([54, 255, 127, 255]);
  });
  it('rasterOf prüft die Größe, grayOf merkt sich das Ergebnis', () => {
    expect(() => rasterOf(2, 2, new Uint8Array(3))).toThrow();
    const r = rasterOf(2, 1, new Uint8Array([10, 20]));
    expect([...grayOf(r)]).toEqual([10, 20]);
    expect(grayOf(r)).toBe(grayOf({ ...r }));
  });
  it('Vorschau mit Modus, Anpassung und Größenkappung', () => {
    const r = rasterOf(4, 1, new Uint8Array([0, 100, 200, 255]));
    expect([...previewRgba(r).data.slice(0, 8)]).toEqual([0, 0, 0, 255, 100, 100, 100, 255]);
    const inv = previewRgba(r, { adjust: { invert: true } });
    expect(inv.data[0]).toBe(255);
    const t = previewRgba(r, { mode: 'THRESHOLD' });
    expect([t.data[0], t.data[4], t.data[8]]).toEqual([0, 0, 255]);
    expect(previewRgba(r, { transparentWhite: true }).data[3]).toBe(255);
    expect(previewRgba(r, { transparentWhite: true }).data[15]).toBe(0);
    const big = previewRgba(rasterOf(100, 100, new Uint8Array(10000)), { maxPixels: 100 });
    expect(big.width * big.height).toBeLessThanOrEqual(100);
  });
  it('Dither erhält die mittlere Helligkeit', () => {
    const gray = new Uint8Array(100 * 100).fill(128);
    for (const m of ['DITHER', 'DITHER_JARVIS', 'DITHER_STUCKI'] as const) {
      const o = binarize(gray, 100, 100, m), mean = o.reduce((s, v) => s + v, 0) / o.length;
      expect(new Set(o).size).toBe(2);
      expect(Math.abs(mean - 128)).toBeLessThan(8);
    }
  });
});

describe('vectorize', () => {
  const image = (w: number, h: number, on: (x: number, y: number) => boolean) => {
    const g = new Uint8Array(w * h).fill(255);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (on(x, y)) g[y * w + x] = 0;
    return g;
  };
  it('Quadrat mit Loch: Außenkontur vor Loch, geschlossen, richtige Fläche', () => {
    const g = image(20, 20, (x, y) => x >= 2 && x < 18 && y >= 2 && y < 18 && !(x >= 8 && x < 12 && y >= 8 && y < 12));
    const r = vectorize(g, 20, 20);
    expect(r.length).toBe(2);
    expect(r.every((p) => polyClosed(p))).toBe(true);
    expect(polyArea(r[0])).toBeCloseTo(256, 6);
    expect(polyArea(r[1])).toBeCloseTo(-16, 6);
    expect(r[0].length).toBe(5);
    expect(boundsOf([r[0]])).toEqual({ minX: 2, minY: 2, maxX: 18, maxY: 18 });
    expect(vectorize(g, 20, 20, { outerOnly: true }).length).toBe(1);
  });
  it('Maßstab und Umkehrung', () => {
    const g = image(10, 10, (x, y) => x < 5 && y < 5);
    const r = vectorize(g, 10, 10, { widthMm: 100, heightMm: 50 });
    expect(boundsOf(r)).toEqual({ minX: 0, minY: 0, maxX: 50, maxY: 25 });
    const inv = vectorize(g, 10, 10, { invert: true });
    expect(totalArea(inv)).toBeCloseTo(75, 6);
  });
  it('Diagonale Pixel bleiben getrennt, Flecken fallen weg', () => {
    const g = image(8, 8, (x, y) => (x >= 1 && x < 4 && y >= 1 && y < 4) || (x >= 4 && x < 7 && y >= 4 && y < 7));
    const r = vectorize(g, 8, 8);
    expect(r.length).toBe(2);
    expect(r.map(polyArea)).toEqual([9, 9]);
    expect(vectorize(image(8, 8, (x, y) => x === 3 && y === 3), 8, 8).length).toBe(0);
    expect(vectorize(image(8, 8, (x, y) => x === 3 && y === 3), 8, 8, { minAreaMm2: 0.5 }).length).toBe(1);
  });
  it('Kreis: wenige Punkte, Fläche nah am Soll, Treppen weg', () => {
    const R = 40, g = image(100, 100, (x, y) => (x + 0.5 - 50) ** 2 + (y + 0.5 - 50) ** 2 < R * R);
    const [c] = vectorize(g, 100, 100);
    expect(Math.abs(polyArea(c) - Math.PI * R * R) / (Math.PI * R * R)).toBeLessThan(0.02);
    expect(c.length).toBeLessThan(90);
  });
  it('Ganz schwarz und ganz weiß, Randberührung', () => {
    expect(vectorize(new Uint8Array(25).fill(255), 5, 5)).toEqual([]);
    const r = vectorize(new Uint8Array(25), 5, 5);
    expect(r.length).toBe(1);
    expect(polyArea(r[0])).toBe(25);
  });
});

describe('boolean', () => {
  const A = rect(0, 0, 10, 10), B = rect(5, 5, 10, 10);
  it('alle vier Operationen', () => {
    expect(totalArea(booleanOp('union', [A], [B]))).toBeCloseTo(175, 6);
    expect(totalArea(booleanOp('intersect', [A], [B]))).toBeCloseTo(25, 6);
    expect(totalArea(booleanOp('subtract', [A], [B]))).toBeCloseTo(75, 6);
    expect(Math.abs(totalArea(booleanOp('xor', [A], [B])))).toBeCloseTo(150, 6);
  });
  it('Ergebnis ist geschlossen mit wiederholtem Anfang', () => {
    for (const p of booleanOp('union', [A], [B])) {
      expect(p[0]).toEqual(p[p.length - 1]);
      expect(p.length).toBeGreaterThan(3);
    }
  });
  it('Loch entsteht und bleibt erhalten, Außenkontur zuerst', () => {
    const r = booleanOp('subtract', [rect(0, 0, 20, 20)], [rect(5, 5, 10, 10)]);
    expect(r.length).toBe(2);
    expect(Math.abs(polyArea(r[0]))).toBeCloseTo(400, 6);
    expect(Math.abs(polyArea(r[1]))).toBeCloseTo(100, 6);
    expect(Math.sign(polyArea(r[0]))).toBe(-Math.sign(polyArea(r[1])));
    // Ein Ring als Subjekt: even-odd, das Loch bleibt beim Vereinigen mit etwas außerhalb
    const u = booleanOp('union', r, [rect(30, 0, 5, 5)]);
    expect(u.length).toBe(3);
    const ring = booleanOp('intersect', r, [rect(0, 0, 20, 10)]);
    expect(Math.abs(totalArea(ring))).toBeCloseTo(150, 6);
  });
  it('mehrere Formen', () => {
    const C = rect(100, 100, 5, 5);
    expect(Math.abs(totalArea(booleanShapes('union', [[A], [B], [C]])))).toBeCloseTo(200, 6);
    expect(Math.abs(totalArea(booleanShapes('subtract', [[A], [B], [rect(0, 0, 2, 2)]])))).toBeCloseTo(71, 6);
    expect(booleanShapes('intersect', [[A], [B], [C]])).toEqual([]);
    expect(booleanOp('intersect', [], [A])).toEqual([]);
    expect(booleanShapes('union', [])).toEqual([]);
  });
  it('Offset wächst und schrumpft, Löcher umgekehrt, Innenecken scharf', () => {
    const grown = offsetPolys([A], 1);
    expect(Math.abs(totalArea(grown))).toBeCloseTo(100 + 40 + Math.PI, 0);
    expect(polyClosed(grown[0])).toBe(true);
    expect(Math.abs(totalArea(offsetPolys([A], 1, 'miter')))).toBeCloseTo(144, 4);
    expect(Math.abs(totalArea(offsetPolys([A], -1)))).toBeCloseTo(64, 4);
    expect(offsetPolys([A], -6)).toEqual([]);
    const ring = offsetPolys([rect(0, 0, 20, 20), rect(5, 5, 10, 10)], 1, 'miter');
    expect(ring.length).toBe(2);
    expect(Math.abs(polyArea(ring[0]))).toBeCloseTo(22 * 22, 4);
    expect(Math.abs(polyArea(ring[1]))).toBeCloseTo(64, 4);
    expect(offsetPolys([[{ x: 0, y: 0 }, { x: 5, y: 5 }]], 1)).toEqual([]);
  });
});

describe('Toolpath', () => {
  it('Zustände wie CoreTest.kt: S bleibt bis zum G0, ohne M3 I kein Schnitt', () => {
    const tp = parseToolpath('G21\nG90\nM3 I\nG0 X10 Y10\nG1 X20 Y10 F600 S128\nG1 X30\nG0 X0 Y0\nG1 X5 F600\nM5 I\nG1 X50 S200\n');
    const cuts = tp.segments.filter((s) => s.cut);
    expect(cuts.map((s) => s.power)).toEqual([128, 128]);
    expect(tp.stats.cutMm).toBe(20);
    expect(tp.stats.maxPower).toBe(128);
    expect(tp.stats.warnings[0]).toContain('1 Laserfahrten');
    expect(tp.segments[1].line).toBe(5);
    expect(tp.lineCount).toBe(11);
    expect(tp.bounds).toEqual({ minX: 10, minY: 10, maxX: 30, maxY: 10 });
  });
  it('Warnung ohne Laserbewegung, Park-Ecke in Maschinenkoordinaten', () => {
    expect(parseToolpath('G0 X1\n').stats.warnings).toEqual(['Keine Laserbewegung gefunden']);
    expect(parseToolpath('M3 I\nG0 X10 Y10\nG1 X20 S10 F100\n').stats.warnings[0]).toContain('Park-Ecke');
    expect(parseToolpath('M3 I\nG0 X100 Y50\nG1 X120 S10 F100\n').stats.warnings).toEqual([]);
  });
  it('Kompakte und ausführliche Form sind gleich', () => {
    const t = 'M3 I\nG0 X100 Y50\nG1 X120 S10 F100\nG1 Y60\n';
    const c = parseToolpathCompact(t);
    expect(c.xy).toBeInstanceOf(Float32Array);
    expect(expandToolpath(c)).toEqual(parseToolpath(t));
    expect(c.count).toBe(3);
  });
  it('Dauer', () => {
    expect(formatDuration(5.9)).toBe('5 s');
    expect(formatDuration(65)).toBe('1 min 05 s');
    expect(formatDuration(3700)).toBe('1 h 01 min');
  });
});

describe('Teile', () => {
  it('splitParts: Ring bleibt ganz, zweites Teil wird eigenes Element', () => {
    const l = newLayer('Linie', 1, 'LINE');
    const e = newElement(l.id, 'SVG', { transform: { x: 10, y: 20, scaleX: 1, scaleY: 1, rotation: 0 }, paths: [rect(0, 0, 20, 20), rect(5, 5, 5, 5), rect(30, 0, 5, 5)], curves: [] });
    const parts = splitParts(e);
    expect(parts.length).toBe(2);
    expect(parts[0].paths.length).toBe(2);
    expect(parts[0].transform.x).toBe(10);
    expect(parts[1].transform.x).toBe(40);
    expect(parts[1].paths[0][0]).toEqual({ x: 0, y: 0 });
    expect('curves' in parts[0]).toBe(false);
    expect(new Set(parts.map((p) => p.id)).size).toBe(2);
    expect(splitParts({ ...e, text: 'A' })).toEqual([{ ...e, text: 'A' }]);
  });
});

describe('Auftrag', () => {
  const docWith = (plate = 0) => {
    const d = newDoc('T');
    const l = d.layers[1];
    d.elements.push(newElement(l.id, 'R', { transform: { x: 20, y: 40, scaleX: 1, scaleY: 1, rotation: 0 }, paths: [rect(0, 0, 5, 5)], plate }));
    return d;
  };
  it('buildJob liefert G-Code, Weg und Werte der Platte', async () => {
    const r = await buildJob(docWith());
    expect(r.gcode).toContain('G1 X');
    expect(r.toolpath.count).toBeGreaterThan(0);
    expect(r.stats.cutMm).toBeCloseTo(20, 6);
    await expect(buildJob(docWith(1), 0)).rejects.toThrow('Nichts zu lasern');
    expect((await buildJob(docWith(1), 1)).stats.cutMm).toBeCloseTo(20, 6);
  });
  it('neuer Lauf bricht den alten ab', async () => {
    const first = buildJob(docWith());
    const second = buildJob(docWith());
    await expect(first).rejects.toBeInstanceOf(JobAborted);
    expect((await second).gcode).toContain('M400');
    const third = buildJob(docWith());
    cancelJob();
    await expect(third).rejects.toBeInstanceOf(JobAborted);
  });
  it('rechnet mit den aktuellen Maschinenmaßen', () => {
    const r = computeJob({ doc: docWith(), plate: 0, bed: { width: 400, height: 300, parkX: 60, parkY: 30 } });
    expect(r.gcode).toContain('X380.000 Y40.000');
  });
});

describe('Tempo', () => {
  const report = (name: string, ms: number, lines: number) => console.log(`${name}: ${Math.round(ms)} ms, ${lines} Zeilen`);
  it('großes Foto 200 × 200 mm bei 0,1 mm (4 Mio. Pixel), Dither', () => {
    const w = 1000, h = 1000, g = new Uint8Array(w * h);
    for (let i = 0; i < g.length; i++) g[i] = (i * 2654435761 >>> 24);
    const d = newDoc('Foto');
    d.elements.push(newElement(d.layers[0].id, 'Bild', { transform: { x: 40, y: 40, scaleX: 1, scaleY: 1, rotation: 0 }, raster: rasterOf(w, h, g), imageWidthMm: 200, imageHeightMm: 200, imageMode: 'DITHER' }));
    const t0 = performance.now();
    const text = writeMarlin(d);
    const t1 = performance.now();
    const tp = parseToolpathCompact(text);
    report('Foto G-Code', t1 - t0, tp.lineCount);
    report('Foto Werkzeugweg', performance.now() - t1, tp.count);
    expect(t1 - t0).toBeLessThan(20000);
  }, 60000);
  it('viele Pfade und große Füllung', () => {
    const d = newDoc('Viele');
    const paths: Poly[] = [];
    for (let i = 0; i < 6000; i++) paths.push(rect(40 + (i % 100) * 2.5, 40 + Math.floor(i / 100) * 2.5, 2, 2));
    d.elements.push(newElement(d.layers[1].id, 'Viele', { paths }));
    const t0 = performance.now();
    const a = writeMarlin(d);
    report('6000 Pfade', performance.now() - t0, a.length);
    const fine: Poly = Shapes.ellipse(250, 250, 0.01).map((p) => ({ x: p.x + 40, y: p.y + 40 }));
    expect(fine.length).toBeGreaterThan(50000);
    const t1 = performance.now();
    const hs = hatch([fine], 0.05);
    report('Schraffur 78000 Kanten', performance.now() - t1, hs.length);
    expect(performance.now() - t1).toBeLessThan(5000);
  }, 60000);
});
