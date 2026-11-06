import { describe, expect, it } from 'vitest';
// @ts-ignore no node types in the app's tsconfig
import { deflateRawSync } from 'node:zlib';
import { newDoc, normalize, isClosed, fromJson, toJson, worldBounds, type Box } from '@/core/model';
import { polysArea, pointInPolys } from './clipper';
import { evalMacroExpr, parseGerber } from './gerber';
import { parseExcellon } from './excellon';
import { classifyLayer } from './layers';
import { isZip, readZip } from './zip';
import { buildBoard, minClearance, readPcbFile, stitchLoops } from './board';
import { applyPlanToDoc, buildPlan, defaultSettings, designChecks, designFacts, estimateSeconds, fiducialPoints, lineInterval, START_VALUES, toJob } from './job';
import { BEISPIEL } from './fixtures';

const G = (body: string, fs = '%FSLAX46Y46*%\n%MOMM*%\n') => parseGerber(`${fs}${body}\nM02*\n`);
const near = (a: number, b: number, tol: number) => expect(Math.abs(a - b)).toBeLessThanOrEqual(tol);
const box = (b: Box | null) => { if (!b) throw new Error('keine Grenzen'); return b; };

describe('Gerber: Formate und Einheiten', () => {
  it('liest Millimeter im Format 4.6 und fuehrende Nullen', () => {
    const g = G('%ADD10C,1*%\nD10*\nX10000000Y-5000000D03*');
    near(box(g.bounds).minX, 9.5, 1e-3); near(box(g.bounds).maxY, -4.5, 1e-3);
  });
  it('rechnet Zoll in Millimeter um, auch Blenden', () => {
    const g = parseGerber('%FSLAX24Y24*%\n%MOIN*%\n%ADD10C,0.1*%\nD10*\nX10000Y0D03*\nM02*\n');
    expect(g.units).toBe('inch');
    near(box(g.bounds).minX, 25.4 - 1.27, 2e-3); near(g.area, Math.PI * 1.27 * 1.27, 0.02);
  });
  it('versteht weggelassene hintere Nullen (T) und inkrementell (I)', () => {
    const t = parseGerber('%FSTAX24Y24*%\n%MOMM*%\n%ADD10R,2X2*%\nD10*\nX1Y1D03*\nM02*\n');
    near(box(t.bounds).minX, 9, 1e-3); // "1" aufgefuellt zu 100000 = 10,0000
    const i = parseGerber('%FSLIX24Y24*%\n%MOMM*%\n%ADD10R,2X2*%\nD10*\nX100000Y0D03*\nX100000Y0D03*\nM02*\n');
    near(box(i.bounds).maxX, 21, 1e-3);
  });
});

describe('Gerber: Blenden', () => {
  it('Kreis, Rechteck, Langloch, Vieleck mit richtiger Flaeche', () => {
    near(G('%ADD10C,2*%\nD10*\nX0Y0D03*').area, Math.PI, 0.01);
    near(G('%ADD10R,3X2*%\nD10*\nX0Y0D03*').area, 6, 1e-6);
    near(G('%ADD10O,4X2*%\nD10*\nX0Y0D03*').area, 2 * 2 + Math.PI, 0.01);
    const hex = G('%ADD10P,2X6*%\nD10*\nX0Y0D03*'); near(hex.area, (3 * Math.sqrt(3)) / 2, 1e-3);
    near(box(hex.bounds).maxX, 1, 1e-3);
  });
  it('Blendenbohrung wird ausgespart', () => {
    near(G('%ADD10C,4X2*%\nD10*\nX0Y0D03*').area, Math.PI * (4 - 1), 0.02);
    near(G('%ADD10R,4X4X2*%\nD10*\nX0Y0D03*').area, 16 - Math.PI, 0.02);
  });
  it('Linie mit runder Blende: Flaeche und Breite', () => {
    const g = G('%ADD10C,0.5*%\nD10*\nX0Y0D02*\nX10000000Y0D01*');
    near(g.area, 10 * 0.5 + Math.PI * 0.25 * 0.25, 0.01);
    expect(g.minStrokeWidth).toBeCloseTo(0.5, 6);
    expect(g.strokes).toHaveLength(1);
  });
  it('Linie mit Rechteckblende ist die konvexe Huelle', () => {
    const g = G('%ADD10R,1X1*%\nD10*\nX0Y0D02*\nX5000000Y0D01*');
    near(g.area, 6, 1e-6);
  });
});

