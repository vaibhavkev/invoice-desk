import { useMemo, useState, type ReactNode } from 'react';
import { ArrowDown, ChevronDown, CircleCheck, CircleMinus, CircleX, LoaderCircle, TriangleAlert } from 'lucide-react';
import { cx, duration } from '../../lib/format';
import { STAGE_DEFS } from '../../lib/stages';
import { useNow } from '../../hooks/useNow';
import type { DocumentClass, StageKey, StageRecord, StageStatus } from '../../types';
import { ErrorBoundary } from '../ErrorBoundary';
import { rulesSummary } from './RulesBody';
import { StageBody } from './StageBody';

const STATUS_LABEL: Partial<Record<StageStatus, { text: string; cls: string }>> = {
  running: { text: 'Running', cls: 'text-running' },
  failed: { text: 'Failed', cls: 'text-reject' },
  skipped: { text: 'Skipped', cls: 'text-ink-400' },
  pending: { text: 'Pending', cls: 'text-ink-400' },
};

function StatusIcon({ status }: { status: StageStatus }) {
  const base = 'flex h-8 w-8 items-center justify-center rounded-full border bg-white';
  switch (status) {
    case 'running':
      return (
        <span className={cx(base, 'animate-soft-pulse border-running-line text-running')}>
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />
        </span>
      );
    case 'done':
      return (
        <span className={cx(base, 'border-approve-line bg-approve-soft text-approve')}>
          <CircleCheck className="h-4 w-4" aria-hidden />
        </span>
      );
    case 'warn':
      return (
        <span className={cx(base, 'border-hold-line bg-hold-soft text-hold')}>
          <TriangleAlert className="h-4 w-4" aria-hidden />
        </span>
      );
    case 'failed':
      return (
        <span className={cx(base, 'border-reject-line bg-reject-soft text-reject')}>
          <CircleX className="h-4 w-4" aria-hidden />
        </span>
      );
    case 'skipped':
      return (
        <span className={cx(base, 'border-dashed border-ink-300 text-ink-300')}>
          <CircleMinus className="h-4 w-4" aria-hidden />
        </span>
      );
    default:
      return (
        <span className={cx(base, 'border-ink-200')}>
          <span className="h-2 w-2 rounded-full bg-ink-200" aria-hidden />
        </span>
      );
  }
}

const finished = (s: StageRecord) => s.status === 'done' || s.status === 'warn' || s.status === 'failed';

export interface TimelineProps {
  stages: StageRecord[];
  documentClass?: DocumentClass | null;
  error?: string | null;
  onShowDecision?: () => void;
  /** Ghost mode: the empty-state preview of the seven stages. */
  ghost?: boolean;
}

