import { useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { ArrowLeft, ArrowRight, Check as CheckIcon, CircuitBoard, FlaskConical, Play, Trash2, Upload, Wand2 } from 'lucide-react';
import { Bed, boxH, boxW, layerCss, parkBox } from '@/core/model';
import { BEISPIEL } from '@/core/pcb/fixtures';
import {
  applyPlanToDoc, buildPlan, centeredOnBed, designChecks, designFacts, estimateSeconds, hasPlatineElements, lineInterval, STAGE_LABEL,
  toJob, type Plan, type PlanLayer, type ProcessKey, type ResistMethod, type Stage,
} from '@/core/pcb/job';
import { LAYER_LABEL, type LayerKind } from '@/core/pcb/layers';
import { formatDuration } from '@/core/toolpath';
import { pickFiles } from '@/platform';
import { useDoc } from '@/store/doc';
import { useUi } from '@/store/ui';
import { Button, Check, confirmDialog, Field, Note, NumberInput, Segmented, toast } from '@/ui/kit';
import { BoardPreview } from './Preview';
import { FILE_FILTERS, loadPicked, usePlatine, type LayerToggle } from './store';
import * as T from './texte';
import './platine.css';

const STEPS = ['Dateien', 'Platine', 'Verfahren', 'Vorschau', 'Lasern'];
const de = (v: number, d = 1) => v.toFixed(d).replace('.', ',');

export default function View() {
  const step = usePlatine((s) => s.step); const setStep = usePlatine((s) => s.setStep);
  const board = usePlatine((s) => s.board); const settings = usePlatine((s) => s.settings);
  const placed = usePlatine((s) => s.placed); const markPlaced = usePlatine((s) => s.markPlaced); const set = usePlatine((s) => s.set);

  // Position, mirror and laser values do not change the geometry: large boards need seconds for it.
  const { x: _x, y: _y, mirror: _m, power, speed, ...geometryInputs } = settings;
  const geometryKey = JSON.stringify(geometryInputs);
  const geometry = useMemo(() => board ? buildPlan(board, settings) : null, [board, geometryKey]); // eslint-disable-line
  const plan = useMemo(() => geometry && { ...geometry, layers: geometry.layers.map((l) => ({ ...l, powerPct: power[l.key], speed: speed[l.key] })) }, [geometry, power, speed]);
  const facts = useMemo(() => board ? designFacts(board, settings.side) : null, [board, settings.side]);
  const checks = useMemo(() => plan && facts ? designChecks(facts, settings, plan) : [], [plan, facts, settings]);

  useEffect(() => { if (plan && !placed) { set(centeredOnBed(plan)); markPlaced(); } }, [plan, placed, set, markPlaced]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.shiftKey) return;
      if (e.key === 'ArrowRight' && board && step < STEPS.length - 1) { e.preventDefault(); setStep(step + 1); }
      if (e.key === 'ArrowLeft' && step > 0) { e.preventDefault(); setStep(step - 1); }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [step, board, setStep]);

  const bad = checks.filter((c) => c.tone === 'bad').length;
  return <div className="pcb" data-testid="platine">
    <ol className="pcb-steps" aria-label="Schritte">
      {STEPS.map((label, i) => <li key={label}>
        <button type="button" className={'pcb-step' + (i < step ? ' done' : '')} aria-current={i === step ? 'step' : undefined} disabled={i > 0 && !board}
          data-testid={`pcb-step-${i + 1}`} onClick={() => setStep(i)}>
          <span className="n">{i < step ? <CheckIcon size={13} strokeWidth={2.6} /> : i + 1}</span>{label}
        </button>
      </li>)}
    </ol>
    {step === 0 && <div className="pcb-body"><StepFiles /></div>}
    {step === 1 && plan && <div className="pcb-body"><StepBoard plan={plan} /></div>}
    {step === 2 && plan && <div className="pcb-body"><StepProcess /></div>}
    {step === 3 && plan && facts && <div className="pcb-body flush"><StepPreview plan={plan} checks={checks} marker={facts.clearance && facts.clearance.mm < settings.beamMm * 1.5 ? facts.clearance : null} /></div>}
    {step === 4 && plan && <div className="pcb-body"><StepLaser plan={plan} bad={bad} /></div>}
    <footer className="pcb-foot">
      <Button icon={<ArrowLeft size={15} />} disabled={step === 0} onClick={() => setStep(step - 1)} title="Zurück (Alt+Pfeil links)">Zurück</Button>
      <div className="grow" />
      {step < 3 && bad > 0 && <span className="chip chip-bad">{bad === 1 ? '1 Problem' : `${bad} Probleme`}, siehe Vorschau</span>}
      {step < STEPS.length - 1
        ? <Button variant="primary" disabled={!board} data-testid="pcb-next" onClick={() => setStep(step + 1)} title="Weiter (Alt+Pfeil rechts)">Weiter: {STEPS[step + 1]}<ArrowRight size={15} /></Button>
        : plan && <LaserActions plan={plan} bad={bad} />}
    </footer>
  </div>;
}

