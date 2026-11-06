import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Crosshair, Fan, Grid3x3, Home, Lightbulb, MapPin, Navigation, ParkingSquare, ScanLine } from 'lucide-react';
import { Bed, fromMachine } from '@/core/model';
import { machineAction, type ActionOpts } from '@/pi/actions';
import { useMachine } from '@/pi/machine';
import { useWorkspace } from '@/pi/workspace';
import { useUi } from '@/store/ui';
import { Button, confirmDialog, NumberInput, Segmented, Slider, toast } from '@/ui/kit';
import { de, freeLock, headline, headWork, homeLock, JOG_STEPS, jogCommand, type JogDir, type JogStep, moveLock, moveTarget, probeLock, zLock } from './locks';
import { ActionRow, LockedButton, LockLine, Stat, Switch, when } from './parts';

type Fields = Record<string, string | number | boolean | undefined>;
/** One action at a time from this view; errors are already a toast. */
function useRun() {
  const [busy, setBusy] = useState<string | null>(null);
  const run = useCallback(async (op: string, fields: Fields = {}, opts: ActionOpts = {}) => {
    setBusy(op);
    try { await machineAction(op, fields, opts); } catch { /* shown as toast */ } finally { setBusy(null); }
  }, []);
  return { busy, run };
}

const HOME_CONFIRM = {
  title: 'Steht der Kopf frei?',
  detail: 'Der Pi kennt die Kopfhöhe nicht (nach Not-Aus, Stromausfall oder Neustart der Steuerung). Beim Referenzieren fährt der Kopf quer über das Bett in die Ecke. Steht die Tasterspitze über allem, was auf dem Bett liegt?',
  okLabel: 'Ja, referenzieren',
};

export function Steuerung() {
  const { status: s, online } = useMachine();
  const url = useUi((u) => u.piUrl);
  const material = useWorkspace((w) => w.material);
  const { busy, run } = useRun();
  const home = () => s.home_needs_confirm ? run('home', { clear: 1 }, { go: HOME_CONFIRM }) : run('home');
  const h = headline(s, online, url);
  const homeL = homeLock(s, online), moveL = moveLock(s, online), probeL = probeLock(s, online);
  const head = headWork(s);
  return <div className="m-steuerung">
    <section className="card m-hero" data-tone={h.tone} data-testid="m-hero">
      <div className="m-hero-head">
        <span className="m-dot" />
        <div className="grow">
          <h1 className="h1" data-testid="m-headline">{h.title}</h1>
          {h.text && <p className="muted" style={{ marginTop: 2 }}>{h.text}</p>}
        </div>
      </div>
      {s.emergency_latched
        ? <Button variant="primary" size="lg" data-testid="m-estop-reset" onClick={() => void run('estop_reset')} disabled={busy === 'estop_reset'}>Not-Aus quittieren</Button>
        : online && s.connected !== false && !s.homed
          ? <LockedButton variant="primary" size="lg" icon={<Home size={16} />} lock={homeL} busy={busy === 'home'} disabled={!!busy} data-testid="m-home-next" onClick={() => void home()}>Referenzieren</LockedButton>
          : null}
      <div className="m-pos" data-testid="m-pos">
        <Stat label="X" value={de(head?.x)} testId="m-x" /><Stat label="Y" value={de(head?.y)} testId="m-y" /><Stat label="Z" value={de(s.position?.[2])} testId="m-z" />
      </div>
      <p className="faint m-small">Position von der Tür gesehen, Ursprung links hinten, in mm.</p>
      <div className="m-stats">
        <Stat label="Referenz" mono={false} value={s.homed ? 'Ja' : 'Nein'} tone={s.homed ? undefined : 'warn'} testId="m-homed" />
        <Stat label="Werkstück Z" value={s.workpiece_surface_z == null ? '–' : `${de(s.workpiece_surface_z, 2)} mm`} testId="m-surface" />
        <Stat label="Fokus Z" value={s.laser_focus_z == null ? '–' : `${de(s.laser_focus_z as number, 2)} mm`} />
        <Stat label="Material" mono={false} value={material ? `${material.name}, ${de(material.thickness_mm)} mm` : 'keins gewählt'} tone={material ? undefined : 'warn'} />
      </div>
    </section>

    <JogCard lock={moveL} zLocked={zLock(s, online)} />

    <section className="card m-actions">
      <h2 className="h3 m-card-title">Aktionen</h2>
      <LockLine text={moveL} />
      <ActionRow icon={<Home size={16} />} title="Referenzfahrt" sub="X und Y an die Endschalter, dann Z." testId="row-home">
        <LockedButton lock={homeL} busy={busy === 'home'} disabled={!!busy && busy !== 'home'} data-testid="m-home" onClick={() => void home()}>Referenzieren</LockedButton>
      </ActionRow>
      <ActionRow icon={<ScanLine size={16} />} title="Abtasten" sub={probeL && !moveL ? <span style={{ color: 'var(--warn)' }}>{probeL}</span> : 'Misst die Oberfläche unter dem Laserpunkt.'} testId="row-probe">
        <LockedButton lock={probeL} busy={busy === 'probe'} disabled={!!busy} data-testid="m-probe" onClick={() => void run('probe')}>Abtasten</LockedButton>
      </ActionRow>
      <ActionRow icon={<ParkingSquare size={16} />} title="Parken" sub="Kopf in die Park-Ecke." testId="row-park">
        <LockedButton lock={moveL} busy={busy === 'park'} disabled={!!busy} data-testid="m-park" onClick={() => void run('park')}>Parken</LockedButton>
      </ActionRow>
      <MoveTo lock={moveL} busy={busy} run={run} />
      <div className="m-sep" />
      <LightRow />
      <ExhaustRow />
      <div className="m-sep" />
      <OriginRow />
      <BedMapRow busy={busy} run={run} />
    </section>
  </div>;
}

