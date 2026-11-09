"""Shared test helpers. Unit tests use the tiny CSVs in tests/fixtures/ref, never data/."""
from __future__ import annotations

import copy
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import PolicyConfig  # noqa: E402
from app.pipeline.stages.integrity import run_integrity  # noqa: E402
from app.pipeline.stages.matching import run_matching  # noqa: E402
from app.refdata import RefData  # noqa: E402
from app.rules.rules import RuleContext  # noqa: E402

FIXTURES = BACKEND / "tests" / "fixtures"
REF_DIR = FIXTURES / "ref"
TODAY = date(2026, 11, 2)


def pytest_configure(config):
    config.addinivalue_line("markers", "live: hits the real Anthropic API (deselect with -m 'not live')")


@pytest.fixture
def ref() -> RefData:
    return RefData.from_csv_dir(REF_DIR)


@pytest.fixture
def policy() -> PolicyConfig:
    return PolicyConfig(tolerance_pct=0.02,
                        tolerance_abs_floor={"USD": 25, "EUR": 25, "GBP": 20, "INR": 2000},
                        confidence_floor=0.75, date_window_days=90, future_date_grace_days=0,
                        duplicate_date_window_days=3, scanned_chars_per_page=50)


def sf(value, confidence: float = 1.0, quote: Optional[str] = None) -> Dict[str, Any]:
    ev = None if value is None else {"quote": quote or str(value), "page": 1}
    return {"value": value, "confidence": 0.0 if value is None else confidence, "evidence": ev}


def line(desc: str, qty, unit, amount=None, confidence: float = 1.0) -> Dict[str, Any]:
    if amount is None and qty is not None and unit is not None:
        amount = round(qty * unit, 2)
    return {"description": desc, "quantity": qty, "unit_price": unit, "amount": amount, "confidence": confidence}


def make_extraction(
    vendor_name="Meridian Cloud Services Inc", vendor_tax_id="12-3456789", invoice_number="MCS-10422",
    invoice_date="2026-10-31", due_date="2026-11-30", currency="USD", po_references=("PO-2026-0107",),
    line_items: Optional[List[Dict[str, Any]]] = None, subtotal=4800.00, tax_amount=0.00, tax_rate_pct=0.0,
    total=4800.00, confidence: float = 1.0, **conf_overrides,
) -> Dict[str, Any]:
    """An HP-like extraction (Meridian, PO-2026-0107, 4,800.00 USD) with overridable fields."""
    if line_items is None:
        line_items = [line("Cloud hosting – Oct 2026", 1, 3200.00), line("Object storage 10TB", 1, 1600.00)]
    ex = {
        "vendor_name": sf(vendor_name, confidence),
        "vendor_tax_id": sf(vendor_tax_id, confidence),
        "vendor_address": sf("1 Market St, San Francisco, CA", confidence),
        "bill_to_name": sf("Zamp Demo Customer Ltd", confidence),
        "invoice_number": sf(invoice_number, confidence),
        "invoice_date": sf(invoice_date, confidence),
        "due_date": sf(due_date, confidence),
        "currency": sf(currency, confidence),
        "po_references": list(po_references),
        "line_items": copy.deepcopy(line_items),
        "subtotal": sf(subtotal, confidence),
        "tax_amount": sf(tax_amount, confidence),
        "tax_rate_pct": sf(tax_rate_pct, confidence),
        "total": sf(total, confidence),
        "payment_terms": sf("Net 30", confidence),
        "document_notes": "",
        "overall_confidence": confidence,
    }
    for k, v in conf_overrides.items():
        field = k.replace("_conf", "")
        ex[field]["confidence"] = v
    return ex


def build_ctx(extraction: Dict[str, Any], ref: RefData, policy: PolicyConfig, today: date = TODAY,
              file_hash: Optional[str] = None) -> RuleContext:
    integ = run_integrity(extraction).output
    match = run_matching(integ["normalised"], ref).output
    return RuleContext(normalised=integ["normalised"], checks=integ["checks"],
                       critical_confidence=integ["critical_confidence"], vendor=match["vendor"],
                       po=match["po"], ref=ref, policy=policy, today=today, file_hash=file_hash)
