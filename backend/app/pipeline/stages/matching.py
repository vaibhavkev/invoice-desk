"""Stage 5 - vendor and PO matching (SPEC 4.5)."""
from __future__ import annotations

from typing import Any, Dict

from ...matching.po import match_po
from ...matching.vendor import match_vendor
from ...refdata import RefData
from ...util import money
from ..types import StageResult

_VENDOR_METHOD = {"tax_id": "matched on tax ID", "alias": "matched on name", "name_fuzzy": "close name match"}
_PO_METHOD = {"explicit": "quoted on invoice"}


def run_matching(normalised: Dict[str, Any], ref: RefData) -> StageResult:
    vendor = match_vendor(normalised.get("vendor_name"), normalised.get("vendor_tax_id"), ref)
    po = match_po(normalised, vendor, ref)
    warnings = list(vendor.get("warnings") or [])

    if vendor["matched"]:
        v_txt = f"Vendor {vendor['vendor_id']} {vendor['legal_name']} ({_VENDOR_METHOD.get(vendor['method'], vendor['method'])}"
        if vendor["method"] == "name_fuzzy":
            v_txt += f", score {vendor['score']:.2f}"
        v_txt += ")"
        if vendor["status"] != "approved":
            v_txt += f", status {vendor['status']}"
        v_txt += "."
    else:
        name = normalised.get("vendor_name") or "the issuer"
        v_txt = f"No vendor in the master matches {name}."

    m = po["method"]
    if po["matched"]:
        p_txt = f" {po['po_number']} ({_PO_METHOD.get(m, m)}"
        if m == "inferred":
            p_txt += f", score {po['score']:.2f}"
        p_txt += f"): {money(po['billed_net_to_date'])} of {money(po['net_total'])} {po['currency']} already billed"
        p_txt += f", {money(po['remaining_net'])} remaining."
        if po["status"] != "open":
            p_txt += f" The PO is {po['status']}."
        if po["vendor_mismatch"]:
            p_txt += f" The PO belongs to a different vendor ({po['vendor_id']})."
            warnings.append(f"{po['po_number']} belongs to vendor {po['vendor_id']}, not the invoicing vendor.")
        if po["unmatched_invoice_lines"]:
            warnings.append("Invoice line(s) " + ", ".join(map(str, po["unmatched_invoice_lines"]))
                            + " do not match any PO line.")
    elif m == "not_found":
        p_txt = f" PO reference {', '.join(po.get('references') or [])} does not exist in the PO register."
    elif m == "ambiguous":
        top = ", ".join(f"{c['po_number']} ({c['score']:.2f})" for c in po["candidates"][:3])
        p_txt = f" No PO quoted and no single PO fits clearly; candidates: {top}."
    else:
        p_txt = " No PO quoted and no open PO could be inferred."

    output = {"vendor": {k: v for k, v in vendor.items() if k != "warnings"}, "po": po}
    status = "done" if vendor["matched"] and po["matched"] else "warn"
    return StageResult(summary=v_txt + p_txt, output=output, status=status, warnings=warnings)
