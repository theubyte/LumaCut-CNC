import type { LucideIcon } from 'lucide-react';
import { BadgeCheck, Box as BoxIcon, Cog, Crop, Hash, Image as ImageIcon, KeyRound, LayoutGrid, QrCode, Ruler, Scale3d, Stamp, Coffee, Package, FlaskConical } from 'lucide-react';
import { type Box, type Doc, type Element, plateElements, worldBounds } from '@/core/model';
import {
  boxResult, FRAME_LABEL, type FrameStyle, frameResult, gearResult, type GenPart, type GenResult, matGridResult, nest, nestUnits,
  PHOTO_MATERIALS, photoMaterial, photoResult, type PhotoSource, qrResult, rulerResult, samplePhoto, scaleBarResult, serialResult, stampResult, templateResult, TEMPLATE_LABEL, type TemplateKind, type TextShaper, MAX_SERIALS,
} from '@/core/generators';

/** The tools of the workshop as data: one form description and one pure compute function each. */
export type Params = Record<string, number | string | boolean>;
export interface Env { shape: TextShaper; doc: Doc; selection: string[]; photo: PhotoSource | null; photoName: string | null }

export type Field =
  | { type: 'num'; key: string; label: string; aria?: string; unit?: string; min?: number; max?: number; step?: number; digits?: number; hint?: string }
  | { type: 'seg'; key: string; label: string; options: { value: string; label: string }[]; hint?: string }
  | { type: 'select'; key: string; label: string; options: { value: string; label: string }[]; hint?: string }
  | { type: 'text'; key: string; label: string; hint?: string; placeholder?: string }
  | { type: 'check'; key: string; label: string; hint?: string }
  | { type: 'slider'; key: string; label: string; min: number; max: number; step?: number; unit?: string; digits?: number }
  | { type: 'row'; fields: Field[] }
  | { type: 'section'; label: string }
  | { type: 'hint'; text: string }
  | { type: 'photo' };

export interface Tool {
  id: string; group: string; title: string; blurb: string; icon: LucideIcon;
  /** Long explanation at the top of the settings. */
  intro?: string;
  defaults(env: Pick<Env, 'doc'>): Params;
  fields(p: Params): Field[];
  compute(p: Params, env: Env): GenResult;
  /** Picture for the gallery when the default settings show nothing without a motif. */
  thumb?(env: Env): GenResult;
  /** Parts on a busy plate would collide: start on a new plate then. */
  freshPlate?: boolean;
  /** Adjust settings when a choice implies others (material sets the line spacing). */
  linked?(key: string, p: Params): Params;
  /** Runs instead of adding the result. */
  applyLabel?: string;
  custom?: 'matgrid' | 'nest';
}

const seg = (key: string, label: string, options: [string, string][], hint?: string): Field => ({ type: 'seg', key, label, hint, options: options.map(([value, l]) => ({ value, label: l })) });
const mm = (key: string, label: string, min: number, max: number, step = 1, digits = 1, hint?: string): Field => ({ type: 'num', key, label, unit: 'mm', min, max, step, digits, hint });
const n = (p: Params, k: string) => p[k] as number;
const s = (p: Params, k: string) => p[k] as string;
const b = (p: Params, k: string) => p[k] as boolean;

const thickness = (d: Pick<Env, 'doc'>) => { const t = d.doc.layers.find((l) => l.name === 'Schneiden')?.thicknessMm; return t && t > 0 ? t : 3; };

/** Selection, else everything on the active plate. */
export function motifBox(env: Pick<Env, 'doc' | 'selection'>): Box | null {
  const pool = plateElements(env.doc);
  const picked = env.selection.length ? pool.filter((e) => env.selection.includes(e.id)) : pool;
  let out: Box | null = null;
  for (const e of picked) {
    const q = worldBounds(e); if (!q) continue;
    out = out ? { minX: Math.min(out.minX, q.minX), minY: Math.min(out.minY, q.minY), maxX: Math.max(out.maxX, q.maxX), maxY: Math.max(out.maxY, q.maxY) } : q;
  }
  return out;
}

