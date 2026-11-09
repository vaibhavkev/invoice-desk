/**
 * USD per million tokens, keyed by model id. Used only for the "about $x" estimate on the extraction card.
 * Anthropic list prices as of November 2026 (standard tier, no caching or batch discount).
 */
export const PRICES: Record<string, { input: number; output: number }> = {
  'claude-opus-5-5': { input: 4, output: 20 },
  'claude-sonnet-5-5': { input: 2, output: 10 },
};

/** Estimated cost in USD, or null when the model is not in the table. */
export function estimateCost(model: string, inputTokens: number, outputTokens: number): number | null {
  const p = PRICES[model];
  return p ? (inputTokens * p.input + outputTokens * p.output) / 1_000_000 : null;
}

/** 5400 → "5.4k", 980 → "980" */
export function tokens(n: number): string {
  return n >= 1000 ? `${+(n / 1000).toFixed(1)}k` : String(n);
}

/** 0.0487 → "$0.05", 0.0031 → "$0.003" */
export function usd(n: number): string {
  return n >= 0.01 ? `$${n.toFixed(2)}` : `$${n.toPrecision(1)}`;
}