function MoveTo({ lock, busy, run }: { lock: string | null; busy: string | null; run: (op: string, f?: Fields, o?: ActionOpts) => Promise<void> }) {
  const s = useMachine((m) => m.status);
  const head = headWork(s);
  const [x, setX] = useState(100); const [y, setY] = useState(100);
  const go = () => {
    const t = moveTarget({ x, y });
    if ('error' in t) { toast(t.error, 'bad'); return; }
    void run('moveto', { x: +t.machine.x.toFixed(2), y: +t.machine.y.toFixed(2) }, { go: { detail: `Der Kopf fährt nach X ${de(x)}, Y ${de(y)} (von der Tür gesehen). Der Laser bleibt aus.` }, quiet: true });
  };
  return <ActionRow icon={<Navigation size={16} />} title="Zu Position fahren" testId="row-moveto" sub={
    <div className="m-moveto">
      <NumberInput value={x} onChange={setX} min={0} max={Bed.width} step={1} digits={1} unit="X" ariaLabel="Ziel X" />
      <NumberInput value={y} onChange={setY} min={0} max={Bed.height} step={1} digits={1} unit="Y" ariaLabel="Ziel Y" />
      <Button size="sm" variant="ghost" title="Aktuelle Kopfposition eintragen" disabled={!head} onClick={() => { if (head) { setX(+head.x.toFixed(1)); setY(+head.y.toFixed(1)); } }} aria-label="Kopfposition übernehmen"><Crosshair size={14} /></Button>
    </div>}>
    <LockedButton lock={lock} busy={busy === 'moveto'} disabled={!!busy} data-testid="m-moveto" onClick={go}>Fahren</LockedButton>
  </ActionRow>;
}

function LightRow() {
  const { status: s, online } = useMachine();
  const lock = freeLock(s, online);
  const [level, setLevel] = useState(s.light_brightness ?? 60);
  const editing = useRef(0);
  useEffect(() => { if (Date.now() - editing.current > 1500 && s.light_brightness != null) setLevel(Math.round(s.light_brightness)); }, [s.light_brightness]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const change = (v: number) => {
    setLevel(v); editing.current = Date.now();
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { void machineAction('light', { on: '1', brightness: Math.round(v) }, { quiet: true }).catch(() => {}); }, 300);
  };
  return <ActionRow icon={<Lightbulb size={16} />} title="Licht" testId="row-light" sub={s.light_dimmable === false ? 'Diese Firmware kann nicht dimmen.' :
    <fieldset className="m-plain" disabled={!!lock} title={lock ?? undefined}><Slider value={level} onChange={change} min={1} max={100} unit="%" /></fieldset>}>
    <Switch label="Licht" on={!!s.lights} disabled={!!lock} title={lock ?? undefined}
      onChange={(on) => void machineAction('light', { on: on ? '1' : '0' }, { quiet: true }).catch(() => {})} />
  </ActionRow>;
}

