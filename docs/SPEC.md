# SPEC — PS-1 Invoice Processing

The contract the code is built against: stage outputs, rules, API, events, database and UI.
Where the code and this file disagree, this file wins and the code is fixed.

Status key used throughout: **MUST** = contract, **SHOULD** = strong default, **MAY** = optional.

---

## 0. Repo layout

```
Zamp Case Study/
├── config.yaml                 # policy knobs (see §1)
├── .env.example
├── docs/
│   ├── SPEC.md                 # this file
├── data/
│   ├── vendors.csv
│   ├── purchase_orders.csv
│   ├── po_lines.csv
│   ├── ledger_seed.csv
│   ├── samples.json
│   └── samples/*.pdf
├── scripts/
│   └── generate_fixtures.py
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py             # FastAPI app, mounts /api and frontend/dist
│   │   ├── config.py           # loads config.yaml + env
│   │   ├── db.py               # SQLite via SQLModel
│   │   ├── models.py           # DB tables
│   │   ├── schemas.py          # API + stage pydantic models
│   │   ├── seed.py             # loads data/*.csv into DB
│   │   ├── api/                # routers
│   │   ├── pipeline/
│   │   │   ├── runner.py       # orchestrates stages, emits events
│   │   │   └── stages/         # intake.py, doc_analysis.py, extraction.py,
│   │   │                       # integrity.py, matching.py, rules.py, decision.py
│   │   ├── extraction/         # schema.py (InvoiceExtraction), prompt.py, client.py
│   │   ├── matching/           # vendor.py, po.py
│   │   └── rules/              # engine.py, rules.py (R1–R10)
│   └── tests/
├── frontend/
│   ├── package.json, vite.config.ts, tailwind config
│   ├── src/
│   ├── mock/server.mjs         # mock API + SSE for development without backend
│   └── dist/                   # build output, served by FastAPI (git-ignored)
└── Dockerfile, docker-compose.yml, railway.json
```

Working directory for backend commands is `backend/`. Working directory for frontend commands
is `frontend/`. Scripts are run from repo root: `python scripts/generate_fixtures.py`.

---

## 1. Configuration

`config.yaml` at repo root. Backend MUST load it at startup and expose values via `app.config`.

```yaml
policy:
  tolerance_pct: 0.02                # applied to totals and unit prices
  tolerance_abs_floor:               # per currency, applied to TOTALS only
    USD: 25
    EUR: 25
    GBP: 20
    INR: 2000
  confidence_floor: 0.75             # R10: min confidence on critical fields
  date_window_days: 90               # R9: invoice must be within this many days
  future_date_grace_days: 0          # R9: invoice date may not be after today + grace
  duplicate_date_window_days: 3      # R3: fuzzy duplicate window
  scanned_chars_per_page: 50         # §4 stage 2: fewer chars than this = scanned page
extraction:
  model: claude-opus-5-5             # overridden by env EXTRACTION_MODEL
  effort: medium
  max_tokens: 8000
  cache_fallback: true               # on API error, use cached extraction if present
```

Environment variables (`.env.example`):

```
ANTHROPIC_API_KEY=
EXTRACTION_MODEL=claude-opus-5-5
DATA_DIR=../data            # relative to backend/
DB_PATH=./app.db            # relative to backend/
PORT=8000
```

---

## 2. Reference data (CSV)

All CSVs are UTF-8, comma-separated, header row, no index column. Money is a decimal string
with two decimals (`4800.00`). Dates are ISO `YYYY-MM-DD`. Booleans are `true`/`false`.

### 2.1 `vendors.csv`

| column | type | notes |
|---|---|---|
| vendor_id | string | `V001`… |
| legal_name | string | as registered |
| aliases | string | pipe-separated alternative names, may be empty |
| tax_id | string | country-appropriate format |
| country | string | ISO-2 |
| currency | string | ISO-4217 |
| status | enum | `approved` / `suspended` |
| payment_terms_days | int | |
| contact_email | string | used in draft emails |

### 2.2 `purchase_orders.csv`

| column | type | notes |
|---|---|---|
| po_number | string | `PO-2026-0101`… |
| vendor_id | string | FK |
| po_date | date | |
| currency | string | MUST equal vendor currency |
| net_total | money | **PO amounts are NET of tax.** All PO comparisons use invoice net (subtotal). |
| status | enum | `open` / `closed` |
| requester_name | string | PO owner |
| requester_email | string | used in draft emails |
| description | string | one line |

### 2.3 `po_lines.csv`

| column | type |
|---|---|
| po_number | string |
| line_no | int (1-based) |
| description | string |
| quantity | decimal |
| unit_price | money (net) |
| line_total | money (= quantity × unit_price) |

### 2.4 `ledger_seed.csv` — invoices already processed before our app existed