export function nestPool(doc: Doc, scope: string): Element[] {
  return scope === 'all' ? doc.elements : plateElements(doc);
}
/** The arrangement as real geometry for the preview, so what is shown is what will happen. */
export function nestPreview(doc: Doc, scope: string, gap: number): { result: GenResult; plan: ReturnType<typeof nest> } {
  const pool = nestPool(doc, scope);
  const plan = nest(nestUnits(pool), gap);
  const parts: GenPart[] = [];
  for (const e of pool) {
    const q = plan.placements.get(e.id); if (!q) continue;
    const layer = doc.layers.find((l) => l.id === e.layerId)?.name ?? 'Linie';
    const t = e.transform;
    const moved = { ...t, x: t.x + q.dx, y: t.y + q.dy };
    if (e.raster) parts.push({ name: e.kind, layer, paths: [], plate: q.plate, x: moved.x, y: moved.y, image: { raster: e.raster, widthMm: e.imageWidthMm, heightMm: e.imageHeightMm, mode: e.imageMode, adjust: e.adjust } });
    else parts.push({ name: e.kind, layer, plate: q.plate, paths: e.paths.map((poly) => poly.map((pt) => {
      const sx = pt.x * t.scaleX, sy = pt.y * t.scaleY, r = t.rotation * Math.PI / 180;
      return { x: sx * Math.cos(r) - sy * Math.sin(r) + moved.x, y: sx * Math.sin(r) + sy * Math.cos(r) + moved.y };
    })) });
  }
  const notes = plan.units
    ? [`${plan.units} Teile auf ${plan.plates} ${plan.plates === 1 ? 'Platte' : 'Platten'}, ${Math.round(plan.usagePct)} % der Fläche belegt.`, 'Einfaches Regal-Verfahren: Rechteck um jedes Teil, höchste zuerst, ohne Drehen und ohne Ineinanderschieben. Gruppen bleiben zusammen, die Park-Ecke bleibt frei.']
    : [];
  const warnings = plan.leftOut ? [`${plan.leftOut} ${plan.leftOut === 1 ? 'Teil ist' : 'Teile sind'} größer als die Platte und ${plan.leftOut === 1 ? 'bleibt' : 'bleiben'} an der alten Stelle.`] : [];
  return { result: { parts, notes, warnings, placement: 'keep' }, plan };
}

/** The sample picture is only a stand-in: a resolution warning about it would mislead. */
const withoutSoftWarning = (env: Env, r: GenResult): GenResult => env.photo ? r : { ...r, warnings: [], notes: ['Vorschau mit Testbild. Für die echte Gravur oben ein Foto wählen.', ...(r.notes ?? [])] };

function templateTool(kind: TemplateKind, icon: LucideIcon, blurb: string, w: number, h: number, text: string, second: string): Tool {
  const round = kind === 'untersetzer';
  return {
    id: `vorlage-${kind}`, group: 'Vorlagen', title: TEMPLATE_LABEL[kind], blurb, icon,
    defaults: () => ({ text, second, w, h }),
    fields: () => [
      { type: 'text', key: 'text', label: kind === 'etikett' ? 'Titel' : 'Text' },
      { type: 'text', key: 'second', label: kind === 'anhaenger' ? 'Zweite Zeile (entfällt)' : 'Zweite Zeile' },
      round ? mm('w', 'Durchmesser', 40, 200, 5) : { type: 'row', fields: [mm('w', 'Breite', 15, 340, 5), mm('h', 'Höhe', 8, 340, 1)] },
    ].filter((f) => !(kind === 'anhaenger' && 'key' in f && f.key === 'second')) as Field[],
    compute: (p, env) => templateResult({ kind, text: s(p, 'text'), second: s(p, 'second'), widthMm: n(p, 'w'), heightMm: round ? n(p, 'w') : n(p, 'h') }, env.shape),
  };
}

