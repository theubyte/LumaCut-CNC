import { describe, expect, it } from 'vitest';
import { Bed, boundsOf, defaultLayers, insideWork, isClosed, newDoc, newElement, parkBox, type Poly } from '../model';
import { encodeGrayPng, exportDxf, exportSvg, exportWarnings } from '../export';
import { parseDxf } from '../import/dxf';
import { parseSvg } from '../import/svg';
import { grayOf, rasterOf } from '../raster';
import { applyNest, boxOuter, boxPanels, boxResult, boxSegments, dashes, frameResult, framePolys, gearDims, gearOutline, gearResult, GenError, maskBit, matGridResult, nest, nestUnits, parseTemplate, photoMaterial, photoResult, preparePhoto, qrEncode, qrPolys, qrResult, resampleGray, resultElements, rsDivisor, rsRemainder, rulerResult, samplePhoto, scaleBarResult, serialResult, serialText, stampResult, templateResult, type GenResult, type TextShaper } from './index';

/** Fake font: every character a 0.6 x 1 box with a hole, so tests need no font file. */
const shape: TextShaper = (text, h) => {
  const out: Poly[] = [];
  [...text].forEach((c, i) => {
    if (c === ' ') return;
    const x = i * h * 0.7, w = h * 0.6;
    out.push([{ x, y: 0 }, { x: x + w, y: 0 }, { x: x + w, y: h }, { x, y: h }, { x, y: 0 }]);
  });
  return out;
};
const area = (p: Poly) => { let a = 0; for (let i = 1; i < p.length; i++) a += p[i - 1].x * p[i].y - p[i].x * p[i - 1].y; return Math.abs(a / 2); };
const inside = (polys: Poly[], x: number, y: number) => {
  let n = 0;
  for (const p of polys) {
    let c = false;
    for (let i = 1; i < p.length; i++) if ((p[i - 1].y > y) !== (p[i].y > y) && x < (p[i].x - p[i - 1].x) * (y - p[i - 1].y) / (p[i].y - p[i - 1].y) + p[i - 1].x) c = !c;
    if (c) n++;
  }
  return n;
};
const ids = (r: GenResult) => resultElements(r, (l) => l);

