import { type ButtonHTMLAttributes, type ReactNode, useEffect, useRef, useState } from 'react';
import { create } from 'zustand';
import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react';

/** Small UI kit. Features build from these and the classes in base.css; no ad-hoc colours or sizes. */
type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'default' | 'primary' | 'ghost' | 'danger'; size?: 'sm' | 'md' | 'lg'; icon?: ReactNode; iconOnly?: boolean; pressed?: boolean };
export function Button({ variant = 'default', size = 'md', icon, iconOnly, pressed, className = '', children, ...rest }: BtnProps) {
  const cls = ['btn', variant !== 'default' && `btn-${variant}`, size !== 'md' && `btn-${size}`, iconOnly && 'btn-icon', className].filter(Boolean).join(' ');
  return <button type="button" className={cls} aria-pressed={pressed} {...rest}>{icon}{children}</button>;
}

export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return <div className="field"><label>{label}</label>{children}{hint && <span className="faint" style={{ fontSize: 'var(--fs-xs)' }}>{hint}</span>}</div>;
}

/**
 * Number input: commits on Enter/blur, Up/Down steps (Shift ×10), accepts "," as decimal, shows a unit.
 * Keeps the typed text while focused so typing is never fought.
 */
export function NumberInput({ value, onChange, unit, step = 1, min, max, digits = 2, disabled, title, ariaLabel }: {
  value: number; onChange(v: number): void; unit?: string; step?: number; min?: number; max?: number; digits?: number; disabled?: boolean; title?: string; ariaLabel?: string;
}) {
  const fmt = (v: number) => Number.isFinite(v) ? String(+v.toFixed(digits)).replace('.', ',') : '';
  const [text, setText] = useState(fmt(value));
  const focused = useRef(false);
  useEffect(() => { if (!focused.current) setText(fmt(value)); }, [value]); // eslint-disable-line
  const clamp = (v: number) => Math.min(max ?? Infinity, Math.max(min ?? -Infinity, v));
  const commit = () => {
    // Nur Anzeige gerundet: ohne Eingabe bleibt der genaue Wert erhalten.
    if (text === fmt(value)) return;
    const v = parseFloat(text.replace(',', '.'));
    if (Number.isFinite(v)) { const c = clamp(v); setText(fmt(c)); if (c !== value) onChange(c); } else setText(fmt(value));
  };
  return (
    <div className={'num' + (unit ? ' has-unit' : '')} title={title}>
      <input className="input" inputMode="decimal" value={text} disabled={disabled} aria-label={ariaLabel}
        onFocus={(e) => { focused.current = true; e.target.select(); }}
        onBlur={() => { focused.current = false; commit(); }}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { commit(); (e.target as HTMLInputElement).blur(); }
          else if (e.key === 'Escape') { setText(fmt(value)); (e.target as HTMLInputElement).blur(); }
          else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
            e.preventDefault();
            const cur = parseFloat(text.replace(',', '.')); const base = Number.isFinite(cur) ? cur : value;
            const c = clamp(base + (e.key === 'ArrowUp' ? 1 : -1) * step * (e.shiftKey ? 10 : 1)); setText(fmt(c)); onChange(c);
          }
        }} />
      {unit && <span className="unit">{unit}</span>}
    </div>
  );
}

export function Slider({ value, onChange, min, max, step = 1, unit, digits = 0, onCommit }: { value: number; onChange(v: number): void; onCommit?(): void; min: number; max: number; step?: number; unit?: string; digits?: number }) {
  return (
    <div className="slider">
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(+e.target.value)} onPointerUp={onCommit} />
      <div style={{ width: 76 }}><NumberInput value={value} onChange={(v) => { onChange(v); onCommit?.(); }} min={min} max={max} step={step} unit={unit} digits={digits} /></div>
    </div>
  );
}

export function Segmented<T extends string>({ options, value, onChange, ariaLabel }: { options: { value: T; label: ReactNode; title?: string }[]; value: T; onChange(v: T): void; ariaLabel?: string }) {
  return <div className="seg" role="radiogroup" aria-label={ariaLabel}>
    {options.map((o) => <button key={o.value} type="button" role="radio" title={o.title} aria-checked={o.value === value} onClick={() => onChange(o.value)}>{o.label}</button>)}
  </div>;
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { value: T; label: ReactNode }[]; value: T; onChange(v: T): void }) {
  return <div className="tabs" role="tablist">{tabs.map((t) => <button key={t.value} role="tab" type="button" aria-selected={t.value === value} onClick={() => onChange(t.value)}>{t.label}</button>)}</div>;
}

export function Check({ checked, onChange, children, disabled }: { checked: boolean; onChange(v: boolean): void; children?: ReactNode; disabled?: boolean }) {
  return <label className="check"><input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />{children}</label>;
}