/* ---- 1 Dateien ---- */
function StepFiles() {
  const { files, board, addFiles, removeFile, setKind, clear } = usePlatine();
  const [over, setOver] = useState(false);
  const load = async (picked: { name: string; bytes: Uint8Array }[]) => {
    try {
      const entries = await loadPicked(picked);
      if (!entries.length) { toast('Darin sind keine Gerber- oder Bohrdateien. Andere Dateien wählen.', 'warn'); return; }
      addFiles(entries);
    } catch (e) { toast(`${(e as Error).message} Datei neu exportieren.`, 'bad'); }
  };
  const onDrop = async (e: DragEvent) => {
    e.preventDefault(); setOver(false);
    await load(await Promise.all([...e.dataTransfer.files].map(async (f) => ({ name: f.name, bytes: new Uint8Array(await f.arrayBuffer()) }))));
  };
  const pick = async () => { const p = await pickFiles(FILE_FILTERS, true); if (p.length) await load(p); };
  const example = () => { clear(); addFiles(BEISPIEL); };
  const dropProps = { onDragOver: (e: DragEvent) => { e.preventDefault(); setOver(true); }, onDragLeave: () => setOver(false), onDrop: (e: DragEvent) => void onDrop(e) };

  if (!files.length) return <div className="pcb-wrap">
    <div>
      <h1 className="h2">Gerber-Daten laden</h1>
      <p className="muted" style={{ marginTop: 'var(--sp-1)' }}>Der Assistent führt von den Fertigungsdaten bis zur Laserebene. Geätzt wird von Hand: der Laser entfernt Lack, nicht Kupfer.</p>
    </div>
    <div className={'pcb-drop big' + (over ? ' over' : '')} data-testid="pcb-drop" {...dropProps}>
      <CircuitBoard size={36} strokeWidth={1.4} className="faint" />
      <div className="h3">Dateien hierher ziehen</div>
      <div className="muted">Gerber RS-274X, Excellon und ZIP, zum Beispiel aus KiCad oder EasyEDA</div>
      <div className="row" style={{ marginTop: 'var(--sp-3)' }}>
        <Button variant="primary" icon={<Upload size={15} />} onClick={() => void pick()}>Dateien wählen</Button>
        <Button icon={<Wand2 size={15} />} data-testid="pcb-example" onClick={example}>Beispielplatine laden</Button>
      </div>
    </div>
  </div>;

  const kinds = Object.keys(LAYER_LABEL) as LayerKind[];
  const allWarnings = [...(board?.warnings ?? []), ...files.flatMap((f) => (f.gerber?.warnings ?? f.drill?.warnings ?? []).map((w) => `${f.name}: ${w}`))];
  return <div className="pcb-wrap">
    <div className="pcb-two">
      <div className="col" style={{ gap: 'var(--sp-4)' }}>
        <div className="card" style={{ overflow: 'hidden' }}>
          <table className="pcb-table" data-testid="pcb-files">
            <thead><tr><th>Datei</th><th style={{ width: 240 }}>Erkannt als</th><th className="r">Inhalt</th><th style={{ width: 40 }} /></tr></thead>
            <tbody>{files.map((f) => <tr key={f.id}>
              <td style={{ wordBreak: 'break-all' }}>{f.name}</td>
              <td><select className="input" aria-label={`Lage von ${f.name}`} value={f.kind} onChange={(e) => setKind(f.id, e.target.value as LayerKind)}>
                {kinds.map((k) => <option key={k} value={k}>{LAYER_LABEL[k]}</option>)}
              </select></td>
              <td className="r muted tnum" style={{ whiteSpace: 'nowrap' }}>{f.error ? <span className="chip chip-bad" title={f.error}>Nicht lesbar</span> : fileSummary(f)}</td>
              <td><Button size="sm" variant="ghost" iconOnly aria-label={`${f.name} entfernen`} title="Entfernen" icon={<Trash2 size={14} />} onClick={() => removeFile(f.id)} /></td>
            </tr>)}</tbody>
          </table>
        </div>
        <div className={'pcb-drop slim' + (over ? ' over' : '')} {...dropProps}>
          <Upload size={16} className="faint" />
          <span className="muted grow">Weitere Dateien hierher ziehen</span>
          <Button size="sm" onClick={() => void pick()}>Wählen</Button>
          <Button size="sm" variant="ghost" onClick={clear}>Alle entfernen</Button>
        </div>
      </div>
      <div className="col" style={{ gap: 'var(--sp-3)' }}>
        <div className="card card-pad col">
          <div className="section-title">Erkannte Platine</div>
          {board ? <dl className="pcb-facts" data-testid="pcb-facts">
            <dt>Größe</dt><dd>{de(boxW(board.bounds))} × {de(boxH(board.bounds))} mm</dd>
            <dt>Kupfer</dt><dd>{[board.copper.top && 'oben', board.copper.bottom && 'unten'].filter(Boolean).join(', ') || 'fehlt'}</dd>
            <dt>Lötstopp</dt><dd>{[board.mask.top && 'oben', board.mask.bottom && 'unten'].filter(Boolean).join(', ') || 'fehlt'}</dd>
            <dt>Beschriftung</dt><dd>{[board.silk.top && 'oben', board.silk.bottom && 'unten'].filter(Boolean).join(', ') || 'fehlt'}</dd>
            <dt>Bohrungen</dt><dd>{board.drills.length}{board.slots.length ? ` + ${board.slots.length} Schlitze` : ''}</dd>
            <dt>Umriss</dt><dd>{board.outlineFromFile ? 'aus Datei' : 'geschätzt'}</dd>
          </dl> : <div className="muted">Noch keine Lage erkannt. Rechts neben der Datei die Lage wählen.</div>}
        </div>
        {allWarnings.map((w) => <Note key={w} tone="warn">{w}</Note>)}
        {files.some((f) => f.error) && <Note tone="bad">Eine Datei ist nicht lesbar. Sie fehlt in der Platine, bis sie neu exportiert ist.</Note>}
      </div>
    </div>
  </div>;
}