describe('Gerber: Boegen', () => {
  it('G75 Vollkreis, gegen den Uhrzeigersinn', () => {
    const g = G('G75*\n%ADD10C,0.2*%\nD10*\nX1000000Y0D02*\nG03*\nX1000000Y0I-1000000J0D01*');
    near(g.area, Math.PI * (1.1 * 1.1 - 0.9 * 0.9), 0.01);
    near(box(g.bounds).minX, -1.1, 1e-2);
  });
  it('G02 und G03 laufen in verschiedene Richtungen', () => {
    const ccw = G('G75*\n%ADD10C,0.1*%\nD10*\nX1000000Y0D02*\nG03*\nX-1000000Y0I-1000000J0D01*');
    const cw = G('G75*\n%ADD10C,0.1*%\nD10*\nX1000000Y0D02*\nG02*\nX-1000000Y0I-1000000J0D01*');
    near(box(ccw.bounds).maxY, 1.05, 0.01);
    near(box(cw.bounds).minY, -1.05, 0.01);
    near(box(cw.bounds).maxY, 0.05, 0.01);
  });
  it('G74: Viertelkreis mit Offsets ohne Vorzeichen', () => {
    const g = G('G74*\n%ADD10C,0.1*%\nD10*\nX1000000Y0D02*\nG03*\nX0Y1000000I1000000J0D01*');
    near(box(g.bounds).maxX, 1.05, 0.01); near(box(g.bounds).maxY, 1.05, 0.01);
    near(g.strokes[0].pts.reduce((m, p) => Math.max(m, Math.abs(Math.hypot(p.x, p.y) - 1)), 0), 0, 1e-3);
  });
  it('Bogen mit falschem Mittelpunkt wird gemeldet', () => {
    const g = G('G75*\n%ADD10C,0.1*%\nD10*\nX1000000Y0D02*\nG03*\nX0Y1000000I-5000000J0D01*');
    expect(g.warnings.join(' ')).toContain('Mittelpunkt');
  });
  it('Region mit Boegen: Kreisscheibe', () => {
    const g = G('G75*\nG36*\nX2000000Y0D02*\nG03*\nX2000000Y0I-2000000J0D01*\nG37*');
    near(g.area, Math.PI * 4, 0.02); expect(g.regionCount).toBe(1);
  });
});

describe('Gerber: Regionen und Polaritaet', () => {
  const square = (s: number) => `G36*\nX0Y0D02*\nG01*\nX${s}000000Y0D01*\nX${s}000000Y${s}000000D01*\nX0Y${s}000000D01*\nX0Y0D01*\nG37*`;
  it('mehrere Konturen in einer Region', () => {
    const g = G(`G36*\nX0Y0D02*\nG01*\nX1000000Y0D01*\nX1000000Y1000000D01*\nX0Y0D01*\nX5000000Y0D02*\nX6000000Y0D01*\nX6000000Y1000000D01*\nX5000000Y0D01*\nG37*`);
    near(g.area, 1, 1e-6); expect(g.polys).toHaveLength(2);
  });
  it('Region mit Schnittlinie (Keyhole) ergibt ein Loch', () => {
    const g = G('G36*\nX0Y0D02*\nG01*\nX4000000Y0D01*\nX4000000Y4000000D01*\nX0Y4000000D01*\nX0Y0D01*\nX1000000Y1000000D01*\nX1000000Y3000000D01*\nX3000000Y3000000D01*\nX3000000Y1000000D01*\nX1000000Y1000000D01*\nX0Y0D01*\nG37*');
    near(g.area, 16 - 4, 1e-3);
    expect(pointInPolys(2, 2, g.polys)).toBe(false); expect(pointInPolys(0.5, 2, g.polys)).toBe(true);
  });
  it('LPC stanzt, LPD danach fuellt wieder', () => {
    const g = G(`${square(10)}\n%LPC*%\n%ADD10C,4*%\nD10*\nX5000000Y5000000D03*\n%LPD*%\n%ADD11C,2*%\nD11*\nX5000000Y5000000D03*`);
    near(g.area, 100 - Math.PI * 4 + Math.PI, 0.03);
    expect(pointInPolys(5, 5, g.polys)).toBe(true);
    expect(pointInPolys(5, 6.5, g.polys)).toBe(false);
    expect(pointInPolys(1, 1, g.polys)).toBe(true);
  });
  it('die Reihenfolge der Polaritaet zaehlt', () => {
    const a = G(`%LPC*%\n%ADD10C,4*%\nD10*\nX5000000Y5000000D03*\n%LPD*%\n${square(10)}`);
    near(a.area, 100, 1e-3); // erst ausstanzen, dann fuellen: nichts bleibt ausgespart
  });
  it('Step and Repeat vervielfaeltigt', () => {
    const g = G('%SRX3Y2I10J5*%\n%ADD10R,1X1*%\nD10*\nX0Y0D03*\n%SR*%');
    near(g.area, 6, 1e-6); near(box(g.bounds).maxX, 20.5, 1e-3); near(box(g.bounds).maxY, 5.5, 1e-3);
    expect(g.flashes).toHaveLength(6);
  });
  it('meldet nicht unterstuetzte Befehle statt zu schweigen', () => {
    const g = G('%IPNEG*%\n%ADD10C,1*%\nD10*\nX0Y0D03*');
    expect(g.warnings.join(' ')).toContain('IPNEG');
  });
  it('fehlende Blende wird gemeldet', () => {
    const g = G('D99*\nX0Y0D03*');
    expect(g.warnings.join(' ')).toContain('D99');
  });
  it('reiner Text ist keine Gerber-Datei', () => {
    expect(() => parseGerber('Hallo Welt')).toThrow();
  });
});

