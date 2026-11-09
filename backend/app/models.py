"""SQLite tables (SPEC section 7). Dates are ISO strings, money is float rounded to 2 dp."""
from __future__ import annotations

from typing import Optional

from sqlmodel import Field, SQLModel


class Vendor(SQLModel, table=True):
    __tablename__ = "vendors"
    vendor_id: str = Field(primary_key=True)
    legal_name: str
    aliases: str = ""
    tax_id: str = ""
    country: str = ""
    currency: str = ""
    status: str = "approved"
    payment_terms_days: int = 30
    contact_email: str = ""


class PurchaseOrder(SQLModel, table=True):
    __tablename__ = "purchase_orders"
    po_number: str = Field(primary_key=True)
    vendor_id: str = Field(index=True)
    po_date: str = ""
    currency: str = ""
    net_total: float = 0.0
    status: str = "open"
    requester_name: str = ""
    requester_email: str = ""
    description: str = ""


class POLine(SQLModel, table=True):
    __tablename__ = "po_lines"
    id: Optional[int] = Field(default=None, primary_key=True)
    po_number: str = Field(index=True)
    line_no: int
    description: str
    quantity: float
    unit_price: float
    line_total: float


class LedgerEntry(SQLModel, table=True):
    __tablename__ = "ledger"
    id: Optional[int] = Field(default=None, primary_key=True)
    invoice_number: Optional[str] = None
    vendor_id: Optional[str] = Field(default=None, index=True)
    invoice_date: Optional[str] = None
    currency: Optional[str] = None
    net_total: Optional[float] = None
    gross_total: Optional[float] = None
    po_number: Optional[str] = Field(default=None, index=True)
    decision: str = "APPROVE"
    file_hash: Optional[str] = None
    processed_at: str = ""
    source: str = "seed"  # seed | run
    run_id: Optional[str] = None


class Run(SQLModel, table=True):
    __tablename__ = "runs"
    id: str = Field(primary_key=True)
    created_at: str
    filename: str
    sample_id: Optional[str] = None
    file_hash: Optional[str] = None
    file_path: Optional[str] = None
    use_cache: bool = False
    status: str = "queued"  # queued | running | completed | failed
    document_class: Optional[str] = None
    decision: Optional[str] = None
    confidence: Optional[float] = None
    vendor_name: Optional[str] = None
    vendor_id: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    currency: Optional[str] = None
    net_total: Optional[float] = None
    gross_total: Optional[float] = None
    po_number: Optional[str] = None
    duration_ms: Optional[int] = None
    current_stage: Optional[str] = None
    error: Optional[str] = None
    # Reviewer override of a HOLD (brief E). `decision` stays the pipeline's answer.
    override_decision: Optional[str] = None  # APPROVE | REJECT
    override_note: Optional[str] = None
    override_by: Optional[str] = None
    override_at: Optional[str] = None
    override_booking_json: Optional[str] = None


class RunStage(SQLModel, table=True):
    __tablename__ = "run_stages"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    key: str
    index: int
    name: str
    status: str = "pending"
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    summary: str = ""
    warnings_json: str = "[]"
    output_json: str = "null"


class RunEvent(SQLModel, table=True):
    __tablename__ = "run_events"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    seq: int
    type: str
    data_json: str
    ts: str


class ExtractionCache(SQLModel, table=True):
    __tablename__ = "extraction_cache"
    id: Optional[int] = Field(default=None, primary_key=True)
    file_hash: str = Field(index=True)
    model: str
    extraction_json: str
    usage_json: str = "{}"
    created_at: str
