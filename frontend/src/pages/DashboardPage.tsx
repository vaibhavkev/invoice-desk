import { useEffect, useMemo, useState, type KeyboardEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Inbox, RefreshCw, Search, X } from 'lucide-react';
import { api } from '../lib/api';
import { amount, clock, cx, duration, pct, relative } from '../lib/format';
import { useResource } from '../hooks/useResource';
import { useNow } from '../hooks/useNow';
import type { Decision, PurchaseOrder, RunSummary, Stats, Vendor } from '../types';
import { useToast } from '../components/Toast';
import { Button, Card, CardHeader, ConsumptionBar, DecisionChip, EmptyState, Mono, RunStatusChip, Skeleton, buttonClass } from '../components/ui';

const REFRESH_MS = 10_000;
type Filter = '' | Decision;

export function DashboardPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>('');
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);

  const onError = (m: string) => toast.error('Dashboard refresh failed', m);
  const stats = useResource(() => api.stats(), 'stats', { intervalMs: REFRESH_MS, onError });
  const runs = useResource(() => api.listRuns({ limit: 100, decision: filter, q: debounced }), `runs:${filter}:${debounced}`, { intervalMs: REFRESH_MS, onError });
  const pos = useResource(() => api.pos(), 'pos', { intervalMs: REFRESH_MS });
  const vendors = useResource(() => api.vendors(), 'vendors');
  const now = useNow(true, 15_000);

  const refreshAll = () => {
    void stats.refresh();
    void runs.refresh();
    void pos.refresh();
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-ink-950">Dashboard</h1>
          <p className="mt-0.5 text-sm text-ink-500">Every processed invoice with its decision. Refreshes every 10 seconds.</p>
        </div>
        <div className="flex items-center gap-3 text-xs text-ink-500">
          <span aria-live="polite">{runs.updatedAt ? `Updated ${relative(new Date(runs.updatedAt).toISOString(), now)}` : 'Loading…'}</span>
          <Button size="sm" variant="secondary" onClick={refreshAll} icon={<RefreshCw className={cx('h-3.5 w-3.5', (runs.loading || stats.loading) && 'animate-spin')} />}>
            Refresh
          </Button>
        </div>
      </div>

      <KpiRow stats={stats.data} loading={stats.loading && !stats.data} />

      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card className="min-w-0 overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-100 px-5 py-3.5">
            <div className="flex items-center gap-1 rounded-lg bg-ink-100 p-0.5" role="tablist" aria-label="Filter by decision">
              {([['', 'All'], ['APPROVE', 'Approved'], ['HOLD', 'On hold'], ['REJECT', 'Rejected']] as Array<[Filter, string]>).map(([v, label]) => {
                const count = !stats.data ? null : v === '' ? stats.data.runs : v === 'APPROVE' ? stats.data.approve : v === 'HOLD' ? stats.data.hold : stats.data.reject;
                const active = filter === v;
                return (
                  <button
                    key={v || 'all'}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => setFilter(v)}
                    className={cx('inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium transition-colors', active ? 'bg-white text-ink-950 shadow-card' : 'text-ink-600 hover:text-ink-900')}
                  >
                    {v && <span className={cx('h-1.5 w-1.5 rounded-full', v === 'APPROVE' ? 'bg-approve' : v === 'HOLD' ? 'bg-hold' : 'bg-reject')} aria-hidden />}
                    {label}
                    {count != null && <span className="tabular text-xs text-ink-400">{count}</span>}
                  </button>
                );
              })}
            </div>
            <label className="relative flex items-center">
              <span className="sr-only">Search runs</span>
              <Search className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-ink-400" aria-hidden />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search vendor, invoice no., PO, file"
                className="h-8 w-72 rounded-lg border border-ink-200 bg-white pl-8 pr-7 text-[13px] text-ink-900 placeholder:text-ink-400 focus:border-ink-400 focus:outline-none"
              />
              {query && (
                <button type="button" onClick={() => setQuery('')} className="absolute right-2 rounded p-0.5 text-ink-400 hover:text-ink-700" aria-label="Clear search">
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </label>
          </div>
          <RunsTable
            items={runs.data?.items ?? null}
            total={runs.data?.total ?? 0}
            loading={runs.loading && !runs.data}
            filtered={!!filter || !!debounced}
            now={now}
            onOpen={(id) => navigate(`/runs/${id}`)}
          />
        </Card>

        <PoPanel pos={pos.data} vendors={vendors.data} loading={pos.loading && !pos.data} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- KPI tiles
function Tile({ label, children, sub, className }: { label: string; children: React.ReactNode; sub?: React.ReactNode; className?: string }) {
  return (
    <Card className={cx('px-5 py-4', className)}>
      <p className="text-xs font-medium text-ink-500">{label}</p>
      <div className="mt-1.5 text-[28px] font-semibold leading-none tracking-tight text-ink-950 tabular">{children}</div>
      {sub && <p className="mt-2 text-xs text-ink-500">{sub}</p>}
    </Card>
  );
}

function KpiRow({ stats, loading }: { stats: Stats | null; loading: boolean }) {
  if (loading || !stats) {
    return (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {Array.from({ length: 4 }, (_, i) => (
          <Card key={i} className={cx('px-5 py-4', i === 1 && 'lg:col-span-2')}>
            <Skeleton className="h-3 w-20" />
            <Skeleton className="mt-3 h-7 w-16" />
            <Skeleton className="mt-3 h-3 w-24" />
          </Card>
        ))}
      </div>
    );
  }
  const decided = stats.approve + stats.hold + stats.reject;
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
      <Tile label="Invoices processed" sub={`${stats.last_24h} in the last 24 hours`}>
        {stats.runs}
      </Tile>
      <Card className="col-span-2 px-5 py-4">
        <p className="text-xs font-medium text-ink-500">Decisions</p>
        <div className="mt-1.5 flex items-baseline gap-5">
          {(
            [
              ['APPROVE', stats.approve, 'Approved', 'text-approve-ink'],
              ['HOLD', stats.hold, 'On hold', 'text-hold-ink'],
              ['REJECT', stats.reject, 'Rejected', 'text-reject-ink'],
            ] as const
          ).map(([k, n, label, cls]) => (
            <span key={k} className="flex items-baseline gap-1.5">
              <span className={cx('text-[28px] font-semibold leading-none tracking-tight tabular', cls)}>{n}</span>
              <span className="text-xs text-ink-500">{label}</span>
            </span>
          ))}
        </div>
        <DecisionSplit approve={stats.approve} hold={stats.hold} reject={stats.reject} />
        <p className="mt-1.5 text-xs text-ink-500">{decided === stats.runs ? `${decided} decided` : `${decided} decided · ${stats.runs - decided} failed or in progress`}</p>
      </Card>
      <Tile label="Auto-approval rate" sub="Approved without a person, of decided runs">
        {pct(stats.auto_approval_rate)}
      </Tile>
      <Tile label="Median processing time" sub="Upload to decision, all seven stages">
        {stats.median_duration_ms ? duration(stats.median_duration_ms) : '—'}
      </Tile>
    </div>
  );
}

/** Stacked part-to-whole bar, status colours with a 2px gap; labels above carry identity. */
function DecisionSplit({ approve, hold, reject }: { approve: number; hold: number; reject: number }) {
  const total = approve + hold + reject;
  if (!total) return <div className="mt-3 h-2 rounded-full bg-ink-100" />;
  const segs = [
    { n: approve, cls: 'bg-approve', label: 'Approved' },
    { n: hold, cls: 'bg-hold', label: 'On hold' },
    { n: reject, cls: 'bg-reject', label: 'Rejected' },
  ].filter((s) => s.n > 0);
  return (
    <div className="mt-3 flex h-2 gap-[2px]" role="img" aria-label={segs.map((s) => `${s.label} ${s.n}`).join(', ')}>
      {segs.map((s, i) => (
        <div
          key={s.label}
          className={cx('h-full', s.cls, i === 0 && 'rounded-l-full', i === segs.length - 1 && 'rounded-r-full')}
          style={{ width: `${(s.n / total) * 100}%` }}
          title={`${s.label}: ${s.n} of ${total} (${Math.round((s.n / total) * 100)}%)`}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- runs table
function RunsTable({ items, total, loading, filtered, now, onOpen }: { items: RunSummary[] | null; total: number; loading: boolean; filtered: boolean; now: number; onOpen: (id: string) => void }) {
  const onKey = (e: KeyboardEvent<HTMLTableRowElement>, id: string) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onOpen(id);
    }
  };
  if (!loading && items && items.length === 0) {
    return filtered ? (
      <EmptyState icon={<Search className="h-5 w-5" />} title="No runs match" body="Try another decision filter or search term." />
    ) : (
      <EmptyState
        icon={<Inbox className="h-5 w-5" />}
        title="No runs yet"
        body="Process a sample invoice and it will appear here with its decision."
        action={
          <Link to="/" className={buttonClass('primary')}>
            Process an invoice
          </Link>
        }
      />
    );
  }
  return (
    <div className="scroll-thin max-h-[640px] overflow-auto">
      <table className="table-base">
        <thead>
          <tr>
            <th>Time</th>
            <th>File</th>
            <th>Vendor</th>
            <th>Invoice no.</th>
            <th className="num">Net total</th>
            <th>PO</th>
            <th>Decision</th>
            <th className="num">Conf.</th>
            <th className="num">Duration</th>
          </tr>
        </thead>
        <tbody>
          {loading || !items
            ? Array.from({ length: 6 }, (_, i) => (
                <tr key={i}>
                  {Array.from({ length: 9 }, (_, j) => (
                    <td key={j}>
                      <Skeleton className="h-4 w-full" />
                    </td>
                  ))}
                </tr>
              ))
            : items.map((r) => (
                <tr
                  key={r.id}
                  tabIndex={0}
                  onClick={() => onOpen(r.id)}
                  onKeyDown={(e) => onKey(e, r.id)}
                  className="cursor-pointer transition-colors hover:bg-ink-50 focus-visible:bg-ink-50"
                  aria-label={`Open run ${r.filename}`}
                >
                  <td className="whitespace-nowrap text-ink-600" title={r.created_at}>
                    <span className="block text-[13px] text-ink-900">{clock(r.created_at)}</span>
                    <span className="block text-[11px] text-ink-400">{relative(r.created_at, now)}</span>
                  </td>
                  <td className="max-w-[150px] xl:max-w-[220px]">
                    <span className="block truncate text-[13px]" title={r.filename}>
                      {r.filename}
                    </span>
                    {r.document_class && <span className="text-[11px] capitalize text-ink-400">{r.document_class}</span>}
                  </td>
                  <td className="max-w-[150px] truncate text-[13px] xl:max-w-[220px]" title={r.vendor_name ?? ''}>
                    {r.vendor_name ?? <span className="text-ink-400">—</span>}
                  </td>
                  <td className="whitespace-nowrap">{r.invoice_number ? <Mono>{r.invoice_number}</Mono> : r.status === 'failed' ? <span className="text-ink-400">—</span> : <span className="text-[13px] italic text-ink-400">none</span>}</td>
                  <td className="num whitespace-nowrap text-[13px]">
                    {r.net_total != null ? (
                      <>
                        <span className="mr-1 text-[11px] text-ink-400">{r.currency}</span>
                        {amount(r.net_total)}
                      </>
                    ) : (
                      <span className="text-ink-400">—</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap">{r.po_number ? <Mono className="text-ink-700">{r.po_number}</Mono> : <span className="text-ink-400">—</span>}</td>
                  <td>
                    {r.decision ? (
                      <span className="inline-flex items-center gap-1.5" title={r.override_decision ? `Pipeline said ${r.decision}; overridden by ${r.override_by ?? 'a reviewer'}` : undefined}>
                        <DecisionChip decision={r.final_decision ?? r.decision} size="xs" />
                        {r.override_decision && <span className="text-[11px] text-ink-400">overridden</span>}
                      </span>
                    ) : (
                      <RunStatusChip status={r.status} />
                    )}
                  </td>
                  <td className="num text-[13px]">{r.confidence != null ? r.confidence.toFixed(2) : <span className="text-ink-400">—</span>}</td>
                  <td className="num whitespace-nowrap text-[13px] text-ink-600">{duration(r.duration_ms)}</td>
                </tr>
              ))}
        </tbody>
      </table>
      {items && total > items.length && <p className="border-t border-ink-100 px-5 py-2.5 text-xs text-ink-500">Showing the latest {items.length} of {total} runs.</p>}
    </div>
  );
}

// ---------------------------------------------------------------- PO ledger panel
function PoPanel({ pos, vendors, loading }: { pos: PurchaseOrder[] | null; vendors: Vendor[] | null; loading: boolean }) {
  const open = useMemo(() => (pos ?? []).filter((p) => p.status === 'open').sort((a, b) => a.po_number.localeCompare(b.po_number)), [pos]);
  const vname = (id: string) => vendors?.find((v) => v.vendor_id === id)?.legal_name ?? id;
  return (
    <Card className="2xl:self-start">
      <CardHeader
        title="Open PO balances"
        subtitle="Net billed against each open purchase order"
        right={
          <Link to="/reference" className="mt-0.5 shrink-0 text-xs font-medium text-ink-600 hover:text-ink-950">
            All POs →
          </Link>
        }
      />
      <ul className="grid grid-cols-1 gap-x-8 px-5 pb-2 pt-2 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-1">
        {loading &&
          Array.from({ length: 5 }, (_, i) => (
            <li key={i} className="border-b border-ink-100 py-3">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="mt-2 h-2 w-full" />
            </li>
          ))}
        {!loading && open.length === 0 && <li className="py-6 text-center text-sm text-ink-500">No open purchase orders.</li>}
        {open.map((p) => {
          const usedPct = p.net_total ? Math.min(100, Math.round((p.billed_net_to_date / p.net_total) * 100)) : 0;
          const over = p.remaining_net < -0.005;
          return (
            <li key={p.po_number} className="border-b border-ink-100 py-3" title={`${p.po_number}: billed ${p.currency} ${amount(p.billed_net_to_date)} of ${amount(p.net_total)}`}>
              <div className="flex items-baseline justify-between gap-2">
                <Mono className="text-[13px] font-semibold text-ink-950">{p.po_number}</Mono>
                <span className="text-[11px] tabular text-ink-500">{usedPct}% billed</span>
              </div>
              <p className="truncate text-xs text-ink-500">{vname(p.vendor_id)}</p>
              <ConsumptionBar total={p.net_total} billed={p.billed_net_to_date} className="mt-2" />
              <p className={cx('mt-1.5 text-xs tabular', over ? 'font-medium text-hold-ink' : 'text-ink-600')}>
                {over ? `Over by ${p.currency} ${amount(-p.remaining_net)}` : `${p.currency} ${amount(p.remaining_net)} remaining`}
                <span className="text-ink-400"> of {amount(p.net_total)}</span>
              </p>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
