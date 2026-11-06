import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { CircuitBoard, Cog, Hammer, Layers3, Minus, OctagonX, Pencil, Play, Settings, Square, Wifi, WifiOff, X, Zap } from 'lucide-react';
import { estop, setBaseUrl } from '@/pi/client';
import { frameActive, jobActive, refreshNow, startPolling, useMachine } from '@/pi/machine';
import { machineAction } from '@/pi/actions';
import { windowControls, type WindowControls } from '@/platform';
import { type Dest, useUi, applyTheme } from '@/store/ui';
import { useDoc } from '@/store/doc';
import { Button, ConfirmHost, toast, Toasts } from '@/ui/kit';
import { GoDialog } from './GoDialog';

const views: Record<Dest, ReturnType<typeof lazy>> = {
  material: lazy(() => import('@/features/material')),
  motiv: lazy(() => import('@/features/motiv')),
  start: lazy(() => import('@/features/start')),
  platine: lazy(() => import('@/features/platine')),
  werkstatt: lazy(() => import('@/features/werkstatt')),
  maschine: lazy(() => import('@/features/maschine')),
  einstellungen: lazy(() => import('@/features/einstellungen')),
};
/** Same words and order as the Android app's navigation; Platine and Werkstatt are new here. */
const NAV: { key: Dest; label: string; icon: typeof Play; kbd: string }[] = [
  { key: 'material', label: 'Material', icon: Layers3, kbd: '1' },
  { key: 'motiv', label: 'Motiv', icon: Pencil, kbd: '2' },
  { key: 'start', label: 'Starten', icon: Play, kbd: '3' },
];
const NAV2: typeof NAV = [
  { key: 'platine', label: 'Platine', icon: CircuitBoard, kbd: '4' },
  { key: 'werkstatt', label: 'Werkstatt', icon: Hammer, kbd: '5' },
  { key: 'maschine', label: 'Maschine', icon: Cog, kbd: '6' },
];

export function App() {
  const { dest, go, theme, piUrl } = useUi();
  useEffect(() => { applyTheme(theme); const m = matchMedia('(prefers-color-scheme: dark)'); const h = () => applyTheme(useUi.getState().theme); m.addEventListener('change', h); return () => m.removeEventListener('change', h); }, [theme]);
  useEffect(() => { setBaseUrl(piUrl); startPolling(piUrl); }, [piUrl]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      // Pause key: NOT-AUS from anywhere, also while typing.
      if (e.key === 'Pause') { e.preventDefault(); void doEstop(); return; }
      if (e.ctrlKey && !e.altKey && !e.shiftKey && /^[1-6]$/.test(e.key)) {
        const hit = [...NAV, ...NAV2].find((n) => n.kbd === e.key); if (hit) { e.preventDefault(); go(hit.key); }
      }
    };
    window.addEventListener('keydown', h, true);
    return () => window.removeEventListener('keydown', h, true);
  }, [go]);
  const View = views[dest];
  return (
    <div className="app">
      <TopBar />
      <JobStrip />
      <nav className="rail" aria-label="Hauptnavigation">
        {NAV.map((n) => <RailBtn key={n.key} n={n} />)}
        <div className="rail-sep" />
        {NAV2.map((n) => <RailBtn key={n.key} n={n} />)}
        <div style={{ flex: 1 }} />
        <RailBtn n={{ key: 'einstellungen', label: 'Optionen', icon: Settings, kbd: '' }} />
      </nav>
      <main className="main"><Suspense fallback={null}><View /></Suspense></main>
      <StatusBar />
      <GoDialog /><ConfirmHost /><Toasts />
    </div>
  );
}

function RailBtn({ n }: { n: (typeof NAV)[number] }) {
  const dest = useUi((s) => s.dest); const go = useUi((s) => s.go); const I = n.icon;
  return <button type="button" aria-current={dest === n.key ? 'page' : undefined} data-testid={`nav-${n.key}`} title={n.kbd ? `${n.label} (Strg+${n.kbd})` : n.label} onClick={() => go(n.key)}><I size={20} strokeWidth={1.8} />{n.label}</button>;
}

async function doEstop() {
  try { await estop(); toast('NOT-AUS ausgelöst. Laser aus, Bewegung gestoppt.', 'bad'); }
  catch (e) { toast(`NOT-AUS nicht bestätigt: ${(e as Error).message}. Netzschalter betätigen!`, 'bad'); }
  refreshNow();
}

