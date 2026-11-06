import { create } from 'zustand';
import { type Doc, fromJson, toJson } from '@/core/model';
import { useDoc } from '@/store/doc';
import { pickFiles, saveFile, type PickedFile } from '@/platform';
import { confirmDialog, toast } from '@/ui/kit';
import { getBaseUrl, pi } from './client';
import { useMachine } from './machine';
import { PiError } from './types';

/**
 * Projects: the Pi's shelf (/api/projects), the open project every device shares
 * (/api/workspace/project with base_revision, same rules as Android's PiSyncViewModel),
 * a local .lumacut file, and a local autosave.
 * Menu entry points: saveProjectToPi, openProjectDialog, saveLocal, openLocal.
 * Dialogs live in features/start/SyncDialogs.tsx, which also calls startSync.
 */
const DEVICE = 'Windows-PC';
const FILE_FILTERS = [{ name: 'LumaCut-Projekt', extensions: ['lumacut'] }];
const LONG_MS = 60000;

export interface SavedProject { id: string; name: string; bytes: number; updated_at: string; updated_by?: string; elements?: number; layers?: number; plates?: number; replaced?: boolean }
export interface Recovered { json: string; savedAt: number; title: string }
interface ProjectDialogReq { mode: 'save' | 'open'; resolve(done: boolean): void }
interface SyncState { conflict: boolean; dialog: ProjectDialogReq | null; recovered: Recovered | null }
export const useSync = create<SyncState>(() => ({ conflict: false, dialog: null, recovered: null }));

/* ---- Shelf on the Pi ---- */
export const listProjects = async () => (await pi.get<{ projects: SavedProject[] }>('/api/projects')).projects;
export const deleteProject = (id: string) => pi.del<{ message: string }>(`/api/projects/${encodeURIComponent(id)}`);
async function storeProject(name: string, json: string) {
  const r = await pi.raw('POST', `/api/projects?name=${encodeURIComponent(name)}&by=${encodeURIComponent(DEVICE)}`, { contentType: 'application/json', body: json, timeoutMs: LONG_MS });
  return (JSON.parse(new TextDecoder().decode(r.body)) as { project: SavedProject }).project;
}

/** Save dialog: name, list of what is already there. Resolves true once saved. */
export const saveProjectToPi = () => new Promise<boolean>((resolve) => useSync.setState({ dialog: { mode: 'save', resolve } }));
/** Open dialog: the Pi's projects. Resolves true once one is open. */
export const openProjectDialog = () => new Promise<boolean>((resolve) => useSync.setState({ dialog: { mode: 'open', resolve } }));

/** Used by the save dialog. The saved name becomes the title, so the next save offers it again. */
export async function saveNamed(name: string) {
  const title = name.trim();
  const s = useDoc.getState();
  if (title !== s.doc.title) s.commit((d) => ({ ...d, title }));
  const saved = await storeProject(title, toJson(useDoc.getState().doc));
  useDoc.getState().markSaved();
  toast(saved.replaced ? `„${saved.name}“ auf dem Pi ersetzt` : `„${saved.name}“ auf dem Pi gespeichert`, 'ok');
}

/** Used by the open dialog. The project becomes the open one and goes on to the other devices as usual. */
export async function openSaved(p: SavedProject): Promise<boolean> {
  if (!(await okToDiscard())) return false;
  const text = new TextDecoder().decode((await pi.raw('GET', `/api/projects/${encodeURIComponent(p.id)}`, { timeoutMs: LONG_MS })).body);
  useDoc.getState().load(fromJson(text));
  toast(`„${p.name}“ geöffnet`, 'ok');
  schedulePush();
  return true;
}

async function okToDiscard() {
  if (!useDoc.getState().dirty) return true;
  return confirmDialog({ title: 'Änderungen verwerfen?', body: 'Das offene Projekt hat ungespeicherte Änderungen. Sie gehen beim Öffnen verloren.', okLabel: 'Verwerfen', danger: true });
}

