import { useMemo, useState } from 'react';
import { cx } from '../../lib/format';
import type { MatchingOutput, RuleResult, RulesOutput, StageRecord } from '../../types';
import { Mono, NoData } from '../ui';

export type RuleState = 'pass' | 'warn' | 'hold' | 'reject' | 'skipped';

/**
 * SPEC §4.6: severity is REJECT | HOLD | WARN; passed is null when skipped.
 * A passing rule that carries a warning (e.g. R2 inferred, R4 partial invoice)
 * shows as WARN either via severity === 'WARN' or a "Rn: …" line in warnings.
 */
export function ruleState(r: RuleResult, warnings: string[] = []): RuleState {
  if (r.skipped || r.passed === null) return 'skipped';
  if (r.severity === 'WARN') return 'warn';
  if (r.passed === false) return r.severity === 'REJECT' ? 'reject' : 'hold';
  if (warnings.some((w) => w.startsWith(`${r.code}:`) || w.startsWith(`${r.code} `))) return 'warn';
  return 'pass';
}

/** Timeline line for the rules stage: when nothing failed, says what was skipped and why. */
export function rulesSummary(rules: StageRecord, matching: StageRecord | undefined): string {
  const o = rules.output as RulesOutput | null;
  const results = o?.results ?? [];
  const skipped = results.filter((r) => ruleState(r) === 'skipped');
  if (!skipped.length || results.some((r) => r.passed === false)) return rules.summary;
  const passed = results.length - skipped.length;
  const warned = results.filter((r) => ruleState(r, o?.warnings ?? []) === 'warn').length;
  const po = (matching?.output as MatchingOutput | null | undefined)?.po;
  const why = po && !po.matched ? 'no PO' : skipped.length === 1 && skipped[0]!.code === 'R5' ? 'nothing billed on this PO yet' : skipped.map((r) => r.code).join(', ');
  return `${passed} rule${passed === 1 ? '' : 's'} passed${warned ? ` (${warned} with a warning)` : ''}, ${skipped.length} not applicable (${why}).`;
}

const STATE_META: Record<RuleState, { chip: string; label: string; text: string }> = {
  pass: { chip: 'border-approve-line bg-approve-soft text-approve-ink', label: 'Pass', text: 'text-approve' },
  warn: { chip: 'border-hold bg-white text-hold-ink', label: 'Warning', text: 'text-hold' },
  hold: { chip: 'border-hold-line bg-hold-soft text-hold-ink', label: 'Fail · HOLD', text: 'text-hold' },
  reject: { chip: 'border-reject-line bg-reject-soft text-reject-ink', label: 'Fail · REJECT', text: 'text-reject' },
  skipped: { chip: 'border-dashed border-ink-300 bg-ink-50 text-ink-400', label: 'Skipped', text: 'text-ink-400' },
};

export function RulesBody({ o }: { o: RulesOutput }) {
  if (!o.results?.length) return <NoData />;
  return <RulesGrid rules={o.results} warnings={o.warnings ?? NO_WARNINGS} />;
}

const NO_WARNINGS: string[] = [];

