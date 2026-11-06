/**
 * Excellon drill file reader: tools, METRIC/INCH, LZ/TZ, decimal or implicit coordinates, modal
 * coordinates, G85 slots and simple routed slots (M15/M16). Result in millimetres, Y up.
 */
import type { Box, Pt } from '@/core/model';

export interface DrillHit { x: number; y: number; dia: number; tool: number }
export interface DrillSlot { a: Pt; b: Pt; dia: number; tool: number }
export interface ExcellonResult { units: 'mm' | 'inch'; tools: Map<number, number>; hits: DrillHit[]; slots: DrillSlot[]; bounds: Box | null; warnings: string[] }

export function parseExcellon(text: string): ExcellonResult {
  const warnings = new Set<string>();
  let unit = 1; let units: 'mm' | 'inch' = 'mm';
  let zeros: 'LZ' | 'TZ' | null = null; // which zeros the file keeps
  let intDigits: number | null = null, decDigits: number | null = null;
  const tools = new Map<number, number>();
  const hits: DrillHit[] = [], slots: DrillSlot[] = [];
  let tool = 0, x = 0, y = 0;
  let incremental = false, routing = false, plunged = false, repeatSeen = false, implicit = false;

  const digitsOf = () => intDigits != null && decDigits != null ? { i: intDigits, d: decDigits } : units === 'inch' ? { i: 2, d: 4 } : { i: 3, d: 3 };
  const coord = (raw: string): number => {
    if (raw.includes('.')) return parseFloat(raw) * unit;
    implicit = true;
    const neg = raw.startsWith('-'); const digits = raw.replace(/^[+-]/, '');
    const { i, d } = digitsOf();
    // LZ: leading zeros kept, trailing ones may be missing, so the point counts from the left.
    // TZ (and no statement): the point counts from the right.
    const v = zeros === 'LZ' ? parseInt(digits.padEnd(i + d, '0'), 10) / 10 ** d : parseInt(digits, 10) / 10 ** d;
    return (neg ? -v : v) * unit;
  };
  const readXY = (s: string, fromX: number, fromY: number) => {
    const mx = /X([+-]?[\d.]+)/.exec(s), my = /Y([+-]?[\d.]+)/.exec(s);
    return { x: mx ? (incremental ? fromX : 0) + coord(mx[1]) : fromX, y: my ? (incremental ? fromY : 0) + coord(my[1]) : fromY, any: !!(mx || my) };
  };

  for (const rawLine of text.split(/\r?\n|\r/)) {
    const line = rawLine.trim();
    if (!line) continue;
    if (line.startsWith(';')) {
      const a = /FILE_FORMAT\s*=\s*(\d+):(\d+)/i.exec(line) ?? /FORMAT\s*=?\s*\{\s*(\d+):(\d+)/i.exec(line);
      if (a) { intDigits = +a[1]; decDigits = +a[2]; }
      continue;
    }
    let up = line.toUpperCase();
    if (up.startsWith('METRIC') || up.startsWith('INCH') || up === 'M71' || up === 'M72') {
      if (up.startsWith('INCH') || up === 'M72') { unit = 25.4; units = 'inch'; } else { unit = 1; units = 'mm'; }
      if (up.includes('LZ')) zeros = 'LZ'; else if (up.includes('TZ')) zeros = 'TZ';
      const f = /,(0+)\.(0+)/.exec(up);
      if (f) { intDigits = f[1].length; decDigits = f[2].length; }
      continue;
    }
    if (up === 'ICI,ON' || up === 'G91') { incremental = true; continue; }
    if (up === 'ICI,OFF' || up === 'G90') { incremental = false; continue; }
    if (up.startsWith('M30') || up === 'M00') break;
    if (up === 'M15') { plunged = true; continue; }
    if (up === 'M16' || up === 'M17') { plunged = false; continue; }
    if (up === 'G05') { routing = false; continue; }
    if (up.startsWith('M48') || up === '%' || /^(FMAT|VER|ATC|TCST|DETECT|AFS|CCW|CP|BLKD|SBK|SG|OSTOP|PF|LN|EXTC|MI)/.test(up)) continue;

    const tdef = /^T(\d+)(?:[A-Z][\d.]*?)*?C([\d.]+)/.exec(up);
    if (tdef) { tool = parseInt(tdef[1], 10); tools.set(tool, parseFloat(tdef[2]) * unit); continue; }
    const tsel = /^T(\d+)$/.exec(up);
    if (tsel) { tool = parseInt(tsel[1], 10); if (tool && !tools.has(tool)) warnings.add(`Werkzeug T${tool} hat keinen Durchmesser.`); continue; }

    if (/^R\d+/.test(up)) { repeatSeen = true; up = up.replace(/^R\d+/, ''); }

    const g85 = /^(.*)G85(.*)$/.exec(up);
    if (g85) {
      const a = readXY(g85[1], x, y), b = readXY(g85[2], a.x, a.y);
      slots.push({ a: { x: a.x, y: a.y }, b: { x: b.x, y: b.y }, dia: tools.get(tool) ?? 0, tool });
      x = b.x; y = b.y;
      continue;
    }
    const gm = /^G0?([0123])/.exec(up);
    if (gm) routing = true;
    const p = readXY(up, x, y);
    if (!p.any) { if (!/^[GM]/.test(up)) warnings.add(`Zeile nicht verstanden: ${line.slice(0, 30)}`); continue; }
    if (routing) {
      if (plunged) slots.push({ a: { x, y }, b: { x: p.x, y: p.y }, dia: tools.get(tool) ?? 0, tool });
    } else {
      hits.push({ x: p.x, y: p.y, dia: tools.get(tool) ?? 0, tool });
    }
    x = p.x; y = p.y;
  }
  if (repeatSeen) warnings.add('Wiederholungen (R) werden nicht unterstützt: nur der erste Treffer zählt.');
  if (implicit && zeros == null && intDigits == null) warnings.add('Datei nennt kein Zahlenformat: Standardformat angenommen, Maße prüfen.');
  const all = [...hits.map((h) => ({ x: h.x, y: h.y, d: h.dia })), ...slots.flatMap((s) => [{ ...s.a, d: s.dia }, { ...s.b, d: s.dia }])];
  const bounds: Box | null = all.length ? {
    minX: Math.min(...all.map((p) => p.x - p.d / 2)), minY: Math.min(...all.map((p) => p.y - p.d / 2)),
    maxX: Math.max(...all.map((p) => p.x + p.d / 2)), maxY: Math.max(...all.map((p) => p.y + p.d / 2)) } : null;
  return { units, tools, hits, slots, bounds, warnings: [...warnings] };
}
