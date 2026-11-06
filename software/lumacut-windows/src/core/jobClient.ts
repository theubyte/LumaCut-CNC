/**
 * Auftrag bauen, ohne dass die Oberfläche hängt. Ein neuer Aufruf bricht den laufenden ab: der alte
 * Worker wird beendet, sein Promise endet mit JobAborted.
 */
import { JobBuildError, type Motion } from './gcode';
import { computeJob, type JobRequest, type JobResult } from './job';
import { Bed, type Doc } from './model';

export type { JobResult } from './job';
export class JobAborted extends Error { override name = 'JobAborted'; }

interface Pending { id: number; resolve: (r: JobResult) => void; reject: (e: Error) => void }
let worker: Worker | null = null;
let pending: Pending | null = null;
let nextId = 1;

function stopWorker() { worker?.terminate(); worker = null; }

export function cancelJob(): void {
  const p = pending;
  if (!p) return;
  pending = null;
  stopWorker();
  p.reject(new JobAborted('Abgebrochen'));
}

function getWorker(): Worker {
  if (worker) return worker;
  const w = new Worker(new URL('./job.worker.ts', import.meta.url), { type: 'module' });
  w.onmessage = (ev: MessageEvent<{ id: number; result?: JobResult; error?: string; build?: boolean }>) => {
    const p = pending;
    if (!p || p.id !== ev.data.id) return;
    pending = null;
    if (ev.data.result) p.resolve(ev.data.result);
    else p.reject(ev.data.build ? new JobBuildError(ev.data.error) : new Error(ev.data.error));
  };
  w.onerror = (ev) => {
    const p = pending;
    pending = null;
    stopWorker();
    p?.reject(new Error(ev.message || 'Auftrag konnte nicht gebaut werden'));
  };
  worker = w;
  return w;
}

/** plate: Standard die aktive Platte. Rechnet mit den aktuellen Maschinenmaßen (Bed). */
export function buildJob(doc: Doc, plate: number = doc.activePlate, motion?: Motion, appVersion?: string): Promise<JobResult> {
  cancelJob();
  const req: JobRequest = { doc, plate, motion, appVersion, bed: { width: Bed.width, height: Bed.height, parkX: Bed.parkX, parkY: Bed.parkY } };
  const id = nextId++;
  return new Promise<JobResult>((resolve, reject) => {
    pending = { id, resolve, reject };
    if (typeof Worker === 'undefined') {
      // Tests unter Node: gleiche Rechnung, nur ohne eigenen Thread.
      setTimeout(() => {
        if (pending?.id !== id) return;
        pending = null;
        try { resolve(computeJob(req)); } catch (e) { reject(e as Error); }
      }, 0);
      return;
    }
    getWorker().postMessage({ id, req });
  });
}
