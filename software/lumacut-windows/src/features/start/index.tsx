import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ArrowLeft, Check as CheckIcon, CheckCircle2, Info, Play, Square, X, XCircle, Zap } from 'lucide-react';
import { framePoints, frameProgram } from '@/core/frame';
import { FIRMWARE_MOTION, type Motion } from '@/core/gcode';
import { buildJob, cancelJob, JobAborted } from '@/core/jobClient';
import { Bed, isImage, layerCss, layerLabel, Limits, type Doc } from '@/core/model';
import { type CompactToolpath, formatDuration, parseToolpathCompact } from '@/core/toolpath';
import { machineAction } from '@/pi/actions';
import { jobNameFrom, pi } from '@/pi/client';
import { frameActive, jobActive, machineFree, useMachine } from '@/pi/machine';
import { loadMaterials, useMaterials } from '@/pi/materials';
import { loadWorkspace, useWorkspace } from '@/pi/workspace';
import { useDoc } from '@/store/doc';
import { useUi } from '@/store/ui';
import { Button, Note, Segmented } from '@/ui/kit';
import { blocksStart, type Check, computeChecks } from './checks';
import { Dock } from './Dock';
import { ToolpathView } from './ToolpathView';
import './start.css';

interface Built { gcode?: string; toolpath: CompactToolpath }
type Source = { kind: 'doc' } | { kind: 'saved'; name: string };

const metres = (mm: number) => mm >= 1000 ? `${(mm / 1000).toFixed(2).replace('.', ',')} m` : `${Math.round(mm)} mm`;
const hasContent = (d: Doc, plate: number) => d.elements.some((e) => e.plate === plate);
const plateDoc = (d: Doc, plate: number): Doc => ({ ...d, elements: d.elements.filter((e) => e.plate === plate) });

/** Laser only on values that were tried on this machine: an entry the operator saved or measured. */
function useMaterialTested(material: { name: string; thickness_mm: number } | null | undefined) {
  const items = useMaterials((s) => s.items), fromPi = useMaterials((s) => s.fromPi);
  useEffect(() => { void loadMaterials(); }, [material?.name, material?.thickness_mm]);
  if (!material || !fromPi) return undefined;
  const same = items.filter((m) => m.name.trim().toLowerCase() === material.name.trim().toLowerCase() && Math.abs(m.thickness_mm - material.thickness_mm) < 0.01);
  return same.some((m) => !m.builtin || !!m.tone_curve);
}