const NOTE_ICON = { info: Info, warn: AlertTriangle, bad: XCircle, ok: CheckCircle2 };
export function Note({ tone = 'info', children }: { tone?: keyof typeof NOTE_ICON; children: ReactNode }) {
  const I = NOTE_ICON[tone];
  return <div className={`note note-${tone}`}><I size={15} /><div>{children}</div></div>;
}

/** Modal dialog. Renders below the top bar, so NOT-AUS stays reachable. Esc closes unless `locked`. */
export function Dialog({ title, children, footer, onClose, width, locked }: { title: ReactNode; children: ReactNode; footer?: ReactNode; onClose?(): void; width?: number; locked?: boolean }) {
  useEffect(() => {
    if (locked || !onClose) return;
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose(); } };
    window.addEventListener('keydown', h, true);
    return () => window.removeEventListener('keydown', h, true);
  }, [onClose, locked]);
  return <div className="scrim" onPointerDown={(e) => { if (e.target === e.currentTarget && !locked) onClose?.(); }}>
    <div className="dialog" role="dialog" aria-modal="true" style={width ? { width } : undefined}>
      <div className="dialog-head">{title}</div>
      <div className="dialog-body">{children}</div>
      {footer && <div className="dialog-foot">{footer}</div>}
    </div>
  </div>;
}

export interface MenuEntry { label?: ReactNode; icon?: ReactNode; kbd?: string; onClick?(): void; disabled?: boolean; separator?: boolean }
/** Dropdown/context menu at screen position. */
export function Menu({ x, y, items, onClose }: { x: number; y: number; items: MenuEntry[]; onClose(): void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x, y });
  useEffect(() => {
    const el = ref.current; if (el) { const r = el.getBoundingClientRect();
      setPos({ x: Math.min(x, innerWidth - r.width - 8), y: Math.min(y, innerHeight - r.height - 8) }); }
    const away = (e: PointerEvent) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('pointerdown', away, true); window.addEventListener('keydown', esc);
    return () => { window.removeEventListener('pointerdown', away, true); window.removeEventListener('keydown', esc); };
  }, [x, y, onClose]);
  return <div ref={ref} className="menu" role="menu" style={{ left: pos.x, top: pos.y }}>
    {items.map((it, i) => it.separator ? <div key={i} className="menu-sep" /> :
      <button key={i} className="menu-item" role="menuitem" type="button" disabled={it.disabled} onClick={() => { onClose(); it.onClick?.(); }}>
        {it.icon}<span>{it.label}</span>{it.kbd && <span className="kbd">{it.kbd}</span>}
      </button>)}
  </div>;
}

/** Button that opens a Menu below itself. */
export function MenuButton({ items, children, ...btn }: BtnProps & { items: MenuEntry[] | (() => MenuEntry[]) }) {
  const [at, setAt] = useState<{ x: number; y: number } | null>(null);
  return <>
    <Button {...btn} onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setAt({ x: r.left, y: r.bottom + 4 }); }}>{children}</Button>
    {at && <Menu x={at.x} y={at.y} items={typeof items === 'function' ? items() : items} onClose={() => setAt(null)} />}
  </>;
}

/* ---- Toasts: `toast('Text', 'ok')` from anywhere. ---- */
type ToastTone = 'ok' | 'bad' | 'info' | 'warn';
interface T { id: number; text: string; tone: ToastTone }
const useToasts = create<{ items: T[] }>(() => ({ items: [] }));
let toastId = 0;
export function toast(text: string, tone: ToastTone = 'info') {
  const id = ++toastId;
  useToasts.setState((s) => ({ items: [...s.items.slice(-3), { id, text, tone }] }));
  setTimeout(() => useToasts.setState((s) => ({ items: s.items.filter((t) => t.id !== id) })), tone === 'bad' ? 8000 : 3500);
}
export function Toasts() {
  const items = useToasts((s) => s.items);
  return <div className="toasts" aria-live="polite">{items.map((t) => <div key={t.id} className={`toast toast-${t.tone}`}>{t.text}</div>)}</div>;
}

/* ---- Simple confirm: `await confirmDialog({title, body})`. For machine moves use the go dialog in pi/actions.ts. ---- */
interface ConfirmReq { title: string; body?: ReactNode; okLabel?: string; danger?: boolean; resolve(v: boolean): void }
const useConfirm = create<{ req: ConfirmReq | null }>(() => ({ req: null }));
export const confirmDialog = (o: Omit<ConfirmReq, 'resolve'>) => new Promise<boolean>((resolve) => useConfirm.setState({ req: { ...o, resolve } }));
export function ConfirmHost() {
  const req = useConfirm((s) => s.req);
  if (!req) return null;
  const done = (v: boolean) => { useConfirm.setState({ req: null }); req.resolve(v); };
  return <Dialog title={req.title} onClose={() => done(false)} footer={<>
    <Button autoFocus onClick={() => done(false)}>Abbrechen</Button>
    <Button variant={req.danger ? 'danger' : 'primary'} onClick={() => done(true)}>{req.okLabel ?? 'OK'}</Button></>}>{req.body}</Dialog>;
}