function fileSummary(f: { kind: LayerKind; gerber?: { area: number; flashes: unknown[]; strokes: unknown[] }; drill?: { hits: unknown[]; tools: Map<number, number> } }) {
  if (f.kind === 'other') return '–';
  if (f.drill) return `${f.drill.hits.length} Löcher, ${f.drill.tools.size} Werkzeuge`;
  if (f.gerber) return f.kind === 'outline' ? `${f.gerber.strokes.length} Linienzug` : `${de(f.gerber.area, 0)} mm²`;
  return '–';
}

/* ---- 2 Platine ---- */
function StepBoard({ plan }: { plan: Plan }) {
  const s = usePlatine((p) => p.settings); const set = usePlatine((p) => p.set); const board = usePlatine((p) => p.board)!;
  const size = { w: boxW(plan.bounds), h: boxH(plan.bounds) };
  const hasBottom = !!board.copper.bottom;
  return <div className="pcb-wrap">
    <div className="pcb-two" style={{ gridTemplateColumns: '320px minmax(0, 1fr)' }}>
      <div className="col" style={{ gap: 'var(--sp-3)' }}>
        <div className="card card-pad col" style={{ gap: 'var(--sp-3)' }}>
          <div className="section-title">Seite</div>
          <Segmented ariaLabel="Seite" value={s.side} onChange={(side) => set({ side })} options={[{ value: 'top', label: 'Oberseite' }, { value: 'bottom', label: 'Unterseite' }]} />
          {!hasBottom && s.side === 'bottom' && <Note tone="warn">Für die Unterseite gibt es keine Kupferlage.</Note>}
          <Check checked={s.mirror} onChange={(mirror) => set({ mirror })}><span data-testid="pcb-mirror">Spiegeln</span></Check>
          <div className="faint" style={{ fontSize: 'var(--fs-sm)' }}>Gerber zeigt die Unterseite von oben durch die Platine. Damit sie unter dem Laser passt, wird sie gespiegelt.</div>
        </div>
        <div className="card card-pad col" style={{ gap: 'var(--sp-3)' }}>
          <div className="section-title">Position auf der Arbeitsfläche</div>
          <div className="row">
            <Field label="X"><NumberInput ariaLabel="Position X" value={s.x} unit="mm" min={0} max={Bed.width} digits={1} onChange={(x) => set({ x })} /></Field>
            <Field label="Y"><NumberInput ariaLabel="Position Y" value={s.y} unit="mm" min={0} max={Bed.height} digits={1} onChange={(y) => set({ y })} /></Field>
          </div>
          <Button data-testid="pcb-center" onClick={() => set(centeredOnBed(plan))}>Mittig legen</Button>
          <div className="faint" style={{ fontSize: 'var(--fs-sm)' }}>Auftragsgröße mit Passmarken: {de(size.w)} × {de(size.h)} mm. In der Karte lässt sich die Platine auch ziehen.</div>
        </div>
        <div className="card card-pad col" style={{ gap: 'var(--sp-3)' }}>
          <div className="section-title">Passmarken</div>
          <Segmented ariaLabel="Passmarken" value={String(s.fiducials)} onChange={(v) => set({ fiducials: +v as 0 | 2 | 4 })} options={[{ value: '0', label: 'Keine' }, { value: '2', label: 'Zwei' }, { value: '4', label: 'Vier' }]} />
          {s.fiducials > 0 && <div className="row">
            <Field label="Größe"><NumberInput ariaLabel="Größe der Passmarke" value={s.fiducialDiaMm} unit="mm" min={0.3} max={3} step={0.1} onChange={(fiducialDiaMm) => set({ fiducialDiaMm })} /></Field>
            <Field label="Abstand"><NumberInput ariaLabel="Abstand der Passmarke" value={s.fiducialOffsetMm} unit="mm" min={1} max={20} step={0.5} onChange={(fiducialOffsetMm) => set({ fiducialOffsetMm })} /></Field>
          </div>}
          <div className="faint" style={{ fontSize: 'var(--fs-sm)' }}>Geätzte Punkte außerhalb des Umrisses. Aufgebohrt und auf Stifte gesetzt, finden sie nach dem Wenden und beim Lötstopp dieselbe Lage wieder. Sie liegen symmetrisch zur senkrechten Mitte: um diese Achse wenden.</div>
        </div>
      </div>
      <div className="col" style={{ gap: 'var(--sp-3)' }}>
        <BedMap plan={plan} />
        <Note>Vor jedem Lasern neu scannen: Die Platine kann seit dem letzten Scan verrutscht sein. Die Position hier ist die Lage im Auftrag, die echte Lage prüft der Rahmen unter Starten.</Note>
      </div>
    </div>
  </div>;
}

