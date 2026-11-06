/// <reference lib="webworker" />
import { JobBuildError } from './gcode';
import { computeJob, type JobRequest } from './job';

const ctx = self as unknown as DedicatedWorkerGlobalScope;
ctx.onmessage = (ev: MessageEvent<{ id: number; req: JobRequest }>) => {
  const { id, req } = ev.data;
  try {
    const result = computeJob(req);
    const t = result.toolpath;
    ctx.postMessage({ id, result }, [t.xy.buffer, t.power.buffer, t.line.buffer] as Transferable[]);
  } catch (e) {
    ctx.postMessage({ id, error: e instanceof Error ? e.message : String(e), build: e instanceof JobBuildError });
  }
};
