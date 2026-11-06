import type { ComponentProps, ReactNode } from 'react';
import { Lock } from 'lucide-react';
import { Button } from '@/ui/kit';

/** A button that says why it is locked: the sentence is the tooltip, also on the disabled state. */
export function LockedButton({ lock, busy, disabled, title, children, ...rest }: ComponentProps<typeof Button> & { lock?: string | null; busy?: boolean }) {
  const reason = lock ?? undefined;
  return <span className="m-lockwrap" title={reason ?? title}>
    <Button disabled={!!lock || disabled || busy} data-lock={reason} {...rest}>{children}{busy && <span className="m-spin" aria-label="läuft" />}</Button>
  </span>;
}

export const LockLine = ({ text }: { text: string | null }) => text
  ? <p className="m-lockline" data-testid="lock-line"><Lock size={13} /><span>{text}</span></p>
  : null;

export function Stat({ label, value, tone, mono = true, testId }: { label: string; value: ReactNode; tone?: 'warn' | 'bad' | 'ok'; mono?: boolean; testId?: string }) {
  return <div className="m-stat"><span className="m-stat-label">{label}</span>
    <span className={(mono ? 'mono ' : '') + 'm-stat-value'} data-testid={testId} style={tone ? { color: `var(--${tone})` } : undefined}>{value}</span></div>;
}

export function Switch({ on, onChange, disabled, label, title }: { on: boolean; onChange(v: boolean): void; disabled?: boolean; label: string; title?: string }) {
  return <span className="m-lockwrap" title={title}><button type="button" role="switch" className="m-switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)}><span /></button></span>;
}

export function ActionRow({ icon, title, sub, children, testId }: { icon: ReactNode; title: string; sub?: ReactNode; children?: ReactNode; testId?: string }) {
  return <div className="m-row" data-testid={testId}>
    <span className="m-row-icon">{icon}</span>
    <div className="m-row-text"><div className="m-row-title">{title}</div>{sub && <div className="m-row-sub">{sub}</div>}</div>
    <div className="m-row-end">{children}</div>
  </div>;
}

/** The Pi gives dates as ISO text or seconds. */
export function when(v: unknown): string {
  if (v == null || v === '') return '–';
  const d = typeof v === 'number' ? new Date(v < 1e11 ? v * 1000 : v) : new Date(String(v));
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' });
}
