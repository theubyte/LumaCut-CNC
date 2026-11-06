import { describe, expect, it, vi } from 'vitest';
import { parse } from 'opentype.js';
import { boundsOf, isClosed } from './model';

vi.mock('@/platform', () => ({ listSystemFonts: async () => [], readSystemFont: async () => new ArrayBuffer(0) }));
const { layoutText } = await import('./text');
const { readFileSync } = await import('node:fs' as string) as { readFileSync(p: string): Uint8Array };
const font = () => { const b = readFileSync('public/fonts/LiberationSans-Regular.ttf'); return parse(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer); };

describe('text', () => {
  it('outlines start at the origin and scale with the em size', () => {
    const a = layoutText(font(), 'LumaCut', 10), b = layoutText(font(), 'LumaCut', 20);
    const ba = boundsOf(a)!, bb = boundsOf(b)!;
    expect(ba.minX).toBeCloseTo(0); expect(ba.minY).toBeCloseTo(0);
    expect(bb.maxX / ba.maxX).toBeCloseTo(2, 1);
    expect(a.every((p) => isClosed(p))).toBe(true);
  });
  it('a second line grows the height', () => {
    expect(boundsOf(layoutText(font(), 'A\nB', 10))!.maxY).toBeGreaterThan(boundsOf(layoutText(font(), 'A', 10))!.maxY * 1.8);
  });
  it('empty text has no paths', () => { expect(layoutText(font(), ' \n ', 10)).toEqual([]); });
});