describe('QR', () => {
  it('RS-Rest stimmt mit dem Android-Referenzwert überein', () => {
    const data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17];
    expect(rsRemainder(data, rsDivisor(10))).toEqual([196, 35, 39, 119, 235, 215, 231, 226, 93, 23]);
  });
  /** Reads the data bits back as a scanner would, with the mask from the format bits. */
  function readText(text: string) {
    const q = qrEncode(text), s = q.size;
    expect(s).toBe(q.version * 4 + 17);
    for (const [fx, fy] of [[0, 0], [s - 7, 0], [0, s - 7]]) {
      expect(q.modules[fy][fx] && q.modules[fy + 6][fx + 6] && !q.modules[fy + 1][fx + 1] && q.modules[fy + 3][fx + 3]).toBe(true);
    }
    expect(q.modules[s - 8][8]).toBe(true);
    let f = 0;
    const pos = [[8, 0], [8, 1], [8, 2], [8, 3], [8, 4], [8, 5], [8, 7], [8, 8], [7, 8], [5, 8], [4, 8], [3, 8], [2, 8], [1, 8], [0, 8]];
    pos.forEach(([x, y], i) => { if (q.modules[y][x]) f |= 1 << i; });
    const un = f ^ 0x5412;
    expect((un >> 13) & 3).toBe(0);           // level M
    expect((un >> 10) & 7).toBe(q.mask);
    return q;
  }
  it('Formatbits, Sucher, Maskenmuster', () => {
    for (const t of ['HELLO', 'https://lumacut.example/abc?x=1', 'Ä ö ü – Straße 12345678901234567890123456789012345678901234567890']) readText(t);
    expect(maskBit(0, 1, 1)).toBe(true);
  });
  it('Module identisch mit der Python-Bibliothek qrcode (Version 3, Maske 2)', () => {
    const q = qrEncode('https://lumacut.example/abc?x=1');
    expect([q.version, q.mask]).toEqual([3, 2]);
    expect(q.modules.map((r) => r.map((b) => b ? '1' : '0').join(''))).toEqual([
      '11111110000000011011101111111',
      '10000010011100000000001000001',
      '10111010110100101000101011101',
      '10111010111110001111001011101',
      '10111010101101110111101011101',
      '10000010100111111100001000001',
      '11111110101010101010101111111',
      '00000000101011010000000000000',
      '10111110010000110100101111100',
      '01011101000100011011111110001',
      '11011011001010000010110110000',
      '00111100001100101000101011010',
      '11000010010100001101000001100',
      '10011100100001110011101110001',
      '10001010010111111110100111100',
      '00001100001001010010000100010',
      '10110011011000110100000001100',
      '10110101110110011011101110101',
      '10001110110100000110000110100',
      '10111100110110101000010110010',
      '10101010101100000111111110111',
      '00000000100001110101100011111',
      '11111110001111111101101011100',
      '10000010111101010001100010001',
      '10111010110100111100111110101',
      '10111010111111000101010101100',
      '10111010111111011011011111110',
      '10000010010001011010101011010',
      '11111110100111001111011100100',
    ]);
  });
  it('Polygone sind geschlossene Läufe; Fehler sind Sätze', () => {
    const q = qrEncode('A');
    const polys = qrPolys(q, 1);
    expect(polys.every((p) => isClosed(p))).toBe(true);
    expect(boundsOf(polys)).toEqual({ minX: 0, minY: 0, maxX: q.size, maxY: q.size });
    expect(() => qrEncode('')).toThrow(GenError);
    expect(() => qrEncode('x'.repeat(500))).toThrow(/zu lang/);
    expect(qrResult({ text: 'x', moduleMm: 0.5, plate: false }).warnings!.length).toBe(1);
    const r = qrResult({ text: 'x', moduleMm: 1, plate: true });
    expect(r.parts.map((p) => p.layer)).toEqual(['Gravieren', 'Schneiden']);
    expect(boundsOf(r.parts[1].paths)!.minX).toBe(-4);
  });
});

