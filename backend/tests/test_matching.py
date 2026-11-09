"""Vendor matching (tax id / alias / fuzzy / none) and PO matching (SPEC 4.5)."""
from __future__ import annotations

from app.matching.po import match_po
from app.matching.vendor import match_vendor
from app.pipeline.stages.integrity import run_integrity
from app.pipeline.stages.matching import run_matching
from app.refdata import LedgerRec

from conftest import line, make_extraction


def normalised(**kw):
    return run_integrity(make_extraction(**kw)).output["normalised"]


# ---------------------------------------------------------------- vendor
def test_vendor_tax_id_exact_ignores_formatting(ref):
    v = match_vendor("Some Other Name", "12 345 6789", ref)
    assert (v["matched"], v["vendor_id"], v["method"], v["score"]) == (True, "V003", "tax_id", 1.0)
    assert v["candidates"][0] == {"vendor_id": "V003", "score": 1.0, "method": "tax_id"}
    assert v["warnings"]  # name does not match the tax id -> flagged


def test_vendor_tax_id_with_dots_and_dashes(ref):
    assert match_vendor(None, "de.123-456.789", ref)["vendor_id"] == "V004"


def test_vendor_alias_exact(ref):
    v = match_vendor("Helios FM", None, ref)
    assert (v["vendor_id"], v["method"], v["score"]) == ("V004", "alias", 1.0)


def test_vendor_legal_name_with_punctuation_and_suffix(ref):
    v = match_vendor("Meridian Cloud Services, Inc.", None, ref)
    assert (v["vendor_id"], v["method"]) == ("V003", "alias")


def test_vendor_fuzzy_name(ref):
    v = match_vendor("Northwind Office Suplies Limited", None, ref)
    assert v["matched"] and v["vendor_id"] == "V001" and v["method"] == "name_fuzzy"
    assert 0.9 <= v["score"] < 1.0


def test_vendor_none_returns_top3_candidates(ref):
    v = match_vendor("Silverline Consulting Partners", "77-0000001", ref)
    assert v["matched"] is False and v["vendor_id"] is None
    assert len(v["candidates"]) == 3
    assert all(c["score"] < 0.9 for c in v["candidates"])


def test_vendor_wrong_tax_id_but_name_matches_warns(ref):
    v = match_vendor("Quantum Lab Supplies BV", "NL000000000B01", ref)
    assert v["vendor_id"] == "V006" and v["method"] == "alias"
    assert any("differs" in w for w in v["warnings"])


# ---------------------------------------------------------------- PO
def _vendor(ref, vid):
    v = ref.vendor(vid)
    return match_vendor(v.legal_name, v.tax_id, ref)


def test_po_explicit_with_noisy_reference(ref):
    n = normalised(po_references=("P.O. # po 2026 0107",))
    po = match_po(n, _vendor(ref, "V003"), ref)
    assert (po["matched"], po["method"], po["po_number"], po["score"]) == (True, "explicit", "PO-2026-0107", 1.0)
    assert po["vendor_mismatch"] is False and po["status"] == "open"
    assert po["line_matches"] == [{"invoice_line": 1, "po_line": 1, "score": 1.0},
                                  {"invoice_line": 2, "po_line": 2, "score": 1.0}]
    assert po["unmatched_invoice_lines"] == []


def test_po_explicit_reference_in_sentence(ref):
    n = normalised(po_references=("as per your order PO-2026-0107",))
    po = match_po(n, _vendor(ref, "V003"), ref)
    assert (po["method"], po["po_number"]) == ("explicit", "PO-2026-0107")


def test_po_not_found(ref):
    po = match_po(normalised(po_references=("PO-2026-0199",)), _vendor(ref, "V003"), ref)
    assert (po["matched"], po["method"]) == (False, "not_found")
    assert po["references"] == ["PO-2026-0199"]


def test_po_vendor_mismatch_still_reports_po(ref):
    po = match_po(normalised(po_references=("PO-2026-0109",)), _vendor(ref, "V003"), ref)
    assert po["matched"] and po["po_number"] == "PO-2026-0109" and po["vendor_mismatch"] is True


