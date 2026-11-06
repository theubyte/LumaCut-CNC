/**
 * Port von android/core MarlinWriter.kt. Die Ausgabe ist für dieselbe Eingabe bis aufs Zeichen gleich
 * (Prüfung: golden.test.ts gegen Dateien, die der Kotlin-Code erzeugt hat).
 * Eine M3-I-Klammer für den ganzen Auftrag, jedes G1 trägt F und S0..255. Maschinen-X = Breite - x.
 * Nichts verlässt die Arbeitsfläche, auch kein Auslauf ohne Laser; nichts reicht in die Park-Ecke.
 */
import { focusDropMm, powerShare } from './darkness';
import { fmt3, fmtFixed } from './fmt';
import { hatch, hypot, orderForCutting, polyClosed } from './geometry';
import { adjustGray, binarize, sampleGray } from './imageTools';
import { Bed, insideWork, isImage, Limits, touchesPark, worldBounds, worldPaths, type Doc, type Element, type Layer, type Poly } from './model';
import { grayOf } from './raster';

export class JobBuildError extends Error { override name = 'JobBuildError'; }
/** Beschleunigung (mm/s²) und Höchsttempo (mm/s): config.motion vom Pi, sonst Firmware. */
export interface Motion { accel: number; speed: number }
export const FIRMWARE_MOTION: Motion = { accel: 500, speed: 150 };
export const maxFeed = (m: Motion) => m.speed * 60;
/** Anlauf ohne Laser für Vorschub mm/min: Weg v²/2a plus 15 % und 0,3 mm. */
export const runUp = (m: Motion, feed: number) => { const v = feed / 60; return v * v / (2 * m.accel) * 1.15 + 0.3; };

const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v);
const inRange = (v: number, r: readonly [number, number]) => v >= r[0] && v <= r[1];