describe('Gerber: Makros', () => {
  it('rechnet mit Variablen und Klammern', () => {
    const v = new Map([[1, 3], [2, 4]]);
    expect(evalMacroExpr('$1+2x$2', v)).toBeCloseTo(11);
    expect(evalMacroExpr('($1+2)x$2', v)).toBeCloseTo(20);
    expect(evalMacroExpr('-$1/2', v)).toBeCloseTo(-1.5);
    expect(evalMacroExpr('$1X$2-.5', v)).toBeCloseTo(11.5);
  });
  it('abgerundetes Rechteck aus Grundformen 21 und 1', () => {
    const g = G('%AMRR*$4=$1-2x$3*$5=$2-2x$3*21,1,$4,$2,0,0,0*21,1,$1,$5,0,0,0*1,1,2x$3,$4/2,$5/2*1,1,2x$3,-$4/2,$5/2*1,1,2x$3,$4/2,-$5/2*1,1,2x$3,-$4/2,-$5/2*%\n%ADD10RR,4X2X0.5*%\nD10*\nX0Y0D03*');
    near(g.area, 4 * 2 - (4 - Math.PI) * 0.25, 0.01); near(box(g.bounds).maxX, 2, 1e-3);
  });
  it('Belichtung 0 stanzt aus dem Makro', () => {
    const g = G('%AMLOCH*21,1,4,4,0,0,0*1,0,2,0,0*%\n%ADD10LOCH*%\nD10*\nX0Y0D03*');
    near(g.area, 16 - Math.PI, 0.02);
  });
  it('Drehung, Kontur 4, Linie 20, Vieleck 5, Linie 22', () => {
    const d = G('%AMD*21,1,4,2,0,0,90*%\n%ADD10D*%\nD10*\nX0Y0D03*');
    near(box(d.bounds).maxY, 2, 1e-3); near(box(d.bounds).maxX, 1, 1e-3);
    near(G('%AMU*4,1,3,0,0,2,0,2,2,0,0,0*%\n%ADD10U*%\nD10*\nX0Y0D03*').area, 2, 1e-3);
    near(G('%AML*20,1,1,0,0,5,0,0*%\n%ADD10L*%\nD10*\nX0Y0D03*').area, 5, 1e-3);
    near(G('%AMP*5,1,4,0,0,2,0*%\n%ADD10P*%\nD10*\nX0Y0D03*').area, 2, 1e-3);
    const ll = G('%AMQ*22,1,2,1,1,1,0*%\n%ADD10Q*%\nD10*\nX0Y0D03*');
    near(box(ll.bounds).minX, 1, 1e-3); near(box(ll.bounds).maxY, 2, 1e-3);
  });
  it('Waermefalle 7: Ring minus Stege', () => {
    const g = G('%AMT*7,0,0,4,2,0.5,0*%\n%ADD10T*%\nD10*\nX0Y0D03*');
    expect(g.polys).toHaveLength(4);
    near(g.area, Math.PI * (4 - 1) - 4 * 0.5 * 1, 0.05);
    expect(pointInPolys(1.5, 0, g.polys)).toBe(false);
    expect(pointInPolys(1.06, 1.06, g.polys)).toBe(true);
  });
  it('Makro-Parameter in Zoll werden umgerechnet', () => {
    const g = parseGerber('%FSLAX24Y24*%\n%MOIN*%\n%AMR1*21,1,$1,$1,0,0,0*%\n%ADD10R1,1*%\nD10*\nX0Y0D03*\nM02*\n');
    near(g.area, 25.4 * 25.4, 0.01);
  });
});

describe('Excellon', () => {
  it('liest metrisch mit Dezimalpunkt', () => {
    const d = parseExcellon('M48\nMETRIC,TZ\nT1C0.800\nT2C3.0\n%\nG90\nG05\nT1\nX10.5Y20.25\nX11Y21\nT2\nX0Y0\nM30\n');
    expect(d.hits).toHaveLength(3); expect(d.hits[0]).toMatchObject({ x: 10.5, y: 20.25, dia: 0.8 }); expect(d.hits[2].dia).toBe(3);
  });
  it('Zoll mit TZ: Nachkommastellen von rechts', () => {
    const d = parseExcellon('M48\nINCH,TZ\nT1C0.0320\n%\nT1\nX10000Y5000\nM30\n');
    near(d.hits[0].x, 25.4, 1e-6); near(d.hits[0].y, 12.7, 1e-6); near(d.hits[0].dia, 0.8128, 1e-6);
  });
  it('Zoll mit LZ: fehlende hintere Nullen', () => {
    const d = parseExcellon('M48\nINCH,LZ\nT1C0.03\n%\nT1\nX01Y005\nM30\n');
    near(d.hits[0].x, 25.4, 1e-6); near(d.hits[0].y, 12.7, 1e-6);
  });
  it('Format aus Kommentar (Altium) und aus der METRIC-Zeile', () => {
    const a = parseExcellon(';FILE_FORMAT=2:5\nM48\nINCH,TZ\nT1C0.03\n%\nT1\nX100000Y50000\nM30\n');
    near(a.hits[0].x, 25.4, 1e-6);
    const b = parseExcellon('M48\nMETRIC,LZ,000.00\nT1C1\n%\nT1\nX01000Y00500\nM30\n');
    near(b.hits[0].x, 10, 1e-6); near(b.hits[0].y, 5, 1e-6);
  });
  it('behaelt modale Koordinaten und liest G85-Schlitze', () => {
    const d = parseExcellon('M48\nMETRIC\nT1C1.0\n%\nT1\nX1.0Y2.0\nY3.0\nX5.0Y5.0G85X8.0Y5.0\nM30\n');
    expect(d.hits).toHaveLength(2); expect(d.hits[1]).toMatchObject({ x: 1, y: 3 });
    expect(d.slots).toHaveLength(1); expect(d.slots[0].b).toEqual({ x: 8, y: 5 });
  });
  it('gefraeste Schlitze mit M15/M16', () => {
    const d = parseExcellon('M48\nMETRIC\nT1C1.0\n%\nT1\nG00X1.0Y1.0\nM15\nG01X4.0Y1.0\nM16\nG05\nX9.0Y9.0\nM30\n');
    expect(d.slots).toHaveLength(1); expect(d.hits).toHaveLength(1);
  });
});

