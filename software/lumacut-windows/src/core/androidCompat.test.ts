import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { fromJson, newDoc, newElement, toJson } from './model';
import { writeMarlin } from './gcode';

/**
 * Projektformat wie Android: android-doc.json hat der Kotlin-Code geschrieben (Document.toJson).
 * Die Gegenrichtung (diese App schreibt, Kotlin liest und erzeugt denselben G-Code) wird mit
 * COMPAT_OUT erzeugt und in einer Kopie von android/ geprüft, siehe golden/GoldenGen.kt.txt.
 */
function sample() {
  const d = newDoc('Kompatibel');
  const engrave = d.layers[0], line = d.layers[1], cut = d.layers[2];
  const square = [{ x: 0, y: 0 }, { x: 40, y: 0 }, { x: 40, y: 30 }, { x: 0, y: 30 }, { x: 0, y: 0 }];
  d.elements.push(newElement(cut.id, 'Rechteck', { paths: [square], transform: { x: 30, y: 60, scaleX: 1, scaleY: 1, rotation: 15 } }));
  d.elements.push(newElement(line.id, 'Pfad', { paths: [[{ x: 0, y: 0 }, { x: 10, y: 5 }]], transform: { x: 100, y: 100, scaleX: 2, scaleY: 1, rotation: 0 },
    curves: [{ closed: false, nodes: [{ x: 0, y: 0 }, { x: 10, y: 5, hx1: 2, hy1: 2 }] }] }));
  d.elements.push(newElement(engrave.id, 'Text', { paths: [square], text: 'Ä', fontSizeMm: 12, transform: { x: 100, y: 150, scaleX: 1, scaleY: 1, rotation: 0 } }));
  d.elements.push(newElement(engrave.id, 'Bild', { raster: { width: 2, height: 2, grayBase64: 'AICAAA==' }, imageWidthMm: 10, imageHeightMm: 10, imageMode: 'DITHER',
    transform: { x: 200, y: 200, scaleX: 1, scaleY: 1, rotation: 0 }, plate: 1 }));
  return { ...d, plateCount: 2, layers: d.layers.map((l, i) => i === 1 ? { ...l, process: 'Markieren' } : l) };
}

describe('Projektformat Android', () => {
  it('schreibt Beispiel für die Gegenprobe in Kotlin', () => {
    const out = process.env.COMPAT_OUT;
    if (!out) return;
    const d = sample();
    writeFileSync(`${out}/from-ts.json`, toJson(d));
    writeFileSync(`${out}/from-ts.gcode`, writeMarlin({ ...d, elements: d.elements.filter((e) => e.plate === 0) }, { appVersion: 'x' }));
  });
  it('liest eine von Kotlin geschriebene Datei und erhält unbekannte Felder', () => {
    const f = new URL('./golden/android-doc.json', import.meta.url);
    if (!existsSync(f)) throw new Error('android-doc.json fehlt');
    const text = readFileSync(f, 'utf8');
    const d = fromJson(text);
    expect(d.elements.length).toBeGreaterThan(0);
    expect(typeof d.layers[0].color).toBe('number');
    const again = fromJson(toJson(fromJson(JSON.stringify({ ...JSON.parse(text), zukunft: 1 }))));
    expect(again.zukunft).toBe(1);
    expect(writeMarlin({ ...d, elements: d.elements.filter((e) => e.plate === 0) }, { appVersion: 'x' })).toContain('G1 ');
  });
});
