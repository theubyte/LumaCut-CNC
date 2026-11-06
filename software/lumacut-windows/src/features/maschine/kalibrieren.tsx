import { type ReactNode, useEffect, useRef, useState } from 'react';
import { CheckCircle2, ChevronRight, CircleDashed, XCircle } from 'lucide-react';
import { machineAction } from '@/pi/actions';
import { pi } from '@/pi/client';
import { loadMaterials } from '@/pi/materials';
import { useMachine } from '@/pi/machine';
import { useWorkspace } from '@/pi/workspace';
import type { MachineStatus } from '@/pi/types';
import { Bed } from '@/core/model';
import { Button, Check, confirmDialog, Dialog, Field, Note, NumberInput, Segmented, toast } from '@/ui/kit';
import { cameraCalibrated, type CameraCalibration, type CameraSettings } from './kamera';
import { de, moveLock, probeLock } from './locks';
import { LockedButton, LockLine, Stat, when } from './parts';

type Tone = 'ok' | 'warn' | 'bad' | 'off';
interface Item { id: string; title: string; group: string; tone: Tone; state: string; value: string; body: ReactNode }

const NOT_YET = 'Der Assistent braucht die Bildauswertung der Tablet-App und kommt in einer späteren Etappe. Bis dahin dort messen; das Ergebnis liegt auf dem Pi und erscheint hier.';

interface BedMap { cols: number; rows: number; lowest: number; highest: number; range: number; mean?: number; measured_at?: unknown; z?: number[]; missing_points?: unknown[]; missing?: number }
interface Matcal {
  kind: 'engrave' | 'cut'; material: string; state: string; steps?: number; error?: string;
  result?: Record<string, { power?: number; speed?: number; tone?: number }> & { best?: { speed?: number; passes?: number } };
  saved?: { id: string; name: string; process: string }[];
}

