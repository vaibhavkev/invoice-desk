"""Every rule, pass and fail, including tolerance boundaries (SPEC 4.6), plus decision aggregation (4.7)."""
from __future__ import annotations

from datetime import date

import pytest

from app.pipeline.stages.decision import run_decision
from app.pipeline.stages.rules import run_rules
from app.refdata import LedgerRec
from app.rules import rules as R
from app.rules.engine import aggregate, evaluate

from conftest import build_ctx, line, make_extraction


def rule(code, ctx):
    return next(r for r in evaluate(ctx)["results"] if r["code"] == code)


def decide(ctx):
    rules_out = run_rules(ctx).output
    return run_decision(rules_out, ctx).output


# ---------------------------------------------------------------- helpers for scenario-shaped invoices
def apex(flange_unit=450.00, flange_qty=200, extra_lines=(), **kw):
    lines = [line("Stainless steel flange DN50", flange_qty, flange_unit),
             line("Hex bolt M12 (box of 100)", 50, 1200.00)] + list(extra_lines)
    sub = round(sum(l["amount"] for l in lines), 2)
    tax = round(sub * 0.18, 2)
    args = dict(vendor_name="Apex Industrial Components Pvt Ltd", vendor_tax_id="27AAACA1234A1Z5",
                invoice_number="AIC/26-27/0931", invoice_date="2026-10-29", currency="INR",
                po_references=("PO-2026-0102",), line_items=lines, subtotal=sub, tax_amount=tax,
                tax_rate_pct=18.0, total=round(sub + tax, 2))
    args.update(kw)
    return make_extraction(**args)


def helios(qty=1, desc="Facility cleaning services – October", invoice_number="HFM-2026-104",
           invoice_date="2026-10-30", net=None):
    net = net if net is not None else qty * 4000.00
    lines = [line(desc, qty, round(net / qty, 2), net)]
    tax = round(net * 0.19, 2)
    return make_extraction(vendor_name="Helios Facility Management GmbH", vendor_tax_id="DE 123 456 789",
                           invoice_number=invoice_number, invoice_date=invoice_date, currency="EUR",
                           po_references=("PO-2026-0105",), line_items=lines, subtotal=net, tax_amount=tax,
                           tax_rate_pct=19.0, total=round(net + tax, 2))


def quantum_no_number():
    lines = [line("Nitrile gloves (box of 100)", 150, 9.00), line("Pipette tips 1000µl (rack)", 60, 30.00)]
    return make_extraction(vendor_name="Quantum Lab Supplies BV", vendor_tax_id="NL123456789B01",
                           invoice_number=None, invoice_date="2026-10-30", currency="EUR", po_references=(),
                           line_items=lines, subtotal=3150.00, tax_amount=661.50, tax_rate_pct=21.0,
                           total=3811.50)


# ================================================================ R1
def test_r1_pass_approved_vendor(ref, policy):
    r = rule("R1", build_ctx(make_extraction(), ref, policy))
    assert r["passed"] is True and r["severity"] == "REJECT"


def test_r1_unknown_vendor_rejects(ref, policy):
    ex = make_extraction(vendor_name="Silverline Consulting Partners", vendor_tax_id="77-0000001")
    r = rule("R1", build_ctx(ex, ref, policy))
    assert r["passed"] is False and r["severity"] == "REJECT"
    assert "Silverline Consulting Partners is not in the vendor master" in r["detail"]


def test_r1_suspended_vendor_holds(ref, policy):
    ex = make_extraction(vendor_name="Bluegrass Logistics LLC", vendor_tax_id="98-7654321",
                         po_references=("PO-2026-0112",), line_items=[line("Courier services", 1, 500.0)],
                         subtotal=500.0, total=500.0)
    r = rule("R1", build_ctx(ex, ref, policy))
    assert r["passed"] is False and r["severity"] == "HOLD"
    assert "suspended" in r["detail"]


# ================================================================ R2
def test_r2_explicit_open_passes(ref, policy):
    r = rule("R2", build_ctx(make_extraction(), ref, policy))
    assert r["passed"] is True and r["warnings"] == []


def test_r2_closed_po_rejects(ref, policy):
    ex = make_extraction(po_references=("PO-2026-0090",), line_items=[line("Support contract", 1, 1000.0)],
                         subtotal=1000.0, total=1000.0)
    r = rule("R2", build_ctx(ex, ref, policy))
    assert r["passed"] is False and r["severity"] == "REJECT" and "closed" in r["detail"]