| column | type | notes |
|---|---|---|
| invoice_number | string | |
| vendor_id | string | |
| invoice_date | date | |
| currency | string | |
| net_total | money | |
| gross_total | money | |
| po_number | string | may be empty |
| decision | enum | `APPROVE` / `HOLD` / `REJECT` |
| file_hash | string | sha256 hex or empty |
| processed_at | datetime ISO | |

### 2.5 `samples.json` — the demo picker

```json
[
  {
    "id": "HP",
    "title": "Happy path — Meridian Cloud, PO matches exactly",
    "scenario": "happy_path",
    "file": "samples/HP_meridian_MCS-10422.pdf",
    "vendor_id": "V003",
    "expected_decision": "APPROVE",
    "expected_rule_failures": [],
    "demo_order": 1,
    "notes": "Clean digital PDF. Two lines, no tax, explicit PO."
  }
]
```

`expected_rule_failures` lists rule codes expected to fail (e.g. `["R3"]`). Entries also carry an
`invoice` object (invoice_number, date, currency, po_reference, net, tax_rate, tax, gross) used by
the fixture verifier; consumers MUST ignore unknown keys. The backend integration test MUST reset
the ledger, then run every sample **in `demo_order`** (EC2b depends on EC2a having been approved)
and assert both `expected_decision` and `expected_rule_failures`.

### 2.6 Fixed scenario data (B generates exactly this; A tests against exactly this)

Vendors:

| id | legal_name | country | currency | tax_id | status | aliases |
|---|---|---|---|---|---|---|
| V001 | Northwind Office Supplies Ltd | GB | GBP | GB123456789 | approved | Northwind Office Supplies |
| V002 | Apex Industrial Components Pvt Ltd | IN | INR | 27AAACA1234A1Z5 | approved | Apex Industrial |
| V003 | Meridian Cloud Services Inc | US | USD | 12-3456789 | approved | Meridian Cloud |
| V004 | Helios Facility Management GmbH | DE | EUR | DE123456789 | approved | Helios FM |
| V005 | Bluegrass Logistics LLC | US | USD | 98-7654321 | **suspended** | |
| V006 | Quantum Lab Supplies BV | NL | EUR | NL123456789B01 | approved | Quantum Lab |

Scenario POs (B MAY add 6–8 more filler POs across vendors, some `closed`):

| po_number | vendor | currency | net_total | lines (description × qty × unit) | status |
|---|---|---|---|---|---|
| PO-2026-0102 | V002 | INR | 150000.00 | Stainless steel flange DN50 × 200 × 450.00; Hex bolt M12 (box of 100) × 50 × 1200.00 | open |
| PO-2026-0103 | V001 | GBP | 1250.00 | Ergonomic chair model K2 × 5 × 180.00; Desk lamp LED × 10 × 35.00 | open |
| PO-2026-0105 | V004 | EUR | 12000.00 | Facility cleaning services – monthly × 3 × 4000.00 | open |
| PO-2026-0106 | V003 | USD | 2400.00 | Managed backup service – Sep 2026 × 1 × 2400.00 | open |
| PO-2026-0107 | V003 | USD | 4800.00 | Cloud hosting – Oct 2026 × 1 × 3200.00; Object storage 10TB × 1 × 1600.00 | open |
| PO-2026-0109 | V006 | EUR | 3150.00 | Nitrile gloves (box of 100) × 150 × 9.00; Pipette tips 1000µl (rack) × 60 × 30.00 | open |

Ledger seed MUST include (plus 6–8 unrelated historical rows):

| invoice_number | vendor | date | net | gross | po | decision |
|---|---|---|---|---|---|---|
| HFM-2026-091 | V004 | 2026-10-05 | 4000.00 | 4760.00 | PO-2026-0105 | APPROVE |
| MCS-10398 | V003 | 2026-10-01 | 2400.00 | 2400.00 | PO-2026-0106 | APPROVE |

Sample invoices (all dated so they sit inside the 90-day window from Nov 2026):