export function Kalibrieren() {
  const { status: s, online } = useMachine();
  const [cal, setCal] = useState<CameraCalibration | null>(null);
  const [cam, setCam] = useState<CameraSettings | null>(null);
  useEffect(() => {
    if (!online) return;
    pi.get<CameraCalibration>('/api/camera/calibration').then(setCal).catch(() => setCal(null));
    pi.get<CameraSettings>('/api/camera/settings').then(setCam).catch(() => setCam(null));
  }, [online]);
  const cfg = s.config;
  const camOk = cameraCalibrated(cal);
  const off = s.probe_xy_offset_mm as [number, number] | null | undefined;
  const motion = cfg?.motion as { accel?: number; speed?: number } | null | undefined;
  const bed = s.bed_map as BedMap | null | undefined;
  const mc = s.material_calibration as Matcal | null | undefined;
  const items: Item[] = [
    { id: 'kamera', group: 'Grundlagen', title: 'Kopfkamera', tone: camOk ? 'ok' : 'bad', state: camOk ? 'erledigt' : 'fehlt',
      value: camOk ? `${cal?.android?.photoWidth ?? cal?.image_width} × ${cal?.android?.photoHeight ?? cal?.image_height} px` : 'Grundlage für Scan und Materialtest',
      body: <CameraDetail cal={cal} ok={camOk} /> },
    { id: 'licht', group: 'Grundlagen', title: 'Kamera-Licht', tone: cam?.white_balance != null ? 'ok' : 'warn', state: cam?.white_balance != null ? 'fest' : 'automatisch',
      value: cam?.white_balance != null ? `Weißabgleich ${cam.white_balance} K` : 'Weißabgleich automatisch',
      body: <LightDetail cam={cam} /> },
    { id: 'taster', group: 'Grundlagen', title: 'Taster-Versatz', tone: off ? 'ok' : 'bad', state: off ? 'erledigt' : 'fehlt',
      value: off ? `X ${de(off[0])}, Y ${de(off[1])} mm` : 'Nötig zum Abtasten',
      body: <ProbeDetail s={s} /> },
    { id: 'fokus', group: 'Grundlagen', title: 'Laser-Fokus', tone: cfg?.focus_gap_mm != null ? 'ok' : 'off', state: 'Wert',
      value: cfg?.focus_gap_mm != null ? `Fokusabstand ${de(cfg.focus_gap_mm)} mm` : '–',
      body: <FocusDetail s={s} /> },
    { id: 'bewegung', group: 'Grundlagen', title: 'Bewegung', tone: motion?.accel ? 'ok' : 'warn', state: motion?.accel ? 'gespeichert' : 'Firmware-Werte',
      value: motion?.accel ? `${de(motion.accel, 0)} mm/s², bis ${de(motion.speed, 0)} mm/s` : '500 mm/s², bis 150 mm/s',
      body: <MotionDetail /> },
    { id: 'bett', group: 'Grundlagen', title: 'Bettkarte', tone: bed ? 'ok' : 'warn', state: bed ? 'gemessen' : 'offen',
      value: bed ? `${bed.cols} × ${bed.rows} Punkte, Spanne ${de(bed.range, 2)} mm` : 'Höhenprofil des leeren Betts',
      body: <BedDetail /> },
    { id: 'material', group: 'Je Material', title: 'Materialtest', tone: mc?.state === 'complete' ? 'ok' : mc?.state === 'error' ? 'bad' : 'off', state: mc ? ({ running: 'läuft', complete: 'fertig', error: 'Fehler', aborted: 'abgebrochen' } as Record<string, string>)[mc.state] ?? mc.state : 'noch keiner',
      value: mc ? `${mc.kind === 'engrave' ? 'Gravur' : 'Schnitt'}: ${mc.material}` : 'Gravur und Schnitt mit der Kamera',
      body: <MatcalDetail camOk={camOk} /> },
  ];
  const [sel, setSel] = useState(() => { try { return localStorage.getItem('lc.kal') ?? 'kamera'; } catch { return 'kamera'; } });
  const pick = (id: string) => { setSel(id); try { localStorage.setItem('lc.kal', id); } catch { /* convenience */ } };
  const cur = items.find((i) => i.id === sel) ?? items[0];
  const groups = [...new Set(items.map((i) => i.group))];
  return <div className="m-kal">
    <nav className="card m-kal-list" aria-label="Kalibrierungen">
      {groups.map((g) => <div key={g}>
        <div className="section-title m-kal-group">{g}</div>
        {items.filter((i) => i.group === g).map((i) => <button key={i.id} type="button" className="m-kal-item" aria-current={i.id === cur.id ? 'true' : undefined} data-testid={`kal-${i.id}`} onClick={() => pick(i.id)}>
          <ToneIcon tone={i.tone} />
          <span className="grow"><span className="m-kal-title">{i.title}</span><span className="m-kal-value">{i.value}</span></span>
          <ChevronRight size={14} className="faint" />
        </button>)}
      </div>)}
    </nav>
    <section className="card card-pad col m-gap m-kal-detail" data-testid="kal-detail">
      <div className="row"><h2 className="h2 grow">{cur.title}</h2><span className={`chip ${cur.tone === 'off' ? '' : `chip-${cur.tone}`}`}>{cur.state}</span></div>
      {cur.body}
    </section>
  </div>;
}

const ToneIcon = ({ tone }: { tone: Tone }) => tone === 'ok' ? <CheckCircle2 size={16} style={{ color: 'var(--ok)' }} /> : tone === 'bad' ? <XCircle size={16} style={{ color: 'var(--bad)' }} /> : <CircleDashed size={16} style={{ color: tone === 'warn' ? 'var(--warn)' : 'var(--faint)' }} />;

function CameraDetail({ cal, ok }: { cal: CameraCalibration | null; ok: boolean }) {
  const a = cal?.android;
  return <>
    <p className="muted">Misst Linse, Maßstab und Lage der Kamera zum Laser. Grundlage für Scan und Materialtest.</p>
    {ok
      ? <div className="m-stats m-stats-2">
          <Stat label="Bildgröße" value={`${a?.photoWidth ?? cal?.image_width} × ${a?.photoHeight ?? cal?.image_height} px`} />
          <Stat label="Genauigkeit" value={a?.lens?.rmsMm != null ? `${de(a.lens.rmsMm, 2)} mm` : 'ohne Linsenmodell'} />
          <Stat label="Scanhöhe" value={a?.scanZ != null ? `Z ${de(a.scanZ)} mm` : cal?.scan_z != null ? `Z ${de(cal.scan_z)} mm` : '–'} />
          <Stat label="Stand" mono={false} value={when(cal?.updated_at)} />
        </div>
      : <Note tone="warn">Noch keine Messung auf dem Pi.</Note>}
    <p className="faint m-small">{NOT_YET}</p>
  </>;
}

