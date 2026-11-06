import { Bed, fromMachine, type Pt, toMachine } from '@/core/model';
import type { MachineStatus } from '@/pi/types';

/**
 * Why a control is locked, as a sentence with the next step. Null means free.
 * The Pi checks everything itself; these only explain up front what it would refuse.
 */
const ACTIVE_JOB = ['homing', 'probing', 'focusing', 'running', 'finishing', 'parking'];
const TRANSIENT_OWNERS = new Set(['Frei', '', 'monitor', 'web']);

/** Controller reachable and not held by anyone: light, exhaust and everything below need this. */
export function freeLock(s: MachineStatus, online: boolean): string | null {
  if (!online) return 'Pi nicht erreichbar. Adresse unter Optionen prüfen.';
  if (s.emergency_latched) return 'Not-Aus aktiv. SKR zurücksetzen, dann quittieren und neu referenzieren.';
  if (s.connected === false) return 'Steuerung nicht verbunden. USB-Kabel zum SKR prüfen.';
  if (['uploading', 'rebooting'].includes((s.firmware_update as { state?: string } | undefined)?.state ?? '')) return 'Firmware-Update läuft. Bitte abwarten.';
  if (ACTIVE_JOB.includes(s.job?.state ?? '')) return `Auftrag „${s.job?.file ?? ''}“ läuft. Erst abwarten oder abbrechen.`;
  if (['running', 'starting'].includes(s.frame?.state ?? '')) return 'Rahmenfahrt läuft. Erst abwarten oder abbrechen.';
  const owner = s.owner ?? 'Frei';
  if (owner === 'lightburn') return 'LightBurn hat die Steuerung. Erst dort trennen.';
  if (!TRANSIENT_OWNERS.has(owner)) return `Steuerung belegt durch ${owner}. Bitte abwarten.`;
  return null;
}
/** Homing: free, and the mechanics have been released. */
export function homeLock(s: MachineStatus, online: boolean): string | null {
  const free = freeLock(s, online);
  if (free) return free;
  if (s.config?.validated === false) return 'Mechanik nicht freigegeben. Die Freigabe erfolgt vor Ort an der Maschine.';
  return null;
}
/** Every move needs a valid reference. */
export function moveLock(s: MachineStatus, online: boolean): string | null {
  const home = homeLock(s, online);
  if (home) return home;
  if (!s.homed) {
    const lost = (s.reference as { lost?: string } | undefined)?.lost;
    return lost ? `Referenz verloren: ${lost} Erst referenzieren.` : 'Nicht referenziert. Erst die Referenzfahrt starten.';
  }
  return null;
}
/** The Pi refuses any Z move while no surface is measured (transport.py). */
export function zLock(s: MachineStatus, online: boolean): string | null {
  const move = moveLock(s, online);
  if (move) return move;
  if (s.workpiece_surface_z == null) return 'Z erst nach dem Abtasten: Ohne gemessene Oberfläche lässt der Pi keine Z-Fahrt zu.';
  return null;
}
export function probeLock(s: MachineStatus, online: boolean): string | null {
  const move = moveLock(s, online);
  if (move) return move;
  if (s.z_probe_supported === false) return 'Die Firmware meldet keinen Z-Taster.';
  if (s.probe_xy_offset_mm == null) return 'Taster-Versatz fehlt. Unter Kalibrieren eintragen.';
  return null;
}