export function Timeline({ stages, documentClass, error, onShowDecision, ghost }: TimelineProps) {
  const [toggles, setToggles] = useState<Partial<Record<StageKey, boolean>>>({});
  const anyRunning = stages.some((s) => s.status === 'running');
  const now = useNow(anyRunning, 100);

  // Auto-expand the latest finished stage that has something to show (never `decision`;
  // it renders in the banner). User toggles always win.
  const autoKey = useMemo(() => {
    const cands = stages.filter((s) => finished(s) && s.key !== 'decision');
    return cands.length ? cands[cands.length - 1]!.key : null;
  }, [stages]);

  const integrity = stages.find((s) => s.key === 'integrity');
  const ctx = { stages, integrity };

  return (
    <ol className="relative" aria-label="Pipeline stages">
      {stages.map((s, i) => {
        const last = i === stages.length - 1;
        const def = STAGE_DEFS[i];
        // The decision stage renders in the banner; its card only links there.
        const hasBody = !ghost && finished(s) && s.key !== 'decision';
        const expanded = hasBody && (toggles[s.key] ?? s.key === autoKey);
        const elapsed =
          s.status === 'running' && s.started_at
            ? Math.max(0, Math.min(now - Date.parse(s.started_at), 3_600_000))
            : s.duration_ms;
        // Only the wait worth noticing gets a time; the instant stages would just read "0 ms".
        const showTime = elapsed != null && !ghost && (s.status === 'running' || elapsed >= 1000);
        const label = STATUS_LABEL[s.status];
        const bodyId = `stage-body-${s.key}`;
        // The open extraction body shows the full note, so drop its shortened copy.
        const cardWarnings = expanded ? s.warnings.filter((w) => !w.startsWith('Document notes:')) : s.warnings;
        const header: ReactNode = (
          <>
            <div className="flex min-w-0 items-center gap-2.5">
              <span className="font-mono text-[11px] text-ink-400">{String(i + 1).padStart(2, '0')}</span>
              <span className={cx('truncate text-[15px] font-semibold', s.status === 'pending' || s.status === 'skipped' ? 'text-ink-500' : 'text-ink-950')}>{s.name || def?.name}</span>
              {label && !ghost && <span className={cx('text-xs font-medium', label.cls)}>{label.text}</span>}
              {s.key === 'doc_analysis' && documentClass && finished(s) && (
                <span className="rounded border border-ink-200 px-1.5 py-px text-[11px] font-medium capitalize text-ink-600">{documentClass}</span>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <span className={cx('font-mono text-xs tabular-nums', s.status === 'running' ? 'text-running' : 'text-ink-500')}>{showTime ? duration(elapsed) : ''}</span>
              {hasBody && <ChevronDown className={cx('h-4 w-4 text-ink-400 transition-transform', expanded && 'rotate-180')} aria-hidden />}
            </div>
          </>
        );
        const stageSummary = s.key === 'rules' && finished(s) ? rulesSummary(s, stages.find((x) => x.key === 'matching')) : s.summary;
        const summary = ghost ? def?.blurb : stageSummary || (s.status === 'pending' ? def?.blurb : s.status === 'running' ? runningHint(s.key, documentClass) : '');

        return (
          <li key={s.key} className="relative pb-3 pl-12 last:pb-0">
            {!last && <span className={cx('absolute left-[15px] top-10 bottom-0 w-px', finished(s) ? 'bg-ink-300' : 'bg-ink-200')} aria-hidden />}
            <span className="absolute left-0 top-3">{ghost ? <StatusIcon status="pending" /> : <StatusIcon status={s.status} />}</span>
            <div
              className={cx(
                'rounded-xl border bg-white transition-colors',
                s.status === 'running' ? 'border-running-line shadow-[0_0_0_3px_theme(colors.running.soft)]' : s.status === 'failed' ? 'border-reject-line' : 'border-ink-200',
                (s.status === 'pending' || s.status === 'skipped' || ghost) && 'bg-white/70',
                'shadow-card',
              )}
            >
              {hasBody ? (
                <button
                  type="button"
                  className="flex w-full items-center justify-between gap-3 rounded-xl px-4 pt-3 text-left"
                  aria-expanded={expanded}
                  aria-controls={bodyId}
                  onClick={() => setToggles((t) => ({ ...t, [s.key]: !expanded }))}
                >
                  {header}
                </button>
              ) : (
                <div className="flex w-full items-center justify-between gap-3 px-4 pt-3">{header}</div>
              )}
              {/* An open failed stage shows the same text in its failure note. */}
              {expanded && s.status === 'failed' ? (
                <div className="h-3" />
              ) : (
                <p className={cx('min-h-[20px] px-4 pb-3 pl-[42px] pt-0.5 text-[13px] leading-5', s.status === 'pending' || ghost ? 'text-ink-400' : 'text-ink-600')}>
                  {summary}
                  {s.key === 'decision' && finished(s) && onShowDecision && (
                    <button type="button" onClick={onShowDecision} className="ml-2 inline-flex items-center gap-1 font-medium text-ink-900 underline decoration-ink-300 underline-offset-2 hover:decoration-ink-900">
                      See decision <ArrowDown className="h-3 w-3" aria-hidden />
                    </button>
                  )}
                </p>
              )}
              {s.key === 'extraction' && s.status === 'running' && (
                <div className="px-4 pb-3 pl-[42px]">
                  <div className="relative h-1 overflow-hidden rounded-full bg-running-soft">
                    <div className="absolute inset-y-0 w-2/5 animate-bar-slide rounded-full bg-running/60" />
                  </div>
                </div>
              )}
              {cardWarnings.length > 0 && finished(s) && s.key !== 'rules' && s.key !== 'integrity' && (
                <ul className="-mt-1 space-y-0.5 px-4 pb-3 pl-[42px]">
                  {cardWarnings.map((w) => (
                    <li key={w} className="flex items-start gap-1.5 text-xs text-hold-ink">
                      <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                      {w}
                    </li>
                  ))}
                </ul>
              )}
              {expanded && s.status !== 'running' && (
                <div id={bodyId} className="animate-fade-up border-t border-ink-100 px-4 py-4 sm:px-5">
                  <ErrorBoundary title="Could not render this stage">
                    <StageBody stage={s} ctx={ctx} error={error} />
                  </ErrorBoundary>
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function runningHint(key: StageKey, cls?: DocumentClass | null): string {
  switch (key) {
    case 'intake':
      return 'Hashing the file and counting pages…';
    case 'doc_analysis':
      return 'Checking each page for a text layer…';
    case 'extraction':
      return cls === 'scanned' ? 'Reading the page images with the model (vision)… usually 5–8 s' : 'Reading the document with the model… usually 4–7 s';
    case 'integrity':
      return 'Normalising amounts and dates, checking arithmetic…';
    case 'matching':
      return 'Looking up the vendor master, purchase orders and ledger…';
    case 'rules':
      return 'Evaluating policy rules R1–R10…';
    case 'decision':
      return 'Aggregating rule results…';
    default:
      return '';
  }
}