export const TOOLS: Tool[] = [
  {
    id: 'materialtest', group: 'Testen', title: 'Materialtest', blurb: 'Leistung gegen Tempo oder automatisch mit der Kamera', icon: FlaskConical, custom: 'matgrid', freshPlate: true,
    defaults: () => ({ powerFrom: 20, powerTo: 100, powerSteps: 5, speedFrom: 300, speedTo: 3000, speedSteps: 5, mode: 'FILL', cell: 10, gap: 4, passes: 1, interval: 0.1 }),
    fields: (p) => [
      { type: 'section', label: 'Leistung' },
      { type: 'hint', text: 'Mindestens 8 %: darunter zündet der Laser nicht sicher.' },
      { type: 'row', fields: [{ type: 'num', key: 'powerFrom', label: 'Von', aria: 'Leistung von', unit: '%', min: 8, max: 100, digits: 0 }, { type: 'num', key: 'powerTo', label: 'Bis', aria: 'Leistung bis', unit: '%', min: 8, max: 100, digits: 0 }, { type: 'num', key: 'powerSteps', label: 'Stufen', aria: 'Leistung Stufen', min: 1, max: 10, digits: 0 }] },
      { type: 'section', label: 'Tempo in mm/min' },
      { type: 'row', fields: [{ type: 'num', key: 'speedFrom', label: 'Von', aria: 'Tempo von', min: 10, max: 30000, step: 100, digits: 0 }, { type: 'num', key: 'speedTo', label: 'Bis', aria: 'Tempo bis', min: 10, max: 30000, step: 100, digits: 0 }, { type: 'num', key: 'speedSteps', label: 'Stufen', aria: 'Tempo Stufen', min: 1, max: 10, digits: 0 }] },
      { type: 'section', label: 'Felder' },
      seg('mode', 'Art', [['FILL', 'Gefüllt'], ['LINE', 'Nur Umriss']]),
      { type: 'row', fields: [mm('cell', 'Feldgröße', 3, 40, 1), mm('gap', 'Abstand', 1, 20, 1), { type: 'num', key: 'passes', label: 'Durchgänge', min: 1, max: 30, digits: 0 }] },
      ...(p.mode === 'FILL' ? [mm('interval', 'Zeilenabstand', 0.05, 1, 0.01, 2)] : []),
    ],
    compute: (p, env) => matGridResult({ powerFrom: n(p, 'powerFrom'), powerTo: n(p, 'powerTo'), powerSteps: n(p, 'powerSteps'), speedFrom: n(p, 'speedFrom'), speedTo: n(p, 'speedTo'), speedSteps: n(p, 'speedSteps'), mode: s(p, 'mode') as 'FILL' | 'LINE', cellMm: n(p, 'cell'), gapMm: n(p, 'gap'), passes: n(p, 'passes'), intervalMm: n(p, 'interval') }, env.shape),
  },
  {
    id: 'foto', group: 'Fotos und Stempel', title: 'Fotogravur', blurb: 'Foto vorbereiten: Kurve, Schärfe, Zeilenabstand', icon: ImageIcon,
    defaults: () => ({ material: 'sperrholz', width: 100, interval: 0.12, mode: 'DITHER', gamma: 1.2, brightness: 0, contrast: 0, sharpen: 20, invert: false }),
    fields: () => [
      { type: 'photo' },
      { type: 'select', key: 'material', label: 'Material', options: PHOTO_MATERIALS.map((m) => ({ value: m.key, label: m.label })), hint: 'Setzt Zeilenabstand, Verfahren und Kurve auf den Richtwert' },
      { type: 'row', fields: [mm('width', 'Breite', 5, 350, 5, 0), { type: 'num', key: 'interval', label: 'Zeilenabstand', unit: 'mm', min: 0.05, max: 1, step: 0.01, digits: 3 }] },
      seg('mode', 'Verfahren', [['GRAYSCALE', 'Graustufen'], ['DITHER', 'Punkte'], ['DITHER_JARVIS', 'Feine Punkte'], ['THRESHOLD', 'Schwelle']]),
      { type: 'section', label: 'Bild' },
      { type: 'slider', key: 'gamma', label: 'Kurve (Mitten aufhellen)', min: 0.5, max: 2.5, step: 0.05, digits: 2 },
      { type: 'slider', key: 'brightness', label: 'Helligkeit', min: -100, max: 100 },
      { type: 'slider', key: 'contrast', label: 'Kontrast', min: -100, max: 100 },
      { type: 'slider', key: 'sharpen', label: 'Schärfen', min: 0, max: 100 },
      { type: 'check', key: 'invert', label: 'Umkehren (für dunkle Materialien, die hell werden)' },
    ],
    linked: (key, p) => { if (key !== 'material') return p; const m = photoMaterial(s(p, 'material')); return { ...p, interval: m.intervalMm, mode: m.mode, gamma: m.gamma }; },
    compute: (p, env) => withoutSoftWarning(env, photoResult(env.photo ?? samplePhoto(), { widthMm: n(p, 'width'), intervalMm: n(p, 'interval'), mode: s(p, 'mode') as 'DITHER', gamma: n(p, 'gamma'), brightness: n(p, 'brightness'), contrast: n(p, 'contrast'), sharpen: n(p, 'sharpen'), invert: b(p, 'invert'), materialKey: s(p, 'material') })),
  },
  {
    id: 'stempel', group: 'Fotos und Stempel', title: 'Stempel', blurb: 'Invertiert und gespiegelt, mit Rahmen, Text und Motiv', icon: Stamp,
    defaults: () => ({ shape: 'rect', w: 60, h: 25, l1: 'Musterfirma', l2: 'Hauptstraße 1', l3: '', motif: 'none', border: 0.8, bold: true, inverted: true, mirrored: true }),
    fields: (p) => [
      seg('shape', 'Form', [['rect', 'Eckig'], ['round', 'Rund']]),
      p.shape === 'round' ? mm('w', 'Durchmesser', 10, 300, 1) : { type: 'row', fields: [mm('w', 'Breite', 10, 300, 1), mm('h', 'Höhe', 10, 300, 1)] },
      { type: 'text', key: 'l1', label: 'Zeile 1' }, { type: 'text', key: 'l2', label: 'Zeile 2' }, { type: 'text', key: 'l3', label: 'Zeile 3' },
      seg('motif', 'Motiv', [['none', 'Keins'], ['star', 'Stern'], ['heart', 'Herz'], ['drop', 'Tropfen']]),
      mm('border', 'Rahmenstärke', 0, 5, 0.1, 1, '0 = ohne Rahmen'),
      { type: 'check', key: 'bold', label: 'Fette Schrift' },
      { type: 'check', key: 'inverted', label: 'Invertiert (Hintergrund wird weggebrannt)' },
      { type: 'check', key: 'mirrored', label: 'Gespiegelt (Abdruck wird lesbar)' },
    ],
    compute: (p, env) => stampResult({ widthMm: n(p, 'w'), heightMm: n(p, 'h'), shape: s(p, 'shape') as 'rect', lines: [s(p, 'l1'), s(p, 'l2'), s(p, 'l3')], motif: s(p, 'motif') as 'none', borderMm: n(p, 'border'), bold: b(p, 'bold'), inverted: b(p, 'inverted'), mirrored: b(p, 'mirrored') }, env.shape),
  },
  {
    id: 'box', group: 'Teile', title: 'Box mit Fingerzinken', blurb: 'Maße innen oder außen, Materialstärke, Deckel', icon: BoxIcon, freshPlate: true,
    defaults: (env) => ({ w: 100, d: 80, h: 60, measure: 'outer', t: thickness(env), finger: 10, lid: 'none', kerf: 0.15 }),
    fields: () => [
      seg('measure', 'Maße gelten', [['outer', 'Außen'], ['inner', 'Innen']]),
      { type: 'row', fields: [mm('w', 'Breite', 20, 340), mm('d', 'Tiefe', 20, 340), mm('h', 'Höhe', 20, 340)] },
      { type: 'row', fields: [mm('t', 'Materialstärke', 0.5, 10, 0.1), mm('finger', 'Zinkenbreite', 2, 50)] },
      seg('lid', 'Deckel', [['none', 'Offen'], ['joined', 'Verzahnt'], ['loose', 'Aufgelegt']]),
      mm('kerf', 'Schnittbreite (Kerf)', 0, 1, 0.05, 2, 'Teile werden um die halbe Schnittbreite größer, damit die Zinken stramm sitzen. Mit einem Probeschnitt messen.'),
    ],
    compute: (p) => boxResult({ w: n(p, 'w'), d: n(p, 'd'), h: n(p, 'h'), t: n(p, 't'), finger: n(p, 'finger'), lid: s(p, 'lid') as 'none', inner: p.measure === 'inner', kerf: n(p, 'kerf') }),
  },
  {
    id: 'zahnrad', group: 'Teile', title: 'Zahnrad', blurb: 'Evolventenverzahnung mit Modul, Zähnen, Bohrung', icon: Cog,
    defaults: () => ({ module: 2, teeth: 24, pressure: 20, bore: 6, kerf: 0 }),
    fields: () => [
      { type: 'row', fields: [mm('module', 'Modul', 0.5, 20, 0.5, 2), { type: 'num', key: 'teeth', label: 'Zähne', min: 6, max: 200, digits: 0 }] },
      { type: 'row', fields: [{ type: 'num', key: 'pressure', label: 'Eingriffswinkel', unit: '°', min: 14, max: 25, digits: 1 }, mm('bore', 'Bohrung', 0, 300, 0.5, 1)] },
      mm('kerf', 'Schnittbreite (Kerf)', 0, 1, 0.05, 2),
    ],
    compute: (p) => gearResult({ module: n(p, 'module'), teeth: n(p, 'teeth'), pressureDeg: n(p, 'pressure'), boreMm: n(p, 'bore'), kerf: n(p, 'kerf') }),
  },
  {
    id: 'lineal', group: 'Teile', title: 'Lineal', blurb: 'Skala in Millimetern mit Zahlen und Aufhängeloch', icon: Ruler,
    defaults: () => ({ length: 150, width: 30, hole: 5, title: '' }),
    fields: () => [
      { type: 'row', fields: [mm('length', 'Messlänge', 30, 340, 10, 0), mm('width', 'Breite', 15, 80, 1)] },
      mm('hole', 'Aufhängeloch', 0, 15, 0.5, 1, '0 = ohne Loch'),
      { type: 'text', key: 'title', label: 'Text auf dem Lineal', placeholder: 'zum Beispiel ein Name' },
    ],
    compute: (p, env) => rulerResult({ lengthMm: n(p, 'length'), widthMm: n(p, 'width'), holeMm: n(p, 'hole'), title: s(p, 'title') }, env.shape),
  },
  {
    id: 'massstab', group: 'Teile', title: 'Maßstabsbalken', blurb: 'Für Pläne und Modelle, zum Beispiel 1:50', icon: Scale3d,
    defaults: () => ({ scale: 50, real: 5, segments: 5, height: 3 }),
    fields: () => [
      { type: 'row', fields: [{ type: 'num', key: 'scale', label: 'Maßstab 1 :', min: 1, max: 100000, digits: 0 }, { type: 'num', key: 'real', label: 'Echte Länge', unit: 'm', min: 0.01, max: 100000, digits: 2 }] },
      { type: 'row', fields: [{ type: 'num', key: 'segments', label: 'Felder', min: 1, max: 20, digits: 0 }, mm('height', 'Balkenhöhe', 1, 20, 0.5)] },
    ],
    compute: (p, env) => scaleBarResult({ scale: n(p, 'scale'), realLengthM: n(p, 'real'), segments: n(p, 'segments'), heightMm: n(p, 'height') }, env.shape),
  },
  {
    id: 'rahmen', group: 'Teile', title: 'Rahmen', blurb: 'Um das Motiv oder in freien Maßen', icon: Crop,
    defaults: (env) => ({ source: motifBox({ doc: env.doc, selection: [] }) ? 'motiv' : 'frei', w: 100, h: 60, margin: 5, style: 'ROUNDED', target: 'cut' }),
    fields: (p) => [
      seg('source', 'Größe', [['motiv', 'Um das Motiv'], ['frei', 'Freie Maße']]),
      p.source === 'motiv' ? mm('margin', 'Abstand zum Motiv', 0, 100, 1) : { type: 'row', fields: [mm('w', 'Breite', 5, 340, 5), mm('h', 'Höhe', 5, 340, 5)] },
      { type: 'select', key: 'style', label: 'Stil', options: (Object.keys(FRAME_LABEL) as FrameStyle[]).map((v) => ({ value: v, label: FRAME_LABEL[v] })) },
      seg('target', 'Ebene', [['cut', 'Schneiden'], ['mark', 'Markieren']]),
    ],
    thumb: () => frameResult({ around: null, widthMm: 100, heightMm: 60, style: 'ROUNDED', marginMm: 0, cut: true }),
    compute: (p, env) => {
      const around = p.source === 'motiv' ? motifBox(env) : null;
      if (p.source === 'motiv' && !around) throw new Error('Im Motiv ist noch nichts. Erst etwas anlegen oder „Freie Maße“ wählen.');
      return frameResult({ around, widthMm: n(p, 'w'), heightMm: n(p, 'h'), style: s(p, 'style') as FrameStyle, marginMm: n(p, 'margin'), cut: p.target === 'cut' });
    },
  },
  {
    id: 'qr', group: 'Beschriften', title: 'QR-Code', blurb: 'Text oder Adresse als graviertes Muster', icon: QrCode,
    defaults: () => ({ text: 'https://', module: 1, plate: false }),
    fields: () => [
      { type: 'text', key: 'text', label: 'Text oder Adresse' },
      mm('module', 'Kantenlänge eines Punktes', 0.2, 10, 0.1, 2),
      { type: 'check', key: 'plate', label: 'Umriss zum Ausschneiden, mit hellem Rand' },
    ],
    compute: (p) => qrResult({ text: s(p, 'text'), moduleMm: n(p, 'module'), plate: b(p, 'plate') }),
  },
  {
    id: 'serien', group: 'Beschriften', title: 'Seriennummern', blurb: 'Fortlaufende Schilder, über mehrere Platten verteilt', icon: Hash, freshPlate: true,
    defaults: () => ({ template: 'SN-{0001}', count: 24, step: 1, textH: 6, tag: true, tagW: 50, tagH: 16, hole: 3, gap: 2 }),
    fields: (p) => [
      { type: 'text', key: 'template', label: 'Vorlage', hint: 'Die Ziffern in { } sind Startwert und Stellenzahl: {0001} ergibt 0001, 0002, …' },
      { type: 'row', fields: [{ type: 'num', key: 'count', label: 'Stück', min: 1, max: MAX_SERIALS, digits: 0 }, { type: 'num', key: 'step', label: 'Schrittweite', min: 1, max: 1000, digits: 0 }, mm('textH', 'Schrifthöhe', 1, 50, 0.5)] },
      { type: 'check', key: 'tag', label: 'Schild um jede Nummer ausschneiden' },
      ...(p.tag ? [{ type: 'row', fields: [mm('tagW', 'Schildbreite', 10, 340), mm('tagH', 'Schildhöhe', 5, 340), mm('hole', 'Loch', 0, 15, 0.5, 1)] } as Field] : []),
      mm('gap', 'Abstand', 0.5, 30, 0.5),
    ],
    compute: (p, env) => serialResult({ template: s(p, 'template'), count: n(p, 'count'), step: n(p, 'step'), textHeightMm: n(p, 'textH'), tagWidthMm: b(p, 'tag') ? n(p, 'tagW') : 0, tagHeightMm: b(p, 'tag') ? n(p, 'tagH') : 0, holeMm: n(p, 'hole'), gapMm: n(p, 'gap') }, env.shape),
  },
  {
    id: 'schachteln', group: 'Anordnen', title: 'Schachteln', blurb: 'Teile aus dem Motiv platzsparend auf Platten legen', icon: LayoutGrid, custom: 'nest', applyLabel: 'Im Motiv anordnen',
    defaults: () => ({ scope: 'plate', gap: 3 }),
    fields: () => [
      seg('scope', 'Teile von', [['plate', 'Dieser Platte'], ['all', 'Allen Platten']]),
      mm('gap', 'Abstand', 0.5, 30, 0.5),
    ],
    thumb: () => ({ placement: 'keep', parts: [[0, 0, 60, 40], [64, 0, 34, 40], [102, 0, 30, 26], [0, 44, 44, 22], [48, 44, 50, 18], [102, 30, 30, 30]].map(([x, y, w, h]) => ({ name: 'Teil', layer: 'Schneiden', paths: [[{ x, y }, { x: x + w, y }, { x: x + w, y: y + h }, { x, y: y + h }, { x, y }]] })) }),
    compute: (p, env) => {
      const { result } = nestPreview(env.doc, s(p, 'scope'), n(p, 'gap'));
      if (!result.parts.length && !result.warnings?.length) throw new Error('Im Motiv ist noch nichts zum Anordnen. Erst Teile anlegen oder importieren.');
      return result;
    },
  },
  templateTool('schild', BadgeCheck, 'Name graviert, Zierlinie, Umriss', 80, 30, 'Anna Muster', 'Werkstatt'),
  templateTool('untersetzer', Coffee, 'Rund, mit Strahlenmuster und Text', 100, 100, 'Prost', 'seit 2026'),
  templateTool('anhaenger', KeyRound, 'Mit Loch für den Ring', 60, 20, 'Anna', ''),
  templateTool('etikett', Package, 'Für Kisten, mit Linien zum Beschriften', 120, 70, 'Schrauben', 'M4 bis M8'),
];
export const GROUPS = ['Testen', 'Fotos und Stempel', 'Teile', 'Beschriften', 'Anordnen', 'Vorlagen'];