function BedMap({ plan }: { plan: Plan }) {
  const s = usePlatine((p) => p.settings); const set = usePlatine((p) => p.set); const board = usePlatine((p) => p.board)!;
  const svg = useRef<SVGSVGElement>(null);
  const grab = useRef<{ dx: number; dy: number } | null>(null);
  const toBed = (e: ReactPointerEvent) => {
    const r = svg.current!.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * Bed.width, y: ((e.clientY - r.top) / r.height) * Bed.height };
  };
  const outline = useMemo(() => board.outline.map((p) => pathD(p.map((q) => toJob(q, plan.bounds, s.mirror)))).join(' '), [board, plan, s.mirror]);
  const copper = useMemo(() => (board.copper[s.side]?.polys ?? []).map((p) => pathD(p.map((q) => toJob(q, plan.bounds, s.mirror)))).join(' '), [board, plan, s.mirror, s.side]);
  const park = parkBox();
  const grid: number[] = [];
  for (let v = 50; v < Math.max(Bed.width, Bed.height); v += 50) grid.push(v);
  const w = boxW(plan.bounds), h = boxH(plan.bounds);
  return <svg ref={svg} className="pcb-bed" data-testid="pcb-bed" viewBox={`0 0 ${Bed.width} ${Bed.height}`} role="img" aria-label="Arbeitsfläche mit Platine"
    onPointerMove={(e) => { if (!grab.current) return; const m = toBed(e); set({ x: Math.round(Math.min(Bed.width - w, Math.max(0, m.x - grab.current.dx))), y: Math.round(Math.min(Bed.height - h, Math.max(0, m.y - grab.current.dy))) }); }}
    onPointerUp={() => { grab.current = null; }}>
    <rect x={0} y={0} width={Bed.width} height={Bed.height} rx={4} style={{ fill: 'var(--sheet)' }} />
    {grid.map((v) => <g key={v}>
      {v < Bed.width && <line x1={v} x2={v} y1={0} y2={Bed.height} strokeWidth={0.5} style={{ stroke: 'var(--grid-major)' }} />}
      {v < Bed.height && <line y1={v} y2={v} x1={0} x2={Bed.width} strokeWidth={0.5} style={{ stroke: 'var(--grid-major)' }} />}
    </g>)}
    <rect x={park.minX} y={park.minY} width={park.maxX - park.minX} height={park.maxY - park.minY} style={{ fill: 'var(--park)' }} />
    <text x={park.minX + 4} y={park.minY + 12} fontSize={9} style={{ fill: 'var(--bad)' }}>Parkecke</text>
    <g transform={`translate(${s.x} ${s.y})`} style={{ cursor: 'grab' }} data-testid="pcb-bed-board"
      onPointerDown={(e) => { const m = toBed(e); grab.current = { dx: m.x - s.x, dy: m.y - s.y }; svg.current?.setPointerCapture(e.pointerId); }}>
      <rect x={0} y={0} width={w} height={h} fill="transparent" />
      <path d={outline} fillRule="evenodd" style={{ fill: 'var(--pcb-fr4)' }} />
      <path d={copper} fillRule="evenodd" style={{ fill: 'var(--pcb-copper)' }} />
      {plan.fiducials.map((f, i) => { const q = toJob(f, plan.bounds, s.mirror); return <circle key={i} cx={q.x} cy={q.y} r={Math.max(s.fiducialDiaMm / 2, 1.2)} style={{ fill: 'var(--pcb-mark)' }} />; })}
    </g>
  </svg>;
}
const pathD = (p: { x: number; y: number }[]) => p.map((q, i) => `${i ? 'L' : 'M'}${q.x.toFixed(2)} ${q.y.toFixed(2)}`).join('') + 'Z';

