"""Claude extraction call (SPEC 3.3).

Shape follows the claude-api skill's Python docs: ``client.beta.messages.parse()`` with the
Pydantic schema as ``output_format``, the PDF as a base64 ``document`` block before the text,
``output_config.effort`` from config, and the server-side refusal fallback beta with
``fallbacks="default"``. Thinking is left at the model default (adaptive on Opus 5.5).
"""
from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import anthropic
from pydantic import ValidationError

from ..config import ExtractionConfig
from .prompt import SYSTEM_PROMPT, USER_INSTRUCTION, text_layer_block
from .schema import InvoiceExtraction

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ExtractionError(Exception):
    """Extraction failed, with a message fit to show the user."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class ExtractionResult:
    extraction: InvoiceExtraction
    model: str
    usage: Dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    served_by: Optional[str] = None
    request_id: Optional[str] = None


_client: Optional[anthropic.Anthropic] = None


def get_client(timeout_s: float = 120.0) -> anthropic.Anthropic:
    """One retry on connection / 408 / 409 / 429 / 5xx (SDK default retry policy); 4xx are not retried."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(timeout=timeout_s, max_retries=1)
    return _client


def build_content(pdf_bytes: bytes, text_layer: str, document_class: str):
    content = [{
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf",
                   "data": base64.standard_b64encode(pdf_bytes).decode("ascii")},
    }]
    if document_class in ("digital", "mixed") and text_layer:
        content.append({"type": "text", "text": text_layer_block(text_layer)})
    content.append({"type": "text", "text": USER_INSTRUCTION})
    return content


def _usage_dict(usage) -> Dict[str, Any]:
    if usage is None:
        return {}
    out = {"input_tokens": getattr(usage, "input_tokens", None), "output_tokens": getattr(usage, "output_tokens", None)}
    for k in ("cache_read_input_tokens", "cache_creation_input_tokens"):
        v = getattr(usage, k, None)
        if v:
            out[k] = v
    return out


def extract_invoice(pdf_bytes: bytes, text_layer: str, document_class: str, cfg: ExtractionConfig) -> ExtractionResult:
    client = get_client(cfg.timeout_s)
    t0 = time.perf_counter()
    try:
        resp = client.beta.messages.parse(
            model=cfg.model,
            max_tokens=cfg.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_content(pdf_bytes, text_layer, document_class)}],
            output_format=InvoiceExtraction,
            output_config={"effort": cfg.effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        raise ExtractionError("The Anthropic API key was rejected (401). Check ANTHROPIC_API_KEY.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise ExtractionError(f"The API key is not allowed to use {cfg.model} (403).") from exc
    except anthropic.NotFoundError as exc:
        raise ExtractionError(f"Model {cfg.model} was not found (404).") from exc
    except anthropic.RateLimitError as exc:
        raise ExtractionError("The Anthropic API is rate limiting us (429) after one retry.") from exc
    except anthropic.BadRequestError as exc:
        raise ExtractionError(f"The extraction request was rejected (400): {exc.message}") from exc
    except anthropic.APITimeoutError as exc:
        raise ExtractionError(f"The extraction call timed out after {cfg.timeout_s:.0f} s.") from exc
    except anthropic.APIConnectionError as exc:
        raise ExtractionError("Could not reach the Anthropic API (network error).") from exc
    except anthropic.APIStatusError as exc:
        raise ExtractionError(f"The Anthropic API returned {exc.status_code}: {exc.message}") from exc
    except ValidationError as exc:
        raise ExtractionError(f"The model's output did not match the invoice schema: {exc.errors()[:2]}") from exc
    latency_ms = int((time.perf_counter() - t0) * 1000)

    usage = _usage_dict(getattr(resp, "usage", None))
    request_id = getattr(resp, "_request_id", None)
    log.info("extraction model=%s served_by=%s stop=%s usage=%s latency_ms=%d request_id=%s",
             cfg.model, getattr(resp, "model", None), resp.stop_reason, usage, latency_ms, request_id)

    if resp.stop_reason == "refusal":
        cat = getattr(getattr(resp, "stop_details", None), "category", None)
        raise ExtractionError(f"The model declined to read this document (refusal{', ' + cat if cat else ''}); "
                              f"it needs manual entry.")
    if resp.stop_reason == "max_tokens":
        raise ExtractionError(f"The extraction ran out of output budget ({cfg.max_tokens} tokens) before finishing; "
                              f"raise extraction.max_tokens in config.yaml.")
    parsed = resp.parsed_output
    if parsed is None:
        raise ExtractionError(f"The model returned no structured output (stop reason {resp.stop_reason}).")
    served_by = getattr(resp, "model", None)
    return ExtractionResult(extraction=parsed, model=cfg.model, usage=usage, latency_ms=latency_ms,
                            served_by=served_by, request_id=request_id)
