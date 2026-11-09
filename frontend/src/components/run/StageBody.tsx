import { useState } from 'react';
import { CircleX } from 'lucide-react';
import { cx } from '../../lib/format';
import type {
  DocAnalysisOutput,
  ExtractionOutput,
  IntakeOutput,
  IntegrityOutput,
  MatchingOutput,
  RulesOutput,
  StageRecord,
} from '../../types';
import { KV, NoData, SectionLabel } from '../ui';
import { ExtractionBody } from './ExtractionBody';
import { IntegrityBody } from './IntegrityBody';
import { MatchingBody } from './MatchingBody';
import { RulesBody } from './RulesBody';

export interface StageCtx {
  stages: StageRecord[];
  integrity: StageRecord | undefined;
}

export function StageBody({ stage, ctx, error }: { stage: StageRecord; ctx: StageCtx; error?: string | null }) {
  // A failed stage's output has no typed payload, so only the failure note is safe to show.
  if (stage.status === 'failed') {
    const message = error || stage.summary || 'This stage failed.';
    return (
      <div className="flex items-start gap-2 rounded-lg border border-reject-line bg-reject-soft px-3 py-2.5 text-sm text-reject-ink">
        <CircleX className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <div>
          <p>{message}</p>
          {stage.summary && stage.summary !== message && <p className="mt-0.5 text-xs">{stage.summary}</p>}
        </div>
      </div>
    );
  }

  if (!stage.output) return <NoData />;

  const normalised = (ctx.integrity?.output as IntegrityOutput | null | undefined)?.normalised ?? null;
  switch (stage.key) {
    case 'intake':
      return <IntakeBody o={stage.output as IntakeOutput} />;
    case 'doc_analysis':
      return <DocAnalysisBody o={stage.output as DocAnalysisOutput} />;
    case 'extraction':
      return <ExtractionBody o={stage.output as ExtractionOutput} />;
    case 'integrity':
      return <IntegrityBody o={stage.output as IntegrityOutput} extraction={(ctx.stages.find((s) => s.key === 'extraction')?.output as ExtractionOutput | null | undefined)?.extraction ?? null} />;
    case 'matching':
      return <MatchingBody o={stage.output as MatchingOutput} normalised={normalised} />;
    case 'rules':
      return <RulesBody o={stage.output as RulesOutput} />;
    default:
      return null;
  }
}

function IntakeBody({ o }: { o: IntakeOutput }) {
  return (
    <dl>
      <KV label="SHA-256" mono>
        <span title={o.sha256}>{o.sha256}</span>
      </KV>
    </dl>
  );
}

const CLASS_NOTE = {
  digital: 'Text layer on every page; the text is passed to extraction alongside the PDF.',
  scanned: 'No usable text layer; the model reads the page images directly (vision).',
  mixed: 'Some pages have text, some are images; both are passed to extraction.',
} as const;

function DocAnalysisBody({ o }: { o: DocAnalysisOutput }) {
  const [showText, setShowText] = useState(false);
  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-500">{CLASS_NOTE[o.document_class] ?? CLASS_NOTE.digital}</p>
      <div>
        <SectionLabel>Pages</SectionLabel>
        <div className="flex flex-wrap gap-2">
          {(o.pages ?? []).map((p) => (
            <span key={p.page} className="inline-flex h-7 items-center gap-2 rounded-md border border-ink-200 bg-white px-2.5 text-xs">
              <span className={cx('h-1.5 w-1.5 rounded-full', p.has_text_layer ? 'bg-ink-700' : 'bg-ink-300')} aria-hidden />
              <span className="font-medium text-ink-900">Page {p.page}</span>
              <span className="tabular text-ink-500">{p.chars.toLocaleString('en-US')} chars</span>
              {!p.has_text_layer && <span className="text-ink-400">· image</span>}
            </span>
          ))}
        </div>
      </div>
      {o.text_layer ? (
        <div>
          <button type="button" className="text-[13px] font-medium text-ink-700 underline decoration-ink-300 underline-offset-2 hover:decoration-ink-700" onClick={() => setShowText((v) => !v)} aria-expanded={showText}>
            {showText ? 'Hide text layer' : 'Show extracted text layer'}
          </button>
          {showText && (
            <pre className="scroll-thin mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-lg border border-ink-200 bg-ink-50 p-3 font-mono text-[12px] leading-relaxed text-ink-700">{o.text_layer}</pre>
          )}
        </div>
      ) : (
        <p className="text-[13px] text-ink-500">No text layer to show.</p>
      )}
    </div>
  );
}
