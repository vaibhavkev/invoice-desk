"""Stage 3 - LLM extraction with cache semantics (SPEC 3.3, 3.4, 4.3)."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from ...config import ExtractionConfig
from ...extraction.client import ExtractionError, ExtractionResult, extract_invoice
from ...extraction.schema import InvoiceExtraction
from ...util import money
from ..types import StageError, StageResult

Extractor = Callable[[bytes, str, str, ExtractionConfig], ExtractionResult]


def _describe(ex: InvoiceExtraction) -> str:
    vendor = ex.vendor_name.value or "an unnamed vendor"
    no = f"invoice {ex.invoice_number.value}" if ex.invoice_number.value else "an invoice with no number"
    cur = ex.currency.value or ""
    total = f"total {cur} {money(ex.total.value)}".replace("  ", " ") if ex.total.value is not None else "no total"
    n = len(ex.line_items)
    return f"Read {no} from {vendor}: {n} line{'s' if n != 1 else ''}, {total}"


def _lowest(ex: InvoiceExtraction) -> str:
    fields = {k: getattr(ex, k) for k in ("vendor_name", "invoice_number", "invoice_date", "currency", "subtotal",
                                          "total") if getattr(ex, k).value is not None}
    if not fields:
        return ""
    k = min(fields, key=lambda f: fields[f].confidence)
    lo = fields[k].confidence
    if all(f.confidence == lo for f in fields.values()):
        return f"all key fields at confidence {lo:.2f}"
    return f"lowest key-field confidence {lo:.2f} ({k.replace('_', ' ')})"


def _notes_warning(notes: str, limit: int = 280) -> str:
    notes = " ".join(notes.split())
    return "Document notes: " + (notes if len(notes) <= limit else notes[:limit].rsplit(" ", 1)[0] + " …")


def run_extraction(pdf_bytes: bytes, file_hash: str, doc_output: Dict[str, Any], cfg: ExtractionConfig,
                   cache=None, use_cache: bool = False, extractor: Optional[Extractor] = None,
                   confidence_floor: float = 0.75) -> StageResult:
    extractor = extractor or extract_invoice
    document_class = doc_output.get("document_class", "digital")
    text_layer = doc_output.get("text_layer") or ""
    warnings = []

    def from_cache(reason: str, status: str) -> Optional[StageResult]:
        hit = cache.get(file_hash, cfg.model) if cache is not None else None
        if not hit:
            return None
        ex = InvoiceExtraction.model_validate(hit["extraction"])
        out = {"model": hit["model"], "extraction": ex.model_dump(), "usage": hit.get("usage") or {},
               "from_cache": True, "latency_ms": 0, "cached_at": hit.get("created_at")}
        return StageResult(summary=f"{reason} {_describe(ex)}.", output=out, status=status,
                           warnings=warnings + ([_notes_warning(ex.document_notes)] if ex.document_notes else []))

    if use_cache:
        res = from_cache("Used cached extraction (run requested cache).", "done")
        if res is not None:
            return res

    try:
        result = extractor(pdf_bytes, text_layer, document_class, cfg)
    except Exception as exc:  # noqa: BLE001 - includes client construction errors such as a missing key
        message = exc.message if isinstance(exc, ExtractionError) else f"{type(exc).__name__}: {exc}"
        if cfg.cache_fallback:
            res = from_cache(f"Used cached extraction (API error: {message})", "warn")
            if res is not None:
                return res
        raise StageError(message) from exc

    ex = result.extraction
    if cache is not None:
        cache.put(file_hash, result.model, ex.model_dump(), result.usage)

    out = {"model": result.model, "extraction": ex.model_dump(), "usage": result.usage, "from_cache": False,
           "latency_ms": result.latency_ms}
    if result.served_by and result.served_by != result.model:
        out["served_by"] = result.served_by
        warnings.append(f"The request was served by fallback model {result.served_by}.")
    if ex.document_notes:
        warnings.append(_notes_warning(ex.document_notes))
    low = _lowest(ex)
    mode = "from the page images" if document_class == "scanned" else "from the PDF"
    summary = f"{_describe(ex)} ({mode}, {low})." if low else f"{_describe(ex)} ({mode})."
    status = "warn" if ex.overall_confidence < confidence_floor else "done"
    return StageResult(summary=summary, output=out, status=status, warnings=warnings)
