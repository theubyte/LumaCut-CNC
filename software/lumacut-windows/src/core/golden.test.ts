/// <reference types="node" />
/**
 * Bis aufs Zeichen gegen den echten Kotlin-Code: golden/ wurde von GoldenGen.kt.txt erzeugt
 * (Eingaben: golden/cases.ts). Neu erzeugen: siehe Kopf von GoldenGen.kt.txt.
 */
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeEach, describe, expect, it } from 'vitest';
import { Contour, Mask } from './contour';
import { makeShape, Curves, Personalize, type Parts, type ShapeKind, type TagStyle, type FrameStyle } from './create';
import { Darkness, powerShare } from './darkness';
import { ArcText, Arrange, ShapeLib } from './extras';
import { buildMaterialTest, convexHull, framePoints, frameProgram } from './frame';
import { hatch, orderForCutting, orderPaths, Shapes, simplify } from './geometry';
import { fuzzCases, geoInput, maskArgb, namedCases, type GoldenCase } from './golden/cases';
import { writeMarlin, JobBuildError } from './gcode';
import { configureBed, newLayer, type Box, type Layer, type Poly } from './model';
import { PartSplitter } from './parts';
import { formatDuration, parseToolpathCompact, remainingSeconds, type CompactToolpath } from './toolpath';
import { Align, Booleans, BoxMaker, Nest, shelf, Tabs, type AlignMode, type RasterBooleanOp } from './tools';

const here = join(dirname(fileURLToPath(import.meta.url)), 'golden');
const read = (name: string) => readFileSync(join(here, name), 'utf8').replace(/\r\n/g, '\n');
const FUZZ = Number(process.env.GOLDEN_FUZZ) || 400;

function run(c: GoldenCase): string {
  const b = c.bed ?? [370, 360, 78, 35];
  configureBed(b[0], b[1], b[2], b[3]);
  try { return writeMarlin(c.doc, { appVersion: 'golden', motion: c.motion }); }
  catch (e) { if (e instanceof JobBuildError) return 'FEHLER: ' + e.message; throw e; }
}
const sha = (s: string) => createHash('sha256').update(s, 'utf8').digest('hex');

function stats(g: string) {
  const tp = parseToolpathCompact(g);
  const bits = new Int32Array(tp.xy.buffer, tp.xy.byteOffset, tp.count * 4);
  const seg: string[] = [];
  for (let i = 0; i < tp.count; i++) { const o = i * 4; seg.push(`${bits[o]} ${bits[o + 1]} ${bits[o + 2]} ${bits[o + 3]} ${tp.power[i]} ${tp.power[i] > 0} ${tp.line[i]}\n`); }
  const cuts = framePoints(tp);
  const b = tp.bounds;
  return {
    cutMm: tp.stats.cutMm, travelMm: tp.stats.travelMm, seconds: tp.stats.seconds, maxPower: tp.stats.maxPower, warnings: tp.stats.warnings,
    bounds: b ? [b.minX, b.minY, b.maxX, b.maxY] : null, lineCount: tp.lineCount, count: tp.count, segments: sha(seg.join('')),
    remaining: remainingSeconds(tp as CompactToolpath, Math.trunc(tp.lineCount / 3)), duration: formatDuration(tp.stats.seconds),
    frameBox: cuts.length ? sha(frameProgram(cuts, 'box')) : '', frameHull: cuts.length ? sha(frameProgram(cuts, 'hull', 5000)) : '',
  };
}

if (process.env.GOLDEN_WRITE) {
  const dir = process.env.GOLDEN_WRITE;
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'named.json'), JSON.stringify(namedCases()));
  writeFileSync(join(dir, 'fuzz.json'), JSON.stringify(fuzzCases(FUZZ)));
  writeFileSync(join(dir, 'geo.json'), JSON.stringify(geoInput()));
}

const hasGolden = existsSync(join(here, 'stats.json'));
const pts = (p: Poly) => p.map((q) => [q.x, q.y]);
const polys = (l: Poly[]) => l.map(pts);
const partsJ = (p: Parts) => ({ engrave: polys(p.engrave), cut: polys(p.cut), marks: polys(p.marks), labels: p.labels.map(([q, s]) => [[q.x, q.y], s]) });

/** Zahlen dürfen nur um Rechenrauschen abweichen (Sinus der JVM und von V8), Struktur und Text gar nicht. */
function near(a: unknown, b: unknown, path: string, eps: number): void {
  if (typeof a === 'number' && typeof b === 'number') {
    if (Math.abs(a - b) > eps) throw new Error(`${path}: ${a} != ${b}`);
    return;
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) throw new Error(`${path}: Länge ${a.length} != ${b.length}`);
    a.forEach((v, i) => near(v, b[i], `${path}[${i}]`, eps));
    return;
  }
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    for (const k of Object.keys(b as object)) near((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k], `${path}.${k}`, eps);
    return;
  }
  if (a !== b) throw new Error(`${path}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`);
}

