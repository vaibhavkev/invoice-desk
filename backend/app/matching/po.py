"""PO matching (SPEC 4.5): explicit reference -> inferred by amount + lines -> ambiguous / none."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz, utils

from ..refdata import PORec, RefData
from ..util import norm_ref, r2

LINE_MATCH_THRESHOLD = 80
INFER_MIN_SCORE = 0.80
INFER_MIN_GAP = 0.20


def _line_sim(a: str, b: str) -> float:
    return fuzz.token_set_ratio(a, b, processor=utils.default_process)


def match_lines(invoice_lines: List[Dict[str, Any]], po: PORec) -> Dict[str, Any]:
    """Best PO line per invoice line by token_set_ratio; >= 80 counts as a match."""
    matches, unmatched = [], []
    for i, il in enumerate(invoice_lines, start=1):
        best_line, best = None, 0.0
        for pl in po.lines:
            s = _line_sim(il.get("description") or "", pl.description)
            if s > best:
                best_line, best = pl, s
        if best_line is not None and best >= LINE_MATCH_THRESHOLD:
            matches.append({"invoice_line": i, "po_line": best_line.line_no, "score": round(best / 100, 2)})
        else:
            unmatched.append(i)
    return {"line_matches": matches, "unmatched_invoice_lines": unmatched}


def line_score(invoice_lines: List[Dict[str, Any]], po: PORec) -> float:
    """Mean over invoice lines of the best token_set_ratio/100 against the PO's lines."""
    if not invoice_lines or not po.lines:
        return 0.0
    bests = [max(_line_sim(il.get("description") or "", pl.description) for pl in po.lines) / 100
             for il in invoice_lines]
    return sum(bests) / len(bests)


def _po_payload(po: PORec, ref: RefData, invoice_lines, vendor_id: Optional[str]) -> Dict[str, Any]:
    billed = ref.billed_net_to_date(po.po_number)
    payload = {
        "po_number": po.po_number,
        "status": po.status,
        "vendor_id": po.vendor_id,
        "vendor_mismatch": bool(vendor_id) and po.vendor_id != vendor_id,
        "currency": po.currency,
        "net_total": r2(po.net_total),
        "billed_net_to_date": billed,
        "remaining_net": r2(po.net_total - billed),
        "requester_name": po.requester_name,
        "requester_email": po.requester_email,
    }
    payload.update(match_lines(invoice_lines, po))
    return payload


def _empty(method: str, candidates=None, extra=None) -> Dict[str, Any]:
    out = {"matched": False, "po_number": None, "method": method, "score": 0.0, "status": None,
           "vendor_id": None, "vendor_mismatch": False, "currency": None, "net_total": None,
           "billed_net_to_date": None, "remaining_net": None, "candidates": candidates or [],
           "line_matches": [], "unmatched_invoice_lines": []}
    out.update(extra or {})
    return out


def match_po(normalised: Dict[str, Any], vendor: Dict[str, Any], ref: RefData) -> Dict[str, Any]:
    refs_n: List[str] = normalised.get("po_references_normalised") or []
    lines = normalised.get("line_items") or []
    vendor_id = vendor.get("vendor_id") if vendor.get("matched") else None

    # (1) explicit reference
    if refs_n:
        def ref_index(p: PORec) -> Optional[int]:
            # exact normalised match, or the PO number embedded in a longer quoted string
            pn = norm_ref(p.po_number)
            for i, r in enumerate(refs_n):
                if r == pn or (len(pn) >= 6 and pn in r):
                    return i
            return None

        hits = [p for p in ref.pos if ref_index(p) is not None]
        if hits:
            hits.sort(key=lambda p: (p.vendor_id != vendor_id, ref_index(p)))
            po = hits[0]
            out = {"matched": True, "method": "explicit", "score": 1.0, "candidates": []}
            out.update(_po_payload(po, ref, lines, vendor_id))
            return out
        return _empty("not_found", extra={"references": normalised.get("po_references") or []})

    # (2) inferred from vendor + amount + lines
    if not vendor_id:
        return _empty("none")
    open_pos = [p for p in ref.pos if p.vendor_id == vendor_id and p.status == "open"]
    if not open_pos:
        return _empty("none")
    invoice_net = normalised.get("subtotal")
    cands = []
    for p in open_pos:
        remaining = p.net_total - ref.billed_net_to_date(p.po_number)
        if invoice_net is None or not p.net_total:
            amount_score = 0.0
        else:
            amount_score = max(0.0, 1 - abs(invoice_net - remaining) / p.net_total)
        ls = line_score(lines, p)
        score = 0.6 * amount_score + 0.4 * ls
        cands.append({"po_number": p.po_number, "score": round(score, 3),
                      "amount_score": round(amount_score, 3), "line_score": round(ls, 3)})
    cands.sort(key=lambda c: -c["score"])
    top = cands[0]
    runner_up = cands[1]["score"] if len(cands) > 1 else 0.0
    if top["score"] >= INFER_MIN_SCORE and top["score"] - runner_up >= INFER_MIN_GAP:
        po = ref.po(top["po_number"])
        out = {"matched": True, "method": "inferred", "score": round(top["score"], 2), "candidates": cands}
        out.update(_po_payload(po, ref, lines, vendor_id))
        return out
    return _empty("ambiguous", candidates=cands, extra={"score": round(top["score"], 2)})
