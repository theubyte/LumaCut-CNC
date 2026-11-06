import { useDeferredValue, useEffect, useMemo, useState } from 'react';
import { AlertCircle, ArrowLeft, Check as CheckIcon, FolderOpen, Info } from 'lucide-react';
import { pickFiles } from '@/platform';
import { BUNDLED_FAMILY, loadFont } from '@/core/text';
import { decodeImageBytes, rasterFromRgba } from '@/core/import/image';
import { grayOf } from '@/core/raster';
import { type GenResult, GenError, type PhotoSource, plateCountOf, samplePhoto, shaperFromFonts, type TextShaper } from '@/core/generators';
import { useDoc } from '@/store/doc';
import { useUi } from '@/store/ui';
import { useMachine } from '@/pi/machine';
import { Button, Check, Field, Note, NumberInput, Segmented, Slider, toast } from '@/ui/kit';
import { applyNesting, applyResult, layerMapFor } from './apply';
import { MatcalSettings, matcalArea } from './Matcal';
import { Preview, Thumb } from './Preview';
import { type Env, type Field as FieldSpec, GROUPS, type Params, type Tool, TOOLS } from './tools';
import './werkstatt.css';

let fontPromise: Promise<TextShaper> | null = null;
const loadShaper = () => fontPromise ??= Promise.all([loadFont(BUNDLED_FAMILY, false), loadFont(BUNDLED_FAMILY, true)]).then(([r, b]) => shaperFromFonts(r, b));
function useShaper() {
  const [shape, setShape] = useState<TextShaper | null>(null);
  useEffect(() => { let on = true; void loadShaper().then((s) => { if (on) setShape(() => s); }); return () => { on = false; }; }, []);
  return shape;
}

export default function View() {
  const [open, setOpen] = useState<string | null>(null);
  const tool = TOOLS.find((t) => t.id === open);
  return tool ? <Wizard key={tool.id} tool={tool} onClose={() => setOpen(null)} /> : <Gallery onOpen={setOpen} />;
}

/* ---- Gallery ---- */
function Gallery({ onOpen }: { onOpen(id: string): void }) {
  const shape = useShaper();
  const doc = useDoc((s) => s.doc);
  const thumbs = useMemo(() => {
    const out = new Map<string, GenResult>();
    if (!shape) return out;
    const env: Env = { shape, doc, selection: [], photo: samplePhoto(240, 160), photoName: null };
    for (const t of TOOLS) {
      try { out.set(t.id, t.thumb ? t.thumb(env) : t.compute(t.defaults({ doc }), env)); } catch { /* the card simply has no picture */ }
    }
    return out;
  }, [shape]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="page" data-testid="werkstatt">
      <div className="page-narrow ws-gallery">
        <header><h1 className="h1">Werkstatt</h1><p className="muted">Fertige Bausteine: einstellen, in der Vorschau prüfen, ins Motiv übernehmen.</p></header>
        <div className="ws-groups">
        {GROUPS.map((g) => (
          <section key={g}>
            <h2 className="section-title">{g}</h2>
            <div className="ws-cards">
              {TOOLS.filter((t) => t.group === g).map((t) => {
                const I = t.icon;
                return (
                  <button key={t.id} type="button" className="ws-card" data-testid={`tool-${t.id}`} onClick={() => onOpen(t.id)}>
                    <Thumb result={thumbs.get(t.id) ?? null} />
                    <span className="ws-card-text"><span className="ws-card-title"><I size={15} />{t.title}</span><span className="muted">{t.blurb}</span></span>
                  </button>
                );
              })}
            </div>
          </section>
        ))}
        </div>
        <Note tone="info"><b>Drehachse:</b> Die LumaCut hat keine Drehachse (nur X, Y und Z). Runde Gegenstände lassen sich nicht rundum gravieren, deshalb gibt es dafür hier keinen Assistenten.</Note>
      </div>
    </div>
  );
}

