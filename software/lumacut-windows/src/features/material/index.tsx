import { useEffect, useMemo, useState } from 'react';
import { Check as CheckIcon, Layers3, Pencil, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';
import { applyGroupToDoc, effectivePasses, entryOf, focusDropOk, groupKey, groupMaterials, lowPower, type MaterialGroup, newProcess, PROCESSES, type PiMaterial, type Process, type ToneCurve } from '@/core/material';
import { Limits } from '@/core/model';
import { createMaterial, deleteMaterial, loadMaterials, updateMaterial, useMaterials } from '@/pi/materials';
import { setWorkMaterial, useWorkspace } from '@/pi/workspace';
import { useDoc } from '@/store/doc';
import { useUi } from '@/store/ui';
import { Button, Check, confirmDialog, Dialog, Field, Note, NumberInput, Segmented, toast } from '@/ui/kit';
import './material.css';

const mm = (v: number) => v.toLocaleString('de-DE', { maximumFractionDigits: 2 });
const toastError = (e: unknown) => toast((e as Error).message, 'bad');

export default function MaterialView() {
  const { items, fromPi, loading, error } = useMaterials();
  const current = useWorkspace((w) => w.material);
  const [query, setQuery] = useState('');
  const [sel, setSel] = useState<string | null>(null);
  const [dialog, setDialog] = useState<{ edit?: MaterialGroup } | null>(null);
  useEffect(() => { void loadMaterials(); }, []);
  const groups = useMemo(() => groupMaterials(items, query), [items, query]);
  const currentKey = current ? groupKey(current.name, current.thickness_mm) : null;
  // The search only filters the list: the open material stays open while it still exists.
  const all = useMemo(() => groupMaterials(items), [items]);
  const open = all.find((g) => g.key === sel) ?? all.find((g) => g.key === currentKey) ?? groups[0] ?? null;
  return <div className="mt-root">
    <aside className="mt-list" aria-label="Materialien">
      <div className="mt-list-head">
        <div className="mt-search"><Search size={14} className="faint" />
          <input className="input" placeholder="Material suchen" aria-label="Material suchen" value={query} onChange={(e) => setQuery(e.target.value)} data-testid="mt-search" /></div>
        <Button iconOnly variant="ghost" title="Liste neu laden" aria-label="Liste neu laden" onClick={() => void loadMaterials()}><RefreshCw size={15} className={loading ? 'mt-rot' : undefined} /></Button>
      </div>
      <div className="mt-items" role="listbox" aria-label="Materialliste">
        {groups.map((g) => {
          const isCur = g.key === currentKey;
          return <button key={g.key} type="button" role="option" aria-selected={g.key === open?.key} className="mt-item" data-testid="mt-item" onClick={() => setSel(g.key)}>
            <span className="grow">
              <span className="mt-item-name">{g.name}</span>
              <span className="mt-item-sub">{mm(g.thicknessMm)} mm · {PROCESSES.filter((p) => entryOf(g, p)).join(', ')}</span>
            </span>
            {isCur && <span className="chip chip-accent" data-testid="mt-current-chip"><CheckIcon size={12} />Aktuell</span>}
          </button>;
        })}
        {!groups.length && <div className="empty">{query ? <p>Nichts gefunden. Anderen Begriff versuchen.</p> : fromPi ? <p>Noch kein Material. Lege das erste an.</p> : <p>{loading ? 'Liste wird geladen.' : 'Keine Liste vorhanden. Verbindung zum Pi prüfen.'}</p>}</div>}
      </div>
      <div className="mt-list-foot"><Button icon={<Plus size={15} />} disabled={!fromPi} title={fromPi ? undefined : 'Geht nur mit Verbindung zum Pi'} onClick={() => setDialog({})} data-testid="mt-new" style={{ width: '100%' }}>Neues Material</Button></div>
    </aside>
    <main className="mt-detail">
      {!fromPi && !loading && <div className="mt-offline"><Note tone="warn">Kein Kontakt zum Pi{error ? `: ${error}` : ''}. Das ist die zuletzt gespeicherte Liste, sie lässt sich nicht ändern.</Note></div>}
      {open ? <Detail key={open.key} g={open} isCurrent={open.key === currentKey} editable={fromPi} onEdit={() => setDialog({ edit: open })} />
        : <div className="empty mt-empty"><Layers3 size={30} /><p>Links ein Material wählen oder ein neues anlegen.</p></div>}
    </main>
    {dialog && <GroupDialog edit={dialog.edit} onClose={() => setDialog(null)} onDone={(key) => { setDialog(null); setSel(key); }} />}
  </div>;
}

function Detail({ g, isCurrent, editable, onEdit }: { g: MaterialGroup; isCurrent: boolean; editable: boolean; onEdit(): void }) {
  const go = useUi((u) => u.go);
  const [busy, setBusy] = useState(false);
  const allBuiltin = g.entries.every((e) => e.builtin);
  const use = async () => {
    setBusy(true);
    try {
      await setWorkMaterial({ name: g.name, thickness_mm: g.thicknessMm });
      useDoc.getState().commit((d) => applyGroupToDoc(d, g));
      toast(`„${g.name}, ${mm(g.thicknessMm)} mm“ ist jetzt das aktuelle Material. Die Ebenen haben die Werte übernommen.`, 'ok');
    } catch (e) { toast(`Nicht übernommen: ${(e as Error).message}`, 'bad'); } finally { setBusy(false); }
  };
  return <div className="mt-detail-in">
    <header className="mt-head">
      <div className="grow">
        <h1 className="h1" data-testid="mt-title">{g.name}</h1>
        <p className="muted tnum">{mm(g.thicknessMm)} mm stark{allBuiltin ? ' · Startwerte' : ''}</p>
      </div>
      {editable && <Button icon={<Pencil size={14} />} variant="ghost" onClick={onEdit} data-testid="mt-edit">Name und Stärke</Button>}
      <Button variant="primary" size="lg" disabled={busy || !editable || isCurrent} icon={<CheckIcon size={16} />} onClick={() => void use()} data-testid="mt-use"
        title={!editable ? 'Geht nur mit Verbindung zum Pi' : undefined}>{isCurrent ? 'Wird verwendet' : 'Dieses Material verwenden'}</Button>
    </header>
    {isCurrent
      ? <div className="row mt-next"><span className="muted grow">Aufträge rechnen mit dieser Stärke. Die Werte stehen auf den Ebenen im Motiv.</span>
          <Button size="sm" variant="ghost" onClick={() => useDoc.getState().commit((d) => applyGroupToDoc(d, g))} data-testid="mt-reapply">Werte erneut auf die Ebenen</Button>
          <Button size="sm" onClick={() => go('motiv')}>Weiter zum Motiv</Button></div>
      : null}
    {g.entries.some((e) => e.builtin) && <Note tone="warn">Startwerte sind ungetestet. Erst auf einem Reststück dieses Materials prüfen, zum Beispiel mit dem Materialtest unter Maschine, Kalibrieren.</Note>}
    <div className="mt-processes">
      {PROCESSES.map((p) => {
        const m = entryOf(g, p);
        return m ? <ProcessCard key={m.id} m={m} editable={editable} /> : <MissingProcess key={p} g={g} process={p} editable={editable} />;
      })}
    </div>
    <p className="faint mt-small">Die Werte gelten für alle Geräte. Jedes Material vor dem ersten Auftrag am eigenen Laser auf einem Reststück testen.</p>
  </div>;
}

function MissingProcess({ g, process, editable }: { g: MaterialGroup; process: Process; editable: boolean }) {
  return <section className="card mt-proc mt-proc-empty" data-testid={`mt-proc-${process}`}>
    <h2 className="h3">{process}</h2>
    <span className="muted grow">Für dieses Material noch nicht angelegt. Die Ebene behält dann ihre eigenen Werte.</span>
    <Button icon={<Plus size={14} />} disabled={!editable} onClick={() => void createMaterial(newProcess(g.name, g.thicknessMm, process)).catch(toastError)} data-testid={`mt-add-${process}`}>Anlegen</Button>
  </section>;
}

function ProcessCard({ m, editable }: { m: PiMaterial; editable: boolean }) {
  const patch = (p: Partial<PiMaterial>) => void updateMaterial(m.id, p).catch(toastError);
  const passes = effectivePasses(m);
  const remove = async () => {
    if (await confirmDialog({ title: `${m.process} löschen?`, body: `${m.name}, ${mm(m.thickness_mm)} mm. Das gilt für alle Geräte.`, okLabel: 'Löschen', danger: true })) await deleteMaterial(m.id).catch(toastError);
  };
  return <section className="card mt-proc" data-testid={`mt-proc-${m.process}`}>
    <div className="mt-proc-head">
      <h2 className="h3 grow">{m.process}</h2>
      {m.tone_curve && <span className="chip chip-ok">gemessen</span>}
      {m.builtin && <span className="chip">Startwert</span>}
      <Segmented ariaLabel="Art" value={m.mode} onChange={(mode) => editable && patch({ mode })} options={[{ value: 'line', label: 'Linie' }, { value: 'fill', label: 'Füllen' }]} />
      {!m.builtin && <Button iconOnly variant="ghost" aria-label={`${m.process} löschen`} title="Löschen" disabled={!editable} onClick={() => void remove()} data-testid={`mt-del-${m.process}`}><Trash2 size={15} /></Button>}
    </div>
    <div className="mt-fields">
      <Field label="Leistung"><NumberInput ariaLabel={`${m.process} Leistung`} disabled={!editable} value={m.power_pct} min={Limits.MIN_RELIABLE_POWER_PCT} max={100} step={1} digits={1} unit="%" onChange={(power_pct) => patch({ power_pct })} /></Field>
      <Field label="Tempo"><NumberInput ariaLabel={`${m.process} Tempo`} disabled={!editable} value={m.speed_mm_min} min={1} max={30000} step={50} digits={0} unit="mm/min" onChange={(speed_mm_min) => patch({ speed_mm_min })} /></Field>
      <Field label="Durchgänge" hint={m.depth_per_pass_mm > 0 ? 'aus Tiefe' : undefined}><NumberInput ariaLabel={`${m.process} Durchgänge`} disabled={!editable || m.depth_per_pass_mm > 0} value={passes} min={1} max={30} step={1} digits={0} onChange={(p) => patch({ passes: p })} /></Field>
      <Field label="Zeilenabstand"><NumberInput ariaLabel={`${m.process} Zeilenabstand`} disabled={!editable} value={m.interval_mm} min={0.03} max={2} step={0.01} digits={3} unit="mm" onChange={(interval_mm) => patch({ interval_mm })} /></Field>
      <Field label="Tiefe je Durchgang"><NumberInput ariaLabel={`${m.process} Tiefe`} disabled={!editable} value={m.depth_per_pass_mm} min={0} max={10} step={0.1} digits={2} unit="mm" onChange={(depth_per_pass_mm) => patch({ depth_per_pass_mm })} /></Field>
      <Field label="Z-Absenkung"><NumberInput ariaLabel={`${m.process} Z-Absenkung`} disabled={!editable} value={m.z_step_mm} min={0} max={2} step={0.1} digits={2} unit="mm" onChange={(z_step_mm) => patch({ z_step_mm })} /></Field>
    </div>
    {lowPower(m) && <Note tone="warn">Unter 8 % zündet der Laser nicht sicher.</Note>}
    {!focusDropOk(passes, m.z_step_mm) && <Note tone="warn">Die Absenkung über alle Durchgänge wird auf 3 mm begrenzt.</Note>}
    {m.tone_curve ? <ToneChart curve={m.tone_curve} /> : m.process === 'Gravieren' && <p className="faint mt-small">Noch keine Tonkurve. Der Materialtest mit Kamera misst sie.</p>}
  </section>;
}

/** Tone over energy per area, the same axis the Android curve uses. */
function ToneChart({ curve }: { curve: ToneCurve }) {
  const pts = (curve.points ?? []).filter((p) => p.power > 0 && p.speed > 0).map((p) => ({ e: p.power / p.speed, tone: p.tone, clean: p.clean !== false, power: p.power, speed: p.speed })).sort((a, b) => a.e - b.e);
  if (pts.length < 2) return null;
  const W = 420, H = 96, P = 8;
  const lo = Math.log(pts[0].e), hi = Math.log(pts[pts.length - 1].e), span = Math.max(hi - lo, 1e-6);
  const x = (e: number) => P + ((Math.log(e) - lo) / span) * (W - 2 * P);
  const y = (t: number) => H - P - Math.min(1, Math.max(0, t)) * (H - 2 * P);
  return <figure className="mt-tone" data-testid="mt-tone">
    <figcaption className="mt-small muted">Tonkurve: {pts.length} Messpunkte, von hell nach dunkel mit steigender Energie</figcaption>
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Tonkurve mit ${pts.length} Messpunkten`}>
      <line x1={P} x2={W - P} y1={y(0)} y2={y(0)} className="mt-tone-axis" />
      <polyline points={pts.map((p) => `${x(p.e)},${y(p.tone)}`).join(' ')} className="mt-tone-line" />
      {pts.map((p, i) => <circle key={i} cx={x(p.e)} cy={y(p.tone)} r={3.5} className={p.clean ? 'mt-tone-dot' : 'mt-tone-dot mt-tone-unclean'}><title>{`${mm(p.power)} %, ${mm(p.speed)} mm/min: Ton ${mm(p.tone)}`}</title></circle>)}
    </svg>
  </figure>;
}

/** New material with its processes, or new name and thickness for all processes of one. */
function GroupDialog({ edit, onClose, onDone }: { edit?: MaterialGroup; onClose(): void; onDone(key: string): void }) {
  const [name, setName] = useState(edit?.name ?? '');
  const [thick, setThick] = useState(edit?.thicknessMm ?? 3);
  const [procs, setProcs] = useState<Set<Process>>(new Set(['Gravieren', 'Schneiden']));
  const [busy, setBusy] = useState(false);
  const clean = name.trim();
  const exists = useMaterials((s) => s.items.some((m) => m.name === clean && m.thickness_mm === thick));
  const unchanged = !!edit && clean === edit.name && thick === edit.thicknessMm;
  const valid = clean.length > 0 && clean.length <= 80 && (edit ? !unchanged : procs.size > 0) && !exists;
  const current = useWorkspace((w) => w.material);
  const save = async () => {
    setBusy(true);
    try {
      if (edit) {
        for (const e of edit.entries) await updateMaterial(e.id, { name: clean, thickness_mm: thick });
        if (current?.name === edit.name && current.thickness_mm === edit.thicknessMm) await setWorkMaterial({ name: clean, thickness_mm: thick });
      } else {
        for (const p of PROCESSES) if (procs.has(p)) await createMaterial(newProcess(clean, thick, p));
      }
      onDone(groupKey(clean, thick));
    } catch (e) { toastError(e); } finally { setBusy(false); }
  };
  const remove = async () => {
    if (!edit) return;
    if (!(await confirmDialog({ title: 'Material löschen?', body: `${edit.name}, ${mm(edit.thicknessMm)} mm mit allen Prozessen. Das gilt für alle Geräte.`, okLabel: 'Löschen', danger: true }))) return;
    try { for (const e of edit.entries) await deleteMaterial(e.id); onClose(); } catch (e) { toastError(e); }
  };
  return <Dialog title={edit ? 'Name und Stärke' : 'Neues Material'} onClose={onClose} footer={<>
    {edit && !edit.entries.some((e) => e.builtin) && <Button variant="ghost" onClick={() => void remove()} data-testid="mt-group-delete" style={{ marginRight: 'auto', color: 'var(--bad)' }}>Material löschen</Button>}
    <Button onClick={onClose}>Abbrechen</Button>
    <Button variant="primary" disabled={!valid || busy} onClick={() => void save()} data-testid="mt-save">{edit ? 'Speichern' : 'Anlegen'}</Button></>}>
    <div className="col mt-form">
      <div className="mt-form-row">
        <Field label="Material"><input className="input" autoFocus value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder="zum Beispiel Birke" aria-label="Materialname" data-testid="mt-name" /></Field>
        <Field label="Stärke"><NumberInput ariaLabel="Stärke" value={thick} onChange={setThick} min={0} max={60} step={0.5} digits={2} unit="mm" /></Field>
      </div>
      {!edit && <Field label="Prozesse"><div className="row" style={{ gap: 14, height: 30 }}>{PROCESSES.map((p) =>
        <Check key={p} checked={procs.has(p)} onChange={(on) => { const n = new Set(procs); if (on) n.add(p); else n.delete(p); setProcs(n); }}>{p}</Check>)}</div></Field>}
      {exists && !unchanged && <Note tone="warn">Dieses Material mit dieser Stärke gibt es schon.</Note>}
      {!edit && <Note tone="warn">Neue Materialien starten mit groben Werten. Vor dem ersten Auftrag auf einem Reststück testen. Leistung und Tempo gleich danach anpassen.</Note>}
    </div>
  </Dialog>;
}
