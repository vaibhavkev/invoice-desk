import { ArrowRight, TriangleAlert } from 'lucide-react';
import { amount, cx } from '../../lib/format';
import { usePurchaseOrders, useVendors } from '../../hooks/useReference';
import type { MatchingOutput, NormalisedInvoice, PoMatch, VendorMatch } from '../../types';
import { ConsumptionBar, Mono, NoData, SectionLabel, Tag } from '../ui';

const VENDOR_METHOD: Record<string, string> = { tax_id: 'Tax ID, exact', alias: 'Name or alias, exact', name_fuzzy: 'Fuzzy name match', none: 'No match' };
const PO_METHOD: Record<string, { label: string; tone: 'neutral' | 'running' | 'hold' | 'reject' | 'outline' }> = {
  explicit: { label: 'Quoted on invoice', tone: 'outline' },
  inferred: { label: 'Inferred', tone: 'running' },
  ambiguous: { label: 'Ambiguous', tone: 'hold' },
  none: { label: 'No PO', tone: 'hold' },
  not_found: { label: 'Reference not found', tone: 'reject' },
};

export function MatchingBody({ o, normalised }: { o: MatchingOutput; normalised: NormalisedInvoice | null }) {
  if (!o.vendor && !o.po) return <NoData />;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      {o.vendor ? <VendorCard v={o.vendor} invoiceName={normalised?.vendor_name ?? null} /> : <NoData />}
      {o.po ? <PoCard po={o.po} normalised={normalised} /> : <NoData />}
    </div>
  );
}

function Panel({ title, tag, children }: { title: string; tag: JSX.Element; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-ink-200">
      <div className="flex items-center justify-between gap-2 border-b border-ink-100 px-4 py-2.5">
        <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-500">{title}</span>
        {tag}
      </div>
      <div className="space-y-4 px-4 py-3.5">{children}</div>
    </div>
  );
}

function ScoreBar({ score }: { score: number }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="relative h-1.5 w-14 overflow-hidden rounded-full bg-ink-100">
        <span className="absolute inset-y-0 left-0 rounded-full bg-ink-500" style={{ width: `${Math.max(0, Math.min(1, score)) * 100}%` }} />
      </span>
      <span className="w-8 text-right font-mono text-xs tabular-nums text-ink-600">{score.toFixed(2)}</span>
    </span>
  );
}

