import type { Poly } from '../model';
import { GenError } from './types';

/** QR code (ISO 18004) in byte mode, level M, versions 1 to 10 (up to 213 bytes). Port of Qr.kt. */
const ECC_PER_BLOCK_M = [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26];
const BLOCKS_M = [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5];
export const QR_MAX_VERSION = 10;
/** Smallest module edge that still scans reliably when engraved. */
export const QR_MIN_MODULE_MM = 0.8;

function rawModules(ver: number) {
  let result = (16 * ver + 128) * ver + 64;
  if (ver >= 2) {
    const align = Math.trunc(ver / 7) + 2;
    result -= (25 * align - 10) * align - 55;
    if (ver >= 7) result -= 36;
  }
  return result;
}
const dataCodewords = (ver: number) => Math.trunc(rawModules(ver) / 8) - ECC_PER_BLOCK_M[ver] * BLOCKS_M[ver];
export const qrCapacity = (version: number) => Math.trunc((dataCodewords(version) * 8 - 4 - (version < 10 ? 8 : 16)) / 8);

function rsMul(x: number, y: number) {
  let z = 0;
  for (let i = 7; i >= 0; i--) { z = (z << 1) ^ ((z >>> 7) * 0x11D); z ^= ((y >>> i) & 1) * x; }
  return z;
}
export function rsDivisor(degree: number): number[] {
  const result = new Array<number>(degree).fill(0); result[degree - 1] = 1;
  let root = 1;
  for (let k = 0; k < degree; k++) {
    for (let j = 0; j < degree; j++) { result[j] = rsMul(result[j], root); if (j + 1 < degree) result[j] ^= result[j + 1]; }
    root = rsMul(root, 2);
  }
  return result;
}
export function rsRemainder(data: number[], divisor: number[]): number[] {
  const result = new Array<number>(divisor.length).fill(0);
  for (const b of data) {
    const factor = b ^ result[0];
    result.shift(); result.push(0);
    for (let i = 0; i < result.length; i++) result[i] ^= rsMul(divisor[i], factor);
  }
  return result;
}
function interleave(ver: number, data: number[]): number[] {
  const blocks = BLOCKS_M[ver], eccLen = ECC_PER_BLOCK_M[ver], raw = Math.trunc(rawModules(ver) / 8);
  const short = blocks - raw % blocks, shortLen = Math.trunc(raw / blocks);
  const divisor = rsDivisor(eccLen);
  const all: number[][] = [];
  let k = 0;
  for (let i = 0; i < blocks; i++) {
    const len = shortLen - eccLen + (i < short ? 0 : 1);
    const dat = data.slice(k, k + len); k += len;
    const ecc = rsRemainder(dat, divisor);
    all.push([...dat, ...(i < short ? [0] : []), ...ecc]);
  }
  const out: number[] = [];
  for (let i = 0; i < all[0].length; i++) for (let j = 0; j < blocks; j++) if (i !== shortLen - eccLen || j >= short) out.push(all[j][i]);
  return out;
}

export function maskBit(m: number, x: number, y: number): boolean {
  switch (m) {
    case 0: return (x + y) % 2 === 0;
    case 1: return y % 2 === 0;
    case 2: return x % 3 === 0;
    case 3: return (x + y) % 3 === 0;
    case 4: return (Math.trunc(x / 3) + Math.trunc(y / 2)) % 2 === 0;
    case 5: return x * y % 2 + x * y % 3 === 0;
    case 6: return (x * y % 2 + x * y % 3) % 2 === 0;
    default: return ((x + y) % 2 + x * y % 3) % 2 === 0;
  }
}

