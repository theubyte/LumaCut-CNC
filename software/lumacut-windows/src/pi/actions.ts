import { create } from 'zustand';
import { toast } from '@/ui/kit';
import { pi } from './client';
import { refreshNow } from './machine';

/**
 * The ONE way the UI triggers machine actions. Rule (docs/STAND.md §4): every laser or motion job
 * needs an explicit go, "Hände raus, Deckel zu, Brille". Exempt: single jog steps, light, exhaust, abort, NOT-AUS.
 * Service ops that fire the laser directly (service_laser, ttl_test, supply_test, ...) are deliberately not offered by this app.
 */
export type GoKind = 'move' | 'laser';
export interface GoRequest { title: string; detail?: string; kind: GoKind; okLabel?: string }

const GATE: Record<string, GoRequest> = {
  home: { title: 'Referenzfahrt starten?', detail: 'Alle Achsen fahren an die Endschalter. Der Kopf muss frei stehen.', kind: 'move' },
  park: { title: 'Kopf parken?', detail: 'Der Kopf fährt in die Park-Ecke.', kind: 'move' },
  moveto: { title: 'Zu dieser Position fahren?', kind: 'move' },
  probe: { title: 'Abtasten starten?', detail: 'Der Kopf senkt sich auf das Material. Liegt das Objekt noch an derselben Stelle? Nach jedem Verschieben neu scannen.', kind: 'move' },
  bedmap: { title: 'Bettkarte messen?', detail: 'Das leere Bett wird an vielen Punkten abgetastet. Bett frei räumen.', kind: 'move' },
  autorun: { title: 'Auftrag starten?', detail: 'Referenzieren, Abtasten, Höhenkorrektur, Lasern, Parken laufen automatisch.', kind: 'laser' },
  start: { title: 'Auftrag starten?', kind: 'laser' },
  queue_run: { title: 'Warteschlange starten?', detail: 'Alle Aufträge laufen nacheinander.', kind: 'laser' },
  frame: { title: 'Rahmen fahren?', detail: 'Der Kopf fährt den Umriss ab. Ist auf dem Pi Glimmen eingestellt, läuft dabei ein schwacher Laserpunkt.', kind: 'laser' },
  matcal: { title: 'Materialtest starten?', detail: 'Es wird gelasert. Testfläche am Rand wählen, kein ungetestetes empfindliches Material unter dem Kopf.', kind: 'laser' },
  motion_test: { title: 'Bewegungstest starten?', detail: 'Der Kopf fährt schnell hin und her.', kind: 'move' },
  line_laser: { title: 'Linienlaser umschalten?', kind: 'laser' },
};
/** Ops that pass without a go. Anything not listed here or in GATE is refused, so a new op cannot slip through. */
const FREE = new Set(['jog', 'light', 'exhaust', 'abort', 'estop', 'estop_reset', 'connect', 'info', 'position', 'endstops', 'report',
  'bedmap_clear', 'origin_set', 'origin_clear', 'place', 'place_clear', 'queue_add', 'queue_pause', 'queue_skip', 'queue_remove', 'queue_clear',
  'motion_limits', 'app_update_check', 'firmware_update_check']);

interface GoState { req: (GoRequest & { resolve(v: boolean): void }) | null }
export const useGo = create<GoState>(() => ({ req: null }));
/** Ask for the go directly (e.g. before several steps that belong together). */
export const askGo = (r: GoRequest) => new Promise<boolean>((resolve) => useGo.setState({ req: { ...r, resolve } }));

export interface ActionOpts { go?: Partial<GoRequest>; quiet?: boolean; timeoutMs?: number }
/** Returns the Pi's reply, or null when the operator said no. Errors are shown as toast and rethrown. */
export async function machineAction<T = { message: string }>(op: string, fields: Record<string, string | number | boolean | undefined> = {}, opts: ActionOpts = {}): Promise<T | null> {
  const gate = GATE[op];
  if (!gate && !FREE.has(op)) throw new Error(`Aktion ${op} ist in dieser App nicht freigegeben`);
  if (gate && !(await askGo({ ...gate, ...opts.go }))) return null;
  try {
    const r = await pi.action<T>(op, fields, opts.timeoutMs);
    const msg = (r as { message?: string }).message;
    if (msg && !opts.quiet) toast(msg, 'ok');
    return r;
  } catch (e) {
    toast((e as Error).message, 'bad');
    throw e;
  } finally { refreshNow(); }
}
