import { forwardRef, useState } from 'react';
import { Check, ChevronDown, CircleX, Copy, Mail, TriangleAlert } from 'lucide-react';
import { api, errorMessage } from '../../lib/api';
import { amount, cx } from '../../lib/format';
import type { Booking, Decision, DecisionOutput, OverrideRequest, RunSummary, StageRecord } from '../../types';
import { ConfirmDialog } from '../ConfirmDialog';
import { useToast } from '../Toast';
import { Button, ConfidenceBar, DecisionIcon, Mono, OWNER_LABEL, SectionLabel } from '../ui';

const TONE = {
  APPROVE: { band: 'bg-approve', border: 'border-approve-line', soft: 'bg-approve-soft', word: 'text-approve', sub: 'Ready to book and pay.' },
  HOLD: { band: 'bg-hold', border: 'border-hold-line', soft: 'bg-hold-soft', word: 'text-hold', sub:'A person needs to act before this can be paid.' },
  REJECT: { band: 'bg-reject', border: 'border-reject-line', soft: 'bg-reject-soft', word: 'text-reject', sub:'Do not pay this invoice.' },
} as const;

const WORD: Record<Decision, string> = { APPROVE: 'Approved', HOLD: 'On hold', REJECT: 'Rejected' };
const OVERRIDE_SUB = { APPROVE: 'Approved by a reviewer. Ready to book and pay.', REJECT: 'Rejected by a reviewer. Do not pay this invoice.' } as const;

interface Props {
  decision: DecisionOutput | null;
  summary: Partial<RunSummary>;
  status: string;
  error: string | null;
  stages: StageRecord[];
  onOverridden: (summary: RunSummary) => void;
}

