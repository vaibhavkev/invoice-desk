// A compact re-implementation of SPEC §4 stages 4–7 over canned extractions, so the
// mock's numbers are internally consistent and react to ledger state (EC2a → EC2b,
// re-running a sample → duplicate). This is NOT the real backend; it is a dev fixture.

import { POLICY, MODEL, VENDORS, POS, CANNED } from './data.mjs';

export const STAGE_DEFS = [
  { key: 'intake', name: 'Intake' },
  { key: 'doc_analysis', name: 'Document analysis' },
  { key: 'extraction', name: 'Extraction' },
  { key: 'integrity', name: 'Normalisation & integrity' },
  { key: 'matching', name: 'Vendor & PO matching' },
  { key: 'rules', name: 'Policy rules' },
  { key: 'decision', name: 'Decision' },
];

const RULE_NAMES = {
  R1: 'Vendor approved',
  R2: 'PO valid',
  R3: 'Not a duplicate',
  R4: 'Invoice total within PO tolerance',
  R5: 'Cumulative billing within PO',
  R6: 'Line prices within tolerance',
  R7: 'Currency matches PO',
  R8: 'Document complete',
  R9: 'Invoice date in window',
  R10: 'Extraction confidence',
};
const RULE_FAIL_SEVERITY = { R1: 'REJECT', R2: 'HOLD', R3: 'REJECT', R4: 'HOLD', R5: 'HOLD', R6: 'HOLD', R7: 'HOLD', R8: 'HOLD', R9: 'HOLD', R10: 'HOLD' };

// ---- small utilities ------------------------------------------------------
export const r2 = (n) => Math.round(n * 100) / 100;
export const money = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const normTax = (s) => (s ? s.replace(/[\s.\-]/g, '').toUpperCase() : null);
const normRef = (s) => (s ? s.toUpperCase().replace(/[^A-Z0-9]/g, '') : null);
const LEGAL = new Set(['ltd', 'limited', 'inc', 'llc', 'gmbh', 'bv', 'pvt', 'plc', 'co', 'corp', 'corporation']);
const normName = (s) => (s || '').toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/).filter((t) => t && !LEGAL.has(t)).join(' ');
const proc = (s) => (s || '').toLowerCase().replace(/[^a-z0-9µ]+/g, ' ').trim();

function lcs(a, b) {
  const m = b.length;
  let prev = new Array(m + 1).fill(0);
  for (let i = 1; i <= a.length; i++) {
    const cur = new Array(m + 1).fill(0);
    for (let j = 1; j <= m; j++) cur[j] = a[i - 1] === b[j - 1] ? prev[j - 1] + 1 : Math.max(prev[j], cur[j - 1]);
    prev = cur;
  }
  return prev[m];
}
const ratio = (a, b) => (!a.length && !b.length ? 100 : (200 * lcs(a, b)) / (a.length + b.length));

/** Approximation of rapidfuzz.fuzz.token_set_ratio (0–100). */
export function tokenSetRatio(a, b) {
  const ta = new Set(proc(a).split(' ').filter(Boolean));
  const tb = new Set(proc(b).split(' ').filter(Boolean));
  const inter = [...ta].filter((t) => tb.has(t)).sort();
  const dab = [...ta].filter((t) => !tb.has(t)).sort();
  const dba = [...tb].filter((t) => !ta.has(t)).sort();
  const sect = inter.join(' ');
  if (sect && (!dab.length || !dba.length)) return 100;
  const c1 = [sect, dab.join(' ')].filter(Boolean).join(' ');
  const c2 = [sect, dba.join(' ')].filter(Boolean).join(' ');
  return Math.max(sect ? ratio(sect, c1) : 0, sect ? ratio(sect, c2) : 0, ratio(c1, c2));
}

const dayDiff = (a, b) => Math.round((Date.parse(a) - Date.parse(b)) / 86400000);
const isoDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const pctStr = (p) => `${r2(p * 100)}%`;

// ---- stage builders -------------------------------------------------------

/** Text the placeholder PDF prints and stage 2 reports as its text layer. */
export function printedLines(sampleId) {
  const c = CANNED[sampleId];
  if (!c) return [];
  const x = c.extraction;
  const q = (f) => f.evidence?.quote;
  const out = [
    q(x.vendor_name), q(x.vendor_address), q(x.vendor_tax_id), '',
    'INVOICE', q(x.invoice_number), q(x.invoice_date), q(x.due_date), c.po_text, q(x.bill_to_name), '',
    'Description    Qty    Unit price    Amount',
    ...x.line_items.map((l) => `${l.description}    ${l.quantity}    ${money(l.unit_price)}    ${money(l.amount)}`), '',
    q(x.subtotal), q(x.tax_amount), q(x.total), q(x.currency), q(x.payment_terms), ...c.extra_lines,
  ];
  return out.filter((l) => l != null);
}

