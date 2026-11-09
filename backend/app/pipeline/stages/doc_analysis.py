"""Stage 2 - document analysis: is there a usable text layer? (SPEC 4.2)."""
from __future__ import annotations

import io
import re

from pypdf import PdfReader

from ..types import StageError, StageResult

_EN_WORDS = {"invoice", "total", "date", "the", "and", "due", "amount", "payment", "tax", "to", "of", "for",
             "qty", "quantity", "price", "description", "bill", "terms", "subtotal", "vat", "number"}


def _language_guess(text: str) -> str:
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if not words:
        return "unknown"
    hits = sum(1 for w in words if w in _EN_WORDS)
    return "en" if hits >= 3 else "unknown"


def run_doc_analysis(data: bytes, scanned_chars_per_page: int = 50) -> StageResult:
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise StageError(f"The PDF could not be parsed for text ({exc}).") from exc

    pages, texts, warnings = [], [], []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - a broken page is treated as image-only
            warnings.append(f"Page {i}: text layer could not be read ({exc}); treating it as scanned.")
            text = ""
        chars = len(re.sub(r"\s", "", text))
        has_text = chars >= scanned_chars_per_page
        pages.append({"page": i, "chars": chars, "has_text_layer": has_text})
        if has_text:
            texts.append(f"--- page {i} ---\n{text.strip()}")

    n = len(pages)
    with_text = sum(1 for p in pages if p["has_text_layer"])
    if with_text == n:
        cls = "digital"
    elif with_text == 0:
        cls = "scanned"
    else:
        cls = "mixed"
    text_layer = "\n\n".join(texts) if cls != "scanned" else ""
    page_word = "page" if n == 1 else "pages"
    if cls == "digital":
        summary = f"{n} {page_word}, text layer present."
    elif cls == "scanned":
        summary = f"{n} {page_word}, no text layer — using vision extraction."
        warnings.append("Scanned document: values are read from the image, so expect lower confidence.")
    else:
        summary = f"{with_text} of {n} pages have a text layer; the other pages are read as images."
    output = {"document_class": cls, "pages": pages, "text_layer": text_layer,
              "language_guess": _language_guess(text_layer)}
    return StageResult(summary=summary, output=output, status="done", warnings=warnings)
