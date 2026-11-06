import { useEffect, useRef, useState } from 'react';
import { Link2, Link2Off, RotateCw } from 'lucide-react';
import { boxH, boxW, docBounds, type Element, type ImageMode, insideWork, isImage, plateElements, touchesPark } from '@/core/model';
import { BUNDLED_FAMILY, listFamilies } from '@/core/text';
import { useDoc } from '@/store/doc';
import { Button, Check, Field, Note, NumberInput, Slider } from '@/ui/kit';
import { useEditor } from './editor';
import * as ops from './ops';
import { fmt } from './render';

/** Below the layers: what is selected and everything that can be set about it. */
export function PropsPanel() {
  useDoc((s) => s.doc); useDoc((s) => s.selection);
  const sel = ops.selectedEls();
  return <section className="mv-sec mv-sec-props" data-testid="props-panel">
    <header className="mv-sec-head"><h2>Eigenschaften</h2>{sel.length > 1 && <span className="mv-muted-note">{sel.length} Objekte</span>}{sel.length === 1 && <span className="mv-muted-note">{sel[0].kind}</span>}</header>
    {sel.length === 0 ? <Nothing /> : <div className="mv-props">
      <Geometry sel={sel} />
      {sel.length === 1 && sel[0].text != null && <TextProps key={sel[0].id} e={sel[0]} />}
      {sel.length === 1 && isImage(sel[0]) && <ImageProps e={sel[0]} />}
      <Warnings sel={sel} />
    </div>}
  </section>;
}

function Nothing() {
  const doc = useDoc((s) => s.doc), els = plateElements(doc), b = docBounds(els);
  return <div className="mv-props">
    <p className="mv-muted-note">Nichts ausgewählt. Klick wählt ein Objekt, Rahmen aufziehen wählt mehrere, Rechtsklick öffnet das Menü.</p>
    {b && <dl className="mv-stats">
      <dt>Objekte auf der Platte</dt><dd className="tnum">{els.length}</dd>
      <dt>Ausmaß</dt><dd className="tnum">{fmt(boxW(b))} × {fmt(boxH(b))} mm</dd>
    </dl>}
  </div>;
}

function Geometry({ sel }: { sel: Element[] }) {
  const lock = useEditor((s) => s.lockAspect), setPref = useEditor((s) => s.setPref);
  const b = ops.selectionBox(sel); if (!b) return null;
  const one = sel.length === 1 ? sel[0] : null, size = one ? ops.localSize(one) : { w: boxW(b), h: boxH(b) };
  return <div className="mv-geo">
    <Field label="X"><NumberInput value={b.minX} unit="mm" step={1} ariaLabel="Position X" onChange={(v) => ops.setPosition(v, null)} /></Field>
    <span />
    <Field label="Y"><NumberInput value={b.minY} unit="mm" step={1} ariaLabel="Position Y" onChange={(v) => ops.setPosition(null, v)} /></Field>
    <Field label="Breite"><NumberInput value={size?.w ?? 0} unit="mm" step={1} min={0.01} ariaLabel="Breite" onChange={(v) => ops.setSize(v, null, lock)} /></Field>
    <Button variant="ghost" size="sm" iconOnly pressed={lock} icon={lock ? <Link2 size={14} /> : <Link2Off size={14} />} title={lock ? 'Seitenverhältnis gesperrt. Klick: frei' : 'Seitenverhältnis frei. Klick: sperren'} aria-label="Seitenverhältnis sperren" onClick={() => setPref('lockAspect', !lock)} data-testid="lock-aspect" />
    <Field label="Höhe"><NumberInput value={size?.h ?? 0} unit="mm" step={1} min={0.01} ariaLabel="Höhe" onChange={(v) => ops.setSize(null, v, lock)} /></Field>
    <Field label="Drehung"><NumberInput value={one ? one.transform.rotation : 0} unit="°" step={1} digits={1} ariaLabel="Drehung" onChange={(v) => ops.setRotation(v)} /></Field>
    <span />
    <div className="mv-geo-quick">
      <Button size="sm" title="Um 90° drehen" icon={<RotateCw size={13} />} onClick={() => ops.setRotation((one ? one.transform.rotation : 0) + 90)}>90°</Button>
      <Button size="sm" title="In die Mitte der Arbeitsfläche" onClick={ops.centerInWork}>Mitte</Button>
    </div>
  </div>;
}

const GENERIC = [{ value: 'sans-serif', label: 'Standard' }, { value: 'serif', label: 'Standard mit Serifen' }, { value: 'monospace', label: 'Standard feste Breite' }];

