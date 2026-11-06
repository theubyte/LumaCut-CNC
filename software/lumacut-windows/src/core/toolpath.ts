/** Port von Toolpath.kt: Marlin-2.1-Lasersemantik, Zeitschätzung gleich wie Android. */
import { hypot } from './geometry';
import { Bed, type Box, type Pt } from './model';

export interface Segment { x0: number; y0: number; x1: number; y1: number; power: number; cut: boolean; line: number }
export interface ToolpathStats { cutMm: number; travelMm: number; seconds: number; maxPower: number; warnings: string[] }
export interface Toolpath { segments: Segment[]; bounds: Box | null; stats: ToolpathStats; lineCount: number }
/**
 * Kompakt für große Aufträge und zum Übertragen aus dem Worker: xy = x0,y0,x1,y1 je Segment
 * (32-Bit wie Android), power 0 = Leerfahrt (cut === power > 0), line = Zeile im G-Code, ab 1.
 */
export interface CompactToolpath { count: number; xy: Float32Array; power: Uint8Array; line: Uint32Array; bounds: Box | null; stats: ToolpathStats; lineCount: number }

const TRAVEL_FEED = 9000, ACCEL = 1000, ARC_MM = 0.5;
const CODE_A = 65, CODE_Z = 90;
const X = 23, Y = 24, F = 5, S = 18, I = 8, J = 9;
const isDigit = (c: number) => c >= 48 && c <= 57;
const isWs = (c: number) => c === 32 || (c >= 9 && c <= 13);

function arc(x0: number, y0: number, x1: number, y1: number, i: number, j: number, cw: boolean): Pt[] {
  const cx = x0 + i, cy = y0 + j, r = hypot(i, j);
  const a0 = Math.atan2(y0 - cy, x0 - cx);
  let a1 = Math.atan2(y1 - cy, x1 - cx);
  if (cw) { if (a1 >= a0) a1 -= 2 * Math.PI; } else if (a1 <= a0) a1 += 2 * Math.PI;
  const n = Math.max(2, Math.ceil(Math.abs(a1 - a0) * r / ARC_MM));
  const out: Pt[] = [];
  for (let k = 1; k <= n; k++) {
    if (k === n) out.push({ x: x1, y: y1 });
    else { const a = a0 + (a1 - a0) * k / n; out.push({ x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) }); }
  }
  return out;
}

