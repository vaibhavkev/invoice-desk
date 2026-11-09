import { useCallback, useEffect, useReducer } from 'react';
import { api, ApiRequestError, errorMessage } from '../lib/api';
import { subscribeRun, type ConnectionState } from '../lib/sse';
import { blankStages, normaliseStages } from '../lib/stages';
import type { DecisionOutput, RunDetail, RunEvent, RunStatus, RunSummary, StageRecord } from '../types';

export interface RunState {
  runId: string | null;
  summary: Partial<RunSummary>;
  stages: StageRecord[];
  decision: DecisionOutput | null;
  status: RunStatus | 'loading';
  error: string | null;
  notFound: boolean;
  connection: ConnectionState | 'idle';
  /** True once the run finished while we were watching it live (not a replay). */
  finishedLive: boolean;
  /** True once anything (detail or an event) has arrived. */
  loaded: boolean;
}

type Action =
  | { type: 'reset'; runId: string | null; hint?: Partial<RunSummary> }
  | { type: 'detail'; detail: RunDetail }
  | { type: 'event'; ev: RunEvent }
  | { type: 'summary'; summary: RunSummary }
  | { type: 'connection'; state: ConnectionState }
  | { type: 'not_found' }
  | { type: 'load_error'; message: string };

const RANK: Record<StageRecord['status'], number> = { pending: 0, running: 1, done: 2, warn: 2, failed: 2, skipped: 2 };
const TERMINAL: ReadonlySet<string> = new Set(['completed', 'failed']);

function initial(runId: string | null, hint?: Partial<RunSummary>): RunState {
  return {
    runId,
    summary: { ...(hint ?? {}), id: runId ?? undefined },
    stages: blankStages(),
    decision: null,
    status: 'loading',
    error: null,
    notFound: false,
    connection: 'idle',
    finishedLive: false,
    loaded: false,
  };
}

/** Replace a stage only if the incoming record is at least as far along. */
function mergeStage(stages: StageRecord[], next: StageRecord): StageRecord[] {
  return stages.map((s) => {
    if (s.key !== next.key) return s;
    if (RANK[next.status] < RANK[s.status]) return s;
    return { ...s, ...next, warnings: next.warnings ?? [] };
  });
}

function skipRemaining(stages: StageRecord[]): StageRecord[] {
  return stages.map((s) => (s.status === 'pending' || s.status === 'running' ? { ...s, status: 'skipped' } : s));
}

function decisionFrom(stages: StageRecord[]): DecisionOutput | null {
  const d = stages.find((s) => s.key === 'decision');
  return d && (d.status === 'done' || d.status === 'warn') && d.output ? (d.output as DecisionOutput) : null;
}

