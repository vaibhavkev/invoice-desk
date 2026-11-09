import { forwardRef, type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode } from 'react';
import { Ban, CircleCheck, CirclePause, LoaderCircle } from 'lucide-react';
import { cx } from '../lib/format';
import type { Decision, RunStatus } from '../types';

// ---------------------------------------------------------------- layout bits
export function Card({ children, className, as: As = 'section', ...rest }: { children: ReactNode; className?: string; as?: 'section' | 'div' | 'article' } & HTMLAttributes<HTMLElement>) {
  return (
    <As className={cx('rounded-xl border border-ink-200 bg-white shadow-card', className)} {...rest}>
      {children}
    </As>
  );
}

export function CardHeader({ title, subtitle, right, className }: { title: ReactNode; subtitle?: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <div className={cx('flex items-start justify-between gap-3 px-5 pt-4', className)}>
      <div className="min-w-0">
        <h2 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-ink-500">{title}</h2>
        {subtitle && <p className="mt-0.5 text-sm text-ink-500">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function SectionLabel({ children, className }: { children: ReactNode; className?: string }) {
  return <h4 className={cx('mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-400', className)}>{children}</h4>;
}

// ---------------------------------------------------------------- buttons
type BtnVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
const BTN_VARIANT: Record<BtnVariant, string> = {
  primary: 'bg-ink-900 text-white hover:bg-ink-700 border border-ink-900',
  secondary: 'bg-white text-ink-900 border border-ink-200 hover:border-ink-300 hover:bg-ink-50',
  ghost: 'bg-transparent text-ink-600 border border-transparent hover:bg-ink-100 hover:text-ink-900',
  danger: 'bg-reject text-white border border-reject hover:bg-reject-ink',
};
/** Button styling, also usable on <Link> so we never nest a button in an anchor. */
export function buttonClass(variant: BtnVariant = 'secondary', size: 'sm' | 'md' = 'md', extra?: string) {
  return cx(
    'inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
    size === 'sm' ? 'h-8 px-2.5 text-[13px]' : 'h-9 px-3.5 text-sm',
    BTN_VARIANT[variant],
    extra,
  );
}
export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: 'sm' | 'md'; icon?: ReactNode }>(
  function Button({ variant = 'secondary', size = 'md', icon, className, children, type = 'button', ...rest }, ref) {
    return (
      <button ref={ref} type={type} className={buttonClass(variant, size, className)} {...rest}>
        {icon}
        {children}
      </button>
    );
  },
);

// ---------------------------------------------------------------- status chips
const DECISION_STYLE: Record<Decision, { cls: string; label: string; dot: string }> = {
  APPROVE: { cls: 'bg-approve-soft text-approve-ink border-approve-line', label: 'Approve', dot: 'bg-approve' },
  HOLD: { cls: 'bg-hold-soft text-hold-ink border-hold-line', label: 'Hold', dot: 'bg-hold' },
  REJECT: { cls: 'bg-reject-soft text-reject-ink border-reject-line', label: 'Reject', dot: 'bg-reject' },
};

export function DecisionChip({ decision, size = 'sm', prefix }: { decision: Decision; size?: 'xs' | 'sm' | 'md'; prefix?: string }) {
  const s = DECISION_STYLE[decision];
  return (
    <span
      className={cx(
        'inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border font-semibold uppercase tracking-[0.04em]',
        size === 'xs' ? 'h-5 px-2 text-[10px]' : size === 'sm' ? 'h-6 px-2.5 text-[11px]' : 'h-7 px-3 text-xs',
        s.cls,
      )}
    >
      <span className={cx('h-1.5 w-1.5 rounded-full', s.dot)} aria-hidden />
      {prefix && <span className="font-medium normal-case tracking-normal opacity-75">{prefix}</span>}
      {decision}
    </span>
  );
}

export function DecisionIcon({ decision, className }: { decision: Decision; className?: string }) {
  if (decision === 'APPROVE') return <CircleCheck className={cx('text-approve', className)} aria-hidden />;
  if (decision === 'HOLD') return <CirclePause className={cx('text-hold', className)} aria-hidden />;
  return <Ban className={cx('text-reject', className)} aria-hidden />;
}

export function RunStatusChip({ status, decision }: { status: RunStatus | 'loading'; decision?: Decision | null }) {
  if (status === 'completed' && decision) return <DecisionChip decision={decision} />;
  const map: Record<string, { cls: string; label: string; spin?: boolean }> = {
    loading: { cls: 'bg-ink-100 text-ink-500 border-ink-200', label: 'Loading' },
    queued: { cls: 'bg-pending-soft text-ink-600 border-pending-line', label: 'Queued' },
    running: { cls: 'bg-running-soft text-running-ink border-running-line', label: 'Running', spin: true },
    completed: { cls: 'bg-ink-100 text-ink-700 border-ink-200', label: 'Completed' },
    failed: { cls: 'bg-reject-soft text-reject-ink border-reject-line', label: 'Failed' },
  };
  const s = map[status] ?? map.loading!;
  return (
    <span className={cx('inline-flex h-6 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 text-[11px] font-semibold uppercase tracking-[0.04em]', s.cls)}>
      {s.spin ? <LoaderCircle className="h-3 w-3 animate-spin" aria-hidden /> : <span className="h-1.5 w-1.5 rounded-full bg-current opacity-60" aria-hidden />}
      {s.label}
    </span>
  );
}

export function Tag({ children, tone = 'neutral', className, title }: { children: ReactNode; tone?: 'neutral' | 'approve' | 'hold' | 'reject' | 'running' | 'outline'; className?: string; title?: string }) {
  const tones = {
    neutral: 'bg-ink-100 text-ink-700 border-transparent',
    outline: 'bg-white text-ink-600 border-ink-200',
    approve: 'bg-approve-soft text-approve-ink border-approve-line',
    hold: 'bg-hold-soft text-hold-ink border-hold-line',
    reject: 'bg-reject-soft text-reject-ink border-reject-line',
    running: 'bg-running-soft text-running-ink border-running-line',
  } as const;
  return (
    <span title={title} className={cx('inline-flex h-[22px] shrink-0 items-center gap-1 whitespace-nowrap rounded-md border px-1.5 text-xs font-medium', tones[tone], className)}>
      {children}
    </span>
  );
}

export function Mono({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cx('font-mono text-[12.5px] tracking-tight', className)}>
      {children}
    </span>
  );
}

// ---------------------------------------------------------------- bars
/** Confidence 0–1 with a tick at the policy floor; amber below the floor. */
export function ConfidenceBar({ value, floor = 0.75, width = 'w-20', showValue = true }: { value: number | null | undefined; floor?: number; width?: string; showValue?: boolean }) {
  const v = value == null ? 0 : Math.max(0, Math.min(1, value));
  const low = value != null && value < floor;
  return (
    <span className="inline-flex items-center gap-2" title={value == null ? 'No confidence' : `Confidence ${value.toFixed(2)} (floor ${floor})`}>
      <span className={cx('relative h-1.5 overflow-hidden rounded-full bg-ink-100', width)}>
        <span className={cx('absolute inset-y-0 left-0 rounded-full', low ? 'bg-hold' : 'bg-ink-600')} style={{ width: `${v * 100}%` }} />
        <span className="absolute inset-y-[-2px] w-px bg-ink-300" style={{ left: `${floor * 100}%` }} aria-hidden />
      </span>
      {showValue && <span className={cx('w-8 text-right font-mono text-xs tabular-nums', low ? 'font-semibold text-hold-ink' : 'text-ink-600')}>{value == null ? '—' : value.toFixed(2)}</span>}
    </span>
  );
}

/**
 * PO consumption: billed (solid) + this invoice (lighter) against the PO total.
 * Anything beyond the PO total renders as an overshoot segment.
 */
export function ConsumptionBar({ total, billed, incoming = 0, tone, className }: { total: number; billed: number; incoming?: number; tone?: 'approve' | 'hold' | 'reject' | 'neutral'; className?: string }) {
  const sum = billed + incoming;
  const scale = Math.max(total, sum) || 1;
  const billedW = (Math.min(billed, scale) / scale) * 100;
  const incomingW = (Math.max(0, Math.min(sum, total) - billed) / scale) * 100;
  const overW = (Math.max(0, sum - total) / scale) * 100;
  const incomingCls = tone === 'hold' ? 'bg-hold/70' : tone === 'reject' ? 'bg-reject/70' : tone === 'approve' ? 'bg-approve/70' : 'bg-running/60';
  return (
    <div className={cx('relative h-2 w-full overflow-hidden rounded-full bg-ink-100', className)} role="img" aria-label={`Billed ${billed} of ${total}${incoming ? `, this invoice ${incoming}` : ''}`}>
      <div className="absolute inset-y-0 left-0 bg-ink-600" style={{ width: `${billedW}%` }} />
      {incoming > 0 && <div className={cx('absolute inset-y-0', incomingCls)} style={{ left: `${billedW}%`, width: `${incomingW}%` }} />}
      {overW > 0 && (
        <div
          className="absolute inset-y-0 bg-[repeating-linear-gradient(135deg,theme(colors.hold.DEFAULT)_0_4px,theme(colors.hold.line)_4px_8px)]"
          style={{ left: `${(total / scale) * 100}%`, width: `${overW}%` }}
        />
      )}
      {sum > total && <div className="absolute inset-y-[-1px] w-0.5 bg-ink-900" style={{ left: `calc(${(total / scale) * 100}% - 1px)` }} aria-hidden />}
    </div>
  );
}

// ---------------------------------------------------------------- loading + empty
export function Skeleton({ className }: { className?: string }) {
  return <span className={cx('block animate-shimmer rounded-md bg-[linear-gradient(90deg,theme(colors.ink.100)_0,theme(colors.ink.50)_50%,theme(colors.ink.100)_100%)] bg-[length:800px_100%]', className)} aria-hidden />;
}

export function EmptyState({ icon, title, body, action, className }: { icon?: ReactNode; title: string; body?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cx('flex flex-col items-center justify-center px-6 py-12 text-center', className)}>
      {icon && <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-ink-100 text-ink-500">{icon}</div>}
      <p className="text-sm font-semibold text-ink-900">{title}</p>
      {body && <p className="mt-1 max-w-sm text-sm text-ink-500">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function NoData() {
  return <p className="text-sm text-ink-500">No data recorded.</p>;
}

export function KV({ label, children, mono }: { label: ReactNode; children: ReactNode; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-ink-500">{label}</dt>
      <dd className={cx('mt-0.5 truncate text-sm text-ink-900', mono && 'font-mono text-[12.5px]')}>{children}</dd>
    </div>
  );
}

export const OWNER_LABEL: Record<string, string> = { ap: 'AP team', requester: 'Requester', vendor: 'Vendor', none: 'No action' };