def test_r2_not_found_rejects(ref, policy):
    ex = make_extraction(po_references=("PO-2026-0199",))
    r = rule("R2", build_ctx(ex, ref, policy))
    assert r["passed"] is False and r["severity"] == "REJECT"
    assert "PO-2026-0199" in r["detail"]


def test_r2_vendor_mismatch_holds(ref, policy):
    ex = make_extraction(po_references=("PO-2026-0109",))  # Meridian invoice quoting a Quantum PO
    r = rule("R2", build_ctx(ex, ref, policy))
    assert r["passed"] is False and r["severity"] == "HOLD"


def test_r2_inferred_passes_with_warning(ref, policy):
    r = rule("R2", build_ctx(quantum_no_number(), ref, policy))
    assert r["passed"] is True and r["severity"] == "WARN"
    assert r["warnings"] == ["PO inferred, confirm with requester"]


def test_r2_ambiguous_holds(ref, policy):
    ex = make_extraction(po_references=(), line_items=[line("Consulting day", 1, 2400.0)], subtotal=2400.0,
                         total=2400.0)
    ctx = build_ctx(ex, ref, policy)
    assert ctx.po["method"] == "ambiguous"
    r = rule("R2", ctx)
    assert r["passed"] is False and r["severity"] == "HOLD"


def test_r2_none_holds(ref, policy):
    ex = make_extraction(vendor_name="Silverline Consulting Partners", vendor_tax_id=None, po_references=())
    r = rule("R2", build_ctx(ex, ref, policy))
    assert r["passed"] is False and r["severity"] == "HOLD"


def test_po_rules_skipped_without_po(ref, policy):
    ex = make_extraction(po_references=("PO-2026-0199",))
    res = {r["code"]: r for r in evaluate(build_ctx(ex, ref, policy))["results"]}
    for code in ("R4", "R5", "R6", "R7"):
        assert res[code]["passed"] is None and res[code]["skipped"] is True
    assert len(res) == 10


# ================================================================ R3
def test_r3_same_vendor_invoice_number_rejects(ref, policy):
    ex = make_extraction(invoice_number="MCS 10398", invoice_date="2026-10-01", po_references=("PO-2026-0106",),
                         line_items=[line("Managed backup service – Sep 2026", 1, 2400.0)],
                         subtotal=2400.0, total=2400.0)
    r = rule("R3", build_ctx(ex, ref, policy))
    assert r["passed"] is False and r["severity"] == "REJECT"
    assert "MCS-10398" in r["detail"] and "2026-10-01" in r["detail"]


def test_r3_same_file_hash_rejects(ref, policy):
    r = rule("R3", build_ctx(make_extraction(), ref, policy, file_hash="ABC123"))
    assert r["passed"] is False and r["evidence"]["match"] == "identical file"


def test_r3_same_amount_within_window_rejects(ref, policy):
    ex = make_extraction(vendor_name="Northwind Office Supplies Ltd", vendor_tax_id="GB123456789",
                         invoice_number="NW-9999", invoice_date="2026-08-23", currency="GBP", po_references=(),
                         line_items=[line("Paper", 1, 640.0)], subtotal=640.0, tax_amount=128.0, total=768.0)
    r = rule("R3", build_ctx(ex, ref, policy))
    assert r["passed"] is False and "within 3 days" in r["evidence"]["match"]


def test_r3_same_amount_outside_window_passes(ref, policy):
    ex = make_extraction(vendor_name="Northwind Office Supplies Ltd", vendor_tax_id="GB123456789",
                         invoice_number="NW-9999", invoice_date="2026-08-24", currency="GBP", po_references=(),
                         line_items=[line("Paper", 1, 640.0)], subtotal=640.0, tax_amount=128.0, total=768.0)
    assert rule("R3", build_ctx(ex, ref, policy))["passed"] is True


def test_r3_ignores_rejected_ledger_rows(ref, policy):
    ref.ledger.append(LedgerRec("MCS-10422", "V003", "2026-10-31", "USD", 4800.0, 4800.0, "PO-2026-0107",
                                "REJECT", None, "2026-11-01T00:00:00Z", "run", "run_x"))
    assert rule("R3", build_ctx(make_extraction(), ref, policy))["passed"] is True