describe('Lagen erkennen', () => {
  const cases: [string, string][] = [
    ['board.GTL', 'copper-top'], ['board.GBL', 'copper-bottom'], ['board.GTS', 'mask-top'], ['board.GBS', 'mask-bottom'], ['board.GTO', 'silk-top'], ['board.GBO', 'silk-bottom'],
    ['board.GKO', 'outline'], ['board.GM1', 'outline'], ['board.GML', 'outline'], ['board.G1', 'copper-inner'], ['board.GTP', 'paste-top'], ['board.TXT', 'drill'], ['board.DRL', 'drill'],
    ['proj-F_Cu.gbr', 'copper-top'], ['proj-B_Cu.gbr', 'copper-bottom'], ['proj-F.Cu.gbr', 'copper-top'], ['proj-F_Mask.gbr', 'mask-top'], ['proj-B_Mask.gbr', 'mask-bottom'],
    ['proj-F_Silkscreen.gbr', 'silk-top'], ['proj-B_SilkS.gbr', 'silk-bottom'], ['proj-Edge_Cuts.gbr', 'outline'], ['proj-F_Paste.gbr', 'paste-top'], ['proj-In1_Cu.gbr', 'copper-inner'],
    ['proj-PTH.drl', 'drill'], ['proj-NPTH.drl', 'drill'], ['proj-job.gbrjob', 'other'],
    ['Gerber_TopLayer.GTL', 'copper-top'], ['Gerber_BottomSolderMaskLayer.GBS', 'mask-bottom'], ['Gerber_BoardOutlineLayer.GKO', 'outline'], ['Drill_PTH_Through.DRL', 'drill'],
    ['eagle.cmp', 'copper-top'], ['eagle.sol', 'copper-bottom'], ['eagle.stc', 'mask-top'], ['eagle.plc', 'silk-top'], ['eagle.dim', 'outline'],
    ['liesmich.pdf', 'other'],
  ];
  for (const [n, k] of cases) it(n, () => expect(classifyLayer(n)).toBe(k));
  it('X2-Attribut schlaegt den Namen', () => {
    expect(classifyLayer('egal.gbr', '%TF.FileFunction,Copper,L2,Bot*%\n')).toBe('copper-bottom');
    expect(classifyLayer('egal.gbr', '%TF.FileFunction,Soldermask,Top*%\n')).toBe('mask-top');
    expect(classifyLayer('egal.gbr', '%TF.FileFunction,Profile,NP*%\n')).toBe('outline');
  });
  it('Bohrdatei am Inhalt', () => expect(classifyLayer('bohr-ohne-endung', 'M48\nMETRIC\n')).toBe('drill'));
});

describe('ZIP', () => {
  it('liest gepackte und ungepackte Eintraege', async () => {
    const enc = new TextEncoder();
    const entries = [{ name: 'a.GTL', data: enc.encode('hallo'), method: 0 }, { name: 'sub/b.GBL', data: enc.encode('welt welt welt welt'), method: 8 }];
    const parts: Uint8Array[] = []; const cd: Uint8Array[] = []; let off = 0;
    for (const e of entries) {
      const body = e.method === 8 ? new Uint8Array(deflateRawSync(e.data)) : e.data;
      const name = enc.encode(e.name);
      const lh = new Uint8Array(30 + name.length); const ld = new DataView(lh.buffer);
      ld.setUint32(0, 0x04034b50, true); ld.setUint16(8, e.method, true); ld.setUint32(18, body.length, true); ld.setUint32(22, e.data.length, true); ld.setUint16(26, name.length, true); lh.set(name, 30);
      parts.push(lh, body);
      const ch = new Uint8Array(46 + name.length); const cv = new DataView(ch.buffer);
      cv.setUint32(0, 0x02014b50, true); cv.setUint16(10, e.method, true); cv.setUint32(20, body.length, true); cv.setUint32(24, e.data.length, true); cv.setUint16(28, name.length, true); cv.setUint32(42, off, true); ch.set(name, 46);
      cd.push(ch); off += lh.length + body.length;
    }
    const cdLen = cd.reduce((s, c) => s + c.length, 0);
    const eo = new Uint8Array(22); const ev = new DataView(eo.buffer);
    ev.setUint32(0, 0x06054b50, true); ev.setUint16(10, entries.length, true); ev.setUint32(12, cdLen, true); ev.setUint32(16, off, true);
    const all = [...parts, ...cd, eo]; const z = new Uint8Array(all.reduce((s, c) => s + c.length, 0));
    let p = 0; for (const c of all) { z.set(c, p); p += c.length; }
    expect(isZip(z)).toBe(true);
    const r = await readZip(z);
    expect(r.map((e) => e.name)).toEqual(['a.GTL', 'sub/b.GBL']);
    expect(new TextDecoder().decode(r[1].bytes)).toBe('welt welt welt welt');
  });
});