function LightDetail({ cam }: { cam: CameraSettings | null }) {
  return <>
    <p className="muted">Feste Kamerawerte, damit die Bilder eines Scans gleich hell und gleich farbig sind.</p>
    <div className="m-stats m-stats-2">
      <Stat label="Weißabgleich" value={cam?.white_balance != null ? `${cam.white_balance} K` : 'automatisch'} />
      <Stat label="Belichtung" value={cam?.exposure ?? 'automatisch'} />
      <Stat label="Verstärkung" value={cam?.gain ?? 'automatisch'} />
      <Stat label="Licht beim Scan" value={cam?.light != null ? `${cam.light} %` : 'wie eingestellt'} />
    </div>
    <p className="faint m-small">Belichtung und Weißabgleich lassen sich im Reiter Kamera von Hand setzen. Der Randabfall wird in der Tablet-App gemessen.</p>
  </>;
}

/** Entered values go to /api/settings; the Pi then forgets the measured surface, so the operator is told first. */
function SettingsDialog({ title, fields, onClose, note }: { title: string; note: string; onClose(): void; fields: { key: string; label: string; value: number; min: number; max: number; digits?: number }[] }) {
  const [v, setV] = useState<Record<string, number>>(() => Object.fromEntries(fields.map((f) => [f.key, f.value])));
  const save = async () => {
    try { await pi.settings(v); toast('Gespeichert. Werkstück vor dem nächsten Auftrag neu abtasten.', 'ok'); onClose(); }
    catch (e) { toast((e as Error).message, 'bad'); }
  };
  return <Dialog title={title} onClose={onClose} footer={<><Button onClick={onClose}>Abbrechen</Button><Button variant="primary" onClick={() => void save()} data-testid="settings-save">Speichern</Button></>}>
    <div className="col m-gap">
      <div className="m-form-2">{fields.map((f) => <Field key={f.key} label={f.label}><NumberInput ariaLabel={f.label} value={v[f.key]} min={f.min} max={f.max} step={0.1} digits={f.digits ?? 2} unit="mm" onChange={(x) => setV({ ...v, [f.key]: x })} /></Field>)}</div>
      <Note tone="warn">{note}</Note>
    </div>
  </Dialog>;
}

function ProbeDetail({ s }: { s: MachineStatus }) {
  const [edit, setEdit] = useState(false);
  const off = s.probe_xy_offset_mm as [number, number] | null | undefined;
  return <>
    <p className="muted">So weit liegt die Tasterspitze neben dem Laserpunkt. Ohne diesen Wert tastet der Pi nicht ab.</p>
    <div className="m-stats m-stats-2">
      <Stat label="Versatz X" value={off ? `${de(off[0])} mm` : '–'} tone={off ? undefined : 'bad'} />
      <Stat label="Versatz Y" value={off ? `${de(off[1])} mm` : '–'} tone={off ? undefined : 'bad'} />
      <Stat label="Taster in Firmware" mono={false} value={s.z_probe_supported === false ? 'Nein' : s.z_probe_supported ? 'Ja' : 'unbekannt'} />
    </div>
    <div className="row"><Button onClick={() => setEdit(true)} data-testid="probe-edit">Werte eintragen</Button></div>
    <p className="faint m-small">Einmessen mit gelasertem Kreuz geht bisher in der Tablet-App. Hier lassen sich bekannte Werte eintragen.</p>
    {edit && <SettingsDialog title="Taster-Versatz" onClose={() => setEdit(false)} note="Der Pi vergisst dabei die gemessene Werkstückoberfläche."
      fields={[{ key: 'probe_offset_x_mm', label: 'Versatz X', value: off?.[0] ?? 0, min: -80, max: 80 }, { key: 'probe_offset_y_mm', label: 'Versatz Y', value: off?.[1] ?? 0, min: -80, max: 80 }]} />}
  </>;
}