def test_r3_clean_invoice_passes(ref, policy):
    assert rule("R3", build_ctx(make_extraction(), ref, policy))["passed"] is True


# ================================================================ R4
@pytest.mark.parametrize("net,passed", [(4896.00, True), (4896.01, False), (4800.00, True)])
def test_r4_pct_tolerance_boundary(ref, policy, net, passed):
    # PO-2026-0107 net 4,800.00 USD -> tolerance max(2% = 96.00, floor 25) = 96.00
    ex = make_extraction(subtotal=net, total=net,
                         line_items=[line("Cloud hosting – Oct 2026", 1, round(net - 1600, 2)),
                                     line("Object storage 10TB", 1, 1600.0)])
    r = rule("R4", build_ctx(ex, ref, policy))
    assert r["passed"] is passed
    assert r["evidence"]["tolerance"] == 96.0


@pytest.mark.parametrize("net,passed", [(925.00, True), (925.01, False)])
def test_r4_abs_floor_boundary(ref, policy, net, passed):
    # PO-2026-0111 net 900.00 EUR -> 2% = 18.00 < floor 25.00 -> tolerance 25.00
    ex = make_extraction(vendor_name="Quantum Lab Supplies BV", vendor_tax_id="NL123456789B01", currency="EUR",
                         po_references=("PO-2026-0111",), line_items=[line("Centrifuge annual service", 1, net)],
                         subtotal=net, total=net)
    r = rule("R4", build_ctx(ex, ref, policy))
    assert r["passed"] is passed
    assert r["evidence"]["tolerance"] == 25.0


def test_r4_detail_matches_spec_wording(ref, policy):
    r = rule("R4", build_ctx(apex(flange_unit=486.00), ref, policy))
    assert r["passed"] is False and r["severity"] == "HOLD"
    assert r["detail"] == ("Invoice net 157,200.00 INR exceeds PO net 150,000.00 by 7,200.00; "
                           "tolerance is 3,000.00 (2%)")
    assert r["evidence"] == {"invoice_net": 157200.0, "po_net": 150000.0, "delta": 7200.0, "tolerance": 3000.0}


def test_r4_under_billing_with_nothing_billed_warns(ref, policy):
    r = rule("R4", build_ctx(apex(flange_qty=100), ref, policy))
    assert r["passed"] is True and r["warnings"] == ["partial invoice; PO remains open"]
    assert "partial invoice" in r["detail"]


def test_r4_under_billing_after_earlier_billing_is_silent(ref, policy):
    r = rule("R4", build_ctx(helios(), ref, policy))  # billed 4,000 of 12,000
    assert r["passed"] is True and r["severity"] == "HOLD" and r["warnings"] == []
    assert "partial" not in r["detail"]


# ================================================================ R5
def test_r5_skipped_when_nothing_billed(ref, policy):
    r = rule("R5", build_ctx(apex(flange_unit=486.00), ref, policy))
    assert r["passed"] is None and r["skipped"] is True
    assert r["detail"] == ("Not evaluated: nothing previously billed on this PO; R4 covers the "
                           "single-invoice check.")


def test_r5_skipped_when_nothing_billed_and_net_unknown(ref, policy):
    ctx = build_ctx(make_extraction(subtotal=None, total=None, tax_amount=None), ref, policy)
    assert rule("R4", ctx)["passed"] is False
    assert rule("R5", ctx)["passed"] is None



def test_r5_within_po_passes_and_reports_remaining(ref, policy):
    r = rule("R5", build_ctx(helios(), ref, policy))  # billed 4,000 + 4,000 of 12,000
    assert r["passed"] is True
    assert r["evidence"]["remaining_after"] == 4000.0


def test_r5_fully_consumed_passes(ref, policy):
    r = rule("R5", build_ctx(helios(qty=2, desc="Facility cleaning services – Nov + Dec",
                                    invoice_number="HFM-2026-118"), ref, policy))
    assert r["passed"] is True and "fully consumed" in r["detail"]


def test_r5_over_po_after_earlier_split_holds(ref, policy):
    ref.ledger.append(LedgerRec("HFM-2026-104", "V004", "2026-10-30", "EUR", 4000.0, 4760.0, "PO-2026-0105",
                                "APPROVE", None, "2026-11-01T00:00:00Z", "run", "run_a"))
    r = rule("R5", build_ctx(helios(qty=2, desc="Facility cleaning services – Nov + Dec",
                                    invoice_number="HFM-2026-118"), ref, policy))
    assert r["passed"] is False and r["severity"] == "HOLD"
    ev = r["evidence"]
    assert (ev["billed_net_to_date"], ev["cumulative"], ev["overshoot"]) == (8000.0, 16000.0, 4000.0)


