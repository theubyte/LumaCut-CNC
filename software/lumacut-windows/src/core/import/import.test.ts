import { describe, expect, it } from 'vitest';
import { boundsOf, defaultLayers, isClosed, type Layer, type Poly } from '../model';
import { parseDxf } from './dxf';
import { detectKind, parseHpgl, parseLbrn } from './formats';
import { readDpi, rasterFromRgba, scaleRgba } from './image';
import { importFile, type ImportContext, ImportError, parseVector } from './index';
import { arrange, shelf, shrinkFactor, spread, unitsOf } from './layout';
import { colour, parseSvg, pathData, svgTransform } from './svg';
import { skippedSentence, vectorImport, type ImportItem, type VectorImport } from './types';
import { parseXml, XmlError } from './xml';
import { isXs, parseXcs, parseXs } from './xtool';
import { applyM, Shapes } from './geom';
import { flatten, parsePdf } from './pdf';

const enc = (s: string) => new TextEncoder().encode(s);
const box = (polys: Poly[]) => { const b = boundsOf(polys)!; return [b.minX, b.minY, b.maxX, b.maxY].map((v) => +v.toFixed(6)); };
const kind = (s: string) => detectKind(enc(s), isXs);
const b64 = (n: number, v?: number) => btoa(String.fromCharCode(...Array.from({ length: n }, (_, i) => v ?? i)));

/** ZIP writer (stored) for the test files. */
function zip(files: [string, string][]): Uint8Array {
  const parts: Uint8Array[] = [], central: Uint8Array[] = [];
  let offset = 0;
  for (const [name, content] of files) {
    const n = enc(name), c = enc(content);
    const local = new Uint8Array(30 + n.length), dv = new DataView(local.buffer);
    dv.setUint32(0, 0x04034B50, true); dv.setUint16(4, 20, true); dv.setUint32(18, c.length, true); dv.setUint32(22, c.length, true); dv.setUint16(26, n.length, true);
    local.set(n, 30);
    const cd = new Uint8Array(46 + n.length), cv = new DataView(cd.buffer);
    cv.setUint32(0, 0x02014B50, true); cv.setUint32(20, c.length, true); cv.setUint32(24, c.length, true); cv.setUint16(28, n.length, true); cv.setUint32(42, offset, true);
    cd.set(n, 46);
    parts.push(local, c); central.push(cd);
    offset += local.length + c.length;
  }
  const size = central.reduce((s, c) => s + c.length, 0);
  const end = new Uint8Array(22), ev = new DataView(end.buffer);
  ev.setUint32(0, 0x06054B50, true); ev.setUint16(8, files.length, true); ev.setUint16(10, files.length, true); ev.setUint32(12, size, true); ev.setUint32(16, offset, true);
  const all = [...parts, ...central, end];
  const out = new Uint8Array(all.reduce((s, p) => s + p.length, 0));
  let at = 0;
  for (const p of all) { out.set(p, at); at += p.length; }
  return out;
}

function ctx(): ImportContext {
  const layers = defaultLayers();
  return { layerByName: (n) => layers.find((l) => l.name === n)!, activeLayer: layers[0] };
}

describe('Xml', () => {
  it('liest Attribute, Entitäten, CDATA und überspringt DOCTYPE', () => {
    const n = parseXml(`<?xml version="1.0"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "x.dtd" [<!ENTITY a "b">]><a x="1&amp;2" y='3'><!-- k --><b>t&#228;<![CDATA[<z>]]></b><c/></a>`);
    expect(n.tag).toBe('a'); expect(n.attrs.x).toBe('1&2'); expect(n.attrs.y).toBe('3');
    expect(n.children.map((c) => c.tag)).toEqual(['b', 'c']); expect(n.children[0].text).toBe('tä<z>');
  });
  it('lehnt Kaputtes ab und expandiert keine eigenen Entitäten', () => {
    expect(() => parseXml('<a><b></a>')).toThrow(XmlError);
    expect(() => parseXml('kein xml')).toThrow(XmlError);
    expect(parseXml('<!DOCTYPE a [<!ENTITY x "boom">]><a v="&x;"/>').attrs.v).toBe('&x;');
  });
});