/* ---- 3 Verfahren ---- */
function StepProcess() {
  const s = usePlatine((p) => p.settings); const set = usePlatine((p) => p.set); const board = usePlatine((p) => p.board)!;
  const m = T.METHODEN[s.method];
  return <div className="pcb-wrap">
    <div className="pcb-two">
      <div className="col" style={{ gap: 'var(--sp-3)' }}>
        <section className={'card card-pad pcb-proc' + (s.resist ? '' : ' off')}>
          <div className="pcb-proc-head">
            <Check checked={s.resist} onChange={(resist) => set({ resist })}>Lack entfernen und ätzen</Check>
            <span className="grow" /><span className="chip">Arbeitsgang 1</span>
          </div>
          <Segmented ariaLabel="Verfahren" value={s.method} onChange={(method: ResistMethod) => set({ method })}
            options={(Object.keys(T.METHODEN) as ResistMethod[]).map((k) => ({ value: k, label: T.METHODEN[k].name, title: T.METHODEN[k].kurz }))} />
          <p>{m.text}</p>
          <p className="pcb-needs"><b>Braucht: </b>{m.braucht}</p>
          {s.method === 'isolation' && <div className="pcb-opts">
            <Field label="Durchgänge"><NumberInput ariaLabel="Durchgänge" value={s.passes} min={1} max={10} digits={0} onChange={(passes) => set({ passes: Math.round(passes) })} /></Field>
            <Check checked={s.removeRest} onChange={(removeRest) => set({ removeRest })}><span data-testid="pcb-rest">Restkupfer auch entfernen</span></Check>
          </div>}
          {s.method !== 'expose' && <p className="pcb-needs">{T.LACK_HINWEIS}</p>}
          {s.method === 'expose' && <Note tone="warn">Dieser Weg ist hier nicht erprobt und reagiert empfindlich auf Streulicht. Erst Probestreifen belichten und entwickeln.</Note>}
        </section>
        <section className={'card card-pad pcb-proc' + (s.drillMarks ? '' : ' off')}>
          <div className="pcb-proc-head">
            <Check checked={s.drillMarks} onChange={(drillMarks) => set({ drillMarks })}>Bohrmarken</Check>
            <span className="grow" /><span className="chip">Arbeitsgang 1</span>
          </div>
          <p>{T.TEXT_BOHRMARKEN}</p>
          <p className="pcb-needs"><b>Braucht: </b>{T.BRAUCHT_BOHRMARKEN}</p>
          {board.drills.length === 0 && <Note tone="warn">Es ist keine Bohrdatei geladen, also gibt es keine Marken. In Schritt 1 ergänzen.</Note>}
          <div className="pcb-opts">
            <Field label="Form"><Segmented ariaLabel="Form der Bohrmarke" value={s.drillStyle} onChange={(drillStyle) => set({ drillStyle })} options={[{ value: 'dot', label: 'Punkt' }, { value: 'cross', label: 'Kreuz' }]} /></Field>
            <Field label="Größe"><NumberInput ariaLabel="Größe der Bohrmarke" value={s.drillMarkMm} unit="mm" min={0.2} max={1.5} step={0.05} onChange={(drillMarkMm) => set({ drillMarkMm })} /></Field>
          </div>
        </section>
        <section className={'card card-pad pcb-proc' + (s.mask ? '' : ' off')}>
          <div className="pcb-proc-head">
            <Check checked={s.mask} onChange={(mask) => set({ mask })}><span data-testid="pcb-mask">Lötstopp freilegen</span></Check>
            <span className="grow" /><span className="chip">Arbeitsgang 2, nach dem Ätzen</span>
          </div>
          <p>{T.TEXT_LOETSTOPP}</p>
          <p className="pcb-needs"><b>Braucht: </b>{T.BRAUCHT_LOETSTOPP}</p>
          {!board.mask[s.side] && <Note tone="warn">Für diese Seite ist keine Lötstopp-Datei geladen.</Note>}
        </section>
        <section className={'card card-pad pcb-proc' + (s.silk ? '' : ' off')}>
          <div className="pcb-proc-head">
            <Check checked={s.silk} onChange={(silk) => set({ silk })}><span data-testid="pcb-silk">Beschriftung</span></Check>
            <span className="grow" /><span className="chip">Arbeitsgang 3, auf dem Lack</span>
          </div>
          <p>{T.TEXT_BESCHRIFTUNG}</p>
          <p className="pcb-needs"><b>Braucht: </b>{T.BRAUCHT_BESCHRIFTUNG}</p>
          {!board.silk[s.side] && <Note tone="warn">Für diese Seite ist keine Beschriftungs-Datei geladen.</Note>}
        </section>
        <section className="card card-pad pcb-proc">
          <div className="pcb-proc-head"><Check checked={s.outlineMark} onChange={(outlineMark) => set({ outlineMark })}>Umriss in den Lack markieren</Check></div>
          <p className="pcb-needs">Eine Linie als Sägehilfe. Der Laser schneidet FR4 nicht. Ohne Haken ist die Ebene vorhanden, aber ohne Ausgabe.</p>
        </section>
      </div>
      <div className="col" style={{ gap: 'var(--sp-3)' }}>
        <div className="card card-pad col" style={{ gap: 'var(--sp-3)' }}>
          <div className="section-title">Strahl</div>
          <Field label="Strahlbreite" hint="Startwert, kein Messwert. Mit der Linienbreite aus dem Materialtest ersetzen."><NumberInput ariaLabel="Strahlbreite" value={s.beamMm} unit="mm" min={0.05} max={0.6} step={0.01} onChange={(beamMm) => set({ beamMm })} /></Field>
          <Field label="Überlappung"><NumberInput ariaLabel="Überlappung" value={s.overlapPct} unit="%" min={0} max={80} step={5} digits={0} onChange={(overlapPct) => set({ overlapPct })} /></Field>
          <dl className="pcb-facts"><dt>Zeilenabstand</dt><dd data-testid="pcb-interval">{de(lineInterval(s), 3)} mm</dd></dl>
        </div>
        <div className="card card-pad col" style={{ gap: 'var(--sp-3)' }}>
          <div className="section-title">Das geht mit dieser Diode nicht</div>
          {T.GEHT_NICHT.map((g) => <div key={g.titel}><b style={{ fontWeight: 600 }}>{g.titel}</b><div className="muted" style={{ fontSize: 'var(--fs-sm)', marginTop: 2 }}>{g.text}</div></div>)}
        </div>
        <div className="faint" style={{ fontSize: 'var(--fs-sm)', padding: '0 var(--sp-1)' }}>Stand aus Physik und Berichten von Bastlern, auf dieser Maschine noch nicht erprobt.</div>
      </div>
    </div>
  </div>;
}

