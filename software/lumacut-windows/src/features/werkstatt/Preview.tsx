import { useEffect, useMemo, useRef, useState } from 'react';
import { Bed, type Doc, isClosed, type Layer, layerCss, layerLabel, parkBox, type Poly } from '@/core/model';
import { drawRasterPreview } from '@/core/raster';
import { type GenImage, type GenPart, type GenResult, partBounds, plateCountOf, plateOffset, resultBounds } from '@/core/generators';
import { Segmented } from '@/ui/kit';

/**
 * True geometry at true scale. In "Teil" the view fits the result, in "Auf der Platte" the whole work area with
 * the park corner. Pixel-independent marks (scale bar, dimensions) are sized from the measured width of the view.
 */
export const pathD = (polys: Poly[], precision = 3) => {
  const f = (v: number) => +v.toFixed(precision);
  let d = '';
  for (const p of polys) {
    if (p.length < 2) continue;
    const closed = isClosed(p, 1e-4);
    const n = closed ? p.length - 1 : p.length;
    d += `M${f(p[0].x)} ${f(p[0].y)}`;
    for (let i = 1; i < n; i++) d += `L${f(p[i].x)} ${f(p[i].y)}`;
    if (closed) d += 'Z';
  }
  return d;
};

export function imageUrl(img: GenImage): string {
  const canvas = document.createElement('canvas');
  drawRasterPreview(canvas, img.raster, { mode: img.mode, adjust: img.adjust, maxPixels: 1_200_000 });
  return canvas.toDataURL('image/png');
}

export interface LayerStyle { color: string; fill: boolean; label: string }
export function layerStyles(r: GenResult, doc: Doc): Map<string, LayerStyle> {
  const out = new Map<string, LayerStyle>();
  const of = (l: Pick<Layer, 'color' | 'mode' | 'name'>): LayerStyle => ({ color: layerCss(l), fill: l.mode === 'FILL', label: layerLabel(l) });
  for (const l of doc.layers) out.set(l.name, of(l));
  for (const g of r.layers ?? []) {
    const base = doc.layers.find((l) => l.name === g.base);
    out.set(g.key, of({ color: g.color ?? base?.color ?? 0xFF808080, mode: g.over.mode ?? base?.mode ?? 'LINE', name: g.name }));
  }
  return out;
}

function PartShape({ part, style }: { part: GenPart; style: LayerStyle | undefined }) {
  const url = useMemo(() => part.image ? imageUrl(part.image) : null, [part.image]);
  if (part.image) return <image href={url ?? undefined} x={part.x ?? 0} y={part.y ?? 0} width={part.image.widthMm} height={part.image.heightMm} preserveAspectRatio="none" style={{ imageRendering: 'pixelated' }} />;
  const d = pathD(part.paths);
  const color = style?.color ?? 'var(--text)';
  return style?.fill
    ? <path d={d} fill={color} fillOpacity={0.82} fillRule="evenodd" stroke={color} strokeWidth={0.75} vectorEffect="non-scaling-stroke" />
    : <path d={d} fill="none" stroke={color} strokeWidth={1.25} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />;
}

const SCALE_STEPS = [1, 2, 5, 10, 20, 50, 100, 200];
const nice = (v: number) => String(+v.toFixed(1)).replace('.', ',');