describe('Dateityp', () => {
  it('wird am Inhalt erkannt', () => {
    expect(kind('<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>')).toBe('SVG');
    expect(kind('<?xml version="1.0" encoding="UTF-8"?><LightBurnProject AppVersion="1.4"></LightBurnProject>')).toBe('LBRN');
    expect(kind('{"canvas":[{"id":"1","displays":[]}],"device":{}}')).toBe('XCS');
    expect(kind('{"title":"Neues Projekt","layers":[],"elements":[]}')).toBe('PROJECT');
    expect(kind('0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n')).toBe('DXF');
    expect(kind('  0\r\nSECTION\r\n  2\r\nHEADER\r\n')).toBe('DXF');
    expect(kind('IN;SP1;PU0,0;PD400,0;')).toBe('HPGL');
    expect(kind('%PDF-1.5\n1 0 obj')).toBe('PDF');
    expect(detectKind(new Uint8Array([0x89, 0x50, 0x4E, 0x47, 13, 10]), isXs)).toBe('IMAGE');
    expect(detectKind(new Uint8Array([0xFF, 0xD8, 0xFF, 0xE0, 0, 0]), isXs)).toBe('IMAGE');
    expect(kind('RIFF\0\0\0\0WEBPVP8 ')).toBe('IMAGE');
    expect(kind('das ist nur Text ohne Format')).toBe('UNKNOWN');
  });
});

describe('HPGL', () => {
  it('nutzt 40 Einheiten je mm und zeigt nach unten', () => {
    const polys = parseHpgl(enc('IN;SP1;PU0,0;PD400,0,400,800,0,800,0,0;PU;'));
    expect(polys.length).toBe(1);
    expect(box(polys)).toEqual([0, 0, 10, 20]);
    expect(isClosed(polys[0])).toBe(true);
    expect(parseHpgl(enc('IN;PU0,0;PD40,0;PU80,0;PD120,0;')).length).toBe(2);
    expect(() => parseHpgl(enc('IN;SP1;'))).toThrow(ImportError);
  });
});

describe('LightBurn', () => {
  it('Rect, Ellipse, Pfad mit Bézier, Gruppe, XForm', () => {
    const r = parseLbrn(enc(`<?xml version="1.0" encoding="UTF-8"?>
      <LightBurnProject AppVersion="1.4.00" FormatVersion="1">
        <CutSetting type="Cut"><index Value="0"/></CutSetting>
        <Shape Type="Rect" CutIndex="0" W="40" H="20" Cr="0"><XForm>1 0 0 1 100 50</XForm></Shape>
        <Shape Type="Ellipse" CutIndex="0" Rx="10" Ry="10"><XForm>1 0 0 1 200 50</XForm></Shape>
        <Shape Type="Path" CutIndex="0"><XForm>1 0 0 1 0 0</XForm>
          <VertList>V0 0c0x0c0y0c1x0c1y10V10 10c0x0c0y10c1x10c1y10</VertList>
          <PrimList>B0 1L1 0</PrimList></Shape>
        <Shape Type="Group"><XForm>1 0 0 1 10 0</XForm><Children>
          <Shape Type="Rect" W="10" H="10"><XForm>1 0 0 1 5 5</XForm></Shape></Children></Shape>
        <Shape Type="Text" CutIndex="0"><XForm>1 0 0 1 0 0</XForm></Shape>
      </LightBurnProject>`));
    expect(r.polys.length).toBe(4);
    expect(box([r.polys[0]])).toEqual([80, 40, 120, 60]);
    const c = boundsOf([r.polys[1]])!;
    expect(c.maxX - c.minX).toBeCloseTo(20, 2); expect((c.minX + c.maxX) / 2).toBeCloseTo(200, 2);
    expect(box([r.polys[2]]).slice(0, 1)).toEqual([0]); expect(boundsOf([r.polys[2]])!.maxX).toBeCloseTo(10, 6);
    expect(r.polys[2].length).toBeGreaterThan(5);
    expect(box([r.polys[3]])).toEqual([10, 0, 20, 10]);
    expect(skippedSentence(r)).toBe('Übersprungen: 1× Text (in Pfade bzw. Bild umwandeln)');
  });
  it('Bitmap wird eingebettetes Bild', () => {
    const r = parseLbrn(enc(`<LightBurnProject><Shape Type="Bitmap" W="30" H="20" Data="${b64(40)}"><XForm>1 0 0 1 50 40</XForm></Shape>
      <Shape Type="Rect" W="1" H="1"><XForm>1 0 0 1 0 0</XForm></Shape></LightBurnProject>`));
    expect(r.images.length).toBe(1);
    expect(r.images[0].box).toEqual({ minX: 35, minY: 30, maxX: 65, maxY: 50 });
    expect(r.images[0].bytes.length).toBe(40);
  });
  it('.lbrn2: LineClosed und Text mit gespeichertem Umriss', () => {
    const r = parseLbrn(enc(`<LightBurnProject AppVersion="1.7" FormatVersion="1">
      <Shape Type="Path"><XForm>1 0 0 1 0 0</XForm><VertList>V0 0V10 0V10 10</VertList><PrimList>LineClosed</PrimList></Shape>
      <Shape Type="Text" Str="Hi"><XForm>1 0 0 1 20 0</XForm><BackupPath Type="Path"><VertList>V0 0V5 0V5 5</VertList><PrimList>LineClosed</PrimList></BackupPath></Shape>
    </LightBurnProject>`));
    expect(r.polys.length).toBe(2);
    expect(isClosed(r.polys[0])).toBe(true);
    expect(box([r.polys[1]])).toEqual([20, 0, 25, 5]);
    expect(r.notes).toEqual(['Text in Pfade umgewandelt (1)']);
  });
  it('sagt ehrlich, wenn nur Text drin ist', () => {
    expect(() => parseLbrn(enc('<LightBurnProject><Shape Type="Text"/></LightBurnProject>'))).toThrow(/Nur Text gefunden/);
    expect(() => parseLbrn(enc('<foo/>'))).toThrow(ImportError);
  });
});