function reducer(state: RunState, action: Action): RunState {
  switch (action.type) {
    case 'reset':
      return initial(action.runId, action.hint);
    case 'not_found':
      return { ...state, notFound: true, status: 'failed', error: 'Run not found', loaded: true };
    case 'load_error':
      return { ...state, error: action.message, loaded: true };
    case 'connection':
      return { ...state, connection: action.state };
    case 'summary':
      return action.summary.id === state.runId ? { ...state, summary: { ...state.summary, ...action.summary } } : state;
    case 'detail': {
      const d = action.detail;
      if (d.id !== state.runId) return state;
      let stages = normaliseStages(d.stages);
      // Keep anything SSE already advanced further than this snapshot.
      for (const s of state.stages) if (RANK[s.status] > RANK[stages.find((x) => x.key === s.key)!.status]) stages = mergeStage(stages, s);
      const { stages: _omit, ...summary } = d;
      void _omit;
      const keepTerminal = TERMINAL.has(state.status) && !TERMINAL.has(d.status);
      const status = keepTerminal ? state.status : d.status;
      if (status === 'failed') stages = skipRemaining(stages);
      return {
        ...state,
        summary: keepTerminal ? { ...summary, ...state.summary } : { ...state.summary, ...summary },
        stages,
        decision: state.decision ?? decisionFrom(stages),
        status,
        error: d.error ?? state.error,
        loaded: true,
      };
    }
    case 'event': {
      const ev = action.ev;
      if (ev.data.run_id !== state.runId) return state;
      switch (ev.type) {
        case 'run.started':
          return {
            ...state,
            loaded: true,
            status: TERMINAL.has(state.status) ? state.status : 'running',
            summary: { ...state.summary, created_at: ev.data.created_at, filename: ev.data.filename, sample_id: ev.data.sample_id },
          };
        case 'stage.started':
        case 'stage.completed': {
          const stages = mergeStage(state.stages, ev.data.stage);
          const decision = ev.data.stage.key === 'decision' && ev.type === 'stage.completed' ? (ev.data.stage.output as DecisionOutput | null) : state.decision;
          const docClass =
            ev.data.stage.key === 'doc_analysis' && ev.data.stage.output && 'document_class' in ev.data.stage.output
              ? ev.data.stage.output.document_class
              : state.summary.document_class;
          return {
            ...state,
            loaded: true,
            stages,
            decision: decision ?? state.decision,
            status: TERMINAL.has(state.status) ? state.status : 'running',
            summary: { ...state.summary, current_stage: ev.data.stage.key, document_class: docClass ?? null },
          };
        }
        case 'stage.failed': {
          const stages = mergeStage(state.stages, ev.data.stage).map((s) => (s.status === 'pending' ? { ...s, status: 'skipped' as const } : s));
          return { ...state, loaded: true, stages, error: ev.data.error };
        }
        case 'run.completed': {
          const stages = state.stages.map((s) =>
            s.key === 'decision' && !s.output ? { ...s, status: s.status === 'pending' || s.status === 'running' ? ('done' as const) : s.status, output: ev.data.decision } : s,
          );
          return {
            ...state,
            loaded: true,
            stages,
            decision: ev.data.decision,
            summary: { ...state.summary, ...ev.data.summary },
            status: 'completed',
            finishedLive: state.connection === 'open' || state.finishedLive || state.status === 'running',
          };
        }
        case 'run.failed':
          return {
            ...state,
            loaded: true,
            stages: skipRemaining(state.stages),
            summary: { ...state.summary, ...ev.data.summary },
            status: 'failed',
            error: ev.data.error,
            finishedLive: true,
          };
        case 'override':
          return { ...state, summary: { ...state.summary, ...ev.data.summary } };
        default:
          return state;
      }
    }
    default:
      return state;
  }
}

/**
 * Loads a run and keeps it live. Finished runs render from `GET /api/runs/{id}`
 * with no SSE; queued/running runs subscribe to the event stream. `fresh` (a run
 * we just created) subscribes immediately in parallel with the GET.
 */
export function useRun(runId: string | null, opts: { fresh?: boolean; hint?: Partial<RunSummary> } = {}): RunState & { applySummary: (s: RunSummary) => void } {
  const [state, dispatch] = useReducer(reducer, null, () => initial(runId, opts.hint));
  const { fresh } = opts;

  useEffect(() => {
    dispatch({ type: 'reset', runId, hint: opts.hint });
    if (!runId) return;
    let cancelled = false;
    let unsub: (() => void) | null = null;
    const subscribe = () => {
      if (unsub || cancelled) return;
      unsub = subscribeRun(runId, {
        onEvent: (ev) => !cancelled && dispatch({ type: 'event', ev }),
        onConnection: (s) => !cancelled && dispatch({ type: 'connection', state: s }),
        onFatal: () => !cancelled && dispatch({ type: 'not_found' }),
      });
    };
    if (fresh) subscribe();
    api
      .getRun(runId)
      .then((detail) => {
        if (cancelled) return;
        dispatch({ type: 'detail', detail });
        if (!TERMINAL.has(detail.status)) subscribe();
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiRequestError && err.status === 404) dispatch({ type: 'not_found' });
        else {
          dispatch({ type: 'load_error', message: errorMessage(err) });
          subscribe(); // the stream may still work if only the GET failed
        }
      });
    return () => {
      cancelled = true;
      unsub?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, fresh]);

  const applySummary = useCallback((summary: RunSummary) => dispatch({ type: 'summary', summary }), []);
  return { ...state, applySummary };
}