export interface Headline { tone: 'ok' | 'warn' | 'bad' | 'busy'; title: string; text: string }
/** State in plain words: same terms as StatusText.kt on Android, Not-Aus first because it can be quit here. */
export function headline(s: MachineStatus, online: boolean, url: string): Headline {
  if (!online) return { tone: 'bad', title: 'Pi nicht erreichbar', text: `Netzwerk und Adresse ${url.replace(/^https?:\/\//, '')} prüfen.` };
  if (s.emergency_latched) return { tone: 'bad', title: 'Not-Aus aktiv', text: 'SKR zurücksetzen (Reset-Taste oder kurz stromlos), dann quittieren.' };
  if (s.connected === false) return { tone: 'bad', title: 'Steuerung getrennt', text: s.fault || 'USB-Verbindung zum SKR fehlt.' };
  const fw = s.firmware_update as { state?: string; message?: string } | undefined;
  if (['uploading', 'rebooting'].includes(fw?.state ?? '')) return { tone: 'busy', title: 'Firmware-Update', text: fw?.message ?? '' };
  if (['running', 'starting'].includes(s.frame?.state ?? '')) return { tone: 'busy', title: 'Rahmenfahrt', text: `${s.frame?.line ?? 0} von ${s.frame?.total ?? 0}` };
  const j = s.job;
  if (j?.state === 'homing') return { tone: 'busy', title: 'Referenzfahrt', text: j.file ?? '' };
  if (j?.state === 'probing') return { tone: 'busy', title: 'Wird abgetastet', text: `${j.file ?? ''}${j.probe ? ` · Punkt ${j.probe.done} von ${j.probe.total}` : ''}` };
  if (ACTIVE_JOB.includes(j?.state ?? '')) return { tone: 'busy', title: 'Auftrag läuft', text: j?.file ?? '' };
  if (s.owner === 'lightburn') return { tone: 'warn', title: 'LightBurn verbunden', text: 'Steuerung über die App erst nach dem Trennen.' };
  if (!TRANSIENT_OWNERS.has(s.owner ?? 'Frei')) return { tone: 'busy', title: 'Beschäftigt', text: `Belegt durch ${s.owner}` };
  if (s.owner === 'web' || s.state === 'Busy') return { tone: 'busy', title: 'In Bewegung', text: 'Die Maschine fährt gerade.' };
  if (!s.homed) {
    const lost = (s.reference as { lost?: string } | undefined)?.lost;
    if (lost) return { tone: 'warn', title: 'Referenz verloren', text: lost };
    return { tone: 'warn', title: 'Nicht referenziert', text: 'Vor dem Arbeiten die Referenzfahrt starten.' };
  }
  if (s.workpiece_surface_z == null) return { tone: 'ok', title: 'Bereit', text: 'Referenziert. Werkstück noch nicht abgetastet.' };
  return { tone: 'ok', title: 'Bereit', text: 'Referenziert und abgetastet.' };
}

export const JOG_STEPS = [0.1, 1, 10] as const;
export type JogStep = (typeof JOG_STEPS)[number];
export type JogDir = 'left' | 'right' | 'up' | 'down';

/**
 * A jog on screen, as seen from the door: right = work X+, down = work Y+. The Pi wants machine axes,
 * and the only conversion is toMachine. Android: right = X−, left = X+, up = Y−, down = Y+.
 */
export function jogCommand(dir: JogDir, step: JogStep): { axis: 'X' | 'Y'; distance: number } {
  const d: Pt = { left: { x: -step, y: 0 }, right: { x: step, y: 0 }, up: { x: 0, y: -step }, down: { x: 0, y: step } }[dir];
  const a = toMachine({ x: 0, y: 0 }), b = toMachine(d);
  const dx = +(b.x - a.x).toFixed(3), dy = +(b.y - a.y).toFixed(3);
  return dx !== 0 ? { axis: 'X', distance: dx } : { axis: 'Y', distance: dy };
}

export const headWork = (s: MachineStatus): Pt | null => s.position ? fromMachine({ x: s.position[0], y: s.position[1] }) : null;

/** Target for "Zu Position fahren" in work coordinates; a sentence when out of travel. */
export function moveTarget(work: Pt): { machine: Pt } | { error: string } {
  if (!(work.x >= 0 && work.x <= Bed.width && work.y >= 0 && work.y <= Bed.height)) return { error: `Ziel außerhalb der Arbeitsfläche (X 0 bis ${Bed.width}, Y 0 bis ${Bed.height} mm)` };
  return { machine: toMachine(work) };
}

/** Number with German decimal comma. */
export const de = (v: number | null | undefined, digits = 1) => v == null || !Number.isFinite(v) ? '–' : v.toLocaleString('de-DE', { minimumFractionDigits: digits, maximumFractionDigits: digits });