describe('xTool', () => {
  const project = '{"activeCanvasId":"c1","modules":{"canvases":["c1"]}}';
  const canvas = '{"id":"c1","layerData":{"#fe0002":{"name":"#FE0002","order":1,"visible":true},"#000000":{"name":"#000000","order":2,"visible":true}}}';
  const display = (o: { x: number; y: number; d: string; skewX?: number; localSkewX?: number; layer?: string; fill?: boolean; groups?: string; scale?: string }) =>
    `{"id":"a","type":"PATH","x":${o.x},"y":${o.y},"angle":0,"scale":${o.scale ?? '{"x":1,"y":1}'},"skew":{"x":${o.skewX ?? 0},"y":0},"localSkew":{"x":${o.localSkewX ?? 0},"y":0},
      "layerTag":"${o.layer ?? '#000000'}","groupTags":${o.groups ?? '[]'},"fill":{"visible":${o.fill ?? false}},"stroke":{"visible":true},"dPath":"${o.d}"}`;
  const xs = (...d: string[]) => zip([['.format', 'v2'], ['project.json', project], ['canvases/c1.json', canvas], ['canvases/c1/displays-0.json', `{"displays":[${d.join(',')}]}`]]);
  const near = (p: Poly, x: number, y: number) => p.some((q) => Math.abs(q.x - x) < 1e-3 && Math.abs(q.y - y) < 1e-3);

  it('.xs: Typ erkannt, x y ist oben links', async () => {
    const bytes = xs(display({ x: 100, y: 50, d: 'M 5 5 L 25 5 L 25 15 L 5 15 Z', layer: '#fe0002', groups: '["g1"]' }));
    expect(detectKind(bytes, isXs)).toBe('XS');
    const r = await parseVector('XS', bytes);
    expect(r.items.length).toBe(1);
    expect(box(r.polys)).toEqual([100, 50, 120, 60]);
    expect(r.items[0].layerKey).toBe('#fe0002'); expect(r.items[0].groups).toEqual(['g1']);
    expect(r.layers.map((l) => l.name)).toEqual(['#FE0002']);
  });
  it('skew π mit localSkew π heben sich auf, y ist die Unterkante', async () => {
    const pi = 3.141593;
    const polys = (await parseXs(xs(display({ x: 200, y: 100, d: 'M 0 0 L 10 0 L 10 1 L 0 4', skewX: pi, localSkewX: pi, scale: '{"x":2,"y":3}' })))).polys;
    const b = boundsOf(polys)!;
    expect(b.maxX - b.minX).toBeCloseTo(20, 3); expect(b.maxY - b.minY).toBeCloseTo(12, 3);
    expect(b.minX).toBeCloseTo(200, 3); expect(b.minY).toBeCloseTo(88, 3); expect(b.maxY).toBeCloseTo(100, 3);
    expect(near(polys[0], 220, 88)).toBe(true); expect(near(polys[0], 220, 91)).toBe(true); expect(near(polys[0], 200, 100)).toBe(true);
  });
  it('Spiegelung, mehrere Blöcke, Ausgeblendetes und Unbekanntes', async () => {
    const one = (await parseXs(xs(display({ x: 10, y: 10, d: 'M 0 0 L 10 0 L 10 2 L 0 6', localSkewX: 3.141593 })))).polys;
    expect(box(one).map((v) => +v.toFixed(2))).toEqual([10, 10, 20, 16]);
    expect(near(one[0], 20, 14)).toBe(true);
    const r = await parseXs(zip([['project.json', project], ['canvases/c1.json', canvas],
      ['canvases/c1/displays-0.json', `{"displays":[${display({ x: 0, y: 0, d: 'M 0 0 L 5 0' })}]}`],
      ['canvases/c1/displays-1.json', `{"displays":[${display({ x: 30, y: 0, d: 'M 0 0 L 5 0', fill: true })},{"id":"t","type":"TEXT","x":0,"y":0,"width":20,"height":5,"text":"Hallo"},{"id":"h","type":"PATH","visible":false,"x":0,"y":0,"dPath":"M 0 0 L 9 9"}]}`]]));
    expect(r.items.length).toBe(2); expect(r.items.map((i) => i.fill)).toEqual([false, true]);
    expect(r.skipped).toEqual(['1× Text']);
  });
  it('Rechteck, Kreis, Bild; kaputte Dateien werden abgelehnt', async () => {
    const r = await parseXs(xs('{"id":"r","type":"RECT","x":10,"y":20,"width":30,"height":10,"layerTag":"#000000","fill":{"visible":false}}',
      '{"id":"c","type":"CIRCLE","x":60,"y":20,"width":8,"height":8,"layerTag":"#000000"}',
      `{"id":"b","type":"BITMAP","x":0,"y":50,"width":15,"height":12,"base64":"data:image/png;base64,${b64(80, 3)}"}`));
    expect(r.items.length).toBe(2); expect(r.images.length).toBe(1);
    expect(box([r.items[0].polys[0]])).toEqual([10, 20, 40, 30]);
    expect(r.images[0].box).toEqual({ minX: 0, minY: 50, maxX: 15, maxY: 62 });
    expect(detectKind(zip([['readme.txt', 'hallo']]), isXs)).toBe('UNKNOWN');
    await expect(parseXs(zip([['readme.txt', 'hallo']]))).rejects.toThrow(ImportError);
    await expect(parseXs(zip([['project.json', project], ['canvases/c1.json', canvas]]))).rejects.toThrow(ImportError);
  });
  it('.xcs: gleiche Platzierung, Text übersprungen', () => {
    const r = parseXcs(enc(`{"canvas":[{"id":"c1","displays":[
      {"id":"a","type":"PATH","x":10,"y":10,"graphicX":10,"graphicY":10,"width":20,"height":10,"dPath":"M0 0L20 0L20 10L0 10Z"},
      {"id":"b","type":"RECT","x":50,"y":10,"width":10,"height":5},
      {"id":"c","type":"CIRCLE","x":70,"y":10,"width":8,"height":8},
      {"id":"d","type":"BITMAP","x":0,"y":30,"width":15,"height":15,"base64":"data:image/png;base64,${b64(64, 7)}"},
      {"id":"e","type":"TEXT","x":0,"y":0,"width":30,"height":10,"text":"Hallo"}]}],"device":{}}`));
    expect(r.polys.length).toBe(3);
    expect(box([r.polys[0]])).toEqual([10, 10, 30, 20]);
    expect(box([r.polys[1]])).toEqual([50, 10, 60, 15]);
    expect(r.images[0].box).toEqual({ minX: 0, minY: 30, maxX: 15, maxY: 45 });
    expect(r.skipped).toEqual(['1× Text']);
    expect(() => parseXcs(enc('{"canvas":[{"displays":[{"type":"TEXT","width":3,"height":3}]}]}'))).toThrow(ImportError);
    expect(() => parseXcs(enc('kein json'))).toThrow(ImportError);
  });
});