export function writeMarlin(doc: Doc, opts: { appVersion?: string; motion?: Motion } = {}): string {
  const appVersion = opts.appVersion ?? 'dev', motion = opts.motion ?? FIRMWARE_MOTION;
  const out: string[] = [];
  const W = Bed.width, H = Bed.height;
  let hasAt = false, atX = 0, atY = 0;
  let lastY = NaN, lastYStr = '';

  const s = (pct: number) => Math.round(clamp(pct, 0, 100) / 100 * 255);
  const feedOf = (l: Layer) => Math.round(clamp(l.speed, Limits.SPEED[0], Limits.SPEED[1]));
  const xy = (x: number, y: number) => {
    const my = clamp(y, 0, H);
    if (!Object.is(my, lastY)) { lastY = my; lastYStr = fmt3(my); }
    return 'X' + fmt3(W - clamp(x, 0, W)) + ' Y' + lastYStr;
  };
  const rapid = (x: number, y: number) => {
    if (!hasAt || hypot(x - atX, y - atY) > 1e-6) out.push('G0 ' + xy(x, y));
    hasAt = true; atX = x; atY = y;
  };
  const burn = (x: number, y: number, power: number, feed: number) => {
    out.push('G1 ' + xy(x, y) + ' F' + feed + ' S' + power);
    hasAt = true; atX = x; atY = y;
  };

  const lines = (paths: Poly[], layer: Layer) => {
    const power = s(layer.powerPct), feed = feedOf(layer);
    for (const path of orderForCutting(paths, hasAt ? { x: atX, y: atY } : { x: 0, y: 0 })) {
      rapid(path[0].x, path[0].y);
      for (let i = 1; i < path.length; i++) burn(path[i].x, path[i].y, power, feed);
    }
  };

  // Laufstücke als flaches Array: x0, x1, power je Stück.
  const scanLine = (y: number, runs: number[], layer: Layer) => {
    if (runs.length === 0) return;
    const n = runs.length, feed = feedOf(layer);
    const dir = runs[1] >= runs[0] ? 1 : -1;
    const over = Math.min(Math.max(clamp(layer.overscanMm, 0, 10), runUp(motion, feed)), 40);
    const start = clamp(runs[0] - dir * over, 0, W);
    const end = clamp(runs[n - 2] + dir * over, 0, W);
    rapid(start, y);
    if (start !== runs[0]) burn(runs[0], y, 0, feed);
    for (let k = 0; k < n; k += 3) {
      if (Math.abs(atX - runs[k]) > 1e-6) burn(runs[k], y, 0, feed);
      burn(runs[k + 1], y, runs[k + 2], feed);
    }
    if (end !== atX) burn(end, y, 0, feed);
  };

  const fill = (paths: Poly[], layer: Layer) => {
    const closed = paths.filter((p) => polyClosed(p));
    if (closed.length === 0) return;
    const power = s(layer.powerPct);
    for (const seg of hatch(closed, clamp(layer.intervalMm, 0.03, 2))) scanLine(seg[0].y, [seg[0].x, seg[seg.length - 1].x, power], layer);
  };

  const raster = (el: Element, layer: Layer) => {
    const r = el.raster, box = worldBounds(el);
    if (!r || !box) return;
    const gray = grayOf(r);
    const interval = clamp(layer.intervalMm, 0.03, 2);
    const bw = box.maxX - box.minX, bh = box.maxY - box.minY;
    const rows = Math.max(1, Math.trunc(bh / interval)), cols = Math.max(1, Math.trunc(bw / interval));
    const sampled = sampleGray(gray, r.width, r.height, cols, rows);
    const levels = binarize(adjustGray(sampled, cols, rows, el.adjust), cols, rows, el.imageMode);
    const maxS = s(layer.powerPct), minS = s(layer.minPowerPct);
    const power = new Int32Array(256);
    for (let g = 0; g < 256; g++) power[g] = g >= 250 ? 0 : Math.round(minS + (maxS - minS) * powerShare(layer, (255 - g) / 255));
    const cell = bw / cols;
    for (let row = 0; row < rows; row++) {
      const y = box.minY + (row + 0.5) * bh / rows;
      const o = row * cols;
      const runs: number[] = [];
      let first = -1, last = -1;
      for (let c = 0; c < cols;) {
        const level = levels[o + c];
        let e = c + 1;
        while (e < cols && levels[o + e] === level) e++;
        const p = power[level];
        if (p > 0) { if (first < 0) first = runs.length; last = runs.length; }
        runs.push(box.minX + c * cell, box.minX + e * cell, p);
        c = e;
      }
      if (first < 0) continue;
      if (row % 2 === 0) scanLine(y, runs.slice(first, last + 3), layer);
      else {
        const rev: number[] = [];
        for (let k = last; k >= first; k -= 3) rev.push(runs[k + 1], runs[k], runs[k + 2]);
        scanLine(y, rev, layer);
      }
    }
  };

  const active = new Set(doc.layers.filter((l) => l.output && l.visible).map((l) => l.id));
  const content = doc.elements.filter((e) => active.has(e.layerId));
  if (content.length === 0) throw new JobBuildError('Nichts zu lasern: keine Elemente auf sichtbaren Ebenen');
  for (const e of content) {
    const box = worldBounds(e);
    if (!box) continue;
    const name = e.text ?? e.kind;
    if (!insideWork(box)) throw new JobBuildError(`„${name}“ ragt über die Arbeitsfläche hinaus`);
    if (touchesPark(box)) throw new JobBuildError(`„${name}“ liegt in der Park-Ecke (oben rechts) – dort wird nicht gelasert`);
    if (isImage(e) && Math.abs(e.transform.rotation) > 1e-6) throw new JobBuildError('Gedrehte Bilder werden noch nicht unterstützt – Drehung auf 0° setzen');
  }
  const activeLayers = doc.layers.filter((l) => active.has(l.id));
  for (const l of activeLayers) {
    if (!inRange(l.powerPct, Limits.POWER) || !inRange(l.speed, Limits.SPEED) || !inRange(l.passes, Limits.PASSES))
      throw new JobBuildError(`Ungültige Werte auf Ebene „${l.name}“`);
    if (l.speed > maxFeed(motion) + 1e-6)
      throw new JobBuildError(`Ebene „${l.name}“: ${fmtFixed(l.speed, 0, ',')} mm/min – die Maschine fährt höchstens ${fmtFixed(maxFeed(motion), 0, ',')} mm/min (Maschine → Kalibrieren → Bewegung)`);
    if (!inRange(l.zStepMm, Limits.Z_STEP) || focusDropMm(l) > Limits.MAX_FOCUS_DROP_MM + 1e-6)
      throw new JobBuildError(`Fokus-Absenkung zu groß auf „${l.name}“ (${fmtFixed(focusDropMm(l), 2, ',')} mm > ${fmtFixed(Limits.MAX_FOCUS_DROP_MM, 0, ',')} mm)`);
  }
  out.push(`; LumaCut App ${appVersion} – ${doc.title.replace(/[\r\n]/g, ' ')}`);
  out.push('G21', 'G90', 'M5 I', 'M3 I');
  for (const layer of activeLayers) {
    const items = content.filter((e) => e.layerId === layer.id);
    if (items.length === 0) continue;
    out.push(`; Ebene ${layer.name}`);
    const images = items.filter(isImage);
    const vector = items.filter((e) => !isImage(e)).flatMap(worldPaths);
    for (let pass = 0; pass < layer.passes; pass++) {
      if (pass > 0 && layer.zStepMm > 0) out.push('G91', `G0 Z${fmt3(-layer.zStepMm)} F600`, 'G90');
      if (layer.passes > 1) out.push(`; Durchgang ${pass + 1}/${layer.passes}`);
      for (const image of images) raster(image, layer);
      if (layer.mode === 'LINE') lines(vector, layer); else fill(vector, layer);
    }
    if (layer.zStepMm > 0 && focusDropMm(layer) > 0) out.push('G91', `G0 Z${fmt3(focusDropMm(layer))} F600`, 'G90');
  }
  out.push('M5 I', 'M400', '');
  return out.join('\n');
}