function docAnalysis(sampleId, pageCount) {
  const c = CANNED[sampleId];
  const text = c.document_class === 'scanned' ? '' : printedLines(sampleId).join('\n');
  const pages = Array.from({ length: Math.max(1, pageCount) }, (_, i) => {
    const chars = i === 0 ? text.length : 0;
    return { page: i + 1, chars, has_text_layer: chars >= POLICY.scanned_chars_per_page };
  });
  const textPages = pages.filter((p) => p.has_text_layer).length;
  const cls = textPages === pages.length ? 'digital' : textPages === 0 ? 'scanned' : 'mixed';
  const n = pages.length;
  const summary =
    cls === 'scanned'
      ? `${n} page${n > 1 ? 's' : ''}, no text layer — using vision extraction.`
      : cls === 'mixed'
        ? `${textPages} of ${n} pages have a text layer; the other pages are read as images.`
        : `${n} page${n > 1 ? 's' : ''}, text layer present.`;
  return { output: { document_class: cls, pages, text_layer: text, language_guess: 'en' }, summary, warnings: cls === 'scanned' ? ['No text layer; extraction relies on vision only'] : [] };
}

function integrity(x) {
  const lines = x.line_items.map((l) => ({ description: l.description, quantity: l.quantity, unit_price: l.unit_price == null ? null : r2(l.unit_price), amount: l.amount == null ? null : r2(l.amount) }));
  const warnings = [];
  let total = x.total.value;
  if (total == null && x.subtotal.value != null && x.tax_amount.value != null) {
    total = r2(x.subtotal.value + x.tax_amount.value);
    warnings.push('total derived from subtotal + tax');
  }
  const normalised = {
    vendor_name: x.vendor_name.value,
    vendor_tax_id: normTax(x.vendor_tax_id.value),
    invoice_number: x.invoice_number.value,
    invoice_date: x.invoice_date.value,
    currency: x.currency.value ? x.currency.value.toUpperCase() : null,
    po_references: x.po_references,
    po_references_normalised: x.po_references.map(normRef),
    subtotal: x.subtotal.value == null ? null : r2(x.subtotal.value),
    tax_amount: x.tax_amount.value == null ? null : r2(x.tax_amount.value),
    total: total == null ? null : r2(total),
    line_items: lines,
  };
  const lineSum = r2(lines.reduce((s, l) => s + (l.amount ?? 0), 0));
  const tax = normalised.tax_amount ?? 0;
  const missing = ['invoice_number', 'invoice_date', 'total', 'vendor_name'].filter((k) => normalised[k] == null);
  const dateOk = normalised.invoice_date != null && !Number.isNaN(Date.parse(normalised.invoice_date));
  const checks = [
    { code: 'lines_sum_subtotal', passed: normalised.subtotal != null && Math.abs(lineSum - normalised.subtotal) <= 0.05, detail: `Lines sum to ${money(lineSum)}; subtotal ${money(normalised.subtotal)}` },
    { code: 'subtotal_tax_total', passed: normalised.subtotal != null && normalised.total != null && Math.abs(normalised.subtotal + tax - normalised.total) <= 0.05, detail: `${money(normalised.subtotal)} + ${money(tax)} = ${money(r2((normalised.subtotal ?? 0) + tax))}${normalised.total != null ? `; printed total ${money(normalised.total)}` : ''}` },
    { code: 'required_fields', passed: missing.length === 0, detail: missing.length ? `Missing: ${missing.join(', ')}` : 'invoice_number, invoice_date, total, vendor_name present' },
    { code: 'date_parse', passed: dateOk, detail: dateOk ? '' : `Invoice date ${normalised.invoice_date ?? 'missing'} could not be parsed` },
  ];
  const cc = { invoice_number: x.invoice_number.confidence, total: x.total.confidence, vendor_name: x.vendor_name.confidence };
  // Absent fields are R8's job: reported with their confidence, excluded from min (SPEC §4.6 R10).
  const present = Object.keys(cc).filter((k) => normalised[k] != null).map((k) => cc[k]);
  const critical_confidence = { ...cc, min: present.length ? Math.min(...present) : null };
  const failed = checks.filter((c) => !c.passed);
  failed.forEach((c) => warnings.push(c.detail));
  const summary = failed.length
    ? `${failed.length} of 4 integrity checks failed (${failed.map((c) => c.code).join(', ')}); rules will decide the consequence.`
    : `Amounts reconcile (${money(normalised.subtotal)} + ${money(tax)} = ${money(normalised.total)} ${normalised.currency}); all required fields present.`;
  return { output: { normalised, checks, critical_confidence }, summary, warnings, status: failed.length ? 'warn' : 'done' };
}

function billedToDate(ledger, poNumber) {
  return r2(ledger.filter((r) => r.po_number === poNumber && r.decision === 'APPROVE').reduce((s, r) => s + r.net_total, 0));
}

function lineMatches(invLines, po) {
  const matches = [];
  const unmatched = [];
  invLines.forEach((il, i) => {
    let best = null;
    po.lines.forEach((pl) => {
      const sc = tokenSetRatio(il.description, pl.description);
      if (!best || sc > best.sc) best = { sc, pl };
    });
    if (best && best.sc >= 80) matches.push({ invoice_line: i + 1, po_line: best.pl.line_no, score: r2(best.sc / 100) });
    else unmatched.push(i + 1);
  });
  return { line_matches: matches, unmatched_invoice_lines: unmatched };
}

