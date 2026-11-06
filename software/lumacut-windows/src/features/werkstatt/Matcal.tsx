import { useState } from 'react';
import { Square, Zap } from 'lucide-react';
import { Bed, fromMachine, insideWork, touchesPark } from '@/core/model';
import { machineAction } from '@/pi/actions';
import { jobActive, machineFree, useMachine } from '@/pi/machine';
import { Button, Field, NumberInput, Note, Segmented, toast } from '@/ui/kit';
import { useUi } from '@/store/ui';
import type { MachineStatus } from '@/pi/types';

/**
 * The Pi's adaptive material test (op=matcal): engraving field by field with the camera, cutting pass by pass
 * until the camera sees the hole open. Results are stored as materials on the Pi. Reference: MatcalCard.kt.
 */
const ENGRAVE_W = 51, ENGRAVE_H = 21, CUT_W = 44, CUT_H = 8;
interface Summary { kind?: string; material?: string; state?: string; steps?: number; error?: string; saved?: { name: string; process: string }[]; last?: Record<string, unknown>; result?: Record<string, unknown> | null }
const de = (v: number, d = 0) => v.toFixed(d).replace('.', ',');

export function lastStepLine(s: Summary): string | null {
  const l = s.last as Record<string, number & boolean> | undefined;
  if (!l) return null;
  if (s.kind === 'engrave') return `Feld ${s.steps}: ${de(+l.power, 1)} % bei ${de(+l.speed)} mm/min, Ton ${de(+l.tone, 2)}${l.clean ? ', sauber' : ', streifig oder Rand'}`;
  return `${de(+l.speed)} mm/min, Durchgang ${+l.pass + 1}: ${l.fell ? 'durchgefallen' : 'noch zu'}`;
}
export function resultLines(s: Summary): string[] {
  const r = s.result; if (!r) return [];
  type F = { power: number; speed: number; tone: number; approximate?: boolean; passes: number; fell?: boolean };
  if (s.kind === 'engrave') return (['dunkel', 'mittel', 'hell'] as const).flatMap((k) => {
    const f = r[k] as F | undefined; if (!f) return [];
    return [`${k[0].toUpperCase()}${k.slice(1)}: ${de(f.power, 1)} % bei ${de(f.speed)} mm/min (Ton ${de(f.tone, 2)})${f.approximate ? ', nur ungefähr' : ''}`];
  });
  const squares = (r.squares as F[] | undefined) ?? [];
  const best = r.best as F | undefined;
  return [...squares.map((q) => `${de(q.speed)} mm/min: ${q.fell ? `${de(q.passes)} Durchgänge` : `nach ${de(q.passes)} nicht durch`}`), ...(best ? [`Gespeichert: ${de(best.speed)} mm/min, ${de(best.passes)} Durchgänge (wenigste Energie)`] : [])];
}

/** Test area in work coordinates for the preview. */
export function matcalArea(kind: 'engrave' | 'cut', mx: number, my: number) {
  const box = kind === 'cut' ? { x0: mx, y0: my, x1: mx + CUT_W, y1: my + CUT_H } : { x0: mx - 3, y0: my, x1: mx - 3 + ENGRAVE_W, y1: my + ENGRAVE_H };
  const a = fromMachine({ x: box.x0, y: box.y0 }), b = fromMachine({ x: box.x1, y: box.y1 });
  return { minX: Math.min(a.x, b.x), minY: a.y, maxX: Math.max(a.x, b.x), maxY: b.y };
}

