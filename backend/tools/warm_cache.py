"""Run live extraction once per sample and store the results in extraction_cache, to pre-warm a demo.

    cd backend
    .venv\\Scripts\\python tools\\warm_cache.py            # all samples
    .venv\\Scripts\\python tools\\warm_cache.py HP EC1     # some samples

Afterwards runs can replay with use_cache=true, and a failed API call falls back to the cache.
Exits 1 if any sample failed.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.db import init_engine  # noqa: E402
from app.extraction.cache import ExtractionCacheStore  # noqa: E402
from app.extraction.client import extract_invoice  # noqa: E402
from app.pipeline.stages.doc_analysis import run_doc_analysis  # noqa: E402


def main(ids, extractor=extract_invoice, engine=None) -> int:
    samples = json.loads((settings.data_dir / "samples.json").read_text(encoding="utf-8"))
    cache = ExtractionCacheStore(engine or init_engine(settings.db_path))
    failed, total_in, total_out = 0, 0, 0
    for s in sorted(samples, key=lambda x: x.get("demo_order", 99)):
        if ids and s["id"] not in ids:
            continue
        pdf = (settings.data_dir / s["file"]).read_bytes()
        doc = run_doc_analysis(pdf, settings.policy.scanned_chars_per_page).output
        try:
            r = extractor(pdf, doc["text_layer"], doc["document_class"], settings.extraction)
        except Exception as exc:  # noqa: BLE001 - one bad sample must not stop the rest
            print(f"{s['id']}: FAILED {exc}")
            failed += 1
            continue
        cache.put(hashlib.sha256(pdf).hexdigest(), r.model, r.extraction.model_dump(), r.usage)
        tokens_in, tokens_out = r.usage.get("input_tokens") or 0, r.usage.get("output_tokens") or 0
        total_in += tokens_in
        total_out += tokens_out
        print(f"{s['id']}: {doc['document_class']:8s} {r.latency_ms:6d} ms  in={tokens_in} out={tokens_out}")
    print(f"total: in={total_in} out={total_out} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(set(sys.argv[1:])))