function matching(norm, ledger) {
  // Vendor
  let vendor;
  const tax = norm.vendor_tax_id;
  const byTax = tax && VENDORS.find((v) => normTax(v.tax_id) === tax);
  const nn = normName(norm.vendor_name);
  const byAlias = VENDORS.find((v) => [v.legal_name, ...v.aliases.split('|')].filter(Boolean).some((a) => normName(a) === nn));
  const fuzzy = VENDORS.map((v) => ({ vendor_id: v.vendor_id, score: r2(Math.max(tokenSetRatio(normName(v.legal_name), nn), ...v.aliases.split('|').filter(Boolean).map((a) => tokenSetRatio(normName(a), nn))) / 100), method: 'name_fuzzy' })).sort((a, b) => b.score - a.score);
  const pick = (v, method, score) => ({ matched: true, vendor_id: v.vendor_id, legal_name: v.legal_name, status: v.status, method, score, candidates: [{ vendor_id: v.vendor_id, score, method }] });
  if (byTax) vendor = pick(byTax, 'tax_id', 1.0);
  else if (byAlias) vendor = pick(byAlias, 'alias', 1.0);
  else if (fuzzy[0].score >= 0.9) vendor = pick(VENDORS.find((v) => v.vendor_id === fuzzy[0].vendor_id), 'name_fuzzy', fuzzy[0].score);
  else vendor = { matched: false, vendor_id: null, legal_name: null, status: null, method: 'none', score: fuzzy[0].score, candidates: fuzzy.slice(0, 3) };

  // PO
  const base = { matched: false, po_number: null, method: 'none', score: 0, status: null, vendor_id: null, vendor_mismatch: false, net_total: null, billed_net_to_date: null, remaining_net: null, candidates: [], line_matches: [], unmatched_invoice_lines: [] };
  let poOut = base;
  const refs = norm.po_references_normalised;
  const explicit = POS.find((p) => refs.includes(normRef(p.po_number)));
  const withPo = (p, method, score, extra = {}) => {
    const billed = billedToDate(ledger, p.po_number);
    return { ...base, matched: true, po_number: p.po_number, method, score, status: p.status, vendor_id: p.vendor_id, vendor_mismatch: !!vendor.vendor_id && p.vendor_id !== vendor.vendor_id, net_total: p.net_total, billed_net_to_date: billed, remaining_net: r2(p.net_total - billed), ...lineMatches(norm.line_items, p), ...extra };
  };
  if (explicit) poOut = withPo(explicit, 'explicit', 1.0);
  else if (refs.length) poOut = { ...base, method: 'not_found' };
  else if (vendor.matched) {
    const net = norm.subtotal ?? 0;
    const cands = POS.filter((p) => p.vendor_id === vendor.vendor_id && p.status === 'open').map((p) => {
      const remaining = r2(p.net_total - billedToDate(ledger, p.po_number));
      const amount_score = Math.max(0, 1 - Math.abs(net - remaining) / p.net_total);
      const line_score = norm.line_items.length ? norm.line_items.reduce((s, il) => s + Math.max(...p.lines.map((pl) => tokenSetRatio(il.description, pl.description))) / 100, 0) / norm.line_items.length : 0;
      return { po_number: p.po_number, score: r2(0.6 * amount_score + 0.4 * line_score), amount_score: r2(amount_score), line_score: r2(line_score), net_total: p.net_total, remaining_net: remaining };
    }).sort((a, b) => b.score - a.score);
    if (!cands.length) poOut = base;
    else if (cands[0].score >= 0.8 && cands[0].score - (cands[1]?.score ?? 0) >= 0.2) poOut = withPo(POS.find((p) => p.po_number === cands[0].po_number), 'inferred', cands[0].score, { candidates: cands });
    else poOut = { ...base, method: 'ambiguous', candidates: cands };
  }

  const vText = vendor.matched
    ? `Vendor ${vendor.vendor_id} ${vendor.legal_name} (${vendor.method === 'tax_id' ? 'matched on tax ID' : vendor.method === 'alias' ? 'matched on name' : `close name match, score ${vendor.score}`}).`
    : `Vendor "${norm.vendor_name}" not found in the vendor master (closest match ${Math.round(vendor.score * 100)}%).`;
  const pText = {
    explicit: `${poOut.po_number} (quoted on invoice),${money(poOut.remaining_net)} of ${money(poOut.net_total)} remaining before this invoice.`,
    inferred: `${poOut.po_number} inferred from vendor, amount and lines (score ${poOut.score}).`,
    ambiguous: `No PO reference; ${poOut.candidates.length} candidate POs, none clearly ahead.`,
    none: 'No PO reference and no candidate PO.',
    not_found: `PO reference ${norm.po_references.join(', ')} does not exist.`,
  }[poOut.method];
  const ok = vendor.matched && ['explicit', 'inferred'].includes(poOut.method);
  return { output: { vendor, po: poOut }, summary: `${vText} ${pText}`, warnings: ok ? [] : [vendor.matched ? 'PO not matched' : 'Vendor not matched'], status: ok ? 'done' : 'warn' };
}

