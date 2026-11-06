import { create } from 'zustand';
import { configureBed } from '@/core/model';
import { pi, setBaseUrl } from './client';
import type { MachineStatus } from './types';

/**
 * Live machine state: polls /api/status while the app runs. All UI reads from here,
 * so one request per interval serves every view.
 */
interface MachineState {
  online: boolean; status: MachineStatus; lastError: string | null; lastSeen: number;
}
export const useMachine = create<MachineState>(() => ({ online: false, status: {}, lastError: null, lastSeen: 0 }));

let timer: ReturnType<typeof setTimeout> | null = null;
let gen = 0;

/** A job in the active phases: nothing else may start. */
export const jobActive = (s: MachineStatus) => ['homing', 'probing', 'focusing', 'running', 'finishing', 'parking'].includes(s.job?.state ?? '');
export const frameActive = (s: MachineStatus) => ['running', 'starting'].includes(s.frame?.state ?? '');
export const machineFree = (s: MachineStatus) => !!s.connected && !s.busy && (s.owner ?? 'Frei') === 'Frei' && !s.emergency_latched && !jobActive(s) && !frameActive(s);

export function refreshNow() { void tick(gen, false); }

async function tick(g: number, schedule = true) {
  try {
    const status = await pi.status();
    if (g !== gen) return;
    const t = status.config?.travels; const p = status.park_corner_mm;
    configureBed(t?.x, t?.y, p?.x, p?.y);
    useMachine.setState({ online: true, status, lastError: null, lastSeen: Date.now() });
  } catch (e) {
    if (g !== gen) return;
    useMachine.setState({ online: false, lastError: (e as Error).message });
  }
  if (!schedule) return;
  const busy = jobActive(useMachine.getState().status);
  timer = setTimeout(() => void tick(g), busy ? 500 : 1000);
}
export function startPolling(baseUrl: string) {
  setBaseUrl(baseUrl);
  if (timer) clearTimeout(timer);
  gen += 1;
  useMachine.setState({ online: false, status: {}, lastError: null });
  void tick(gen);
}