describe('Box', () => {
  const s = { w: 100, d: 60, h: 50, t: 3, finger: 10, lid: 'none' as const };
  it('Teile, Maße und Flächen wie Android', () => {
    const p = new Map(boxPanels(s).map((x) => [x.name, x.poly]));
    expect([...p.keys()].sort()).toEqual(['Boden', 'Hinten', 'Links', 'Rechts', 'Vorne']);
    const b = boundsOf([p.get('Boden')!])!;
    expect(b.maxX - b.minX).toBeCloseTo(100, 9); expect(b.maxY - b.minY).toBeCloseTo(60, 9);
    const f = boundsOf([p.get('Vorne')!])!;
    expect(f.maxX - f.minX).toBeCloseTo(100, 9); expect(f.maxY - f.minY).toBeCloseTo(50, 9);
    expect(boundsOf([p.get('Links')!])!.maxX - boundsOf([p.get('Links')!])!.minX).toBeCloseTo(60, 9);
    expect([...p.values()].every((q) => isClosed(q))).toBe(true);
    expect([boxSegments(100, 10), boxSegments(50, 10), boxSegments(15, 10)]).toEqual([9, 5, 1]);
    expect(area(p.get('Vorne')!)).toBeCloseTo(5000 - 5 * 100 / 9 * 3 - 4 * 10 * 3, 6);
    expect(area(p.get('Links')!)).toBeCloseTo(3000 - 3 * 10 * 3 * 2 - 3 * 12 * 3 + 2 * 9, 6);
    expect(boxPanels({ ...s, lid: 'joined' }).length).toBe(6);
  });
  it('Innenmaße, Deckel, Kerf, zu klein', () => {
    expect(boxOuter({ ...s, inner: true })).toEqual({ w: 106, d: 66, h: 53 });
    expect(boxOuter({ ...s, inner: true, lid: 'joined' })).toEqual({ w: 106, d: 66, h: 56 });
    const loose = boxPanels({ ...s, lid: 'loose' }).map((p) => p.name);
    expect(loose).toContain('Deckel-Einsatz');
    const k = boxResult({ ...s, kerf: 0.2 });
    const base = boxResult(s);
    const w = (r: GenResult) => { const b = boundsOf(r.parts.find((p) => p.name === 'Boden')!.paths)!; return b.maxX - b.minX; };
    expect(w(k) - w(base)).toBeCloseTo(0.2, 2);
    expect(() => boxPanels({ ...s, t: 30 })).toThrow(/zu klein/);
  });
  it('liegt in der Arbeitsfläche, spart die Park-Ecke aus, geht auf mehrere Platten', () => {
    const small = boxResult(s);
    expect(small.placement).toBe('keep');
    for (const p of small.parts) {
      const b = boundsOf(p.paths)!;
      expect(insideWork(b)).toBe(true);
      const k = parkBox();
      expect(b.maxX > k.minX && b.minY < k.maxY).toBe(false);
    }
    const big = boxResult({ w: 250, d: 250, h: 200, t: 3, finger: 15, lid: 'joined' });
    expect(Math.max(...big.parts.map((p) => p.plate ?? 0))).toBeGreaterThan(0);
    expect(() => boxResult({ w: 500, d: 100, h: 100, t: 3, finger: 15, lid: 'none' })).toThrow(/größer als eine Platte/);
  });
});

describe('Zahnrad', () => {
  const g = { module: 2, teeth: 20, pressureDeg: 20, boreMm: 6 };
  it('Durchmesser stimmen, geschlossen, n Zähne', () => {
    const d = gearDims(g);
    expect(d.pitch).toBe(40); expect(d.outer).toBe(44); expect(d.root).toBe(35);
    const o = gearOutline(g);
    expect(isClosed(o)).toBe(true);
    const c = 22;
    const radii = o.map((p) => Math.hypot(p.x - c, p.y - c));
    expect(Math.max(...radii)).toBeCloseTo(22, 6);
    expect(Math.min(...radii)).toBeCloseTo(17.5, 6);
    let tips = 0, was = false;
    for (const r of radii) { const on = r > 21.9; if (on && !was) tips++; was = on; }
    expect(tips).toBe(20);
    const r = gearResult(g);
    expect(r.parts[0].paths.length).toBe(2);
    const bore = boundsOf([r.parts[0].paths[1]])!;
    expect(bore.maxX - bore.minX).toBeCloseTo(6, 1);
    expect((bore.minX + bore.maxX) / 2).toBeCloseTo(22, 1);
  });
  it('Zahndicke am Teilkreis ist die halbe Teilung', () => {
    const c = 22, o = gearOutline(g), rp = 20;
    const ang = (p: { x: number; y: number }) => Math.atan2(p.y - c, p.x - c);
    const crossing = o.slice(0, 40).findIndex((p, i) => i > 0 && Math.hypot(o[i - 1].x - c, o[i - 1].y - c) < rp && Math.hypot(p.x - c, p.y - c) >= rp);
    const t = ang(o[crossing]);
    expect(Math.abs(t + Math.PI / 2)).toBeCloseTo(Math.PI / 40, 1);
  });
  it('Grenzen und Warnung bei wenigen Zähnen', () => {
    expect(() => gearResult({ ...g, teeth: 3 })).toThrow(GenError);
    expect(() => gearResult({ ...g, boreMm: 40 })).toThrow(/Bohrung/);
    expect(gearResult({ ...g, teeth: 12 }).warnings!.length).toBe(1);
    expect(gearResult(g).warnings).toEqual([]);
  });
});

