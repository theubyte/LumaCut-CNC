import type { CompactToolpath } from '@/core/toolpath';

/**
 * Draws a toolpath into plain byte buffers instead of canvas paths, so half a million segments
 * stay fluid: the cost follows the pixels touched, and those are bounded by the screen, not by the
 * job. Lines are antialiased across the minor axis; overlapping lines keep the strongest value.
 */
export interface ViewXf { scale: number; ox: number; oy: number }
export interface Ink { cut: [number, number, number]; travel: [number, number, number] }
export interface PathOptions { showTravel: boolean; bedWidth: number }

export class PathRaster {
  private w = 0; private h = 0;
  private done = new Uint8Array(0); private pending = new Uint8Array(0); private travel = new Uint8Array(0);
  private canvas: OffscreenCanvas | null = null; private ctx: OffscreenCanvasRenderingContext2D | null = null;
  private image: ImageData | null = null; private pixels = new Uint32Array(0);

  private resize(w: number, h: number) {
    if (w === this.w && h === this.h && this.canvas) return;
    this.w = w; this.h = h;
    const n = w * h;
    this.done = new Uint8Array(n); this.pending = new Uint8Array(n); this.travel = new Uint8Array(n);
    this.canvas = new OffscreenCanvas(Math.max(1, w), Math.max(1, h));
    this.ctx = this.canvas.getContext('2d', { alpha: true });
    this.image = this.ctx!.createImageData(Math.max(1, w), Math.max(1, h));
    this.pixels = new Uint32Array(this.image.data.buffer);
  }

  /**
   * Segments before `upto` count as done (full tone), the rest as still to come (faint).
   * `xf` maps work mm to device pixels. Returns the bitmap to blit at 0/0.
   */
  render(tp: CompactToolpath, upto: number, xf: ViewXf, w: number, h: number, ink: Ink, o: PathOptions): OffscreenCanvas {
    this.resize(w, h);
    this.done.fill(0); this.pending.fill(0); this.travel.fill(0);
    const { xy, power, count } = tp;
    const { scale, ox, oy } = xf;
    const bw = o.bedWidth;
    let minX = w, minY = h, maxX = -1, maxY = -1;
    for (let i = 0; i < count; i++) {
      const p = power[i];
      if (p === 0 && !o.showTravel) continue;
      const k = i * 4;
      // Machine mm in the file; the work area on screen is mirrored in X.
      const x0 = (bw - xy[k]) * scale + ox, y0 = xy[k + 1] * scale + oy, x1 = (bw - xy[k + 2]) * scale + ox, y1 = xy[k + 3] * scale + oy;
      const lox = x0 < x1 ? x0 : x1, hix = x0 < x1 ? x1 : x0, loy = y0 < y1 ? y0 : y1, hiy = y0 < y1 ? y1 : y0;
      if (hix < 0 || lox >= w - 1 || hiy < 0 || loy >= h - 1) continue;
      if (lox < minX) minX = lox;
      if (hix > maxX) maxX = hix;
      if (loy < minY) minY = loy;
      if (hiy > maxY) maxY = hiy;
      if (p === 0) this.line(this.travel, x0, y0, x1, y1, 255);
      else this.line(i < upto ? this.done : this.pending, x0, y0, x1, y1, TONE[p]);
    }
    this.compose(minX, minY, maxX, maxY, ink);
    return this.canvas!;
  }

  private line(buf: Uint8Array, x0: number, y0: number, x1: number, y1: number, v: number) {
    const w = this.w, h = this.h;
    const dx = x1 - x0, dy = y1 - y0;
    if (Math.abs(dx) >= Math.abs(dy)) {
      const left = x0 < x1 ? x0 : x1, right = x0 < x1 ? x1 : x0;
      const a = dx === 0 ? 0 : dy / dx;
      const from = Math.max(0, Math.floor(left)), to = Math.min(w - 2, Math.floor(right));
      for (let x = from; x <= to; x++) {
        const y = y0 + (x + 0.5 - x0) * a - 0.5;
        const yi = Math.floor(y);
        if (yi < 0 || yi >= h - 1) continue;
        const f = y - yi, at = yi * w + x;
        const c0 = v * (1 - f) + 0.5 | 0, c1 = v * f + 0.5 | 0;
        if (buf[at] < c0) buf[at] = c0;
        if (buf[at + w] < c1) buf[at + w] = c1;
      }
    } else {
      const top = y0 < y1 ? y0 : y1, bottom = y0 < y1 ? y1 : y0;
      const a = dx / dy;
      const from = Math.max(0, Math.floor(top)), to = Math.min(h - 2, Math.floor(bottom));
      for (let y = from; y <= to; y++) {
        const x = x0 + (y + 0.5 - y0) * a - 0.5;
        const xi = Math.floor(x);
        if (xi < 0 || xi >= w - 1) continue;
        const f = x - xi, at = y * w + xi;
        const c0 = v * (1 - f) + 0.5 | 0, c1 = v * f + 0.5 | 0;
        if (buf[at] < c0) buf[at] = c0;
        if (buf[at + 1] < c1) buf[at + 1] = c1;
      }
    }
  }

  private compose(minX: number, minY: number, maxX: number, maxY: number, ink: Ink) {
    const w = this.w, h = this.h, px = this.pixels, done = this.done, pending = this.pending, travel = this.travel;
    px.fill(0);
    if (maxX >= minX && maxY >= minY) {
      const cut = (ink.cut[2] << 16) | (ink.cut[1] << 8) | ink.cut[0];
      const trv = (ink.travel[2] << 16) | (ink.travel[1] << 8) | ink.travel[0];
      const x0 = Math.max(0, Math.floor(minX) - 1), x1 = Math.min(w - 1, Math.ceil(maxX) + 1);
      const y0 = Math.max(0, Math.floor(minY) - 1), y1 = Math.min(h - 1, Math.ceil(maxY) + 1);
      for (let y = y0; y <= y1; y++) {
        const row = y * w;
        for (let i = row + x0, end = row + x1; i <= end; i++) {
          const d = done[i], p = pending[i], t = travel[i];
          if (d) px[i] = cut | (d << 24);
          else if (p) px[i] = cut | (((p * 0.3) | 0) << 24);
          else if (t) px[i] = trv | ((t * 0.34) << 24);
        }
      }
    }
    this.ctx!.putImageData(this.image!, 0, 0);
  }
}

/** S value to line strength: a faint power stays visible, full power reads as solid. Coverage then scales this value. */
const TONE = Uint8Array.from({ length: 256 }, (_, v) => Math.round(255 * (0.3 + 0.7 * Math.pow(v / 255, 0.75))));