export function Preview({ result, doc, initialView = 'part' }: { result: GenResult | null; doc: Doc; initialView?: 'part' | 'plate' }) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [view, setView] = useState<'part' | 'plate'>(initialView);
  const [plate, setPlate] = useState(0);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const plates = result ? plateCountOf(result) : 0;
  useEffect(() => { if (plate >= plates && plates > 0) setPlate(plates - 1); }, [plate, plates]);
  const off = result ? plateOffset(result, plate) : { x: 0, y: 0 };
  const parts = useMemo(() => result ? result.parts.filter((p) => (p.plate ?? 0) === plate) : [], [result, plate]);
  const b = useMemo(() => {
    const q = resultBounds(parts);
    return q ? { minX: q.minX + off.x, minY: q.minY + off.y, maxX: q.maxX + off.x, maxY: q.maxY + off.y } : null;
  }, [parts, off.x, off.y]);
  const styles = useMemo(() => result ? layerStyles(result, doc) : new Map<string, LayerStyle>(), [result, doc]);

  // Room for the controls on top, the scale bar below and the dimensions at the right.
  const padT = 84, padB = 44, padL = 28, padR = 60;
  const frame = view === 'plate' || !b ? { minX: 0, minY: 0, maxX: Bed.width, maxY: Bed.height } : b;
  const fw = Math.max(frame.maxX - frame.minX, 1), fh = Math.max(frame.maxY - frame.minY, 1);
  const k = Math.max(0.01, Math.min((size.w - padL - padR) / fw, (size.h - padT - padB) / fh));
  const vbW = size.w / k, vbH = size.h / k;
  const vbX = (frame.minX + frame.maxX) / 2 - (padL + (size.w - padL - padR) / 2) / k, vbY = (frame.minY + frame.maxY) / 2 - (padT + (size.h - padT - padB) / 2) / k;
  const px = 1 / k;
  const barMm = SCALE_STEPS.find((v) => v * k >= 60) ?? 500;
  const grid = (barMm >= 50 ? 10 : barMm >= 5 ? 5 : 1);

  const used = useMemo(() => {
    const seen = new Map<string, LayerStyle>();
    for (const p of parts) { const st = styles.get(p.layer); if (st && !result?.layers?.some((g) => g.key === p.layer && g.key.startsWith('f'))) seen.set(st.label, st); }
    return [...seen.values()];
  }, [parts, styles, result]);

  const w = b ? b.maxX - b.minX : 0, h = b ? b.maxY - b.minY : 0;
  return (
    <div className="ws-preview" ref={ref}>
      <svg data-testid="ws-preview" data-w={w.toFixed(2)} data-h={h.toFixed(2)} data-plates={plates} viewBox={`${vbX} ${vbY} ${vbW} ${vbH}`} width={size.w} height={size.h} role="img" aria-label={b ? `Vorschau ${nice(w)} mal ${nice(h)} Millimeter` : 'Keine Vorschau'}>
        <defs>
          <pattern id="ws-grid" width={grid} height={grid} patternUnits="userSpaceOnUse"><path d={`M${grid} 0H0V${grid}`} fill="none" stroke="var(--grid)" strokeWidth={px} /></pattern>
        </defs>
        {view === 'plate' ? <>
          <rect x={0} y={0} width={Bed.width} height={Bed.height} fill="var(--sheet)" stroke="var(--line-2)" strokeWidth={px} />
          <rect x={0} y={0} width={Bed.width} height={Bed.height} fill="url(#ws-grid)" />
          {(() => { const q = parkBox(); return <g><rect x={q.minX} y={q.minY} width={q.maxX - q.minX} height={q.maxY - q.minY} fill="var(--park)" /><text x={(q.minX + q.maxX) / 2} y={(q.minY + q.maxY) / 2 + 4 * px} fontSize={11 * px} textAnchor="middle" fill="var(--faint)">Park-Ecke</text></g>; })()}
        </> : <rect x={vbX} y={vbY} width={vbW} height={vbH} fill="url(#ws-grid)" />}
        <g transform={`translate(${off.x} ${off.y})`}>{parts.map((p, i) => <PartShape key={i} part={p} style={styles.get(p.layer)} />)}</g>
        {b && view === 'part' && <g fontSize={12 * px} fill="var(--muted)" stroke="var(--faint)" strokeWidth={px}>
          <line x1={b.minX} x2={b.maxX} y1={b.minY - 14 * px} y2={b.minY - 14 * px} /><line x1={b.minX} x2={b.minX} y1={b.minY - 18 * px} y2={b.minY - 10 * px} /><line x1={b.maxX} x2={b.maxX} y1={b.minY - 18 * px} y2={b.minY - 10 * px} />
          <line y1={b.minY} y2={b.maxY} x1={b.maxX + 14 * px} x2={b.maxX + 14 * px} /><line y1={b.minY} y2={b.minY} x1={b.maxX + 10 * px} x2={b.maxX + 18 * px} /><line y1={b.maxY} y2={b.maxY} x1={b.maxX + 10 * px} x2={b.maxX + 18 * px} />
          <text stroke="none" x={(b.minX + b.maxX) / 2} y={b.minY - 19 * px} textAnchor="middle" style={{ fontVariantNumeric: 'tabular-nums' }}>{nice(w)} mm</text>
          <text stroke="none" transform={`translate(${b.maxX + 28 * px} ${(b.minY + b.maxY) / 2}) rotate(90)`} textAnchor="middle" style={{ fontVariantNumeric: 'tabular-nums' }}>{nice(h)} mm</text>
        </g>}
        <g transform={`translate(${vbX + 16 * px} ${vbY + vbH - 18 * px})`} fontSize={11 * px} fill="var(--muted)">
          <rect width={barMm} height={3 * px} fill="var(--muted)" /><text y={-5 * px} style={{ fontVariantNumeric: 'tabular-nums' }}>{barMm} mm</text>
        </g>
      </svg>
      <div className="ws-preview-top">
        <Segmented<'part' | 'plate'> ariaLabel="Ansicht" value={view} onChange={setView} options={[{ value: 'part', label: 'Teil' }, { value: 'plate', label: 'Auf der Platte' }]} />
        {plates > 1 && <div className="seg" role="tablist" aria-label="Platten" data-testid="ws-plates">
          {Array.from({ length: Math.min(plates, 12) }, (_, i) => <button key={i} type="button" role="tab" aria-checked={i === plate} aria-selected={i === plate} onClick={() => setPlate(i)}>Platte {i + 1}</button>)}
          {plates > 12 && <span className="muted" style={{ alignSelf: 'center', padding: '0 8px' }}>von {plates}</span>}
        </div>}
        <div className="grow" />
        {used.length > 0 && <div className="ws-legend">{used.map((u) => <span key={u.label}><i style={{ background: u.color }} />{u.label}</span>)}</div>}
      </div>
    </div>
  );
}

