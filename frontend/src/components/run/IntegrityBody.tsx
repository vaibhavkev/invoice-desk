import { ArrowRight, Check, X } from 'lucide-react';
import { amount, cx } from '../../lib/format';
import type { IntegrityOutput, InvoiceExtraction, NormalisedInvoice } from '../../types';
import { Mono, NoData, SectionLabel } from '../ui';

const CHECK_LABEL: Record<string, string> = {
  lines_sum_subtotal: 'Line items add up to the subtotal',
  subtotal_tax_total: 'Subtotal plus tax equals the total',
  required_fields: 'Required fields are present',
  date_parse: 'Invoice date is a valid date',
};

/** Only the values normalisation actually changed; the rest are already on the extraction card. */
function changes(x: InvoiceExtraction | null, n: NormalisedInvoice) {
  if (!x) return [];
  const m = (v: number | null) => (v == null ? '—' : amount(v));
  const s = (v: string | null) => v ?? '—';
  const rows: Array<[string, string, string]> = [
    ['Vendor', s(x.vendor_name.value), s(n.vendor_name)],
    ['Tax ID', s(x.vendor_tax_id.value), s(n.vendor_tax_id)],
    ['Invoice number', s(x.invoice_number.value), s(n.invoice_number)],
    ['Invoice date', s(x.invoice_date.value), s(n.invoice_date)],
    ['Currency', s(x.currency.value), s(n.currency)],
    ['PO references', x.po_references.join(', ') || '—', (n.po_references_normalised ?? []).join(', ') || '—'],
    ['Subtotal (net)', m(x.subtotal.value), m(n.subtotal)],
    ['Tax', m(x.tax_amount.value), m(n.tax_amount)],
    ['Total (gross)', m(x.total.value), m(n.total)],
  ];
  return rows.filter(([, from, to]) => from !== to);
}

export function IntegrityBody({ o, extraction }: { o: IntegrityOutput; extraction: InvoiceExtraction | null }) {
  const n = o.normalised;
  if (!n) return <NoData />;
  const changed = changes(extraction, n);
  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div>
        <SectionLabel>Normalised</SectionLabel>
        {changed.length ? (
          <ul className="space-y-2">
            {changed.map(([label, from, to]) => (
              <li key={label} className="text-[13px]">
                <p className="text-xs text-ink-500">{label}</p>
                <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-ink-900">
                  <Mono className="text-ink-500">{from}</Mono>
                  <ArrowRight className="h-3 w-3 shrink-0 text-ink-400" aria-label="becomes" />
                  <Mono>{to}</Mono>
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-ink-500">No values needed changing.</p>
        )}
      </div>
      <div>
        <SectionLabel>Integrity checks</SectionLabel>
        <ul className="divide-y divide-ink-100 rounded-lg border border-ink-200">
          {(o.checks ?? []).map((c) => (
            <li key={c.code} className="flex items-start gap-2.5 px-3 py-2.5">
              <span className={cx('mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full', c.passed ? 'bg-approve-soft text-approve' : 'bg-hold-soft text-hold')}>
                {c.passed ? <Check className="h-3 w-3" strokeWidth={3} aria-label="pass" /> : <X className="h-3 w-3" strokeWidth={3} aria-label="fail" />}
              </span>
              <div className="min-w-0">
                <p className="text-[13.5px] font-medium text-ink-900">{CHECK_LABEL[c.code] ?? c.code}</p>
                {c.detail && <p className="mt-0.5 text-xs text-ink-500">{c.detail}</p>}
              </div>
              {!c.passed && <span className="ml-auto shrink-0 text-xs font-semibold text-hold">Fail</span>}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