| id | file name | vendor | invoice_no | date | content | expected |
|---|---|---|---|---|---|---|
| HP | HP_meridian_MCS-10422.pdf | V003 | MCS-10422 | 2026-10-31 | PO-2026-0107 explicit; lines exactly as PO; no tax; total 4800.00 | APPROVE |
| EC1 | EC1_scanned_northwind_NW-7781.pdf | V001 | NW-7781 | 2026-10-27 | **image-only PDF** (render → rotate 1.5° → light noise → re-wrap). PO-2026-0103; lines as PO; subtotal 1250.00; VAT 20% 250.00; total 1500.00 | APPROVE via the vision path; doc_analysis reports `scanned` and adds a warning. No stricter confidence floor for scans; R10 applies as usual |
| EC2a | EC2a_split_helios_HFM-2026-104.pdf | V004 | HFM-2026-104 | 2026-10-30 | PO-2026-0105; "Facility cleaning services – October" × 1 × 4000.00; VAT 19% 760.00; total 4760.00 | APPROVE; remaining 4000.00 |
| EC2b | EC2b_split_helios_HFM-2026-118.pdf | V004 | HFM-2026-118 | 2026-10-31 | PO-2026-0105; "Facility cleaning services – Nov + Dec" × 2 × 4000.00; VAT 19% 1520.00; total 9520.00 | HOLD (R5) **if run after EC2a**; APPROVE "PO fully consumed" if run on a fresh ledger |
| EC3 | EC3_variance_apex_AIC-26-27-0931.pdf | V002 | AIC/26-27/0931 | 2026-10-29 | PO-2026-0102; flange × 200 × **486.00**; bolts × 50 × 1200.00; subtotal 157200.00; GST 18% 28296.00; total 185496.00 | HOLD (R4, R6; R5 skipped as nothing was billed before) |
| EC4 | EC4_duplicate_meridian_MCS-10398_resent.pdf | V003 | MCS-10398 | 2026-10-01 | Same content as ledger row, **different template** and a footer "Reminder: payment overdue" so the hash differs | REJECT (R3; R5 also fails since the PO is fully billed) |
| EC5 | EC5_missing_quantum_no-number.pdf | V006 | *(none)* | 2026-10-30 | **No invoice number, no PO reference.** Lines exactly as PO-2026-0109; VAT 21% 661.50; total 3811.50 | HOLD (R8 only; R10 ignores absent fields), PO inferred, draft email |
| EC6 | EC6_unknown_silverline_SCP-0042.pdf | *(unknown)* "Silverline Consulting Partners" | SCP-0042 | 2026-10-28 | PO ref "PO-2026-0199" (does not exist); 1 line 2500.00 USD | REJECT (R1, R2 not_found) |

`expected_rule_failures` in `samples.json` is derived from the §4.6 logic and is authoritative over
the shorthand above. EC2b's expectation (HOLD) assumes EC2a was approved first; on a fresh ledger it
APPROVEs and fully consumes the PO. Helios samples deliberately use German number format
(`4.000,00 €`) and `DD.MM.YYYY` dates.

Six visually distinct templates, one per vendor: two-column header, table-heavy, logo block,
minimal/plain, bundled line ("Services as per PO"), tax-inclusive layout. EC4 uses a
different template from the one that vendor normally uses.

---

## 3. Extraction schema and prompt

### 3.1 Pydantic schema (`backend/app/extraction/schema.py`)

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Generic, TypeVar

class Evidence(BaseModel):
    quote: str = Field(description="Verbatim text from the document supporting the value, max 120 chars")
    page: int = Field(description="1-based page number")

class StrField(BaseModel):
    value: Optional[str]
    confidence: float = Field(ge=0, le=1)
    evidence: Optional[Evidence]

class NumField(BaseModel):
    value: Optional[float]
    confidence: float = Field(ge=0, le=1)
    evidence: Optional[Evidence]

class LineItem(BaseModel):
    description: str
    quantity: Optional[float]
    unit_price: Optional[float]
    amount: Optional[float]            # line total as printed
    confidence: float = Field(ge=0, le=1)

class InvoiceExtraction(BaseModel):
    vendor_name: StrField
    vendor_tax_id: StrField
    vendor_address: StrField
    bill_to_name: StrField
    invoice_number: StrField
    invoice_date: StrField              # ISO YYYY-MM-DD or null
    due_date: StrField
    currency: StrField                  # ISO-4217
    po_references: List[str]            # all PO-like references found, verbatim, may be empty
    line_items: List[LineItem]
    subtotal: NumField                  # net of tax
    tax_amount: NumField
    tax_rate_pct: NumField
    total: NumField                     # gross, amount payable
    payment_terms: StrField
    document_notes: str                 # anything odd: handwriting, stamps, missing sections
    overall_confidence: float = Field(ge=0, le=1)
```

Confidence semantics (MUST appear in the prompt): 1.0 = printed clearly and unambiguous;
0.8 = clearly printed but label ambiguous or derived (e.g. total computed from parts);
0.5 = partially legible or inferred from context; 0.0 = absent, `value` is null.

### 3.2 System prompt (`backend/app/extraction/prompt.py`)

```
You are an accounts-payable document analyst. You extract structured data from a single
vendor invoice so that a deterministic rules engine can decide whether to pay it. You do
not decide anything yourself.

Read the whole document, including scanned or image pages. Extract every field in the
schema. For each field give the value, a confidence score, and the verbatim evidence quote
with its page number.

Confidence scale: 1.0 printed clearly and unambiguously; 0.8 clearly printed but the label
is ambiguous or the value is derived from other printed values; 0.5 partially legible or
inferred from context; 0.0 absent (set value to null). Never invent a value. A missing
invoice number, date, or total is a null with confidence 0.0, not a guess.

Rules of interpretation:
- vendor_name is the party issuing the invoice, not the customer being billed.
- invoice_number is the vendor's own invoice identifier. Do not use the PO number, a
  customer number, or a quote number as the invoice number.