export function parseToolpathCompact(text: string): CompactToolpath {
  const lines = text.split(/\r\n|\n|\r/);
  let cap = 1024, count = 0;
  let xy = new Float32Array(cap * 4), powers = new Uint8Array(cap), lineNo = new Uint32Array(cap);
  let x = 0, y = 0, absolute = true, scale = 1, feed = 1000, power = 0, armed = false;
  let cutMm = 0, travelMm = 0, seconds = 0, maxPower = 0, unpowered = 0, dirX = 0, dirY = 0;
  let bMinX = Infinity, bMinY = Infinity, bMaxX = -Infinity, bMaxY = -Infinity;
  const w = new Float64Array(26);
  const has = new Uint8Array(26);

  const step = (px: number, py: number, qx: number, qy: number, cut: boolean, speed: number, lineIndex: number) => {
    const len = hypot(qx - px, qy - py);
    if (!(len > 0)) return;
    if (count === cap) {
      cap *= 2;
      const a = new Float32Array(cap * 4); a.set(xy); xy = a;
      const b = new Uint8Array(cap); b.set(powers); powers = b;
      const l = new Uint32Array(cap); l.set(lineNo); lineNo = l;
    }
    const o = count * 4;
    xy[o] = px; xy[o + 1] = py; xy[o + 2] = qx; xy[o + 3] = qy;
    powers[count] = cut ? power : 0;
    lineNo[count] = lineIndex + 1;
    count++;
    if (cut) {
      cutMm += len;
      if (power > maxPower) maxPower = power;
      const loX = px < qx ? px : qx, hiX = px > qx ? px : qx, loY = py < qy ? py : qy, hiY = py > qy ? py : qy;
      if (loX < bMinX) bMinX = loX;
      if (hiX > bMaxX) bMaxX = hiX;
      if (loY < bMinY) bMinY = loY;
      if (hiY > bMaxY) bMaxY = hiY;
    } else travelMm += len;
    seconds += len / Math.max(speed, 1) * 60;
    const ux = (qx - px) / len, uy = (qy - py) / len;
    if (ux * dirX + uy * dirY < 0.5) seconds += speed / 60 / ACCEL;
    dirX = ux; dirY = uy;
  };

  for (let index = 0; index < lines.length; index++) {
    let line = lines[index];
    if (line.indexOf('(') >= 0) line = line.replace(/\([^)]*\)/g, '');
    const semi = line.indexOf(';');
    if (semi >= 0) line = line.slice(0, semi);
    line = line.trim();
    if (line.length === 0) continue;
    line = line.toUpperCase();
    if (line.startsWith('M3') && /\bI\b/.test(line)) { armed = true; continue; }
    if (line.startsWith('M5')) { armed = false; power = 0; continue; }
    has.fill(0);
    let motion = -1;
    const n = line.length;
    for (let i = 0; i < n;) {
      const c = line.charCodeAt(i);
      if (c < CODE_A || c > CODE_Z) { i++; continue; }
      let p = i + 1;
      while (p < n && isWs(line.charCodeAt(p))) p++;
      const numStart = p;
      let d = line.charCodeAt(p);
      if (d === 43 || d === 45) { p++; d = line.charCodeAt(p); }
      let ok = false;
      if (isDigit(d)) {
        while (p < n && isDigit(line.charCodeAt(p))) p++;
        if (line.charCodeAt(p) === 46) { p++; while (p < n && isDigit(line.charCodeAt(p))) p++; }
        ok = true;
      } else if (d === 46 && isDigit(line.charCodeAt(p + 1))) {
        p++;
        while (p < n && isDigit(line.charCodeAt(p))) p++;
        ok = true;
      }
      if (!ok) { i++; continue; }
      const value = Number(line.slice(numStart, p));
      if (c === 71) {
        const g = Math.trunc(value);
        if (g === 20) scale = 25.4;
        else if (g === 21) scale = 1;
        else if (g === 90) absolute = true;
        else if (g === 91) absolute = false;
        else if (motion < 0 && g >= 0 && g <= 3) motion = g;
      } else if (c !== 77) { w[c - CODE_A] = value; has[c - CODE_A] = 1; }
      i = p;
    }
    if (motion < 0) continue;
    if (has[F]) feed = w[F] * scale;
    const nx = has[X] ? (absolute ? w[X] * scale : x + w[X] * scale) : x;
    const ny = has[Y] ? (absolute ? w[Y] * scale : y + w[Y] * scale) : y;
    const rapid = motion === 0;
    if (rapid) power = 0;
    else if (has[S]) power = Math.min(255, Math.max(0, Math.trunc(w[S])));
    else if (armed && power === 0) unpowered++;
    const cut = !rapid && armed && power > 0;
    const speed = rapid && !has[F] ? TRAVEL_FEED : feed;
    if ((motion === 2 || motion === 3) && (has[I] || has[J])) {
      let px = x, py = y;
      for (const q of arc(x, y, nx, ny, (has[I] ? w[I] : 0) * scale, (has[J] ? w[J] : 0) * scale, motion === 2)) {
        step(px, py, q.x, q.y, cut, speed, index); px = q.x; py = q.y;
      }
    } else step(x, y, nx, ny, cut, speed, index);
    x = nx; y = ny;
  }
  const warnings: string[] = [];
  if (unpowered > 0) warnings.push(`${unpowered} Laserfahrten nach Leerfahrt ohne S-Wert: Marlin lasert dort mit 0`);
  const bounds: Box | null = bMinX === Infinity ? null : { minX: bMinX, minY: bMinY, maxX: bMaxX, maxY: bMaxY };
  if (!bounds) warnings.push('Keine Laserbewegung gefunden');
  else if (bounds.minX < 0 || bounds.minY < 0 || bounds.maxX > Bed.width || bounds.maxY > Bed.height || (bounds.minX < Bed.parkX && bounds.minY < Bed.parkY))
    warnings.push('Motiv berührt die Park-Ecke oder liegt außerhalb der Arbeitsfläche');
  return {
    count, xy: xy.slice(0, count * 4), power: powers.slice(0, count), line: lineNo.slice(0, count), bounds,
    stats: { cutMm, travelMm, seconds, maxPower, warnings }, lineCount: lines.length,
  };
}

export function expandToolpath(t: CompactToolpath): Toolpath {
  const segments: Segment[] = new Array(t.count);
  for (let i = 0; i < t.count; i++) {
    const o = i * 4;
    segments[i] = { x0: t.xy[o], y0: t.xy[o + 1], x1: t.xy[o + 2], y1: t.xy[o + 3], power: t.power[i], cut: t.power[i] > 0, line: t.line[i] };
  }
  return { segments, bounds: t.bounds, stats: t.stats, lineCount: t.lineCount };
}
export const parseToolpath = (text: string): Toolpath => expandToolpath(parseToolpathCompact(text));

/** Geschätzte Restzeit, wenn die Maschine bei Zeile `line` von lineCount ist. */
export const remainingSeconds = (tp: { stats: ToolpathStats; lineCount: number }, line: number) =>
  tp.lineCount <= 0 ? 0 : tp.stats.seconds * Math.min(1, Math.max(0, 1 - line / tp.lineCount));

export const formatDuration = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h > 0 ? `${h} h ${String(m).padStart(2, '0')} min` : m > 0 ? `${m} min ${String(r).padStart(2, '0')} s` : `${r} s`;
};
