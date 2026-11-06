import { ImportError } from './types';

/** Minimal ZIP reader (stored and deflate) over the central directory, with size limits against oversized archives. */
const MAX_ENTRY = 40 * 1024 * 1024;
const MAX_TOTAL = 4 * MAX_ENTRY;
export const isZip = (b: Uint8Array) => b.length >= 22 && b[0] === 0x50 && b[1] === 0x4B;

interface Entry { name: string; method: number; compressed: number; size: number; offset: number }

function directory(b: Uint8Array): Entry[] {
  const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  let eocd = -1;
  for (let i = b.length - 22; i >= 0 && i >= b.length - 22 - 65535; i--) if (dv.getUint32(i, true) === 0x06054B50) { eocd = i; break; }
  if (eocd < 0) throw new Error('Kein ZIP');
  const count = dv.getUint16(eocd + 10, true);
  let p = dv.getUint32(eocd + 16, true);
  const out: Entry[] = [];
  const dec = new TextDecoder('utf-8');
  for (let k = 0; k < count; k++) {
    if (p + 46 > b.length || dv.getUint32(p, true) !== 0x02014B50) throw new Error('Kein ZIP');
    const nameLen = dv.getUint16(p + 28, true), extra = dv.getUint16(p + 30, true), comment = dv.getUint16(p + 32, true);
    out.push({ name: dec.decode(b.subarray(p + 46, p + 46 + nameLen)), method: dv.getUint16(p + 10, true), compressed: dv.getUint32(p + 20, true), size: dv.getUint32(p + 24, true), offset: dv.getUint32(p + 42, true) });
    p += 46 + nameLen + extra + comment;
  }
  return out;
}

export const zipNames = (b: Uint8Array) => directory(b).map((e) => e.name);

async function inflate(data: Uint8Array, limit: number): Promise<Uint8Array> {
  const stream = new Blob([data as BlobPart]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  const reader = stream.getReader();
  const parts: Uint8Array[] = []; let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.length;
    if (total > limit) { await reader.cancel(); throw new ImportError('Die Datei ist zu groß'); }
    parts.push(value);
  }
  const out = new Uint8Array(total); let at = 0;
  for (const part of parts) { out.set(part, at); at += part.length; }
  return out;
}

export async function readZip(b: Uint8Array): Promise<Map<string, Uint8Array>> {
  const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  const out = new Map<string, Uint8Array>();
  let total = 0;
  for (const e of directory(b)) {
    if (e.name.endsWith('/')) continue;
    const nameLen = dv.getUint16(e.offset + 26, true), extra = dv.getUint16(e.offset + 28, true);
    const start = e.offset + 30 + nameLen + extra;
    const raw = b.subarray(start, start + e.compressed);
    let data: Uint8Array;
    if (e.method === 0) data = raw;
    else if (e.method === 8) data = await inflate(raw, MAX_ENTRY);
    else throw new Error('Unbekannte Kompression');
    if (data.length > MAX_ENTRY) throw new ImportError('Die Datei ist zu groß');
    total += data.length;
    if (total > MAX_TOTAL) throw new ImportError('Die Datei ist zu groß');
    out.set(e.name, data);
  }
  return out;
}
