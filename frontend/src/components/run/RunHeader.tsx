import { Download, ExternalLink, WifiOff } from 'lucide-react';
import { api, errorMessage, runFileUrl } from '../../lib/api';
import { clock, cx, duration } from '../../lib/format';
import { useNow } from '../../hooks/useNow';
import type { RunState } from '../../hooks/useRun';
import { Card, RunStatusChip, Skeleton } from '../ui';
import { useToast } from '../Toast';

/** Saves the full GET /api/runs/{id} response (stages, rule results, decision, override) for audit. */
async function downloadAudit(runId: string, invoiceNumber: string | null | undefined) {
  const detail = await api.getRun(runId);
  const name = (invoiceNumber || runId).replace(/[^\w.-]+/g, '_');
  const url = URL.createObjectURL(new Blob([JSON.stringify(detail, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `${name}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function RunHeader({ run }: { run: RunState }) {
  const toast = useToast();
  const s = run.summary;
  const live = run.status === 'running' || run.status === 'queued';
  const now = useNow(live, 200);
  const started = s.created_at ? Date.parse(s.created_at) : null;
  const elapsed = run.status === 'completed' || run.status === 'failed' ? s.duration_ms ?? null : started ? Math.max(0, now - started) : null;
  const current = run.stages.find((x) => x.status === 'running');
  const reconnecting = live && run.connection === 'reconnecting';

  return (
    <Card className="px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {s.filename ? <h1 className="truncate text-[17px] font-semibold tracking-tight text-ink-950">{s.filename}</h1> : <Skeleton className="h-5 w-64" />}
            {s.sample_id && <span className="rounded border border-ink-200 px-1.5 py-px font-mono text-[11px] text-ink-600">{s.sample_id}</span>}
          </div>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[13px] text-ink-500">
            {s.created_at && <span>started {clock(s.created_at)}</span>}
            {run.runId && (run.stages[0]?.status === 'done' || run.stages[0]?.status === 'warn') && (
              <>
                <span aria-hidden>·</span>
                <a href={runFileUrl(run.runId)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-ink-700 hover:text-ink-950">
                  Open PDF <ExternalLink className="h-3 w-3" aria-hidden />
                </a>
              </>
            )}
            {run.runId && !live && (
              <>
                <span aria-hidden>·</span>
                <button
                  type="button"
                  onClick={() => downloadAudit(run.runId!, s.invoice_number).catch((err) => toast.error('Could not download audit JSON', errorMessage(err)))}
                  className="inline-flex items-center gap-1 font-medium text-ink-700 hover:text-ink-950"
                >
                  Download audit JSON <Download className="h-3 w-3" aria-hidden />
                </button>
              </>
            )}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {reconnecting && (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-hold-ink" role="status">
              <WifiOff className="h-3.5 w-3.5" aria-hidden /> Reconnecting…
            </span>
          )}
          <div className="text-right">
            <p className="text-[11px] uppercase tracking-[0.06em] text-ink-400">{live ? (current ? current.name : 'Starting') : 'Total time'}</p>
            <p className={cx('font-mono text-sm tabular-nums', live ? 'text-running' : 'text-ink-900')}>{elapsed != null ? duration(elapsed) : '—'}</p>
          </div>
          <RunStatusChip status={run.status} decision={s.final_decision ?? s.decision ?? run.decision?.decision ?? null} />
        </div>
      </div>
    </Card>
  );
}
