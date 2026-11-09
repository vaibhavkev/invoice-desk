import { Fragment, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ChevronRight, RotateCcw } from 'lucide-react';
import { api, errorMessage } from '../lib/api';
import { amount, cx, isoDate, qty, shortDateTime } from '../lib/format';
import { useResource } from '../hooks/useResource';
import { invalidateReference } from '../hooks/useReference';
import type { LedgerRow, PolicySettings, PurchaseOrder, Vendor } from '../types';
import { useToast } from '../components/Toast';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { Button, Card, CardHeader, ConsumptionBar, DecisionChip, EmptyState, Mono, Skeleton, Tag } from '../components/ui';

type TabKey = 'pos' | 'ledger' | 'vendors';
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'pos', label: 'Purchase orders' },
  { key: 'ledger', label: 'Ledger' },
  { key: 'vendors', label: 'Vendors' },
];

export function ReferencePage() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.some((t) => t.key === params.get('tab')) ? params.get('tab') : 'pos') as TabKey;
  const onError = (m: string) => toast.error('Could not load reference data', m);
  const vendors = useResource(() => api.vendors(), 'vendors', { onError });
  const pos = useResource(() => api.pos(), 'pos', { onError });
  const ledger = useResource(() => api.ledger(), 'ledger', { onError });
  const policy = useResource(() => api.policy(), 'policy', { onError });

  const [confirm, setConfirm] = useState(false);
  const [clearRuns, setClearRuns] = useState(true);
  const [busy, setBusy] = useState(false);

  const doReset = async () => {
    setBusy(true);
    try {
      await api.reset(clearRuns);
      invalidateReference();
      await Promise.all([pos.refresh(), ledger.refresh(), vendors.refresh()]);
      toast.success('Demo data reset', clearRuns ? 'Ledger re-seeded and run history cleared.' : 'Ledger re-seeded from ledger_seed.csv.');
      setConfirm(false);
    } catch (err) {
      toast.error('Reset failed', errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const vname = (id: string | null) => (id ? vendors.data?.find((v) => v.vendor_id === id)?.legal_name ?? id : '—');
  const counts: Record<TabKey, number | undefined> = { pos: pos.data?.length, ledger: ledger.data?.length, vendors: vendors.data?.length };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-ink-950">Reference data</h1>
          <p className="mt-0.5 text-sm text-ink-500">What the matcher and rules check against: purchase orders with their billing state, the invoice ledger, and the vendor master.</p>
        </div>
        <Button variant="ghost" size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => setConfirm(true)}>
          Reset demo data
        </Button>
      </div>

      <div className="flex gap-1 border-b border-ink-200" role="tablist" aria-label="Reference tables">
        {TABS.map((t) => {
          const active = t.key === tab;
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setParams(t.key === 'pos' ? {} : { tab: t.key }, { replace: true })}
              className={cx('relative -mb-px flex h-10 items-center gap-2 border-b-2 px-3 text-sm font-medium transition-colors', active ? 'border-ink-900 text-ink-950' : 'border-transparent text-ink-500 hover:text-ink-900')}
            >
              {t.label}
              {counts[t.key] != null && <span className="rounded-full bg-ink-100 px-1.5 text-[11px] tabular text-ink-600">{counts[t.key]}</span>}
            </button>
          );
        })}
      </div>

      <Card className="overflow-hidden" role="tabpanel">
        {tab === 'pos' && <PoTable pos={pos.data} loading={pos.loading && !pos.data} vname={vname} />}
        {tab === 'ledger' && <LedgerTable rows={ledger.data} loading={ledger.loading && !ledger.data} vname={vname} />}
        {tab === 'vendors' && <VendorTable vendors={vendors.data} loading={vendors.loading && !vendors.data} />}
      </Card>

      <PolicyCard settings={policy.data} />

      <ConfirmDialog open={confirm} title="Reset demo data?" confirmLabel="Reset" tone="danger" busy={busy} onConfirm={() => void doReset()} onClose={() => setConfirm(false)}>
        <p>
          Reloads the ledger from <Mono>ledger_seed.csv</Mono>, so PO balances and duplicate checks start fresh (EC2a → EC2b and EC4 behave as in the demo script).
        </p>
        <label className="mt-3 flex items-center gap-2 text-ink-800">
          <input type="checkbox" checked={clearRuns} onChange={(e) => setClearRuns(e.target.checked)} className="h-4 w-4 rounded border-ink-300 accent-ink-900" />
          Also delete the run history
        </label>
      </ConfirmDialog>
    </div>
  );
}