describe('Beispielplatine', () => {
  const files = BEISPIEL.map((f) => readPcbFile(f.name, f.text));
  const board = buildBoard(files)!;
  it('erkennt alle Lagen ohne Warnung', () => {
    expect(files.map((f) => f.kind)).toEqual(['copper-top', 'copper-bottom', 'mask-top', 'mask-bottom', 'silk-top', 'outline', 'drill']);
    for (const f of files) { expect(f.error).toBeUndefined(); expect(f.gerber?.warnings ?? f.drill?.warnings).toEqual([]); }
  });
  it('Umriss 60 x 40 mit gerundeten Ecken', () => {
    expect(board.outlineFromFile).toBe(true);
    expect(board.outline).toHaveLength(1);
    near(board.bounds.maxX - board.bounds.minX, 60, 0.01); near(board.bounds.maxY - board.bounds.minY, 40, 0.01);
    near(polysArea(board.outline), Math.abs(polysArea(board.outline)), 1e-9);
    near(Math.abs(polysArea(board.outline)), 60 * 40 - (4 - Math.PI) * 4, 0.1);
  });
  it('26 Bohrungen in den richtigen Durchmessern', () => {
    expect(board.drills).toHaveLength(26);
    expect(board.drills.filter((d) => d.dia === 0.8)).toHaveLength(20);
    expect(board.drills.filter((d) => d.dia === 3.2)).toHaveLength(4);
  });
  it('Kupfer oben: Leiterbreite 0,6 mm und plausible Flaeche', () => {
    const c = board.copper.top!;
    near(c.minStroke!, 0.6, 1e-6);
    expect(c.area).toBeGreaterThan(100); expect(c.area).toBeLessThan(400);
    expect(pointInPolys(26.19, 23.81, c.polys)).toBe(true);
  });
  it('Kupfer unten: Massefläche mit Freistellungen', () => {
    const c = board.copper.bottom!;
    expect(c.area).toBeGreaterThan(1500); expect(c.area).toBeLessThan(2184);
    expect(pointInPolys(4, 4, c.polys)).toBe(false);         // Montageloch freigestellt
    expect(pointInPolys(15, 30, c.polys)).toBe(true);        // Fläche
    expect(pointInPolys(26.19, 21.27, c.polys)).toBe(true);  // Signalpad wieder da
    expect(pointInPolys(26.19 + 1.1, 21.27 + 0.3, c.polys)).toBe(false); // Freistellring
  });
  it('Abstand: gefunden und gegen die Pruefung gemeldet', () => {
    const top = minClearance(board.copper.top!.polys);
    expect(top).not.toBeNull(); expect(top!.mm).toBeGreaterThan(0.25);
    const bottom = minClearance(board.copper.bottom!.polys);
    expect(bottom!.mm).toBeGreaterThan(0.25);
  });
});

describe('Abstandspruefung', () => {
  it('misst die Luecke, nicht die Ringbreite', () => {
    const g = G('%ADD10R,2X2*%\nD10*\nX0Y0D03*\nX2500000Y0D03*');
    near(minClearance(g.polys)!.mm, 0.5, 1e-3);
    const ring = G('%ADD10C,4X3.9*%\nD10*\nX0Y0D03*');
    expect(minClearance(ring.polys)).toBeNull();
  });
  it('findet nichts oberhalb der Grenze', () => {
    const g = G('%ADD10R,2X2*%\nD10*\nX0Y0D03*\nX9000000Y0D03*');
    expect(minClearance(g.polys, 2)).toBeNull();
  });
  it('Umriss aus losen Linien wird geschlossen', () => {
    const loops = stitchLoops([[{ x: 0, y: 0 }, { x: 5, y: 0 }], [{ x: 5, y: 5 }, { x: 5, y: 0 }], [{ x: 5, y: 5 }, { x: 0, y: 5 }], [{ x: 0, y: 5 }, { x: 0, y: 0 }]]);
    expect(loops).toHaveLength(1); near(Math.abs(polysArea(loops)), 25, 1e-6);
  });
});

