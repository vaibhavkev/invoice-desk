# Backend — invoice pipeline and API

FastAPI + SQLite (SQLModel). It runs the seven stages in `docs/SPEC.md` §4: intake, doc analysis,
extraction, integrity, matching, rules and decision. It streams them over SSE and keeps every run, stage
and event. Claude is used in stage 3 only. Stages 1, 2 and 4–7 are pure functions with unit tests.

## Setup (Windows, Python 3.10)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

Copy `../.env.example` to `backend/.env` and set the key there. The file is git-ignored and loaded on
startup, so the key reaches processes that did not inherit it, such as ones launched from a shortcut or
the desktop app. Real environment variables win over the file.

Environment (all optional except the key; defaults in brackets):

| var | meaning |
|---|---|
| `ANTHROPIC_API_KEY` | needed for live extraction |
| `EXTRACTION_MODEL` | overrides `config.yaml` `extraction.model` [`claude-opus-5-5`] |
| `EXTRACTION_EFFORT` | overrides `extraction.effort` [`medium`] |
| `DATA_DIR` | reference CSVs + samples [`../data`] |
| `DB_PATH` | SQLite file [`./app.db`] |
| `UPLOAD_DIR` | uploaded PDFs [`./uploads`] |
| `FRONTEND_DIST` | built SPA served at `/` [`../frontend/dist`] |
| `APP_TODAY` | pins "today" for R9 (`YYYY-MM-DD`), for rehearsals [real date] |
| `CONFIG_PATH` | policy file [`../config.yaml`] |

## Run

```powershell
cd backend
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

- `GET /health` gives `{"ok": true, "model": "...", "db": "ok"}`.
- On first start the DB is seeded from `data/*.csv` if the `vendors` table is empty.
- `POST /api/admin/reset` with `{"clear_runs": true}` re-seeds the ledger and deletes runs. Add
  `"reload_reference": true` to also reload vendors and POs after the fixtures are regenerated.
- To pre-warm before a demo, run `.\.venv\Scripts\python tools\warm_cache.py`. It extracts every sample
  into the cache and prints tokens and latency per sample. After that,
  `{"sample_id": "HP", "use_cache": true}` replays from the extraction cache with no API call.
  If the extraction call fails for any reason, including a missing key, the cache is also used
  automatically (stage status `warn`).

## Tests

```powershell
.\.venv\Scripts\python -m pytest                 # deterministic, no network (live test deselected)
.\.venv\Scripts\python -m pytest -m live         # one real API call (HP), needs ANTHROPIC_API_KEY
.\.venv\Scripts\python tools\record_extractions.py   # re-record tests/fixtures/extractions/*.json
```

- `test_rules.py`, `test_matching.py` and `test_integrity.py` use the tiny CSVs in `tests/fixtures/ref/`.
- `test_pipeline_samples.py` resets the ledger, then runs all eight `data/` samples through the real runner
  in `demo_order`, using recorded extractions. For each sample it asserts `expected_decision` and
  `expected_rule_failures`.
- `test_api.py` covers the HTTP API, SSE replay, the error shape, reset, the SPA fallback and the cache
  semantics.
- Re-record the extractions if the sample PDFs' content changes.

## Layout

```
app/main.py            FastAPI app, error shape, /health, SPA fallback
app/config.py          config.yaml + env + backend/.env
app/db.py, models.py   SQLite tables (vendors, purchase_orders, po_lines, ledger, runs, run_stages, run_events, extraction_cache)
app/refdata.py         in-memory snapshot of vendors/POs/ledger used by the pure stages
app/seed.py            CSV loading
app/extraction/        schema.py (SPEC 3.1), prompt.py (SPEC 3.2 verbatim), client.py (API call), cache.py
app/matching/          vendor.py, po.py
app/rules/             rules.py (R1–R10), engine.py (evaluate + aggregate)
app/pipeline/          runner.py (stages, events, ledger write), events.py (pub/sub), stages/*.py
app/api/               runs.py (runs + SSE), reference.py (samples, reference, stats, admin), deps.py
tools/record_extractions.py, warm_cache.py
```

## Interpretation notes (where SPEC left room)

- **Rule severity on passed rules:** `severity` is the rule's nominal failure severity, or `WARN` if
  it passed with a warning. Each result also has `skipped` and a `warnings` list.
- **next_action priority:** SPEC 4.7 sets the owner: any REJECT failure goes to `ap`, else `vendor`, else
  `requester`, else `ap`. Within that owner, the next-action text comes from the first failing rule in a
  priority list. REJECT: R1, R3, R2. HOLD: R8, R10, R9, R1, R2, R4, R6, R5, R7. R2 `none` goes to `ap`,
  since there is no requester to ask, and a suspended vendor (R1 HOLD) sits in the last `ap` tier. The
  requester email lists every failing requester-owned rule (max 3).
- **Embedded PO references:** a quoted reference counts as explicit if it equals a PO number or
  contains one, after normalisation (e.g. "as per your order PO-2026-0107").
- **Integrity:** an invoice with no line items fails `lines_sum_subtotal`. If the lines are printed
  tax-inclusive and add up to the total, the check passes and the lines are converted to net for R6,
  with a warning. A missing subtotal is derived as total − tax, with a warning.
- **R9** is skipped when there is no readable invoice date. R8 already holds the invoice in that case.
- **Ledger rows** from runs that hold an invoice count as "seen" for R3. Re-running the same sample
  without a reset is therefore REJECTed as a duplicate, which is correct behaviour.
