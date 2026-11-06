/**
 * Everything that differs between the installed app (Tauri) and a plain browser (tests, screenshots).
 * Features use only this module for files, fonts and Pi transport; never import @tauri-apps elsewhere.
 */
export const isTauri = () => '__TAURI_INTERNALS__' in window;

export interface PiResponse { status: number; contentType: string; body: Uint8Array }
export interface PiRequest { method: string; path: string; contentType?: string; body?: Uint8Array; timeoutMs?: number }

/** One HTTP request to the Pi. In the app through Rust (no CORS, no Origin header), in a browser through the Vite proxy. */
export async function piTransport(baseUrl: string, req: PiRequest): Promise<PiResponse> {
  if (isTauri()) {
    const { invoke } = await import('@tauri-apps/api/core');
    const raw = await invoke<ArrayBuffer>('pi_request', req.body ?? new Uint8Array(0), {
      headers: {
        'x-lc-base': baseUrl, 'x-lc-method': req.method, 'x-lc-path': encodeURI(req.path),
        'x-lc-ctype': req.contentType ?? '', 'x-lc-timeout': String(req.timeoutMs ?? 8000),
      },
    });
    // Frame from Rust: u16 status, u16 content-type length, content-type, body.
    const u = new Uint8Array(raw); const dv = new DataView(raw);
    const status = dv.getUint16(0, true), n = dv.getUint16(2, true);
    return { status, contentType: new TextDecoder().decode(u.subarray(4, 4 + n)), body: u.subarray(4 + n) };
  }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), req.timeoutMs ?? 8000);
  try {
    const r = await fetch(req.path, { method: req.method, signal: ctl.signal,
      headers: req.contentType ? { 'Content-Type': req.contentType } : undefined, body: req.body && req.body.length ? (req.body as BodyInit) : undefined });
    return { status: r.status, contentType: r.headers.get('content-type') ?? '', body: new Uint8Array(await r.arrayBuffer()) };
  } finally { clearTimeout(timer); }
}

export interface FileFilter { name: string; extensions: string[] }
export interface PickedFile { name: string; path?: string; bytes: Uint8Array }

export async function pickFiles(filters: FileFilter[], multiple = false): Promise<PickedFile[]> {
  if (isTauri()) {
    const { open } = await import('@tauri-apps/plugin-dialog');
    const { readFile } = await import('@tauri-apps/plugin-fs');
    const sel = await open({ filters, multiple });
    const paths = sel == null ? [] : Array.isArray(sel) ? sel : [sel];
    return Promise.all(paths.map(async (path) => ({ path, name: path.split(/[\\/]/).pop() ?? path, bytes: await readFile(path) })));
  }
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file'; input.multiple = multiple;
    input.accept = filters.flatMap((f) => f.extensions.map((e) => '.' + e)).join(',');
    input.onchange = async () => resolve(await Promise.all([...(input.files ?? [])].map(async (f) => ({ name: f.name, bytes: new Uint8Array(await f.arrayBuffer()) }))));
    input.oncancel = () => resolve([]);
    input.click();
  });
}

/** Returns the path/name saved to, or null when cancelled. With `path` it writes there without asking. */
export async function saveFile(suggested: string, data: Uint8Array | string, filters: FileFilter[], path?: string): Promise<string | null> {
  const bytes = typeof data === 'string' ? new TextEncoder().encode(data) : data;
  if (isTauri()) {
    const { save } = await import('@tauri-apps/plugin-dialog');
    const { writeFile } = await import('@tauri-apps/plugin-fs');
    const target = path ?? await save({ defaultPath: suggested, filters });
    if (!target) return null;
    await writeFile(target, bytes);
    return target;
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([bytes as BlobPart]));
  a.download = suggested; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  return suggested;
}

export interface SystemFont { family: string; file: string; bold: boolean; italic: boolean }
/** Installed fonts (Windows). Empty in a browser: use the bundled font then. */
export async function listSystemFonts(): Promise<SystemFont[]> {
  if (!isTauri()) return [];
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke<SystemFont[]>('list_system_fonts');
}
export async function readSystemFont(file: string): Promise<ArrayBuffer> {
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke<ArrayBuffer>('read_system_font', { file });
}

export interface WindowControls { minimize(): void; toggleMaximize(): void; close(): void }
export async function windowControls(): Promise<WindowControls | null> {
  if (!isTauri()) return null;
  const { getCurrentWindow } = await import('@tauri-apps/api/window');
  const w = getCurrentWindow();
  return { minimize: () => void w.minimize(), toggleMaximize: () => void w.toggleMaximize(), close: () => void w.close() };
}

export interface UpdateInfo { available: boolean; current: string; version?: string; notes?: string; sizeBytes?: number; error?: string }
export async function checkForUpdate(): Promise<UpdateInfo> {
  if (!isTauri()) return { available: false, current: 'dev' };
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke<UpdateInfo>('update_check');
}
/** Downloads, checks SHA-256, starts the MSI and closes the app. */
export async function installUpdate(): Promise<void> {
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('update_install');
}
export async function appVersion(): Promise<string> {
  if (!isTauri()) return 'dev';
  const { getVersion } = await import('@tauri-apps/api/app');
  return getVersion();
}