describe('Auftrag', () => {
  const pad = (x: number, y: number) => `X${x}000000Y${y}000000D03*`;
  const copper = readPcbFile('c.GTL', parseFileBody(`%ADD10R,2X2*%\nD10*\n${pad(5, 5)}\n${pad(15, 5)}`));
  const edge = readPcbFile('c.GKO', parseFileBody('%ADD11C,0.1*%\nD11*\nX0Y0D02*\nX20000000Y0D01*\nX20000000Y10000000D01*\nX0Y10000000D01*\nX0Y0D01*'));
  const drill = readPcbFile('c.DRL', 'M48\nMETRIC\nT1C1.0\n%\nT1\nX5.0Y5.0\nX15.0Y5.0\nM30\n');
  const board = buildBoard([copper, edge, drill])!;
  const S = { ...defaultSettings(), beamMm: 0.2, overlapPct: 50, fiducials: 0 as const };

  it('Zeilenabstand folgt der Strahlbreite', () => {
    expect(lineInterval({ beamMm: 0.2, overlapPct: 50 })).toBeCloseTo(0.1);
    expect(lineInterval({ beamMm: 0.04, overlapPct: 50 })).toBeCloseTo(0.03);
    expect(buildPlan(board, S).layers[0].intervalMm).toBeCloseTo(0.1);
  });
  it('Raster negativ: alles ausser Kupfer plus halber Strahl', () => {
    const plan = buildPlan(board, { ...S, drillMarks: false });
    const r = plan.layers.find((l) => l.key === 'resist')!;
    expect(r.mode).toBe('FILL');
    const edgeArea = 21 * 11 - (4 - Math.PI) * 0.25; // Umriss + 0,5 mm rund
    const padArea = 2 * (2.2 * 2.2 - (4 - Math.PI) * 0.01);
    near(polysArea(r.polys), edgeArea - padArea, 0.05);
    expect(pointInPolys(5, 5, r.polys)).toBe(false);
    expect(pointInPolys(10, 5, r.polys)).toBe(true);
    expect(r.polys.every((p) => isClosed(p))).toBe(true);
  });
  it('Isolation: n Bahnen, Abstand je Durchgang, keine Flaeche', () => {
    const plan = buildPlan(board, { ...S, method: 'isolation', passes: 2, drillMarks: false });
    const r = plan.layers.find((l) => l.key === 'resist')!;
    expect(r.mode).toBe('LINE');
    expect(r.polys).toHaveLength(4); // zwei Pads, je zwei Bahnen
    const xs = r.polys.map((p) => Math.max(...p.map((q) => q.x))).sort((a, b) => a - b);
    near(xs[0], 6.1, 1e-3); near(xs[1], 6.2, 1e-3); near(xs[2], 16.1, 1e-3); near(xs[3], 16.2, 1e-3);
    expect(plan.layers.some((l) => l.name.endsWith('Rest'))).toBe(false);
  });
  it('Isolation mit Restkupfer: Bahnen und Flaeche ergaenzen sich', () => {
    const plan = buildPlan(board, { ...S, method: 'isolation', passes: 2, removeRest: true, drillMarks: false });
    const rest = plan.layers.find((l) => l.name.endsWith('Rest'))!;
    expect(rest.mode).toBe('FILL');
    expect(pointInPolys(6.1, 5, rest.polys)).toBe(false);
    expect(pointInPolys(10, 5, rest.polys)).toBe(true);
  });
  it('Isolationsbahnen bleiben innerhalb des Umrisses', () => {
    const near2edge = buildBoard([readPcbFile('c.GTL', parseFileBody(`%ADD10R,2X2*%\nD10*\n${pad(1, 5)}`)), edge])!;
    const r = buildPlan(near2edge, { ...S, method: 'isolation', passes: 8, drillMarks: false }).layers.find((l) => l.key === 'resist')!;
    expect(Math.min(...r.polys.flat().map((p) => p.x))).toBeGreaterThanOrEqual(-0.5 - 1e-3);
  });
  it('Belichten: Kupfer selbst, Bohrmitte bleibt dunkel', () => {
    const plan = buildPlan(board, { ...S, method: 'expose' });
    const r = plan.layers.find((l) => l.key === 'resist')!;
    expect(pointInPolys(10, 5, r.polys)).toBe(false);
    expect(pointInPolys(5.5, 5.5, r.polys)).toBe(true);
    expect(pointInPolys(5, 5, r.polys)).toBe(false);
    expect(plan.layers.some((l) => l.key === 'drill')).toBe(false);
  });
  it('Bohrmarken: Punkt oder Kreuz in der Mitte, kleiner als die Bohrung', () => {
    const dot = buildPlan(board, { ...S, drillMarkMm: 0.5 }).layers.find((l) => l.key === 'drill')!;
    near(polysArea(dot.polys), 2 * Math.PI * 0.0625, 0.01);
    expect(pointInPolys(5, 5, dot.polys)).toBe(true); expect(pointInPolys(5.5, 5, dot.polys)).toBe(false);
    const big = buildPlan(board, { ...S, drillMarkMm: 5 }).layers.find((l) => l.key === 'drill')!;
    expect(Math.max(...big.polys.flat().map((p) => p.x)) - 15).toBeLessThanOrEqual(0.41);
    const cross = buildPlan(board, { ...S, drillStyle: 'cross', drillMarkMm: 0.6 }).layers.find((l) => l.key === 'drill')!;
    expect(pointInPolys(5.25, 5, cross.polys)).toBe(true); expect(pointInPolys(5.25, 5.25, cross.polys)).toBe(false);
  });
  it('Passmarken liegen so, dass sie beim Wenden aufeinanderfallen', () => {
    for (const count of [2, 4] as const) {
      const s = { ...S, fiducials: count };
      const plan = buildPlan(board, s);
      const top = plan.fiducials.map((f) => toJob(f, plan.bounds, false));
      const bot = plan.fiducials.map((f) => toJob(f, plan.bounds, true));
      const key = (p: { x: number; y: number }) => `${p.x.toFixed(3)}/${p.y.toFixed(3)}`;
      expect(new Set(bot.map(key))).toEqual(new Set(top.map(key)));
    }
    expect(fiducialPoints(board.bounds, 0, 3)).toEqual([]);
  });
  it('Spiegeln: Pad links wird rechts, Y zeigt nach unten', () => {
    const plan = buildPlan(board, S);
    const b = plan.bounds;
    expect(toJob({ x: 5, y: 5 }, b, false)).toEqual({ x: 5, y: 5 });
    expect(toJob({ x: 5, y: 7 }, b, false)).toEqual({ x: 5, y: 3 });
    expect(toJob({ x: 5, y: 5 }, b, true)).toEqual({ x: 15, y: 5 });
  });
  it('Pruefung warnt bei zu engem Abstand und zu schmaler Leiter', () => {
    const tight = buildBoard([readPcbFile('t.GTL', parseFileBody('%ADD10C,0.1*%\n%ADD12R,2X2*%\nD12*\nX0Y0D03*\nX2100000Y0D03*\nD10*\nX0Y5000000D02*\nX5000000Y5000000D01*')), edge])!;
    const s = { ...S, beamMm: 0.15, x: 100, y: 100 };
    const checks = designChecks(designFacts(tight, 'top'), s, buildPlan(tight, s));
    expect(checks.find((c) => c.id === 'clearance')!.tone).toBe('bad');
    expect(checks.find((c) => c.id === 'trace')!.tone).toBe('bad');
    const okS = { ...s, beamMm: 0.05 };
    expect(designChecks(designFacts(tight, 'top'), okS, buildPlan(tight, okS)).find((c) => c.id === 'clearance')!.tone).toBe('ok');
  });
  it('Pruefung warnt ausserhalb der Arbeitsflaeche und bei falscher Spiegelung', () => {
    const s = { ...S, x: 9999, y: 0, side: 'bottom' as const, mirror: false };
    const ids = designChecks(designFacts(board, 'bottom'), s, buildPlan(board, s)).map((c) => c.id);
    expect(ids).toContain('bed'); expect(ids).toContain('mirror');
  });
  it('Startwerte liegen ueber der Untergrenze fuer brennende Leistung', () => {
    for (const v of Object.values(START_VALUES)) expect(v.power).toBeGreaterThanOrEqual(8);
  });
  it('Zeitschaetzung: 10 x 10 mm Flaeche bei 0,1 mm und 600 mm/min', () => {
    const sq = [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }, { x: 0, y: 10 }, { x: 0, y: 0 }];
    near(estimateSeconds({ mode: 'FILL', polys: [sq], intervalMm: 0.1, speed: 600 }, 0), 100, 1.5);
    near(estimateSeconds({ mode: 'LINE', polys: [sq], intervalMm: 0.1, speed: 600 }), 4, 1e-9);
  });
});

