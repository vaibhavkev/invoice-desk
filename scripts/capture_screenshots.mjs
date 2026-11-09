// Capture the README screenshots from a running backend.
//
// Resets the ledger, runs the eight samples in demo order, overrides EC2b to
// APPROVE, then saves three PNGs under docs/screenshots/. Safe to rerun: every
// run starts from a reset.
//
//   node scripts/capture_screenshots.mjs
//
// Env: BASE_URL (default http://127.0.0.1:8010), USE_CACHE=1 to reuse cached
// extractions instead of calling the API. Playwright is a dev dependency of
// frontend/; install it with `npm i` and `npx playwright install chromium` there.

import { createRequire } from 'node:module';
import { mkdir, readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(ROOT, 'frontend', 'package.json'));
const { chromium } = require('playwright');

const BASE = (process.env.BASE_URL ?? 'http://127.0.0.1:8010').replace(/\/$/, '');
const USE_CACHE = process.env.USE_CACHE === '1';
const OUT = path.join(ROOT, 'docs', 'screenshots');
const RUN_TIMEOUT_MS = 120_000;

const OVERRIDE = {
  decision: 'APPROVE',
  reviewer: 'AP lead',
  note: 'Lena Fischer confirmed the Munich cleaning scope was extended in November; PO-2026-0105 amendment to 16,000 EUR is in approval.',
};

async function api(method, url, body) {
  const res = await fetch(BASE + url, {
    method,
    headers: body ? { 'content-type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`${method} ${url} → ${res.status}: ${text}`);
  return text ? JSON.parse(text) : null;
}

async function waitForRun(id) {
  const deadline = Date.now() + RUN_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const run = await api('GET', `/api/runs/${id}`);
    if (run.status === 'completed' || run.status === 'failed') return run;
    await new Promise((r) => setTimeout(r, 750));
  }
  throw new Error(`run ${id} did not finish within ${RUN_TIMEOUT_MS / 1000}s`);
}

async function runSamples() {
  const samples = JSON.parse(await readFile(path.join(ROOT, 'data', 'samples.json'), 'utf8'))
    .sort((a, b) => a.demo_order - b.demo_order);
  const ids = {};
  for (const s of samples) {
    const { run_id } = await api('POST', '/api/runs', { sample_id: s.id, use_cache: USE_CACHE });
    const run = await waitForRun(run_id);
    const ok = run.status === 'completed' && run.decision === s.expected_decision;
    console.log(`${ok ? 'ok  ' : 'MISS'} ${s.id.padEnd(5)} ${run.status} ${run.decision ?? '-'} (expected ${s.expected_decision})`);
    if (run.status !== 'completed') throw new Error(`${s.id} failed: ${run.error ?? 'see the run page'}`);
    ids[s.id] = run_id;
  }
  return ids;
}

async function shot(page, url, file, prepare) {
  await page.goto(BASE + url, { waitUntil: 'networkidle' });
  await prepare(page);
  await page.waitForTimeout(600); // let entry animations settle
  const target = path.join(OUT, file);
  await page.screenshot({ path: target });
  console.log(`saved docs/screenshots/${file} (${Math.round((await stat(target)).size / 1024)} KB)`);
}

async function showBanner(page) {
  const banner = page.locator('div.shadow-lift[role="status"]').first();
  await banner.waitFor({ state: 'visible', timeout: 15_000 });
  // Put the banner near the top so the stages above it stay partly in view.
  await banner.evaluate((el) => window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 360, behavior: 'instant' }));
}

async function main() {
  await api('GET', '/health');
  await mkdir(OUT, { recursive: true });

  console.log(`Resetting ${BASE}`);
  await api('POST', '/api/admin/reset', { clear_runs: true });
  const ids = await runSamples();

  await api('POST', `/api/runs/${ids.EC2b}/override`, OVERRIDE);
  console.log('ok   EC2b overridden to APPROVE');

  // The headless shell has no PDF viewer, so the preview panel shows the app's
  // "Open PDF in a new tab" fallback. Full Chrome or Edge under Playwright
  // renders the PDF at the wrong zoom, which looks worse.
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      deviceScaleFactor: 2,
      colorScheme: 'light',
      reducedMotion: 'reduce',
    });
    const page = await context.newPage();
    await shot(page, `/runs/${ids.HP}`, 'run-happy-path.png', showBanner);
    await shot(page, `/runs/${ids.EC2b}`, 'run-split-po-override.png', showBanner);
    await shot(page, '/dashboard', 'dashboard.png', async (p) => {
      await p.getByText('Loading…').waitFor({ state: 'detached', timeout: 15_000 }).catch(() => {});
    });
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err.message ?? err);
  process.exit(1);
});
