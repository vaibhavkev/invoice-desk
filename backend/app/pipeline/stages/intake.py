"""Stage 1 - intake: validate the upload, hash it, count pages (SPEC 4.1)."""
from __future__ import annotations

import hashlib
import io
from typing import Optional

from pypdf import PdfReader

from ..types import StageError, StageResult

MAX_BYTES = 15 * 1024 * 1024


def run_intake(data: bytes, filename: str, sample_id: Optional[str] = None,
               max_bytes: int = MAX_BYTES) -> StageResult:
    size = len(data or b"")
    if size == 0:
        raise StageError(f"The file {filename!r} is empty.")
    if size > max_bytes:
        raise StageError(f"The file {filename!r} is {size / 1_048_576:.1f} MB; the limit is "
                         f"{max_bytes // 1_048_576} MB.")
    if not data.lstrip()[:5].startswith(b"%PDF-"):
        raise StageError(f"The file {filename!r} is not a PDF (it does not start with a PDF header).")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001 - reported to the user
                raise StageError(f"The PDF {filename!r} is password-protected and cannot be read.") from exc
        page_count = len(reader.pages)
    except StageError:
        raise
    except Exception as exc:  # noqa: BLE001 - any parser error becomes a readable stage failure
        raise StageError(f"The file {filename!r} could not be opened as a PDF ({exc}).") from exc
    if page_count == 0:
        raise StageError(f"The PDF {filename!r} has no pages.")

    sha = hashlib.sha256(data).hexdigest()
    output = {"filename": filename, "size_bytes": size, "sha256": sha,
              "page_count": page_count, "sample_id": sample_id}
    pages = "page" if page_count == 1 else "pages"
    summary = f"Received {filename} ({size / 1024:.0f} KB, {page_count} {pages})."
    return StageResult(summary=summary, output=output)