describe('SVG', () => {
  const svg = (body: string) => enc(`<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">${body}</svg>`);
  const parse = (body: string) => parseSvg(svg(body));
  const square = '<rect x="10" y="10" width="10" height="10" ', other = '<rect x="40" y="10" width="10" height="10" ';

  it('zwei Farben werden Ebenen, Strich ist Linie, Fläche ist Füllung', () => {
    const r = parse(`${square} stroke="#ff0000" fill="none"/>${other} fill="#0000ff"/>`);
    expect(r.items.map((i) => i.layerKey)).toEqual(['#ff0000', '#0000ff']);
    expect(r.items.map((i) => i.fill)).toEqual([false, true]);
    expect(r.layers.map((l) => l.name)).toEqual(['Rot', 'Blau']);
  });
  it('eine Farbe bleibt auf der gewählten Ebene', () => {
    const r = parse(`${square} fill="#000"/>${other} fill="black"/>`);
    expect(r.items.every((i) => i.layerKey == null)).toBe(true); expect(r.layers).toEqual([]);
  });
  it('gleiche Farbe als Linie und Füllung wird unterschieden', () => {
    const r = parse(`${square} stroke="black" fill="none"/>${other} fill="black"/>`);
    expect(r.items.map((i) => i.fill)).toEqual([false, true]);
    expect(new Set(r.items.map((i) => i.layerKey))).toEqual(new Set(['#000000']));
  });
  it('Farben aus style, CSS-Klasse und Elterngruppe', () => {
    const r = parse(`<style>.a{fill:#00ff00} .b,.c{stroke:rgb(255,0,0);fill:none}</style>
      ${square} class="a"/>${other} class="c"/><g fill="#0000ff"><circle cx="70" cy="70" r="5"/></g>
      <rect x="1" y="50" width="5" height="5" style="fill:#abc"/>`);
    expect(r.items.map((i) => i.layerKey)).toEqual(['#00ff00', '#ff0000', '#0000ff', '#aabbcc']);
  });
  it('Rahmen um andere Formen bleibt eigenes Teil', () => {
    expect(parse(`<rect x="0" y="0" width="90" height="90" fill="none" stroke="#000"/>${square} fill="none" stroke="#000"/>`).items.length).toBe(2);
  });
  it('ein Buchstabe behält sein Loch', () => {
    const r = parse('<path d="M0 0H20V20H0Z M5 5H15V15H5Z" fill="#000"/>');
    expect(r.items.length).toBe(1); expect(r.items[0].polys.length).toBe(2);
  });
  it('Gruppe um alles entfällt, innere Gruppen bleiben', () => {
    const g = parse(`<g><g>${square}/>${other}/></g><g><rect x="70" y="70" width="5" height="5"/></g></g>`).items.map((i) => i.groups[0]);
    expect(g[0]).toBe(g[1]); expect(g[0]).not.toBe(g[2]);
  });
  it('ohne Gruppe wird der Import eine Gruppe', () => {
    expect([...new Set(parse(`${square}/>${other}/>`).items.flatMap((i) => i.groups))]).toEqual(['*']);
  });
  it('Weiß startet ausgeblendet', () => {
    const r = parse(`<rect width="100" height="100" fill="#fff"/>${square} stroke="#000" fill="none"/>`);
    expect(r.layers.find((l) => l.key === '#ffffff')!.visible).toBe(false);
    expect(r.layers.find((l) => l.key === '#000000')!.visible).toBe(true);
  });
  it('Ausgelassenes wird gemeldet, Verstecktes nicht', () => {
    expect(parse(`${square}/><text x="0" y="0">Hallo</text><use href="#a"/><image href="bild.png" width="5" height="5"/>`).skipped).toEqual(['Text (1)', 'verlinkte Bilder (1)', 'Klone (1)']);
    expect(parse(`${square}/><rect width="5" height="5" style="display:none"/><rect width="5" height="5" visibility="hidden"/>`).items.length).toBe(1);
  });
  it('eingebettetes Bild kommt mit seinem Rahmen', () => {
    const r = parse(`${square}/><image x="10" y="20" width="30" height="40" href="data:image/png;base64,${b64(20)}"/>`);
    expect(r.images[0].box).toEqual({ minX: 10, minY: 20, maxX: 40, maxY: 60 });
  });
  it('Farbwerte und Verläufe', () => {
    expect(colour('url(#g)', '#000000')).toBeNull();
    expect(colour('rgb(16, 32, 48)', null)).toBe('#102030');
    expect(colour('none', null)).toBe('none');
  });
  it('Einheiten, viewBox und Transformationen ergeben mm', () => {
    const r = parseSvg(enc('<svg xmlns="http://www.w3.org/2000/svg" width="10cm" viewBox="10 10 200 100"><rect x="10" y="10" width="200" height="100" fill="none" stroke="#000"/></svg>'));
    expect(box(r.polys)).toEqual([0, 0, 100, 50]);
    const p96 = parseSvg(enc('<svg xmlns="http://www.w3.org/2000/svg"><line x1="0" y1="0" x2="96" y2="0" stroke="#000"/></svg>'));
    expect(boundsOf(p96.polys)!.maxX).toBeCloseTo(25.4, 6);
    const q = applyM(svgTransform('translate(10 20) rotate(90) scale(2)'), { x: 1, y: 0 });
    expect(q.x).toBeCloseTo(10, 6); expect(q.y).toBeCloseTo(22, 6);
  });
  it('alle Pfadbefehle, auch Bögen mit zusammengeschriebenen Flags', () => {
    const p = pathData('M0 0 L10 0 H20 V10 C20 20 10 20 10 10 S0 0 0 10 Q5 15 10 10 T20 10 a5 5 0 01 10 0 Z');
    expect(p.length).toBe(1); expect(isClosed(p[0])).toBe(true);
    const arc = pathData('M0 0 A10 10 0 0 1 20 0')[0];
    expect(boundsOf([arc])!.minY).toBeCloseTo(-10, 1);
    expect(() => pathData('10 10')).toThrow(ImportError);
  });
  it('DOCTYPE stört nicht, kaputtes SVG ergibt einen Satz', () => {
    expect(parseSvg(enc('<?xml version="1.0"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd"><svg xmlns="http://www.w3.org/2000/svg" width="1mm" height="1mm" viewBox="0 0 1 1"><rect width="1" height="1"/></svg>')).items.length).toBe(1);
    expect(() => parseSvg(enc('<svg><rect></svg>'))).toThrow('SVG konnte nicht gelesen werden');
    expect(() => parseSvg(enc('<svg xmlns="x"><text>nur</text></svg>'))).toThrow(/Keine Vektoren/);
  });
});