describe.runIf(hasGolden)('G-Code gleich Kotlin', () => {
  beforeEach(() => configureBed(370, 360, 78, 35));
  const named = namedCases();
  const expected = hasGolden ? JSON.parse(read('stats.json')) : {};

  for (const c of named) {
    it(c.name, () => {
      const got = run(c), want = read(`gcode/${c.name}.gcode`);
      if (got !== want) {
        const a = got.split('\n'), b = want.split('\n');
        const i = a.findIndex((l, k) => l !== b[k]);
        expect(`Zeile ${i + 1}: ${a[i]}`).toBe(`Zeile ${i + 1}: ${b[i]}`);
        expect(got.length).toBe(want.length);
      }
      if (!got.startsWith('FEHLER')) expect(stats(got)).toEqual(expected[c.name]);
      else expect(want.startsWith('FEHLER')).toBe(true);
    });
  }

  it(`${FUZZ} Zufallsdokumente`, () => {
    const want = JSON.parse(process.env.GOLDEN_FUZZ_FILE ? readFileSync(process.env.GOLDEN_FUZZ_FILE, 'utf8') : read('fuzz.json'));
    const bad: string[] = [];
    let errors = 0, ok = 0;
    for (const c of fuzzCases(FUZZ)) {
      const got = run(c), w = want[c.name];
      if (got.startsWith('FEHLER')) errors++; else ok++;
      if (sha(got) !== w.sha) { bad.push(`${c.name}: ${got.startsWith('FEHLER') ? got : 'G-Code weicht ab'} / Kotlin ${w.error ?? 'G-Code'}`); continue; }
      if (w.stats) { try { expect(stats(got)).toEqual(w.stats); } catch (e) { bad.push(`${c.name}: Werkzeugweg ${(e as Error).message.slice(0, 300)}`); } }
    }
    expect(bad).toEqual([]);
    expect(ok).toBeGreaterThan(100);
    expect(errors).toBeGreaterThan(20);
  }, 120000);
});