function FocusDetail({ s }: { s: MachineStatus }) {
  const [edit, setEdit] = useState(false);
  const c = s.config;
  const tip = c?.z_switch_tip_offset_mm as number | undefined;
  return <>
    <p className="muted">Abstand von der Werkstückoberfläche, in dem der Laserpunkt am kleinsten ist.</p>
    <div className="m-stats m-stats-2">
      <Stat label="Fokusabstand" value={`${de(c?.focus_gap_mm)} mm`} />
      <Stat label="Schalter zu Spitze" value={`${de(tip)} mm`} />
      <Stat label="Z-Rückzug" value={`${de(c?.z_clearance_mm)} mm`} />
      <Stat label="Fokus Z jetzt" value={s.laser_focus_z == null ? '–' : `${de(s.laser_focus_z as number, 2)} mm`} />
    </div>
    <div className="row"><Button onClick={() => setEdit(true)} data-testid="focus-edit">Werte eintragen</Button></div>
    <p className="faint m-small">{NOT_YET}</p>
    {edit && <SettingsDialog title="Fokus und Höhen" onClose={() => setEdit(false)} note="Der Pi vergisst dabei die gemessene Werkstückoberfläche. Falsche Werte führen zu unscharfen Schnitten, im Zweifel unverändert lassen."
      fields={[{ key: 'focus_gap_mm', label: 'Fokusabstand', value: c?.focus_gap_mm ?? 0, min: 0.1, max: 30 }, { key: 'z_switch_tip_offset_mm', label: 'Schalter zu Spitze', value: tip ?? 0, min: -20, max: 20 }, { key: 'z_clearance_mm', label: 'Z-Rückzug', value: c?.z_clearance_mm ?? 20, min: 0.5, max: 50 }]} />}
  </>;
}

function MotionDetail() {
  const { status: s, online } = useMachine();
  const stored = s.config?.motion as { accel?: number; speed?: number } | null | undefined;
  const [accel, setAccel] = useState(stored?.accel ?? 1000);
  const [speed, setSpeed] = useState(stored?.speed ?? 100);
  const [span, setSpan] = useState(40);
  const [cycles, setCycles] = useState(6);
  const [busy, setBusy] = useState(false);
  const pos = s.position;
  const lock = moveLock(s, online);
  const test = async () => {
    if (!pos) return;
    const [x, y] = pos;
    if (x - span < 0 || x + span > Bed.width || y - span < 0 || y + span > Bed.height) { toast(`Für ±${span} mm steht der Kopf zu nah am Rand. Erst zur Mitte fahren.`, 'bad'); return; }
    setBusy(true);
    try { await machineAction('motion_test', { accel, speed, x, y, span, cycles }, { go: { detail: `Der Kopf fährt ${cycles}-mal um ±${span} mm um die aktuelle Position, mit ${accel} mm/s² und bis ${speed} mm/s. Der Laser bleibt aus, es wird laut.` } }); }
    catch { /* toast */ } finally { setBusy(false); }
  };
  const store = async () => {
    if (!(await confirmDialog({ title: 'Grenzen speichern?', body: `Alle Aufträge fahren dann mit ${accel} mm/s² und bis ${speed} mm/s. Nur speichern, wenn die Testfahrt sauber lief.`, okLabel: 'Speichern' }))) return;
    await machineAction('motion_limits', { accel, speed }).catch(() => {});
  };
  return <>
    <p className="muted">Beschleunigung und Tempo für X und Y. Aufträge fahren damit, der Anlauf beim Gravieren wird daraus berechnet.</p>
    <div className="m-stats m-stats-2">
      <Stat label="Beschleunigung" value={stored?.accel ? `${de(stored.accel, 0)} mm/s²` : '500 mm/s² (Firmware)'} testId="motion-accel" />
      <Stat label="Tempo" value={stored?.speed ? `${de(stored.speed, 0)} mm/s` : '150 mm/s (Firmware)'} />
    </div>
    <h3 className="section-title" style={{ marginTop: 8 }}>Testfahrt mit dem Laser aus</h3>
    <div className="m-form-4">
      <Field label="Beschleunigung"><NumberInput ariaLabel="Beschleunigung" value={accel} onChange={setAccel} min={100} max={20000} step={100} digits={0} unit="mm/s²" /></Field>
      <Field label="Tempo"><NumberInput ariaLabel="Tempo" value={speed} onChange={setSpeed} min={10} max={500} step={10} digits={0} unit="mm/s" /></Field>
      <Field label="Weg"><NumberInput ariaLabel="Weg" value={span} onChange={setSpan} min={5} max={120} step={5} digits={0} unit="mm" /></Field>
      <Field label="Wiederholungen"><NumberInput ariaLabel="Wiederholungen" value={cycles} onChange={setCycles} min={1} max={30} step={1} digits={0} /></Field>
    </div>
    <LockLine text={lock} />
    <div className="row">
      <LockedButton variant="primary" lock={lock} busy={busy} data-testid="motion-test" onClick={() => void test()}>Testfahrt starten</LockedButton>
      <LockedButton lock={lock} data-testid="motion-save" onClick={() => void store()}>Diese Werte speichern</LockedButton>
      {stored?.accel && <LockedButton variant="ghost" lock={lock} data-testid="motion-reset" onClick={() => void machineAction('motion_limits').catch(() => {})}>Firmware-Werte</LockedButton>}
    </div>
    <p className="faint m-small">Die Testfahrt um die aktuelle Kopfposition zeigt keinen Schrittverlust von selbst: Danach an einer Marke prüfen. Die automatische Messung mit Prüfmarken und Kamera läuft bisher in der Tablet-App.</p>
  </>;
}