function rules(ctx) {
  const { norm, integ, match, ledger, fileHash, today } = ctx;
  const { vendor, po } = match;
  const vrec = vendor.matched ? VENDORS.find((v) => v.vendor_id === vendor.vendor_id) : null;
  const porec = po.matched ? POS.find((p) => p.po_number === po.po_number) : null;
  const cur = norm.currency;
  const net = norm.subtotal ?? 0;
  const results = [];
  const warnings = [];
  const add = (code, passed, detail, evidence = {}, opts = {}) => {
    const severity = opts.severity ?? (passed ? (opts.warn ? 'WARN' : RULE_FAIL_SEVERITY[code]) : RULE_FAIL_SEVERITY[code]);
    results.push({ code, name: RULE_NAMES[code], passed, severity, detail, evidence, skipped: !!opts.skipped });
    if (opts.warn) warnings.push(`${code}: ${opts.warn}`);
  };
  const skip = (code, why) => add(code, null, `Skipped — ${why}`, {}, { skipped: true });
  const tolTotal = porec ? r2(Math.max(POLICY.tolerance_pct * porec.net_total, POLICY.tolerance_abs_floor[porec.currency] ?? 0)) : null;
  const tolLabel = porec ? (POLICY.tolerance_pct * porec.net_total >= (POLICY.tolerance_abs_floor[porec.currency] ?? 0) ? `(${pctStr(POLICY.tolerance_pct)})` : `(floor ${porec.currency} ${money(POLICY.tolerance_abs_floor[porec.currency])})`) : '';

  // R1
  if (!vendor.matched) {
    const top = vendor.candidates[0];
    const v = top && VENDORS.find((x) => x.vendor_id === top.vendor_id);
    add('R1', false, `"${norm.vendor_name}" is not in the vendor master${v ? `; closest is ${v.legal_name} at ${Math.round(top.score * 100)}%` : ''}`, { vendor_name: norm.vendor_name, candidates: vendor.candidates });
  } else if (vendor.status !== 'approved') {
    add('R1', false, `${vendor.legal_name} is ${vendor.status}`, { vendor_id: vendor.vendor_id, status: vendor.status }, { severity: 'HOLD' });
  } else add('R1', true, `${vendor.legal_name} (${vendor.vendor_id}) is an approved vendor`, { vendor_id: vendor.vendor_id, status: vendor.status });

  // R2
  if (po.method === 'not_found') add('R2', false, `PO reference ${norm.po_references.join(', ')} does not exist`, { references: norm.po_references }, { severity: 'REJECT' });
  else if (po.matched && po.status === 'closed') add('R2', false, `${po.po_number} is closed`, { po_number: po.po_number, status: po.status }, { severity: 'REJECT' });
  else if (po.matched && po.vendor_mismatch) add('R2', false, `${po.po_number} belongs to ${po.vendor_id}, not ${vendor.vendor_id}`, { po_number: po.po_number, po_vendor_id: po.vendor_id });
  else if (po.method === 'explicit') add('R2', true, `${po.po_number} is open and belongs to ${vendor.vendor_id}`, { po_number: po.po_number, method: 'explicit' });
  else if (po.method === 'inferred') add('R2', true, `${po.po_number} inferred (score ${po.score}); confirm with requester`, { po_number: po.po_number, method: 'inferred', score: po.score }, { warn: 'PO inferred, confirm with requester' });
  else if (po.method === 'ambiguous') add('R2', false, `No PO reference; ${po.candidates.length} candidates and none is a clear match`, { candidates: po.candidates });
  else add('R2', false, 'No PO reference on the invoice and no open PO for this vendor', {});

  // R3
  const live = ledger.filter((r) => r.decision !== 'REJECT');
  const invNo = normRef(norm.invoice_number);
  let dup = null;
  if (vendor.vendor_id && invNo) dup = live.find((r) => r.vendor_id === vendor.vendor_id && normRef(r.invoice_number) === invNo) && { kind: 'vendor_invoice_number', row: live.find((r) => r.vendor_id === vendor.vendor_id && normRef(r.invoice_number) === invNo) };
  if (!dup && fileHash) { const row = live.find((r) => r.file_hash && r.file_hash === fileHash); if (row) dup = { kind: 'file_hash', row }; }
  if (!dup && vendor.vendor_id && norm.invoice_date) {
    const row = live.find((r) => r.vendor_id === vendor.vendor_id && Math.abs(r.net_total - net) < 0.005 && Math.abs(dayDiff(r.invoice_date, norm.invoice_date)) <= POLICY.duplicate_date_window_days);
    if (row) dup = { kind: 'vendor_amount_date', row };
  }
  if (dup) {
    const how = { vendor_invoice_number: 'same vendor and invoice number', file_hash: 'identical file', vendor_amount_date: `same vendor and net amount within ${POLICY.duplicate_date_window_days} days` }[dup.kind];
    add('R3', false, `Duplicate of invoice ${dup.row.invoice_number ?? '(no number)'} dated ${dup.row.invoice_date} (${how}; ${dup.row.decision}, processed ${dup.row.processed_at.slice(0, 10)})`, { match: dup.kind, ledger_invoice_number: dup.row.invoice_number, ledger_invoice_date: dup.row.invoice_date, ledger_decision: dup.row.decision, ledger_source: dup.row.source ?? 'seed', ledger_run_id: dup.row.run_id ?? null });
  } else add('R3', true, 'No earlier invoice with this vendor and number, file, or amount and date', {});

  // R4–R7 require a matched PO
  if (!porec) {
    ['R4', 'R5', 'R6', 'R7'].forEach((c) => skip(c, 'no matched PO'));
  } else {
    const billed = po.billed_net_to_date;
    // R4
    const over = r2(net - porec.net_total);
    if (net > porec.net_total + tolTotal) add('R4', false, `Invoice net ${money(net)} ${cur} exceeds PO net ${money(porec.net_total)} by ${money(over)}; tolerance is ${money(tolTotal)} ${tolLabel}`, { invoice_net: net, po_net: porec.net_total, delta: over, tolerance: tolTotal });
    else if (net < porec.net_total - tolTotal && billed === 0) add('R4', true, `Invoice net ${money(net)} is below PO net ${money(porec.net_total)}; partial invoice, PO remains open`, { invoice_net: net, po_net: porec.net_total, delta: over, tolerance: tolTotal }, { warn: 'partial invoice; PO remains open' });
    else if (net < porec.net_total - tolTotal) add('R4', true, `Invoice net ${money(net)} is below PO net ${money(porec.net_total)}; R5 covers the cumulative position`, { invoice_net: net, po_net: porec.net_total, delta: over, tolerance: tolTotal });
    else add('R4', true, `Invoice net ${money(net)} ${cur} is within ${money(tolTotal)} of PO net ${money(porec.net_total)}`, { invoice_net: net, po_net: porec.net_total, delta: over, tolerance: tolTotal });
    // R5
    const cum = r2(billed + net);
    const overshoot = r2(cum - porec.net_total);
    if (billed === 0) add('R5', null, 'Not evaluated: nothing previously billed on this PO; R4 covers the single-invoice check', {}, { skipped: true });
    else if (cum > porec.net_total + tolTotal) add('R5', false, `Billed to date ${money(billed)} + this invoice ${money(net)} = ${money(cum)} ${cur}, exceeding PO ${money(porec.net_total)} by ${money(overshoot)} (tolerance ${money(tolTotal)})`, { billed_net_to_date: billed, invoice_net: net, po_net: porec.net_total, overshoot, tolerance: tolTotal });
    else add('R5', true, `Billed to date ${money(billed)} + this invoice ${money(net)} = ${money(cum)} of ${money(porec.net_total)} ${cur}; ${money(Math.max(0, r2(porec.net_total - cum)))} remains`, { billed_net_to_date: billed, invoice_net: net, po_net: porec.net_total, overshoot, tolerance: tolTotal });
    // R6
    const lines = po.line_matches.map((m) => {
      const il = norm.line_items[m.invoice_line - 1];
      const pl = porec.lines.find((l) => l.line_no === m.po_line);
      const delta_pct = pl.unit_price ? r2(((il.unit_price - pl.unit_price) / pl.unit_price) * 100) : 0;
      return { invoice_line: m.invoice_line, po_line: m.po_line, description: il.description, invoice_unit_price: il.unit_price, po_unit_price: pl.unit_price, delta_pct, invoice_quantity: il.quantity, po_quantity: pl.quantity, within: Math.abs(il.unit_price - pl.unit_price) <= POLICY.tolerance_pct * pl.unit_price + 1e-9 };
    });
    const bad = lines.filter((l) => !l.within);
    const qtyOver = lines.filter((l) => l.invoice_quantity > l.po_quantity);
    const unmatchedAmt = r2(po.unmatched_invoice_lines.reduce((s, i) => s + (norm.line_items[i - 1].amount ?? 0), 0));
    const ev = { lines, unmatched_invoice_lines: po.unmatched_invoice_lines, unmatched_amount: unmatchedAmt, tolerance_pct: POLICY.tolerance_pct };
    if (bad.length) add('R6', false, bad.map((l) => `Line ${l.invoice_line} "${l.description}": unit price ${money(l.invoice_unit_price)} vs PO ${money(l.po_unit_price)} (${l.delta_pct > 0 ? '+' : ''}${l.delta_pct}%, tolerance ${pctStr(POLICY.tolerance_pct)})`).join('; '), ev);
    else if (unmatchedAmt > tolTotal) add('R6', false, `${po.unmatched_invoice_lines.length} invoice line(s) worth ${money(unmatchedAmt)} have no matching PO line`, ev);
    else if (qtyOver.length) add('R6', true, `Unit prices within ${pctStr(POLICY.tolerance_pct)}; quantity on line ${qtyOver.map((l) => l.invoice_line).join(', ')} exceeds the PO line`, ev, { warn: `quantity on line ${qtyOver.map((l) => l.invoice_line).join(', ')} exceeds PO` });
    else if (po.unmatched_invoice_lines.length) add('R6', true, `Matched lines within tolerance; ${po.unmatched_invoice_lines.length} small unmatched line(s)`, ev, { warn: 'unmatched invoice lines below tolerance' });
    else add('R6', true, `All ${lines.length} line${lines.length === 1 ? '' : 's'} within ${pctStr(POLICY.tolerance_pct)} of PO unit prices`, ev);
    // R7
    if (cur === porec.currency) add('R7', true, `Invoice and PO are both in ${cur}`, { invoice_currency: cur, po_currency: porec.currency });
    else add('R7', false, `Invoice currency ${cur} differs from PO currency ${porec.currency}`, { invoice_currency: cur, po_currency: porec.currency });
  }

  // R8
  const missing = ['invoice_number', 'invoice_date', 'total', 'vendor_name'].filter((k) => norm[k] == null);
  const arith = integ.checks.filter((c) => ['lines_sum_subtotal', 'subtotal_tax_total'].includes(c.code) && !c.passed);
  if (missing.length || arith.length) add('R8', false, [missing.length ? `Missing: ${missing.map((m) => m.replace('_', ' ')).join(', ')}` : '', ...arith.map((c) => `${c.code}: ${c.detail}`)].filter(Boolean).join('; '), { missing, failed_checks: arith.map((c) => c.code) });
  else add('R8', true, 'Invoice number, date, total and vendor present; arithmetic reconciles', { missing: [] });

  // R9
  if (!norm.invoice_date) add('R9', false, 'No invoice date to check', {});
  else {
    const age = dayDiff(today, norm.invoice_date);
    if (age < -POLICY.future_date_grace_days) add('R9', false, `Invoice date ${norm.invoice_date} is ${-age} days in the future`, { invoice_date: norm.invoice_date, today, age_days: age });
    else if (age > POLICY.date_window_days) add('R9', false, `Invoice date ${norm.invoice_date} is ${age} days old (limit ${POLICY.date_window_days})`, { invoice_date: norm.invoice_date, today, age_days: age });
    else add('R9', true, `Invoice date ${norm.invoice_date} is ${age} days old, inside the ${POLICY.date_window_days}-day window`, { invoice_date: norm.invoice_date, today, age_days: age });
  }

  // R10
  const cc = integ.critical_confidence;
  const presentFields = ['invoice_number', 'total', 'vendor_name'].filter((k) => norm[k] != null);
  const weakest = presentFields.length ? presentFields.reduce((a, b) => (cc[b] < cc[a] ? b : a)) : null;
  if (!weakest) add('R10', true, 'No critical field was found, so there is no extraction confidence to assess (R8 covers the missing fields)', { ...cc, floor: POLICY.confidence_floor }, { warn: 'no fields to assess' });
  else if (cc.min >= POLICY.confidence_floor) add('R10', true, `Lowest critical-field confidence is ${cc.min.toFixed(2)} (${weakest}), floor ${POLICY.confidence_floor}`, { ...cc, floor: POLICY.confidence_floor, weakest });
  else add('R10', false, `${weakest} confidence ${cc.min.toFixed(2)} is below the ${POLICY.confidence_floor} floor`, { ...cc, floor: POLICY.confidence_floor, weakest });

  const failed_hold = results.filter((r) => r.passed === false && r.severity === 'HOLD').map((r) => r.code);
  const failed_reject = results.filter((r) => r.passed === false && r.severity === 'REJECT').map((r) => r.code);
  const passedN = results.filter((r) => r.passed === true).length;
  const skippedN = results.filter((r) => r.skipped).length;
  const fails = [...failed_reject, ...failed_hold];
  const summary = fails.length
    ? `${passedN} passed, ${fails.length} failed (${[failed_reject.length ? `REJECT: ${failed_reject.join(', ')}` : '', failed_hold.length ? `HOLD: ${failed_hold.join(', ')}` : ''].filter(Boolean).join('; ')})${skippedN ? `, ${skippedN} skipped` : ''}.`
    : `All ${passedN} evaluated rules passed${warnings.length ? ` with ${warnings.length} warning${warnings.length > 1 ? 's' : ''}` : ''}${skippedN ? `, ${skippedN} skipped` : ''}.`;
  return { output: { results, failed_hold, failed_reject, warnings }, summary, warnings, status: fails.length ? 'warn' : 'done', vrec, porec, tolTotal };
}

