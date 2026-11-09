"""Policy rules R1-R10 (SPEC 4.6). Each rule is a pure function of a ``RuleContext``.

A rule returns a dict:
    code, name, passed (True | False | None when skipped), skipped, severity (REJECT | HOLD | WARN),
    detail (one readable sentence), evidence (numbers behind the detail), warnings (list of str)

``severity`` on a failed rule is the consequence. On a passed rule it is "WARN" if the rule
raised a warning, otherwise the rule's nominal failure severity (what it guards against).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from ..config import PolicyConfig
from ..refdata import RefData
from ..util import EPS, money, norm_ref, parse_iso_date, pct, r2

NAMES = {
    "R1": "Vendor approved",
    "R2": "PO valid",
    "R3": "Not a duplicate",
    "R4": "Invoice total within PO tolerance",
    "R5": "Cumulative billing within PO",
    "R6": "Line prices within tolerance",
    "R7": "Currency matches PO",
    "R8": "Document complete",
    "R9": "Invoice date in window",
    "R10": "Extraction confidence",
}
NOMINAL = {"R1": "REJECT", "R2": "HOLD", "R3": "REJECT", "R4": "HOLD", "R5": "HOLD", "R6": "HOLD",
           "R7": "HOLD", "R8": "HOLD", "R9": "HOLD", "R10": "HOLD"}
PO_RULES = ("R4", "R5", "R6", "R7")


@dataclass
class RuleContext:
    normalised: Dict[str, Any]
    checks: List[Dict[str, Any]]
    critical_confidence: Dict[str, Any]
    vendor: Dict[str, Any]
    po: Dict[str, Any]
    ref: RefData
    policy: PolicyConfig
    today: date
    file_hash: Optional[str] = None
    exclude_run_id: Optional[str] = None

    @property
    def invoice_net(self) -> Optional[float]:
        return self.normalised.get("subtotal")

    @property
    def po_matched(self) -> bool:
        return bool(self.po.get("matched"))

    def tol_total(self) -> float:
        po_net = self.po.get("net_total") or 0.0
        return r2(max(self.policy.tolerance_pct * po_net, self.policy.abs_floor(self.po.get("currency"))))

    def tol_basis(self) -> str:
        po_net = self.po.get("net_total") or 0.0
        if self.policy.tolerance_pct * po_net >= self.policy.abs_floor(self.po.get("currency")):
            return pct(self.policy.tolerance_pct)
        return f"floor {money(self.policy.abs_floor(self.po.get('currency')))}"


def result(code: str, passed: Optional[bool], detail: str, evidence: Optional[Dict[str, Any]] = None,
           severity: Optional[str] = None, warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    warnings = warnings or []
    if passed is None:
        sev = NOMINAL[code]
    elif passed:
        sev = "WARN" if warnings else NOMINAL[code]
    else:
        sev = severity or NOMINAL[code]
    return {"code": code, "name": NAMES[code], "passed": passed, "skipped": passed is None,
            "severity": sev, "detail": detail, "evidence": evidence or {}, "warnings": warnings}


def skipped(code: str, why: str) -> Dict[str, Any]:
    return result(code, None, why)


# ---------------------------------------------------------------- R1
def r1_vendor_approved(c: RuleContext) -> Dict[str, Any]:
    v = c.vendor
    if not v.get("matched"):
        name = c.normalised.get("vendor_name") or "The issuing vendor"
        closest = (v.get("candidates") or [{}])[0]
        hint = f" (closest: {closest['vendor_id']}, score {closest['score']:.2f})" if closest.get("vendor_id") else ""
        return result("R1", False, f"{name} is not in the vendor master{hint}.",
                      {"vendor_name": c.normalised.get("vendor_name"), "candidates": v.get("candidates")},
                      severity="REJECT")
    if v.get("status") != "approved":
        return result("R1", False, f"{v['vendor_id']} {v['legal_name']} is {v.get('status')} in the vendor master.",
                      {"vendor_id": v["vendor_id"], "status": v.get("status")}, severity="HOLD")
    return result("R1", True, f"{v['vendor_id']} {v['legal_name']} is an approved vendor.",
                  {"vendor_id": v["vendor_id"], "method": v.get("method"), "score": v.get("score")})


# ---------------------------------------------------------------- R2
def r2_po_valid(c: RuleContext) -> Dict[str, Any]:
    p = c.po
    m = p.get("method")
    if m in ("explicit", "inferred"):
        ev = {"po_number": p["po_number"], "method": m, "status": p.get("status"),
              "vendor_mismatch": p.get("vendor_mismatch"), "score": p.get("score")}
        if p.get("status") != "open":
            return result("R2", False, f"{p['po_number']} is {p.get('status')}; no further invoices can be booked to it.",
                          ev, severity="REJECT")
        if p.get("vendor_mismatch"):
            return result("R2", False, f"{p['po_number']} belongs to vendor {p.get('vendor_id')}, "
                                       f"not to the invoicing vendor.", ev, severity="HOLD")
        if m == "inferred":
            return result("R2", True, f"No PO was quoted; {p['po_number']} was inferred from vendor, amount and "
                                      f"lines (score {p.get('score', 0):.2f}).", ev,
                          warnings=["PO inferred, confirm with requester"])
        return result("R2", True, f"{p['po_number']} is quoted on the invoice and is open.", ev)
    if m == "not_found":
        refs = ", ".join(p.get("references") or []) or "a PO reference"
        return result("R2", False, f"The invoice quotes {refs}, which does not exist in the PO register.",
                      {"references": p.get("references"), "method": m}, severity="REJECT")
    if m == "ambiguous":
        cands = ", ".join(f"{x['po_number']} ({x['score']:.2f})" for x in (p.get("candidates") or [])[:3])
        return result("R2", False, f"No PO was quoted and more than one open PO could fit: {cands}.",
                      {"method": m, "candidates": p.get("candidates")}, severity="HOLD")
    return result("R2", False, "No PO was quoted and no open PO for this vendor could be inferred.",
                  {"method": m or "none"}, severity="HOLD")


# ---------------------------------------------------------------- R3
def r3_not_duplicate(c: RuleContext) -> Dict[str, Any]:
    vid = c.vendor.get("vendor_id") if c.vendor.get("matched") else None
    inv_no = norm_ref(c.normalised.get("invoice_number"))
    net = c.invoice_net
    inv_date = parse_iso_date(c.normalised.get("invoice_date"))
    window = c.policy.duplicate_date_window_days
    rows = [r for r in c.ref.ledger if r.decision != "REJECT"
            and not (c.exclude_run_id and r.run_id == c.exclude_run_id)]

    def describe(r, why: str) -> Dict[str, Any]:
        label = r.invoice_number or "an invoice with no number"
        when = f" dated {r.invoice_date}" if r.invoice_date else ""
        source = "a previous run" if r.source == "run" else "the ledger"
        net_txt = f", net {money(r.net_total)} {r.currency or ''}".rstrip() if r.net_total is not None else ""
        return result("R3", False,
                      f"Duplicate of {label}{when}{net_txt}, already recorded in {source} "
                      f"with decision {r.decision} ({why}).",
                      {"match": why, "earlier_invoice_number": r.invoice_number, "earlier_invoice_date": r.invoice_date,
                       "earlier_net_total": r.net_total, "earlier_decision": r.decision,
                       "earlier_source": r.source, "earlier_run_id": r.run_id, "po_number": r.po_number},
                      severity="REJECT")

    if vid and inv_no:
        for r in rows:
            if r.vendor_id == vid and norm_ref(r.invoice_number) == inv_no:
                return describe(r, "same vendor and invoice number")
    if c.file_hash:
        for r in rows:
            if r.file_hash and r.file_hash.lower() == c.file_hash.lower():
                return describe(r, "identical file")
    if vid and net is not None and inv_date is not None:
        for r in rows:
            d = parse_iso_date(r.invoice_date)
            if (r.vendor_id == vid and r.net_total is not None and abs(r.net_total - net) < EPS
                    and d is not None and abs((d - inv_date).days) <= window):
                return describe(r, f"same vendor and net amount within {window} days")
    checked = ["file fingerprint"]
    if vid and inv_no:
        checked.insert(0, "vendor + invoice number")
    if vid and net is not None and inv_date is not None:
        checked.append(f"vendor + amount + date ±{window}d")
    return result("R3", True, f"No earlier invoice matches ({', '.join(checked)} checked against "
                              f"{len(rows)} ledger rows).", {"ledger_rows_checked": len(rows), "checks": checked})


# ---------------------------------------------------------------- R4
def r4_total_within_po(c: RuleContext) -> Dict[str, Any]:
    if not c.po_matched:
        return skipped("R4", "Not evaluated: no PO matched.")
    po_net, cur = c.po["net_total"], c.po.get("currency") or ""
    net = c.invoice_net
    tol = c.tol_total()
    if net is None:
        return result("R4", False, "The invoice net amount could not be determined, so it cannot be compared "
                                   "with the PO.", {"po_net": po_net, "tolerance": tol})
    delta = r2(net - po_net)
    ev = {"invoice_net": net, "po_net": po_net, "delta": delta, "tolerance": tol}
    if net > po_net + tol + EPS:
        return result("R4", False, f"Invoice net {money(net)} {cur} exceeds PO net {money(po_net)} by "
                                   f"{money(delta)}; tolerance is {money(tol)} ({c.tol_basis()})", ev)
    if net < po_net - tol - EPS:
        if c.po.get("billed_net_to_date"):
            return result("R4", True, f"Invoice net {money(net)} {cur} is below PO net {money(po_net)}; "
                                      f"R5 covers the cumulative position.", ev)
        return result("R4", True, f"Invoice net {money(net)} {cur} is below PO net {money(po_net)}: "
                                  f"partial invoice; PO remains open.", ev,
                      warnings=["partial invoice; PO remains open"])
    return result("R4", True, f"Invoice net {money(net)} {cur} is within tolerance of PO net {money(po_net)} "
                              f"(tolerance {money(tol)}, {c.tol_basis()}).", ev)


# ---------------------------------------------------------------- R5
def r5_cumulative_within_po(c: RuleContext) -> Dict[str, Any]:
    if not c.po_matched:
        return skipped("R5", "Not evaluated: no PO matched.")
    po_net, cur = c.po["net_total"], c.po.get("currency") or ""
    billed = c.po.get("billed_net_to_date") or 0.0
    if not billed:
        return skipped("R5", "Not evaluated: nothing previously billed on this PO; R4 covers the "
                             "single-invoice check.")
    net = c.invoice_net
    tol = c.tol_total()
    if net is None:
        return result("R5", False, "The invoice net amount could not be determined, so cumulative billing "
                                   "cannot be checked.", {"billed_net_to_date": billed, "po_net": po_net})
    cumulative = r2(billed + net)
    remaining_after = r2(po_net - cumulative)
    overshoot = r2(max(0.0, cumulative - po_net))
    ev = {"billed_net_to_date": billed, "invoice_net": net, "po_net": po_net, "cumulative": cumulative,
          "tolerance": tol, "remaining_after": remaining_after, "overshoot": overshoot}
    if cumulative > po_net + tol + EPS:
        return result("R5", False, f"Already billed {money(billed)} + this invoice {money(net)} = "
                                   f"{money(cumulative)} {cur}, which exceeds the PO total {money(po_net)} by "
                                   f"{money(overshoot)} (tolerance {money(tol)}).", ev)
    if remaining_after <= EPS:
        tail = "the PO is fully consumed."
    else:
        tail = f"{money(remaining_after)} remains."
    return result("R5", True, f"Billed to date {money(billed)} + this invoice {money(net)} = {money(cumulative)} "
                              f"of {money(po_net)} {cur}; {tail}", ev)


# ---------------------------------------------------------------- R6
def r6_line_prices(c: RuleContext) -> Dict[str, Any]:
    if not c.po_matched:
        return skipped("R6", "Not evaluated: no PO matched.")
    po = c.ref.po(c.po["po_number"])
    lines = c.normalised.get("line_items") or []
    p_pct = c.policy.tolerance_pct
    failures, warnings, evidence = [], [], []
    po_lines = {l.line_no: l for l in (po.lines if po else [])}
    for m in c.po.get("line_matches") or []:
        il = lines[m["invoice_line"] - 1]
        pl = po_lines.get(m["po_line"])
        if pl is None:
            continue
        desc = il.get("description") or f"line {m['invoice_line']}"
        unit = il.get("unit_price")
        row = {"invoice_line": m["invoice_line"], "po_line": pl.line_no, "description": desc,
               "invoice_unit_price": unit, "po_unit_price": pl.unit_price,
               "invoice_quantity": il.get("quantity"), "po_quantity": pl.quantity}
        if unit is None:
            warnings.append(f"line {m['invoice_line']} has no unit price; price not checked")
        else:
            delta = unit - pl.unit_price
            delta_pct = delta / pl.unit_price if pl.unit_price else 0.0
            row["delta"], row["delta_pct"] = r2(delta), round(delta_pct, 4)
            if abs(delta) > p_pct * pl.unit_price + EPS:
                sign = "+" if delta > 0 else "−"
                failures.append(f"Line {m['invoice_line']} '{desc}': unit price {money(unit)} vs PO "
                                f"{money(pl.unit_price)} ({sign}{pct(abs(delta_pct))}, tolerance {pct(p_pct)})")
        q = il.get("quantity")
        if q is not None and q > pl.quantity + 1e-9:
            warnings.append(f"quantity on line {m['invoice_line']} ({q:g}) exceeds PO quantity ({pl.quantity:g})")
        evidence.append(row)
    unmatched = c.po.get("unmatched_invoice_lines") or []
    if unmatched:
        amt = r2(sum((lines[i - 1].get("amount") or 0.0) for i in unmatched))
        names = ", ".join(f"{i} '{lines[i - 1].get('description')}'" for i in unmatched)
        tol = c.tol_total()
        if amt > tol + EPS:
            failures.append(f"Line(s) {names} totalling {money(amt)} are not on the PO (more than the "
                            f"{money(tol)} tolerance)")
        else:
            warnings.append(f"line(s) {names} ({money(amt)}) are not on the PO but within tolerance")
    ev = {"lines": evidence, "unmatched_invoice_lines": unmatched, "tolerance_pct": p_pct}
    if failures:
        return result("R6", False, "; ".join(failures) + ".", ev, warnings=warnings)
    n = len(evidence)
    return result("R6", True, f"{n} matched line{'s' if n != 1 else ''} priced within {pct(p_pct)} of the PO.",
                  ev, warnings=warnings)


# ---------------------------------------------------------------- R7
def r7_currency(c: RuleContext) -> Dict[str, Any]:
    if not c.po_matched:
        return skipped("R7", "Not evaluated: no PO matched.")
    inv_cur, po_cur = c.normalised.get("currency"), c.po.get("currency")
    ev = {"invoice_currency": inv_cur, "po_currency": po_cur}
    if not inv_cur:
        return result("R7", False, f"The invoice does not show a currency; the PO is in {po_cur}.", ev)
    if inv_cur != po_cur:
        return result("R7", False, f"Invoice is in {inv_cur} but {c.po['po_number']} is in {po_cur}.", ev)
    return result("R7", True, f"Invoice and PO are both in {po_cur}.", ev)


# ---------------------------------------------------------------- R8
def r8_document_complete(c: RuleContext) -> Dict[str, Any]:
    n = c.normalised
    missing = [f for f in ("invoice_number", "invoice_date", "total", "vendor_name") if n.get(f) in (None, "")]
    by_code = {ch["code"]: ch for ch in c.checks}
    failed_checks = [by_code[k] for k in ("lines_sum_subtotal", "subtotal_tax_total")
                     if k in by_code and not by_code[k]["passed"]]
    ev = {"missing_fields": missing, "failed_checks": [ch["code"] for ch in failed_checks]}
    if missing or failed_checks:
        parts = []
        if missing:
            parts.append("missing " + ", ".join(f.replace("_", " ") for f in missing))
        for ch in failed_checks:
            parts.append(ch["detail"].rstrip("."))
        return result("R8", False, "Document incomplete: " + "; ".join(parts) + ".", ev)
    return result("R8", True, "Invoice number, date, total and vendor are present and the arithmetic adds up.", ev)


# ---------------------------------------------------------------- R9
def r9_date_window(c: RuleContext) -> Dict[str, Any]:
    d = parse_iso_date(c.normalised.get("invoice_date"))
    if d is None:
        return skipped("R9", "Not evaluated: no readable invoice date (see R8).")
    earliest = date.fromordinal(c.today.toordinal() - c.policy.date_window_days)
    latest = date.fromordinal(c.today.toordinal() + c.policy.future_date_grace_days)
    age = (c.today - d).days
    ev = {"invoice_date": d.isoformat(), "today": c.today.isoformat(), "age_days": age,
          "window_days": c.policy.date_window_days, "earliest": earliest.isoformat(), "latest": latest.isoformat()}
    if d > latest:
        return result("R9", False, f"Invoice date {d.isoformat()} is in the future (today is {c.today.isoformat()}).", ev)
    if d < earliest:
        return result("R9", False, f"Invoice date {d.isoformat()} is {age} days old; the limit is "
                                   f"{c.policy.date_window_days} days.", ev)
    return result("R9", True, f"Invoice date {d.isoformat()} is {age} days old, inside the "
                              f"{c.policy.date_window_days}-day window.", ev)


# ---------------------------------------------------------------- R10
def r10_confidence(c: RuleContext) -> Dict[str, Any]:
    cc = c.critical_confidence
    floor = c.policy.confidence_floor
    present = {f: cc.get(f) for f in ("invoice_number", "total", "vendor_name")
               if c.normalised.get(f) not in (None, "") and cc.get(f) is not None}
    ev = {"critical_confidence": cc, "floor": floor}
    if not present:
        return result("R10", True, "No critical field (invoice number, total, vendor) was found, so there is no "
                                   "extraction confidence to assess (R8 covers the missing fields).", ev,
                      warnings=["no fields to assess"])
    weakest = min(present, key=lambda f: present[f])
    lo = present[weakest]
    ev["weakest_field"] = weakest
    label = weakest.replace("_", " ")
    if lo < floor - 1e-9:
        return result("R10", False, f"Confidence on {label} is {lo:.2f}, below the {floor:.2f} floor; a person "
                                    f"should check it against the PDF.", ev)
    return result("R10", True, f"Lowest confidence on critical fields is {lo:.2f} ({label}); floor {floor:.2f}.", ev)


RULES: List[Callable[[RuleContext], Dict[str, Any]]] = [
    r1_vendor_approved, r2_po_valid, r3_not_duplicate, r4_total_within_po, r5_cumulative_within_po,
    r6_line_prices, r7_currency, r8_document_complete, r9_date_window, r10_confidence,
]