function RulesGrid({ rules, warnings }: { rules: RuleResult[]; warnings: string[] }) {
  const results = useMemo(() => [...rules].sort((a, b) => Number(a.code.slice(1)) - Number(b.code.slice(1))), [rules]);
  const states = useMemo(() => new Map(results.map((r) => [r.code, ruleState(r, warnings)])), [results, warnings]);
  const defaultSel =
    results.find((r) => states.get(r.code) === 'reject') ?? results.find((r) => states.get(r.code) === 'hold') ?? results.find((r) => states.get(r.code) === 'warn') ?? null;
  const [selected, setSelected] = useState<string | null>(defaultSel?.code ?? null);
  const [showAll, setShowAll] = useState(false);
  const sel = results.find((r) => r.code === selected) ?? null;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-5 gap-2" role="listbox" aria-label="Policy rules">
        {results.map((r) => {
          const st = states.get(r.code)!;
          const m = STATE_META[st];
          const active = selected === r.code;
          return (
            <button
              key={r.code}
              type="button"
              role="option"
              aria-selected={active}
              onClick={() => setSelected(active ? null : r.code)}
              className={cx('flex h-[52px] flex-col items-start justify-center rounded-lg border px-2.5 text-left transition-shadow', m.chip, active && 'ring-2 ring-ink-900/70 ring-offset-1')}
              title={`${r.code} ${r.name}: ${m.label}`}
            >
              <span className="flex w-full items-center justify-between">
                <span className="font-mono text-[13px] font-semibold">{r.code}</span>
                <span className="text-[10px] font-semibold uppercase tracking-wide opacity-80">{st === 'pass' ? 'pass' : st === 'skipped' ? 'skip' : st === 'warn' ? 'warn' : st}</span>
              </span>
              <span className="w-full truncate text-[11px] leading-tight opacity-90">{r.name}</span>
            </button>
          );
        })}
      </div>

      <div className="flex justify-end text-[11px]">
        <button type="button" onClick={() => setShowAll((v) => !v)} className="font-medium text-ink-700 underline decoration-ink-300 underline-offset-2 hover:decoration-ink-700" aria-expanded={showAll}>
          {showAll ? 'Hide all details' : 'Show all details'}
        </button>
      </div>

      {!showAll && (
        <div className="min-h-[76px] rounded-lg border border-ink-200 bg-ink-50/60 px-4 py-3">
          {sel ? <RuleDetail r={sel} state={states.get(sel.code)!} /> : <p className="pt-3 text-center text-[13px] text-ink-400">Select a rule to see its detail and evidence.</p>}
        </div>
      )}

      {showAll && (
        <ul className="divide-y divide-ink-100 rounded-lg border border-ink-200">
          {results.map((r) => (
            <li key={r.code} className="px-4 py-3">
              <RuleDetail r={r} state={states.get(r.code)!} compact />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RuleDetail({ r, state, compact }: { r: RuleResult; state: RuleState; compact?: boolean }) {
  const m = STATE_META[state];
  const ev = r.evidence && Object.keys(r.evidence).length ? r.evidence : null;
  return (
    <div>
      <p className="flex flex-wrap items-baseline gap-x-2 text-[13.5px]">
        <Mono className="font-semibold text-ink-950">{r.code}</Mono>
        <span className="font-semibold text-ink-900">{r.name}</span>
        <span className={cx('text-xs font-semibold', m.text)}>{m.label}</span>
      </p>
      <p className="mt-1 text-[13px] leading-relaxed text-ink-700">{r.detail || '—'}</p>
      {ev && !compact && <Evidence ev={ev} />}
    </div>
  );
}

function fmt(v: unknown): string {
  if (v == null) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString('en-US') : v.toLocaleString('en-US', { maximumFractionDigits: 4 });
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v === 'string') return v;
  return JSON.stringify(v);
}

const evidenceLabel = (key: string) => (key === 'billed_net_to_date' ? 'billed to date' : key.replace(/_/g, ' '));

/** Generic evidence renderer: scalars as key/value, arrays of objects as a mini table. */
function Evidence({ ev }: { ev: Record<string, unknown> }) {
  const scalars = Object.entries(ev).filter(([, v]) => v === null || typeof v !== 'object' || (Array.isArray(v) && v.every((x) => typeof x !== 'object')));
  const tables = Object.entries(ev).filter(([, v]) => Array.isArray(v) && v.length > 0 && v.every((x) => x && typeof x === 'object')) as Array<[string, Array<Record<string, unknown>>]>;
  return (
    <div className="mt-2.5 space-y-2">
      {scalars.length > 0 && (
        <dl className="flex flex-wrap gap-x-5 gap-y-1">
          {scalars.map(([k, v]) => (
            <div key={k} className="flex items-baseline gap-1.5 text-xs">
              <dt className="text-ink-400">{evidenceLabel(k)}</dt>
              <dd className="font-mono text-ink-800">{Array.isArray(v) ? (v.length ? v.join(', ') : '[]') : fmt(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {tables.map(([k, rows]) => {
        const cols = Array.from(new Set(rows.flatMap((r) => Object.keys(r))));
        return (
          <div key={k} className="overflow-x-auto">
            <p className="mb-1 text-[11px] text-ink-400">{evidenceLabel(k)}</p>
            <table className="text-xs">
              <thead>
                <tr>
                  {cols.map((c) => (
                    <th key={c} className="whitespace-nowrap pb-1 pr-4 text-left font-normal text-ink-400">
                      {evidenceLabel(c)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i}>
                    {cols.map((c) => (
                      <td key={c} className={cx('whitespace-nowrap pr-4 font-mono tabular-nums', row[c] === false ? 'font-semibold text-hold-ink' : 'text-ink-800')}>
                        {fmt(row[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}