class Builder {
  size: number; modules: boolean[][]; isFunction: boolean[][]; ver: number;
  constructor(ver: number) {
    this.ver = ver;
    this.size = ver * 4 + 17;
    this.modules = Array.from({ length: this.size }, () => new Array<boolean>(this.size).fill(false));
    this.isFunction = Array.from({ length: this.size }, () => new Array<boolean>(this.size).fill(false));
  }
  private setFn(x: number, y: number, dark: boolean) { this.modules[y][x] = dark; this.isFunction[y][x] = true; }
  drawFunctionPatterns() {
    const s = this.size;
    for (let i = 0; i < s; i++) { this.setFn(6, i, i % 2 === 0); this.setFn(i, 6, i % 2 === 0); }
    this.finder(3, 3); this.finder(s - 4, 3); this.finder(3, s - 4);
    const pos = this.alignPositions(), n = pos.length;
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
      if ((i === 0 && j === 0) || (i === 0 && j === n - 1) || (i === n - 1 && j === 0)) continue;
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) this.setFn(pos[i] + dx, pos[j] + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }
    this.drawFormat(0);
    this.drawVersion();
  }
  private finder(x: number, y: number) {
    for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) {
      const d = Math.max(Math.abs(dx), Math.abs(dy)), xx = x + dx, yy = y + dy;
      if (xx >= 0 && xx < this.size && yy >= 0 && yy < this.size) this.setFn(xx, yy, d !== 2 && d !== 4);
    }
  }
  private alignPositions(): number[] {
    if (this.ver === 1) return [];
    const n = Math.trunc(this.ver / 7) + 2;
    const step = Math.trunc((this.ver * 4 + n * 2 + 1) / (n * 2 - 2)) * 2;
    const r = new Array<number>(n).fill(0); r[0] = 6;
    for (let i = 0; i < n - 1; i++) r[n - 1 - i] = this.size - 7 - i * step;
    return r;
  }
  /** Format bits for level M (00) and the mask. */
  drawFormat(mask: number) {
    const s = this.size, bit = (v: number, i: number) => ((v >>> i) & 1) !== 0;
    let rem = mask;
    for (let k = 0; k < 10; k++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    const bits = ((mask << 10) | rem) ^ 0x5412;
    for (let i = 0; i <= 5; i++) this.setFn(8, i, bit(bits, i));
    this.setFn(8, 7, bit(bits, 6)); this.setFn(8, 8, bit(bits, 7)); this.setFn(7, 8, bit(bits, 8));
    for (let i = 9; i <= 14; i++) this.setFn(14 - i, 8, bit(bits, i));
    for (let i = 0; i <= 7; i++) this.setFn(s - 1 - i, 8, bit(bits, i));
    for (let i = 8; i <= 14; i++) this.setFn(8, s - 15 + i, bit(bits, i));
    this.setFn(8, s - 8, true);
  }
  private drawVersion() {
    if (this.ver < 7) return;
    let rem = this.ver;
    for (let k = 0; k < 12; k++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1F25);
    const bits = (this.ver << 12) | rem;
    for (let i = 0; i <= 17; i++) {
      const c = ((bits >>> i) & 1) !== 0, a = this.size - 11 + i % 3, b = Math.trunc(i / 3);
      this.setFn(a, b, c); this.setFn(b, a, c);
    }
  }
  drawCodewords(data: number[]) {
    const s = this.size;
    let i = 0, right = s - 1;
    while (right >= 1) {
      if (right === 6) right = 5;
      for (let vert = 0; vert < s; vert++) for (let j = 0; j <= 1; j++) {
        const x = right - j, upward = ((right + 1) & 2) === 0, y = upward ? s - 1 - vert : vert;
        if (!this.isFunction[y][x] && i < data.length * 8) { this.modules[y][x] = ((data[i >>> 3] >>> (7 - (i & 7))) & 1) !== 0; i++; }
      }
      right -= 2;
    }
  }
  applyMask(m: number) {
    for (let y = 0; y < this.size; y++) for (let x = 0; x < this.size; x++) if (maskBit(m, x, y) && !this.isFunction[y][x]) this.modules[y][x] = !this.modules[y][x];
  }
  penalty(): number {
    const s = this.size, mod = this.modules;
    let result = 0;
    const P1 = [true, false, true, true, true, false, true, false, false, false, false];
    const P2 = [false, false, false, false, true, false, true, true, true, false, true];
    const line = (get: (i: number) => boolean) => {
      let run = 1;
      for (let i = 1; i < s; i++) {
        if (get(i) === get(i - 1)) { run++; if (run === 5) result += 3; else if (run > 5) result++; } else run = 1;
      }
      for (let a = 0; a <= s - 11; a++) {
        let m1 = true, m2 = true;
        for (let k = 0; k < 11; k++) { if (get(a + k) !== P1[k]) m1 = false; if (get(a + k) !== P2[k]) m2 = false; }
        if (m1 || m2) result += 40;
      }
    };
    for (let y = 0; y < s; y++) line((i) => mod[y][i]);
    for (let x = 0; x < s; x++) line((i) => mod[i][x]);
    for (let y = 0; y < s - 1; y++) for (let x = 0; x < s - 1; x++) {
      const c = mod[y][x];
      if (c === mod[y][x + 1] && c === mod[y + 1][x] && c === mod[y + 1][x + 1]) result += 3;
    }
    let dark = 0;
    for (const row of mod) for (const v of row) if (v) dark++;
    const total = s * s;
    const k = Math.trunc((Math.abs(dark * 20 - total * 10) + total - 1) / total) - 1;
    return result + k * 10;
  }
}

