import { piTransport } from '@/platform';
import type { MachineStatus } from './types';
import { PiError } from './types';

/** Thin client for the Pi API (docs/PI_API_REFERENZ.md). The Pi enforces every limit; this only transports. */
const dec = new TextDecoder(), enc = new TextEncoder();
let baseUrl = 'http://192.168.2.89:8080';
export const getBaseUrl = () => baseUrl;
export const setBaseUrl = (u: string) => { baseUrl = u.replace(/\/+$/, ''); };

async function request(method: string, path: string, opts: { contentType?: string; body?: Uint8Array | string; timeoutMs?: number } = {}) {
  const body = typeof opts.body === 'string' ? enc.encode(opts.body) : opts.body;
  let r;
  try { r = await piTransport(baseUrl, { method, path, contentType: opts.contentType, body, timeoutMs: opts.timeoutMs }); }
  catch (e) { throw new PiError(`Pi nicht erreichbar: ${(e as Error).message ?? e}`, 0); }
  if (r.status >= 400) {
    let msg = `Fehler ${r.status}`;
    try { msg = JSON.parse(dec.decode(r.body)).error ?? msg; } catch { /* HTML from older Pi versions */ }
    throw new PiError(msg, r.status);
  }
  return r;
}
const json = <T,>(r: { body: Uint8Array }): T => JSON.parse(dec.decode(r.body)) as T;
const form = (f: Record<string, string | number | boolean | undefined>) =>
  new URLSearchParams(Object.entries(f).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)])).toString();

export const pi = {
  raw: request,
  get: async <T,>(path: string, timeoutMs = 8000) => json<T>(await request('GET', path, { timeoutMs })),
  getText: async (path: string) => dec.decode((await request('GET', path)).body),
  getBytes: async (path: string, timeoutMs = 15000) => request('GET', path, { timeoutMs }),
  putJson: async <T,>(path: string, data: unknown) => json<T>(await request('PUT', path, { contentType: 'application/json', body: JSON.stringify(data) })),
  postJson: async <T,>(path: string, data: unknown) => json<T>(await request('POST', path, { contentType: 'application/json', body: JSON.stringify(data) })),
  putBytes: async <T,>(path: string, bytes: Uint8Array, contentType: string) => json<T>(await request('PUT', path, { contentType, body: bytes, timeoutMs: 60000 })),
  del: async <T,>(path: string) => json<T>(await request('DELETE', path)),

  status: (timeoutMs = 3000) => pi.get<MachineStatus>('/api/status', timeoutMs),

  /**
   * POST /api/action. Do NOT call this directly from UI for anything that moves the machine or the
   * laser: use `machineAction` (src/pi/actions.ts), which enforces the go dialog.
   * Long moves block their request, so the timeout is generous.
   */
  action: async <T = { message: string }>(op: string, fields: Record<string, string | number | boolean | undefined> = {}, timeoutMs = 180000) =>
    json<T>(await request('POST', '/api/action', { contentType: 'application/x-www-form-urlencoded', body: form({ op, ...fields }), timeoutMs })),

  settings: async (fields: Record<string, string | number | boolean>) =>
    json<{ message: string }>(await request('POST', '/api/settings', { contentType: 'application/x-www-form-urlencoded', body: form(fields) })),

  /** POST /api/upload: multipart, field `file`. Name must end in .gcode. */
  upload: async (name: string, gcode: string) => {
    const boundary = '----lumacut' + Math.random().toString(16).slice(2);
    const head = `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${name}"\r\nContent-Type: text/plain\r\n\r\n`;
    return json<{ message: string }>(await request('POST', '/api/upload', { contentType: `multipart/form-data; boundary=${boundary}`, body: head + gcode + `\r\n--${boundary}--\r\n`, timeoutMs: 120000 }));
  },
};

/** NOT-AUS: no gate, short timeout, sent a second time if the first attempt fails. */
export async function estop() {
  try { return await pi.action('estop', {}, 3000); }
  catch { return pi.action('estop', {}, 3000); }
}
export const jobNameFrom = (title: string) => {
  const base = title.normalize('NFKD').replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '') || 'Auftrag';
  return base.slice(0, 60) + '.gcode';
};
