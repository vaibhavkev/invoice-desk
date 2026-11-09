# Frontend: Invoice Desk

Vite + React 18 + TypeScript (strict) + Tailwind. React Router for routing, lucide-react for icons; no other runtime dependencies.

## Commands

Run everything from `frontend/`.

```bash
npm install          # once
npm run mock         # mock API + SSE on http://localhost:8000 (Node built-ins only)
npm run dev          # Vite on http://localhost:5173, proxies /api and /health to :8000
npm run build        # type-check, then build to frontend/dist (served by FastAPI)
npm run typecheck    # tsc --noEmit only
```

Use either `npm run mock` or the real backend on port 8000, not both. To point the dev server somewhere else, set `API_TARGET=http://host:port` before `npm run dev`.

### Mock server options

```bash
npm run mock:fast            # stage delays divided by 5
npm run mock -- --drop       # end every live SSE stream after 2.5 s (tests reconnect + dedupe)
npm run mock -- --no-history # start with an empty dashboard
```

The same switches are available as the environment variables `MOCK_FAST=1`, `MOCK_SSE_DROP=1` and `MOCK_HISTORY=0`.

The mock implements every endpoint in SPEC §5 and the SSE stream in §6, with realistic timing (300–800 ms per stage, 4–7 s for extraction). It serves the real PDFs from `data/samples/` when they exist and generates placeholder PDFs when they don't. Stages 4–7 are computed from canned extractions against an in-memory ledger, so state carries across runs: EC2b holds after EC2a, re-running a sample is rejected as a duplicate, and `POST /api/admin/reset` restores the seed. Uploading a file that is not one of the samples fails at extraction with a clear message.

## Screens

| Route | What it shows |
|---|---|
| `/` | Drop zone and sample list on the left, seven-stage preview in the centre. Clicking a sample starts a run. |
| `/runs/:id` | Live run: header, stage timeline with expandable outputs, decision banner. Finished runs render from `GET /api/runs/{id}` with no SSE. |
| `/dashboard` | KPI tiles, runs table with decision filter and search (refreshes every 10 s), open PO balances. |
| `/reference` | Tabs for purchase orders (billed and remaining, expandable lines and invoices), ledger and vendors. Includes "Reset demo data". |

## Layout of `src/`

```
types.ts                 every SPEC object, field names exactly as the API sends them
lib/api.ts               fetch wrapper, typed endpoints, error shape
lib/sse.ts               SSE parser + reconnecting client (Last-Event-ID, seq dedupe, stall watchdog)
lib/format.ts, stages.ts formatting helpers, the fixed seven-stage skeleton
hooks/useRun.ts          run state: detail snapshot merged with live events
hooks/useResource.ts     fetch + optional polling (pauses while the tab is hidden)
components/run/*         timeline, per-stage bodies, decision banner, sample list, preview
pages/*                  RunPage, DashboardPage, ReferencePage
mock/*                   server.mjs (HTTP + SSE), engine.mjs (stages 4–7), data.mjs, pdf.mjs
```