function ExhaustRow() {
  const { status: s, online } = useMachine();
  const lock = freeLock(s, online);
  const auto = s.config?.exhaust_auto;
  return <ActionRow icon={<Fan size={16} />} title="Abluft" testId="row-exhaust" sub={auto ? `Läuft beim Auftrag von selbst, ${s.config?.exhaust_after_s ?? 0} s Nachlauf.` : 'Nur von Hand.'}>
    <Switch label="Abluft" on={!!s.exhaust} disabled={!!lock} title={lock ?? undefined}
      onChange={(on) => void machineAction('exhaust', { on: on ? '1' : '0' }, { quiet: true }).catch(() => {})} />
  </ActionRow>;
}

function OriginRow() {
  const { status: s, online } = useMachine();
  const lock = moveLock(s, online);
  const user = (s.origin as { user?: [number, number] | null } | undefined)?.user ?? null;
  const w = user ? fromMachine({ x: user[0], y: user[1] }) : null;
  return <ActionRow icon={<MapPin size={16} />} title="Ursprung" sub={w ? `Gesetzt auf X ${de(w.x)}, Y ${de(w.y)}.` : 'Keiner gesetzt. Aufträge laufen wie entworfen.'} testId="row-origin">
    <LockedButton lock={lock} data-testid="m-origin-set" title="Aktuelle Kopfposition als Ursprung speichern, fährt nicht" onClick={() => void machineAction('origin_set').catch(() => {})}>Hier setzen</LockedButton>
    {w && <Button variant="ghost" data-testid="m-origin-clear" onClick={() => void (async () => {
      if (await confirmDialog({ title: 'Ursprung löschen?', body: 'Aufträge, die sich auf diesen Ursprung beziehen, müssen danach neu platziert werden.', okLabel: 'Löschen', danger: true })) await machineAction('origin_clear').catch(() => {});
    })()}>Löschen</Button>}
  </ActionRow>;
}

interface BedSummary { measured_at?: unknown; cols?: number; rows?: number; lowest?: number; highest?: number; range?: number; missing?: number }
function BedMapRow({ busy, run }: { busy: string | null; run: (op: string, f?: Fields, o?: ActionOpts) => Promise<void> }) {
  const { status: s, online } = useMachine();
  const lock = probeLock(s, online);
  const b = s.bed_map as BedSummary | null | undefined;
  return <ActionRow icon={<Grid3x3 size={16} />} title="Bettkarte" testId="row-bedmap"
    sub={b ? `${b.cols} × ${b.rows} Punkte, Spanne ${de(b.range, 2)} mm, ${when(b.measured_at)}` : 'Noch nicht gemessen. Das Bett muss dafür leer sein.'}>
    <LockedButton lock={lock} busy={busy === 'bedmap'} disabled={!!busy} data-testid="m-bedmap" onClick={() => void run('bedmap')}>Messen</LockedButton>
    {b && <Button variant="ghost" data-testid="m-bedmap-clear" onClick={() => void (async () => {
      if (await confirmDialog({ title: 'Bettkarte löschen?', body: 'Danach fehlt die Höhenkorrektur des Betts, bis sie neu gemessen ist.', okLabel: 'Löschen', danger: true })) await machineAction('bedmap_clear').catch(() => {});
    })()}>Löschen</Button>}
  </ActionRow>;
}

