"""Vendor matching (SPEC 4.5): tax id exact -> name/alias exact -> fuzzy name >= 90."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz

from ..refdata import RefData, VendorRec
from ..util import norm_name, norm_tax_id

FUZZY_THRESHOLD = 90


def _names(v: VendorRec) -> List[str]:
    return [v.legal_name] + list(v.aliases)


def _best_name_score(name_n: str, v: VendorRec) -> float:
    best = 0.0
    for n in _names(v):
        nn = norm_name(n)
        if nn:
            best = max(best, fuzz.token_set_ratio(name_n, nn))
    return best


def _result(v: Optional[VendorRec], method: Optional[str], score: float, candidates: List[Dict[str, Any]],
            warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "matched": v is not None,
        "vendor_id": v.vendor_id if v else None,
        "legal_name": v.legal_name if v else None,
        "status": v.status if v else None,
        "method": method,
        "score": round(score, 2),
        "candidates": candidates,
        "contact_email": v.contact_email if v else None,
        "currency": v.currency if v else None,
        "payment_terms_days": v.payment_terms_days if v else None,
        "warnings": warnings or [],
    }


def match_vendor(vendor_name: Optional[str], vendor_tax_id: Optional[str], ref: RefData) -> Dict[str, Any]:
    tax_n = norm_tax_id(vendor_tax_id)
    name_n = norm_name(vendor_name)

    # Candidate list (top 3 by fuzzy name score) is reported in every case.
    scored = sorted(((round(_best_name_score(name_n, v) / 100, 2) if name_n else 0.0, v) for v in ref.vendors),
                    key=lambda t: -t[0])
    candidates = [{"vendor_id": v.vendor_id, "score": s, "method": "name_fuzzy"} for s, v in scored[:3]]

    # (1) tax id exact
    if tax_n:
        for v in ref.vendors:
            if norm_tax_id(v.tax_id) and norm_tax_id(v.tax_id) == tax_n:
                warnings = []
                name_score = _best_name_score(name_n, v) if name_n else 100.0
                if name_n and name_score < FUZZY_THRESHOLD:
                    warnings.append(f"Tax id matches {v.legal_name} but the printed name "
                                    f"{vendor_name!r} does not (name score {name_score:.0f}).")
                cands = [{"vendor_id": v.vendor_id, "score": 1.0, "method": "tax_id"}] + \
                        [c for c in candidates if c["vendor_id"] != v.vendor_id][:2]
                return _result(v, "tax_id", 1.0, cands, warnings)

    def tax_warning(v: VendorRec) -> List[str]:
        if tax_n and norm_tax_id(v.tax_id) and norm_tax_id(v.tax_id) != tax_n:
            return [f"Printed tax id {vendor_tax_id} differs from the vendor master ({v.tax_id})."]
        return []

    # (2) normalised name equals legal name or an alias
    if name_n:
        for v in ref.vendors:
            if any(norm_name(n) == name_n for n in _names(v)):
                cands = [{"vendor_id": v.vendor_id, "score": 1.0, "method": "alias"}] + \
                        [c for c in candidates if c["vendor_id"] != v.vendor_id][:2]
                return _result(v, "alias", 1.0, cands, tax_warning(v))

        # (3) fuzzy
        if scored and scored[0][0] * 100 >= FUZZY_THRESHOLD:
            s, v = scored[0]
            return _result(v, "name_fuzzy", s, candidates, tax_warning(v))

    return _result(None, None, scored[0][0] if scored else 0.0, candidates)
