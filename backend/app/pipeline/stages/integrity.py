"""Stage 4 - normalisation and integrity checks (SPEC 4.4).

Pure function of the extraction. It never decides; failed checks make the stage ``warn`` and
the rules engine (R8) decides the consequence.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from ...extraction.schema import InvoiceExtraction
from ...util import ARITH_TOLERANCE, money, norm_ref, norm_tax_id, parse_iso_date, r2
from ..types import StageResult

CRITICAL_FIELDS = ("invoice_number", "total", "vendor_name")
REQUIRED_FIELDS = ("invoice_number", "invoice_date", "total", "vendor_name")

_CURRENCY_SYMBOLS = {"£": "GBP", "€": "EUR", "₹": "INR", "RS": "INR", "RS.": "INR", "US$": "USD",
                     "EURO": "EUR", "EUROS": "EUR"}


def _clean_str(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = " ".join(str(v).split())
    return v or None


def normalise_currency(v: Optional[str]) -> Optional[str]:
    v = _clean_str(v)
    if not v:
        return None
    up = v.upper()
    if up in _CURRENCY_SYMBOLS:
        return _CURRENCY_SYMBOLS[up]
    if v in _CURRENCY_SYMBOLS:
        return _CURRENCY_SYMBOLS[v]
    letters = "".join(ch for ch in up if ch.isalpha())
    return letters[:3] if len(letters) >= 3 else up


def _close(a: float, b: float, tol: float = ARITH_TOLERANCE) -> bool:
    return abs(a - b) <= tol + 1e-9


def run_integrity(extraction: Union[InvoiceExtraction, Dict[str, Any]]) -> StageResult:
    ex = extraction if isinstance(extraction, InvoiceExtraction) else InvoiceExtraction.model_validate(extraction)
    warnings: List[str] = []

    subtotal = r2(ex.subtotal.value)
    tax = r2(ex.tax_amount.value)
    total = r2(ex.total.value)

    # --- derive missing totals (each derivation is announced) --------------------------
    if total is None and subtotal is not None and tax is not None:
        total = r2(subtotal + tax)
        warnings.append("total derived from subtotal + tax")
    if subtotal is None and total is not None and tax is not None:
        subtotal = r2(total - tax)
        warnings.append("subtotal derived from total − tax")
    if tax is None and subtotal is not None and total is not None and _close(subtotal, total):
        tax = 0.0
    if subtotal is None and total is not None and tax is None and ex.tax_rate_pct.value in (None, 0):
        subtotal, tax = total, 0.0
        warnings.append("no subtotal or tax printed; the total is treated as the net amount")

    # --- line items --------------------------------------------------------------------
    lines: List[Dict[str, Any]] = []
    for li in ex.line_items:
        qty = li.quantity
        unit = r2(li.unit_price)
        amount = r2(li.amount)
        if amount is None and qty is not None and unit is not None:
            amount = r2(qty * unit)
        if unit is None and amount is not None and qty:
            unit = r2(amount / qty)
        lines.append({"description": _clean_str(li.description) or "", "quantity": qty,
                      "unit_price": unit, "amount": amount, "confidence": li.confidence})

    # --- dates -------------------------------------------------------------------------
    raw_date = _clean_str(ex.invoice_date.value)
    inv_date = parse_iso_date(raw_date)
    raw_due = _clean_str(ex.due_date.value)
    due_date = parse_iso_date(raw_due)

    po_refs = []
    for ref in ex.po_references:
        ref = _clean_str(ref)
        if ref and ref not in po_refs:
            po_refs.append(ref)
    po_norm = []
    for ref in po_refs:
        n = norm_ref(ref)
        if n and n not in po_norm:
            po_norm.append(n)

    checks: List[Dict[str, Any]] = []

    # lines_sum_subtotal
    lines_tax_inclusive = False
    if not lines:
        checks.append({"code": "lines_sum_subtotal", "passed": False, "detail": "No line items were found on the invoice."})
    elif any(l["amount"] is None for l in lines):
        bad = [str(i) for i, l in enumerate(lines, 1) if l["amount"] is None]
        checks.append({"code": "lines_sum_subtotal", "passed": False,
                       "detail": f"Line {', '.join(bad)} has no amount, so lines cannot be summed."})
    else:
        lsum = r2(sum(l["amount"] for l in lines))
        if subtotal is None:
            checks.append({"code": "lines_sum_subtotal", "passed": False,
                           "detail": f"Lines sum to {money(lsum)} but no subtotal is printed."})
        elif _close(lsum, subtotal):
            checks.append({"code": "lines_sum_subtotal", "passed": True,
                           "detail": f"Lines sum to {money(lsum)}; subtotal {money(subtotal)}"})
        elif total is not None and tax and _close(lsum, total):
            # Lines printed tax-inclusive: convert to net for PO comparison, and say so.
            lines_tax_inclusive = True
            factor = subtotal / total if total else 1.0
            for l in lines:
                l["unit_price_printed"], l["amount_printed"] = l["unit_price"], l["amount"]
                l["unit_price"] = r2(l["unit_price"] * factor) if l["unit_price"] is not None else None
                l["amount"] = r2(l["amount"] * factor)
            warnings.append("line prices are printed including tax; converted to net for PO comparison")
            checks.append({"code": "lines_sum_subtotal", "passed": True,
                           "detail": f"Lines are tax-inclusive and sum to the total {money(total)}; "
                                     f"net subtotal {money(subtotal)}"})
        else:
            checks.append({"code": "lines_sum_subtotal", "passed": False,
                           "detail": f"Lines sum to {money(lsum)} but the subtotal is {money(subtotal)} "
                                     f"(difference {money(abs(lsum - subtotal))})"})

    # subtotal_tax_total
    if subtotal is None or total is None:
        missing = [n for n, v in (("subtotal", subtotal), ("total", total)) if v is None]
        checks.append({"code": "subtotal_tax_total", "passed": False,
                       "detail": f"Cannot check arithmetic: {' and '.join(missing)} missing."})
    else:
        t = tax or 0.0
        calc = r2(subtotal + t)
        if _close(calc, total):
            checks.append({"code": "subtotal_tax_total", "passed": True,
                           "detail": f"{money(subtotal)} + {money(t)} = {money(total)}"})
        else:
            checks.append({"code": "subtotal_tax_total", "passed": False,
                           "detail": f"{money(subtotal)} + {money(t)} = {money(calc)}, but the invoice total is "
                                     f"{money(total)}"})

    # required_fields
    values = {"invoice_number": _clean_str(ex.invoice_number.value), "invoice_date": inv_date,
              "total": total, "vendor_name": _clean_str(ex.vendor_name.value)}
    missing = [f for f in REQUIRED_FIELDS if values[f] is None]
    if missing:
        checks.append({"code": "required_fields", "passed": False, "detail": "Missing: " + ", ".join(f.replace("_", " ") for f in missing)})
    else:
        checks.append({"code": "required_fields", "passed": True,
                       "detail": "invoice_number, invoice_date, total, vendor_name present"})

    # date_parse
    date_problems = []
    if raw_date and inv_date is None:
        date_problems.append(f"invoice date {raw_date!r} is not a valid date")
    if raw_due and due_date is None:
        date_problems.append(f"due date {raw_due!r} is not a valid date")
    if inv_date and due_date and due_date < inv_date:
        date_problems.append(f"due date {due_date.isoformat()} is before the invoice date {inv_date.isoformat()}")
    checks.append({"code": "date_parse", "passed": not date_problems, "detail": "; ".join(date_problems)})

    # critical confidence (SPEC 4.4 as amended): min over critical fields whose value is non-null.
    # Null fields are reported with their confidence (0.0) but excluded; an absent field is R8's job.
    # If every critical field is null, min is None and R10 passes with a warning.
    conf = {"invoice_number": ex.invoice_number.confidence, "total": ex.total.confidence,
            "vendor_name": ex.vendor_name.confidence}
    present = [conf[f] for f in CRITICAL_FIELDS if values[f] is not None]
    critical = dict(conf)
    critical["min"] = round(min(present), 2) if present else None

    normalised = {
        "vendor_name": values["vendor_name"],
        "vendor_tax_id": norm_tax_id(ex.vendor_tax_id.value) or None,
        "vendor_address": _clean_str(ex.vendor_address.value),
        "bill_to_name": _clean_str(ex.bill_to_name.value),
        "invoice_number": values["invoice_number"],
        "invoice_date": inv_date.isoformat() if inv_date else None,
        "due_date": due_date.isoformat() if due_date else None,
        "currency": normalise_currency(ex.currency.value),
        "po_references": po_refs,
        "po_references_normalised": po_norm,
        "subtotal": subtotal,
        "tax_amount": tax,
        "tax_rate_pct": ex.tax_rate_pct.value,
        "total": total,
        "payment_terms": _clean_str(ex.payment_terms.value),
        "line_items": lines,
        "lines_tax_inclusive": lines_tax_inclusive,
    }

    failed = [c for c in checks if not c["passed"]]
    if not failed:
        summary = ("All integrity checks passed: lines add up to the subtotal, subtotal plus tax equals the "
                   "total, required fields are present and dates are valid.")
    else:
        summary = (f"{len(failed)} of {len(checks)} integrity checks failed: "
                   + "; ".join(c["detail"].rstrip(".") for c in failed) + ".")
    output = {"normalised": normalised, "checks": checks, "critical_confidence": critical}
    return StageResult(summary=summary, output=output, status="warn" if failed else "done", warnings=warnings)