const days = (n: number) => `${n} day${n === 1 ? '' : 's'}`;

function PolicyCard({ settings }: { settings: PolicySettings | null }) {
  const p = settings?.policy;
  const e = settings?.extraction;
  const pct = p ? `${+(p.tolerance_pct * 100).toFixed(2)} %` : '';
  const floors = p ? Object.entries(p.tolerance_abs_floor).map(([c, v]) => `${c} ${amount(v, 0)}`).join(' · ') : '';
  const rows: Array<[string, string, string]> = p && e ? [
    ['Price tolerance', pct, `Totals may differ from the PO by up to ${pct}, or the per-currency floor if larger. Unit prices use the percentage alone.`],
    ['Per-currency floor', floors || 'none', 'Smallest absolute difference on totals that still counts as a match, so small invoices are not held over rounding-sized differences.'],
    ['Confidence floor', p.confidence_floor.toFixed(2), `Critical fields read with confidence below ${p.confidence_floor.toFixed(2)} hold the invoice for a person to check.`],
    ['Date window', days(p.date_window_days), `Invoices dated more than ${days(p.date_window_days)} ago are held as stale.`],
    ['Future-date grace', days(p.future_date_grace_days), p.future_date_grace_days === 0 ? 'Invoices dated after today are held.' : `Invoices may be dated up to ${days(p.future_date_grace_days)} after today; later ones are held.`],
    ['Duplicate window', days(p.duplicate_date_window_days), `Same vendor and amount within ${days(p.duplicate_date_window_days)} of an earlier invoice is rejected as a duplicate (on top of exact invoice-number and file matches).`],
    ['Scanned-page threshold', `${p.scanned_chars_per_page} chars`, `A PDF page with fewer than ${p.scanned_chars_per_page} text characters is treated as a scan and read from the image.`],
    ['Extraction model', e.model, 'The model that reads the invoice into structured fields.'],
    ['Effort', e.effort, 'How much reasoning the model spends per invoice.'],
    ['Cache fallback', e.cache_fallback ? 'on' : 'off', e.cache_fallback ? 'If the model call fails, a previously recorded extraction of the same file is used.' : 'If the model call fails, the run fails instead of using a recorded extraction.'],
  ] : [];
  return (
    <Card>
      <CardHeader title="Policy" subtitle={<>Loaded from <Mono>config.yaml</Mono>. Read-only here; change the file and restart to apply.</>} />
      <dl className="mt-3 divide-y divide-ink-100 border-t border-ink-100">
        {!settings
          ? Array.from({ length: 4 }, (_, i) => <div key={i} className="px-5 py-3"><Skeleton className="h-4 w-full" /></div>)
          : rows.map(([label, value, meaning]) => (
            <div key={label} className="grid gap-x-4 gap-y-0.5 px-5 py-2.5 sm:grid-cols-[180px_220px_1fr]">
              <dt className="text-sm text-ink-600">{label}</dt>
              <dd className="font-mono text-[12.5px] text-ink-900 tabular">{value}</dd>
              <dd className="text-sm text-ink-500">{meaning}</dd>
            </div>
          ))}
      </dl>
    </Card>
  );
}