describe('DXF', () => {
  const dxf = (entities: string, header = '') => enc(`0\nSECTION\n2\nHEADER\n${header}0\nENDSEC\n0\nSECTION\n2\nENTITIES\n${entities}0\nENDSEC\n0\nEOF\n`);
  it('LINE, CIRCLE, Y zeigt nach unten', () => {
    const r = parseDxf(dxf('0\nLINE\n10\n0\n20\n0\n11\n10\n21\n20\n0\nCIRCLE\n10\n50\n20\n50\n40\n5\n'));
    expect(r.polys.length).toBe(2);
    expect(r.polys[0][0].y).toBeGreaterThan(r.polys[0][1].y);
    expect(boundsOf(r.polys)!.minY).toBeCloseTo(0, 6);
  });
  it('LWPOLYLINE geschlossen und mit Bogen, Einheiten aus dem Kopf', () => {
    const r = parseDxf(dxf('0\nLWPOLYLINE\n90\n4\n70\n1\n10\n0\n20\n0\n10\n1\n20\n0\n10\n1\n20\n1\n10\n0\n20\n1\n', '9\n$INSUNITS\n70\n1\n'));
    expect(isClosed(r.polys[0])).toBe(true);
    expect(boundsOf(r.polys)!.maxX).toBeCloseTo(25.4, 6);
    const bulge = parseDxf(dxf('0\nLWPOLYLINE\n90\n2\n70\n0\n10\n0\n20\n0\n42\n1\n10\n10\n20\n0\n'));
    const b = boundsOf(bulge.polys)!;
    expect(b.maxY - b.minY).toBeCloseTo(5, 1);
  });
  it('Blöcke, POLYLINE, ARC, ELLIPSE, SPLINE; Text wird gemeldet', () => {
    const blocks = '0\nSECTION\n2\nBLOCKS\n0\nBLOCK\n2\nB1\n0\nLINE\n10\n0\n20\n0\n11\n5\n21\n0\n0\nENDBLK\n0\nENDSEC\n';
    const r = parseDxf(enc(`${blocks}0\nSECTION\n2\nENTITIES\n0\nINSERT\n2\nB1\n10\n100\n20\n0\n41\n2\n42\n2\n0\nPOLYLINE\n70\n0\n0\nVERTEX\n10\n0\n20\n0\n0\nVERTEX\n10\n5\n20\n5\n0\nSEQEND\n0\nARC\n10\n0\n20\n0\n40\n3\n50\n0\n51\n90\n0\nELLIPSE\n10\n20\n20\n20\n11\n5\n21\n0\n40\n0.5\n0\nSPLINE\n71\n3\n40\n0\n40\n0\n40\n0\n40\n0\n40\n1\n40\n1\n40\n1\n40\n1\n10\n0\n20\n0\n10\n1\n20\n1\n10\n2\n20\n1\n10\n3\n20\n0\n0\nTEXT\n1\nHallo\n0\nMTEXT\n1\nDu\n0\nENDSEC\n0\nEOF\n`));
    expect(r.polys.length).toBe(5);
    expect(r.skipped).toEqual(['2× Text']);
  });
  it('Fehler sind Sätze', () => {
    expect(() => parseDxf(enc('AutoCAD Binary DXF\n'))).toThrow(/Binäres DXF/);
    expect(() => parseDxf(enc('kein\ndxf\n'))).toThrow(ImportError);
    expect(() => parseDxf(dxf('0\nTEXT\n1\nx\n'))).toThrow(/Keine unterstützten/);
  });
});

