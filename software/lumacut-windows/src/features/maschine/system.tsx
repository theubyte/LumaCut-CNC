import { useEffect, useState } from 'react';
import { Download } from 'lucide-react';
import { pi } from '@/pi/client';
import { useMachine } from '@/pi/machine';
import { saveFile } from '@/platform';
import { Button, Note, toast } from '@/ui/kit';
import { de } from './locks';
import { Stat, when } from './parts';

interface PiSystem { software_commit: string | null; software_date: string | null; service_uptime_s: number; disk_free_bytes: number | null; disk_total_bytes: number | null; jobs_bytes: number; cpu_temp_c: number | null }
interface FirmwareRelease { number?: number; commit?: string; board_name?: string | null; running_build?: string | null; release_build?: string | null; update_available?: boolean; checked_at?: unknown; error?: string }
interface FirmwareUpdate { state?: string; progress?: number; message?: string }
interface PanelInfo { connected?: boolean; port?: string; version?: string; available?: string; update_available?: boolean; state?: string; message?: string }

const gb = (b: number | null | undefined) => b == null ? '–' : `${de(b / 1e9)} GB`;
function uptime(s: number | undefined) {
  if (s == null) return '–';
  const d = Math.floor(s / 86400), h = Math.floor(s / 3600) % 24, m = Math.floor(s / 60) % 60;
  return d ? `${d} T ${h} Std` : h ? `${h} Std ${m} Min` : `${m} Min`;
}
const firmwareName = (identity?: string) => (identity ?? '').replace(/^FIRMWARE_NAME:/, '').split(' SOURCE_CODE_URL')[0].split(' MACHINE_TYPE')[0];

