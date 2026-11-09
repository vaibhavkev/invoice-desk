"""Stage 7 - decision: aggregate rule results into APPROVE / HOLD / REJECT (SPEC 4.7).

Everything here is templated; no LLM is involved, so the same inputs always give the same words.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ...rules.engine import aggregate
from ...rules.rules import RuleContext
from ...util import money, pct
from ..types import StageResult

REJECT_PRIORITY = ["R1", "R3", "R2"]
HOLD_PRIORITY = ["R8", "R10", "R9", "R1", "R2", "R4", "R6", "R5", "R7"]
REQUESTER_RULES = ("R2", "R4", "R5", "R6", "R7")
OWNER_PRECEDENCE = ("vendor", "requester", "ap")
MAX_WARNINGS_IN_EXPLANATION = 3


def _sentence(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return s
    s = s[0].upper() + s[1:]
    return s if s.endswith((".", "!", "?")) else s + "."


def _owner(code: str, rule: Dict[str, Any], c: RuleContext) -> str:
    if code in ("R1", "R3", "R9", "R10"):
        return "ap"
    if code == "R8":
        return "vendor"
    if code == "R2":
        m = rule["evidence"].get("method")
        if m in ("not_found", "none") or rule["severity"] == "REJECT":
            return "ap"
        return "requester"
    return "requester"


def _lead(decision: str, failing: List[Dict[str, Any]], c: RuleContext) -> Tuple[Dict[str, Any], str]:
    """The failing rule that sets the next action, and its owner. REJECT is always AP's; a HOLD goes to
    the highest-precedence owner among all failing rules (SPEC 4.7)."""
    if decision == "REJECT":
        return min((r for r in failing if r["severity"] == "REJECT"), key=lambda r: REJECT_PRIORITY.index(r["code"])), "ap"
    lead = min(failing, key=lambda r: (OWNER_PRECEDENCE.index(_owner(r["code"], r, c)), HOLD_PRIORITY.index(r["code"])))
    return lead, _owner(lead["code"], lead, c)


def _requester(c: RuleContext) -> Dict[str, Optional[str]]:
    po = c.po
    if po.get("matched"):
        return {"name": po.get("requester_name"), "email": po.get("requester_email"), "po": po.get("po_number")}
    if po.get("method") == "ambiguous" and po.get("candidates"):
        top = c.ref.po(po["candidates"][0]["po_number"])
        if top:
            return {"name": top.requester_name, "email": top.requester_email, "po": top.po_number}
    return {"name": None, "email": None, "po": None}


def _first_name(name: Optional[str]) -> str:
    return (name or "").split()[0] if name else "there"


def _next_action_text(code: str, rule: Dict[str, Any], c: RuleContext, vendor_label: str,
                      results: List[Dict[str, Any]]) -> str:
    ev = rule["evidence"]
    req = _requester(c)
    who = req["name"] or "the requester"
    po = req["po"] or c.po.get("po_number") or "the PO"
    cur = c.po.get("currency") or c.normalised.get("currency") or ""
    if code == "R1":
        if rule["severity"] == "REJECT":
            return (f"Do not pay. Check whether {vendor_label} should be onboarded as a vendor; until it is in the "
                    f"vendor master, return the invoice to the sender.")
        return f"{vendor_label} is {ev.get('status')}. Check with procurement before releasing any payment."
    if code == "R3":
        earlier = ev.get("earlier_invoice_number") or "an earlier invoice"
        when = f" dated {ev['earlier_invoice_date']}" if ev.get("earlier_invoice_date") else ""
        return (f"Do not pay: this duplicates {earlier}{when}. Confirm with the vendor that the earlier "
                f"invoice covers it.")
    if code == "R2":
        m = ev.get("method")
        if m == "not_found":
            refs = ", ".join(ev.get("references") or []) or "the quoted PO"
            return f"Do not pay: {refs} is not a valid PO. Ask the vendor for the correct PO number."
        if rule["severity"] == "REJECT":
            return f"Do not pay: {ev.get('po_number')} is {ev.get('status')}. Ask the requester whether a new PO is needed."
        if ev.get("vendor_mismatch"):
            return f"Confirm with {who} whether {ev.get('po_number')} should be billed by {vendor_label}."
        if m == "ambiguous":
            cands = ", ".join(x["po_number"] for x in (ev.get("candidates") or [])[:3])
            return f"Ask {who} which PO this invoice belongs to (candidates: {cands})."
        return "Find the PO this invoice belongs to, or ask the vendor to quote one."
    if code in ("R4", "R6"):
        line_fail = None
        r6 = next((r for r in results if r["code"] == "R6" and r["passed"] is False), None)
        if r6:
            for row in r6["evidence"].get("lines", []):
                if row.get("delta_pct") is not None and abs(row["delta_pct"]) > c.policy.tolerance_pct + 1e-9:
                    line_fail = row
                    break
        if line_fail:
            direction = "increase" if line_fail["delta"] > 0 else "decrease"
            return (f"Confirm with {who} ({po}) whether the {line_fail['description']} price {direction} to "
                    f"{money(line_fail['invoice_unit_price'])} was agreed.")
        r4 = next((r for r in results if r["code"] == "R4" and r["passed"] is False), None)
        if r4 and r4["evidence"].get("delta") is not None:
            return (f"Confirm with {who} ({po}) whether the extra {money(r4['evidence']['delta'])} {cur} over the "
                    f"PO was agreed.")
        return f"Confirm with {who} ({po}) whether the invoiced lines were agreed."
    if code == "R5":
        return (f"Ask {who} whether {po} should be increased: billing would reach "
                f"{money(ev.get('cumulative'))} of {money(ev.get('po_net'))} {cur}.")
    if code == "R7":
        return f"Confirm with {who} whether {po} can be paid in {ev.get('invoice_currency') or 'the invoiced currency'}."
    if code == "R8":
        return f"Ask {vendor_label} to reissue the invoice with " + _missing_phrase(ev, c) + "."
    if code == "R9":
        return f"Check the invoice date {ev.get('invoice_date')} with the vendor before paying."
    if code == "R10":
        f = (ev.get("weakest_field") or "the critical fields").replace("_", " ")
        lo = (ev.get("critical_confidence") or {}).get(ev.get("weakest_field"))
        tail = f" (extraction confidence {lo:.2f})" if isinstance(lo, (int, float)) else ""
        return f"Check the {f} against the PDF before paying{tail}."
    return "Review the invoice."


def _missing_phrase(ev: Dict[str, Any], c: RuleContext) -> str:
    labels = {"invoice_number": "an invoice number", "invoice_date": "an invoice date",
              "total": "the total amount", "vendor_name": "your legal company name"}
    parts = [labels[m] for m in ev.get("missing_fields") or []]
    if ev.get("failed_checks"):
        parts.append("corrected amounts (the lines, subtotal, tax and total do not add up)")
    if c.po.get("method") == "inferred" and c.po.get("po_number"):
        parts.append(f"our PO number {c.po['po_number']}")
    elif not c.normalised.get("po_references"):
        parts.append("our PO number")
    if not parts:
        return "the missing details"
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _trim_words(text: str, limit: int = 118) -> str:
    words = text.split(" ")
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]) + "…"


def _draft_email(owner: str, failing: List[Dict[str, Any]], c: RuleContext, vendor_label: str,
                 gross: Optional[float], currency: str) -> Optional[Dict[str, str]]:
    n = c.normalised
    inv_no = n.get("invoice_number")
    inv_date = n.get("invoice_date")
    amount = f"{currency} {money(gross)}".strip() if gross is not None else "an unstated amount"
    if owner == "vendor":
        to = c.vendor.get("contact_email") if c.vendor.get("matched") else None
        if not to:
            return None
        r8 = next(r for r in failing if r["code"] == "R8")
        dated = f"dated {inv_date}" if inv_date else "with no date"
        subject = f"Missing information on your invoice {dated} for {amount}"
        body = (f"Hello {vendor_label} team,\n\n"
                f"We received your invoice {inv_no + ' ' if inv_no else ''}{dated} for {amount}, but we cannot "
                f"process it yet. Please reissue it with {_missing_phrase(r8['evidence'], c)}.\n\n"
                f"Once we receive the corrected invoice we will process it straight away.\n\n"
                f"Thank you,\nAP Automation")
        return {"to": to, "subject": subject, "body": _trim_words(body)}
    if owner == "requester":
        req = _requester(c)
        if not req["email"]:
            return None
        lines = [f"- {_sentence(r['detail'])}" for r in failing if r["code"] in REQUESTER_RULES][:3]
        label = f"invoice {inv_no}" if inv_no else "an invoice with no number"
        subject = f"Please confirm: {vendor_label} {label} on {req['po']}"
        body = (f"Hello {_first_name(req['name'])},\n\n"
                f"{vendor_label} {label}{' dated ' + inv_date if inv_date else ''} for {amount} is on hold "
                f"against {req['po']}:\n\n" + "\n".join(lines) + "\n\n"
                f"Please confirm whether this was agreed, or reply and we will ask the vendor for a corrected "
                f"invoice.\n\nAP Automation")
        return {"to": req["email"], "subject": subject, "body": _trim_words(body)}
    return None


def run_decision(rules_output: Dict[str, Any], c: RuleContext) -> StageResult:
    results = rules_output["results"]
    decision = aggregate(rules_output)
    n = c.normalised
    vendor_label = c.vendor.get("legal_name") if c.vendor.get("matched") else (n.get("vendor_name") or "the vendor")
    currency = n.get("currency") or c.po.get("currency") or ""
    gross = n.get("total")
    net = n.get("subtotal")

    failing = [r for r in results if r["passed"] is False]
    reasons = [{"code": r["code"], "text": _sentence(r["detail"])} for r in failing]
    warnings = list(rules_output.get("warnings") or [])

    # next action
    if decision == "APPROVE":
        po = c.po.get("po_number")
        due = n.get("due_date")
        terms = c.vendor.get("payment_terms_days")
        when = f"by {due}" if due else (f"on {terms}-day terms" if terms else "on the agreed terms")
        next_action = {"owner": "none", "text": f"No action needed: book to {po} and schedule payment {when}."}
        lead = None
    else:
        lead, owner = _lead(decision, failing, c)
        if owner == "requester" and not _requester(c)["email"]:
            owner = "ap"
        next_action = {"owner": owner, "text": _next_action_text(lead["code"], lead, c, vendor_label, results)}

    draft = None
    if next_action["owner"] in ("vendor", "requester"):
        draft = _draft_email(next_action["owner"], failing, c, vendor_label, gross, currency)

    # booking
    remaining_after = None
    if decision == "APPROVE" and c.po.get("matched") and net is not None:
        remaining_after = round((c.po.get("remaining_net") or 0.0) - net, 2)
    booking = {"po_number": c.po.get("po_number"), "net_amount": net, "gross_amount": gross,
               "currency": currency or None, "po_remaining_after": remaining_after}

    # explanation (templated)
    no = n.get("invoice_number") or "with no number"
    verb = {"APPROVE": "approved", "HOLD": "on hold", "REJECT": "rejected"}[decision]
    sentences = [f"Invoice {no} from {vendor_label} for {currency} {money(gross)} is {verb}.".replace("  ", " ")]
    sentences += [_sentence(r["detail"]) for r in failing]
    for w in warnings[:MAX_WARNINGS_IN_EXPLANATION]:
        sentences.append("Note: " + _sentence(w.split(": ", 1)[-1]))
    if decision == "APPROVE" and c.po.get("po_number"):
        if remaining_after is not None and remaining_after <= 0.005:
            sentences.append(f"Booked against {c.po['po_number']}; the PO is now fully consumed.")
        else:
            sentences.append(f"Booked against {c.po['po_number']}; {c.po.get('currency') or currency} "
                             f"{money(remaining_after)} remains open on the PO.")
    explanation = " ".join(sentences)

    confidence = c.critical_confidence.get("min")
    output = {"decision": decision, "confidence": confidence, "reasons": reasons, "warnings": warnings,
              "explanation": explanation, "next_action": next_action, "draft_email": draft, "booking": booking}

    if decision == "APPROVE":
        summary = "Approved for payment."
    elif decision == "HOLD":
        summary = f"On hold ({', '.join(r['code'] for r in failing)})."
    else:
        summary = f"Rejected ({', '.join(r['code'] for r in failing if r['severity'] == 'REJECT')})."
    return StageResult(summary=summary, output=output, status="done", warnings=[])