describe('Ins Dokument', () => {
  const board = buildBoard(BEISPIEL.map((f) => readPcbFile(f.name, f.text)))!;
  const S = { ...defaultSettings(), x: 50, y: 60, mask: true, silk: true, fiducials: 4 as const };
  const plan = buildPlan(board, S);

  it('legt je Prozess eine eigene Ebene an, die Standardebenen bleiben', () => {
    const { doc, ids } = applyPlanToDoc(newDoc(), plan, S, { stage: 'resist', replace: false });
    const names = doc.layers.map((l) => l.name);
    for (const n of ['Gravieren', 'Linie', 'Schneiden', 'Platine Ätzresist', 'Platine Bohrmarken', 'Platine Passmarken', 'Platine Umriss', 'Platine Lötstopp', 'Platine Beschriftung']) expect(names).toContain(n);
    expect(ids).toHaveLength(doc.elements.length);
    expect(new Set(doc.elements.map((e) => e.groupId)).size).toBe(1);
  });
  it('nur der gewaehlte Arbeitsgang hat Ausgabe, Umriss nur auf Wunsch', () => {
    const { doc } = applyPlanToDoc(newDoc(), plan, S, { stage: 'resist', replace: false });
    const out = (n: string) => doc.layers.find((l) => l.name === n)!.output;
    expect(out('Platine Ätzresist')).toBe(true); expect(out('Platine Bohrmarken')).toBe(true); expect(out('Platine Passmarken')).toBe(true);
    expect(out('Platine Lötstopp')).toBe(false); expect(out('Platine Beschriftung')).toBe(false); expect(out('Platine Umriss')).toBe(false);
    const m = applyPlanToDoc(newDoc(), plan, S, { stage: 'mask', replace: false }).doc;
    expect(m.layers.find((l) => l.name === 'Platine Lötstopp')!.output).toBe(true);
    expect(m.layers.find((l) => l.name === 'Platine Ätzresist')!.output).toBe(false);
  });
  it('Modus, Zeilenabstand, Lage auf dem Bett stimmen und FILL ist geschlossen', () => {
    const { doc } = applyPlanToDoc(newDoc(), plan, S, { stage: 'resist', replace: false });
    const res = doc.layers.find((l) => l.name === 'Platine Ätzresist')!;
    expect(res.mode).toBe('FILL'); expect(res.intervalMm).toBeCloseTo(lineInterval(S));
    expect(doc.layers.find((l) => l.name === 'Platine Umriss')!.mode).toBe('LINE');
    for (const e of doc.elements) {
      const l = doc.layers.find((x) => x.id === e.layerId)!;
      if (l.mode === 'FILL') expect(e.paths.every((p) => isClosed(p))).toBe(true);
      const w = worldBounds(e)!;
      expect(w.minX).toBeGreaterThanOrEqual(50 - 1e-6); expect(w.minY).toBeGreaterThanOrEqual(60 - 1e-6);
      expect(w.maxX).toBeLessThanOrEqual(50 + 60 + 2 * 3.5 + 1e-6); expect(w.maxY).toBeLessThanOrEqual(60 + 40 + 2 * 3.5 + 1e-6);
    }
  });
  it('Dokument bleibt kompatibel: JSON hin und zurueck, normalize aendert nichts', () => {
    const { doc } = applyPlanToDoc(newDoc(), plan, S, { stage: 'resist', replace: false });
    const back = fromJson(toJson(doc));
    expect(back.elements).toHaveLength(doc.elements.length);
    expect(back.layers.map((l) => l.name)).toEqual(doc.layers.map((l) => l.name));
    expect(normalize(back).elements[0].paths[0].length).toBe(doc.elements[0].paths[0].length);
    expect(doc.elements[0].kind).toBe('Platine');
    expect(doc.elements[0].raster).toBeNull();
  });
  it('zweites Uebernehmen: Ebenen werden wiederverwendet, Ersetzen entfernt nur Platinen-Teile', () => {
    const first = applyPlanToDoc(newDoc(), plan, S, { stage: 'resist', replace: false }).doc;
    const n = first.layers.length, count = first.elements.length;
    const again = applyPlanToDoc(first, plan, S, { stage: 'resist', replace: false }).doc;
    expect(again.layers).toHaveLength(n); expect(again.elements).toHaveLength(2 * count);
    const rep = applyPlanToDoc(first, plan, S, { stage: 'resist', replace: true }).doc;
    expect(rep.elements).toHaveLength(count);
  });
});

