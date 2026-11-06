import { finishDrawables, type RawDrawable } from './svg';
import { applyM, cubicPoints, IDENTITY_M, mat, type Matrix, mul, type Poly, type Pt } from './geom';
import { ImportError, type VectorImport } from './types';

/**
 * PDF through pdf.js: the path operators of the first page become vectors (mm, y down), colours become
 * layers as in SVG. Text and pictures inside the PDF cannot be taken over as vectors and are reported.
 * Without any path the page comes back rendered, so the caller can place it as a picture with a warning.
 */
const PT_MM = 25.4 / 72;
const CURVE_MM = 0.2;

export interface PdfResult { vector: VectorImport | null; pages: number; texts: number; images: number; widthMm: number; heightMm: number; render(pxPerMm: number): Promise<{ data: Uint8ClampedArray; width: number; height: number } | null> }

/* pdf.js types are wide; only the parts used here are named. */
interface PdfjsModule {
  getDocument(src: unknown): { promise: Promise<PdfDoc>; destroy?(): void };
  OPS: Record<string, number>;
  GlobalWorkerOptions: { workerSrc: string };
}
interface PdfPage {
  getViewport(o: { scale: number }): { width: number; height: number; transform: number[] };
  getOperatorList(): Promise<{ fnArray: number[]; argsArray: unknown[][] }>;
  render(o: unknown): { promise: Promise<void> };
  cleanup(): void;
}
interface PdfDoc { numPages: number; getPage(n: number): Promise<PdfPage>; destroy(): Promise<void> }

async function loadPdfjs(): Promise<PdfjsModule> {
  if (typeof document === 'undefined') return await import('pdfjs-dist/legacy/build/pdf.mjs') as unknown as PdfjsModule;
  const lib = await import('pdfjs-dist') as unknown as PdfjsModule;
  const worker = await import('pdfjs-dist/build/pdf.worker.min.mjs?url');
  lib.GlobalWorkerOptions.workerSrc = worker.default;
  return lib;
}

const hex2 = (v: number) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0');
/** pdf.js hands colours as "#rrggbb" or as three numbers, depending on the version. */
function toColour(args: unknown[]): string | null {
  const a = args[0];
  if (typeof a === 'string') return /^#[0-9a-f]{6}$/i.test(a) ? a.toLowerCase() : null;
  if (args.length >= 3 && args.slice(0, 3).every((v) => typeof v === 'number')) return '#' + (args.slice(0, 3) as number[]).map(hex2).join('');
  return null;
}