function SkeletonRows({ cols, rows = 6 }: { cols: number; rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, i) => (
        <tr key={i}>
          {Array.from({ length: cols }, (_, j) => (
            <td key={j}>
              <Skeleton className="h-4 w-full" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

function PoTable({ pos, loading, vname }: { pos: PurchaseOrder[] | null; loading: boolean; vname: (id: string) => string }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (k: string) => setOpen((s) => {
    const n = new Set(s);
    if (n.has(k)) n.delete(k);
    else n.add(k);
    return n;
  });
  if (!loading && pos && pos.length === 0) return <EmptyState title="No purchase orders" body="purchase_orders.csv has no rows." />;
  return (
    <div className="overflow-x-auto">
      <table className="table-base">
        <thead>
          <tr>
            <th className="w-8" aria-label="Expand" />
            <th>PO number</th>
            <th>Vendor</th>
            <th>Description</th>
            <th className="num">Net total</th>
            <th className="num">Billed</th>
            <th className="w-[220px]">Remaining</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {loading || !pos ? (
            <SkeletonRows cols={8} />
          ) : (
            pos.map((p) => {
              const expanded = open.has(p.po_number);
              const over = p.remaining_net < -0.005;
              return (
                <Fragment key={p.po_number}>
                  <tr className="cursor-pointer hover:bg-ink-50" onClick={() => toggle(p.po_number)}>
                    <td>
                      <button
                        type="button"
                        aria-expanded={expanded}
                        aria-label={`${expanded ? 'Collapse' : 'Expand'} ${p.po_number}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          toggle(p.po_number);
                        }}
                        className="rounded p-0.5 text-ink-400 hover:text-ink-900"
                      >
                        <ChevronRight className={cx('h-4 w-4 transition-transform', expanded && 'rotate-90')} />
                      </button>
                    </td>
                    <td className="whitespace-nowrap">
                      <Mono className="font-semibold">{p.po_number}</Mono>
                    </td>
                    <td className="max-w-[170px] truncate text-[13px] xl:max-w-[240px]">{vname(p.vendor_id)}</td>
                    <td className="max-w-[170px] truncate text-[13px] text-ink-600 xl:max-w-[280px]" title={p.description}>
                      {p.description}
                    </td>
                    <td className="num whitespace-nowrap text-[13px]">
                      <span className="mr-1 text-[11px] text-ink-400">{p.currency}</span>
                      {amount(p.net_total)}
                    </td>
                    <td className="num whitespace-nowrap text-[13px]">{amount(p.billed_net_to_date)}</td>
                    <td>
                      <div className="flex items-center gap-3">
                        <ConsumptionBar total={p.net_total} billed={p.billed_net_to_date} className="w-24" />
                        <span className={cx('whitespace-nowrap text-[13px] tabular', over ? 'font-medium text-hold-ink' : 'text-ink-900')}>{over ? `−${amount(-p.remaining_net)}` : amount(p.remaining_net)}</span>
                      </div>
                    </td>
                    <td>
                      <Tag tone={p.status === 'open' ? 'outline' : 'neutral'} className="capitalize">
                        {p.status}
                      </Tag>
                    </td>
                  </tr>
                  {expanded && (
                    <tr>
                      <td />
                      <td colSpan={7} className="bg-ink-50/60">
                        <div className="grid gap-6 py-2 xl:grid-cols-2">
                          <div>
                            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-400">Lines</p>
                            <table className="w-full text-[13px]">
                              <thead>
                                <tr className="text-left text-[11px] text-ink-400">
                                  <th className="pb-1 font-medium">#</th>
                                  <th className="pb-1 font-medium">Description</th>
                                  <th className="pb-1 text-right font-medium">Qty</th>
                                  <th className="pb-1 text-right font-medium">Unit</th>
                                  <th className="pb-1 text-right font-medium">Total</th>
                                </tr>
                              </thead>
                              <tbody>
                                {p.lines.map((l) => (
                                  <tr key={l.line_no}>
                                    <td className="py-0.5 text-ink-400">{l.line_no}</td>
                                    <td className="py-0.5">{l.description}</td>
                                    <td className="py-0.5 text-right tabular-nums">{qty(l.quantity)}</td>
                                    <td className="py-0.5 text-right tabular-nums">{amount(l.unit_price)}</td>
                                    <td className="py-0.5 text-right tabular-nums">{amount(l.line_total)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                            <p className="mt-2 text-xs text-ink-500">
                              Requester {p.requester_name} · <span className="text-ink-600">{p.requester_email}</span> · raised {isoDate(p.po_date)}
                            </p>
                          </div>
                          <div>
                            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-400">Invoices against this PO</p>
                            {p.invoices.length === 0 ? (
                              <p className="text-[13px] text-ink-500">None yet.</p>
                            ) : (
                              <ul className="space-y-1">
                                {p.invoices.map((inv, i) => (
                                  <li key={`${inv.invoice_number}-${i}`} className="flex items-center justify-between gap-3 text-[13px]">
                                    <span className="flex items-center gap-2">
                                      <Mono>{inv.invoice_number ?? '(no number)'}</Mono>
                                      <span className="text-[11px] text-ink-400">{inv.source === 'seed' ? 'seed' : 'this app'}</span>
                                    </span>
                                    <span className="flex items-center gap-3">
                                      <span className="tabular">{amount(inv.net_total)}</span>
                                      <DecisionChip decision={inv.decision} size="xs" />
                                    </span>
                                  </li>
                                ))}
                              </ul>
                            )}
                            <p className="mt-2 text-xs text-ink-500">Only APPROVE invoices count toward billed.</p>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

function LedgerTable({ rows, loading, vname }: { rows: LedgerRow[] | null; loading: boolean; vname: (id: string | null) => string }) {
  if (!loading && rows && rows.length === 0) return <EmptyState title="Ledger is empty" body="Reset demo data to reload ledger_seed.csv." />;
  return (
    <div className="scroll-thin max-h-[680px] overflow-auto">
      <table className="table-base">
        <thead>
          <tr>
            <th>Processed</th>
            <th>Invoice no.</th>
            <th>Vendor</th>
            <th>Invoice date</th>
            <th className="num">Net</th>
            <th className="num">Gross</th>
            <th>PO</th>
            <th>Decision</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {loading || !rows ? (
            <SkeletonRows cols={9} />
          ) : (
            rows.map((r, i) => (
              <tr key={r.id ?? i}>
                <td className="whitespace-nowrap text-[13px] text-ink-600">{shortDateTime(r.processed_at)}</td>
                <td className="whitespace-nowrap">{r.invoice_number ? <Mono>{r.invoice_number}</Mono> : <span className="text-[13px] italic text-ink-400">none</span>}</td>
                <td className="max-w-[150px] truncate text-[13px] xl:max-w-[240px]" title={vname(r.vendor_id)}>{vname(r.vendor_id)}</td>
                <td className="whitespace-nowrap text-[13px]">{isoDate(r.invoice_date)}</td>
                <td className="num whitespace-nowrap text-[13px]">
                  <span className="mr-1 text-[11px] text-ink-400">{r.currency}</span>
                  {amount(r.net_total)}
                </td>
                <td className="num whitespace-nowrap text-[13px]">{amount(r.gross_total)}</td>
                <td className="whitespace-nowrap">{r.po_number ? <Mono className="text-ink-700">{r.po_number}</Mono> : <span className="text-ink-400">—</span>}</td>
                <td>
                  <DecisionChip decision={r.decision} size="xs" />
                </td>
                <td className="whitespace-nowrap text-[13px]">
                  {r.source === 'run' && r.run_id ? (
                    <Link to={`/runs/${r.run_id}`} className="font-medium text-ink-800 underline decoration-ink-300 underline-offset-2 hover:decoration-ink-800">
                      Run
                    </Link>
                  ) : (
                    <span className="text-ink-500">Seed</span>
                  )}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function VendorTable({ vendors, loading }: { vendors: Vendor[] | null; loading: boolean }) {
  if (!loading && vendors && vendors.length === 0) return <EmptyState title="No vendors" body="vendors.csv has no rows." />;
  return (
    <div className="overflow-x-auto">
      <table className="table-base">
        <thead>
          <tr>
            <th>ID</th>
            <th>Legal name</th>
            <th>Tax ID</th>
            <th>Country</th>
            <th>Currency</th>
            <th className="num">Terms</th>
            <th>Contact</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {loading || !vendors ? (
            <SkeletonRows cols={8} />
          ) : (
            vendors.map((v) => (
              <tr key={v.vendor_id}>
                <td>
                  <Mono className="text-ink-600">{v.vendor_id}</Mono>
                </td>
                <td className="text-[13px]">
                  <span className="font-medium text-ink-950">{v.legal_name}</span>
                  {v.aliases && <span className="block text-xs text-ink-500">aka {v.aliases.split('|').join(', ')}</span>}
                </td>
                <td>
                  <Mono>{v.tax_id}</Mono>
                </td>
                <td className="text-[13px]">{v.country}</td>
                <td>
                  <Mono>{v.currency}</Mono>
                </td>
                <td className="num text-[13px]">{v.payment_terms_days} days</td>
                <td className="text-[13px] text-ink-600">{v.contact_email}</td>
                <td>
                  <Tag tone={v.status === 'approved' ? 'approve' : 'hold'} className="capitalize">
                    {v.status}
                  </Tag>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