function reasonText(r, cur) {
  const e = r.evidence;
  switch (r.code) {
    case 'R1': return r.severity === 'REJECT' ? `Vendor "${e.vendor_name}" is not in the vendor master` : `Vendor is ${e.status}`;
    case 'R2': return r.detail;
    case 'R3': return `Duplicate of ${e.ledger_invoice_number} dated ${e.ledger_invoice_date}, already ${e.ledger_decision === 'APPROVE' ? 'approved' : 'on hold'}`;
    case 'R4': return `Invoice net exceeds PO by ${money(e.delta)} ${cur} (tolerance ${money(e.tolerance)})`;
    case 'R5': return `Cumulative billing ${money(r2(e.billed_net_to_date + e.invoice_net))} ${cur} would exceed PO ${money(e.po_net)} by ${money(e.overshoot)}`;
    case 'R6': return r.detail;
    case 'R7': return r.detail;
    case 'R8': return r.detail;
    case 'R9': return r.detail;
    case 'R10': return r.detail;
    default: return r.detail;
  }
}

function decision(ctx, ruleRes) {
  const { norm, match, sample } = ctx;
  const { results, failed_hold, failed_reject, warnings } = ruleRes.output;
  const { vrec, porec } = ruleRes;
  const cur = norm.currency;
  const dec = failed_reject.length ? 'REJECT' : failed_hold.length ? 'HOLD' : 'APPROVE';
  const failing = results.filter((r) => r.passed === false);
  const reasons = failing.map((r) => ({ code: r.code, text: reasonText(r, cur) }));
  const vendorName = match.vendor.legal_name ?? norm.vendor_name;
  const gross = norm.total;
  const word = { APPROVE: 'approved', HOLD: 'on hold', REJECT: 'rejected' }[dec];
  const sentences = [`Invoice ${norm.invoice_number ?? 'with no number'} from ${vendorName} for ${cur} ${money(gross)} is ${word}.`];
  reasons.forEach((r) => sentences.push(`${r.text.replace(/\.$/, '')}.`));
  warnings.slice(0, 3).forEach((w) => sentences.push(`Note: ${w.replace(/^R\d+: /, '').replace(/^./, (c) => c.toUpperCase())}.`));
  let booking = null;
  if (dec === 'APPROVE' && porec) {
    const after = r2(porec.net_total - (match.po.billed_net_to_date + norm.subtotal));
    booking = { po_number: porec.po_number, net_amount: norm.subtotal, gross_amount: gross, currency: cur, po_remaining_after: Math.max(0, after) };
    sentences.push(after <= 0.005 ? `Booked against ${porec.po_number}; the PO is now fully consumed.` : `Booked against ${porec.po_number}; ${cur} ${money(after)} remains open on the PO.`);
  }

  // Owner: REJECT reasons first, then vendor (R8), requester, ap.
  const ownerOf = (code) => ({ R1: 'ap', R3: 'ap', R2: 'requester', R4: 'requester', R5: 'requester', R6: 'requester', R7: 'requester', R8: 'vendor', R9: 'ap', R10: 'ap' })[code];
  let owner = 'none';
  let text = `No action needed. Scheduled for payment by ${ctx.x.due_date.value ?? 'the due date'} under ${ctx.x.payment_terms.value ?? 'standard'} terms.`;
  const firstReject = failing.find((r) => r.severity === 'REJECT');
  const holdOwners = failing.filter((r) => r.severity === 'HOLD').map((r) => ownerOf(r.code));
  if (firstReject) {
    owner = 'ap';
    text = firstReject.code === 'R3'
      ? `Close as a duplicate of ${firstReject.evidence.ledger_invoice_number}; reply to ${vendorName} that it was already processed.`
      : firstReject.code === 'R1'
        ? `Do not pay. Check with procurement whether ${vendorName} should be onboarded before any invoice is accepted.`
        : `Do not pay. ${firstReject.detail}; ask the vendor to reissue against a valid PO.`;
  } else if (holdOwners.length) {
    owner = holdOwners.includes('vendor') ? 'vendor' : holdOwners.includes('requester') ? 'requester' : 'ap';
    if (owner === 'vendor') text = `Ask ${vendorName} for the missing ${failing.find((r) => r.code === 'R8').evidence.missing.map((m) => m.replace('_', ' ')).join(', ') || 'details'}${match.po.method === 'inferred' ? `; ${match.po.po_number} inferred, confirm with ${porec.requester_name}` : ''}.`;
    else if (owner === 'requester') {
      const r = failing.find((f) => ['R6', 'R4', 'R5', 'R7', 'R2'].includes(f.code) && f.passed === false);
      text = r.code === 'R6'
        ? `Confirm with ${porec.requester_name} (${porec.po_number}) whether the price change on ${r.evidence.lines.filter((l) => !l.within).map((l) => `"${l.description}" to ${money(l.invoice_unit_price)}`).join(', ')} was agreed.`
        : r.code === 'R5'
          ? `Ask ${porec.requester_name} to approve a PO amendment of ${cur} ${money(r.evidence.overshoot)} on ${porec.po_number}, or to reject the over-billing.`
          : porec ? `Confirm with ${porec.requester_name} (${porec.po_number}): ${r.detail}.` : `Find the right PO for this invoice: ${r.detail}.`;
    } else text = `AP to verify the document manually: ${failing.filter((r) => r.severity === 'HOLD').map((r) => r.detail).join('; ')}.`;
  }

  let draft_email = null;
  const amount = `${cur} ${money(gross)}`;
  if (owner === 'vendor' && vrec) {
    const miss = failing.find((r) => r.code === 'R8').evidence.missing.map((m) => m.replace('_', ' '));
    draft_email = {
      to: vrec.contact_email,
      subject: `Invoice dated ${norm.invoice_date} for ${amount}: ${miss.join(', ') || 'details'} required`,
      body: `Hello ${vrec.legal_name} team,\n\nWe received your invoice dated ${norm.invoice_date} for ${amount}. We cannot process it yet because the following is missing: ${miss.join(', ') || 'arithmetic does not reconcile'}.\n\nPlease reply with a corrected invoice${miss.includes('invoice number') ? ' showing your invoice number' : ''}${match.po.method === 'inferred' ? ` and our purchase order reference (we believe it is ${match.po.po_number})` : ''}. We will process it as soon as we receive it.\n\nThank you,\nAP Automation`,
    };
  } else if (owner === 'requester' && porec) {
    draft_email = {
      to: porec.requester_email,
      subject: `Please confirm: ${norm.invoice_number ?? 'invoice'} from ${vendorName} on ${porec.po_number}`,
      body: `Hi ${porec.requester_name.split(' ')[0]},\n\nInvoice ${norm.invoice_number ?? '(no number)'} from ${vendorName} for ${amount} is on hold against ${porec.po_number}.\n\n${failing.filter((r) => r.severity === 'HOLD').map((r) => `- ${reasonText(r, cur)}`).join('\n')}\n\nCan you confirm whether this was agreed, or whether we should ask the vendor to correct the invoice? Reply to this email and AP will release or return it.\n\nThanks,\nAP Automation`,
    };
  }

  const output = {
    decision: dec,
    confidence: ctx.integ.critical_confidence.min,
    reasons,
    warnings,
    explanation: sentences.join(' '),
    next_action: { owner, text },
    draft_email,
    booking,
  };
  const summary = dec === 'APPROVE'
    ? `APPROVE — booked against ${booking?.po_number ?? 'the PO'}.`
    : `${dec} — ${reasons.length} reason${reasons.length > 1 ? 's' : ''} (${reasons.map((r) => r.code).join(', ')}); next action with ${owner === 'ap' ? 'AP' : owner}.`;
  return { output, summary, warnings: [], status: 'done' };
}

