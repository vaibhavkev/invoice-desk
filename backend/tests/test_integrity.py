"""Normalisation and arithmetic checks (SPEC 4.4), plus intake / document analysis."""
from __future__ import annotations

import io

import pytest

from app.pipeline.stages.doc_analysis import run_doc_analysis
from app.pipeline.stages.intake import run_intake
from app.pipeline.stages.integrity import normalise_currency, run_integrity
from app.pipeline.types import StageError

from conftest import line, make_extraction, sf


def checks(out):
    return {c["code"]: c for c in out["checks"]}


def test_happy_path_normalisation_matches_spec_shape():
    res = run_integrity(make_extraction())
    n = res.output["normalised"]
    assert res.status == "done" and res.warnings == []
    assert n["vendor_tax_id"] == "123456789"
    assert n["po_references"] == ["PO-2026-0107"] and n["po_references_normalised"] == ["PO20260107"]
    assert (n["subtotal"], n["tax_amount"], n["total"]) == (4800.0, 0.0, 4800.0)
    assert n["line_items"][0] == {"description": "Cloud hosting – Oct 2026", "quantity": 1, "unit_price": 3200.0,
                                  "amount": 3200.0, "confidence": 1.0}
    c = checks(res.output)
    assert all(x["passed"] for x in c.values())
    assert c["lines_sum_subtotal"]["detail"] == "Lines sum to 4,800.00; subtotal 4,800.00"
    assert c["subtotal_tax_total"]["detail"] == "4,800.00 + 0.00 = 4,800.00"
    assert res.output["critical_confidence"] == {"invoice_number": 1.0, "total": 1.0, "vendor_name": 1.0, "min": 1.0}


def test_money_rounded_to_2dp():
    res = run_integrity(make_extraction(subtotal=4800.004, total=4800.0049))
    assert res.output["normalised"]["subtotal"] == 4800.0


def test_lines_not_summing_to_subtotal_fails():
    res = run_integrity(make_extraction(subtotal=4900.0, total=4900.0))
    c = checks(res.output)
    assert c["lines_sum_subtotal"]["passed"] is False and res.status == "warn"
    assert "4,800.00" in c["lines_sum_subtotal"]["detail"] and "4,900.00" in c["lines_sum_subtotal"]["detail"]


def test_arithmetic_tolerance_is_five_cents():
    ok = checks(run_integrity(make_extraction(subtotal=4800.0, tax_amount=0.0, total=4800.05)).output)
    bad = checks(run_integrity(make_extraction(subtotal=4800.0, tax_amount=0.0, total=4800.06)).output)
    assert ok["subtotal_tax_total"]["passed"] is True
    assert bad["subtotal_tax_total"]["passed"] is False


def test_total_derived_from_subtotal_and_tax_with_warning():
    res = run_integrity(make_extraction(total=None, subtotal=1250.0, tax_amount=250.0,
                                        line_items=[line("Ergonomic chair model K2", 5, 180.0),
                                                    line("Desk lamp LED", 10, 35.0)]))
    assert res.output["normalised"]["total"] == 1500.0
    assert "total derived from subtotal + tax" in res.warnings
    assert checks(res.output)["required_fields"]["passed"] is True


def test_subtotal_derived_from_total_minus_tax():
    res = run_integrity(make_extraction(subtotal=None, tax_amount=250.0, total=1500.0,
                                        line_items=[line("Ergonomic chair model K2", 5, 180.0),
                                                    line("Desk lamp LED", 10, 35.0)]))
    assert res.output["normalised"]["subtotal"] == 1250.0
    assert any("subtotal derived" in w for w in res.warnings)


def test_tax_inclusive_lines_converted_to_net():
    # lines printed gross (incl. 20% VAT) summing to the total, net subtotal printed separately
    res = run_integrity(make_extraction(subtotal=1250.0, tax_amount=250.0, total=1500.0,
                                        line_items=[line("Ergonomic chair model K2", 5, 216.0),
                                                    line("Desk lamp LED", 10, 42.0)]))
    n = res.output["normalised"]
    assert checks(res.output)["lines_sum_subtotal"]["passed"] is True
    assert n["lines_tax_inclusive"] is True
    assert n["line_items"][0]["unit_price"] == 180.0 and n["line_items"][0]["unit_price_printed"] == 216.0