/* ---- Assistant ---- */
function Wizard({ tool, onClose }: { tool: Tool; onClose(): void }) {
  const doc = useDoc((s) => s.doc);
  const selection = useDoc((s) => s.selection);
  const go = useUi((u) => u.go);
  const shape = useShaper();
  const [params, setParams] = useState<Params>(() => tool.defaults({ doc }));
  const [photo, setPhoto] = useState<PhotoSource | null>(null);
  const [photoName, setPhotoName] = useState<string | null>(null);
  const [matMode, setMatMode] = useState<'grid' | 'camera'>('grid');
  const [camKind, setCamKind] = useState<'engrave' | 'cut'>('engrave');
  const deferred = useDeferredValue(params);
  const head = useMachine((m) => m.status.position);
  const camera = tool.custom === 'matgrid' && matMode === 'camera';

  const set = (key: string, v: number | string | boolean) => setParams((p) => { const n = { ...p, [key]: v }; return tool.linked ? tool.linked(key, n) : n; });

  const { result, error } = useMemo((): { result: GenResult | null; error: string | null } => {
    if (!shape || camera) return { result: null, error: null };
    try { return { result: tool.compute(deferred, { shape, doc, selection, photo, photoName }), error: null }; }
    catch (e) { if (e instanceof GenError || e instanceof Error) return { result: null, error: e.message }; throw e; }
  }, [deferred, shape, doc, selection, photo, photoName, tool, camera]);

  const camResult = useMemo((): GenResult | null => {
    if (!camera || !head) return null;
    const a = matcalArea(camKind, head[0], head[1]);
    return { placement: 'keep', layers: [{ key: 'testbereich', name: 'Testbereich', base: 'Linie', over: {} }], parts: [{ name: 'Testbereich', layer: 'testbereich', paths: [[{ x: a.minX, y: a.minY }, { x: a.maxX, y: a.minY }, { x: a.maxX, y: a.maxY }, { x: a.minX, y: a.maxY }, { x: a.minX, y: a.minY }]] }] };
  }, [camera, camKind, head]);

  const apply = () => {
    if (!result) return;
    if (tool.custom === 'nest') {
      const r = applyNesting(params.scope as string, params.gap as number);
      toast(`${r.moved} Elemente auf ${r.plates} ${r.plates === 1 ? 'Platte' : 'Platten'} angeordnet.`, r.leftOut ? 'warn' : 'ok');
    } else {
      const r = applyResult(result, { freshPlate: tool.freshPlate });
      toast(`${tool.title}: ${r.count} ${r.count === 1 ? 'Element' : 'Elemente'} im Motiv${r.plates > 1 ? `, ${r.plates} Platten` : ''}.`, 'ok');
    }
    go('motiv');
  };

  const pick = async () => {
    const files = await pickFiles([{ name: 'Bilder', extensions: ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif'] }]);
    const f = files[0]; if (!f) return;
    try {
      const raster = rasterFromRgba(await decodeImageBytes(f.bytes));
      setPhoto({ gray: grayOf(raster), width: raster.width, height: raster.height });
      setPhotoName(f.name);
    } catch (e) { toast((e as Error).message, 'bad'); }
  };

  const plates = result ? plateCountOf(result) : 0;
  const summary = useMemo(() => {
    if (!result || !result.parts.length) return null;
    const map = layerMapFor(result, doc);
    const newLayers = map.layers.length - doc.layers.length;
    const count = result.parts.length;
    const on = [...new Set(result.parts.map((p) => p.layer))].filter((l) => ['Gravieren', 'Linie', 'Schneiden'].includes(l)).map((l) => l === 'Linie' ? 'Markieren' : l);
    return [`${count} ${count === 1 ? 'Element' : 'Elemente'}`, on.length ? `auf ${on.join(', ')}` : null, newLayers ? `${newLayers} neue ${newLayers === 1 ? 'Ebene' : 'Ebenen'}` : null, plates > 1 ? `${plates} Platten` : null].filter(Boolean).join(' · ');
  }, [result, doc, plates]);

  const fields = tool.fields(params);
  return (
    <div className="ws-wizard" data-testid="ws-wizard">
      <header className="ws-head">
        <Button variant="ghost" icon={<ArrowLeft size={16} />} onClick={onClose} data-testid="ws-back">Werkstatt</Button>
        <span className="ws-sep" />
        <h1 className="h2">{tool.title}</h1>
        <span className="muted ws-blurb">{tool.blurb}</span>
      </header>
      <div className="ws-body">
        <aside className="ws-settings">
          {tool.custom === 'matgrid' && <div className="ws-way">
            <Segmented<'grid' | 'camera'> ariaLabel="Weg" value={matMode} onChange={setMatMode} options={[{ value: 'grid', label: 'Raster im Motiv' }, { value: 'camera', label: 'Automatisch mit Kamera' }]} />
            {!camera && <p className="muted">Ein Raster aus Feldern mit Leistung gegen Tempo kommt ins Motiv. Sie starten es wie jeden Auftrag und beurteilen das Ergebnis selbst.</p>}
          </div>}
          {camera ? <MatcalSettings kind={camKind} setKind={setCamKind} /> : <>
            <div className="col ws-form">{fields.map((f, i) => <FieldView key={i} f={f} p={params} set={set} photoName={photoName} pick={pick} clearPhoto={() => { setPhoto(null); setPhotoName(null); }} />)}</div>
            <div className="col ws-messages">
              {error && <Note tone="bad"><span data-testid="ws-error">{error}</span></Note>}
              {result?.warnings?.map((w) => <Note key={w} tone="warn">{w}</Note>)}
              {result?.notes?.map((n) => <p key={n} className="ws-note"><Info size={14} /><span>{n}</span></p>)}
            </div>
          </>}
        </aside>
        <section className="ws-stage">
          {camera && !camResult
            ? <div className="empty grow"><AlertCircle size={22} /><p>Sobald die Position bekannt ist, erscheint hier der Testbereich. Dazu die Maschine referenzieren.</p></div>
            : <Preview key={camera ? 'camera' : 'tool'} result={camera ? camResult : result} doc={doc} initialView={camera ? 'plate' : 'part'} />}
        </section>
      </div>
      {!camera && <footer className="ws-foot">
        <span className="muted" data-testid="ws-summary">{summary ?? (shape ? '' : 'Schrift wird geladen …')}</span>
        <div className="grow" />
        <Button size="lg" onClick={onClose}>Abbrechen</Button>
        <Button size="lg" variant="primary" icon={<CheckIcon size={16} />} disabled={!result || !result.parts.length} onClick={apply} data-testid="ws-apply">{tool.applyLabel ?? 'Ins Motiv übernehmen'}</Button>
      </footer>}
    </div>
  );
}

function FieldView({ f, p, set, photoName, pick, clearPhoto }: { f: FieldSpec; p: Params; set(k: string, v: number | string | boolean): void; photoName: string | null; pick(): void; clearPhoto(): void }) {
  switch (f.type) {
    case 'section': return <h3 className="section-title ws-section">{f.label}</h3>;
    case 'hint': return <p className="faint ws-hint">{f.text}</p>;
    case 'row': return <div className="ws-row" style={{ gridTemplateColumns: `repeat(${f.fields.length}, minmax(0, 1fr))` }}>{f.fields.map((x, i) => <FieldView key={i} f={x} p={p} set={set} photoName={photoName} pick={pick} clearPhoto={clearPhoto} />)}</div>;
    case 'num': return <Field label={f.label} hint={f.hint}><NumberInput ariaLabel={f.aria ?? f.label} value={p[f.key] as number} onChange={(v) => set(f.key, v)} unit={f.unit} min={f.min} max={f.max} step={f.step} digits={f.digits} /></Field>;
    case 'seg': return <Field label={f.label} hint={f.hint}><Segmented ariaLabel={f.label} value={p[f.key] as string} onChange={(v) => set(f.key, v)} options={f.options} /></Field>;
    case 'select': return <Field label={f.label} hint={f.hint}><select className="input" aria-label={f.label} value={p[f.key] as string} onChange={(e) => set(f.key, e.target.value)}>{f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></Field>;
    case 'text': return <Field label={f.label} hint={f.hint}><input className="input" aria-label={f.label} value={p[f.key] as string} placeholder={f.placeholder} onChange={(e) => set(f.key, e.target.value)} /></Field>;
    case 'check': return <Check checked={p[f.key] as boolean} onChange={(v) => set(f.key, v)}>{f.label}</Check>;
    case 'slider': return <Field label={f.label}><Slider value={p[f.key] as number} onChange={(v) => set(f.key, v)} min={f.min} max={f.max} step={f.step} unit={f.unit} digits={f.digits} /></Field>;
    case 'photo': return <div className="ws-photo">
      <Button icon={<FolderOpen size={15} />} onClick={pick} data-testid="ws-photo-pick">{photoName ? 'Anderes Foto' : 'Foto wählen'}</Button>
      <span className="muted ws-photo-name">{photoName ?? 'Noch kein Foto. Die Vorschau zeigt ein Testbild.'}</span>
      {photoName && <Button variant="ghost" size="sm" onClick={clearPhoto}>Entfernen</Button>}
    </div>;
  }
}
