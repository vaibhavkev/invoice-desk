"""Run live extraction once per sample and save the output as test fixtures.

    cd backend
    .venv\\Scripts\\python tools\\record_extractions.py            # all samples
    .venv\\Scripts\\python tools\\record_extractions.py HP EC1     # some samples

Writes tests/fixtures/extractions/{sample_id}.json (the InvoiceExtraction) and
tests/fixtures/extractions/_usage.json (model, tokens, latency per sample).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.extraction.client import ExtractionError, extract_invoice  # noqa: E402
from app.pipeline.stages.doc_analysis import run_doc_analysis  # noqa: E402

OUT = BACKEND / "tests" / "fixtures" / "extractions"


def main(ids):
    samples = json.loads((settings.data_dir / "samples.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    usage_path = OUT / "_usage.json"
    usage = json.loads(usage_path.read_text(encoding="utf-8")) if usage_path.exists() else {}
    for s in sorted(samples, key=lambda x: x.get("demo_order", 99)):
        if ids and s["id"] not in ids:
            continue
        pdf = (settings.data_dir / s["file"]).read_bytes()
        doc = run_doc_analysis(pdf, settings.policy.scanned_chars_per_page).output
        try:
            r = extract_invoice(pdf, doc["text_layer"], doc["document_class"], settings.extraction)
        except ExtractionError as exc:
            print(f"{s['id']}: FAILED {exc.message}")
            continue
        (OUT / f"{s['id']}.json").write_text(json.dumps(r.extraction.model_dump(), indent=2, ensure_ascii=False),
                                             encoding="utf-8")
        usage[s["id"]] = {"model": r.model, "served_by": r.served_by, "document_class": doc["document_class"],
                          "latency_ms": r.latency_ms, **r.usage}
        print(f"{s['id']}: {doc['document_class']:8s} {r.latency_ms:6d} ms  in={r.usage.get('input_tokens')} "
              f"out={r.usage.get('output_tokens')}  inv={r.extraction.invoice_number.value} "
              f"total={r.extraction.total.value} min_conf="
              f"{min(r.extraction.invoice_number.confidence, r.extraction.total.confidence, r.extraction.vendor_name.confidence):.2f}")
        usage_path.write_text(json.dumps(usage, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(set(sys.argv[1:]))
