import type { StageKey, StageRecord } from '../types';

export const STAGE_DEFS: ReadonlyArray<{ key: StageKey; name: string; blurb: string }> = [
  { key: 'intake', name: 'Intake', blurb: 'Hash, size and page count' },
  { key: 'doc_analysis', name: 'Document analysis', blurb: 'Text layer or scanned image' },
  { key: 'extraction', name: 'Extraction', blurb: 'LLM reads fields with confidence and evidence' },
  { key: 'integrity', name: 'Normalisation & integrity', blurb: 'Amounts, dates and required fields' },
  { key: 'matching', name: 'Vendor & PO matching', blurb: 'Vendor master, purchase orders and ledger' },
  { key: 'rules', name: 'Policy rules', blurb: 'Ten deterministic AP rules' },
  { key: 'decision', name: 'Decision', blurb: 'Approve, hold or reject with reasons' },
];

export function blankStages(): StageRecord[] {
  return STAGE_DEFS.map((d, i) => ({
    key: d.key,
    index: i + 1,
    name: d.name,
    status: 'pending',
    started_at: null,
    finished_at: null,
    duration_ms: null,
    summary: '',
    warnings: [],
    output: null,
  }));
}

/** Merge whatever the server sent onto the fixed seven-stage skeleton. */
export function normaliseStages(incoming: StageRecord[] | undefined | null): StageRecord[] {
  const base = blankStages();
  if (!incoming) return base;
  for (const s of incoming) {
    const i = base.findIndex((b) => b.key === s.key);
    if (i !== -1) base[i] = { ...base[i]!, ...s, warnings: s.warnings ?? [] };
  }
  return base;
}

export const isFinishedStage = (s: StageRecord) => s.status === 'done' || s.status === 'warn' || s.status === 'failed';
