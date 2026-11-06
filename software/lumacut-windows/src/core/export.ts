import { applyT, Bed, type Doc, type Element, type Layer, layerCss, isClosed, plateElements, worldPaths } from './model';
import { grayOf } from './raster';

/** Export of one plate in mm. SVG keeps layers and pictures; DXF has lines only; PNG is a picture of the plate. */
const f = (v: number) => String(+v.toFixed(3));
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function visibleByLayer(doc: Doc, plate: number): { layer: Layer; elements: Element[] }[] {
  const els = plateElements(doc, plate);
  return doc.layers.filter((l) => l.visible).map((layer) => ({ layer, elements: els.filter((e) => e.layerId === layer.id) })).filter((g) => g.elements.length);
}

export function exportSvg(doc: Doc, plate: number = doc.activePlate): string {
  const out: string[] = ['<?xml version="1.0" encoding="UTF-8"?>',
    `<svg xmlns="http://www.w3.org/2000/svg" width="${f(Bed.width)}mm" height="${f(Bed.height)}mm" viewBox="0 0 ${f(Bed.width)} ${f(Bed.height)}">`,
    `<title>${esc(doc.title)}</title>`];
  for (const { layer, elements } of visibleByLayer(doc, plate)) {
    const c = layerCss(layer);
    const paint = layer.mode === 'FILL' ? `fill="${c}" fill-rule="evenodd" stroke="none"` : `fill="none" stroke="${c}" stroke-width="0.1"`;
    out.push(`<g data-name="${esc(layer.name)}" ${paint}>`);
    for (const e of elements) {
      if (e.raster) {
        const t = e.transform, r = t.rotation * Math.PI / 180;
        const matrix = [t.scaleX * Math.cos(r), t.scaleX * Math.sin(r), -t.scaleY * Math.sin(r), t.scaleY * Math.cos(r), t.x, t.y].map(f).join(' ');
        const png = encodeGrayPng(grayOf(e.raster), e.raster.width, e.raster.height);
        out.push(`<image transform="matrix(${matrix})" width="${f(e.imageWidthMm)}" height="${f(e.imageHeightMm)}" href="data:image/png;base64,${b64(png)}"/>`);
        continue;
      }
      const d = worldPaths(e).filter((p) => p.length >= 2).map((p) => {
        const closed = isClosed(p);
        const pts = closed ? p.slice(0, -1) : p;
        return 'M' + pts.map((q) => `${f(q.x)} ${f(q.y)}`).join('L') + (closed ? 'Z' : '');
      }).join('');
      if (d) out.push(`<path d="${d}"/>`);
    }
    out.push('</g>');
  }
  out.push('</svg>');
  return out.join('\n');
}

const ACI: [number, number, number, number][] = [[1, 255, 0, 0], [2, 255, 255, 0], [3, 0, 255, 0], [4, 0, 255, 255], [5, 0, 0, 255], [6, 255, 0, 255], [7, 0, 0, 0], [8, 128, 128, 128]];
function aciOf(argb: number) {
  const r = Math.floor(argb / 65536) % 256, g = Math.floor(argb / 256) % 256, b = argb % 256;
  let best = 7, bd = Infinity;
  for (const [i, x, y, z] of ACI) { const d = (r - x) ** 2 + (g - y) ** 2 + (b - z) ** 2; if (d < bd) { bd = d; best = i; } }
  return best;
}
const dxfName = (s: string) => s.replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/Ä/g, 'Ae').replace(/Ö/g, 'Oe').replace(/Ü/g, 'Ue').replace(/ß/g, 'ss').replace(/[^A-Za-z0-9_-]+/g, '_').slice(0, 31) || 'Ebene';

/** ASCII DXF (R12 entities, $INSUNITS = mm), Y pointing up as DXF expects. Pictures are left out, see `exportWarnings`. */
export function exportDxf(doc: Doc, plate: number = doc.activePlate): string {
  const groups = visibleByLayer(doc, plate);
  const o: (string | number)[] = [0, 'SECTION', 2, 'HEADER', 9, '$ACADVER', 1, 'AC1009', 9, '$INSUNITS', 70, 4, 0, 'ENDSEC'];
  o.push(0, 'SECTION', 2, 'TABLES', 0, 'TABLE', 2, 'LAYER', 70, groups.length);
  const names = new Map<string, string>();
  for (const { layer } of groups) {
    const base = dxfName(layer.name); let name = base, n = 2;
    while ([...names.values()].includes(name)) name = `${base}_${n++}`;
    names.set(layer.id, name);
    o.push(0, 'LAYER', 2, name, 70, 0, 62, aciOf(layer.color), 6, 'CONTINUOUS');
  }
  o.push(0, 'ENDTAB', 0, 'ENDSEC', 0, 'SECTION', 2, 'ENTITIES');
  for (const { layer, elements } of groups) for (const e of elements) for (const p of worldPaths(e)) {
    if (p.length < 2) continue;
    const closed = isClosed(p), pts = closed ? p.slice(0, -1) : p, name = names.get(layer.id)!;
    o.push(0, 'POLYLINE', 8, name, 66, 1, 70, closed ? 1 : 0);
    for (const q of pts) o.push(0, 'VERTEX', 8, name, 10, f(q.x), 20, f(Bed.height - q.y), 30, 0);
    o.push(0, 'SEQEND', 8, name);
  }
  o.push(0, 'ENDSEC', 0, 'EOF');
  let s = '';
  for (let i = 0; i < o.length; i += 2) s += `${o[i]}\n${o[i + 1]}\n`;
  return s;
}