export default function View() {
  const doc = useDoc((s) => s.doc);
  const { status, online } = useMachine();
  const go = useUi((s) => s.go);
  const wsLoaded = useWorkspace((s) => s.loaded), wsMaterial = useWorkspace((s) => s.material);
  const material = wsLoaded ? wsMaterial : undefined;
  useEffect(() => { void loadWorkspace().catch(() => undefined); }, []);
  const materialTested = useMaterialTested(material);
  // The Pi reports nulls until the motion was calibrated; then the firmware's values apply, as on Android.
  const piMotion = status.config?.motion as Partial<Motion> | undefined;
  const motion: Motion = piMotion?.accel && piMotion.speed ? { accel: piMotion.accel, speed: piMotion.speed } : FIRMWARE_MOTION;
  const motionKey = `${motion.accel}/${motion.speed}`;

  const [source, setSource] = useState<Source>({ kind: 'doc' });
  const [chosenPlate, setChosenPlate] = useState(doc.activePlate);
  const plate = Math.max(0, Math.min(doc.plateCount - 1, chosenPlate));
  const multi = doc.plateCount > 1;

  const [built, setBuilt] = useState<Built | null>(null);
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [rejection, setRejection] = useState<string | null>(null);
  const [busy, setBusy] = useState<'start' | 'frame' | 'queue' | null>(null);
  const [dismissed, setDismissed] = useState('');
  const [runPath, setRunPath] = useState<{ name: string; toolpath: CompactToolpath } | null>(null);

  // The job as it would leave this PC. Saved jobs are only read back and parsed.
  useEffect(() => {
    let live = true;
    setRejection(null); setBuildError(null);
    if (source.kind === 'saved') {
      setBuilt(null); setBuilding(true);
      pi.getText(`/api/jobs/${encodeURIComponent(source.name)}/content`)
        .then((text) => { if (live) setBuilt({ gcode: text, toolpath: parseToolpathCompact(text) }); })
        .catch((e: Error) => { if (live) setBuildError(`Vorschau nicht möglich: ${e.message}`); })
        .finally(() => { if (live) setBuilding(false); });
      return () => { live = false; };
    }
    if (!hasContent(doc, plate)) { setBuilt(null); setBuilding(false); return; }
    setBuilding(true);
    const t = setTimeout(() => {
      buildJob(doc, plate, motion)
        .then((r) => { if (live) { setBuilt({ gcode: r.gcode, toolpath: r.toolpath }); setBuildError(null); } })
        .catch((e: Error) => { if (live && !(e instanceof JobAborted)) { setBuilt(null); setBuildError(e.message); } })
        .finally(() => { if (live) setBuilding(false); });
    }, 200);
    return () => { live = false; clearTimeout(t); cancelJob(); };
  }, [doc, plate, source, motionKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const running = jobActive(status);
  const framing = frameActive(status);
  const job = status.job;
  const docName = jobNameFrom(multi ? `${doc.title} Platte ${plate + 1}` : doc.title);
  const name = source.kind === 'saved' ? source.name : docName;
  const toolpath = built?.toolpath ?? null;

  // A job that started elsewhere (queue, another device): show that one, not the open motif.
  useEffect(() => {
    if (!running || !job?.file || job.file === name) { setRunPath(null); return; }
    let live = true;
    pi.getText(`/api/jobs/${encodeURIComponent(job.file)}/content`)
      .then((text) => { if (live) setRunPath({ name: job.file!, toolpath: parseToolpathCompact(text) }); })
      .catch(() => { if (live) setRunPath(null); });
    return () => { live = false; };
  }, [running, job?.file, name]);
  const shown = running && runPath ? runPath.toolpath : toolpath;
  const lasering = running && (job?.phase ?? job?.state) !== 'homing' && (job?.state === 'running' || job?.state === 'finishing' || job?.state === 'parking');
  const fraction = job?.total ? Math.min(1, (job.line ?? 0) / job.total) : 0;

  const viewDoc = source.kind === 'doc' ? plateDoc(doc, plate) : null;
  const checks = useMemo(() => computeChecks({
    doc: viewDoc, plate, multi, toolpath: source.kind === 'saved' || built ? toolpath : null, buildError, rejection, status, online, motion, material, materialTested,
    bed: { width: Bed.width, height: Bed.height },
  }), [viewDoc?.elements, viewDoc?.layers, plate, multi, toolpath, buildError, rejection, status, online, motionKey, material, materialTested, source.kind]); // eslint-disable-line react-hooks/exhaustive-deps

  const free = machineFree(status);
  const empty = source.kind === 'doc' && !hasContent(doc, plate);
  const blocked = blocksStart(checks) || !built || building || empty;
  const canFrame = !!built && !building && !empty && free && online && !buildError;

  const start = async () => {
    if (!built || busy) return;
    setBusy('start'); setRejection(null);
    try {
      if (source.kind === 'doc') await pi.upload(name, built.gcode!);
      await machineAction('autorun', { name, clear: status.home_needs_confirm ? 1 : undefined }, {
        quiet: true,
        go: {
          title: multi && source.kind === 'doc' ? `Platte ${plate + 1} starten?` : 'Auftrag starten?',
          detail: `${name}, Dauer ca. ${formatDuration(built.toolpath.stats.seconds)}. Liegt das Material, und liegt es noch an derselben Stelle? `
            + (status.home_needs_confirm ? 'Der Pi kennt die Kopfhöhe nicht: steht die Tasterspitze über allem, was auf dem Bett liegt? ' : '')
            + 'Danach läuft alles von selbst: Referenzieren, Abtasten, Höhenkorrektur, Lasern, Parken.',
        },
      });
    } catch (e) { setRejection((e as Error).message); }
    finally { setBusy(null); }
  };

  const frame = async () => {
    if (!built || busy) return;
    setBusy('frame'); setRejection(null);
    try {
      if (!status.homed) {
        const homed = await machineAction('home', { clear: status.home_needs_confirm ? 1 : undefined }, {
          quiet: true,
          go: { title: 'Erst referenzieren?', detail: 'Für den Rahmen muss die Maschine wissen, wo der Kopf steht. Der Kopf fährt an die Endschalter.' },
        });
        if (!homed) return;
      }
      await machineAction('frame', { gcode: frameProgram(framePoints(built.toolpath), 'box'), mode: 'box' }, { quiet: true, go: { title: 'Rahmen fahren?', detail: `Der Kopf fährt den Umriss von ${name} ab.` } });
    } catch (e) { setRejection((e as Error).message); }
    finally { setBusy(null); }
  };

  const enqueue = useCallback(async () => {
    if (!built?.gcode || busy) return;
    setBusy('queue'); setRejection(null);
    try { await pi.upload(name, built.gcode); await machineAction('queue_add', { name }); }
    catch (e) { setRejection((e as Error).message); }
    finally { setBusy(null); }
  }, [built, busy, name]);

  const previewSaved = useCallback((n: string) => setSource({ kind: 'saved', name: n }), []);
  const backToDoc = () => setSource({ kind: 'doc' });

  const resultKey = `${job?.file}|${job?.state}|${job?.error ?? ''}`;
  const showResult = !running && !!job && ['complete', 'aborted', 'error'].includes(job.state) && dismissed !== resultKey;
  const dismissResult = () => setDismissed(resultKey);

  return <div className="start" data-testid="start-view">
    <ToolpathView toolpath={shown} liveFraction={running ? (lasering ? fraction : 0) : null} head={running || framing ? status.position : null}
      overlay={!shown && !running ? <EmptyState empty={empty} building={building} error={buildError} multi={multi} plate={plate} onMotiv={() => go('motiv')} /> : undefined} />
    <Dock selected={source.kind === 'saved' ? source.name : null} onPreview={previewSaved} onEnqueueCurrent={source.kind === 'doc' && built ? enqueue : undefined} enqueueBusy={busy === 'queue'} />

    <aside className="start-side">
      <div className="start-scroll">
        {showResult && <Result state={job!.state} error={job!.error} file={job!.file} onClose={dismissResult} />}
        {running
          ? <RunPanel file={job?.file ?? name} state={job?.phase ?? job?.state ?? ''} probe={job?.probe} fraction={fraction} lasering={lasering} seconds={shown?.stats.seconds ?? null} />
          : <>
            <Plan source={source} name={name} doc={doc} plate={plate} multi={multi} setPlate={setChosenPlate} material={material} onBack={backToDoc} onMaterial={() => go('material')} />
            <Numbers toolpath={toolpath} building={building} />
            {viewDoc && <LayerTable doc={viewDoc} />}
            <Checks checks={checks} onGo={go} />
          </>}
      </div>
      <div className="start-actions">
        {running
          ? <Button size="lg" className="start-go" icon={<Square size={15} />} data-testid="job-abort" onClick={() => void machineAction('abort')}>Abbrechen</Button>
          : <>
            {framing
              ? <Button onClick={() => void machineAction('abort')} icon={<Square size={14} />} data-testid="frame-abort">Rahmen abbrechen ({status.frame?.line ?? 0}/{status.frame?.total ?? 0})</Button>
              : <Button disabled={!canFrame || !!busy} onClick={() => void frame()} data-testid="frame" title="Der Kopf fährt den Umriss des Auftrags ab">{busy === 'frame' ? 'Rahmen wird vorbereitet …' : 'Rahmen'}</Button>}
            <Button variant="danger" size="lg" className="start-go" disabled={blocked || !free || !!busy} title={checks.find((c) => c.tone === 'bad')?.text} icon={<Zap size={17} />} data-testid="start" onClick={() => void start()}>
              {busy === 'start' ? 'Wird gesendet …' : 'Starten'}
            </Button>
          </>}
      </div>
    </aside>
  </div>;
}

function EmptyState({ empty, building, error, multi, plate, onMotiv }: { empty: boolean; building: boolean; error: string | null; multi: boolean; plate: number; onMotiv(): void }) {
  if (building) return <div className="preview-empty muted" data-testid="preview-building">Auftrag wird berechnet …</div>;
  if (empty) return <div className="preview-empty" data-testid="preview-empty">
    <span className="h3">{multi ? `Platte ${plate + 1} ist leer` : 'Noch kein Motiv'}</span>
    <span className="muted">{multi ? 'Eine andere Platte wählen oder im Motiv etwas auf diese Platte legen.' : 'Lege im Bereich Motiv etwas an. Hier erscheint dann, was der Laser fährt.'}</span>
    <Button variant="primary" onClick={onMotiv} style={{ marginTop: 'var(--sp-2)' }}>Zum Motiv</Button>
  </div>;
  if (error) return <div className="preview-empty" data-testid="preview-error">
    <span className="h3">Keine Vorschau möglich</span>
    <span className="muted">Rechts unter „Prüfungen“ steht, was zu tun ist.</span>
  </div>;
  return null;
}

function Plan({ source, name, doc, plate, multi, setPlate, material, onBack, onMaterial }: {
  source: Source; name: string; doc: Doc; plate: number; multi: boolean; setPlate(p: number): void; material: { name: string; thickness_mm: number } | null | undefined; onBack(): void; onMaterial(): void;
}) {
  return <div className="start-block">
    {source.kind === 'saved' && <div className="start-source">
      <div style={{ minWidth: 0 }}>
        <div className="start-stat-label">Gespeicherter Auftrag</div>
        <div className="start-source-value" title={name} data-testid="source-name">{name}</div>
      </div>
      <Button size="sm" variant="ghost" icon={<ArrowLeft size={13} />} onClick={onBack} data-testid="back-to-motif">Zum Motiv</Button>
    </div>}
    <div className="start-source">
      <div style={{ minWidth: 0 }}>
        <div className="start-stat-label">Material</div>
        <div className="start-source-value" data-testid="material-name">{material === undefined ? '…' : material ? `${material.name}, ${String(material.thickness_mm).replace('.', ',')} mm` : 'Noch keines gewählt'}</div>
      </div>
      <Button size="sm" onClick={onMaterial}>{material ? 'Ändern' : 'Wählen'}</Button>
    </div>
    {multi && source.kind === 'doc' && <div className="col" style={{ gap: 3 }}>
      <div className="start-stat-label">Platte</div>
      <Segmented ariaLabel="Platte wählen" value={String(plate)} onChange={(v) => setPlate(+v)}
        options={Array.from({ length: doc.plateCount }, (_, i) => ({ value: String(i), label: String(i + 1), title: `Platte ${i + 1}: ${doc.elements.filter((e) => e.plate === i).length} Elemente` }))} />
    </div>}
  </div>;
}

function Numbers({ toolpath, building }: { toolpath: CompactToolpath | null; building: boolean }) {
  const s = toolpath?.stats, b = toolpath?.bounds;
  const dash = building ? '…' : '–';
  return <div className="start-block">
    <div className="start-stat-label">Zeitschätzung</div>
    <div className="start-time" data-testid="estimate">{s ? formatDuration(s.seconds) : dash}</div>
    <div className="start-stats" style={{ marginTop: 'var(--sp-1)' }}>
      <div><div className="start-stat-label">Laserweg</div><div className="start-stat-value" data-testid="cut-length">{s ? metres(s.cutMm) : dash}</div></div>
      <div><div className="start-stat-label">Leerweg</div><div className="start-stat-value" data-testid="travel-length">{s ? metres(s.travelMm) : dash}</div></div>
      <div><div className="start-stat-label">Größe</div><div className="start-stat-value">{b ? `${Math.round(b.maxX - b.minX)} × ${Math.round(b.maxY - b.minY)} mm` : dash}</div></div>
    </div>
  </div>;
}

function LayerTable({ doc }: { doc: Doc }) {
  const rows = doc.layers.filter((l) => doc.elements.some((e) => e.layerId === l.id));
  if (!rows.length) return null;
  return <div className="start-block">
    <span className="section-title">Ebenen</span>
    <table className="layer-table" data-testid="layer-table">
      <thead><tr><th aria-label="Ebene" /><th>Leistung</th><th>Tempo</th><th>Durchg.</th><th>Abstand</th></tr></thead>
      <tbody>{rows.map((l) => {
        const on = l.output && l.visible;
        const weak = l.powerPct > 0 && l.powerPct < Limits.MIN_RELIABLE_POWER_PCT;
        const filled = l.mode === 'FILL' || doc.elements.some((e) => e.layerId === l.id && isImage(e));
        return <tr key={l.id} className={on ? '' : 'off'} title={on ? undefined : 'Diese Ebene wird nicht gelasert'}>
          <td><span className="layer-name"><span className="layer-dot" style={{ background: layerCss(l), opacity: on ? 1 : .35 }} />{layerLabel(l)}</span></td>
          {on ? <>
            <td className={weak ? 'value-warn' : undefined}>{String(l.powerPct).replace('.', ',')} %</td>
            <td>{Math.round(l.speed)}</td>
            <td>{l.passes}</td>
            <td>{filled ? String(l.intervalMm).replace('.', ',') : '–'}</td>
          </> : <td colSpan={4}>aus</td>}
        </tr>;
      })}</tbody>
    </table>
    <span className="faint" style={{ fontSize: 'var(--fs-xs)' }}>Tempo in mm/min, Abstand in mm</span>
  </div>;
}

const CHECK_ICON = { bad: XCircle, warn: AlertTriangle, info: Info };
function Checks({ checks, onGo }: { checks: Check[]; onGo(d: 'material' | 'motiv' | 'maschine'): void }) {
  const serious = checks.some((c) => c.tone !== 'info');
  return <div className="start-block">
    <span className="section-title">Prüfungen</span>
    <div className="check-list" data-testid="checks">
      {!serious && <div className="check-item check-ok" data-check="ok"><CheckCircle2 size={15} /><span>Alles in Ordnung, der Auftrag kann starten.</span></div>}
      {checks.map((c) => {
        const I = CHECK_ICON[c.tone];
        return <div key={c.id} className={`check-item check-${c.tone}`} data-check={c.id}><I size={15} /><span>{c.text}{c.go && <> <button type="button" className="check-link" onClick={() => onGo(c.go!.dest)}>{c.go.label}</button></>}</span></div>;
      })}
    </div>
  </div>;
}

const PHASES: [string, string[]][] = [
  ['Referenzieren', ['homing']], ['Material abtasten', ['probing']], ['Höhe korrigieren', ['focusing']], ['Lasern', ['running']], ['Parken', ['finishing', 'parking']],
];
function RunPanel({ file, state, probe, fraction, lasering, seconds }: { file: string; state: string; probe?: { done: number; total: number } | null; fraction: number; lasering: boolean; seconds: number | null }) {
  const now = Math.max(0, PHASES.findIndex(([, s]) => s.includes(state)));
  const probing = state === 'probing' && probe?.total;
  const share = lasering ? fraction : probing ? probe!.done / probe!.total : 0;
  return <>
    <div className="start-block">
      <div className="start-stat-label">Auftrag läuft</div>
      <div className="start-source-value" title={file} data-testid="run-file">{file}</div>
    </div>
    <div className="start-block">
      <div className="run-percent" data-testid="run-percent">{Math.floor(share * 100)} %</div>
      <div className="progress run-progress"><div style={{ width: `${share * 100}%` }} /></div>
      <div className="muted tnum" data-testid="run-remaining">
        {lasering && seconds != null ? `noch ca. ${formatDuration(seconds * (1 - fraction))}` : probing ? `Messpunkt ${probe!.done} von ${probe!.total}` : 'Vorbereitung …'}
      </div>
    </div>
    <div className="run-phases" data-testid="run-phases">
      {PHASES.map(([label], i) => <div key={label} className={`run-phase ${i < now ? 'done' : i === now ? 'now' : ''}`} data-phase={i === now ? 'now' : undefined}>
        <span>{i < now ? <CheckIcon size={12} strokeWidth={3} /> : i === now ? <Play size={10} /> : i + 1}</span><span>{label}</span>
      </div>)}
    </div>
  </>;
}

function Result({ state, error, file, onClose }: { state: string; error?: string; file?: string | null; onClose(): void }) {
  const tone = state === 'complete' ? 'ok' : state === 'error' ? 'bad' : 'info';
  const text = state === 'complete' ? `Fertig: ${file ?? 'der Auftrag'} ist gelasert, der Kopf steht geparkt.`
    : state === 'aborted' ? 'Abgebrochen: der Laser ist aus. Zum Wiederholen erneut starten.'
    : error || 'Der Auftrag wurde wegen eines Fehlers beendet.';
  return <div data-testid="job-result" data-state={state}><Note tone={tone}>
    <div className="row" style={{ alignItems: 'flex-start' }}>
      <span className="grow">{text}</span>
      <Button variant="ghost" size="sm" iconOnly aria-label="Meldung schließen" icon={<X size={13} />} style={{ margin: '-2px -4px 0 0' }} onClick={onClose} />
    </div>
  </Note></div>;
}
