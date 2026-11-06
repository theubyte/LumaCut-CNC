import { type Box, type Doc, Limits, insideWork, layerLabel, touchesPark, worldBounds, isImage } from '@/core/model';
import type { Motion } from '@/core/gcode';
import type { CompactToolpath } from '@/core/toolpath';
import { frameActive, jobActive } from '@/pi/machine';
import type { MachineStatus } from '@/pi/types';

export type CheckTone = 'bad' | 'warn' | 'info';
export type CheckTarget = 'material' | 'motiv' | 'maschine';
export interface Check { id: string; tone: CheckTone; text: string; go?: { label: string; dest: CheckTarget } }

export interface MaterialChoice { name: string; thickness_mm: number }

/** The sentence that says why the machine cannot start, with the next step. Null when it can. */
export function machineBlocker(s: MachineStatus, online: boolean): string | null {
  if (!online) return 'Der Pi ist nicht erreichbar: WLAN und Pi-Adresse prüfen.';
  if (s.emergency_latched) return 'Not-Aus ist aktiv: Ursache beseitigen, dann oben „Not-Aus quittieren“.';
  if (s.connected === false) return 'Die Steuerung ist nicht verbunden: USB-Kabel am Pi prüfen.';
  if (s.owner && s.owner !== 'Frei' && s.owner !== 'monitor' && !jobActive(s) && !frameActive(s)) {
    if (s.owner === 'job' || s.owner === 'frame' || s.owner === 'web' || s.owner === 'shutdown') return 'Die Maschine ist noch beschäftigt: einen Moment warten.';
    return `Der Laser wird gerade von ${s.owner === 'lightburn' ? 'LightBurn' : s.owner} benutzt: dort zuerst trennen.`;
  }
  if (s.config && s.config.validated === false) return 'Die Mechanik ist noch nicht freigegeben: unter Maschine prüfen und freigeben.';
  return null;
}

export interface CheckInput {
  /** Elements of the plate to laser, on outputting layers. Absent for a saved job. */
  doc?: Doc | null;
  plate?: number;
  multi?: boolean;
  toolpath: CompactToolpath | null;
  /** Writer or parser refused the job. */
  buildError?: string | null;
  /** The Pi refused the upload, the start or the frame. */
  rejection?: string | null;
  status: MachineStatus;
  online: boolean;
  motion?: Motion | null;
  /** undefined: still unknown, no statement. null: nothing chosen. */
  material?: MaterialChoice | null;
  /** undefined: unknown, no statement. */
  materialTested?: boolean;
  bed: { width: number; height: number };
}

const fmt = (n: number) => n.toLocaleString('de-DE', { maximumFractionDigits: 1 });
const label = (e: { text: string | null; kind: string }) => `„${e.text?.trim() || e.kind}“`;