/* ---- Local file ---- */
const fileBase = (title: string) => title.replace(/[\\/:*?"<>|]+/g, '-').trim() || 'Projekt';

/** Writes to the known file; asks for a place when there is none or with `saveAs`. */
export async function saveLocal(saveAs = false): Promise<boolean> {
  const { doc, filePath } = useDoc.getState();
  try {
    const target = await saveFile(`${fileBase(doc.title)}.lumacut`, toJson(doc), FILE_FILTERS, saveAs ? undefined : filePath ?? undefined);
    if (!target) return false;
    useDoc.getState().markSaved(target);
    toast(`Gespeichert: ${target.split(/[\\/]/).pop()}`, 'ok');
    return true;
  } catch (e) {
    toast(`Speichern fehlgeschlagen: ${(e as Error).message}`, 'bad');
    return false;
  }
}

export async function openLocal(): Promise<boolean> {
  if (!(await okToDiscard())) return false;
  let picked: PickedFile | undefined;
  try { [picked] = await pickFiles(FILE_FILTERS); }
  catch (e) { toast(`Datei nicht lesbar: ${(e as Error).message}`, 'bad'); return false; }
  if (!picked) return false;
  let doc: Doc;
  try { doc = fromJson(new TextDecoder().decode(picked.bytes)); }
  catch { toast(`„${picked.name}“ ist kein LumaCut-Projekt.`, 'bad'); return false; }
  useDoc.getState().load(doc, picked.path ?? null);
  toast(`„${picked.name}“ geöffnet`, 'ok');
  schedulePush();
  return true;
}

/* ---- The open project, shared with the other devices ---- */
const revKey = () => `lc.sync.${getBaseUrl()}.project`;
const base = () => { try { return Number(localStorage.getItem(revKey())) || 0; } catch { return 0; } };
const setBase = (rev: number) => { try { localStorage.setItem(revKey(), String(rev)); } catch { /* per-device convenience */ } };
const piRevision = () => useMachine.getState().status.sync?.project ?? 0;
const canSync = () => { const m = useMachine.getState(); return m.online && !!m.status.features?.includes('workspace'); };

/** What this device last sent to or took from the Pi; null = nothing yet in this session. */
let synced: string | null = null;
let queue: Promise<unknown> = Promise.resolve();
/** One conversation with the Pi at a time, so a status poll cannot overtake a save. */
const locked = (fn: () => Promise<void>) => { queue = queue.then(fn).catch(() => undefined); return queue; };

async function putProject(json: string, baseRevision: number) {
  const r = await pi.raw('PUT', `/api/workspace/project?base_revision=${baseRevision}&by=${encodeURIComponent(DEVICE)}`, { contentType: 'application/json', body: json, timeoutMs: LONG_MS });
  return (JSON.parse(new TextDecoder().decode(r.body)) as { revision: number }).revision;
}
const hasUnsent = () => {
  const s = useDoc.getState();
  return synced != null ? toJson(s.doc) !== synced : s.dirty;
};
function takeRemote(text: string, rev: number) {
  useDoc.getState().load(fromJson(text));
  synced = toJson(useDoc.getState().doc);
  setBase(rev);
}
/** The revision is read before the content: a change in between arrives again with the next status. */
const readRemote = async () => new TextDecoder().decode((await pi.raw('GET', '/api/workspace/project', { timeoutMs: LONG_MS })).body);

const pull = () => locked(async () => {
  const rev = piRevision();
  if (!canSync() || rev <= base() || useSync.getState().conflict) return;
  if (hasUnsent()) { useSync.setState({ conflict: true }); return; }
  takeRemote(await readRemote(), rev);
  toast('Projekt vom Pi übernommen (an einem anderen Gerät geändert)', 'info');
});

const push = () => locked(async () => {
  if (!canSync() || useSync.getState().conflict) return;
  const json = toJson(useDoc.getState().doc);
  if (json === synced) return;
  // A new device with an untouched project takes the Pi's project instead of replacing it.
  if (synced == null && base() === 0 && piRevision() > 0 && !useDoc.getState().dirty) return;
  try {
    setBase(await putProject(json, base()));
    synced = json;
  } catch (e) {
    if (e instanceof PiError && e.status === 409) useSync.setState({ conflict: true });
  }
});

/** The operator's answer to a conflict: the Pi's project, or this device's over it. */
export const resolveConflict = (takePi: boolean) => locked(async () => {
  try {
    const rev = (await pi.status()).sync?.project ?? piRevision();
    if (takePi) takeRemote(await readRemote(), rev);
    else { const json = toJson(useDoc.getState().doc); setBase(await putProject(json, rev)); synced = json; }
    useSync.setState({ conflict: false });
  } catch (e) { toast(`Abgleich mit dem Pi fehlgeschlagen: ${(e as Error).message}`, 'bad'); }
});

let pushTimer: ReturnType<typeof setTimeout> | null = null;
function schedulePush() { if (pushTimer) clearTimeout(pushTimer); pushTimer = setTimeout(() => void push(), 2000); }

/* ---- Local autosave: IndexedDB, because pictures do not fit into localStorage ---- */
const STORE = 'autosave', KEY = 'doc';
const openDb = () => new Promise<IDBDatabase>((resolve, reject) => {
  const r = indexedDB.open('lumacut', 1);
  r.onupgradeneeded = () => r.result.createObjectStore(STORE);
  r.onsuccess = () => resolve(r.result);
  r.onerror = () => reject(r.error);
});
async function idb<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest): Promise<T | undefined> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const req = fn(db.transaction(STORE, mode).objectStore(STORE));
    req.onsuccess = () => { db.close(); resolve(req.result as T); };
    req.onerror = () => { db.close(); reject(req.error); };
  });
}
let autosaveTimer: ReturnType<typeof setTimeout> | null = null;
function scheduleAutosave() {
  if (autosaveTimer) clearTimeout(autosaveTimer);
  autosaveTimer = setTimeout(() => {
    const { doc, dirty } = useDoc.getState();
    const rec: Recovered = { json: toJson(doc), savedAt: Date.now(), title: doc.title };
    void (dirty ? idb('readwrite', (s) => s.put(rec, KEY)) : idb('readwrite', (s) => s.delete(KEY))).catch(() => undefined);
  }, 4000);
}
export function restoreAutosave(r: Recovered) {
  useDoc.getState().load(fromJson(r.json));
  useDoc.setState({ dirty: true });
  useSync.setState({ recovered: null });
  schedulePush();
}
export function discardAutosave() {
  useSync.setState({ recovered: null });
  void idb('readwrite', (s) => s.delete(KEY)).catch(() => undefined);
}

let started = false;
/**
 * Runs once for the app's lifetime. Browser tests start many fresh pages against one simulator and
 * must not inherit each other's project through it, so they switch the sharing on explicitly.
 */
export function startSync() {
  if (started) return;
  started = true;
  useDoc.subscribe((s, prev) => {
    if (s.doc !== prev.doc || s.dirty !== prev.dirty) scheduleAutosave();
    if (s.doc !== prev.doc) schedulePush();
  });
  void idb<Recovered>('readonly', (s) => s.get(KEY)).then((r) => {
    const s = useDoc.getState();
    if (r && !s.dirty && s.doc.elements.length === 0) useSync.setState({ recovered: r });
  }).catch(() => undefined);
  let shared = !navigator.webdriver;
  try { shared ||= localStorage.getItem('lc.sync.e2e') === '1'; } catch { /* stays off */ }
  if (!shared) return;
  let lastRev = -1, wasOnline = false;
  useMachine.subscribe((m) => {
    const rev = m.status.sync?.project ?? 0;
    if (rev !== lastRev) { lastRev = rev; void pull(); }
    if (m.online && !wasOnline) schedulePush();
    wasOnline = m.online;
  });
}
