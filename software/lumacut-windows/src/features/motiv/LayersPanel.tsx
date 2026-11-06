import { useRef, useState } from 'react';
import { ChevronDown, ChevronRight, Eye, EyeOff, GripVertical, Plus, Trash2, Zap, ZapOff } from 'lucide-react';
import { type Layer, layerCss, layerLabel, Limits, STANDARD_LAYERS } from '@/core/model';
import { useMachine } from '@/pi/machine';
import { useDoc } from '@/store/doc';
import { Button, confirmDialog, Field, Note, NumberInput, Segmented } from '@/ui/kit';
import * as ops from './ops';

const PROCESS: { value: ops.Process; label: string; title: string }[] = [
  { value: 'Gravieren', label: 'Gravieren', title: 'Flächen zeilenweise füllen' },
  { value: 'Linie', label: 'Markieren', title: 'Der Linie folgen, nicht durchtrennen' },
  { value: 'Schneiden', label: 'Schneiden', title: 'Der Linie folgen, durchtrennen' },
];

/** Layers that carry something, top to bottom in the order they are lasered. */
export function LayersPanel() {
  const doc = useDoc((s) => s.doc), active = useDoc((s) => s.activeLayerId), selection = useDoc((s) => s.selection);
  const setActive = useDoc((s) => s.setActiveLayer), layerByName = useDoc((s) => s.layerByName);
  const rows = ops.shownLayers(doc, active);
  const usage = new Map<string, number>();
  for (const e of doc.elements) usage.set(e.layerId, (usage.get(e.layerId) ?? 0) + 1);
  const ids = new Set(selection), selLayers = new Set(doc.elements.filter((e) => ids.has(e.id)).map((e) => e.layerId));
  const focus = selLayers.size === 1 ? [...selLayers][0] : selLayers.size ? null : active;
  const focusName = doc.layers.find((l) => l.id === focus)?.name;
  const pick = (name: ops.Process) => { const l = layerByName(name); setActive(l.id); ops.moveSelectionToLayer(l.id); };

  const list = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ id: string; before: string | null } | null>(null);
  const startDrag = (e: React.PointerEvent, id: string) => {
    e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId);
    setDrag({ id, before: null });
  };
  const moveDrag = (e: React.PointerEvent) => {
    if (!drag || !list.current) return;
    let before: string | null = null;
    for (const el of list.current.querySelectorAll<HTMLElement>('[data-layer]')) {
      const r = el.getBoundingClientRect();
      if (e.clientY < r.top + r.height / 2) { before = el.dataset.layer!; break; }
    }
    if (before !== drag.before) setDrag({ ...drag, before });
  };
  const endDrag = () => {
    if (drag) {
      const order = rows.map((r) => r.id), from = order.indexOf(drag.id), to = drag.before ? order.indexOf(drag.before) : order.length;
      if (to !== from && to !== from + 1) ops.moveLayer(drag.id, drag.before);
    }
    setDrag(null);
  };

  const cut = rows.findIndex((l) => l.name === 'Schneiden' && l.output && l.visible);
  const cutNotLast = cut >= 0 && rows.slice(cut + 1).some((l) => l.output && l.visible && (usage.get(l.id) ?? 0) > 0);

  return <section className="mv-sec" data-testid="layers-panel">
    <header className="mv-sec-head">
      <h2>Ebenen</h2>
      <Button variant="ghost" size="sm" iconOnly icon={<Plus size={15} />} title="Eigene Ebene hinzufügen" aria-label="Eigene Ebene hinzufügen" onClick={ops.addLayer} data-testid="layer-add" />
    </header>
    <div className="mv-process">
      <span className="mv-process-label">{selection.length ? `Auswahl (${selection.length}) soll:` : 'Neue Formen sollen:'}</span>
      <Segmented ariaLabel="Was der Laser tut" options={PROCESS} value={(focusName && STANDARD_LAYERS.has(focusName) ? focusName : '') as ops.Process} onChange={pick} />
    </div>
    <div className="mv-layers" ref={list} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={() => setDrag(null)}>
      {rows.length === 0 && <p className="mv-muted-note">Ebenen erscheinen von selbst, sobald etwas darauf liegt.</p>}
      {rows.map((l) => <div key={l.id} data-layer={l.id}>
        {drag && drag.before === l.id && drag.id !== l.id && <div className="mv-drop-line" />}
        <LayerRow layer={l} count={usage.get(l.id) ?? 0} focused={l.id === focus} dragging={drag?.id === l.id} onGrip={(e) => startDrag(e, l.id)}
          incoming={doc.elements.filter((e) => ids.has(e.id) && e.layerId !== l.id).length} />
      </div>)}
      {drag && drag.before === null && <div className="mv-drop-line" />}
    </div>
    {cutNotLast && <div className="mv-layer-warn"><Note tone="warn">Schneiden läuft nicht zuletzt: ausgeschnittene Teile können verrutschen, bevor der Rest gelasert ist.</Note></div>}
  </section>;
}