- po_references: list every reference that looks like a purchase order number anywhere in
  the document, verbatim, including ones embedded in sentences such as "as per your order
  PO-2026-0107". If none, return an empty list.
- Dates in ISO YYYY-MM-DD. Resolve ambiguous day/month using the vendor's country and any
  other dates in the document; if still ambiguous, lower the confidence to 0.5.
- subtotal is the net amount before tax. If the invoice is tax-inclusive and shows no
  subtotal, compute it from total and tax, mark confidence 0.8, and say so in document_notes.
- total is the amount payable as printed. Do not recompute it; if printed values do not
  add up, report them as printed and describe the discrepancy in document_notes.
- line_items: one entry per printed line. If lines are bundled ("Services as per PO"),
  return the single bundled line as printed. Do not split or merge lines.
- currency: from the symbol or code on the document; if only a symbol such as $ is shown,
  use the vendor's country to disambiguate and lower confidence to 0.8.
- document_notes: mention anything a human reviewer should know: stamps, handwriting,
  "duplicate" or "reminder" markings, missing sections, poor scan quality.
```

### 3.3 API call

The call follows the Anthropic Python SDK's structured-outputs documentation. Required properties:

- Model from config (`claude-opus-5-5` default), `output_config.effort` from config.
- Structured output via `client.messages.parse()` with `InvoiceExtraction` as the schema. No prefill, no forced tool choice.
- PDF passed as a native `document` block (base64, `application/pdf`), placed **before** the text block in the user message.
- For `digital`/`mixed` documents, also pass the text layer dump as a text block labelled "Text layer extracted by pypdf, for reference. The PDF is authoritative."
- Server-side refusal fallback on by default: `betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"` (on the beta messages surface if the SDK requires it). Harmless for invoices; keeps the demo from dying on a classifier false positive.
- Check `stop_reason` before reading content. `max_tokens` or `refusal` → stage fails with a clear message.
- Record `usage` (input/output tokens) on the stage output.
- Timeout 120 s; one retry on connection/429/5xx errors; no retry on 4xx.

### 3.4 Extraction cache

Table `extraction_cache(file_hash, model, extraction_json, usage_json, created_at)`.
MUST always write after a successful call. MUST read only when (a) the API call fails and
`extraction.cache_fallback` is true, in which case the stage completes with status `warn`
and summary "Used cached extraction (API error: …)", or (b) the run was created with
`use_cache=true`.

---

## 4. Pipeline stages — exact outputs

Stage keys, in order: `intake`, `doc_analysis`, `extraction`, `integrity`, `matching`, `rules`, `decision`.

Every stage record:

```json
{
  "key": "matching",
  "index": 5,
  "name": "Vendor & PO matching",
  "status": "done",                     // pending | running | done | warn | failed | skipped
  "started_at": "2026-11-02T10:00:01.120Z",
  "finished_at": "2026-11-02T10:00:01.410Z",
  "duration_ms": 290,
  "summary": "Vendor V003 Meridian Cloud Services Inc (tax id exact). PO-2026-0107 (explicit).",
  "warnings": [],
  "output": { ...stage-specific, below... }
}
```

`summary` is one sentence a non-technical reader understands. `warnings` is a list of short
strings. A `failed` stage stops the run; the run status becomes `failed`. `skipped` is used
for stages after a failure.

### 4.1 `intake`

```json
{ "filename": "HP_meridian_MCS-10422.pdf", "size_bytes": 48211, "sha256": "…",
  "page_count": 1, "sample_id": "HP" }
```
Rejects non-PDF or >15 MB with `failed`.

### 4.2 `doc_analysis`

```json
{ "document_class": "digital",            // digital | scanned | mixed
  "pages": [ { "page": 1, "chars": 1432, "has_text_layer": true } ],
  "text_layer": "…full text or empty…",
  "language_guess": "en" }
```
A page is scanned if `chars < policy.scanned_chars_per_page`. Class: all pages text → `digital`;
none → `scanned`; else `mixed`. `summary` MUST say the class, e.g. "Scanned document, 1 page, no text layer — using vision extraction."

### 4.3 `extraction`

```json
{ "model": "claude-opus-5-5", "extraction": { ...InvoiceExtraction... },
  "usage": { "input_tokens": 5120, "output_tokens": 1820 }, "from_cache": false, "latency_ms": 6400 }
```

### 4.4 `integrity`