/* ---- 4 Vorschau ---- */
const LAYER_ROWS: { key: LayerToggle; label: string; color: string; show: (p: Plan, hasDrill: boolean) => boolean }[] = [
  { key: 'copper', label: 'Kupfer', color: 'var(--pcb-copper)', show: () => true },
  { key: 'resist', label: 'Laserbahnen', color: 'var(--pcb-laser)', show: (p) => p.layers.some((l) => l.key === 'resist') },
  { key: 'drill', label: 'Bohrungen', color: 'var(--pcb-drill)', show: (_, d) => d },
  { key: 'marks', label: 'Bohrmarken', color: 'var(--pcb-mark)', show: (p) => p.layers.some((l) => l.key === 'drill') },
  { key: 'fiducial', label: 'Passmarken', color: 'var(--pcb-mark)', show: (p) => p.layers.some((l) => l.key === 'fiducial') },
  { key: 'mask', label: 'Lötstopp-Öffnungen', color: 'var(--pcb-mask)', show: (p) => p.layers.some((l) => l.key === 'mask') },
  { key: 'silk', label: 'Beschriftung', color: 'var(--pcb-silk)', show: (p) => p.layers.some((l) => l.key === 'silk') },
  { key: 'outline', label: 'Umriss', color: 'var(--pcb-edge)', show: () => true },
];