export interface QrCode { version: number; size: number; mask: number; modules: boolean[][] }
export function qrEncode(text: string): QrCode {
  const bytes = [...new TextEncoder().encode(text)];
  if (!bytes.length) throw new GenError('Kein Text für den QR-Code.');
  let version = 0;
  for (let v = 1; v <= QR_MAX_VERSION; v++) if (bytes.length <= qrCapacity(v)) { version = v; break; }
  if (!version) throw new GenError(`Der Text ist zu lang für den QR-Code (höchstens ${qrCapacity(QR_MAX_VERSION)} Zeichen).`);
  const cap = dataCodewords(version) * 8;
  const bits: number[] = [];
  const put = (value: number, n: number) => { for (let i = n - 1; i >= 0; i--) bits.push((value >>> i) & 1); };
  put(4, 4); put(bytes.length, version < 10 ? 8 : 16);
  for (const b of bytes) put(b, 8);
  put(0, Math.min(4, cap - bits.length));
  while (bits.length % 8) bits.push(0);
  let pad = 0xEC;
  while (bits.length < cap) { put(pad, 8); pad ^= 0xEC ^ 0x11; }
  const data: number[] = [];
  for (let i = 0; i < bits.length; i += 8) { let v = 0; for (let k = 0; k < 8; k++) v = (v << 1) | bits[i + k]; data.push(v); }
  const b = new Builder(version);
  b.drawFunctionPatterns();
  b.drawCodewords(interleave(version, data));
  let best = 0, bestPenalty = Infinity;
  for (let m = 0; m < 8; m++) {
    b.applyMask(m); b.drawFormat(m);
    const p = b.penalty();
    if (p < bestPenalty) { bestPenalty = p; best = m; }
    b.applyMask(m);
  }
  b.applyMask(best); b.drawFormat(best);
  return { version, size: b.size, mask: best, modules: b.modules };
}

/** Filled rectangles, one per horizontal run of dark modules, top-left corner at (0, 0). Quiet zone not included. */
export function qrPolys(q: QrCode, moduleMm: number): Poly[] {
  const out: Poly[] = [];
  for (let y = 0; y < q.size; y++) {
    let x = 0;
    while (x < q.size) {
      if (!q.modules[y][x]) { x++; continue; }
      let e = x;
      while (e < q.size && q.modules[y][e]) e++;
      out.push([{ x: x * moduleMm, y: y * moduleMm }, { x: e * moduleMm, y: y * moduleMm }, { x: e * moduleMm, y: (y + 1) * moduleMm }, { x: x * moduleMm, y: (y + 1) * moduleMm }, { x: x * moduleMm, y: y * moduleMm }]);
      x = e;
    }
  }
  return out;
}

export interface QrSpec { text: string; moduleMm: number; plate: boolean }
export function qrResult(s: QrSpec): import('./types').GenResult {
  const q = qrEncode(s.text);
  if (!(s.moduleMm >= 0.2 && s.moduleMm <= 10)) throw new GenError('Punktgröße: 0,2 bis 10 mm.');
  const size = q.size * s.moduleMm, n = (v: number) => String(+v.toFixed(1)).replace('.', ',');
  const notes = [`${q.size} × ${q.size} Punkte = ${n(size)} × ${n(size)} mm. Gelasert werden die dunklen Punkte.`];
  const warnings: string[] = [];
  if (s.moduleMm < QR_MIN_MODULE_MM) warnings.push(`Punkte unter ${n(QR_MIN_MODULE_MM)} mm lassen sich oft nicht mehr lesen. Größer wählen.`);
  const quiet = 4 * s.moduleMm;
  const parts: import('./types').GenPart[] = [{ name: 'QR-Code', layer: 'Gravieren', paths: qrPolys(q, s.moduleMm), group: s.plate ? 'qr' : undefined }];
  if (s.plate) {
    const t = size + 2 * quiet;
    parts.push({ name: 'QR Umriss', layer: 'Schneiden', group: 'qr', paths: [[{ x: -quiet, y: -quiet }, { x: t - quiet, y: -quiet }, { x: t - quiet, y: t - quiet }, { x: -quiet, y: t - quiet }, { x: -quiet, y: -quiet }]] });
    notes.push('Der Umriss lässt rundum vier Punkte hellen Rand.');
  } else notes.push('Beim Gravieren rundum einen hellen Rand von mindestens vier Punkten lassen.');
  return { parts, notes, warnings };
}