describe('Anordnung', () => {
  const rectItem = (x: number, y: number, w: number, h: number, group?: string): ImportItem =>
    ({ polys: [Shapes.rect(w, h).map((p) => ({ x: p.x + x, y: p.y + y }))], layerKey: null, fill: false, groups: group ? [group] : [], name: null });
  const result = (...items: ImportItem[]): VectorImport => vectorImport(items.flatMap((i) => i.polys), [], [], items);
  const W = 360, H = 340;
  it('klein: 1 zu 1, mittig', () => {
    const l = arrange(unitsOf(result(rectItem(0, 0, 100, 50))), W, H);
    expect(l.kind).toBe('AS_IS'); expect(l.offsets[0]).toEqual({ x: 130, y: 145 });
  });
  it('Gruppen, die zusammen nicht passen, in Reihen mit 5 mm', () => {
    const units = unitsOf(result(rectItem(0, 0, 170, 150, 'a'), rectItem(500, 0, 170, 150, 'b'), rectItem(0, 500, 170, 150, 'c')));
    expect(units.length).toBe(3);
    const l = arrange(units, W, H);
    expect(l.kind).toBe('PACKED');
    const placed = l.units.map((u, i) => ({ minX: u.box.minX + l.offsets[i]!.x, minY: u.box.minY + l.offsets[i]!.y, maxX: u.box.maxX + l.offsets[i]!.x, maxY: u.box.maxY + l.offsets[i]!.y }));
    expect(placed.every((b) => b.minX >= 0 && b.minY >= 0 && b.maxX <= W && b.maxY <= H)).toBe(true);
    expect(Math.max(...placed.map((b) => b.minY))).toBeCloseTo(156, 9);
  });
  it('Unplatzierbares wird gemeldet, Verkleinerung angeboten', () => {
    const units = unitsOf(result(rectItem(0, 0, 400, 100, 'a'), rectItem(0, 200, 100, 100, 'b')));
    const l = arrange(units, W, H);
    expect(l.kind).toBe('PARTIAL'); expect(l.offsets[0]).toBeNull(); expect(l.offsets[1]).not.toBeNull();
    expect(shrinkFactor(units, W, H)).toBeCloseTo((W - 10) / 400, 9);
  });
  it('eine große Gruppe fällt auf ihre Teile zurück; ohne Struktur eine Gruppe', () => {
    const l = arrange(unitsOf(result(rectItem(0, 0, 200, 200, 'g'), rectItem(300, 0, 100, 100, 'g'))), W, H);
    expect(l.units.length).toBe(2); expect(l.kind).toBe('PACKED');
    const u = unitsOf(vectorImport([Shapes.rect(10, 10), Shapes.rect(10, 10).map((p) => ({ x: p.x + 30, y: p.y }))]));
    expect(u.length).toBe(1); expect(u[0].items.length).toBe(2);
  });
  it('Verteilen auf mehrere Platten', () => {
    const units = unitsOf(result(...Array.from({ length: 6 }, (_, i) => rectItem(i * 300, 0, 170, 150, `g${i}`))));
    const s = spread(units, W, H);
    expect(s.plates.length).toBe(2); expect(s.leftOut).toBe(0);
    expect(s.plates.flatMap((p) => p.offsets.filter(Boolean)).length).toBe(6);
  });
  it('Park-Ecke wird vom Regal ausgespart', () => {
    const boxes = Array.from({ length: 5 }, () => ({ minX: 0, minY: 0, maxX: 80, maxY: 30 }));
    const keepOut = { minX: 292, minY: 0, maxX: 370, maxY: 35 };
    const p = shelf(boxes, 370, 360, 5, keepOut);
    for (const o of p) {
      const hit = o!.x + 80 > keepOut.minX && o!.y < keepOut.maxY;
      expect(hit).toBe(false);
    }
  });
});

