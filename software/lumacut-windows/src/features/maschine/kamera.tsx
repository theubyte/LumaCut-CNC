import { useEffect, useRef, useState } from 'react';
import { Camera as CameraIcon, Pause, Play, RefreshCw } from 'lucide-react';
import { pi } from '@/pi/client';
import { jobActive, useMachine } from '@/pi/machine';
import { fetchScanBlob, useWorkspace } from '@/pi/workspace';
import { Button, Check, Field, Note, Slider, toast } from '@/ui/kit';
import { de } from './locks';
import { Stat, when } from './parts';

export interface CameraSettings {
  exposure: number | null; gain: number | null; white_balance: number | null; light: number | null;
  ranges?: { exposure?: [number, number]; gain?: [number, number]; white_balance?: [number, number] };
}
export interface CameraCalibration {
  status?: string; placeholder?: boolean; calibrated?: boolean; revision?: number; updated_at?: string; updated_by?: string;
  image_width?: number; image_height?: number; px_per_mm?: number | null; scan_z?: number | null;
  android?: { photoWidth?: number; photoHeight?: number; scanZ?: number; aboveSurface?: number; lens?: { rmsMm?: number } | null; shading?: unknown } | null;
}
/** A calibration from the app counts; the Pi's placeholder does not. */
export const cameraCalibrated = (c: CameraCalibration | null) => !!c && !c.placeholder && (c.status === 'kalibriert' || !!c.android);

const GAP_MS = 250;
/**
 * Snapshot polling. The Pi needs 1 to 2 s per picture, so there is no fixed rate: the next request goes
 * out shortly after the last answer. Stops with the tab, with a hidden window, and during jobs,
 * because the job may need the camera itself and the Pi should not spend time on ffmpeg while lasering.
 */
function useLivePreview(run: boolean) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ms, setMs] = useState<number | null>(null);
  const [visible, setVisible] = useState(!document.hidden);
  useEffect(() => { const h = () => setVisible(!document.hidden); document.addEventListener('visibilitychange', h); return () => document.removeEventListener('visibilitychange', h); }, []);
  const active = run && visible;
  useEffect(() => {
    if (!active) return;
    let stop = false; let timer: ReturnType<typeof setTimeout>;
    const next = async () => {
      const t0 = performance.now();
      let wait = GAP_MS;
      try {
        const r = await pi.getBytes('/api/camera/snapshot?w=1280&h=720', 20000);
        if (stop) return;
        const u = URL.createObjectURL(new Blob([r.body as BlobPart], { type: 'image/jpeg' }));
        setUrl((old) => { if (old) URL.revokeObjectURL(old); return u; });
        setMs(performance.now() - t0); setError(null);
      } catch (e) {
        if (stop) return;
        setError((e as Error).message); wait = 3000;
      }
      timer = setTimeout(() => void next(), wait);
    };
    void next();
    return () => { stop = true; clearTimeout(timer); };
  }, [active]);
  useEffect(() => () => { setUrl((old) => { if (old) URL.revokeObjectURL(old); return null; }); }, []);
  return { url, error, ms };
}

export function Kamera() {
  const { status: s, online } = useMachine();
  const [paused, setPaused] = useState(false);
  const available = s.camera?.available === true;
  const job = jobActive(s);
  const live = useLivePreview(online && available && !paused && !job);
  return <div className="m-kamera">
    <section className="card m-preview-card">
      <div className="m-preview" data-testid="cam-preview">
        {live.url && <img src={live.url} alt="Live-Bild der Kopfkamera" data-testid="cam-image" />}
        {!available
          ? <div className="empty m-preview-empty"><CameraIcon size={28} /><p>{online ? 'Keine Kamera am Pi. Kopfkamera anschließen, dann erscheint hier das Bild.' : 'Pi nicht erreichbar. Adresse unter Optionen prüfen.'}</p></div>
          : !live.url && !live.error && <div className="empty m-preview-empty"><CameraIcon size={28} /><p>{job ? 'Während eines Auftrags ruht die Vorschau, damit die Kamera frei bleibt.' : paused ? 'Vorschau angehalten.' : 'Erstes Bild wird geholt.'}</p></div>}
        {live.error && available && <div className="m-preview-err"><Note tone="bad">{live.error} Nächster Versuch in 3 Sekunden.</Note></div>}
      </div>
      <div className="m-preview-foot">
        <Button icon={paused ? <Play size={15} /> : <Pause size={15} />} disabled={!available} onClick={() => setPaused(!paused)} data-testid="cam-pause">{paused ? 'Weiter' : 'Anhalten'}</Button>
        <span className="muted grow">{job ? 'Ruht während des Auftrags.' : paused ? 'Angehalten.' : live.ms != null ? `Live, ${de(live.ms / 1000)} s je Bild` : ''}</span>
        {available && <span className="faint m-small">Das Licht geht für die Vorschau von selbst an und danach wieder aus.</span>}
      </div>
    </section>
    <div className="m-kamera-side">
      <CameraSettingsCard available={available} />
      <CalibrationState />
      <ScanCard />
    </div>
  </div>;
}