/** Honest notes on what an export loses. */
export function exportWarnings(doc: Doc, plate: number = doc.activePlate, format: 'svg' | 'dxf' | 'png' = 'dxf'): string[] {
  const els = plateElements(doc, plate);
  const out: string[] = [];
  const pictures = els.filter((e) => e.raster).length;
  if (format === 'dxf' && pictures) out.push(`DXF kennt keine Bilder: ${pictures} ${pictures > 1 ? 'Bilder fehlen' : 'Bild fehlt'} in der Datei. Für Bilder SVG wählen.`);
  const hidden = els.filter((e) => !doc.layers.find((l) => l.id === e.layerId)?.visible).length;
  if (hidden) out.push(`${hidden} Elemente auf ausgeblendeten Ebenen wurden nicht exportiert.`);
  return out;
}

/** The plate as a picture, `pxPerMm` pixels per millimetre (browser only, uses a canvas). */
export async function exportPng(doc: Doc, plate: number = doc.activePlate, pxPerMm = 10): Promise<Uint8Array> {
  const canvas = new OffscreenCanvas(Math.ceil(Bed.width * pxPerMm), Math.ceil(Bed.height * pxPerMm));
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Kein Zeichenkontext');
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.scale(pxPerMm, pxPerMm);
  for (const { layer, elements } of visibleByLayer(doc, plate)) for (const e of elements) {
    if (e.raster) {
      const g = grayOf(e.raster), img = new ImageData(e.raster.width, e.raster.height);
      for (let i = 0; i < g.length; i++) { img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = g[i]; img.data[i * 4 + 3] = 255; }
      const bmp = await createImageBitmap(img);
      const a = applyT(e.transform, { x: 0, y: 0 });
      ctx.save(); ctx.translate(a.x, a.y); ctx.rotate(e.transform.rotation * Math.PI / 180);
      ctx.drawImage(bmp, 0, 0, e.imageWidthMm * e.transform.scaleX, e.imageHeightMm * e.transform.scaleY);
      ctx.restore(); bmp.close();
      continue;
    }
    const path = new Path2D();
    for (const p of worldPaths(e)) { p.forEach((q, i) => i ? path.lineTo(q.x, q.y) : path.moveTo(q.x, q.y)); if (isClosed(p)) path.closePath(); }
    if (layer.mode === 'FILL') { ctx.fillStyle = layerCss(layer); ctx.fill(path, 'evenodd'); }
    else { ctx.strokeStyle = layerCss(layer); ctx.lineWidth = Math.max(0.1, 1 / pxPerMm); ctx.stroke(path); }
  }
  const blob = await canvas.convertToBlob({ type: 'image/png' });
  return new Uint8Array(await blob.arrayBuffer());
}

/* ---- small PNG writer (stored deflate): gray pictures inside SVG, also without a browser ---- */
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xFFFFFFFF; for (let i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
export function encodeGrayPng(gray: Uint8Array, w: number, h: number): Uint8Array {
  const raw = new Uint8Array((w + 1) * h);
  for (let y = 0; y < h; y++) raw.set(gray.subarray(y * w, (y + 1) * w), y * (w + 1) + 1);
  let a = 1, b = 0;
  for (let i = 0; i < raw.length; i++) { a = (a + raw[i]) % 65521; b = (b + a) % 65521; }
  const blocks = Math.max(1, Math.ceil(raw.length / 65535));
  const z = new Uint8Array(2 + raw.length + blocks * 5 + 4);
  z[0] = 0x78; z[1] = 0x01;
  let at = 2;
  for (let i = 0; i < blocks; i++) {
    const start = i * 65535, len = Math.min(65535, raw.length - start);
    z[at++] = i === blocks - 1 ? 1 : 0; z[at++] = len & 255; z[at++] = len >> 8; z[at++] = ~len & 255; z[at++] = (~len >> 8) & 255;
    z.set(raw.subarray(start, start + len), at); at += len;
  }
  new DataView(z.buffer).setUint32(at, ((b << 16) | a) >>> 0);
  const chunk = (type: string, data: Uint8Array) => {
    const c = new Uint8Array(12 + data.length), dv = new DataView(c.buffer);
    dv.setUint32(0, data.length);
    for (let i = 0; i < 4; i++) c[4 + i] = type.charCodeAt(i);
    c.set(data, 8);
    dv.setUint32(8 + data.length, crc32(c.subarray(4, 8 + data.length)));
    return c;
  };
  const ihdr = new Uint8Array(13), dv = new DataView(ihdr.buffer);
  dv.setUint32(0, w); dv.setUint32(4, h); ihdr[8] = 8; ihdr[9] = 0;
  const parts = [new Uint8Array([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]), chunk('IHDR', ihdr), chunk('IDAT', z), chunk('IEND', new Uint8Array(0))];
  const out = new Uint8Array(parts.reduce((s, p) => s + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}
const b64 = (u: Uint8Array) => { let s = ''; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode(...u.subarray(i, i + 0x8000)); return btoa(s); };