function StepPreview({ plan, checks, marker }: { plan: Plan; checks: ReturnType<typeof designChecks>; marker: { mm: number; at: { x: number; y: number } } | null }) {
  const { settings: s, board, viewFrom, setViewFrom, hidden, toggle } = usePlatine();
  const b = board!;
  const under = (s.side === 'bottom') === s.mirror && viewFrom === s.side;
  return <>
    <div className="pcb-view">
      <BoardPreview board={b} plan={plan} beamMm={s.beamMm} side={s.side} viewFrom={viewFrom} hidden={hidden} marker={marker} />
      <div className="pcb-view-bar">
        <Segmented ariaLabel="Ansicht" value={viewFrom} onChange={setViewFrom} options={[{ value: 'top', label: 'Von oben' }, { value: 'bottom', label: 'Von unten' }]} />
        <span className="chip" style={{ background: 'var(--surface)', boxShadow: 'var(--shadow-1)' }}>{under ? 'So liegt sie unter dem Laser' : 'Nicht die Ansicht unter dem Laser'}</span>
      </div>
    </div>
    <aside className="panel pcb-side">
      <div className="col">
        <div className="section-title">Lagen, {s.side === 'top' ? 'Oberseite' : 'Unterseite'}</div>
        {LAYER_ROWS.filter((r) => r.show(plan, b.drills.length > 0)).map((r) => <div className="pcb-layer" key={r.key}>
          <Check checked={!hidden[r.key]} onChange={() => toggle(r.key)}><span data-testid={`pcb-layer-${r.key}`}>{r.label}</span></Check>
          <span className="grow" /><span className="pcb-swatch" style={{ background: r.color }} />
        </div>)}
      </div>
      <div className="col" data-testid="pcb-checks">
        <div className="section-title">Prüfung gegen {de(s.beamMm, 2)} mm Strahl</div>
        {checks.map((c) => <Note key={c.id} tone={c.tone}><b style={{ fontWeight: 600 }}>{c.title}</b><div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{c.text}</div></Note>)}
        {plan.warnings.map((w) => <Note key={w} tone="warn">{w}</Note>)}
        <div className="faint" style={{ fontSize: 'var(--fs-sm)' }}>Die Prüfung rechnet mit der Datei. Mechanische Schwingungen oder Lack, der ausfranst, sieht sie nicht: feine Strukturen erst auf einem Reststück probieren.</div>
      </div>
    </aside>
  </>;
}

/* ---- 5 Lasern ---- */
const stagesOf = (plan: Plan): Stage[] => (['resist', 'mask', 'silk'] as Stage[]).filter((st) => plan.layers.some((l) => l.stage === st));