def test_missing_required_fields_listed():
    res = run_integrity(make_extraction(invoice_number=None, invoice_date=None))
    c = checks(res.output)
    assert c["required_fields"]["passed"] is False
    assert c["required_fields"]["detail"] == "Missing: invoice number, invoice date"


def test_bad_date_fails_date_parse():
    res = run_integrity(make_extraction(invoice_date="31/13/2026"))
    c = checks(res.output)
    assert c["date_parse"]["passed"] is False and res.output["normalised"]["invoice_date"] is None


def test_non_iso_date_is_normalised():
    res = run_integrity(make_extraction(invoice_date="31.10.2026"))
    assert res.output["normalised"]["invoice_date"] == "2026-10-31"


def test_due_before_invoice_date_fails():
    res = run_integrity(make_extraction(invoice_date="2026-10-31", due_date="2026-10-01"))
    assert checks(res.output)["date_parse"]["passed"] is False


def test_no_line_items_fails_lines_check():
    res = run_integrity(make_extraction(line_items=[]))
    assert checks(res.output)["lines_sum_subtotal"]["passed"] is False


def test_line_amount_derived_from_qty_and_unit():
    res = run_integrity(make_extraction(line_items=[line("Cloud hosting – Oct 2026", 1, 3200.0),
                                                    {"description": "Object storage 10TB", "quantity": 2,
                                                     "unit_price": 800.0, "amount": None, "confidence": 1.0}]))
    assert res.output["normalised"]["line_items"][1]["amount"] == 1600.0
    assert checks(res.output)["lines_sum_subtotal"]["passed"] is True


def test_critical_confidence_min_ignores_absent_fields():
    res = run_integrity(make_extraction(invoice_number=None, total_conf=0.8))
    cc = res.output["critical_confidence"]
    assert cc["invoice_number"] == 0.0 and cc["min"] == 0.8


@pytest.mark.parametrize("raw,iso", [("usd", "USD"), ("£", "GBP"), ("€", "EUR"), ("₹", "INR"), (" eur ", "EUR"),
                                     (None, None)])
def test_currency_normalisation(raw, iso):
    assert normalise_currency(raw) == iso


def test_po_refs_deduplicated():
    n = run_integrity(make_extraction(po_references=("PO-2026-0107", "PO 2026 0107", "PO-2026-0107"))).output["normalised"]
    assert n["po_references"] == ["PO-2026-0107", "PO 2026 0107"]
    assert n["po_references_normalised"] == ["PO20260107"]


# ---------------------------------------------------------------- intake and document analysis
def _pdf(text: str = None) -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    if text:
        y = 800
        for chunk in text.split("\n"):
            c.drawString(50, y, chunk)
            y -= 14
    else:
        c.rect(100, 100, 200, 200, fill=1)  # an image-like page with no text
    c.showPage()
    c.save()
    return buf.getvalue()


def test_intake_hashes_and_counts_pages():
    data = _pdf("Invoice MCS-10422")
    res = run_intake(data, "x.pdf", "HP")
    assert res.output["page_count"] == 1 and len(res.output["sha256"]) == 64 and res.output["sample_id"] == "HP"


def test_intake_rejects_non_pdf():
    with pytest.raises(StageError, match="not a PDF"):
        run_intake(b"hello world", "x.txt")


def test_intake_rejects_oversize():
    with pytest.raises(StageError, match="limit is 15 MB"):
        run_intake(b"%PDF-" + b"0" * (15 * 1024 * 1024 + 1), "big.pdf")


def test_intake_rejects_broken_pdf():
    with pytest.raises(StageError, match="could not be opened"):
        run_intake(b"%PDF-1.4 garbage", "broken.pdf")


def test_doc_analysis_digital():
    res = run_doc_analysis(_pdf("Invoice MCS-10422 from Meridian Cloud Services Inc\nTotal due 4,800.00 USD\n"
                                "Payment terms Net 30 days. Thank you for your business."))
    assert res.output["document_class"] == "digital"
    assert res.output["pages"][0]["has_text_layer"] is True
    assert "MCS-10422" in res.output["text_layer"]
    assert res.summary == "1 page, text layer present."


def test_doc_analysis_scanned():
    res = run_doc_analysis(_pdf(None))
    assert res.output["document_class"] == "scanned" and res.output["text_layer"] == ""
    assert res.summary == "1 page, no text layer — using vision extraction."