function TextProps({ e }: { e: Element }) {
  const [families, setFamilies] = useState<string[]>([BUNDLED_FAMILY]);
  const [text, setText] = useState(e.text ?? '');
  const area = useRef<HTMLTextAreaElement>(null), editing = useRef(false), focusId = useEditor((s) => s.focusTextId);
  useEffect(() => { void listFamilies().then(setFamilies); }, []);
  useEffect(() => { if (document.activeElement !== area.current) setText(e.text ?? ''); }, [e.text]);
  // Fresh text and double click arrive here ready to type over.
  // Nach dem Mausklick fokussieren: mousedown nimmt der Seite sonst den Fokus wieder.
  useEffect(() => { if (focusId === e.id) { useEditor.getState().set({ focusTextId: null }); setTimeout(() => { area.current?.focus(); area.current?.select(); }, 0); } }, [focusId, e.id]);
  const shown = [...GENERIC.map((g) => g.value), ...families];
  return <div className="mv-group-v">
    <Field label="Text"><textarea ref={area} className="input mv-textarea" rows={2} value={text} data-testid="text-input" spellCheck={false}
      onChange={(x) => { setText(x.target.value); if (!x.target.value.trim()) return; if (!editing.current) { editing.current = true; useDoc.getState().checkpoint(); } void ops.updateText(e.id, { text: x.target.value }, false); }}
      onBlur={() => { editing.current = false; if (!text.trim()) setText(e.text ?? ''); }} /></Field>
    <div className="mv-grid-font">
      <Field label="Schrift"><select className="input" value={e.fontFamily} aria-label="Schrift" data-testid="font-select" onChange={(x) => void ops.updateText(e.id, { fontFamily: x.target.value }, true)}>
        {GENERIC.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
        {!shown.includes(e.fontFamily) && <option value={e.fontFamily}>{e.fontFamily}</option>}
        {families.map((f) => <option key={f} value={f}>{f}</option>)}
      </select></Field>
      <Field label="Größe"><NumberInput value={e.fontSizeMm} unit="mm" step={1} min={0.5} max={300} ariaLabel="Schriftgröße" onChange={(v) => void ops.updateText(e.id, { fontSizeMm: v }, true)} /></Field>
    </div>
    <Check checked={e.bold} onChange={(v) => void ops.updateText(e.id, { bold: v }, true)}>Fett</Check>
  </div>;
}

const MODES: { value: ImageMode; label: string }[] = [
  { value: 'GRAYSCALE', label: 'Graustufen' }, { value: 'DITHER', label: 'Dithering Floyd-Steinberg' }, { value: 'DITHER_JARVIS', label: 'Dithering Jarvis' }, { value: 'DITHER_STUCKI', label: 'Dithering Stucki' }, { value: 'THRESHOLD', label: 'Schwellwert (nur Schwarz und Weiß)' },
];
function ImageProps({ e }: { e: Element }) {
  const set = useEditor((s) => s.set);
  const a = e.adjust as { brightness?: number; contrast?: number; sharpen?: number; invert?: boolean };
  const open = useRef(false);
  const adjust = (patch: Record<string, unknown>) => {
    if (!open.current) { open.current = true; useDoc.getState().checkpoint(); }
    useDoc.getState().mutate((d) => ({ ...d, elements: d.elements.map((x) => (x.id === e.id ? { ...x, adjust: { ...x.adjust, ...patch } } : x)) }));
  };
  const close = () => { open.current = false; };
  const commit = (patch: Partial<Element>) => useDoc.getState().commit((d) => ({ ...d, elements: d.elements.map((x) => (x.id === e.id ? { ...x, ...patch } : x)) }));
  const r = e.raster!, w = e.imageWidthMm * Math.abs(e.transform.scaleX);
  return <div className="mv-group-v">
    <Field label="Bildmodus"><select className="input" value={e.imageMode} aria-label="Bildmodus" data-testid="image-mode" onChange={(x) => commit({ imageMode: x.target.value as ImageMode })}>
      {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
    </select></Field>
    <Field label="Helligkeit"><Slider value={a.brightness ?? 0} min={-100} max={100} onChange={(v) => adjust({ brightness: v })} onCommit={close} /></Field>
    <Field label="Kontrast"><Slider value={a.contrast ?? 0} min={-100} max={100} onChange={(v) => adjust({ contrast: v })} onCommit={close} /></Field>
    <Field label="Schärfe"><Slider value={a.sharpen ?? 0} min={0} max={100} onChange={(v) => adjust({ sharpen: v })} onCommit={close} /></Field>
    <Check checked={!!a.invert} onChange={(v) => commit({ adjust: { ...e.adjust, invert: v } })}>Umkehren (Negativ)</Check>
    <p className="mv-muted-note">{r.width} × {r.height} Pixel, {Math.round(r.width / Math.max(w, 0.01) * 25.4)} dpi. Die Vorschau zeigt, wie das Bild gelasert würde.</p>
    <Button icon={undefined} onClick={() => set({ dialog: 'vectorize' })} data-testid="vectorize">Vektorisieren …</Button>
  </div>;
}

function Warnings({ sel }: { sel: Element[] }) {
  const b = ops.selectionBox(sel); if (!b) return null;
  const out = !insideWork(b), park = !out && touchesPark(b);
  if (!out && !park) return null;
  return <div className="mv-group-v" data-testid="props-warning">
    <Note tone={out ? 'bad' : 'warn'}>{out ? 'Ragt über die Arbeitsfläche. So startet der Auftrag nicht.' : 'Liegt in der Park-Ecke. Dort steht der Kopf in der Ruhelage.'}</Note>
    <Button size="sm" onClick={ops.keepInside}>{out ? 'In die Arbeitsfläche schieben' : 'Aus der Park-Ecke schieben'}</Button>
  </div>;
}
