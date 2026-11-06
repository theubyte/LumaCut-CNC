import { useEffect, useState } from 'react';
import { Download, Monitor, Moon, RefreshCw, Sun, Zap } from 'lucide-react';
import { useMachine } from '@/pi/machine';
import type { MachineStatus } from '@/pi/types';
import { appVersion, checkForUpdate, installUpdate, isTauri, piTransport, type UpdateInfo } from '@/platform';
import { type ThemePref, useUi } from '@/store/ui';
import { Button, confirmDialog, Field, Note, Segmented, toast } from '@/ui/kit';
import { DEFAULT_PI, parseAddress } from './address';
import './einstellungen.css';

export default function Optionen() {
  return <div className="page"><div className="o-page">
    <h1 className="h1">Optionen</h1>
    <Connection />
    <Appearance />
    <Update />
    <Shortcuts />
    <About />
  </div></div>;
}

type Check = { state: 'idle' | 'checking' } | { state: 'ok'; text: string } | { state: 'bad'; text: string };

function Connection() {
  const piUrl = useUi((u) => u.piUrl); const setPiUrl = useUi((u) => u.setPiUrl);
  const online = useMachine((m) => m.online); const name = useMachine((m) => m.status.config?.machine_name);
  const [text, setText] = useState(piUrl);
  const [check, setCheck] = useState<Check>({ state: 'idle' });
  useEffect(() => setText(piUrl), [piUrl]);
  const parsed = parseAddress(text);
  const url = 'url' in parsed ? parsed.url : null;
  const test = async () => {
    if (!url) return;
    setCheck({ state: 'checking' });
    try {
      const r = await piTransport(url, { method: 'GET', path: '/api/status', timeoutMs: 4000 });
      if (r.status !== 200) { setCheck({ state: 'bad', text: `Der Pi antwortet mit Fehler ${r.status}. Ist das die richtige Adresse?` }); return; }
      const s = JSON.parse(new TextDecoder().decode(r.body)) as MachineStatus;
      setCheck({ state: 'ok', text: `Erreichbar: ${s.config?.machine_name ?? 'LumaCut'}${s.connected ? ', Steuerung verbunden.' : ', Steuerung nicht verbunden.'}` });
    } catch (e) {
      setCheck({ state: 'bad', text: `Keine Antwort von ${url}. Netzwerk und Adresse prüfen. (${(e as Error).message})` });
    }
  };
  const save = () => { if (url) { setPiUrl(url); setText(url); toast('Adresse gespeichert.', 'ok'); } };
  return <section className="card card-pad col o-gap" data-testid="o-connection">
    <div className="row"><h2 className="h3 grow">Verbindung zum Pi</h2>
      <span className={`chip chip-${online ? 'ok' : 'bad'}`} data-testid="o-online">{online ? `Verbunden${name ? `: ${name}` : ''}` : 'Nicht erreichbar'}</span></div>
    <Field label="Adresse" hint={'error' in parsed ? parsed.error : url !== text.trim() ? `Wird zu ${url}` : undefined}>
      <div className="row">
        <input className="input o-addr" spellCheck={false} value={text} aria-label="Pi-Adresse" data-testid="o-address"
          onChange={(e) => { setText(e.target.value); setCheck({ state: 'idle' }); }} onKeyDown={(e) => { if (e.key === 'Enter') void test(); }} />
        <Button disabled={!url || check.state === 'checking'} onClick={() => void test()} data-testid="o-test">{check.state === 'checking' ? 'Prüft' : 'Prüfen'}</Button>
        <Button variant="primary" disabled={!url || url === piUrl} onClick={save} data-testid="o-save">Speichern</Button>
      </div>
    </Field>
    {check.state === 'ok' && <Note tone="ok"><span data-testid="o-check">{check.text}</span></Note>}
    {check.state === 'bad' && <Note tone="bad"><span data-testid="o-check">{check.text}</span></Note>}
    {piUrl !== DEFAULT_PI && <div><Button size="sm" variant="ghost" onClick={() => setText(DEFAULT_PI)}>Vorgabe eintragen ({DEFAULT_PI.replace('http://', '')})</Button></div>}
    {!isTauri() && <p className="faint o-small">Im Browser geht jede Anfrage an den Simulator, unabhängig von dieser Adresse.</p>}
  </section>;
}

function Appearance() {
  const theme = useUi((u) => u.theme); const setTheme = useUi((u) => u.setTheme);
  return <section className="card card-pad o-line" data-testid="o-theme">
    <div className="grow"><h2 className="h3">Darstellung</h2><p className="muted">System folgt der Einstellung von Windows.</p></div>
    <Segmented<ThemePref> ariaLabel="Darstellung" value={theme} onChange={setTheme} options={[
      { value: 'light', label: <><Sun size={14} />Hell</> }, { value: 'dark', label: <><Moon size={14} />Dunkel</> }, { value: 'system', label: <><Monitor size={14} />System</> }]} />
  </section>;
}