function FixedSlider({ label, value, range, unit, fallback, onChange, testId }: { label: string; value: number | null; range: [number, number]; unit?: string; fallback: number; onChange(v: number | null): void; testId: string }) {
  const [local, setLocal] = useState(value ?? fallback);
  useEffect(() => { if (value != null) setLocal(value); }, [value]);
  const fixed = value != null;
  return <Field label={<span className="m-field-head"><span>{label}</span><span data-testid={testId}><Check checked={!fixed} onChange={(auto) => onChange(auto ? null : Math.min(range[1], Math.max(range[0], local)))}>Automatisch</Check></span></span>}>
    {fixed
      ? <Slider value={local} min={range[0]} max={range[1]} unit={unit} onChange={setLocal} onCommit={() => onChange(local)} />
      : <div className="m-auto-hint faint">Die Kamera regelt selbst.</div>}
  </Field>;
}

function CameraSettingsCard({ available }: { available: boolean }) {
  const [v, setV] = useState<CameraSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const online = useMachine((m) => m.online);
  useEffect(() => { if (online) pi.get<CameraSettings>('/api/camera/settings').then((x) => { setV(x); setError(null); }).catch((e) => setError((e as Error).message)); }, [online]);
  const save = async (patch: Partial<CameraSettings>) => {
    if (!v) return;
    const next = { ...v, ...patch };
    setV(next);
    const { ranges: _r, ...body } = next; void _r;
    try { await pi.putJson('/api/camera/settings', { exposure: body.exposure, gain: body.gain, white_balance: body.white_balance, light: body.light }); }
    catch (e) { toast((e as Error).message, 'bad'); }
  };
  return <section className="card card-pad col m-gap" data-testid="cam-settings">
    <h2 className="h3">Bild</h2>
    {error && <Note tone="bad">{error}</Note>}
    {!v && !error && <p className="muted">Wird geladen.</p>}
    {v && <>
      <FixedSlider label="Belichtung" testId="cam-exp-auto" value={v.exposure} fallback={500} range={v.ranges?.exposure ?? [1, 10000]} onChange={(exposure) => void save({ exposure })} />
      <FixedSlider label="Weißabgleich" testId="cam-wb-auto" value={v.white_balance} fallback={4500} unit="K" range={v.ranges?.white_balance ?? [2000, 10000]} onChange={(white_balance) => void save({ white_balance })} />
      {!available && <p className="faint m-small">Die Werte gelten, sobald eine Kamera angeschlossen ist.</p>}
      <p className="faint m-small">Feste Werte machen Scans gleichmäßig. Sie gelten für alle Geräte.</p>
    </>}
  </section>;
}

function CalibrationState() {
  const [c, setC] = useState<CameraCalibration | null>(null);
  const [error, setError] = useState<string | null>(null);
  const online = useMachine((m) => m.online);
  useEffect(() => { if (online) pi.get<CameraCalibration>('/api/camera/calibration').then((x) => { setC(x); setError(null); }).catch((e) => setError((e as Error).message)); }, [online]);
  const ok = cameraCalibrated(c);
  const w = c?.android?.photoWidth ?? c?.image_width, h = c?.android?.photoHeight ?? c?.image_height;
  return <section className="card card-pad col m-gap" data-testid="cam-calibration">
    <div className="row"><h2 className="h3 grow">Kalibrierung</h2><span className={`chip chip-${ok ? 'ok' : 'warn'}`}>{ok ? 'kalibriert' : 'fehlt'}</span></div>
    {error && <Note tone="bad">{error}</Note>}
    {c && !ok && <p className="muted">Noch keine Messung. Scan und Materialtest brauchen sie. Die Kalibrierung mit dem Punktraster läuft bisher in der Tablet-App.</p>}
    {c && ok && <div className="m-stats m-stats-2">
      <Stat label="Bildgröße" value={w ? `${w} × ${h}` : '–'} />
      <Stat label="Genauigkeit" value={c.android?.lens?.rmsMm != null ? `${de(c.android.lens.rmsMm, 2)} mm` : '–'} />
      <Stat label="Stand" mono={false} value={when(c.updated_at)} />
      <Stat label="Von" mono={false} value={c.updated_by || '–'} />
    </div>}
  </section>;
}

function ScanCard() {
  const rev = useWorkspace((w) => w.scanRevision);
  const [url, setUrl] = useState<string | null>(null);
  const [state, setState] = useState<'loading' | 'none' | 'ok' | 'error'>('loading');
  const last = useRef<string | null>(null);
  useEffect(() => {
    let stop = false;
    setState('loading');
    fetchScanBlob().then((r) => {
      if (stop) return;
      if (last.current) { URL.revokeObjectURL(last.current); last.current = null; }
      if (!r) { setUrl(null); setState('none'); return; }
      last.current = URL.createObjectURL(r.blob); setUrl(last.current); setState('ok');
    }).catch(() => { if (!stop) setState('error'); });
    return () => { stop = true; };
  }, [rev]);
  useEffect(() => () => { if (last.current) URL.revokeObjectURL(last.current); }, []);
  return <section className="card card-pad col m-gap" data-testid="cam-scan">
    <div className="row"><h2 className="h3 grow">Arbeitsplatz-Scan</h2>{state === 'loading' && <RefreshCw size={14} className="faint" />}</div>
    {url && <img className="m-scan" src={url} alt="Letzter Scan der Arbeitsfläche" data-testid="cam-scan-image" />}
    {state === 'none' && <p className="muted">Auf dem Pi liegt noch kein Scan.</p>}
    {state === 'error' && <p className="muted">Der Scan ließ sich nicht laden.</p>}
    <p className="faint m-small">Neu scannen geht bisher nur in der Tablet-App. Das Ergebnis erscheint hier und im Editor. Der Scan am PC folgt in der nächsten Etappe.</p>
  </section>;
}