```json
{ "normalised": {
     "vendor_name": "Meridian Cloud Services Inc", "vendor_tax_id": "123456789",
     "invoice_number": "MCS-10422", "invoice_date": "2026-10-31", "currency": "USD",
     "po_references": ["PO-2026-0107"], "po_references_normalised": ["PO20260107"],
     "subtotal": 4800.00, "tax_amount": 0.00, "total": 4800.00,
     "line_items": [ { "description": "...", "quantity": 1, "unit_price": 3200.00, "amount": 3200.00 } ]
  },
  "checks": [
     { "code": "lines_sum_subtotal", "passed": true,  "detail": "Lines sum to 4800.00; subtotal 4800.00" },
     { "code": "subtotal_tax_total", "passed": true,  "detail": "4800.00 + 0.00 = 4800.00" },
     { "code": "required_fields",    "passed": true,  "detail": "invoice_number, invoice_date, total, vendor_name present" },
     { "code": "date_parse",         "passed": true,  "detail": "" }
  ],
  "critical_confidence": { "invoice_number": 1.0, "total": 1.0, "vendor_name": 1.0, "min": 1.0 }
}
```
`critical_confidence.min` is the minimum over critical fields whose value is non-null; a null
field is reported with its confidence (0.0) but excluded from `min`.
Normalisation rules: tax ids strip spaces/dashes/dots; PO refs uppercase and strip non-alphanumerics;
money rounded to 2 dp; arithmetic tolerance 0.05 absolute. If `total` is null but subtotal and tax
exist, derive total and add warning "total derived from subtotal + tax". Stage status is `warn` if
any check fails (rules decide the consequence, not this stage).

### 4.5 `matching`

```json
{ "vendor": { "matched": true, "vendor_id": "V003", "legal_name": "…", "status": "approved",
              "method": "tax_id", "score": 1.0,
              "candidates": [ { "vendor_id": "V003", "score": 1.0, "method": "tax_id" } ] },
  "po":     { "matched": true, "po_number": "PO-2026-0107", "method": "explicit",  // explicit | inferred | ambiguous | none | not_found
              "score": 1.0, "status": "open", "vendor_id": "V003", "vendor_mismatch": false,
              "net_total": 4800.00, "billed_net_to_date": 0.00, "remaining_net": 4800.00,
              "candidates": [] ,
              "line_matches": [ { "invoice_line": 1, "po_line": 1, "score": 0.97 } ],
              "unmatched_invoice_lines": [] } }
```

Vendor matching order: (1) normalised tax id exact → `tax_id`, score 1.0; (2) normalised name
equals legal_name or an alias → `alias`, 1.0; (3) `rapidfuzz.fuzz.token_set_ratio` on names
normalised by lowercasing, stripping punctuation and legal suffixes (ltd, limited, inc, llc,
gmbh, bv, pvt, plc, co, corp, corporation) ≥ 90 → `name_fuzzy`, score/100. Else `matched:false`
with top-3 candidates.

PO matching: if any normalised PO reference equals a PO number (normalised the same way) →
`explicit`. If the PO's vendor differs from the matched vendor → `vendor_mismatch:true` (still
report the PO). If no reference and vendor matched: candidates = that vendor's `open` POs;
`score = 0.6 × amount_score + 0.4 × line_score` where `amount_score = max(0, 1 − |invoice_net − remaining_net| / net_total)`
and `line_score` = mean best `token_set_ratio/100` of invoice lines against PO lines. Top candidate
≥ 0.80 and ≥ 0.20 clear of the runner-up → `inferred`; otherwise `ambiguous` with candidates.
No vendor match or no candidates → `none`. Reference given but no such PO → `not_found`.

`billed_net_to_date` = sum of `net_total` over ledger rows with this `po_number` and `decision = APPROVE`
(seed rows and prior runs). Line matches: `token_set_ratio ≥ 80` or an explicit line reference.

### 4.6 `rules`

```json
{ "results": [
    { "code": "R4", "name": "Invoice total within PO tolerance", "passed": false, "severity": "HOLD",
      "detail": "Invoice net 157,200.00 INR exceeds PO net 150,000.00 by 7,200.00; tolerance is 3,000.00 (2%)",
      "evidence": { "invoice_net": 157200.0, "po_net": 150000.0, "delta": 7200.0, "tolerance": 3000.0 } }
  ],
  "failed_hold": ["R4","R6"], "failed_reject": [], "warnings": ["R6: quantity on line 2 differs"] }
```

`severity` is one of `REJECT`, `HOLD`, `WARN`. A rule that passes still appears with `passed:true`
so the UI can show ten green/amber/red chips. Rules MUST be pure functions of the stage outputs
and the reference data, with unit tests. Exact semantics:

| Code | Name | Logic | Fail severity |
|---|---|---|---|
| R1 | Vendor approved | vendor.matched and status == approved | not matched → REJECT; suspended → HOLD |
| R2 | PO valid | po.method in (explicit, inferred) and po.status == open and not vendor_mismatch | not_found or closed → REJECT; none/ambiguous/vendor_mismatch → HOLD. `inferred` passes but adds WARN "PO inferred, confirm with requester" |
| R3 | Not a duplicate | No ledger row (decision ≠ REJECT) with (a) same vendor_id + same normalised invoice_number, or (b) same file_hash, or (c) same vendor_id + same net_total + invoice_date within ±`duplicate_date_window_days` | REJECT, detail names the earlier invoice and date |
| R4 | Total within PO tolerance | `invoice_net ≤ po.net_total + tol_total` where `tol_total = max(pct × po.net_total, abs_floor[currency])`. Under-billing (`invoice_net < po.net_total − tol_total`) passes with WARN "partial invoice; PO remains open" **only when `billed_net_to_date == 0`**; once something has been billed, R4 passes silently and R5 describes the cumulative position | HOLD |
| R5 | Cumulative within PO | `billed_net_to_date + invoice_net ≤ po.net_total + tol_total`. **Skipped** (passed null) when `billed_net_to_date == 0`, with detail "Not evaluated: nothing previously billed on this PO; R4 covers the single-invoice check" — otherwise R5 would repeat R4 | HOLD, detail shows billed-to-date, this invoice, PO total, overshoot |
| R6 | Line prices within tolerance | For each matched line: `|unit_price − po_unit_price| ≤ pct × po_unit_price` (pct only, no floor). Quantity above PO quantity → WARN. Unmatched invoice lines whose summed amount > tol_total → fail; otherwise WARN | HOLD, detail names the line, both prices, pct delta |
| R7 | Currency matches | invoice currency == po currency. Skipped silently (no warning) when no PO is matched | HOLD |
| R8 | Document complete | all of invoice_number, invoice_date, total, vendor_name non-null AND integrity checks `lines_sum_subtotal` and `subtotal_tax_total` pass | HOLD; detail lists what is missing; triggers vendor draft email |
| R9 | Date in window | `today − date_window_days ≤ invoice_date ≤ today + future_date_grace_days` | HOLD |
| R10 | Extraction confidence | `critical_confidence.min ≥ confidence_floor`, where the min is taken over critical fields whose value is **non-null** (absent fields are R8's job, not R10's; if every critical field is null, R10 passes with WARN "no fields to assess") | HOLD, detail names the weakest field |

Rules R2, R4–R7 are evaluated only when a PO is matched; otherwise they are `skipped:true` with
`passed:null` (R2 itself is the one that fails). Skipped rules render grey.

### 4.7 `decision`

```json
{ "decision": "HOLD",                                   // APPROVE | HOLD | REJECT
  "confidence": 0.93,                                   // = critical_confidence.min
  "reasons": [ { "code": "R4", "text": "Invoice net exceeds PO by 7,200.00 INR (tolerance 3,000.00)" } ],
  "warnings": [ "…" ],
  "explanation": "Invoice AIC/26-27/0931 from Apex Industrial Components Pvt Ltd for INR 185,496.00 is on hold. …",
  "next_action": { "owner": "requester", "text": "Confirm with Priya Nair (PO-2026-0102) whether the flange price increase to 486.00 was agreed." },
  "draft_email": { "to": "priya.nair@example.com", "subject": "…", "body": "…" },   // or null
  "booking": { "po_number": "PO-2026-0102", "net_amount": 157200.0, "gross_amount": 185496.0,
               "currency": "INR", "po_remaining_after": null }            // null unless APPROVE
}
```

Aggregation: any REJECT failure → `REJECT`; else any HOLD failure → `HOLD`; else `APPROVE`.
Explanation is **templated** (no LLM):
`"Invoice {no or 'with no number'} from {vendor} for {currency} {gross} is {approved|on hold|rejected}. {one sentence per failing rule}. {one sentence per warning, max 3}."`
On APPROVE the explanation ends with `"Booked against {po}; {remaining} remains open on the PO."`

`next_action.owner` ∈ `ap`, `requester`, `vendor`, `none`. Mapping: R1/R3 → ap; R2 ambiguous/inferred, R4, R5, R6, R7 → requester; R8 → vendor; R9/R10 → ap.
When several failing rules map to different owners, precedence is: any REJECT-severity failure → `ap`
(nothing else matters once it is rejected); else `vendor` (R8: the document cannot be booked without
the missing fields); else `requester` (R2/R4–R7); else `ap` (R9/R10). The draft email follows the
chosen owner. On APPROVE the owner is `none`.

Draft email: produced when owner is `vendor` (to vendor contact_email: ask for the missing
fields, name the invoice by date and amount) or `requester` (to PO requester_email: state the
discrepancy with numbers and ask for confirmation). Plain text, under 120 words, signed "AP Automation".

Ledger write: after `decision`, insert a ledger row for the run (source `run`) when
`invoice_number` is non-null OR decision is APPROVE. Rows with decision REJECT are inserted too
(for audit) but excluded from duplicate and cumulative checks.

---

### 4.8 Reviewer override (after `decision`)
A completed run whose pipeline `decision` is `HOLD` may be overridden **once** by a reviewer to `APPROVE` or `REJECT`. `APPROVE` and `REJECT` runs, failed runs and already overridden runs cannot be overridden. The pipeline decision and the `decision` stage output are never rewritten; the override is stored next to them.