function LayerRow({ layer: l, count, focused, dragging, onGrip, incoming }: { layer: Layer; count: number; focused: boolean; dragging: boolean; onGrip(e: React.PointerEvent): void; incoming: number }) {
  const [open, setOpen] = useState(false);
  const maxFeed = useMachine((m) => m.status.config?.motion?.speed) ?? Limits.SPEED[1];
  const setActive = useDoc((s) => s.setActiveLayer), standard = STANDARD_LAYERS.has(l.name);
  const off = !l.visible || !l.output;
  const remove = async () => {
    if (count === 0 || await confirmDialog({ title: `Ebene ${layerLabel(l)} löschen?`, body: `${count === 1 ? '1 Teil wird' : `${count} Teile werden`} mitgelöscht, auch auf anderen Platten. Rückgängig holt alles zurück.`, okLabel: 'Löschen', danger: true })) ops.deleteLayer(l.id);
  };
  const lowPower = l.powerPct > 0 && l.powerPct < Limits.MIN_RELIABLE_POWER_PCT;
  return <div className={'mv-layer-row' + (focused ? ' focused' : '') + (dragging ? ' dragging' : '') + (off ? ' off' : '')} data-testid={`layer-${l.name}`} onClick={(e) => { if ((e.target as HTMLElement).closest('input,button,select,label') == null) setActive(l.id); }}>
    <div className="mv-layer-top">
      <span className="mv-grip" title="Ziehen ändert die Reihenfolge beim Lasern" onPointerDown={onGrip} data-testid={`layer-grip-${l.name}`}><GripVertical size={14} /></span>
      <label className="mv-swatch" style={{ background: layerCss(l) }} title="Farbe ändern">
        <input type="color" value={layerCss(l)} aria-label="Farbe der Ebene" onChange={(e) => ops.updateLayer(l.id, { color: 0xFF000000 + parseInt(e.target.value.slice(1), 16) })} />
      </label>
      {standard
        ? <span className="mv-layer-name" title={`${count} ${count === 1 ? 'Teil' : 'Teile'}`}>{layerLabel(l)}</span>
        : <input className="mv-layer-name-input" value={l.name} aria-label="Name der Ebene" onChange={(e) => ops.updateLayer(l.id, { name: e.target.value })} />}
      <span className="mv-layer-count tnum" title="Teile auf dieser Ebene, alle Platten">{count}</span>
      <Button variant="ghost" size="sm" iconOnly icon={l.visible ? <Eye size={14} /> : <EyeOff size={14} />} title={l.visible ? 'Ausblenden, wird dann auch nicht gelasert' : 'Einblenden'} aria-label={l.visible ? 'Ausblenden' : 'Einblenden'} onClick={() => ops.updateLayer(l.id, { visible: !l.visible })} />
      <Button variant="ghost" size="sm" iconOnly icon={l.output ? <Zap size={14} /> : <ZapOff size={14} />} className={l.output ? 'mv-on' : ''} title={l.output ? 'Wird gelasert. Klick: nicht lasern' : 'Wird nicht gelasert. Klick: lasern'} aria-label={l.output ? 'Nicht lasern' : 'Lasern'} onClick={() => ops.updateLayer(l.id, { output: !l.output })} />
      <Button variant="ghost" size="sm" iconOnly icon={open ? <ChevronDown size={14} /> : <ChevronRight size={14} />} title="Weitere Werte" aria-label="Weitere Werte" aria-expanded={open} onClick={() => setOpen(!open)} data-testid={`layer-more-${l.name}`} />
    </div>
    <div className="mv-layer-vals">
      <NumberInput value={l.powerPct} unit="%" step={1} min={Limits.POWER[0]} max={Limits.POWER[1]} digits={1} ariaLabel={`Leistung ${layerLabel(l)}`} title="Leistung" onChange={(v) => ops.updateLayer(l.id, { powerPct: v })} />
      <NumberInput value={l.speed} unit="mm/min" step={100} min={1} max={maxFeed} digits={0} ariaLabel={`Tempo ${layerLabel(l)}`} title={`Tempo, höchstens ${maxFeed} mm/min`} onChange={(v) => ops.updateLayer(l.id, { speed: v })} />
    </div>
    {lowPower && <div className="mv-layer-warnline">Unter {Limits.MIN_RELIABLE_POWER_PCT} % zündet der Laser nicht sicher.</div>}
    {incoming > 0 && !focused && !standard && <button type="button" className="mv-layer-incoming" onClick={() => { setActive(l.id); ops.moveSelectionToLayer(l.id); }}>Auswahl hierher ({incoming})</button>}
    {open && <div className="mv-layer-more">
      <Field label="Art"><Segmented ariaLabel="Art der Ebene" options={PROCESS} value={ops.processOf(l)} onChange={(p) => ops.setProcess(l, p)} /></Field>
      <div className="mv-grid2">
        <Field label="Durchgänge"><NumberInput value={l.passes} unit="×" min={Limits.PASSES[0]} max={Limits.PASSES[1]} digits={0} onChange={(v) => ops.updateLayer(l.id, (x) => ({ passes: Math.round(v), zStepMm: ops.safeZStep(Math.round(v), x.zStepMm) }))} /></Field>
        <Field label="Fokus tiefer je Durchgang"><NumberInput value={l.zStepMm} unit="mm" step={0.1} min={0} max={Limits.Z_STEP[1]} disabled={l.passes <= 1} onChange={(v) => ops.updateLayer(l.id, (x) => ({ zStepMm: ops.safeZStep(x.passes, v) }))} /></Field>
        {l.mode === 'FILL' && <>
          <Field label="Zeilenabstand"><NumberInput value={l.intervalMm} unit="mm" step={0.01} min={0.03} max={2} digits={3} onChange={(v) => ops.updateLayer(l.id, { intervalMm: v })} /></Field>
          <Field label="Überlauf"><NumberInput value={l.overscanMm} unit="mm" step={0.5} min={0} max={30} digits={1} onChange={(v) => ops.updateLayer(l.id, { overscanMm: v })} /></Field>
        </>}
      </div>
      {l.passes > 1 && l.zStepMm > 0 && <p className="mv-muted-note">Fokus sinkt insgesamt um {((l.passes - 1) * l.zStepMm).toFixed(2).replace('.', ',')} mm, höchstens {Limits.MAX_FOCUS_DROP_MM} mm, danach zurück.</p>}
      {l.materialName && <p className="mv-muted-note">Werte aus {l.materialName}{l.thicknessMm > 0 ? `, ${String(l.thicknessMm).replace('.', ',')} mm` : ''}.</p>}
      <div><Button variant="ghost" size="sm" icon={<Trash2 size={14} />} onClick={() => void remove()} data-testid={`layer-delete-${l.name}`}>Ebene löschen</Button></div>
    </div>}
  </div>;
}
