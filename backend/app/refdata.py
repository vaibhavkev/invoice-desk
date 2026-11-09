"""Plain in-memory view of the reference data (vendors, POs, ledger).

Pipeline stages are pure functions of their inputs plus a ``RefData`` snapshot, so unit tests
can build one straight from CSV fixtures without touching the database.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


def _money(v) -> Optional[float]:
    if v is None or str(v).strip() == "":
        return None
    return round(float(str(v).replace(",", "")), 2)


def _opt(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


@dataclass
class VendorRec:
    vendor_id: str
    legal_name: str
    aliases: List[str]
    tax_id: str
    country: str
    currency: str
    status: str
    payment_terms_days: int
    contact_email: str


@dataclass
class POLineRec:
    line_no: int
    description: str
    quantity: float
    unit_price: float
    line_total: float


@dataclass
class PORec:
    po_number: str
    vendor_id: str
    po_date: str
    currency: str
    net_total: float
    status: str
    requester_name: str
    requester_email: str
    description: str
    lines: List[POLineRec] = field(default_factory=list)


@dataclass
class LedgerRec:
    invoice_number: Optional[str]
    vendor_id: Optional[str]
    invoice_date: Optional[str]
    currency: Optional[str]
    net_total: Optional[float]
    gross_total: Optional[float]
    po_number: Optional[str]
    decision: str
    file_hash: Optional[str]
    processed_at: str
    source: str = "seed"
    run_id: Optional[str] = None


@dataclass
class RefData:
    vendors: List[VendorRec]
    pos: List[PORec]
    ledger: List[LedgerRec]

    def vendor(self, vendor_id: Optional[str]) -> Optional[VendorRec]:
        return next((v for v in self.vendors if v.vendor_id == vendor_id), None)

    def po(self, po_number: Optional[str]) -> Optional[PORec]:
        return next((p for p in self.pos if p.po_number == po_number), None)

    def billed_net_to_date(self, po_number: str) -> float:
        """Sum of net over APPROVE ledger rows on this PO (SPEC 4.5)."""
        total = sum((r.net_total or 0.0) for r in self.ledger
                    if r.po_number == po_number and r.decision == "APPROVE")
        return round(total, 2)

    # ---- loaders -------------------------------------------------------
    @classmethod
    def from_csv_dir(cls, data_dir: Path) -> "RefData":
        data_dir = Path(data_dir)
        vendors = [vendor_from_row(r) for r in read_csv(data_dir / "vendors.csv")]
        pos = [po_from_row(r) for r in read_csv(data_dir / "purchase_orders.csv")]
        by_po: Dict[str, PORec] = {p.po_number: p for p in pos}
        for r in read_csv(data_dir / "po_lines.csv"):
            line = po_line_from_row(r)
            if r["po_number"].strip() in by_po:
                by_po[r["po_number"].strip()].lines.append(line)
        for p in pos:
            p.lines.sort(key=lambda l: l.line_no)
        ledger = [ledger_from_row(r) for r in read_csv(data_dir / "ledger_seed.csv")]
        return cls(vendors=vendors, pos=pos, ledger=ledger)

    @classmethod
    def from_db(cls, session) -> "RefData":
        from sqlmodel import select
        from .models import LedgerEntry, POLine, PurchaseOrder, Vendor

        vendors = [VendorRec(
            vendor_id=v.vendor_id, legal_name=v.legal_name,
            aliases=[a.strip() for a in (v.aliases or "").split("|") if a.strip()],
            tax_id=v.tax_id or "", country=v.country or "", currency=v.currency or "",
            status=v.status, payment_terms_days=v.payment_terms_days, contact_email=v.contact_email or "",
        ) for v in session.exec(select(Vendor)).all()]
        pos = {p.po_number: PORec(
            po_number=p.po_number, vendor_id=p.vendor_id, po_date=p.po_date, currency=p.currency,
            net_total=round(p.net_total, 2), status=p.status, requester_name=p.requester_name,
            requester_email=p.requester_email, description=p.description,
        ) for p in session.exec(select(PurchaseOrder)).all()}
        for l in session.exec(select(POLine).order_by(POLine.po_number, POLine.line_no)).all():
            if l.po_number in pos:
                pos[l.po_number].lines.append(POLineRec(l.line_no, l.description, l.quantity, l.unit_price, l.line_total))
        ledger = [LedgerRec(
            invoice_number=e.invoice_number, vendor_id=e.vendor_id, invoice_date=e.invoice_date,
            currency=e.currency, net_total=e.net_total, gross_total=e.gross_total, po_number=e.po_number,
            decision=e.decision, file_hash=e.file_hash, processed_at=e.processed_at, source=e.source,
            run_id=e.run_id,
        ) for e in session.exec(select(LedgerEntry)).all()]
        return cls(vendors=vendors, pos=list(pos.values()), ledger=ledger)


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return [{(k or "").strip(): (v if v is not None else "") for k, v in row.items()}
                for row in csv.DictReader(fh)]


def vendor_from_row(r: Dict[str, str]) -> VendorRec:
    return VendorRec(
        vendor_id=r["vendor_id"].strip(), legal_name=r["legal_name"].strip(),
        aliases=[a.strip() for a in (r.get("aliases") or "").split("|") if a.strip()],
        tax_id=(r.get("tax_id") or "").strip(), country=(r.get("country") or "").strip(),
        currency=(r.get("currency") or "").strip().upper(),
        status=(r.get("status") or "approved").strip().lower(),
        payment_terms_days=int(r.get("payment_terms_days") or 30),
        contact_email=(r.get("contact_email") or "").strip(),
    )


def po_from_row(r: Dict[str, str]) -> PORec:
    return PORec(
        po_number=r["po_number"].strip(), vendor_id=r["vendor_id"].strip(),
        po_date=(r.get("po_date") or "").strip(), currency=(r.get("currency") or "").strip().upper(),
        net_total=_money(r.get("net_total")) or 0.0, status=(r.get("status") or "open").strip().lower(),
        requester_name=(r.get("requester_name") or "").strip(),
        requester_email=(r.get("requester_email") or "").strip(),
        description=(r.get("description") or "").strip(),
    )


def po_line_from_row(r: Dict[str, str]) -> POLineRec:
    return POLineRec(
        line_no=int(r["line_no"]), description=r["description"].strip(),
        quantity=float(r["quantity"]), unit_price=_money(r["unit_price"]) or 0.0,
        line_total=_money(r["line_total"]) or 0.0,
    )


def ledger_from_row(r: Dict[str, str]) -> LedgerRec:
    return LedgerRec(
        invoice_number=_opt(r.get("invoice_number")), vendor_id=_opt(r.get("vendor_id")),
        invoice_date=_opt(r.get("invoice_date")), currency=_opt(r.get("currency")),
        net_total=_money(r.get("net_total")), gross_total=_money(r.get("gross_total")),
        po_number=_opt(r.get("po_number")), decision=(r.get("decision") or "APPROVE").strip().upper(),
        file_hash=_opt(r.get("file_hash")), processed_at=(r.get("processed_at") or "").strip(), source="seed",
    )