Ledger effect (same session and commit as the run update):
- **Override to APPROVE**: the run's ledger row (`run_id` = this run) gets `decision = APPROVE`. If the run wrote no row (no invoice number), one is inserted with the same fields as the 4.7 insert. From then on R3 and R5 see it. A booking is computed exactly as 4.7 does for an approved run, against the PO balance at override time: `po_remaining_after = round(po.net_total − billed_net_to_date(po) − net, 2)` when the PO matched and net is known, else null.
- **Override to REJECT**: the run's ledger row gets `decision = REJECT`, so R3 and R5 exclude it as for any rejected row. If there is no row, none is inserted (same condition as 4.7).

---

## 5. HTTP API

Base path `/api`. JSON everywhere except upload. Errors: `{ "error": { "code": "…", "message": "…" } }`.

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/health` | | `{ "ok": true, "model": "…", "db": "ok" }` |
| GET | `/api/samples` | | `samples.json` array plus `"url": "/api/samples/{id}/file"` |
| GET | `/api/samples/{id}/file` | | the PDF |
| POST | `/api/runs` | multipart `file` (PDF) **or** JSON `{ "sample_id": "HP", "use_cache": false }` | `202 { "run_id": "…" }` — processing starts in a background task immediately |
| GET | `/api/runs` | `?limit=50&offset=0&decision=HOLD&q=text` | `{ "items": [RunSummary], "total": 123 }` newest first |
| GET | `/api/runs/{id}` | | `RunDetail` = `RunSummary` + `stages: [StageRecord×7]` (pending stages included) |
| GET | `/api/runs/{id}/events` | | SSE stream, see §6 |
| GET | `/api/runs/{id}/file` | | the uploaded PDF |
| GET | `/api/stats` | | `{ "runs": 42, "approve": 20, "hold": 15, "reject": 7, "auto_approval_rate": 0.48, "median_duration_ms": 8100, "last_24h": 12 }` |
| GET | `/api/reference/vendors` | | vendors array |
| GET | `/api/reference/pos` | | POs with `lines`, `billed_net_to_date`, `remaining_net`, `invoices: [{invoice_number, net_total, decision, source}]` |
| GET | `/api/reference/ledger` | | ledger rows newest first |
| POST | `/api/admin/reset` | `{ "clear_runs": true }` | re-seeds ledger from CSV; optionally deletes runs. `{ "ok": true }` |

`RunSummary`:

```json
{ "id": "run_01JD…", "created_at": "…", "filename": "…", "sample_id": "HP",
  "file_hash": "…", "status": "completed",            // queued | running | completed | failed
  "document_class": "digital", "decision": "APPROVE", "confidence": 0.98,
  "vendor_name": "…", "vendor_id": "V003", "invoice_number": "MCS-10422",
  "invoice_date": "2026-10-31", "currency": "USD", "net_total": 4800.0, "gross_total": 4800.0,
  "po_number": "PO-2026-0107", "duration_ms": 8120, "current_stage": "decision", "error": null }
```

Run ids: `run_` + ULID (or uuid4 hex if ULID lib is a hassle). CORS: allow `http://localhost:5173`
in dev. FastAPI MUST serve `frontend/dist` at `/` with SPA fallback (any non-`/api` path → `index.html`)
when the folder exists.


**Reviewer override (added 2026-11-03, see §4.8): API additions**

- `POST /api/runs/{id}/override` with body `{decision: "APPROVE"|"REJECT", note: string (10–500 chars after trimming), reviewer?: string (≤80 chars, blank or omitted → "AP reviewer")}`. Returns the run summary (200).
  - `404 run_not_found` for an unknown run; `409 override_not_allowed` when the run is not a completed HOLD or was already overridden; `422 validation_error` for a bad body. All use the standard `{error: {code, message}}` shape.
  - Runs under the same lock as pipeline execution, so it never interleaves with a run.
- The run summary (list items, detail, SSE payloads) gains `override_decision`, `override_note`, `override_by`, `override_at` (ISO UTC), `override_booking` (the 4.7 `booking` shape, APPROVE overrides only, else null), and the derived `final_decision` = `override_decision ?? decision`.
- `GET /api/runs?decision=X` filters on `final_decision`.
- `GET /api/stats`: `approve`, `hold`, `reject` count `final_decision`. `auto_approval_rate` stays the pipeline's own (`decision == APPROVE` / completed), since an override is not automatic.

---

## 6. Server-Sent Events

`GET /api/runs/{id}/events` → `text/event-stream`. On connect, the server first replays every
event already emitted for the run (so a late or refreshed client catches up), then streams
live events, then closes after the terminal event. Heartbeat comment line `: ping` every 15 s.

Each event: `id: {seq}`, `event: {type}`, `data: {json}`.

