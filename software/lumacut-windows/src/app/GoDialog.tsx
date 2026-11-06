import { useEffect } from 'react';
import { Glasses, Hand, PanelTop, Zap, Move } from 'lucide-react';
import { useGo } from '@/pi/actions';
import { Button, Dialog } from '@/ui/kit';

/**
 * The go before every laser or motion job. Enter must NOT confirm: the focus is on "Abbrechen",
 * starting takes a deliberate click or Alt+S. An answer to another question is never a go.
 */
export function GoDialog() {
  const req = useGo((s) => s.req);
  useEffect(() => {
    if (!req) return;
    const h = (e: KeyboardEvent) => { if (e.altKey && e.key.toLowerCase() === 's') { e.preventDefault(); done(true); } };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }); // eslint-disable-line
  if (!req) return null;
  function done(v: boolean) { useGo.setState({ req: null }); req!.resolve(v); }
  const laser = req.kind === 'laser';
  const items = laser
    ? [[Hand, 'Hände raus'], [PanelTop, 'Deckel zu'], [Glasses, 'Brille auf']] as const
    : [[Hand, 'Hände raus'], [Move, 'Fahrweg frei']] as const;
  return (
    <Dialog title={req.title} onClose={() => done(false)} width={460} footer={<>
      <Button autoFocus size="lg" onClick={() => done(false)}>Abbrechen</Button>
      <Button size="lg" variant={laser ? 'danger' : 'primary'} icon={laser ? <Zap size={16} /> : <Move size={16} />} onClick={() => done(true)} data-testid="go-confirm">
        {req.okLabel ?? (laser ? 'Starten' : 'Fahren')}
      </Button></>}>
      <div className="col" style={{ gap: 12 }}>
        {req.detail && <p className="muted">{req.detail}</p>}
        <div className="row" style={{ gap: 8 }}>
          {items.map(([I, text]) => (
            <div key={text} className="card grow col" style={{ alignItems: 'center', gap: 6, padding: '12px 4px', fontWeight: 600 }}><I size={20} />{text}</div>
          ))}
        </div>
      </div>
    </Dialog>
  );
}