/**
 * Compute every stage for a sample run. Returns an array of seven
 * { key, name, status, summary, warnings, output, fail? } plus run-level fields.
 */
export function computeRun({ sampleId, filename, size, sha256, pageCount, ledger, useCache = false, today = isoDate(new Date()) }) {
  const c = CANNED[sampleId];
  const x = structuredClone(c.extraction);
  const stages = [];
  stages.push({ key: 'intake', output: { filename, size_bytes: size, sha256, page_count: pageCount, sample_id: sampleId }, summary: `Received ${filename} (${(size / 1024).toFixed(1)} KB, ${pageCount} page${pageCount > 1 ? 's' : ''}).`, warnings: [], status: 'done' });
  const da = docAnalysis(sampleId, pageCount);
  stages.push({ key: 'doc_analysis', ...da, status: 'done' });
  const fields = Object.values(x).filter((v) => v && typeof v === 'object' && 'confidence' in v && !Array.isArray(v));
  const found = fields.filter((f) => f.value != null).length;
  stages.push({
    key: 'extraction',
    output: { model: MODEL, extraction: x, usage: c.usage, from_cache: useCache, latency_ms: 0 },
    summary: `${useCache ? 'Used cached extraction: ' : ''}${found} of ${fields.length} fields and ${x.line_items.length} line item${x.line_items.length > 1 ? 's' : ''} extracted${da.output.document_class === 'scanned' ? ' from page images' : ''}; overall confidence ${x.overall_confidence.toFixed(2)}.`,
    warnings: x.document_notes ? [x.document_notes] : [],
    status: 'done',
  });
  const integ = integrity(x);
  stages.push({ key: 'integrity', ...integ });
  const norm = integ.output.normalised;
  const match = matching(norm, ledger);
  stages.push({ key: 'matching', ...match });
  const ctx = { norm, x, integ: integ.output, match: match.output, ledger, fileHash: sha256, today, sample: sampleId };
  const rr = rules(ctx);
  stages.push({ key: 'rules', output: rr.output, summary: rr.summary, warnings: rr.warnings, status: rr.status });
  const dd = decision(ctx, rr);
  stages.push({ key: 'decision', ...dd });
  STAGE_DEFS.forEach((d, i) => Object.assign(stages[i], { name: d.name, index: i + 1 }));

  const dec = dd.output;
  const run = {
    document_class: da.output.document_class,
    decision: dec.decision,
    confidence: dec.confidence,
    vendor_name: match.output.vendor.legal_name ?? norm.vendor_name,
    vendor_id: match.output.vendor.vendor_id,
    invoice_number: norm.invoice_number,
    invoice_date: norm.invoice_date,
    currency: norm.currency,
    net_total: norm.subtotal,
    gross_total: norm.total,
    po_number: match.output.po.po_number,
  };
  const ledgerRow = norm.invoice_number != null || dec.decision === 'APPROVE'
    ? { invoice_number: norm.invoice_number, vendor_id: match.output.vendor.vendor_id, invoice_date: norm.invoice_date, currency: norm.currency, net_total: norm.subtotal, gross_total: norm.total, po_number: match.output.po.po_number, decision: dec.decision, file_hash: sha256 }
    : null;
  return { stages, run, decision: dec, ledgerRow };
}