| type | data |
|---|---|
| `run.started` | `{ "run_id", "created_at", "filename", "sample_id" }` |
| `stage.started` | `{ "run_id", "stage": StageRecord(status=running) }` |
| `stage.completed` | `{ "run_id", "stage": StageRecord(status=done\|warn) }` |
| `stage.failed` | `{ "run_id", "stage": StageRecord(status=failed), "error": "…" }` |
| `run.completed` | `{ "run_id", "summary": RunSummary, "decision": DecisionOutput }` |
| `run.failed` | `{ "run_id", "error": "…", "summary": RunSummary }` |

Events MUST also be persisted (table `run_events(run_id, seq, type, data_json, ts)`) so replay works
after a server restart and the dashboard "replay" view is just the stored stages.


**Reviewer override (added 2026-11-03, see §4.8): event addition**

- `override` → `{run_id, summary}`, emitted once when the override is recorded. It is stored like every other event, so it comes *after* `run.completed`. Replay sends every stored event and closes the stream if a terminal event was among them. A live subscriber's stream has already closed at `run.completed`, so the page that makes the override applies the POST response directly. The event serves replay and audit.

---

## 7. Database (SQLite, SQLModel)

Tables: `vendors`, `purchase_orders`, `po_lines`, `ledger`, `runs`, `run_stages`, `run_events`,
`extraction_cache`. `seed.py` loads the CSVs on startup if `vendors` is empty; `/api/admin/reset`
truncates `ledger` and reloads `ledger_seed.csv`. Ledger table = `ledger_seed.csv` columns plus
`id`, `source` (`seed`|`run`), `run_id` (nullable).

The pipeline runs in a FastAPI `BackgroundTask` (one run at a time is fine; a simple
`asyncio.Lock` or queue is acceptable). Event fan-out: an in-process pub/sub keyed by `run_id`.


**Reviewer override (added 2026-11-03, see §4.8): schema addition**

`runs` gains nullable `override_decision`, `override_note`, `override_by`, `override_at`, `override_booking_json`. `init_engine` adds missing nullable columns to an existing SQLite file (`ALTER TABLE … ADD COLUMN`), so a pre-existing `app.db` keeps working without a reset.

---

## 8. Frontend contract

Routes: `/` (new run + live view), `/runs/:id` (same view, replay or live), `/dashboard`,
`/reference` (POs with billed/remaining, ledger, vendors). Vite dev server on 5173 proxies
`/api` and `/health` to `http://localhost:8000`. Build to `frontend/dist`.

`frontend/mock/server.mjs`: Node (no deps beyond built-ins) HTTP server on 8000 implementing
every endpoint in §5 with canned data for all eight samples, emitting SSE stage events with
realistic delays (300–800 ms per stage, 4–7 s for `extraction`). This lets the frontend be
developed before the backend is ready and is the fallback for UI demos.

Visual direction: a calm finance tool, light theme, Inter, colour only for status. Non-negotiables: stage timeline shows all seven stages
from the start (pending → running → done/warn/failed), extraction fields show confidence bars
and evidence quotes, rules render as ten chips with detail on expand, the decision banner is
colour-coded, HOLD/REJECT show the reason list and next action, draft email has a copy button,
dashboard has KPI tiles, filterable runs table, and the PO ledger panel.


**Reviewer override (added 2026-11-03, see §4.8): UI additions**

- Decision banner, completed HOLD with no override: in the Next action card, two secondary buttons, "Approve anyway" and "Reject". Each opens `ConfirmDialog` with a Note textarea (10–500 chars, confirm disabled until valid) and a Reviewer input (default "AP reviewer").
- Overridden run: the banner takes the final decision's colour and word, adds "Pipeline said: On hold (R…)" and a strip with "Overridden by {reviewer} {time}" and the note. Reason chips keep the HOLD colour. The Next action card and draft email are hidden, and an APPROVE override shows the Booking card from `override_booking`. The run header chip shows `final_decision`.
- Dashboard: the decision column shows `final_decision` with a small grey "overridden" label (tooltip: pipeline decision and reviewer). The filter chips and counts use `final_decision`.

---

## 9. Testing requirements

- `backend/tests/test_rules.py`: every rule, pass and fail, including tolerance boundaries.
- `backend/tests/test_matching.py`: vendor tax id / alias / fuzzy / none; PO explicit / inferred / ambiguous / not_found / vendor_mismatch; cumulative billed.
- `backend/tests/test_integrity.py`: normalisation and arithmetic checks.
- `backend/tests/test_pipeline_samples.py`: runs all eight samples end to end **with a recorded extraction fixture per sample** (JSON under `backend/tests/fixtures/extractions/`) so the suite is deterministic and free. A separate `@pytest.mark.live` test hits the real API for HP only.
- The fixtures above are produced once by running real extraction and saving the output; they are re-recorded whenever the sample PDFs change.

---

## 10. Non-goals for v1

LLM-written analyst note, 3-way match / goods receipts, multi-invoice batch upload,
authentication, email sending (drafts only), multi-currency conversion.