/** Single steps only: no repeat on a held key, the next one only after the Pi answered. */
function JogCard({ lock, zLocked }: { lock: string | null; zLocked: string | null }) {
  const [step, setStep] = useState<JogStep>(() => { try { const v = +(localStorage.getItem('lc.jog.step') ?? 1); return (JOG_STEPS as readonly number[]).includes(v) ? v as JogStep : 1; } catch { return 1; } });
  const [active, setActive] = useState<string | null>(null);
  const pending = useRef(false);
  const lockRef = useRef(lock); lockRef.current = lock;
  const zRef = useRef(zLocked); zRef.current = zLocked;
  const stepRef = useRef(step); stepRef.current = step;
  const pick = (v: JogStep) => { setStep(v); try { localStorage.setItem('lc.jog.step', String(v)); } catch { /* convenience */ } };

  const send = useCallback(async (key: string, axis: string, distance: number) => {
    const refused = axis === 'Z' ? zRef.current : lockRef.current;
    if (refused) { toast(refused, 'warn'); return; }
    if (pending.current) return;
    pending.current = true; setActive(key);
    try { await machineAction('jog', { axis, distance }, { quiet: true }); }
    catch { /* shown as toast */ }
    finally { pending.current = false; setActive(null); }
  }, []);
  const xy = useCallback((dir: JogDir) => { const c = jogCommand(dir, stepRef.current); void send(dir, c.axis, c.distance); }, [send]);
  const z = useCallback((sign: 1 | -1) => void send(sign > 0 ? 'zup' : 'zdown', 'Z', sign * stepRef.current), [send]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.altKey || e.metaKey || e.repeat) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.closest('input, textarea, select, [contenteditable="true"]'))) return;
      if (document.querySelector('.scrim')) return;
      const act = ({ ArrowLeft: () => xy('left'), ArrowRight: () => xy('right'), ArrowUp: () => xy('up'), ArrowDown: () => xy('down'), PageUp: () => z(1), PageDown: () => z(-1) } as Record<string, () => void>)[e.key];
      if (act) { e.preventDefault(); act(); }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [xy, z]);

  const key = (id: string, label: string, kbd: string, icon: ReactNode, onClick: () => void, blocked = lock) =>
    <button type="button" className="m-jog-key" data-active={active === id} data-testid={`jog-${id}`} data-lock={blocked ?? undefined} aria-label={label} disabled={!!blocked} title={blocked ?? `${label} (${kbd})`} onClick={onClick} onKeyDown={(e) => { if (e.repeat) e.preventDefault(); }}>{icon}</button>;

  return <section className="card m-jog" data-testid="m-jog">
    <div className="m-jog-head">
      <h2 className="h3">Bewegen</h2>
      <div className="row" style={{ gap: 6 }}>
        <Segmented ariaLabel="Schrittweite" value={String(step)} onChange={(v) => pick(+v as JogStep)}
          options={JOG_STEPS.map((v) => ({ value: String(v), label: de(v, v < 1 ? 1 : 0) }))} />
        <span className="faint">mm</span>
      </div>
    </div>
    <div className="m-jog-pads">
      <div className="m-cross">
        <span />{key('up', 'Nach hinten', 'Pfeil hoch', <ArrowUp size={22} />, () => xy('up'))}<span />
        {key('left', 'Nach links', 'Pfeil links', <ArrowLeft size={22} />, () => xy('left'))}
        <div className="m-cross-mid">X Y</div>
        {key('right', 'Nach rechts', 'Pfeil rechts', <ArrowRight size={22} />, () => xy('right'))}
        <span />{key('down', 'Nach vorne', 'Pfeil runter', <ArrowDown size={22} />, () => xy('down'))}<span />
      </div>
      <div className="m-z">
        {key('zup', 'Kopf hoch', 'Bild auf', <ArrowUp size={22} />, () => z(1), zLocked)}
        <div className="m-cross-mid">Z</div>
        {key('zdown', 'Kopf runter', 'Bild ab', <ArrowDown size={22} />, () => z(-1), zLocked)}
      </div>
    </div>
    {lock || zLocked
      ? <LockLine text={lock ?? zLocked} />
      : <p className="faint m-small m-jog-hint"><span className="kbd">←</span> <span className="kbd">↑</span> <span className="kbd">↓</span> <span className="kbd">→</span> bewegen, <span className="kbd">Bild auf</span> <span className="kbd">Bild ab</span> für Z. Jeder Druck ein Schritt.</p>}
  </section>;
}