function StepLaser({ plan, bad }: { plan: Plan; bad: number }) {
  const { settings: s, set, stage, setStage } = usePlatine();
  const go = useUi((u) => u.go);
  const stages = stagesOf(plan);
  const current: Stage = stages.includes(stage) ? stage : stages[0] ?? 'resist';
  const rows = plan.layers.filter((l) => l.stage === current && (l.key !== 'outline' || s.outlineMark));
  const total = rows.reduce((sum, l) => sum + estimateSeconds(l), 0);
  const seen = new Set<string>();
  const setProc = (key: ProcessKey, field: 'power' | 'speed', v: number) => set({ [field]: { ...s[field], [key]: v } });
  const steps = T.arbeitsablauf(s.method, s.mask, s.silk);
  return <div className="pcb-wrap">
    <Note tone="warn"><b style={{ fontWeight: 600 }}>Pflicht: Materialtest auf demselben Lack.</b> Unten stehen nur Startwerte, sie sind nicht geprüft. Welche Leistung den Lack sauber entfernt, zeigt nur Ihr eigener Test auf einem Probestück, danach die Werte hier eintragen. Nie auf ungetestetem Lack lasern.</Note>
    {bad > 0 && <Note tone="bad">Die Vorschau meldet {bad === 1 ? 'ein Problem' : `${bad} Probleme`}. So wird das Ergebnis voraussichtlich nicht funktionieren.</Note>}
    <div className="pcb-pair">
      <div className="col" style={{ gap: 'var(--sp-3)' }}>
        <div className="card card-pad col" style={{ gap: 'var(--sp-3)' }}>
          <div className="row">
            <div className="section-title grow">Jetzt lasern</div>
            <span className="chip chip-warn">Startwerte, ungeprüft</span>
          </div>
          {stages.length > 1 && <Segmented ariaLabel="Arbeitsgang" value={current} onChange={setStage} options={stages.map((st) => ({ value: st, label: STAGE_LABEL[st] }))} />}
          {rows.length === 0 ? <div className="empty">In Schritt 3 mindestens ein Verfahren wählen.</div> :
            <table className="pcb-table" data-testid="pcb-processes">
              <thead><tr><th style={{ paddingLeft: 0 }}>Ebene</th><th style={{ width: 92 }}>Leistung</th><th style={{ width: 112 }}>Tempo</th><th className="r" style={{ paddingRight: 0 }}>Dauer</th></tr></thead>
              <tbody>{rows.map((l: PlanLayer) => { const first = !seen.has(l.key); seen.add(l.key); return <tr key={l.name}>
                <td style={{ paddingLeft: 0 }}><span className="row" style={{ gap: 6 }}><span className="pcb-swatch" style={{ background: layerCss(l) }} />{l.name.replace('Platine ', '')}<span className="faint">{l.mode === 'FILL' ? 'Fläche' : 'Linie'}</span></span></td>
                <td>{first ? <NumberInput ariaLabel={`Leistung ${l.name}`} value={s.power[l.key]} unit="%" min={8} max={100} digits={0} onChange={(v) => setProc(l.key, 'power', v)} /> : <span className="muted">wie oben</span>}</td>
                <td>{first ? <NumberInput ariaLabel={`Tempo ${l.name}`} value={s.speed[l.key]} min={100} max={12000} step={100} digits={0} title="mm/min" onChange={(v) => setProc(l.key, 'speed', v)} /> : <span className="muted">wie oben</span>}</td>
                <td className="r muted tnum" style={{ paddingRight: 0, whiteSpace: 'nowrap' }}>{formatDuration(estimateSeconds(l))}</td>
              </tr>; })}</tbody>
            </table>}
          <div className="row">
            <span className="muted grow" style={{ fontSize: 'var(--fs-sm)' }}>Tempo in mm/min. Untergrenze 8 %: darunter zündet der Laser nicht sicher.</span>
            <span className="tnum" data-testid="pcb-time">Grob {formatDuration(total)}</span>
          </div>
          <Button icon={<FlaskConical size={15} />} onClick={() => go('werkstatt')}>Zum Materialtest in der Werkstatt</Button>
        </div>
        <div className="card card-pad col">
          <div className="section-title">Sicherheit</div>
          <ul className="pcb-list">{T.SICHERHEIT.map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
      </div>
      <div className="card card-pad col">
        <div className="section-title">Ablauf an der Werkbank</div>
        <ol className="pcb-workflow" data-testid="pcb-workflow">
          {steps.map((st) => <li key={st.titel} className={st.laser ? 'is-laser' : undefined}><b>{st.titel}.</b> <span className="muted">{st.text}</span></li>)}
        </ol>
      </div>
    </div>
  </div>;
}

function LaserActions({ plan, bad }: { plan: Plan; bad: number }) {
  const { settings: s, stage } = usePlatine();
  const go = useUi((u) => u.go);
  const stages = stagesOf(plan);
  const current: Stage = stages.includes(stage) ? stage : stages[0] ?? 'resist';
  const send = async (dest: 'motiv' | 'start') => {
    const store = useDoc.getState();
    if (bad > 0 && !await confirmDialog({ title: 'Trotz Problemen übernehmen?', body: 'Die Vorschau meldet Probleme, die das Ergebnis verderben können.', okLabel: 'Trotzdem übernehmen' })) return;
    let replace = false;
    if (hasPlatineElements(store.doc)) {
      if (!await confirmDialog({ title: 'Platine ersetzen?', body: 'Auf dieser Platte liegt schon eine Platine. Sie wird durch die neue ersetzt. Für beide Seiten im Motiv eine zweite Platte anlegen.', okLabel: 'Ersetzen' })) return;
      replace = true;
    }
    let ids: string[] = [];
    store.commit((d) => { const r = applyPlanToDoc(d, plan, s, { stage: current, replace }); ids = r.ids; return r.doc; });
    useDoc.getState().select(ids);
    toast(`Platine übernommen. Ausgabe an: ${STAGE_LABEL[current]}.`, 'ok');
    go(dest);
  };
  return <>
    <Button icon={<Play size={15} />} data-testid="pcb-to-start" disabled={!plan.layers.length} onClick={() => void send('start')}>Zu Starten</Button>
    <Button variant="primary" data-testid="pcb-to-motiv" disabled={!plan.layers.length} onClick={() => void send('motiv')}>Ins Motiv übernehmen</Button>
  </>;
}