function Update() {
  const [version, setVersion] = useState('');
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { void appVersion().then(setVersion); }, []);
  const check = async () => {
    setBusy(true);
    try { setInfo(await checkForUpdate()); }
    catch (e) { setInfo({ available: false, current: version, error: (e as Error).message }); }
    finally { setBusy(false); }
  };
  const install = async () => {
    if (!(await confirmDialog({ title: 'Update installieren?', body: `Version ${info?.version} wird geladen und geprüft, dann startet das Setup und die App schließt sich. Ungespeicherte Änderungen vorher sichern.`, okLabel: 'Installieren' }))) return;
    setBusy(true);
    try { await installUpdate(); } catch (e) { toast((e as Error).message, 'bad'); setBusy(false); }
  };
  return <section className="card card-pad col o-gap" data-testid="o-update">
    <div className="o-line">
      <div className="grow"><h2 className="h3">App-Version</h2><p className="muted tnum" data-testid="o-version">{version === 'dev' ? 'Entwicklungsstand' : version || '–'}</p></div>
      <Button icon={<RefreshCw size={14} />} disabled={busy} onClick={() => void check()} data-testid="o-check-update">Nach Update suchen</Button>
    </div>
    {info?.error && <Note tone="bad">Prüfung fehlgeschlagen: {info.error}</Note>}
    {info && !info.error && !info.available && <Note tone="ok"><span data-testid="o-update-result">{isTauri() ? 'Die App ist aktuell.' : 'Updates gibt es nur in der installierten App.'}</span></Note>}
    {info?.available && <div className="col o-gap">
      <div className="o-line"><div className="grow"><b>Version {info.version} ist verfügbar</b>{info.sizeBytes ? <span className="muted"> · {(info.sizeBytes / 1e6).toLocaleString('de-DE', { maximumFractionDigits: 1 })} MB</span> : null}{info.notes && <p className="muted o-notes">{info.notes}</p>}</div>
        <Button variant="primary" icon={<Download size={15} />} disabled={busy} onClick={() => void install()}>Installieren</Button></div>
      <Note tone="info">Das Setup ist nicht signiert. Windows zeigt deshalb eine SmartScreen-Warnung: „Weitere Informationen“, dann „Trotzdem ausführen“.</Note>
    </div>}
  </section>;
}

const KEYS: { area: string; rows: [string[], string][] }[] = [
  { area: 'Überall', rows: [[['Pause'], 'NOT-AUS'], [['Strg', '1…6'], 'Material, Motiv, Starten, Platine, Werkstatt, Maschine'], [['Alt', 'S'], 'Im Freigabe-Dialog: Starten (Enter löst nie aus)'], [['Esc'], 'Dialog schließen']] },
  { area: 'Maschine, Reiter Steuerung', rows: [[['←', '↑', '↓', '→'], 'Kopf einen Schritt bewegen, von der Tür gesehen'], [['Bild auf', 'Bild ab'], 'Kopf einen Schritt hoch oder runter']] },
  { area: 'Zahlenfelder', rows: [[['Enter'], 'Wert übernehmen'], [['↑', '↓'], 'Wert ändern, mit Umschalt zehnfach']] },
];
function Shortcuts() {
  return <section className="card card-pad col o-gap" data-testid="o-keys">
    <h2 className="h3">Tastenkürzel</h2>
    <div className="o-keys">
      {KEYS.map((g) => <div key={g.area} className="col" style={{ gap: 5 }}>
        <div className="section-title">{g.area}</div>
        {g.rows.map(([keys, what]) => <div key={what} className="o-key"><span className="o-key-keys">{keys.map((k) => <span key={k} className="kbd">{k}</span>)}</span><span className="muted">{what}</span></div>)}
      </div>)}
    </div>
    <p className="faint o-small">Die Kürzel des Motiv-Editors stehen dort in den Tooltips.</p>
  </section>;
}

function About() {
  return <section className="card card-pad o-about" data-testid="o-about">
    <div className="logo o-logo"><Zap size={18} /></div>
    <div className="grow col" style={{ gap: 3 }}>
      <h2 className="h3">LumaCut Studio</h2>
      <p className="muted">Software für den selbstgebauten Diodenlaser LumaCut. Einstellungen, Grenzen, Kalibrierungen, Materialien und Projekte liegen auf dem Pi, Tablet und PC greifen auf denselben Stand zu.</p>
      <p className="muted">Der NOT-AUS in der App ersetzt nicht den Schalter an der Maschine.</p>
    </div>
  </section>;
}