/** Everything that speaks against this start, most serious first. Pure, so the sentences are testable. */
export function computeChecks(i: CheckInput): Check[] {
  const out: Check[] = [];
  const add = (id: string, tone: CheckTone, text: string, go?: Check['go']) => { if (!out.some((c) => c.id === id)) out.push({ id, tone, text, go }); };

  if (i.rejection) add('rejected', 'bad', i.rejection);
  const blocker = machineBlocker(i.status, i.online);
  if (blocker) add('machine', 'bad', blocker, { label: 'Zur Maschine', dest: 'maschine' });
  if (i.material === null) add('material', 'bad', 'Kein Material gewählt: die Stärke bestimmt die Fahrhöhe, der Pi startet ohne sie nicht.', { label: 'Material wählen', dest: 'material' });

  const doc = i.doc;
  let ownFinding = false;
  if (doc && !doc.elements.length) add('nothing', 'bad', i.multi ? `Platte ${(i.plate ?? 0) + 1} ist leer: eine andere Platte wählen.` : 'Noch kein Motiv: zuerst etwas gestalten.', { label: 'Zum Motiv', dest: 'motiv' });
  if (doc) {
    const active = new Set(doc.layers.filter((l) => l.output && l.visible).map((l) => l.id));
    const used = new Set<string>();
    if (doc.elements.length && !doc.elements.some((e) => active.has(e.layerId))) add('off', 'bad', 'Alle Elemente liegen auf ausgeschalteten Ebenen: im Motiv eine Ebene einschalten.', { label: 'Zum Motiv', dest: 'motiv' });
    for (const e of doc.elements) {
      if (!active.has(e.layerId)) continue;
      used.add(e.layerId);
      const b = worldBounds(e);
      if (b && !insideWork(b)) { add('outside', 'bad', `${label(e)} ragt über die Arbeitsfläche hinaus: im Motiv verschieben oder verkleinern.`, { label: 'Zum Motiv', dest: 'motiv' }); ownFinding = true; }
      if (b && touchesPark(b)) { add('park', 'bad', `${label(e)} liegt in der Park-Ecke (oben rechts): dort wird nicht gelasert.`, { label: 'Zum Motiv', dest: 'motiv' }); ownFinding = true; }
      if (isImage(e) && Math.abs(e.transform.rotation) > 1e-6) { add('rotated', 'bad', `Das Bild ${label(e)} ist gedreht: gedrehte Bilder gehen noch nicht, Drehung auf 0° setzen.`, { label: 'Zum Motiv', dest: 'motiv' }); ownFinding = true; }
    }
    const maxFeed = i.motion ? i.motion.speed * 60 : null;
    for (const l of doc.layers) {
      if (!used.has(l.id)) continue;
      if (maxFeed != null && l.speed > maxFeed + 1e-6) { add(`fast-${l.id}`, 'bad', `Ebene „${layerLabel(l)}“ ist zu schnell: ${fmt(l.speed)} mm/min, die Maschine fährt höchstens ${fmt(maxFeed)} mm/min.`, { label: 'Zum Motiv', dest: 'motiv' }); ownFinding = true; }
      if (l.powerPct > 0 && l.powerPct < Limits.MIN_RELIABLE_POWER_PCT) add(`weak-${l.id}`, 'warn', `Ebene „${layerLabel(l)}“ hat nur ${fmt(l.powerPct)} % Leistung: unter ${Limits.MIN_RELIABLE_POWER_PCT} % zündet der Laser nicht sicher.`);
    }
  }
  if (i.buildError && !ownFinding) add('build', 'bad', i.buildError);

  const tp = i.toolpath;
  if (tp?.bounds && !ownFinding) {
    const b = tp.bounds;
    // Bounds are machine mm; the park corner sits at machine 0/0.
    const work: Box = { minX: i.bed.width - b.maxX, minY: b.minY, maxX: i.bed.width - b.minX, maxY: b.maxY };
    if (!insideWork(work)) add('outside', 'bad', 'Der Auftrag ragt über die Arbeitsfläche hinaus.');
    else if (touchesPark(work)) add('park', 'bad', 'Der Auftrag berührt die Park-Ecke (oben rechts): dort wird nicht gelasert.');
  }
  if (tp && !tp.bounds) add('empty', 'bad', 'Im Auftrag ist keine Laserbahn: es gäbe nichts zu lasern.');
  for (const [n, w] of (tp?.stats.warnings ?? []).entries()) if (!/Park-Ecke|Keine Laserbewegung/.test(w)) add(`stat-${n}`, 'warn', w);

  if (i.material && i.materialTested === false) add('untested', 'warn', `Ungetestetes Material: für „${i.material.name}“ gibt es keine eigenen Werte. Erst einen Materialtest machen.`, { label: 'Zum Material', dest: 'material' });
  if (!doc?.elements.length && doc) return out;
  add('moved', 'info', 'Objekt verschoben? Dann vor dem Start neu scannen, sonst sitzt der Laser daneben.');
  return out;
}

export const blocksStart = (checks: Check[]) => checks.some((c) => c.tone === 'bad');
