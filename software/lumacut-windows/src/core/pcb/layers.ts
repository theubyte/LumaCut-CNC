/** Recognises what a fabrication file is, by X2 attribute and name first, by content second. */
export type LayerKind = 'copper-top' | 'copper-bottom' | 'copper-inner' | 'mask-top' | 'mask-bottom' | 'silk-top' | 'silk-bottom' | 'paste-top' | 'paste-bottom' | 'outline' | 'drill' | 'other';

export const LAYER_LABEL: Record<LayerKind, string> = {
  'copper-top': 'Kupfer oben', 'copper-bottom': 'Kupfer unten', 'copper-inner': 'Kupfer innen (ungenutzt)',
  'mask-top': 'Lötstopp oben', 'mask-bottom': 'Lötstopp unten', 'silk-top': 'Beschriftung oben', 'silk-bottom': 'Beschriftung unten',
  'paste-top': 'Lötpaste oben (ungenutzt)', 'paste-bottom': 'Lötpaste unten (ungenutzt)',
  outline: 'Platinenumriss', drill: 'Bohrungen', other: 'Nicht verwenden',
};

const EXT: Record<string, LayerKind> = {
  gtl: 'copper-top', cmp: 'copper-top', top: 'copper-top', gbl: 'copper-bottom', sol: 'copper-bottom', bot: 'copper-bottom',
  gts: 'mask-top', stc: 'mask-top', smt: 'mask-top', gbs: 'mask-bottom', sts: 'mask-bottom', smb: 'mask-bottom',
  gto: 'silk-top', plc: 'silk-top', sst: 'silk-top', gbo: 'silk-bottom', pls: 'silk-bottom', ssb: 'silk-bottom',
  gtp: 'paste-top', crc: 'paste-top', gbp: 'paste-bottom', crs: 'paste-bottom',
  gko: 'outline', gml: 'outline', dim: 'outline', oln: 'outline', out: 'outline', bor: 'outline',
  drl: 'drill', xln: 'drill', exc: 'drill', drd: 'drill', tap: 'drill', ncd: 'drill',
};

/** Name fragments of KiCad, EasyEDA, Eagle and Altium exports. Order matters: mask before copper. */
const NAME_RULES: [RegExp, LayerKind][] = [
  [/edge[._-]?cuts|board[._ -]?outline|outline|umriss|profile|keep[._-]?out/, 'outline'],
  [/(^|[^a-z])(pth|npth)([^a-z]|$)|drill|bohr/, 'drill'],
  [/f[._]?(mask|sm)\b|top[._ -]?(solder[._ -]?)?mask|solder[._ -]?mask[._ -]?top|mask[._ -]?top/, 'mask-top'],
  [/b[._]?(mask|sm)\b|bot(tom)?[._ -]?(solder[._ -]?)?mask|solder[._ -]?mask[._ -]?bot|mask[._ -]?bot/, 'mask-bottom'],
  [/f[._]?paste|top[._ -]?paste|paste[._ -]?top/, 'paste-top'],
  [/b[._]?paste|bot(tom)?[._ -]?paste|paste[._ -]?bot/, 'paste-bottom'],
  [/f[._]?silk|top[._ -]?silk|silk[._ -]?top|top[._ -]?overlay/, 'silk-top'],
  [/b[._]?silk|bot(tom)?[._ -]?silk|silk[._ -]?bot|bot(tom)?[._ -]?overlay/, 'silk-bottom'],
  [/in\d+[._]?cu|inner/, 'copper-inner'],
  [/f[._]cu\b|top[._ -]?(layer|copper)|copper[._ -]?top/, 'copper-top'],
  [/b[._]cu\b|bot(tom)?[._ -]?(layer|copper)|copper[._ -]?bot/, 'copper-bottom'],
];

/** X2 attribute value, for example "Copper,L1,Top". */
export function kindFromFileFunction(f: string): LayerKind | null {
  const p = f.split(',');
  const side = p.some((s) => /^top$/i.test(s)) ? 'top' : p.some((s) => /^bot/i.test(s)) ? 'bottom' : null;
  switch (p[0].toLowerCase()) {
    case 'copper': return side ? `copper-${side}` : 'copper-inner';
    case 'soldermask': return side ? `mask-${side}` : null;
    case 'legend': return side ? `silk-${side}` : null;
    case 'paste': return side ? `paste-${side}` : null;
    case 'profile': return 'outline';
    case 'plated': case 'nonplated': return 'drill';
    default: return null;
  }
}

export function looksLikeDrill(text: string): boolean {
  const head = text.slice(0, 4000);
  return /^\s*M48\b/m.test(head) || (/^\s*T\d+C[\d.]+/m.test(head) && !head.includes('%FS'));
}

/** `text` is optional: without it only the name counts. */
export function classifyLayer(fileName: string, text?: string): LayerKind {
  const base = (fileName.split(/[\\/]/).pop() ?? fileName).toLowerCase();
  const dot = base.lastIndexOf('.');
  const ext = dot >= 0 ? base.slice(dot + 1) : '';
  const stem = dot >= 0 ? base.slice(0, dot) : base;

  if (['gbrjob', 'pdf', 'png', 'jpg', 'zip', 'rpt', 'csv', 'pos', 'html', 'md'].includes(ext)) return 'other';
  if (text) {
    const m = /(?:%|#@!\s*)TF\.FileFunction,([^*]*)\*/.exec(text);
    if (m) { const k = kindFromFileFunction(m[1]); if (k) return k; }
  }
  if (/^gm\d+$/.test(ext)) return 'outline';
  if (/^g\d+$/.test(ext) || /^gp\d+$/.test(ext)) return 'copper-inner';
  if (EXT[ext]) return EXT[ext];
  for (const [re, kind] of NAME_RULES) if (re.test(stem)) return kind;
  if (text && looksLikeDrill(text)) return 'drill';
  if (!text && ['txt', 'nc', 'cnc'].includes(ext)) return 'drill';
  return 'other';
}