function BedDetail() {
  const { status: s, online } = useMachine();
  const summary = s.bed_map as BedMap | null | undefined;
  const [full, setFull] = useState<BedMap | null>(null);
  const [busy, setBusy] = useState(false);
  const stamp = String(summary?.measured_at ?? '');
  useEffect(() => { if (online) pi.get<{ bed_map: BedMap | null }>('/api/bedmap').then((r) => setFull(r.bed_map)).catch(() => setFull(null)); }, [online, stamp]);
  const lock = probeLock(s, online);
  const measure = async () => { setBusy(true); try { await machineAction('bedmap'); } catch { /* toast */ } finally { setBusy(false); } };
  return <>
    <p className="muted">Höhenprofil des leeren Betts, damit Stärke und Höhenkorrektur stimmen.</p>
    {summary
      ? <div className="m-stats m-stats-2">
          <Stat label="Punkte" value={`${summary.cols} × ${summary.rows}`} testId="bed-points" />
          <Stat label="Spanne" value={`${de(summary.range, 2)} mm`} />
          <Stat label="Tiefster, höchster Punkt" value={`${de(summary.lowest, 2)} bis ${de(summary.highest, 2)} mm`} />
          <Stat label="Gemessen" mono={false} value={when(summary.measured_at)} />
        </div>
      : <Note tone="warn">Noch nicht gemessen.</Note>}
    {full?.z && <BedGrid map={full} />}
    <LockLine text={lock} />
    <div className="row">
      <LockedButton variant="primary" lock={lock} busy={busy} data-testid="bed-measure" onClick={() => void measure()}>{summary ? 'Neu messen' : 'Messen'}</LockedButton>
      {summary && <Button variant="ghost" data-testid="bed-clear" onClick={() => void (async () => {
        if (await confirmDialog({ title: 'Bettkarte löschen?', body: 'Danach fehlt die Höhenkorrektur des Betts, bis sie neu gemessen ist.', okLabel: 'Löschen', danger: true })) await machineAction('bedmap_clear').catch(() => {});
      })()}>Löschen</Button>}
    </div>
    <p className="faint m-small">Das Bett muss dafür leer sein, der Pi prüft das nicht.</p>
  </>;
}

/** Machine rows, shown as seen from the door: X reversed. */
function BedGrid({ map }: { map: BedMap }) {
  const z = map.z ?? [];
  const lo = Math.min(...z), hi = Math.max(...z), span = Math.max(hi - lo, 0.01);
  return <div className="m-bedgrid" style={{ gridTemplateColumns: `repeat(${map.cols}, 1fr)` }} data-testid="bed-grid">
    {Array.from({ length: map.rows }, (_, r) => Array.from({ length: map.cols }, (_, c) => {
      const v = z[r * map.cols + (map.cols - 1 - c)];
      return <div key={`${r}-${c}`} className="m-bedcell mono" style={{ background: `color-mix(in srgb, var(--accent) ${Math.round(((v - lo) / span) * 45 + 4)}%, var(--surface-2))` }}>{de(v, 2)}</div>;
    }))}
  </div>;
}