describe('Gerber: echte Exporte', () => {
  it('KiCad: RoundRect-Makro mit Kommentaren und negativen Parametern', () => {
    const g = parseGerber([
      'G04 #@! TF.FileFunction,Copper,L1,Top*', 'G04 Gerber Fmt 4.6, Leading zero omitted, Abs format (unit mm)*', '%TF.GenerationSoftware,KiCad,Pcbnew,8.0*%', '%MOMM*%', '%FSLAX46Y46*%',
      '%AMRoundRect*', '0 Rectangle with rounded corners*', '0 $1 Rounding radius*', '0 $2 $3 $4 $5 $6 $7 $8 $9 X,Y pos of 4 corners*', '0 Add a 4 corners polygon primitive as box body*',
      '4,1,4,$2,$3,$4,$5,$6,$7,$8,$9,$2,$3,0*', '0 Add four circle primitives for the rounded corners*', '1,1,$1+$1,$2,$3*', '1,1,$1+$1,$4,$5*', '1,1,$1+$1,$6,$7*', '1,1,$1+$1,$8,$9*',
      '0 Add four rect primitives between the rounded corners*', '20,1,$1+$1,$2,$3,$4,$5,0*', '20,1,$1+$1,$4,$5,$6,$7,0*', '20,1,$1+$1,$6,$7,$8,$9,0*', '20,1,$1+$1,$8,$9,$2,$3,0*%',
      'G04 Aperture macros list end*', '%TA.AperFunction,SMDPad,CuDef*%', '%ADD10RoundRect,0.250000X-1.000000X-0.500000X1.000000X-0.500000X1.000000X0.500000X-1.000000X0.500000X0*%', '%TD*%',
      'G04 APERTURE END LIST*', 'D10*', '%TO.N,GND*%', 'X10000000Y10000000D03*', '%TD*%', 'M02*',
    ].join('\n'));
    expect(g.warnings).toEqual([]);
    // Body 2 x 1 grown by the 0.25 radius on all sides: 2.5 x 1.5 with rounded corners.
    near(g.area, 2.5 * 1.5 - (4 - Math.PI) * 0.0625, 0.01);
    near(box(g.bounds).maxX, 11.25, 2e-3);
  });
  it('alte Exporte: G54, modale D-Codes, Kommentar mit Prozentzeichen', () => {
    const g = parseGerber('%FSLAX24Y24*%\n%MOMM*%\nG04 Fuellung 50% *\n%ADD10C,1*%\nG54D10*\nG01X0Y0D02*\nX100000D01*\nX200000*\nM02*\n');
    near(box(g.bounds).maxX, 20.5, 2e-3);
    near(g.area, 20 + Math.PI * 0.25, 0.02);
  });
  it('Attribut im Kommentar wird fuer die Lage erkannt', () => {
    expect(classifyLayer('x.gbr', 'G04 #@! TF.FileFunction,Soldermask,Bot*\n')).toBe('mask-bottom');
  });
  it('grosse Platine bleibt schnell genug', () => {
    let body = '%ADD10C,0.25*%\n%ADD11C,1.5*%\nG36*\nX0Y0D02*\nG01*\nX150000000Y0D01*\nX150000000Y100000000D01*\nX0Y100000000D01*\nX0Y0D01*\nG37*\n%LPC*%\n';
    const u = (v: number) => Math.round(v * 1000000);
    const pad = (x: number, y: number) => `X${u(x)}Y${u(y)}D03*\n`;
    body += '%ADD12C,2.1*%\nD12*\n';
    for (let i = 0; i < 40; i++) for (let k = 0; k < 25; k++) body += pad(3 + i * 3.5, 3 + k * 3.8);
    body += '%LPD*%\nD11*\n';
    for (let i = 0; i < 40; i++) for (let k = 0; k < 25; k++) body += pad(3 + i * 3.5, 3 + k * 3.8);
    body += 'D10*\n';
    for (let i = 0; i < 39; i++) for (let k = 0; k < 25; k++) body += `X${u(3 + i * 3.5)}Y${u(3 + k * 3.8)}D02*\nX${u(3 + (i + 1) * 3.5)}Y${u(3 + k * 3.8)}D01*\n`;
    const t0 = performance.now();
    const f = readPcbFile('gross.GTL', `%FSLAX46Y46*%\n%MOMM*%\n${body}M02*\n`);
    const parsed = performance.now();
    const b = buildBoard([f])!;
    const s = { ...defaultSettings(), fiducials: 0 as const };
    const plan = buildPlan(b, s);
    const planned = performance.now();
    designFacts(b, 'top');
    const checked = performance.now();
    expect(plan.layers.length).toBeGreaterThan(0);
    // Generous ceiling: guards against accidental quadratic behaviour, not a benchmark.
    expect(parsed - t0).toBeLessThan(20000);
    expect(planned - parsed).toBeLessThan(30000);
    expect(checked - planned).toBeLessThan(20000);
  }, 90000);
});


function parseFileBody(body: string) { return `%FSLAX46Y46*%\n%MOMM*%\n${body}\nM02*\n`; }