@pytest.mark.parametrize("net,passed", [(8240.00, True), (8240.01, False)])
def test_r5_tolerance_boundary(ref, policy, net, passed):
    # billed 4,000 seed; PO 12,000; tolerance 240 -> cumulative limit 12,240
    r = rule("R5", build_ctx(helios(qty=2, net=net, invoice_number="HFM-X"), ref, policy))
    assert r["passed"] is passed


def test_r5_ignores_hold_rows_for_billing(ref, policy):
    ref.ledger.append(LedgerRec("HFM-2026-200", "V004", "2026-10-20", "EUR", 8000.0, 9520.0, "PO-2026-0105",
                                "HOLD", None, "2026-11-01T00:00:00Z", "run", "run_b"))
    r = rule("R5", build_ctx(helios(), ref, policy))
    assert r["passed"] is True and r["evidence"]["billed_net_to_date"] == 4000.0


# ================================================================ R6
@pytest.mark.parametrize("unit,passed", [(459.00, True), (459.01, False), (441.00, True), (440.99, False)])
def test_r6_unit_price_boundary(ref, policy, unit, passed):
    r = rule("R6", build_ctx(apex(flange_unit=unit), ref, policy))
    assert r["passed"] is passed


def test_r6_variance_detail_names_line_prices_and_pct(ref, policy):
    r = rule("R6", build_ctx(apex(flange_unit=486.00), ref, policy))
    assert r["passed"] is False
    assert "Stainless steel flange DN50" in r["detail"]
    assert "486.00 vs PO 450.00 (+8%, tolerance 2%)" in r["detail"]


def test_r6_quantity_above_po_warns(ref, policy):
    r = rule("R6", build_ctx(apex(flange_qty=210), ref, policy))
    assert r["passed"] is True and r["severity"] == "WARN"
    assert any("quantity on line 1" in w for w in r["warnings"])


def test_r6_small_unmatched_line_warns(ref, policy):
    r = rule("R6", build_ctx(apex(extra_lines=[line("Freight and packing", 1, 1500.0)]), ref, policy))
    assert r["passed"] is True and any("not on the PO" in w for w in r["warnings"])


def test_r6_large_unmatched_line_fails(ref, policy):
    r = rule("R6", build_ctx(apex(extra_lines=[line("Freight and packing", 1, 3000.01)]), ref, policy))
    assert r["passed"] is False and "not on the PO" in r["detail"]


# ================================================================ R7
def test_r7_currency_match_passes(ref, policy):
    assert rule("R7", build_ctx(make_extraction(), ref, policy))["passed"] is True


def test_r7_currency_mismatch_holds(ref, policy):
    r = rule("R7", build_ctx(make_extraction(currency="EUR"), ref, policy))
    assert r["passed"] is False and r["severity"] == "HOLD" and "EUR" in r["detail"]


def test_r7_missing_currency_holds(ref, policy):
    assert rule("R7", build_ctx(make_extraction(currency=None), ref, policy))["passed"] is False


def test_r7_skipped_silently_without_po(ref, policy):
    out = evaluate(build_ctx(make_extraction(po_references=("PO-2026-0199",)), ref, policy))
    r7 = next(r for r in out["results"] if r["code"] == "R7")
    assert r7["passed"] is None and r7["warnings"] == []
    assert not any(w.startswith("R7") for w in out["warnings"])


# ================================================================ R8
def test_r8_complete_passes(ref, policy):
    assert rule("R8", build_ctx(make_extraction(), ref, policy))["passed"] is True


def test_r8_missing_invoice_number_holds(ref, policy):
    r = rule("R8", build_ctx(make_extraction(invoice_number=None), ref, policy))
    assert r["passed"] is False and "invoice number" in r["detail"]


def test_r8_arithmetic_mismatch_holds(ref, policy):
    r = rule("R8", build_ctx(make_extraction(total=4900.0), ref, policy))
    assert r["passed"] is False and r["evidence"]["failed_checks"] == ["subtotal_tax_total"]


