"""Load data/*.csv into the database (SPEC section 7)."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlmodel import Session, delete, select

from .models import LedgerEntry, POLine, PurchaseOrder, Vendor
from .refdata import ledger_from_row, po_from_row, po_line_from_row, read_csv, vendor_from_row

log = logging.getLogger(__name__)

_PO_FIELDS = ("po_number", "vendor_id", "po_date", "currency", "net_total", "status",
              "requester_name", "requester_email", "description")


def seed_reference(session: Session, data_dir: Path) -> int:
    """Load vendors, POs and PO lines. Returns the number of vendors loaded."""
    data_dir = Path(data_dir)
    vendors = [vendor_from_row(r) for r in read_csv(data_dir / "vendors.csv")]
    for v in vendors:
        session.add(Vendor(vendor_id=v.vendor_id, legal_name=v.legal_name, aliases="|".join(v.aliases),
                           tax_id=v.tax_id, country=v.country, currency=v.currency, status=v.status,
                           payment_terms_days=v.payment_terms_days, contact_email=v.contact_email))
    for p in (po_from_row(r) for r in read_csv(data_dir / "purchase_orders.csv")):
        session.add(PurchaseOrder(**{k: getattr(p, k) for k in _PO_FIELDS}))
    for r in read_csv(data_dir / "po_lines.csv"):
        l = po_line_from_row(r)
        session.add(POLine(po_number=r["po_number"].strip(), line_no=l.line_no, description=l.description,
                           quantity=l.quantity, unit_price=l.unit_price, line_total=l.line_total))
    session.commit()
    return len(vendors)


def reseed_ledger(session: Session, data_dir: Path) -> int:
    """Truncate the ledger and reload ledger_seed.csv. Returns rows loaded."""
    session.exec(delete(LedgerEntry))
    rows = [ledger_from_row(r) for r in read_csv(Path(data_dir) / "ledger_seed.csv")]
    for e in rows:
        session.add(LedgerEntry(invoice_number=e.invoice_number, vendor_id=e.vendor_id,
                                invoice_date=e.invoice_date, currency=e.currency, net_total=e.net_total,
                                gross_total=e.gross_total, po_number=e.po_number, decision=e.decision,
                                file_hash=e.file_hash, processed_at=e.processed_at, source="seed"))
    session.commit()
    return len(rows)


def reseed_reference(session: Session, data_dir: Path) -> int:
    """Drop and reload vendors / POs / PO lines (used after fixtures are regenerated)."""
    session.exec(delete(POLine))
    session.exec(delete(PurchaseOrder))
    session.exec(delete(Vendor))
    session.commit()
    return seed_reference(session, data_dir)


def seed_if_empty(session: Session, data_dir: Path) -> bool:
    """Seed reference data and the ledger when the vendors table is empty."""
    if session.exec(select(Vendor)).first() is not None:
        return False
    n = seed_reference(session, data_dir)
    if n == 0:
        log.warning("No vendors found in %s; reference data not seeded yet", data_dir)
        return False
    reseed_ledger(session, data_dir)
    log.info("Seeded %d vendors and the ledger from %s", n, data_dir)
    return True