describe('importFile', () => {
  it('SVG: Elemente mittig, neue Ebenen, Warnsatz', async () => {
    const r = await importFile('a.svg', enc('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100"><rect width="10" height="10" stroke="#f00" fill="none"/><rect x="20" width="10" height="10" fill="#00f"/><text>x</text></svg>'), ctx());
    expect(r.elements.length).toBe(2);
    expect(r.layers!.map((l: Layer) => l.name)).toEqual(['Rot', 'Blau (Füllen)']);
    expect(r.layers!.map((l) => l.mode)).toEqual(['LINE', 'FILL']);
    expect(r.elements[0].layerId).toBe(r.layers![0].id);
    expect(r.warnings[0]).toBe('Übersprungen: Text (1) (in Pfade bzw. Bild umwandeln)');
    expect(r.elements[0].groupId).toBe(r.elements[1].groupId);
    const b = r.elements.map((e) => e.transform);
    expect((b[0].x + b[1].x + 10) / 2).toBeCloseTo(185, 6);
  });
  it('zu groß und unteilbar: wird verkleinert und sagt es', async () => {
    const r = await importFile('g.dxf', enc('0\nSECTION\n2\nENTITIES\n0\nLINE\n10\n0\n20\n0\n11\n1000\n21\n0\n0\nENDSEC\n0\nEOF\n'), ctx());
    expect(r.warnings.join(' ')).toMatch(/verkleinert/);
    const b = boundsOf(r.elements[0].paths)!;
    expect(b.maxX).toBeLessThan(370);
  });
  it('Unbekanntes, Projekt und Leeres sind Sätze', async () => {
    await expect(importFile('x', enc('Hallo Welt, das ist Text'), ctx())).rejects.toThrow(/Format kenne ich nicht/);
    await expect(importFile('x', enc('{"title":"a","layers":[],"elements":[]}'), ctx())).rejects.toThrow(/LumaCut-Projekt/);
    await expect(importFile('x', new Uint8Array(0), ctx())).rejects.toThrow(ImportError);
  });
});