export function MatcalSettings({ kind, setKind }: { kind: 'engrave' | 'cut'; setKind(k: 'engrave' | 'cut'): void }) {
  const status = useMachine((m) => m.status) as MachineStatus & { material_calibration?: Summary | null };
  const online = useMachine((m) => m.online);
  const go = useUi((u) => u.go);
  const [name, setName] = useState('');
  const [thickness, setThickness] = useState(4);
  const [raised, setRaised] = useState(false);
  const supported = (status.features ?? []).includes('material_calibration');
  const last = status.material_calibration ?? null;
  const active = last?.state === 'running' && jobActive(status);
  const head = status.position;
  const ready = online && machineFree(status) && !!status.homed;
  const blocked = !online ? 'Der Pi ist nicht erreichbar.' : !status.connected ? 'Die Steuerung ist nicht verbunden.' : !status.homed ? 'Die Maschine ist nicht referenziert. Erst unter Maschine eine Referenzfahrt machen.' : !machineFree(status) ? 'Die Maschine ist gerade belegt.' : null;

  const area = head ? matcalArea(kind, head[0], head[1]) : null;
  const badArea = !!area && (!insideWork(area) || touchesPark(area) || area.minX < 30 || area.minY < 30 || area.maxX > Bed.width - 30);

  const start = async () => {
    if (!name.trim()) { toast('Bitte einen Materialnamen eintragen.', 'bad'); return; }
    if (!head) { toast('Position unbekannt. Erst referenzieren.', 'bad'); return; }
    const what = kind === 'engrave' ? 'Gravur Feld für Feld (bis 18 kleine Felder, ca. 5 bis 15 min)' : 'Schnitt Durchgang für Durchgang (4 Quadrate zu 8 mm, ca. 10 min)';
    await machineAction('matcal', { kind, x: head[0].toFixed(2), y: head[1].toFixed(2), name: name.trim(), thickness: thickness.toFixed(2), raised: raised ? '1' : undefined }, {
      go: { title: 'Materialtest starten?', detail: `${what} auf „${name.trim()}“ ab X ${de(head[0])} / Y ${de(head[1])}. Der Pi tastet zuerst ab und lasert dann. Liegt das Material noch an derselben Stelle? Abluft an und danebenbleiben.`, okLabel: 'Lasern' },
      timeoutMs: 20000,
    }).catch(() => undefined);
  };

  return (
    <div className="col ws-form" data-testid="matcal">
      <p className="muted">Der Pi lasert ein Feld, fotografiert es, misst den Ton und rechnet daraus das nächste Feld. Die Ergebnisse speichert er als Materialien. Das Motiv bleibt dabei unberührt.</p>
      {!supported && online && <Note tone="warn">Dieser Pi kann das noch nicht. Pi-Software aktualisieren.</Note>}
      {blocked && <Note tone="info">{blocked}{!status.homed && online && <> <button type="button" className="btn btn-sm" onClick={() => go('maschine')}>Zur Maschine</button></>}</Note>}
      <Field label="Art"><Segmented ariaLabel="Art" value={kind} onChange={setKind} options={[{ value: 'engrave', label: 'Gravur' }, { value: 'cut', label: 'Schnitt' }]} /></Field>
      <Field label="Materialname" hint="Unter diesem Namen speichert der Pi das Ergebnis"><input className="input" value={name} aria-label="Materialname" placeholder="zum Beispiel Sperrholz 4 mm" onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Materialstärke"><NumberInput value={thickness} onChange={setThickness} unit="mm" min={0.1} max={50} step={0.5} digits={1} ariaLabel="Materialstärke" /></Field>
      <Field label="Platte"><Segmented ariaLabel="Platte" value={raised ? 'raised' : 'flat'} onChange={(v) => setRaised(v === 'raised')} options={[{ value: 'flat', label: 'Liegt flach' }, { value: 'raised', label: 'Hochgelegt' }]} /></Field>
      <Note tone="info">Kopf über eine freie, glatte Stelle fahren: der Testbereich beginnt am Laserpunkt und reicht {kind === 'cut' ? `${CUT_W} × ${CUT_H}` : `${ENGRAVE_W} × ${ENGRAVE_H}`} mm. {kind === 'cut' && 'Zum Schneiden die Platte auf Abstandhalter legen (etwa 10 mm Luft). '}Vorher unter Material das aktuelle Material wählen: seine Stärke bestimmt die Fahrhöhe.</Note>
      {badArea && <Note tone="warn">Der Testbereich liegt zu nah am Rand oder in der Park-Ecke. Der Pi braucht mindestens 30 mm Abstand: Kopf erst unter Maschine zu einer freien Stelle fahren.</Note>}
      {kind === 'cut' && !raised && <Note tone="warn">Schnitt nur mit hochgelegter Platte: flach verkohlt die Rückseite, und die Kamera sieht das Loch nicht.</Note>}
      <Button variant="danger" size="lg" icon={<Zap size={16} />} disabled={!ready || !head || !supported || active || (kind === 'cut' && !raised)} onClick={() => void start()} data-testid="matcal-start">
        {kind === 'engrave' ? 'Gravur kalibrieren' : 'Schnitt kalibrieren'}
      </Button>
      {last && <div className="col" data-testid="matcal-last">
        <div className="section-title">{last.kind === 'engrave' ? 'Gravur' : 'Schnitt'}: {last.material}</div>
        {active && <><div className="progress"><div style={{ width: `${Math.min(100, (last.steps ?? 0) / (last.kind === 'engrave' ? 18 : 20) * 100)}%` }} /></div><Button icon={<Square size={14} />} onClick={() => void machineAction('abort')}>Abbrechen</Button></>}
        {lastStepLine(last) && <p className="muted">{lastStepLine(last)}</p>}
        {resultLines(last).map((l) => <p key={l}>{l}</p>)}
        {last.state === 'complete' && <Note tone="ok">Als Material gespeichert: {(last.saved ?? []).map((q) => `${q.name} (${q.process})`).join(', ')}</Note>}
        {(last.state === 'error' || last.state === 'aborted') && <Note tone="bad">{last.error || 'Abgebrochen'}</Note>}
      </div>}
    </div>
  );
}