def test_po_prefers_reference_belonging_to_vendor(ref):
    po = match_po(normalised(po_references=("PO-2026-0109", "PO-2026-0107")), _vendor(ref, "V003"), ref)
    assert po["po_number"] == "PO-2026-0107" and po["vendor_mismatch"] is False


def test_po_inferred_from_amount_and_lines(ref):
    lines = [line("Nitrile gloves (box of 100)", 150, 9.00), line("Pipette tips 1000µl (rack)", 60, 30.00)]
    n = normalised(vendor_name="Quantum Lab Supplies BV", vendor_tax_id="NL123456789B01", po_references=(),
                   line_items=lines, subtotal=3150.0, tax_amount=661.5, total=3811.5, currency="EUR")
    po = match_po(n, _vendor(ref, "V006"), ref)
    assert (po["matched"], po["method"], po["po_number"]) == (True, "inferred", "PO-2026-0109")
    assert po["score"] >= 0.8
    top, runner = po["candidates"][0], po["candidates"][1]
    assert top["po_number"] == "PO-2026-0109" and top["score"] - runner["score"] >= 0.2


def test_po_ambiguous_when_no_clear_winner(ref):
    n = normalised(po_references=(), line_items=[line("Consulting day", 1, 2400.0)], subtotal=2400.0, total=2400.0)
    po = match_po(n, _vendor(ref, "V003"), ref)
    assert po["matched"] is False and po["method"] == "ambiguous"
    assert {c["po_number"] for c in po["candidates"]} == {"PO-2026-0106", "PO-2026-0107"}  # closed 0090 excluded


def test_po_none_without_vendor(ref):
    n = normalised(vendor_name="Silverline Consulting Partners", vendor_tax_id=None, po_references=())
    po = match_po(n, match_vendor("Silverline Consulting Partners", None, ref), ref)
    assert po["method"] == "none" and po["matched"] is False


def test_po_none_when_vendor_has_no_open_pos(ref):
    ref.pos = [p for p in ref.pos if p.vendor_id != "V001"]
    n = normalised(vendor_name="Northwind Office Supplies Ltd", vendor_tax_id="GB123456789", po_references=())
    assert match_po(n, _vendor(ref, "V001"), ref)["method"] == "none"


def test_cumulative_billed_counts_only_approved_rows(ref):
    ref.ledger.append(LedgerRec("HFM-2026-104", "V004", "2026-10-30", "EUR", 4000.0, 4760.0, "PO-2026-0105",
                                "APPROVE", None, "", "run", "r1"))
    ref.ledger.append(LedgerRec("HFM-2026-150", "V004", "2026-10-30", "EUR", 1000.0, 1190.0, "PO-2026-0105",
                                "HOLD", None, "", "run", "r2"))
    ref.ledger.append(LedgerRec("HFM-2026-151", "V004", "2026-10-30", "EUR", 999.0, 1190.0, "PO-2026-0105",
                                "REJECT", None, "", "run", "r3"))
    n = normalised(vendor_name="Helios Facility Management GmbH", vendor_tax_id="DE123456789",
                   po_references=("PO-2026-0105",), currency="EUR",
                   line_items=[line("Facility cleaning services – October", 1, 4000.0)], subtotal=4000.0,
                   tax_amount=760.0, total=4760.0)
    po = match_po(n, _vendor(ref, "V004"), ref)
    assert po["billed_net_to_date"] == 8000.0 and po["remaining_net"] == 4000.0


def test_line_match_tolerates_period_wording(ref):
    n = normalised(vendor_name="Helios Facility Management GmbH", vendor_tax_id="DE123456789",
                   po_references=("PO-2026-0105",), currency="EUR",
                   line_items=[line("Facility cleaning services – Nov + Dec", 2, 4000.0)], subtotal=8000.0,
                   tax_amount=1520.0, total=9520.0)
    po = match_po(n, _vendor(ref, "V004"), ref)
    assert po["line_matches"] and po["line_matches"][0]["po_line"] == 1


def test_matching_stage_summary_reads_like_a_sentence(ref):
    res = run_matching(normalised(), ref)
    assert res.summary.startswith("Vendor V003 Meridian Cloud Services Inc (matched on tax ID). "
                                  "PO-2026-0107 (quoted on invoice)")
    assert res.status == "done"