export const DecisionBanner = forwardRef<HTMLDivElement, Props>(function DecisionBanner({ decision, summary, status, error, stages, onOverridden }, ref) {
  if (status === 'failed' && !decision) {
    const failed = stages.find((s) => s.status === 'failed');
    return (
      <div ref={ref} className="scroll-mt-20 rounded-xl border border-reject-line bg-white p-5 shadow-card" role="status">
        <div className="flex items-start gap-3">
          <CircleX className="mt-0.5 h-6 w-6 shrink-0 text-reject" aria-hidden />
          <div>
            <p className="text-lg font-semibold text-ink-950">Run failed{failed ? ` at ${failed.name}` : ''}</p>
            <p className="mt-1 text-sm text-ink-600">{error ?? failed?.summary ?? 'The pipeline stopped before reaching a decision.'}</p>
            <p className="mt-2 text-[13px] text-ink-500">No decision was made, so nothing was written to the ledger. Fix the input and run it again.</p>
          </div>
        </div>
      </div>
    );
  }

  if (!decision) {
    return (
      <div ref={ref} className="scroll-mt-20 flex min-h-[132px] items-center justify-center rounded-xl border border-dashed border-ink-300 bg-white/60 px-6 text-center" aria-live="polite">
        <div>
          <p className="text-sm font-semibold text-ink-700">Decision pending</p>
          <p className="mt-1 text-[13px] text-ink-500">Appears here when all seven stages have finished: approve, hold or reject, with the reasons.</p>
        </div>
      </div>
    );
  }

  const over = summary.override_decision ?? null;
  const final = over ?? decision.decision;
  const t = TONE[final];
  const pt = TONE[decision.decision]; // reason chips keep the pipeline's colour
  const booking: Booking | null = over === 'APPROVE' ? summary.override_booking ?? null : decision.decision === 'APPROVE' ? decision.booking : null;
  const cur = booking?.currency ?? decision.booking?.currency ?? summary.currency ?? null;
  const canOverride = status === 'completed' && decision.decision === 'HOLD' && !over && !!summary.id;
  return (
    <div ref={ref} className={cx('scroll-mt-20 overflow-hidden rounded-xl border bg-white shadow-lift animate-fade-up', t.border)} role="status" aria-live="polite">
      <div className={cx('h-1.5', t.band)} aria-hidden />
      <div className={cx('flex flex-wrap items-center justify-between gap-4 px-6 py-5', t.soft)}>
        <div className="flex items-center gap-4">
          <DecisionIcon decision={final} className="h-10 w-10" />
          <div>
            <p className={cx('text-[28px] font-bold leading-none tracking-tight', t.word)}>{final}</p>
            <p className="mt-1.5 text-sm font-medium text-ink-900">{over ? OVERRIDE_SUB[over] : t.sub}</p>
            {over && (
              <p className="mt-1 text-xs text-ink-500">
                Pipeline said: {WORD[decision.decision]}
                {decision.reasons.length > 0 && ` (${decision.reasons.map((r) => r.code).join(', ')})`}
              </p>
            )}
          </div>
        </div>
        <div className="text-right">
          <p className="text-xs text-ink-500">Invoice</p>
          <p className="text-sm font-semibold text-ink-950">
            {summary.invoice_number ? <Mono className="text-sm">{summary.invoice_number}</Mono> : <span className="italic text-ink-500">no number</span>}
            <span className="mx-1.5 text-ink-300">·</span>
            <span className="tabular">{cur ? `${cur} ` : ''}{amount(summary.gross_total ?? decision.booking?.gross_amount ?? null)}</span>
          </p>
          <p className="mt-0.5 text-xs text-ink-500">{summary.vendor_name ?? '—'}</p>
          <div className="mt-2 flex items-center justify-end gap-2 text-xs text-ink-500">
            Extraction confidence <ConfidenceBar value={decision.confidence} width="w-20" />
          </div>
        </div>
      </div>

      {over && (
        <div className="border-b border-ink-100 px-6 py-3.5">
          <p className="text-[13px] font-semibold text-ink-900">
            Overridden by {summary.override_by}
            {summary.override_at && <span className="ml-1.5 font-normal text-ink-500">{new Date(summary.override_at).toLocaleString()}</span>}
          </p>
          <p className="mt-0.5 whitespace-pre-wrap text-[13.5px] leading-relaxed text-ink-700">{summary.override_note}</p>
        </div>
      )}

      <div className="grid gap-6 px-6 py-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          {/* On HOLD/REJECT the explanation only repeats the reasons word for word. */}
          {decision.decision === 'APPROVE' && (
            <div>
              <SectionLabel>Explanation</SectionLabel>
              <p className="text-[14.5px] leading-relaxed text-ink-900">{decision.explanation}</p>
            </div>
          )}
          {decision.reasons.length > 0 && (
            <div>
              <SectionLabel>Reasons</SectionLabel>
              <ul className="space-y-2">
                {decision.reasons.map((r) => (
                  <li key={r.code + r.text} className="flex items-start gap-2.5">
                    <span className={cx('mt-px inline-flex h-5 shrink-0 items-center rounded px-1.5 font-mono text-[11px] font-semibold', pt.soft, pt.word)}>{r.code}</span>
                    <span className="text-[13.5px] leading-snug text-ink-800">{r.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {decision.warnings.length > 0 && (
            <div>
              <SectionLabel>Warnings</SectionLabel>
              <ul className="space-y-1">
                {decision.warnings.map((w) => (
                  <li key={w} className="flex items-start gap-1.5 text-[13px] text-ink-600">
                    <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-hold" aria-hidden />
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="space-y-4">
          {/* Once a reviewer has decided, the pipeline's next action and draft email are spent. */}
          {!over && (
            <div className="rounded-lg border border-ink-200 p-4">
              <div className="mb-2 flex items-center justify-between gap-2">
                <SectionLabel className="mb-0">Next action</SectionLabel>
                <span className={cx('inline-flex h-6 items-center rounded-full border px-2.5 text-xs font-semibold', decision.next_action.owner === 'none' ? 'border-approve-line bg-approve-soft text-approve-ink' : 'border-ink-900 bg-ink-900 text-white')}>
                  {OWNER_LABEL[decision.next_action.owner] ?? decision.next_action.owner}
                </span>
              </div>
              <p className="text-[13.5px] leading-relaxed text-ink-900">{decision.next_action.text}</p>
              {canOverride && <OverrideActions runId={summary.id!} onDone={onOverridden} />}
            </div>
          )}

          {booking && (
            <div className="rounded-lg border border-approve-line bg-approve-soft/50 p-4">
              <SectionLabel>Booking</SectionLabel>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-[13px]">
                <div>
                  <dt className="text-xs text-ink-500">Purchase order</dt>
                  <dd className="mt-0.5 font-mono font-semibold text-ink-950">{booking.po_number ?? '—'}</dd>
                </div>
                <div>
                  <dt className="text-xs text-ink-500">Remaining on PO after</dt>
                  <dd className="mt-0.5 font-semibold tabular text-ink-950">
                    {booking.po_remaining_after == null ? '—' : `${cur ?? ''} ${amount(booking.po_remaining_after)}`}
                    {booking.po_remaining_after != null && booking.po_remaining_after <= 0.005 && (
                      <span className="ml-1.5 text-xs font-medium text-ink-500">{booking.po_remaining_after < -0.005 ? '(over the PO)' : '(fully consumed)'}</span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-ink-500">Net amount</dt>
                  <dd className="mt-0.5 tabular text-ink-900">{cur} {amount(booking.net_amount)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-ink-500">Gross amount</dt>
                  <dd className="mt-0.5 tabular text-ink-900">{cur} {amount(booking.gross_amount)}</dd>
                </div>
              </dl>
            </div>
          )}

          {!over && decision.draft_email && <DraftEmail email={decision.draft_email} />}
        </div>
      </div>
    </div>
  );
});

const NOTE_MIN = 10;
const NOTE_MAX = 500;

/** "Approve anyway" / "Reject" on a HOLD: one reviewer override, recorded next to the pipeline decision. */
function OverrideActions({ runId, onDone }: { runId: string; onDone: (summary: RunSummary) => void }) {
  const [choice, setChoice] = useState<OverrideRequest['decision'] | null>(null);
  const [note, setNote] = useState('');
  const [reviewer, setReviewer] = useState('AP reviewer');
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const len = note.trim().length;
  const submit = async () => {
    if (!choice) return;
    setBusy(true);
    try {
      const summary = await api.overrideRun(runId, { decision: choice, note: note.trim(), reviewer: reviewer.trim() || 'AP reviewer' });
      setChoice(null);
      onDone(summary);
      toast.success(choice === 'APPROVE' ? 'Approved by reviewer' : 'Rejected by reviewer', 'The ledger has been updated.');
    } catch (err) {
      toast.error('Could not record the override', errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-ink-100 pt-3">
        <span className="mr-auto text-xs text-ink-500">Reviewed it yourself?</span>
        <Button size="sm" variant="secondary" onClick={() => setChoice('APPROVE')}>
          Approve anyway
        </Button>
        <Button size="sm" variant="secondary" onClick={() => setChoice('REJECT')}>
          Reject
        </Button>
      </div>
      <ConfirmDialog
        open={choice !== null}
        title={choice === 'APPROVE' ? 'Approve this invoice anyway?' : 'Reject this invoice?'}
        confirmLabel={choice === 'APPROVE' ? 'Approve' : 'Reject'}
        tone={choice === 'REJECT' ? 'danger' : 'primary'}
        busy={busy}
        confirmDisabled={len < NOTE_MIN || len > NOTE_MAX}
        onConfirm={() => void submit()}
        onClose={() => setChoice(null)}
      >
        <p>
          {choice === 'APPROVE'
            ? 'It will be booked to its PO and count toward billing and duplicate checks.'
            : 'It will be marked rejected in the ledger and left out of billing and duplicate checks.'}{' '}
          The pipeline decision stays on record. A run can be overridden once.
        </p>
        <label className="mt-4 block">
          <span className="text-xs font-medium text-ink-700">Note</span>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            maxLength={NOTE_MAX}
            placeholder="Why you are overriding, e.g. the requester confirmed the PO increase."
            className="mt-1 block w-full rounded-lg border border-ink-200 px-3 py-2 text-[13px] text-ink-900 placeholder:text-ink-400 focus:border-ink-400 focus:outline-none"
          />
          <span className={cx('mt-1 block text-[11px]', len > 0 && len < NOTE_MIN ? 'text-hold-ink' : 'text-ink-400')}>
            {len < NOTE_MIN ? `At least ${NOTE_MIN} characters (${len} so far).` : `${len} / ${NOTE_MAX}`}
          </span>
        </label>
        <label className="mt-3 block">
          <span className="text-xs font-medium text-ink-700">Reviewer</span>
          <input
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
            maxLength={80}
            className="mt-1 block h-9 w-full rounded-lg border border-ink-200 px-3 text-[13px] text-ink-900 focus:border-ink-400 focus:outline-none"
          />
        </label>
      </ConfirmDialog>
    </>
  );
}

function DraftEmail({ email }: { email: NonNullable<DecisionOutput['draft_email']> }) {
  const [open, setOpen] = useState(true);
  const [copied, setCopied] = useState(false);
  const toast = useToast();
  const copy = async () => {
    const text = `To: ${email.to}\nSubject: ${email.subject}\n\n${email.body}`;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard API can be blocked (non-secure origin); fall back to a hidden textarea.
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      ta.remove();
      if (!ok) {
        toast.error('Could not copy', 'Select the text and copy it manually.');
        return;
      }
    }
    setCopied(true);
    toast.success('Draft email copied', `To ${email.to}`);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="rounded-lg border border-ink-200">
      <div className="flex items-center justify-between gap-2 px-4 py-2.5">
        <button type="button" onClick={() => setOpen((v) => !v)} className="flex min-w-0 items-center gap-2 text-left" aria-expanded={open}>
          <Mail className="h-4 w-4 shrink-0 text-ink-500" aria-hidden />
          <span className="min-w-0">
            <span className="block text-[13px] font-semibold text-ink-900">Draft email</span>
            <span className="block truncate text-xs text-ink-500">to {email.to}</span>
          </span>
          <ChevronDown className={cx('h-4 w-4 shrink-0 text-ink-400 transition-transform', open && 'rotate-180')} aria-hidden />
        </button>
        <Button size="sm" variant="secondary" onClick={copy} icon={copied ? <Check className="h-3.5 w-3.5 text-approve" /> : <Copy className="h-3.5 w-3.5" />}>
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
      {open && (
        <div className="border-t border-ink-100 px-4 py-3">
          <p className="text-xs text-ink-500">Subject</p>
          <p className="mb-2.5 text-[13px] font-medium text-ink-900">{email.subject}</p>
          <pre className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-ink-800">{email.body}</pre>
          <p className="mt-3 text-[11px] text-ink-400">Drafts only. Nothing is sent automatically.</p>
        </div>
      )}
    </div>
  );
}