export function SystemTab() {
  const { status: s, online } = useMachine();
  const [sys, setSys] = useState<PiSystem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!online) return;
    const load = () => pi.get<PiSystem>('/api/system').then((x) => { setSys(x); setError(null); }).catch((e) => setError((e as Error).message));
    void load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [online]);
  const fw = s.firmware_release as FirmwareRelease | undefined;
  const upd = s.firmware_update as FirmwareUpdate | undefined;
  const panel = s.panel as PanelInfo | null | undefined;
  // The heartbeat's position reports say nothing; the status shows the position anyway.
  const lines = (s.recent ?? []).filter((l) => !l.startsWith('ok') && !/^X:-?[\d.]+ Y:/.test(l)).slice(-14);
  const backup = async () => {
    setSaving(true);
    try {
      const r = await pi.getBytes('/api/backup', 30000);
      const name = `lumacut-sicherung-${new Date().toISOString().slice(0, 10)}.json`;
      const saved = await saveFile(name, r.body, [{ name: 'JSON', extensions: ['json'] }]);
      if (saved) toast(`Sicherung gespeichert: ${saved}`, 'ok');
    } catch (e) { toast((e as Error).message, 'bad'); } finally { setSaving(false); }
  };
  return <div className="m-system">
    {!online && <Note tone="bad">Pi nicht erreichbar. Die Werte unten sind der letzte bekannte Stand. Adresse unter Optionen prüfen.</Note>}
    <section className="card card-pad col m-gap" data-testid="sys-firmware">
      <div className="row"><h2 className="h3 grow">Firmware</h2>
        <span className={`chip chip-${s.connected ? 'ok' : 'bad'}`}>{s.connected ? 'verbunden' : 'nicht verbunden'}</span></div>
      <p className="mono m-wrap" data-selectable>{firmwareName(s.identity) || '–'}</p>
      <div className="m-stats m-stats-2">
        <Stat label="Update" mono={false} value={fw?.update_available ? `Verfügbar: ${fw.release_build ?? fw.number ?? ''}` : fw?.error ? 'Prüfung fehlgeschlagen' : fw?.checked_at ? 'Aktuell' : 'Noch nicht geprüft'} tone={fw?.update_available ? 'warn' : undefined} />
        <Stat label="Zuletzt geprüft" mono={false} value={when(fw?.checked_at)} />
        <Stat label="Update-Status" mono={false} value={upd?.state && upd.state !== 'idle' ? `${upd.state}${upd.progress != null ? `, ${upd.progress} %` : ''}` : 'Kein Update läuft'} />
        <Stat label="Serielle Fehler" value={s.serial_errors ?? '–'} tone={s.serial_errors ? 'warn' : undefined} />
      </div>
      {fw?.error && <p className="faint m-small">{fw.error}</p>}
      {upd?.message && <p className="muted">{upd.message}</p>}
      <p className="faint m-small">Geflasht wird nur vor Ort an der Maschine, nicht aus dieser App.</p>
    </section>

    <section className="card card-pad col m-gap" data-testid="sys-pi">
      <h2 className="h3">Pi</h2>
      {error && <Note tone="bad">{error}</Note>}
      <div className="m-stats m-stats-2">
        <Stat label="Softwarestand" value={sys?.software_commit ? sys.software_commit.slice(0, 8) : '–'} />
        <Stat label="Stand vom" mono={false} value={when(sys?.software_date)} />
        <Stat label="Freier Speicher" value={`${gb(sys?.disk_free_bytes)} von ${gb(sys?.disk_total_bytes)}`} />
        <Stat label="Temperatur" value={sys?.cpu_temp_c == null ? '–' : `${de(sys.cpu_temp_c)} °C`} tone={(sys?.cpu_temp_c ?? 0) > 75 ? 'warn' : undefined} />
        <Stat label="Dienst läuft seit" mono={false} value={uptime(sys?.service_uptime_s)} />
        <Stat label="Gespeicherte Aufträge" value={sys ? `${de(sys.jobs_bytes / 1e6)} MB` : '–'} />
      </div>
      <div className="m-sep" />
      <div className="row"><Button icon={<Download size={15} />} disabled={!online || saving} onClick={() => void backup()} data-testid="sys-backup">Sicherung herunterladen</Button></div>
      <p className="faint m-small">Einstellungen, Materialien, Arbeitsstand, Kalibrierungen. Ohne Aufträge, Projekte und Scan.</p>
    </section>

    <section className="card card-pad col m-gap" data-testid="sys-mechanik">
      <div className="row"><h2 className="h3 grow">Mechanik-Freigabe</h2>
        <span className={`chip chip-${s.config?.validated ? 'ok' : 'warn'}`}>{s.config?.validated ? 'freigegeben' : 'nicht freigegeben'}</span></div>
      <p className="muted">{s.config?.validated ? 'Referenzfahrt, Fahren und Aufträge sind erlaubt.' : 'Ohne Freigabe lehnt der Pi Referenzfahrt, Fahren und Aufträge ab. Sie wird vor Ort an der Maschine erteilt.'}</p>
      <div className="m-stats m-stats-2">
        <Stat label="Fahrweg X × Y × Z" value={s.config?.travels ? `${s.config.travels.x} × ${s.config.travels.y} × ${s.config.travels.z} mm` : '–'} />
        <Stat label="Gerätename" mono={false} value={s.config?.machine_name ?? '–'} />
      </div>
    </section>

    <section className="card card-pad col m-gap" data-testid="sys-panel">
      <div className="row"><h2 className="h3 grow">Bedienpanel</h2>
        <span className={`chip chip-${panel?.connected ? 'ok' : ''}`}>{panel?.connected ? 'verbunden' : 'nicht verbunden'}</span></div>
      {panel?.connected
        ? <div className="m-stats m-stats-2"><Stat label="Version" value={panel.version ?? '–'} /><Stat label="Auf dem Pi" value={panel.available ?? '–'} /></div>
        : <p className="muted">Kein Panel am USB des Pi.</p>}
      {panel?.message && <p className="muted">{panel.message}</p>}
    </section>

    <section className="card card-pad col m-gap m-system-wide" data-testid="sys-recent">
      <h2 className="h3">Letzte Meldungen der Steuerung</h2>
      {lines.length ? <pre className="m-log mono" data-selectable>{lines.join('\n')}</pre> : <p className="muted">Noch keine Meldungen.</p>}
      {s.fault && <Note tone="warn">{s.fault}</Note>}
    </section>
  </div>;
}
