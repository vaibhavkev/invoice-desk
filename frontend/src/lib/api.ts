import type {
  ApiError,
  CreateRunResponse,
  Decision,
  Health,
  LedgerRow,
  OverrideRequest,
  PolicySettings,
  PurchaseOrder,
  RunDetail,
  RunList,
  RunSummary,
  Sample,
  Stats,
  Vendor,
} from '../types';

/** Same origin in production (FastAPI serves dist); Vite proxies /api in dev. */
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

export class ApiRequestError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiRequestError';
    this.status = status;
    this.code = code;
  }
}

function isApiError(x: unknown): x is ApiError {
  return typeof x === 'object' && x !== null && 'error' in x && typeof (x as ApiError).error?.message === 'string';
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, init);
  } catch {
    throw new ApiRequestError(0, 'network', 'Cannot reach the API. Is the backend (or `npm run mock`) running on port 8000?');
  }
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON error body */
    }
    if (isApiError(body)) throw new ApiRequestError(res.status, body.error.code, body.error.message);
    // FastAPI default validation errors arrive as { detail }.
    const detail = typeof body === 'object' && body && 'detail' in body ? JSON.stringify((body as { detail: unknown }).detail) : res.statusText;
    throw new ApiRequestError(res.status, `http_${res.status}`, detail || `Request failed (${res.status})`);
  }
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export interface RunQuery {
  limit?: number;
  offset?: number;
  decision?: Decision | '';
  q?: string;
}

export const api = {
  health: () => request<Health & { mock?: boolean }>('/health'),
  samples: () => request<Sample[]>('/api/samples'),
  createRunFromSample: (sample_id: string, use_cache = false) => request<CreateRunResponse>('/api/runs', json({ sample_id, use_cache })),
  createRunFromFile: (file: File) => {
    const fd = new FormData();
    fd.append('file', file, file.name);
    return request<CreateRunResponse>('/api/runs', { method: 'POST', body: fd });
  },
  listRuns: (q: RunQuery = {}) => {
    const p = new URLSearchParams();
    p.set('limit', String(q.limit ?? 50));
    p.set('offset', String(q.offset ?? 0));
    if (q.decision) p.set('decision', q.decision);
    if (q.q) p.set('q', q.q);
    return request<RunList>(`/api/runs?${p.toString()}`);
  },
  getRun: (id: string) => request<RunDetail>(`/api/runs/${encodeURIComponent(id)}`),
  overrideRun: (id: string, body: OverrideRequest) => request<RunSummary>(`/api/runs/${encodeURIComponent(id)}/override`, json(body)),
  stats: () => request<Stats>('/api/stats'),
  policy: () => request<PolicySettings>('/api/policy'),
  vendors: () => request<Vendor[]>('/api/reference/vendors'),
  pos: () => request<PurchaseOrder[]>('/api/reference/pos'),
  ledger: () => request<LedgerRow[]>('/api/reference/ledger'),
  reset: (clear_runs: boolean) => request<{ ok: boolean }>('/api/admin/reset', json({ clear_runs })),
};

export const runFileUrl = (id: string) => `${BASE}/api/runs/${encodeURIComponent(id)}/file`;
export const runEventsUrl = (id: string) => `${BASE}/api/runs/${encodeURIComponent(id)}/events`;
export const sampleFileUrl = (s: Pick<Sample, 'id' | 'url'>) => `${BASE}${s.url || `/api/samples/${encodeURIComponent(s.id)}/file`}`;

export function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}