describe('Lineal, Maßstab, Rahmen', () => {
  it('Lineal: Striche je mm, Zahlen je cm, Umriss', () => {
    const r = rulerResult({ lengthMm: 150, widthMm: 30, holeMm: 5 }, shape);
    const by = (n: string) => r.parts.find((p) => p.name === n)!;
    expect(by('Lineal Striche').paths.length).toBe(151);
    expect(by('Lineal Striche').layer).toBe('Linie');
    const t = by('Lineal Striche').paths;
    expect(t[10][0].x - t[0][0].x).toBeCloseTo(10, 9);
    expect(by('Lineal Umriss').paths.length).toBe(2);
    expect(by('Lineal Umriss').layer).toBe('Schneiden');
    expect(by('Lineal Zahlen').paths.length).toBeGreaterThan(15);
    expect(() => rulerResult({ lengthMm: 5, widthMm: 30, holeMm: 0 }, shape)).toThrow(GenError);
  });
  it('Maßstab: Länge folgt aus Maßstab', () => {
    const r = scaleBarResult({ scale: 50, realLengthM: 5, segments: 5, heightMm: 3 }, shape);
    const frame = boundsOf(r.parts.find((p) => p.name === 'Maßstab Rahmen')!.paths)!;
    expect(frame.maxX - frame.minX).toBeCloseTo(100, 6);
    expect(r.parts.find((p) => p.name === 'Maßstab Felder')!.paths.length).toBe(3);
    expect(() => scaleBarResult({ scale: 1, realLengthM: 5, segments: 5, heightMm: 3 }, shape)).toThrow(/mm lang/);
  });
  it('Rahmen: Abstand, Doppelt, Oval umschließt, Striche', () => {
    const box = { minX: 10, minY: 10, maxX: 30, maxY: 20 };
    expect(boundsOf(framePolys(box, 'SIMPLE', 5))).toEqual({ minX: 5, minY: 5, maxX: 35, maxY: 25 });
    expect(framePolys(box, 'DOUBLE', 5).length).toBe(2);
    const oval = framePolys(box, 'OVAL', 0)[0];
    expect(inside([oval], 10.5, 10.5)).toBe(1);
    expect(dashes(framePolys(box, 'SIMPLE', 0)[0], 4, 2).length).toBeGreaterThan(8);
    const r = frameResult({ around: box, widthMm: 0, heightMm: 0, style: 'SIMPLE', marginMm: 2, cut: false });
    expect(r.placement).toBe('keep'); expect(r.parts[0].layer).toBe('Linie');
  });
});

describe('Seriennummern', () => {
  it('Vorlage: Startwert und Breite aus den Ziffern', () => {
    const t = parseTemplate('SN-{0007}/A');
    expect(serialText(t, 0)).toBe('SN-0007/A'); expect(serialText(t, 3, 2)).toBe('SN-0013/A');
    expect(serialText(parseTemplate('{9}'), 1)).toBe('10');
    expect(() => parseTemplate('ohne')).toThrow(/Platzhalter/);
  });
  const spec = { template: 'SN-{0001}', count: 12, textHeightMm: 5, tagWidthMm: 50, tagHeightMm: 15, holeMm: 3, gapMm: 2 };
  it('n Stück als Gruppen im Raster, nichts überlappt', () => {
    const r = serialResult(spec, shape);
    const texts = r.parts.filter((p) => p.layer === 'Gravieren');
    expect(texts.map((p) => p.name)).toContain('SN-0012');
    expect(texts.length).toBe(12);
    expect(r.parts.filter((p) => p.layer === 'Schneiden').length).toBe(12);
    const boxes = r.parts.filter((p) => p.layer === 'Schneiden').map((p) => boundsOf(p.paths)!);
    for (let i = 0; i < boxes.length; i++) {
      expect(insideWork(boxes[i])).toBe(true);
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j];
        expect(a.maxX <= b.minX || b.maxX <= a.minX || a.maxY <= b.minY || b.maxY <= a.minY).toBe(true);
      }
    }
  });
  it('mehrere Platten, wenn nötig; nur Text geht auch', () => {
    const many = serialResult({ ...spec, count: 200, tagWidthMm: 80, tagHeightMm: 40 }, shape);
    const plates = new Set(many.parts.map((p) => p.plate ?? 0));
    expect(plates.size).toBeGreaterThan(1);
    expect(many.parts.filter((p) => p.layer === 'Gravieren').length).toBe(200);
    expect(many.notes![0]).toMatch(/Platten/);
    const els = ids(many);
    expect(new Set(els.map((e) => e.plate)).size).toBe(plates.size);
    const text = serialResult({ ...spec, tagWidthMm: 0, tagHeightMm: 0 }, shape);
    expect(text.parts.every((p) => p.layer === 'Gravieren')).toBe(true);
    expect(() => serialResult({ ...spec, count: 9999 }, shape)).toThrow(/Anzahl/);
  });
});