/** Small monochrome picture of a tool for the gallery. Same generators, same geometry. */
export function Thumb({ result }: { result: GenResult | null }) {
  const data = useMemo(() => {
    if (!result) return null;
    const parts = result.parts.filter((p) => (p.plate ?? 0) === 0 && (p.paths.length || p.image));
    const b = resultBounds(parts);
    if (!b) return null;
    const pad = Math.max(b.maxX - b.minX, b.maxY - b.minY) * 0.06;
    return { parts, vb: `${b.minX - pad} ${b.minY - pad} ${b.maxX - b.minX + 2 * pad} ${b.maxY - b.minY + 2 * pad}` };
  }, [result]);
  if (!data) return <div className="ws-thumb" />;
  return (
    <div className="ws-thumb"><svg viewBox={data.vb} preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      {data.parts.map((p, i) => {
        if (p.image) { const q = partBounds(p)!; return <ThumbImage key={i} img={p.image} x={q.minX} y={q.minY} />; }
        const fill = p.layer === 'Gravieren' || p.layer === 'foto' || p.layer === 'beschriftung' || p.layer.startsWith('f');
        return <path key={i} d={pathD(p.paths, 2)} fill={fill ? 'var(--muted)' : 'none'} fillRule="evenodd" stroke={p.layer === 'Schneiden' ? 'var(--accent)' : 'var(--faint)'} strokeWidth={1} vectorEffect="non-scaling-stroke" />;
      })}
    </svg></div>
  );
}
function ThumbImage({ img, x, y }: { img: GenImage; x: number; y: number }) {
  const url = useMemo(() => imageUrl(img), [img]);
  return <image href={url} x={x} y={y} width={img.widthMm} height={img.heightMm} />;
}
