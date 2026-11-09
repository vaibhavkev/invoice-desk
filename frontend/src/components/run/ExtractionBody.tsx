import { Info } from 'lucide-react';
import { amount, cx, isoDate, qty } from '../../lib/format';
import type { ExtractionOutput, InvoiceExtraction, NumField, StrField } from '../../types';
import { estimateCost, tokens, usd } from '../../lib/pricing';
import { ConfidenceBar, Mono, NoData, SectionLabel, Tag } from '../ui';

type Kind = 'text' | 'date' | 'money' | 'pct' | 'code';
const FIELDS: Array<{ key: keyof InvoiceExtraction; label: string; kind: Kind; critical?: boolean }> = [
  { key: 'vendor_name', label: 'Vendor', kind: 'text', critical: true },
  { key: 'vendor_tax_id', label: 'Vendor tax ID', kind: 'code' },
  { key: 'vendor_address', label: 'Vendor address', kind: 'text' },
  { key: 'bill_to_name', label: 'Bill to', kind: 'text' },
  { key: 'invoice_number', label: 'Invoice number', kind: 'code', critical: true },
  { key: 'invoice_date', label: 'Invoice date', kind: 'date' },
  { key: 'due_date', label: 'Due date', kind: 'date' },
  { key: 'currency', label: 'Currency', kind: 'code' },
  { key: 'subtotal', label: 'Subtotal (net)', kind: 'money' },
  { key: 'tax_amount', label: 'Tax', kind: 'money' },
  { key: 'tax_rate_pct', label: 'Tax rate', kind: 'pct' },
  { key: 'total', label: 'Total (gross)', kind: 'money', critical: true },
  { key: 'payment_terms', label: 'Payment terms', kind: 'text' },
];

const FLOOR = 0.75;

function renderValue(f: StrField | NumField, kind: Kind, currency: string | null) {
  if (f.value == null) return <span className="italic text-ink-400">Not found</span>;
  switch (kind) {
    case 'date':
      return <span>{isoDate(String(f.value))}</span>;
    case 'money':
      return (
        <span className="tabular">
          {currency && <span className="mr-1 text-ink-500">{currency}</span>}
          {amount(Number(f.value))}
        </span>
      );
    case 'pct':
      return <span className="tabular">{Number(f.value)}%</span>;
    case 'code':
      return <Mono>{String(f.value)}</Mono>;
    default:
      return <span>{String(f.value)}</span>;
  }
}

/** "5.4k in · 1.2k out · about $0.05"; a cached extraction made no model call, so it used no tokens. */
function UsageLine({ o }: { o: ExtractionOutput }) {
  const inT = o.usage?.input_tokens;
  const outT = o.usage?.output_tokens;
  if (o.from_cache || inT == null || outT == null) return <Tag tone="outline">from cache, no tokens used</Tag>;
  const cost = estimateCost(o.model, inT, outT);
  return (
    <span className="tabular" title={`${inT.toLocaleString('en-US')} input · ${outT.toLocaleString('en-US')} output tokens. Cost at Anthropic list prices, no caching discount.`}>
      <span className="text-ink-800">{tokens(inT)}</span> in · <span className="text-ink-800">{tokens(outT)}</span> out
      {cost != null && <> · about <span className="text-ink-800">{usd(cost)}</span></>}
    </span>
  );
}

export function ExtractionBody({ o }: { o: ExtractionOutput }) {
  const x = o.extraction;
  if (!x) return <NoData />;
  const currency = x.currency?.value ?? null;
  const poRefs = x.po_references ?? [];
  const lines = x.line_items ?? [];
  return (
    <div className="space-y-5">
      <div>
        <div className="mb-2 flex items-end justify-between">
          <SectionLabel className="mb-0">Fields</SectionLabel>
          <span className="flex items-center gap-3 text-[11px] text-ink-400">
            <span className="inline-flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-ink-900" aria-hidden /> critical field
            </span>
            <span>tick = {FLOOR} floor</span>
          </span>
        </div>
        <div className="divide-y divide-ink-100 rounded-lg border border-ink-200">
          {FIELDS.map(({ key, label, kind, critical }) => {
            const f = (x[key] ?? { value: null, confidence: 0, evidence: null }) as StrField | NumField;
            const low = f.confidence < FLOOR;
            return (
              <div key={key} className={cx('grid grid-cols-[132px_minmax(0,1fr)_112px] items-start gap-3 px-3 py-2', low && critical && 'bg-hold-soft/60')}>
                <div className="flex items-center gap-1.5 pt-px text-[13px] text-ink-500">
                  {critical && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-ink-900" title="Critical field (R10)" aria-label="critical" />}
                  {label}
                </div>
                <div className="min-w-0">
                  <div className="text-[13.5px] font-medium text-ink-950">{renderValue(f, kind, currency)}</div>
                  {f.evidence ? (
                    <p className="mt-0.5 truncate text-xs text-ink-500" title={`“${f.evidence.quote}” — page ${f.evidence.page}`}>
                      <span className="italic">“{f.evidence.quote}”</span>
                      <span className="ml-1.5 rounded bg-ink-100 px-1 py-px font-mono text-[10.5px] not-italic text-ink-500">p.{f.evidence.page}</span>
                    </p>
                  ) : (
                    <p className="mt-0.5 text-xs text-ink-400">No evidence in document</p>
                  )}
                </div>
                <div className="flex justify-end pt-1">
                  <ConfidenceBar value={f.confidence} floor={FLOOR} width="w-14" />
                </div>
              </div>
            );
          })}
          <div className="grid grid-cols-[132px_minmax(0,1fr)_112px] items-start gap-3 px-3 py-2">
            <div className="pt-px text-[13px] text-ink-500">PO references</div>
            <div className="flex flex-wrap gap-1.5">
              {poRefs.length ? poRefs.map((r) => <Tag key={r} tone="outline"><Mono>{r}</Mono></Tag>) : <span className="text-[13.5px] italic text-ink-400">None found</span>}
            </div>
            <div />
          </div>
        </div>
      </div>

      <div>
        <SectionLabel>Line items ({lines.length})</SectionLabel>
        <div className="overflow-x-auto rounded-lg border border-ink-200">
          <table className="table-base">
            <thead>
              <tr>
                <th className="w-8">#</th>
                <th>Description</th>
                <th className="num">Qty</th>
                <th className="num">Unit price</th>
                <th className="num">Amount</th>
                <th className="num">Conf.</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l, i) => (
                <tr key={i}>
                  <td className="text-ink-400">{i + 1}</td>
                  <td className="max-w-[260px] truncate" title={l.description}>{l.description}</td>
                  <td className="num">{qty(l.quantity)}</td>
                  <td className="num">{amount(l.unit_price)}</td>
                  <td className="num font-medium">{amount(l.amount)}</td>
                  <td className="num">
                    <ConfidenceBar value={l.confidence} width="w-10" />
                  </td>
                </tr>
              ))}
              {!lines.length && (
                <tr>
                  <td colSpan={6} className="text-center text-ink-400">No line items extracted</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {x.document_notes && (
        <div className="flex items-start gap-2.5 rounded-lg border border-ink-200 bg-ink-50 px-3 py-2.5">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-ink-500" aria-hidden />
          <div>
            <p className="text-xs font-semibold text-ink-700">Notes from the model</p>
            <p className="mt-0.5 text-[13px] text-ink-600">{x.document_notes}</p>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t border-ink-100 pt-3 text-xs text-ink-500">
        <span>
          Model <Mono className="text-ink-800">{o.model}</Mono>
        </span>
        <UsageLine o={o} />
      </div>
    </div>
  );
}