function MatcalDetail({ camOk }: { camOk: boolean }) {
  const { status: s, online } = useMachine();
  const material = useWorkspace((w) => w.material);
  const [kind, setKind] = useState<'engrave' | 'cut'>('engrave');
  const [raised, setRaised] = useState(false);
  const [busy, setBusy] = useState(false);
  const last = s.material_calibration as Matcal | null | undefined;
  const seen = useRef(last?.state);
  useEffect(() => { if (seen.current === 'running' && last?.state === 'complete') void loadMaterials(); seen.current = last?.state; }, [last?.state]);
  const lock = moveLock(s, online)
    ?? (s.camera?.available ? null : 'Keine Kamera am Pi. Kopfkamera anschließen.')
    ?? (camOk ? null : 'Kamera nicht kalibriert. Erst die Kopfkamera einmessen.')
    ?? (s.probe_xy_offset_mm == null ? 'Taster-Versatz fehlt. Der Test tastet zuerst ab.' : null)
    ?? (material ? null : 'Kein Material gewählt. Erst im Bereich Material ein Material verwenden.')
    ?? (s.position ? null : 'Kopfposition unbekannt.')
    ?? (kind === 'cut' && !raised ? 'Zum Schneiden die Platte hochlegen und unten bestätigen.' : null);
  const start = async () => {
    if (!s.position || !material) return;
    const [x, y] = s.position;
    const what = kind === 'engrave' ? 'Gravur Feld für Feld, bis 18 kleine Felder, etwa 5 bis 15 Minuten' : 'Schnitt Durchgang für Durchgang, 4 Quadrate zu 8 mm, etwa 10 Minuten';
    setBusy(true);
    try {
      await machineAction('matcal', { kind, x, y, name: material.name, thickness: material.thickness_mm, raised: kind === 'cut' ? 1 : undefined }, {
        go: { detail: `${what} auf „${material.name}“ ab Kopfposition. Der Pi tastet zuerst ab und lasert dann. Testfläche frei und am Rand? Abluft an, danebenbleiben.`, okLabel: 'Lasern' },
      });
    } catch { /* toast */ } finally { setBusy(false); }
  };
  const results = (['dunkel', 'mittel', 'hell'] as const).flatMap((k) => { const r = last?.result?.[k] as { power?: number; speed?: number } | undefined; return r ? [[k, r] as const] : []; });
  return <>
    <p className="muted">Der Pi lasert, fotografiert und misst selbst, bis die Werte sitzen, und speichert sie als Material. Kopf vorher über eine freie, glatte Stelle fahren: Der Test beginnt am Laserpunkt.</p>
    <div className="row" style={{ flexWrap: 'wrap' }}>
      <Segmented<'engrave' | 'cut'> ariaLabel="Art" value={kind} onChange={setKind} options={[{ value: 'engrave', label: 'Gravur' }, { value: 'cut', label: 'Schnitt' }]} />
      {kind === 'cut' && <Check checked={raised} onChange={setRaised}>Platte liegt auf Abstandhaltern, etwa 10 mm Luft</Check>}
    </div>
    <div className="m-stats m-stats-2">
      <Stat label="Material" mono={false} value={material ? `${material.name}, ${de(material.thickness_mm)} mm` : 'keins gewählt'} tone={material ? undefined : 'warn'} />
      <Stat label="Testbereich" mono={false} value={kind === 'engrave' ? '51 × 21 mm ab Kopf' : '56 × 8 mm ab Kopf'} />
    </div>
    <LockLine text={lock} />
    <div className="row"><LockedButton variant="primary" lock={lock} busy={busy} data-testid="matcal-start" onClick={() => void start()}>Materialtest starten</LockedButton></div>
    {last && <div className="col m-gap m-kal-result" data-testid="matcal-last">
      <h3 className="section-title">Letzter Test: {last.kind === 'engrave' ? 'Gravur' : 'Schnitt'}, {last.material}</h3>
      {last.state === 'running' && <p className="muted">Läuft, Schritt {last.steps ?? 0}.</p>}
      {results.map(([k, r]) => <p key={k} className="tnum"><b>{k[0].toUpperCase() + k.slice(1)}:</b> {de(r.power, 0)} %, {de(r.speed, 0)} mm/min</p>)}
      {last.result?.best && <p className="tnum"><b>Bester Schnitt:</b> {de(last.result.best.speed, 0)} mm/min, {last.result.best.passes} Durchgänge</p>}
      {last.state === 'complete' && !!last.saved?.length && <Note tone="ok">Als Material gespeichert: {last.saved.map((x) => `${x.name} (${x.process})`).join(', ')}</Note>}
      {(last.state === 'error' || last.state === 'aborted') && <Note tone="bad">{last.error || 'Abgebrochen'}</Note>}
    </div>}
  </>;
}
