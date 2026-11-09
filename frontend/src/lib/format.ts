const numberFmt = new Map<number, Intl.NumberFormat>();
function nf(dp: number) {
  let f = numberFmt.get(dp);
  if (!f) {
    f = new Intl.NumberFormat('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp });
    numberFmt.set(dp, f);
  }
  return f;
}

/** 157200 → "157,200.00". Null-safe. */
export function amount(n: number | null | undefined, dp = 2): string {
  if (n == null || Number.isNaN(n)) return '—';
  return nf(dp).format(n);
}

/** "USD 4,800.00" */
export function money(n: number | null | undefined, currency?: string | null): string {
  if (n == null || Number.isNaN(n)) return '—';
  return currency ? `${currency} ${amount(n)}` : amount(n);
}

export function qty(n: number | null | undefined): string {
  if (n == null) return '—';
  return Number.isInteger(n) ? nf(0).format(n) : nf(2).format(n);
}

/** 0.983 → "0.98" */
export function conf(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toFixed(2);
}

/** 0.48 → "48%" */
export function pct(n: number | null | undefined, dp = 0): string {
  if (n == null || Number.isNaN(n)) return '—';
  return `${(n * 100).toFixed(dp)}%`;
}

/** 290 → "290 ms", 6400 → "6.4 s", 72000 → "1m 12s" */
export function duration(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return '—';
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}

export function bytes(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

const timeFmt = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const pad = (n: number) => String(n).padStart(2, '0');
// Hand-rolled so every browser prints '28 Sep 2026' (some ICU builds say 'Sept').
const fmtDate = (d: Date) => `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
const fmtShort = (d: Date) => `${d.getDate()} ${MONTHS[d.getMonth()]}, ${pad(d.getHours())}:${pad(d.getMinutes())}`;

/** ISO date "2026-10-31" → "31 Oct 2026" (no timezone shift). */
export function isoDate(d: string | null | undefined): string {
  if (!d) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d);
  if (m) return fmtDate(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  const t = Date.parse(d);
  return Number.isNaN(t) ? d : fmtDate(new Date(t));
}

export function clock(ts: string | null | undefined): string {
  if (!ts) return '—';
  const t = Date.parse(ts);
  return Number.isNaN(t) ? '—' : timeFmt.format(new Date(t));
}

export function shortDateTime(ts: string | null | undefined): string {
  if (!ts) return '—';
  const t = Date.parse(ts);
  return Number.isNaN(t) ? '—' : fmtShort(new Date(t));
}

/** "just now", "4 min ago", "3 h ago", else short date. */
export function relative(ts: string | null | undefined, now = Date.now()): string {
  if (!ts) return '—';
  const t = Date.parse(ts);
  if (Number.isNaN(t)) return '—';
  const s = Math.round((now - t) / 1000);
  if (s < 45) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return shortDateTime(ts);
}

export function titleParts(title: string): [string, string] {
  const i = title.indexOf(' — ');
  if (i === -1) return [title, ''];
  return [title.slice(0, i), title.slice(i + 3)];
}

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}