# ================================================================ R9
@pytest.mark.parametrize("d,passed", [("2026-08-04", True), ("2026-08-03", False), ("2026-11-02", True),
                                      ("2026-11-03", False)])
def test_r9_date_window_boundaries(ref, policy, d, passed):
    r = rule("R9", build_ctx(make_extraction(invoice_date=d), ref, policy, today=date(2026, 11, 2)))
    assert r["passed"] is passed


def test_r9_future_grace(ref, policy):
    policy.future_date_grace_days = 2
    r = rule("R9", build_ctx(make_extraction(invoice_date="2026-11-04"), ref, policy, today=date(2026, 11, 2)))
    assert r["passed"] is True


def test_r9_skipped_without_date(ref, policy):
    r = rule("R9", build_ctx(make_extraction(invoice_date=None), ref, policy))
    assert r["passed"] is None


# ================================================================ R10
@pytest.mark.parametrize("conf,passed", [(0.75, True), (0.74, False)])
def test_r10_confidence_floor_boundary(ref, policy, conf, passed):
    r = rule("R10", build_ctx(make_extraction(total_conf=conf), ref, policy))
    assert r["passed"] is passed
    if not passed:
        assert "total" in r["detail"] and "0.74" in r["detail"]


def test_r10_absent_field_is_r8s_job_not_r10s(ref, policy):
    r = rule("R10", build_ctx(make_extraction(invoice_number=None, total_conf=0.9), ref, policy))
    assert r["passed"] is True and r["evidence"]["weakest_field"] == "total"


def test_r10_all_critical_fields_null_passes_with_warning(ref, policy):
    ex = make_extraction(invoice_number=None, vendor_name=None, vendor_tax_id=None, total=None, subtotal=None,
                         tax_amount=None)
    ctx = build_ctx(ex, ref, policy)
    assert ctx.critical_confidence["min"] is None
    r = rule("R10", ctx)
    assert r["passed"] is True and r["severity"] == "WARN" and r["warnings"] == ["no fields to assess"]


# ================================================================ aggregation + decision
def test_aggregate_precedence():
    assert aggregate({"failed_reject": ["R3"], "failed_hold": ["R4"]}) == "REJECT"
    assert aggregate({"failed_reject": [], "failed_hold": ["R4"]}) == "HOLD"
    assert aggregate({"failed_reject": [], "failed_hold": []}) == "APPROVE"


def test_decision_happy_path_approves(ref, policy):
    d = decide(build_ctx(make_extraction(), ref, policy))
    assert d["decision"] == "APPROVE" and d["reasons"] == []
    assert d["next_action"]["owner"] == "none" and d["draft_email"] is None
    assert d["booking"] == {"po_number": "PO-2026-0107", "net_amount": 4800.0, "gross_amount": 4800.0,
                            "currency": "USD", "po_remaining_after": 0.0}
    assert d["explanation"].startswith("Invoice MCS-10422 from Meridian Cloud Services Inc for USD 4,800.00 is approved.")
    assert d["explanation"].endswith("Booked against PO-2026-0107; the PO is now fully consumed.")


def test_decision_split_po_reports_remaining(ref, policy):
    d = decide(build_ctx(helios(), ref, policy))
    assert d["decision"] == "APPROVE"
    assert d["booking"]["po_remaining_after"] == 4000.0
    assert d["explanation"].endswith("Booked against PO-2026-0105; EUR 4,000.00 remains open on the PO.")
    assert "partial invoice" not in d["explanation"].lower()


def test_decision_price_variance_holds_with_requester_email(ref, policy):
    d = decide(build_ctx(apex(flange_unit=486.00), ref, policy))
    assert d["decision"] == "HOLD"
    assert [r["code"] for r in d["reasons"]] == ["R4", "R6"]
    assert d["next_action"]["owner"] == "requester"
    assert "Priya Nair" in d["next_action"]["text"] and "486.00" in d["next_action"]["text"]
    assert d["draft_email"]["to"] == "priya.nair@example.com"
    assert len(d["draft_email"]["body"].split()) < 120
    assert d["draft_email"]["body"].rstrip().endswith("AP Automation")
    assert d["booking"]["po_remaining_after"] is None


