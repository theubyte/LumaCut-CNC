import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Trash2 } from 'lucide-react';
import { deleteProject, discardAutosave, listProjects, openSaved, resolveConflict, restoreAutosave, saveNamed, type SavedProject, startSync, useSync } from '@/pi/sync';
import { useDoc } from '@/store/doc';
import { Button, confirmDialog, Dialog, Field, toast } from '@/ui/kit';
import './start.css';

/** Mounted once by the app shell: starts the project sharing and shows its dialogs. */
export function SyncHost() {
  useEffect(startSync, []);
  const dialog = useSync((s) => s.dialog), conflict = useSync((s) => s.conflict), recovered = useSync((s) => s.recovered);
  return <>
    {dialog && <ProjectDialog key={dialog.mode} mode={dialog.mode} onDone={(done) => { useSync.setState({ dialog: null }); dialog.resolve(done); }} />}
    {conflict && <Dialog title="Projekt an einem anderen Gerät geändert" locked width={480} footer={<>
      <Button onClick={() => void resolveConflict(false)} data-testid="conflict-keep">Diese Fassung behalten</Button>
      <Button variant="primary" onClick={() => void resolveConflict(true)} data-testid="conflict-take">Vom Pi übernehmen</Button></>}>
      <p className="muted">Auf dem Pi liegt eine neuere Fassung des Projekts, und auch hier wurde geändert. Welche soll gelten? Die andere geht verloren, solange sie nicht gespeichert ist.</p>
    </Dialog>}
    {recovered && !conflict && <Dialog title="Ungesicherte Arbeit gefunden" width={440} onClose={discardAutosave} footer={<>
      <Button onClick={discardAutosave}>Verwerfen</Button>
      <Button variant="primary" onClick={() => restoreAutosave(recovered)}>Wiederherstellen</Button></>}>
      <p className="muted">„{recovered.title}“ wurde zuletzt am {new Date(recovered.savedAt).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' })} automatisch gesichert und nie gespeichert.</p>
    </Dialog>}
  </>;
}

const formatSize = (b: number) => b >= 1048576 ? `${(b / 1048576).toFixed(1).replace('.', ',')} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;
const projectLine = (p: SavedProject) => {
  const when = new Date(p.updated_at);
  const parts = [Number.isNaN(+when) ? '' : when.toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' }), p.updated_by ?? '', p.elements != null ? `${p.elements} Elemente` : '', formatSize(p.bytes)];
  return parts.filter(Boolean).join(' · ');
};

function ProjectDialog({ mode, onDone }: { mode: 'save' | 'open'; onDone(done: boolean): void }) {
  const save = mode === 'save';
  const [list, setList] = useState<SavedProject[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState(useDoc.getState().doc.title);
  const reload = useCallback(() => {
    setError(null);
    listProjects().then(setList).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(reload, [reload]);
  const existing = list?.find((p) => p.name.toLowerCase() === name.trim().toLowerCase());
  const nameOk = name.trim().length >= 1 && name.trim().length <= 80;

  const store = async () => {
    setBusy(true);
    try { await saveNamed(name); onDone(true); }
    catch (e) { toast((e as Error).message, 'bad'); setBusy(false); }
  };
  const open = async (p: SavedProject) => {
    setBusy(true);
    try { if (await openSaved(p)) onDone(true); else setBusy(false); }
    catch (e) { toast((e as Error).message, 'bad'); setBusy(false); }
  };
  const remove = async (p: SavedProject) => {
    if (!(await confirmDialog({ title: `„${p.name}“ löschen?`, body: 'Das Projekt verschwindet vom Pi und damit von allen Geräten.', okLabel: 'Löschen', danger: true }))) return;
    try { await deleteProject(p.id); toast(`„${p.name}“ gelöscht`, 'ok'); reload(); }
    catch (e) { toast((e as Error).message, 'bad'); }
  };

  return <Dialog title={save ? 'Auf dem Pi speichern' : 'Projekt vom Pi öffnen'} width={520} onClose={() => onDone(false)} footer={<>
    <Button onClick={() => onDone(false)}>{save ? 'Abbrechen' : 'Schließen'}</Button>
    {save && <Button variant="primary" disabled={!nameOk || busy || !!error || !list} data-testid="project-save" onClick={() => void store()}>{existing ? 'Ersetzen' : 'Speichern'}</Button>}
  </>}>
    <div className="col" style={{ gap: 'var(--sp-3)' }}>
      {save && <Field label="Name" hint={existing ? `Ein Projekt „${existing.name}“ gibt es schon: Speichern ersetzt es.` : undefined}>
        <input className="input" autoFocus value={name} maxLength={80} data-testid="project-name" onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && nameOk && !busy && list) void store(); }} />
      </Field>}
      {error ? <div className="row" style={{ justifyContent: 'space-between' }}><span>{error}</span><Button size="sm" icon={<RefreshCw size={13} />} onClick={reload}>Neu laden</Button></div>
        : !list ? <p className="muted">Liste wird geladen …</p>
        : !list.length ? <p className="muted">Noch keine Projekte auf dem Pi.{save ? '' : ' Speichere zuerst eines über „Auf dem Pi speichern“.'}</p>
        : <div className="col" style={{ gap: 2 }}>
          {save && <span className="field-label">Schon auf dem Pi (Klick übernimmt den Namen)</span>}
          <div className="project-list" data-testid="project-list">
            {list.map((p) => <div key={p.id} className="list-row">
              <button type="button" className="list-row-main" disabled={busy} onClick={() => { if (save) setName(p.name); else void open(p); }}>
                <span className="list-row-title">{p.name}</span>
                <span className="faint list-row-sub">{projectLine(p)}</span>
              </button>
              <Button variant="ghost" size="sm" iconOnly title={`„${p.name}“ löschen`} aria-label={`${p.name} löschen`} disabled={busy} icon={<Trash2 size={14} />} onClick={() => void remove(p)} />
            </div>)}
          </div>
        </div>}
    </div>
  </Dialog>;
}