export async function parsePdf(bytes: Uint8Array): Promise<PdfResult> {
  const pdfjs = await loadPdfjs();
  let doc: PdfDoc;
  try {
    doc = await pdfjs.getDocument({ data: bytes.slice(), isEvalSupported: false, useSystemFonts: false, verbosity: 0 }).promise;
  } catch { throw new ImportError('Das PDF lässt sich nicht lesen (verschlüsselt oder beschädigt). Als Bild oder SVG exportieren.'); }
  if (doc.numPages < 1) throw new ImportError('Das PDF hat keine Seite.');
  const page = await doc.getPage(1);
  const vp = page.getViewport({ scale: 1 });
  const base: Matrix = mat(...(vp.transform as [number, number, number, number, number, number]));
  const list = await page.getOperatorList();
  const O = pdfjs.OPS;
  const raw: RawDrawable[] = [];
  let ctm: Matrix = IDENTITY_M, fill: string | null = '#000000', stroke: string | null = '#000000';
  const stack: { ctm: Matrix; fill: string | null; stroke: string | null }[] = [];
  let texts = 0, images = 0;
  const textOps = new Set([O.showText, O.showSpacedText, O.nextLineShowText, O.nextLineSetSpacingShowText]);
  const imageOps = new Set([O.paintImageXObject, O.paintInlineImageXObject, O.paintImageMaskXObject, O.paintImageXObjectRepeat, O.paintImageMaskXObjectRepeat, O.paintSolidColorImageMask, O.paintInlineImageXObjectGroup, O.paintImageMaskXObjectGroup]);
  const strokeOps = new Set([O.stroke, O.closeStroke, O.fillStroke, O.eoFillStroke, O.closeFillStroke, O.closeEOFillStroke]);
  const fillOps = new Set([O.fill, O.eoFill, O.fillStroke, O.eoFillStroke, O.closeFillStroke, O.closeEOFillStroke]);
  const toMm = (p: Pt) => { const q = applyM(mul(base, ctm), p); return { x: q.x * PT_MM, y: q.y * PT_MM }; };

  const addPath = (paint: number, data: ArrayLike<number>) => {
    const closeAll = paint === O.closeStroke || paint === O.closeFillStroke || paint === O.closeEOFillStroke;
    const polys = flatten(data, toMm, closeAll);
    if (!polys.length) return;
    const stroked = strokeOps.has(paint), filled = !stroked && fillOps.has(paint);
    if (!stroked && !filled) return; // endPath: a clipping path draws nothing
    raw.push({ polys, colour: stroked ? stroke : fill, fill: filled, groups: [], name: null });
  };

  for (let i = 0; i < list.fnArray.length; i++) {
    const fn = list.fnArray[i], args = list.argsArray[i] ?? [];
    if (fn === O.save) stack.push({ ctm, fill, stroke });
    else if (fn === O.restore) { const s = stack.pop(); if (s) ({ ctm, fill, stroke } = s); }
    else if (fn === O.transform) ctm = mul(ctm, mat(...(args as [number, number, number, number, number, number])));
    else if (fn === O.paintFormXObjectBegin) {
      stack.push({ ctm, fill, stroke });
      const m = args[0];
      if (Array.isArray(m) || ArrayBuffer.isView(m)) { const v = m as unknown as number[]; if (v.length === 6) ctm = mul(ctm, mat(v[0], v[1], v[2], v[3], v[4], v[5])); }
    }
    else if (fn === O.paintFormXObjectEnd) { const s = stack.pop(); if (s) ({ ctm, fill, stroke } = s); }
    else if (fn === O.setFillRGBColor) fill = toColour(args);
    else if (fn === O.setStrokeRGBColor) stroke = toColour(args);
    else if (fn === O.constructPath) {
      // Since pdf.js 5: [paintOp, [Float32Array of DrawOPS], minMax]
      const paint = args[0] as number, data = (args[1] as unknown[] | undefined)?.[0];
      if (data && typeof (data as ArrayLike<number>).length === 'number') addPath(paint, data as ArrayLike<number>);
    }
    else if (textOps.has(fn)) texts++;
    else if (imageOps.has(fn)) images++;
  }

  let vector: VectorImport | null = null;
  if (raw.length) {
    const { items, layers } = finishDrawables(raw);
    vector = { polys: raw.flatMap((r) => r.polys), images: [], skipped: [], items, layers };
  }
  return {
    vector, pages: doc.numPages, texts, images, widthMm: vp.width * PT_MM, heightMm: vp.height * PT_MM,
    async render(pxPerMm) {
      if (typeof document === 'undefined') return null;
      const scale = pxPerMm * PT_MM;
      const v = page.getViewport({ scale });
      const canvas = document.createElement('canvas');
      canvas.width = Math.ceil(v.width); canvas.height = Math.ceil(v.height);
      const ctx = canvas.getContext('2d', { willReadFrequently: true })!;
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
      await page.render({ canvas, canvasContext: ctx, viewport: v }).promise;
      const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
      return { data: img.data, width: img.width, height: img.height };
    },
  };
}

/** Parses the DrawOPS of pdf.js: moveTo 0, lineTo 1, curveTo 2, quadraticCurveTo 3, closePath 4. */
export function flatten(d: ArrayLike<number>, map: (p: Pt) => Pt, closeAll: boolean): Poly[] {
  const out: Poly[] = [];
  let cur: Pt[] = [], start: Pt | null = null;
  const flush = (close: boolean) => {
    if (close && cur.length >= 2 && start) cur.push(start);
    if (cur.length >= 2) out.push(cur);
    cur = [];
  };
  for (let i = 0; i < d.length;) {
    switch (d[i++]) {
      case 0: flush(false); start = map({ x: d[i++], y: d[i++] }); cur = [start]; break;
      case 1: cur.push(map({ x: d[i++], y: d[i++] })); break;
      case 2: {
        const c1 = map({ x: d[i++], y: d[i++] }), c2 = map({ x: d[i++], y: d[i++] }), p = map({ x: d[i++], y: d[i++] });
        cur.push(...cubicPoints(cur[cur.length - 1] ?? c1, c1, c2, p, CURVE_MM));
        break;
      }
      case 3: {
        const c = map({ x: d[i++], y: d[i++] }), p = map({ x: d[i++], y: d[i++] }), p0 = cur[cur.length - 1] ?? c;
        cur.push(...cubicPoints(p0, { x: p0.x + (c.x - p0.x) * 2 / 3, y: p0.y + (c.y - p0.y) * 2 / 3 }, { x: p.x + (c.x - p.x) * 2 / 3, y: p.y + (c.y - p.y) * 2 / 3 }, p, CURVE_MM));
        break;
      }
      case 4: {
        flush(true);
        if (start) cur = [start];
        break;
      }
      default: return out;
    }
  }
  if (closeAll) flush(true); else flush(false);
  return out.filter((p) => p.length >= 2);
}