def test_decision_missing_number_holds_with_vendor_email(ref, policy):
    d = decide(build_ctx(quantum_no_number(), ref, policy))
    assert d["decision"] == "HOLD"
    assert [r["code"] for r in d["reasons"]] == ["R8"]
    assert d["next_action"]["owner"] == "vendor"
    email = d["draft_email"]
    assert email["to"] == "finance@quantumlab.example.nl"
    assert "2026-10-30" in email["subject"] and "EUR 3,811.50" in email["subject"]
    assert "invoice number" in email["body"] and "PO-2026-0109" in email["body"]
    assert len(email["body"].split()) < 120
    assert d["explanation"].startswith("Invoice with no number from Quantum Lab Supplies BV for EUR 3,811.50 is on hold.")


def test_decision_duplicate_rejects(ref, policy):
    ex = make_extraction(invoice_number="MCS-10398", invoice_date="2026-10-01", po_references=("PO-2026-0106",),
                         line_items=[line("Managed backup service – Sep 2026", 1, 2400.0)], subtotal=2400.0,
                         total=2400.0)
    d = decide(build_ctx(ex, ref, policy))
    assert d["decision"] == "REJECT"
    assert "R3" in [r["code"] for r in d["reasons"]]
    assert d["next_action"]["owner"] == "ap" and d["draft_email"] is None


def test_decision_unknown_vendor_rejects(ref, policy):
    ex = make_extraction(vendor_name="Silverline Consulting Partners", vendor_tax_id=None, invoice_number="SCP-0042",
                         po_references=("PO-2026-0199",), line_items=[line("Advisory services", 1, 2500.0)],
                         subtotal=2500.0, total=2500.0, invoice_date="2026-10-28")
    d = decide(build_ctx(ex, ref, policy))
    assert d["decision"] == "REJECT"
    assert d["reasons"][0]["code"] == "R1"
    assert d["next_action"]["owner"] == "ap"


def test_owner_reject_beats_every_hold_owner(ref, policy):
    # R3 rejects; R8 (vendor) and R4 (requester) also fail
    ex = make_extraction(invoice_number="MCS-10398", invoice_date=None, po_references=("PO-2026-0106",),
                         line_items=[line("Managed backup service – Sep 2026", 1, 9000.0)], subtotal=9000.0,
                         total=9000.0)
    d = decide(build_ctx(ex, ref, policy))
    assert d["decision"] == "REJECT" and {"R3", "R4", "R8"} <= {r["code"] for r in d["reasons"]}
    assert d["next_action"]["owner"] == "ap" and d["draft_email"] is None


def test_owner_vendor_beats_requester_and_ap(ref, policy):
    # R8 (no invoice number) + R4/R6 (price variance) + R10 (low confidence on total)
    d = decide(build_ctx(apex(flange_unit=486.00, invoice_number=None, total_conf=0.5), ref, policy))
    assert {"R4", "R6", "R8", "R10"} == {r["code"] for r in d["reasons"]}
    assert d["next_action"]["owner"] == "vendor"
    assert d["draft_email"]["to"] != "priya.nair@example.com" and "invoice number" in d["draft_email"]["body"]


def test_owner_requester_beats_ap(ref, policy):
    # R10 and R9 are AP's, R4/R6 are the requester's
    d = decide(build_ctx(apex(flange_unit=486.00, invoice_date="2026-01-01", total_conf=0.5), ref, policy))
    assert {"R4", "R6", "R9", "R10"} == {r["code"] for r in d["reasons"]}
    assert d["next_action"]["owner"] == "requester" and "Priya Nair" in d["next_action"]["text"]
    assert d["draft_email"]["to"] == "priya.nair@example.com"


def test_owner_ap_when_only_ap_rules_fail(ref, policy):
    d = decide(build_ctx(make_extraction(total_conf=0.5), ref, policy))
    assert [r["code"] for r in d["reasons"]] == ["R10"]
    assert d["next_action"]["owner"] == "ap" and d["draft_email"] is None


def test_decision_confidence_is_critical_min(ref, policy):
    d = decide(build_ctx(make_extraction(vendor_name_conf=0.9), ref, policy))
    assert d["confidence"] == 0.9


def test_rule_results_are_pure(ref, policy):
    ctx = build_ctx(apex(flange_unit=486.00), ref, policy)
    assert evaluate(ctx) == evaluate(ctx)


def test_nominal_severities_cover_all_rules():
    assert set(R.NAMES) == set(R.NOMINAL) == {f"R{i}" for i in range(1, 11)}