function VendorCard({ v, invoiceName }: { v: VendorMatch; invoiceName: string | null }) {
  const vendors = useVendors();
  const nameOf = (id: string) => vendors?.find((x) => x.vendor_id === id)?.legal_name ?? id;
  const candidates = v.candidates ?? [];
  return (
    <Panel title="Vendor" tag={v.matched ? <Tag tone="approve">Matched</Tag> : <Tag tone="reject">Not in vendor master</Tag>}>
      {v.matched ? (
        <>
          <div>
            <p className="text-[15px] font-semibold text-ink-950">{v.legal_name}</p>
            <p className="mt-0.5 flex items-center gap-2 text-[13px] text-ink-500">
              <Mono>{v.vendor_id}</Mono>
              <span aria-hidden>·</span>
              <span className={cx('font-medium', v.status === 'approved' ? 'text-approve' : 'text-hold')}>{v.status === 'approved' ? 'Approved vendor' : `Vendor ${v.status}`}</span>
            </p>
          </div>
          <dl className="grid grid-cols-2 gap-3 text-[13px]">
            <div>
              <dt className="text-xs text-ink-500">Matched by</dt>
              <dd className="mt-0.5 text-ink-900">{VENDOR_METHOD[v.method] ?? v.method}</dd>
            </div>
            {v.method === 'name_fuzzy' && (
              <div>
                <dt className="text-xs text-ink-500">Score</dt>
                <dd className="mt-1">
                  <ScoreBar score={v.score} />
                </dd>
              </div>
            )}
          </dl>
        </>
      ) : (
        <>
          <div>
            <p className="text-xs text-ink-500">Name on invoice</p>
            <p className="mt-0.5 text-[15px] font-semibold text-ink-950">{invoiceName ?? 'Unknown'}</p>
          </div>
          {candidates.length > 0 && (
            <div>
              <SectionLabel>Closest vendors (below 0.90 threshold)</SectionLabel>
              <ul className="space-y-1.5">
                {candidates.map((c) => (
                  <li key={c.vendor_id} className="flex items-center justify-between gap-3 text-[13px]">
                    <span className="min-w-0 truncate">
                      <Mono className="mr-2 text-ink-500">{c.vendor_id}</Mono>
                      {nameOf(c.vendor_id)}
                    </span>
                    <ScoreBar score={c.score} />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

function Money({ label, value, cur, strong, tone }: { label: string; value: number | null; cur?: string | null; strong?: boolean; tone?: 'hold' | 'approve' }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-[13px]">
      <span className="text-ink-500">{label}</span>
      <span className={cx('tabular', strong ? 'font-semibold' : 'font-medium', tone === 'hold' ? 'text-hold-ink' : tone === 'approve' ? 'text-approve-ink' : 'text-ink-900')}>
        {value == null ? '—' : `${cur ? `${cur} ` : ''}${amount(value)}`}
      </span>
    </div>
  );
}

function PoCard({ po, normalised }: { po: PoMatch; normalised: NormalisedInvoice | null }) {
  const pos = usePurchaseOrders();
  const ref = po.po_number ? pos?.find((p) => p.po_number === po.po_number) : undefined;
  const cur = ref?.currency ?? normalised?.currency ?? null;
  const net = normalised?.subtotal ?? null;
  const meta = PO_METHOD[po.method] ?? { label: po.method, tone: 'outline' as const };
  const after = po.remaining_net != null && net != null ? Math.round((po.remaining_net - net) * 100) / 100 : null;
  const lineMatches = po.line_matches ?? [];
  const unmatchedLines = po.unmatched_invoice_lines ?? [];
  const candidates = po.candidates ?? [];

  return (
    <Panel title="Purchase order" tag={<Tag tone={meta.tone}>{meta.label}</Tag>}>
      {po.matched && po.po_number ? (
        <>
          <div>
            <p className="flex items-center gap-2">
              <Mono className="text-[15px] font-semibold text-ink-950">{po.po_number}</Mono>
              {po.status && <Tag tone={po.status === 'open' ? 'neutral' : 'reject'} className="capitalize">{po.status}</Tag>}
              {po.method === 'inferred' && <span className="text-xs text-ink-500">score {po.score.toFixed(2)}</span>}
            </p>
            {ref && <p className="mt-0.5 text-[13px] text-ink-500">{ref.description} · requester {ref.requester_name}</p>}
            {po.vendor_mismatch && (
              <p className="mt-1.5 flex items-center gap-1.5 text-xs font-medium text-hold-ink">
                <TriangleAlert className="h-3.5 w-3.5" aria-hidden /> PO belongs to {po.vendor_id}, not the matched vendor
              </p>
            )}
          </div>
          {po.net_total != null && po.billed_net_to_date != null && (
            <div className="space-y-1.5">
              <Money label="PO net total" value={po.net_total} cur={cur} />
              <Money label="Billed to date" value={po.billed_net_to_date} cur={cur} />
              <Money label="Remaining before this invoice" value={po.remaining_net} cur={cur} />
              <Money label="This invoice (net)" value={net} cur={cur} />
              <div className="pt-1">
                <ConsumptionBar total={po.net_total} billed={po.billed_net_to_date} incoming={net ?? 0} tone={after != null && after < -0.005 ? 'hold' : 'approve'} />
                <div className="mt-1.5 flex items-center gap-3 text-[11px] text-ink-500">
                  <span className="inline-flex items-center gap-1">
                    <span className="h-2 w-2 rounded-sm bg-ink-600" aria-hidden /> billed
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <span className={cx('h-2 w-2 rounded-sm', after != null && after < -0.005 ? 'bg-hold/70' : 'bg-approve/70')} aria-hidden /> this invoice
                  </span>
                </div>
              </div>
              <div className="border-t border-ink-100 pt-1.5">
                {after != null && after < -0.005 ? (
                  <Money label="Over the PO by" value={-after} cur={cur} strong tone="hold" />
                ) : (
                  <Money label="Remaining after this invoice" value={after} cur={cur} strong />
                )}
              </div>
            </div>
          )}
          {(lineMatches.length > 0 || unmatchedLines.length > 0) && (
            <div>
              <SectionLabel>Line matches</SectionLabel>
              <ul className="space-y-1.5">
                {lineMatches.map((lm) => {
                  const il = normalised?.line_items[lm.invoice_line - 1];
                  const pl = ref?.lines.find((l) => l.line_no === lm.po_line);
                  return (
                    <li key={`${lm.invoice_line}-${lm.po_line}`} className="rounded-md bg-ink-50 px-2.5 py-1.5 text-[12.5px]">
                      <div className="flex items-center justify-between gap-2">
                        <span className="flex min-w-0 items-center gap-1.5 text-ink-700">
                          <span className="shrink-0 font-medium">Inv {lm.invoice_line}</span>
                          <ArrowRight className="h-3 w-3 shrink-0 text-ink-400" aria-hidden />
                          <span className="shrink-0 font-medium">PO line {lm.po_line}</span>
                        </span>
                        <span className="font-mono text-xs tabular-nums text-ink-500">{lm.score.toFixed(2)}</span>
                      </div>
                      {(il || pl) && (
                        <p className="mt-0.5 truncate text-ink-500" title={`${il?.description ?? ''} ↔ ${pl?.description ?? ''}`}>
                          {il?.description}
                          {pl && il && pl.description !== il.description && <span className="text-ink-400"> ↔ {pl.description}</span>}
                          {il?.unit_price != null && pl && (
                            <span className={cx('ml-1.5 tabular', Math.abs(il.unit_price - pl.unit_price) > 0.02 * pl.unit_price ? 'font-medium text-hold-ink' : 'text-ink-400')}>
                              · {amount(il.unit_price)} vs {amount(pl.unit_price)}
                            </span>
                          )}
                        </p>
                      )}
                    </li>
                  );
                })}
                {unmatchedLines.map((n) => (
                  <li key={`u${n}`} className="flex items-center justify-between rounded-md bg-hold-soft px-2.5 py-1.5 text-[12.5px] text-hold-ink">
                    <span>
                      Inv {n} · {normalised?.line_items[n - 1]?.description ?? ''}
                    </span>
                    <span className="text-xs font-medium">no PO line</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      ) : (
        <div className="space-y-2 text-[13px]">
          {po.method === 'not_found' && (
            <p className="text-ink-700">
              The invoice references <Mono className="font-semibold">{normalised?.po_references.join(', ') || 'a PO'}</Mono>, but no such purchase order exists.
            </p>
          )}
          {po.method === 'none' && <p className="text-ink-700">No PO reference on the invoice, and no open PO for this vendor to infer from.</p>}
          {po.method === 'ambiguous' && <p className="text-ink-700">No PO reference on the invoice. Several open POs fit; none is clearly ahead.</p>}
        </div>
      )}
      {candidates.length > 0 && (
        <div>
          <SectionLabel>Candidate POs</SectionLabel>
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="text-left text-[11px] text-ink-400">
                <th className="pb-1 font-medium">PO</th>
                <th className="pb-1 text-right font-medium">Amount</th>
                <th className="pb-1 text-right font-medium">Lines</th>
                <th className="pb-1 text-right font-medium">Score</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((c) => (
                <tr key={c.po_number} className={cx(c.po_number === po.po_number && 'font-semibold')}>
                  <td className="py-0.5">
                    <Mono>{c.po_number}</Mono>
                  </td>
                  <td className="py-0.5 text-right tabular-nums text-ink-600">{c.amount_score?.toFixed(2) ?? '—'}</td>
                  <td className="py-0.5 text-right tabular-nums text-ink-600">{c.line_score?.toFixed(2) ?? '—'}</td>
                  <td className="py-0.5 text-right tabular-nums">{c.score.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
