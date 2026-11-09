import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { SearchX } from 'lucide-react';
import { api, errorMessage, runFileUrl, sampleFileUrl } from '../lib/api';
import { useResource } from '../hooks/useResource';
import { useRun } from '../hooks/useRun';
import { invalidateReference } from '../hooks/useReference';
import { blankStages } from '../lib/stages';
import type { RunSummary, Sample } from '../types';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { useToast } from '../components/Toast';
import { Card, EmptyState, buttonClass } from '../components/ui';
import { DropZone, SampleList } from '../components/run/SamplePanel';
import { PdfPreview } from '../components/run/PdfPreview';
import { RunHeader } from '../components/run/RunHeader';
import { Timeline } from '../components/run/Timeline';
import { DecisionBanner } from '../components/run/DecisionBanner';

interface NavState {
  fresh?: boolean;
  hint?: Partial<RunSummary>;
}

export function RunPage() {
  const { id } = useParams();
  const runId = id ?? null;
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const nav = (location.state ?? null) as NavState | null;

  const samples = useResource(() => api.samples(), 'samples', { onError: (m) => toast.error('Could not load samples', m) });
  const run = useRun(runId, { fresh: !!nav?.fresh, hint: nav?.hint });
  const [startingId, setStartingId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const bannerRef = useRef<HTMLDivElement>(null);

  const start = async (src: { sample: Sample } | { file: File }) => {
    const isSample = 'sample' in src;
    if (isSample) setStartingId(src.sample.id);
    else setUploading(true);
    try {
      const res = isSample ? await api.createRunFromSample(src.sample.id) : await api.createRunFromFile(src.file);
      const hint: Partial<RunSummary> = isSample
        ? { filename: src.sample.file.split('/').pop() ?? src.sample.id, sample_id: src.sample.id, status: 'queued' }
        : { filename: src.file.name, sample_id: null, status: 'queued' };
      navigate(`/runs/${res.run_id}`, { state: { fresh: true, hint } satisfies NavState });
    } catch (err) {
      toast.error('Could not start the run', errorMessage(err));
    } finally {
      setStartingId(null);
      setUploading(false);
    }
  };

  // When a run finishes while we watch it, bring the decision into view and
  // drop cached reference data (PO balances changed).
  useEffect(() => {
    if (!run.finishedLive) return;
    invalidateReference();
    const t = setTimeout(() => bannerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 150);
    return () => clearTimeout(t);
  }, [run.finishedLive]);

  useEffect(() => {
    if (run.finishedLive && run.status === 'failed') toast.error('Run failed', run.error ?? undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.finishedLive, run.status]);

  const activeSample = samples.data?.find((s) => s.id === run.summary.sample_id) ?? null;
  // Only preview once intake has accepted the file as a PDF; pointing the iframe at a
  // rejected file (e.g. a JPG served as octet-stream) would make the browser download it.
  const intake = run.stages[0];
  const intakeFailed = intake?.status === 'failed';
  const intakePassed = intake?.status === 'done' || intake?.status === 'warn';
  const previewSrc = runId && intakePassed ? runFileUrl(runId) : null;
  const previewName = run.summary.filename ?? (activeSample ? activeSample.file.split('/').pop() : null);

  return (
    <div className="grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[320px_minmax(0,1fr)]">
      <aside className="space-y-4" aria-label="Choose an invoice">
        <Card className="p-4">
          <DropZone busy={uploading} onFile={(file) => void start({ file })} onReject={(m) => toast.error('File not accepted', m)} />
        </Card>
        <SampleList
          samples={samples.data}
          loading={samples.loading}
          error={samples.error}
          activeSampleId={runId ? run.summary.sample_id ?? null : null}
          startingId={startingId}
          onPick={(s) => void start({ sample: s })}
        />
        <PdfPreview src={runId ? previewSrc : activeSample ? sampleFileUrl(activeSample) : null} name={previewName} note={intakeFailed ? 'No preview: the file was rejected at intake.' : undefined} />
      </aside>

      <div className="min-w-0 space-y-4">
        {!runId ? (
          <IdleView />
        ) : run.notFound ? (
          <Card>
            <EmptyState
              icon={<SearchX className="h-5 w-5" />}
              title="Run not found"
              body={`No run with id ${runId}. It may have been cleared by a demo reset.`}
              action={
                <Link to="/dashboard" className={buttonClass('secondary')}>
                  Go to dashboard
                </Link>
              }
            />
          </Card>
        ) : (
          <ErrorBoundary key={runId} title="Could not render this run">
            <div className="space-y-4">
              <RunHeader run={run} />
              <Timeline
                stages={run.stages}
                documentClass={run.summary.document_class ?? null}
                error={run.error}
                onShowDecision={() => bannerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
              />
              <ErrorBoundary title="Could not render the decision">
                <DecisionBanner ref={bannerRef} decision={run.decision} summary={run.summary} status={run.status} error={run.error} stages={run.stages} onOverridden={run.applySummary} />
              </ErrorBoundary>
            </div>
          </ErrorBoundary>
        )}
      </div>
    </div>
  );
}

function IdleView() {
  return (
    <>
      <Card className="px-6 py-5">
        <h1 className="text-[19px] font-semibold tracking-tight text-ink-950">Process an invoice</h1>
        <p className="mt-1 max-w-2xl text-sm leading-relaxed text-ink-600">
          Pick a sample on the left or drop a vendor invoice PDF. Each of the seven stages below streams in as it runs, and the result is a decision you can act on: approve, hold or reject, with the
          reasons, the next step and who owns it.
        </p>
      </Card>
      <Timeline stages={blankStages()} ghost />
      <div className="rounded-xl border border-dashed border-ink-300 bg-white/60 px-6 py-6 text-center">
        <p className="text-sm font-semibold text-ink-700">Decision</p>
        <p className="mt-1 text-[13px] text-ink-500">The model only extracts. Ten deterministic rules decide, so the same invoice always gets the same answer.</p>
      </div>
    </>
  );
}
