import { useState } from 'react';
import { exportDxf, exportPng, exportSvg, exportWarnings } from '@/core/export';
import { plateElements } from '@/core/model';
import { saveFile } from '@/platform';
import { useDoc } from '@/store/doc';
import { Button, Check, Dialog, Field, Note, NumberInput, Segmented, Slider, toast } from '@/ui/kit';
import { useEditor } from './editor';
import * as ops from './ops';

export function MotivDialogs() {
  const dialog = useEditor((s) => s.dialog), set = useEditor((s) => s.set);
  const close = () => set({ dialog: null });
  if (dialog === 'contour') return <ContourDialog onClose={close} />;
  if (dialog === 'vectorize') return <VectorizeDialog onClose={close} />;
  if (dialog === 'rename') return <RenameDialog onClose={close} />;
  if (dialog === 'export') return <ExportDialog onClose={close} />;
  return null;
}

function ContourDialog({ onClose }: { onClose(): void }) {
  const [offset, setOffset] = useState(2), [outer, setOuter] = useState(true), [remove, setRemove] = useState(false);
  return <Dialog title="Kontur erzeugen" onClose={onClose} width={420} footer={<>
    <Button onClick={onClose}>Abbrechen</Button>
    <Button variant="primary" data-testid="contour-ok" onClick={() => { if (ops.makeContour(offset, remove, outer)) onClose(); }}>Kontur erzeugen</Button></>}>
    <div className="col" style={{ gap: 'var(--sp-3)' }}>
      <p className="muted">Zieht eine Linie im festen Abstand um die Auswahl. Sie kommt auf die Ebene Schneiden.</p>
      <Field label="Abstand"><div style={{ width: 120 }}><NumberInput value={offset} unit="mm" step={0.5} min={-50} max={100} ariaLabel="Abstand" onChange={setOffset} /></div></Field>
      <Check checked={outer} onChange={setOuter}>Nur der äußere Rand, Löcher ignorieren</Check>
      <Check checked={remove} onChange={setRemove}>Ausgangsform entfernen</Check>
    </div>
  </Dialog>;
}

function VectorizeDialog({ onClose }: { onClose(): void }) {
  const [threshold, setThreshold] = useState(128), [invert, setInvert] = useState(false), [smooth, setSmooth] = useState(true), [outerOnly, setOuterOnly] = useState(false), [remove, setRemove] = useState(false);
  return <Dialog title="Bild vektorisieren" onClose={onClose} width={440} footer={<>
    <Button onClick={onClose}>Abbrechen</Button>
    <Button variant="primary" data-testid="vectorize-ok" onClick={() => { if (ops.vectorizeSel({ threshold, invert, smooth, outerOnly }, remove)) onClose(); }}>Vektorisieren</Button></>}>
    <div className="col" style={{ gap: 'var(--sp-3)' }}>
      <p className="muted">Macht aus dunklen Bildteilen Pfade, die sich schneiden oder markieren lassen.</p>
      <Field label="Schwellwert"><Slider value={threshold} min={1} max={254} onChange={setThreshold} /></Field>
      <Check checked={invert} onChange={setInvert}>Helle statt dunkle Teile</Check>
      <Check checked={smooth} onChange={setSmooth}>Kanten glätten</Check>
      <Check checked={outerOnly} onChange={setOuterOnly}>Nur äußere Umrisse</Check>
      <Check checked={remove} onChange={setRemove}>Bild danach entfernen</Check>
    </div>
  </Dialog>;
}

function RenameDialog({ onClose }: { onClose(): void }) {
  const title = useDoc((s) => s.doc.title), [v, setV] = useState(title);
  const ok = () => { const t = v.trim(); if (t && t !== title) useDoc.getState().commit((d) => ({ ...d, title: t })); onClose(); };
  return <Dialog title="Projekt umbenennen" onClose={onClose} width={420} footer={<><Button onClick={onClose}>Abbrechen</Button><Button variant="primary" onClick={ok}>Umbenennen</Button></>}>
    <input className="input" autoFocus value={v} aria-label="Projektname" onChange={(e) => setV(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') ok(); }} />
  </Dialog>;
}

const FORMATS = [
  { value: 'svg', label: 'SVG', title: 'Vektoren für andere Programme' }, { value: 'dxf', label: 'DXF', title: 'Für CAD' }, { value: 'png', label: 'PNG', title: 'Bild der Platte' },
] as const;
type Format = (typeof FORMATS)[number]['value'];
/** Exports the active plate of the document. The camera background is not in the document, so it cannot leak into a file. */
function ExportDialog({ onClose }: { onClose(): void }) {
  const doc = useDoc((s) => s.doc), [format, setFormat] = useState<Format>('svg'), [busy, setBusy] = useState(false);
  const empty = !plateElements(doc).length, warnings = empty ? [] : exportWarnings(doc, doc.activePlate, format);
  const run = async () => {
    setBusy(true);
    try {
      const name = `${doc.title.replace(/[\\/:*?"<>|]+/g, '-')}${doc.plateCount > 1 ? `-Platte-${doc.activePlate + 1}` : ''}.${format}`;
      const data = format === 'svg' ? exportSvg(doc) : format === 'dxf' ? exportDxf(doc) : await exportPng(doc);
      const saved = await saveFile(name, data, [{ name: format.toUpperCase(), extensions: [format] }]);
      if (saved) { toast(`Gespeichert: ${saved}`, 'ok'); onClose(); }
    } catch (e) { toast(`Export ging nicht: ${(e as Error).message}`, 'bad'); } finally { setBusy(false); }
  };
  return <Dialog title="Exportieren" onClose={onClose} width={440} footer={<>
    <Button onClick={onClose}>Abbrechen</Button>
    <Button variant="primary" disabled={empty || busy} onClick={() => void run()} data-testid="export-ok">Exportieren</Button></>}>
    <div className="col" style={{ gap: 'var(--sp-3)' }}>
      <Field label="Format"><div><Segmented<Format> ariaLabel="Format" options={[...FORMATS]} value={format} onChange={setFormat} /></div></Field>
      <p className="muted">{empty ? 'Auf dieser Platte liegt noch nichts.' : `Platte ${doc.activePlate + 1} mit ${plateElements(doc).length} Objekten.`}</p>
      {warnings.map((w) => <Note key={w} tone="warn">{w}</Note>)}
    </div>
  </Dialog>;
}