describe('Schachteln', () => {
  const rect = (x: number, y: number, w: number, h: number, group: string | null = null) =>
    newElement('l', 'x', { transform: { x, y, scaleX: 1, scaleY: 1, rotation: 0 }, paths: [[{ x: 0, y: 0 }, { x: w, y: 0 }, { x: w, y: h }, { x: 0, y: h }, { x: 0, y: 0 }]], groupId: group });
  it('Gruppen bleiben zusammen, Teile überlappen nicht', () => {
    const els = [rect(100, 100, 50, 50), rect(100, 100, 40, 40), rect(10, 10, 20, 20, 'g'), rect(40, 40, 20, 20, 'g')];
    const units = nestUnits(els);
    expect(units.length).toBe(3);
    const plan = nest(units, 3);
    expect(plan.plates).toBe(1); expect(plan.leftOut).toBe(0);
    const doc = { ...newDoc(), elements: els };
    const out = applyNest(doc, plan, 0);
    const g = out.elements.filter((e) => e.groupId === 'g');
    expect(g[1].transform.x - g[0].transform.x).toBe(30);
    const a = out.elements[0].transform, b = out.elements[1].transform;
    expect(a.x + 50 + 3 <= b.x || b.x + 40 + 3 <= a.x || a.y + 50 + 3 <= b.y || b.y + 40 + 3 <= a.y).toBe(true);
  });
  it('überläuft auf neue Platten, zu Großes wird gemeldet', () => {
    const els = Array.from({ length: 12 }, (_, i) => rect(i, i, 150, 150));
    const plan = nest(nestUnits(els), 3);
    expect(plan.plates).toBeGreaterThan(1);
    const out = applyNest({ ...newDoc(), elements: els }, plan, 1);
    expect(out.plateCount).toBe(1 + plan.plates);
    expect(Math.min(...out.elements.map((e) => e.plate))).toBe(1);
    expect(nest(nestUnits([rect(0, 0, 900, 10)]), 3).leftOut).toBe(1);
    expect(plan.usagePct).toBeGreaterThan(20);
  });
  it('Park-Ecke bleibt frei', () => {
    const els = Array.from({ length: 20 }, (_, i) => rect(i, i, 60, 30));
    const plan = nest(nestUnits(els), 3);
    const out = applyNest({ ...newDoc(), elements: els }, plan, 0);
    const k = parkBox();
    for (const e of out.elements) expect(e.transform.x + 60 > k.minX && e.transform.y < k.maxY).toBe(false);
  });
});