describe.runIf(hasGolden)('Geometrie gleich Kotlin', () => {
  beforeEach(() => configureBed(370, 360, 78, 35));
  const g = geoInput();
  const want = hasGolden ? JSON.parse(read('geometry.json')) : {};
  const boxes: Box[] = g.boxes;
  const m = () => Mask.fromArgb(maskArgb(60, 40), 60, 40, 30, 20);
  const cases: Record<string, () => unknown> = {
    hatch: () => polys(hatch(g.nested, 0.5)),
    hatchRing: () => polys(hatch(g.ring, 1.3)),
    orderPaths: () => polys(orderPaths(g.open, { x: 5, y: 5 })),
    orderForCutting: () => polys(orderForCutting([...g.nested, ...g.open], { x: 0, y: 0 })),
    simplify: () => pts(simplify(g.dense, 0.3)),
    rect: () => pts(Shapes.rect(30, 20)), rectR: () => pts(Shapes.rect(30, 20, 4)), ellipse: () => pts(Shapes.ellipse(30, 20)), polygon: () => pts(Shapes.polygon(7, 30, 20)),
    contourOut: () => polys(Contour.fromPolys(g.nested, 2)), contourIn: () => polys(Contour.fromPolys(g.nested, -0.5)), contourOuter: () => polys(Contour.fromPolys(g.ring, 1, 8, true)),
    maskCount: () => m().count, maskFilled: () => m().filled().count, maskSpecks: () => m().withoutSpecks(0.5).count,
    sticker: () => polys(Contour.sticker(m(), 2)), stickerJoin: () => polys(Contour.sticker(m(), 1, true)), edge: () => polys(Contour.edge(m(), 0.2)),
    split: () => PartSplitter.split([...g.nested, ...g.open]).parts.map(polys),
    distH: () => pts(Align.distribute(boxes, true)), distV: () => pts(Align.distribute(boxes, false)),
    tabs: () => polys(Tabs.apply([...g.ring, ...g.open], 3, 1.5)),
    shelf: () => shelf(boxes, 370, 360).map((p) => (p ? [p.x, p.y] : null)),
    nest: () => Nest.place(boxes).map((p) => (p ? [p.plate, [p.offset.x, p.offset.y]] : null)),
    boxOpen: () => BoxMaker.panels({ w: 60, d: 40, h: 30, t: 3, finger: 8 }).map(([n, p]) => [n, pts(p)]),
    boxClosed: () => BoxMaker.panels({ w: 60, d: 40, h: 30, t: 3, finger: 8, closed: true }).map(([n, p]) => [n, pts(p)]),
    arcUp: () => polys(ArcText.bend(g.text, 30)), arcDown: () => polys(ArcText.bend(g.text, -30)),
    grid: () => pts(Arrange.gridOffsets(boxes[0], 3, 4, 2, 5)), gridInside: () => pts(Arrange.inside(boxes[4], Arrange.gridOffsets(boxes[0], 3, 4, 20, 5))),
    heart: () => pts(ShapeLib.heart(30, 25)), star: () => pts(ShapeLib.star(6, 30, 25, 0.5)), pendant: () => polys(ShapeLib.pendant(30, 25)),
    curveOpen: () => pts(Curves.catmullRom(g.points.slice(0, 4), false)), curveClosed: () => pts(Curves.catmullRom(g.points.slice(0, 4), true, 5)),
    emblem: () => partsJ(Personalize.emblem(g.text, g.text, g.text, 60)), emblemPlain: () => partsJ(Personalize.emblem(g.text, null, null, 40)),
    dashes: () => polys(Personalize.dashes(g.ring[0], 4, 2.5)), ruler: () => partsJ(Personalize.ruler(50, 20, 4)),
    puzzle7: () => polys(Personalize.puzzle(60, 40, 3, 2)), puzzle2: () => polys(Personalize.puzzle(60, 40, 2, 3, 123456)), puzzle3: () => polys(Personalize.puzzle(60, 40, 2, 2, -5)),
    hull: () => pts(convexHull(g.points)), frameBox: () => frameProgram(g.points, 'box'), frameHull: () => frameProgram(g.points, 'hull', 12000),
    toolpath: () => stats(g.toolpath),
    materialTest: () => {
      const mt = buildMaterialTest({ powerSteps: 3, speedSteps: 2 }, (t, h) => [Shapes.rect(t.length * h, h)]);
      return { title: mt.title, layers: mt.layers.map((l) => [l.name, l.color, l.powerPct, l.speed, l.mode]), elements: mt.elements.map((e) => [e.kind, [e.transform.x, e.transform.y], polys(e.paths), e.text]) };
    },
    dark: () => {
      const curve = { points: [[20, 0.1], [40, 0.3], [60, 0.25], [90, 0.8]].map(([power, tone]) => ({ power, speed: 3000, tone })) };
      const lay: Layer = newLayer('G', 1, 'FILL', { powerPct: 30, speed: 3000, intervalMm: 0.1, darkness: curve });
      const plain: Layer = newLayer('L', 1, 'LINE', { powerPct: 30, speed: 1500 });
      const res = (r: { layer: Layer; limit: string | null }) => [r.layer.speed, r.layer.powerPct, r.limit];
      return [...Darkness.speedRange(lay, 9000), ...Darkness.speedRange(plain, 9000),
        res(Darkness.atSpeed(lay, 500, 9000)), res(Darkness.atSpeed(lay, 8000, 9000)), res(Darkness.atSpeed(plain, 100, 9000)), res(Darkness.atSpeed(plain, 2000, 9000)),
        Darkness.speedPosition(lay, 9000), Darkness.speedAt(lay, 0.7, 9000), Darkness.tone(lay) ?? -1, Darkness.tone(plain) ?? -1,
        res(Darkness.atTone(lay, 0.5, 9000)), res(Darkness.atTone(lay, 0.05, 9000)), res(Darkness.atTone(lay, 0.95, 9000)), res(Darkness.atTone(lay, 0.11, 1000)), res(Darkness.atTone(plain, 0.5, 9000)),
        powerShare({ toneCurve: [0, 0.2, 0.9] }, 0.3), powerShare(lay, 1.5)];
    },
  };
  for (const mode of ['LEFT', 'CENTER_X', 'RIGHT', 'TOP', 'CENTER_Y', 'BOTTOM'] as AlignMode[]) cases[`align${mode}`] = () => pts(Align.offsets(boxes, mode, boxes[1]));
  for (const op of ['UNION', 'SUBTRACT', 'INTERSECT'] as RasterBooleanOp[]) cases[`bool${op}`] = () => polys(Booleans.apply([g.ring, [Shapes.rect(20, 50).map((p) => ({ x: p.x + 10, y: p.y - 5 }))]], op));
  for (const k of ['STAR', 'HEART', 'ARROW', 'BUBBLE', 'CROSS', 'DROP'] as ShapeKind[]) cases[`make${k}`] = () => pts(makeShape(k, 30, 25));
  for (const s of ['KEYCHAIN', 'PLATE', 'HEART', 'ROUND'] as TagStyle[]) {
    cases[`tag${s}`] = () => partsJ(Personalize.tag(g.text, s, 4));
    cases[`tagNo${s}`] = () => partsJ(Personalize.tag(g.text, s, null));
  }
  for (const s of ['SIMPLE', 'ROUNDED', 'DOUBLE', 'OVAL', 'DASHED'] as FrameStyle[]) cases[`frame${s}`] = () => polys(Personalize.frame(boxes[0], s, 3));

  it('alle Golden-Schlüssel haben einen Vergleich', () => {
    expect(Object.keys(want).filter((k) => !(k in cases))).toEqual([]);
  });
  for (const [name, fn] of Object.entries(cases)) it(name, () => near(fn(), want[name], name, 1e-6));
});