function TopBar() {
  const title = useDoc((s) => s.doc.title); const dirty = useDoc((s) => s.dirty);
  const { online, status } = useMachine();
  const [win, setWin] = useState<WindowControls | null>(null);
  useEffect(() => { void windowControls().then(setWin); }, []);
  const latched = !!status.emergency_latched;
  return (
    <header className="topbar" data-tauri-drag-region>
      <div className="brand" data-tauri-drag-region><div className="logo"><Zap size={14} /></div>LumaCut</div>
      <div className="faint" data-tauri-drag-region style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{title}{dirty ? ' •' : ''}</div>
      <div className="grow" data-tauri-drag-region style={{ alignSelf: 'stretch' }} />
      <ConnChip online={online} />
      {latched && <Button size="sm" onClick={() => void machineAction('estop_reset')}>Not-Aus quittieren</Button>}
      <button type="button" className={'estop' + (latched ? ' latched' : '')} data-testid="estop" title="NOT-AUS (Taste Pause)" onClick={() => void doEstop()}><OctagonX size={18} />NOT-AUS</button>
      {win ? <div className="winctl">
        <button type="button" aria-label="Minimieren" onClick={win.minimize}><Minus size={15} /></button>
        <button type="button" aria-label="Maximieren" onClick={win.toggleMaximize}><Square size={12} /></button>
        <button type="button" className="close" aria-label="Schließen" onClick={win.close}><X size={16} /></button>
      </div> : <div style={{ width: 8 }} />}
    </header>
  );
}

function ConnChip({ online }: { online: boolean }) {
  const s = useMachine((m) => m.status);
  const go = useUi((u) => u.go);
  const { tone, text } = useMemo(() => {
    if (!online) return { tone: 'bad', text: 'Pi nicht erreichbar' };
    if (s.emergency_latched) return { tone: 'bad', text: 'Not-Aus aktiv' };
    if (s.connected === false) return { tone: 'warn', text: 'Steuerung nicht verbunden' };
    if (s.laser_armed) return { tone: 'bad', text: 'Laser scharf' };
    if (jobActive(s)) return { tone: 'accent', text: 'Auftrag läuft' };
    if (frameActive(s)) return { tone: 'accent', text: 'Rahmen läuft' };
    if (s.homed === false) return { tone: 'warn', text: 'Nicht referenziert' };
    return { tone: 'ok', text: 'Bereit' };
  }, [online, s]);
  const I = online ? Wifi : WifiOff;
  return <button type="button" className={`chip chip-${tone}`} style={{ border: 0, cursor: 'pointer' }} title="Zur Maschine" onClick={() => go('maschine')} data-testid="conn-chip"><I size={13} />{text}</button>;
}

function JobStrip() {
  const s = useMachine((m) => m.status);
  const go = useUi((u) => u.go);
  const j = s.job;
  if (!j || !jobActive(s)) return null;
  const pct = j.total ? Math.min(100, (100 * (j.line ?? 0)) / j.total) : 0;
  const phase = ({ homing: 'Referenzfahrt', probing: `Abtasten ${j.probe?.done ?? 0}/${j.probe?.total ?? 0}`, focusing: 'Höhenkorrektur', running: 'Lasern', finishing: 'Abschluss', parking: 'Parken' } as Record<string, string>)[j.state] ?? j.state;
  return <div className="jobstrip" data-testid="jobstrip">
    <button type="button" className="btn btn-ghost btn-sm" onClick={() => go('start')}>{j.file}</button>
    <span className="chip chip-accent">{phase}</span>
    <div className="progress grow"><div style={{ width: `${pct}%` }} /></div>
    <span className="tnum muted">{pct.toFixed(0)} %</span>
    <Button size="sm" onClick={() => void machineAction('abort')}>Abbrechen</Button>
  </div>;
}

function StatusBar() {
  const { status: s, online } = useMachine();
  const url = useUi((u) => u.piUrl);
  const p = s.position;
  return <footer className="statusbar">
    <span className="mono">{p ? `X ${p[0].toFixed(1)}  Y ${p[1].toFixed(1)}  Z ${p[2].toFixed(1)}` : 'X –  Y –  Z –'}</span>
    <span>{s.state ?? '–'}</span>
    {s.laser_armed && <span style={{ color: 'var(--bad)', fontWeight: 600 }}>LASER SCHARF</span>}
    <span id="statusbar-slot" className="grow" />
    <span>{online ? url.replace(/^https?:\/\//, '') : 'getrennt'}</span>
  </footer>;
}