describe('Materialtest-Raster', () => {
  const spec = { powerFrom: 20, powerTo: 100, powerSteps: 5, speedFrom: 300, speedTo: 3000, speedSteps: 5, mode: 'FILL' as const, cellMm: 10, gapMm: 4, passes: 1, intervalMm: 0.1 };
  it('Felder je eigene Ebene, Werte stimmen', () => {
    const r = matGridResult(spec, shape);
    expect(r.parts.filter((p) => p.name === 'Testfeld').length).toBe(25);
    expect(r.layers!.length).toBe(26);
    const first = r.layers!.find((l) => l.key === 'f0-0')!, last = r.layers!.find((l) => l.key === 'f4-4')!;
    expect(first.over.powerPct).toBe(20); expect(first.over.speed).toBe(300);
    expect(last.over.powerPct).toBe(100); expect(last.over.speed).toBe(3000);
    expect(first.name).toBe('20 % · 300 mm/min');
  });
  it('unter 8 % nicht erlaubt', () => {
    expect(() => matGridResult({ ...spec, powerFrom: 5 }, shape)).toThrow(/zündet/);
    expect(() => matGridResult({ ...spec, powerSteps: 11 }, shape)).toThrow(GenError);
  });
});

describe('Stempel', () => {
  const spec = { widthMm: 60, heightMm: 30, shape: 'rect' as const, lines: ['ABC'], bold: true, motif: 'none' as const, borderMm: 1, inverted: true, mirrored: true };
  it('invertiert: Hintergrund brennt, Schrift bleibt stehen', () => {
    const r = stampResult({ ...spec, borderMm: 0 }, shape);
    const paths = r.parts[0].paths;
    expect(inside(paths, 1, 1) % 2).toBe(1);
    const letter = paths[1], b = boundsOf([letter])!;
    expect(inside(paths, (b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2) % 2).toBe(0);
    expect(r.parts[1].layer).toBe('Schneiden');
  });
  it('Rand bleibt als Ring stehen', () => {
    const paths = stampResult(spec, shape).parts[0].paths;
    expect(inside(paths, 0.5, 15) % 2).toBe(1);   // outside the ring: burned
    expect(inside(paths, 2, 15) % 2).toBe(0);     // ring: stays
    expect(inside(paths, 3, 15) % 2).toBe(1);     // inside the ring: burned
  });
  it('gespiegelt heißt: x an der Mitte umgekehrt', () => {
    const asym: TextShaper = (t, h) => t ? [[{ x: 0, y: 0 }, { x: h, y: 0 }, { x: 0, y: h }, { x: 0, y: 0 }]] : [];
    const a = stampResult({ ...spec, borderMm: 0, mirrored: false }, asym).parts[0].paths[1];
    const b = stampResult({ ...spec, borderMm: 0, mirrored: true }, asym).parts[0].paths[1];
    a.forEach((p, i) => { expect(b[i].x).toBeCloseTo(60 - p.x, 6); expect(b[i].y).toBeCloseTo(p.y, 6); });
    expect(stampResult({ ...spec, mirrored: false }, shape).warnings!.join()).toMatch(/verkehrt/);
  });
  it('Motiv, rund, Fehler', () => {
    const m = stampResult({ ...spec, motif: 'star', borderMm: 0 }, shape);
    expect(m.parts[0].paths.length).toBe(1 + 1 + 3);
    const round = stampResult({ ...spec, shape: 'round', motif: 'heart' }, shape);
    expect(boundsOf(round.parts[1].paths)!.maxY).toBeCloseTo(60, 2);
    expect(() => stampResult({ ...spec, lines: [] }, shape)).toThrow(/fehlt/);
    const all = stampResult(spec, shape);
    expect(all.warnings!.join()).toMatch(/PVC/);
  });
});

describe('Foto', () => {
  const src = samplePhoto(100, 50);
  const spec = { widthMm: 50, intervalMm: 0.1, mode: 'DITHER' as const, gamma: 1, brightness: 0, contrast: 10, sharpen: 20, invert: false, materialKey: 'sperrholz' };
  it('Auflösung folgt dem Zeilenabstand, Maß bleibt', () => {
    const r = preparePhoto(src, spec);
    expect([r.width, r.height]).toEqual([500, 250]);
    const res = photoResult(src, spec);
    const img = res.parts[0].image!;
    expect(img.widthMm).toBe(50); expect(img.heightMm).toBe(25);
    expect(img.adjust).toEqual({ brightness: 0, contrast: 10, sharpen: 20, invert: false });
    expect(res.layers![0].over.intervalMm).toBe(0.1);
    expect(res.layers![0].name).toBe('Foto 0,1 mm');
  });
  it('Gamma hellt die Mitte auf, Mittelung stimmt', () => {
    const g = { gray: new Uint8Array(4).fill(100), width: 2, height: 2 };
    const r1 = grayOf(preparePhoto(g, { ...spec, widthMm: 2, intervalMm: 1 }));
    expect(r1[0]).toBe(100);
    const r2 = grayOf(preparePhoto(g, { ...spec, widthMm: 2, intervalMm: 1, gamma: 2 }));
    expect(r2[0]).toBeGreaterThan(150);
    expect([...resampleGray({ gray: new Uint8Array([0, 100, 200, 100]), width: 2, height: 2 }, 1, 1)]).toEqual([100]);
  });
  it('Empfehlung je Material, Warnung bei wenig Auflösung, Graustufen nicht unter 8 %', () => {
    expect(photoMaterial('eloxal').intervalMm).toBeLessThan(photoMaterial('karton').intervalMm);
    expect(photoResult(src, { ...spec, widthMm: 300 }).warnings!.join()).toMatch(/weich/);
    expect(photoResult(src, { ...spec, mode: 'GRAYSCALE' }).layers![0].over.minPowerPct).toBe(8);
    expect(() => preparePhoto(src, { ...spec, intervalMm: 2 })).toThrow(GenError);
  });
});

describe('Vorlagen', () => {
  it('alle vier: geschlossener Umriss, passender Text', () => {
    for (const [kind, w, h] of [['schild', 80, 30], ['untersetzer', 100, 100], ['anhaenger', 60, 20], ['etikett', 120, 70]] as const) {
      const r = templateResult({ kind, text: 'Anna', second: 'Werkstatt', widthMm: w, heightMm: h }, shape);
      const cut = r.parts.find((p) => p.layer === 'Schneiden')!;
      expect(cut.paths.every((p) => isClosed(p, 1e-3))).toBe(true);
      const text = r.parts.find((p) => p.layer === 'Gravieren')!;
      const t = boundsOf(text.paths)!, c = boundsOf(cut.paths)!;
      expect(t.minX).toBeGreaterThan(c.minX); expect(t.maxX).toBeLessThan(c.maxX);
      expect(t.minY).toBeGreaterThan(c.minY); expect(t.maxY).toBeLessThan(c.maxY);
    }
    expect(() => templateResult({ kind: 'schild', text: ' ', second: '', widthMm: 80, heightMm: 30 }, shape)).toThrow(/fehlt/);
  });
});

describe('Elemente', () => {
  it('center setzt mittig auf die Arbeitsfläche, Pfade lokal ab 0/0', () => {
    const r: GenResult = { parts: [{ name: 'a', layer: 'L', paths: [[{ x: 10, y: 10 }, { x: 30, y: 30 }]] }] };
    const [e] = ids(r);
    expect(e.paths[0][0]).toEqual({ x: 0, y: 0 });
    expect(e.transform.x).toBeCloseTo(Bed.width / 2 - 10, 9);
    expect(e.layerId).toBe('L');
  });
  it('keep behält Koordinaten, Gruppe je Platte', () => {
    const r: GenResult = { placement: 'keep', parts: [
      { name: 'a', layer: 'L', group: 'g', paths: [[{ x: 1, y: 2 }, { x: 3, y: 4 }]] },
      { name: 'b', layer: 'L', group: 'g', paths: [[{ x: 5, y: 2 }, { x: 6, y: 4 }]] },
      { name: 'c', layer: 'L', group: 'g', plate: 1, paths: [[{ x: 1, y: 2 }, { x: 3, y: 4 }]] }] };
    const e = resultElements(r, (l) => l, 2);
    expect(e[0].transform.x).toBe(1); expect(e[0].plate).toBe(2); expect(e[2].plate).toBe(3);
    expect(e[0].groupId).toBe(e[1].groupId); expect(e[2].groupId).not.toBe(e[0].groupId);
  });
});

describe('Export', () => {
  const layers = defaultLayers();
  const doc = { ...newDoc('Test <1>'), layers, elements: [
    newElement(layers[2].id, 'Schnitt', { transform: { x: 10, y: 20, scaleX: 1, scaleY: 1, rotation: 0 }, paths: [[{ x: 0, y: 0 }, { x: 50, y: 0 }, { x: 50, y: 30 }, { x: 0, y: 30 }, { x: 0, y: 0 }]] }),
    newElement(layers[0].id, 'Füllung', { transform: { x: 100, y: 20, scaleX: 2, scaleY: 2, rotation: 0 }, paths: [[{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }, { x: 0, y: 10 }, { x: 0, y: 0 }]] }),
    newElement(layers[0].id, 'andere Platte', { plate: 1, paths: [[{ x: 0, y: 0 }, { x: 300, y: 300 }]] }),
  ] };
  it('SVG: Maße in mm, Rückimport liefert dieselbe Geometrie', () => {
    const svg = exportSvg(doc, 0);
    expect(svg).toContain(`width="${Bed.width}mm"`);
    expect(svg).toContain('Test &lt;1&gt;');
    const r = parseSvg(new TextEncoder().encode(svg));
    expect(r.items.length).toBe(2);
    const fill = r.items.find((i) => i.fill)!, line = r.items.find((i) => !i.fill)!;
    expect(boundsOf(line.polys)).toEqual({ minX: 10, minY: 20, maxX: 60, maxY: 50 });
    expect(boundsOf(fill.polys)).toEqual({ minX: 100, minY: 20, maxX: 120, maxY: 40 });
  });
  it('SVG: Bilder eingebettet mit Größe, PNG ist gültig', () => {
    const raster = rasterOf(2, 2, new Uint8Array([0, 100, 200, 255]));
    const d = { ...doc, elements: [newElement(layers[0].id, 'Bild', { raster, imageWidthMm: 40, imageHeightMm: 40, transform: { x: 5, y: 6, scaleX: 1, scaleY: 1, rotation: 0 } })] };
    const r = parseSvg(new TextEncoder().encode(exportSvg(d, 0)));
    expect(r.images[0].box).toEqual({ minX: 5, minY: 6, maxX: 45, maxY: 46 });
    const png = encodeGrayPng(new Uint8Array([0, 100, 200, 255]), 2, 2);
    expect([...png.subarray(0, 4)]).toEqual([0x89, 0x50, 0x4E, 0x47]);
  });
  it('DXF: Rückimport und Warnung für Bilder', () => {
    const dxf = exportDxf(doc, 0);
    const r = parseDxf(new TextEncoder().encode(dxf));
    expect(r.polys.length).toBe(2);
    const b = boundsOf(r.polys)!;
    expect(b.maxX - b.minX).toBeCloseTo(110, 3); expect(b.maxY - b.minY).toBeCloseTo(30, 3);
    expect(isClosed(r.polys[0])).toBe(true);
    expect(dxf).toContain('AC1009');
    const withImage = { ...doc, elements: [newElement(layers[0].id, 'Bild', { raster: rasterOf(1, 1, new Uint8Array([0])), imageWidthMm: 1, imageHeightMm: 1 })] };
    expect(exportWarnings(withImage, 0, 'dxf')[0]).toMatch(/DXF kennt keine Bilder/);
  });
});
