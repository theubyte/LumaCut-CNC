import { useCallback, useEffect, useState } from 'react';
import { ChevronDown, ChevronUp, Download, Eye, ListPlus, Pause, Play, Trash2, Upload, X, SkipForward } from 'lucide-react';
import { machineAction } from '@/pi/actions';
import { pi } from '@/pi/client';
import { jobActive, useMachine } from '@/pi/machine';
import { pickFiles, saveFile } from '@/platform';
import { Button, confirmDialog, toast } from '@/ui/kit';

interface JobFile { name: string; bytes: number; modified: number }
interface QItem { id: number; file: string; state: string; error?: string }

const Q_STATE: Record<string, string> = { queued: 'wartet', running: 'läuft', done: 'fertig', error: 'Fehler', aborted: 'abgebrochen', skipped: 'übersprungen' };
const Q_TONE: Record<string, string> = { running: 'chip-accent', done: 'chip-ok', error: 'chip-bad', aborted: 'chip-warn' };
const size = (b: number) => b >= 1048576 ? `${(b / 1048576).toFixed(1).replace('.', ',')} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;
const when = (s: number) => s > 0 ? new Date(s * 1000).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' }) : '';
const loadOpen = () => { try { return localStorage.getItem('lc.start.dock') === '1'; } catch { return false; } };

/** Below the preview, folded by default: what waits on the Pi and what is stored there. */
export function Dock({ selected, onPreview, onEnqueueCurrent, enqueueBusy }: { selected: string | null; onPreview(name: string): void; onEnqueueCurrent?(): void; enqueueBusy: boolean }) {
  const [open, setOpen] = useState(loadOpen);
  const [jobs, setJobs] = useState<JobFile[]>([]);
  const status = useMachine((m) => m.status);
  const online = useMachine((m) => m.online);
  const queue = status.queue;
  const items = (queue?.items ?? []) as unknown as QItem[];
  const waiting = items.filter((i) => i.state === 'queued' || i.state === 'running').length;
  const jobState = status.job?.state;

  const reload = useCallback(() => {
    pi.get<{ files: JobFile[] }>('/api/jobs').then((r) => setJobs([...r.files].sort((a, b) => b.modified - a.modified))).catch(() => undefined);
  }, []);
  useEffect(reload, [reload, online, jobState, enqueueBusy, items.length]);

  const toggle = () => { const v = !open; setOpen(v); try { localStorage.setItem('lc.start.dock', v ? '1' : '0'); } catch { /* per-device convenience */ } };

  return <section className="dock" data-testid="dock">
    <button type="button" className="dock-head" aria-expanded={open} data-testid="dock-toggle" onClick={toggle}>
      <span>Warteschlange <span className="dock-count" data-testid="queue-count">{waiting}</span></span>
      <span>Gespeicherte Aufträge <span className="dock-count" data-testid="jobs-count">{jobs.length}</span></span>
      <span className="grow" />
      {open ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
    </button>
    {open && <div className="dock-body">
      <QueueColumn items={items} state={queue?.state ?? 'idle'} anyJob={jobActive(status)} onEnqueueCurrent={onEnqueueCurrent} enqueueBusy={enqueueBusy} />
      <JobsColumn jobs={jobs} selected={selected} items={items} onPreview={onPreview} reload={reload} />
    </div>}
  </section>;
}

function QueueColumn({ items, state, anyJob, onEnqueueCurrent, enqueueBusy }: { items: QItem[]; state: string; anyJob: boolean; onEnqueueCurrent?(): void; enqueueBusy: boolean }) {
  const queued = items.filter((i) => i.state === 'queued').length;
  const active = state === 'running' || state === 'pausing';
  const act = (op: string, f: Record<string, string | number> = {}) => { void machineAction(op, f, { quiet: true }).catch(() => undefined); };
  return <div className="dock-col" data-testid="queue">
    <div className="dock-col-head">
      <span className="section-title grow">Warteschlange{state === 'pausing' ? ' hält nach diesem Auftrag an' : queued && state === 'paused' ? ' pausiert' : queued && state === 'stopped' ? ' angehalten' : ''}</span>
      {onEnqueueCurrent && <Button size="sm" icon={<ListPlus size={13} />} disabled={enqueueBusy} data-testid="queue-add-current" title="Das aktuelle Motiv hochladen und hinten anstellen" onClick={onEnqueueCurrent}>Motiv einreihen</Button>}
      {active
        ? <Button size="sm" icon={<Pause size={13} />} disabled={state === 'pausing'} data-testid="queue-pause" onClick={() => act('queue_pause')}>Pause</Button>
        : <Button size="sm" icon={<Play size={13} />} disabled={!queued || anyJob} data-testid="queue-run" onClick={() => act('queue_run')}>{queued && (state === 'paused' || state === 'stopped') ? 'Fortsetzen' : 'Starten'}</Button>}
      <Button size="sm" variant="ghost" disabled={!items.length} data-testid="queue-clear" onClick={() => act('queue_clear')}>Leeren</Button>
    </div>
    <div className="dock-list">
      {!items.length && <div className="dock-empty">Leer. Reihe das aktuelle Motiv oder einen gespeicherten Auftrag ein: alles läuft dann nacheinander, jeder Auftrag mit eigener Abtastung.</div>}
      {items.map((it) => <div key={it.id} className="list-row" data-testid="queue-item" data-state={it.state}>
        <div className="list-row-main list-row-static">
          <span className="list-row-title" title={it.file}>{it.file}</span>
          {it.error && <span className="list-row-sub list-row-error">{it.error}</span>}
        </div>
        <span className={`chip ${Q_TONE[it.state] ?? ''}`}>{Q_STATE[it.state] ?? it.state}</span>
        {it.state === 'queued' && <Button variant="ghost" size="sm" iconOnly title="Überspringen" aria-label={`${it.file} überspringen`} icon={<SkipForward size={13} />} onClick={() => act('queue_skip', { id: it.id })} />}
        {it.state !== 'running' && <Button variant="ghost" size="sm" iconOnly title="Entfernen" aria-label={`${it.file} entfernen`} icon={<X size={14} />} onClick={() => act('queue_remove', { id: it.id })} />}
      </div>)}
    </div>
  </div>;
}

function JobsColumn({ jobs, selected, items, onPreview, reload }: { jobs: JobFile[]; selected: string | null; items: QItem[]; onPreview(n: string): void; reload(): void }) {
  const running = useMachine((m) => m.status.job?.file && jobActive(m.status) ? m.status.job.file : null);
  const upload = async () => {
    const [f] = await pickFiles([{ name: 'G-Code', extensions: ['gcode', 'gc', 'nc'] }]);
    if (!f) return;
    try { const r = await pi.upload(f.name, new TextDecoder().decode(f.bytes)); toast(r.message, 'ok'); reload(); onPreview(f.name); }
    catch (e) { toast((e as Error).message, 'bad'); }
  };
  const exportJob = async (name: string) => {
    try { const text = await pi.getText(`/api/jobs/${encodeURIComponent(name)}/content`); if (await saveFile(name, text, [{ name: 'G-Code', extensions: ['gcode'] }])) toast(`${name} exportiert`, 'ok'); }
    catch (e) { toast((e as Error).message, 'bad'); }
  };
  const remove = async (name: string) => {
    if (!(await confirmDialog({ title: `„${name}“ löschen?`, body: 'Der Auftrag verschwindet vom Pi. Das Projekt bleibt erhalten.', okLabel: 'Löschen', danger: true }))) return;
    try { const r = await pi.raw('POST', `/api/jobs/${encodeURIComponent(name)}/delete`); toast(JSON.parse(new TextDecoder().decode(r.body)).message, 'ok'); reload(); }
    catch (e) { toast((e as Error).message, 'bad'); }
  };
  return <div className="dock-col" data-testid="jobs">
    <div className="dock-col-head">
      <span className="section-title grow">Gespeicherte Aufträge</span>
      <Button size="sm" icon={<Upload size={13} />} title="G-Code-Datei vom PC auf den Pi laden" onClick={() => void upload()}>Hochladen</Button>
    </div>
    <div className="dock-list">
      {!jobs.length && <div className="dock-empty">Noch keine Aufträge auf dem Pi. Jeder Start und jedes Einreihen legt einen an.</div>}
      {jobs.map((j) => {
        const waiting = items.some((i) => i.file === j.name && (i.state === 'queued' || i.state === 'running'));
        return <div key={j.name} className={'list-row' + (selected === j.name ? ' selected' : '')} data-testid="job-row" data-name={j.name}>
          <button type="button" className="list-row-main" title="Vorschau" onClick={() => onPreview(j.name)}>
            <span className="list-row-title">{j.name}</span>
            <span className="faint list-row-sub tnum">{[when(j.modified), size(j.bytes)].filter(Boolean).join(' · ')}</span>
          </button>
          <Button variant="ghost" size="sm" iconOnly title="Vorschau" aria-label={`${j.name}: Vorschau`} data-testid="job-preview" icon={<Eye size={14} />} onClick={() => onPreview(j.name)} />
          <Button variant="ghost" size="sm" iconOnly title="In die Warteschlange" aria-label={`${j.name} einreihen`} data-testid="job-enqueue" icon={<ListPlus size={14} />} onClick={() => void machineAction('queue_add', { name: j.name }).catch(() => undefined)} />
          <Button variant="ghost" size="sm" iconOnly title="G-Code exportieren" aria-label={`${j.name} exportieren`} data-testid="job-export" icon={<Download size={14} />} onClick={() => void exportJob(j.name)} />
          <Button variant="ghost" size="sm" iconOnly title={running === j.name ? 'Läuft gerade' : waiting ? 'Steht in der Warteschlange' : 'Löschen'} aria-label={`${j.name} löschen`} data-testid="job-delete" disabled={running === j.name || waiting} icon={<Trash2 size={14} />} onClick={() => void remove(j.name)} />
        </div>;
      })}
    </div>
  </div>;
}