describe('PDF', () => {
  /** Minimal one-page PDF, built by hand, content stream as given. */
  function pdf(content: string, pages = 1): Uint8Array {
    const kids = Array.from({ length: pages }, (_, i) => `${3 + i} 0 R`).join(' ');
    const streamId = 3 + pages;
    const objs = [`<</Type/Catalog/Pages 2 0 R>>`, `<</Type/Pages/Kids[${kids}]/Count ${pages}>>`,
      ...Array.from({ length: pages }, () => `<</Type/Page/Parent 2 0 R/MediaBox[0 0 283.46 283.46]/Contents ${streamId} 0 R/Resources<<>>>>`),
      `<</Length ${content.length}>>\nstream\n${content}\nendstream`];
    let s = '%PDF-1.5\n'; const offs: number[] = [];
    objs.forEach((o, i) => { offs.push(s.length); s += `${i + 1} 0 obj\n${o}\nendobj\n`; });
    const xref = s.length;
    s += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map((o) => String(o).padStart(10, '0') + ' 00000 n \n').join('');
    s += `trailer\n<</Size ${objs.length + 1}/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF\n`;
    return enc(s);
  }
  it('Vektorpfade in mm, Y nach unten, Seitenzahl, Farben als Ebenen', async () => {
    const r = await parsePdf(pdf('1 0 0 RG 0 0 m 72 0 l S 0 0 1 rg 72 72 72 72 re f', 2));
    expect(r.pages).toBe(2);
    expect(r.widthMm).toBeCloseTo(100, 1);
    expect(r.vector).not.toBeNull();
    const v = r.vector!;
    expect(v.items.length).toBe(2);
    const line = boundsOf(v.items[0].polys)!;
    expect(line.maxX - line.minX).toBeCloseTo(25.4, 3);
    expect(line.minY).toBeCloseTo(100, 1);
    const rect = boundsOf(v.items[1].polys)!;
    expect(rect.maxX - rect.minX).toBeCloseTo(25.4, 3);
    expect(rect.maxY).toBeCloseTo(100 - 25.4, 1);
    expect(v.items[0].fill).toBe(false); expect(v.items[1].fill).toBe(true);
    expect(v.layers.map((l) => l.name)).toEqual(['Rot', 'Blau']);
  }, 30000);
  it('ohne Pfade kein Vektor', async () => {
    const r = await parsePdf(pdf('q Q'));
    expect(r.vector).toBeNull();
  }, 30000);
  it('kaputtes PDF ist ein Satz', async () => {
    await expect(parsePdf(enc('%PDF-1.5\nkaputt'))).rejects.toThrow(ImportError);
  }, 30000);
  it('flatten schließt und krümmt', () => {
    const p = flatten([0, 0, 0, 1, 10, 0, 2, 10, 5, 5, 10, 0, 10, 4], (q) => q, false);
    expect(p.length).toBe(1); expect(isClosed(p[0])).toBe(true); expect(p[0].length).toBeGreaterThan(4);
  });
});

describe('Bilder', () => {
  it('Transparenz gilt als Weiß, langes Maß wird begrenzt', () => {
    const r = rasterFromRgba({ data: new Uint8ClampedArray([0, 0, 0, 255, 0, 0, 0, 0]), width: 2, height: 1 });
    expect(r.width).toBe(2);
    const g = atob(r.grayBase64);
    expect(g.charCodeAt(0)).toBe(0); expect(g.charCodeAt(1)).toBe(255);
    const big = { data: new Uint8ClampedArray(3000 * 100 * 4).fill(255), width: 3000, height: 100 };
    const s = scaleRgba(big, 1000);
    expect(s.width).toBe(1000); expect(s.height).toBe(33);
  });
  it('DPI aus PNG und JPEG, 72/96 zählt nicht', () => {
    const png = (ppm: number) => {
      const b = new Uint8Array(8 + 12 + 9); b.set([0x89, 0x50, 0x4E, 0x47, 13, 10, 26, 10]);
      const dv = new DataView(b.buffer); dv.setUint32(8, 9); b.set([0x70, 0x48, 0x59, 0x73], 12); dv.setUint32(16, ppm); dv.setUint32(20, ppm); b[24] = 1;
      return b;
    };
    expect(readDpi(png(11811))).toBeCloseTo(300, 0);
    expect(readDpi(png(2835))).toBeNull();
    const jpg = new Uint8Array(24); jpg.set([0xFF, 0xD8, 0xFF, 0xE0, 0, 16, 0x4A, 0x46, 0x49, 0x46, 0, 1, 1, 1, 0x01, 0x2C, 0x01, 0x2C]);
    expect(readDpi(jpg)).toBe(300);
    expect(readDpi(new Uint8Array(20))).toBeNull();
  });
});
