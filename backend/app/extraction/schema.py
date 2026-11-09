"""InvoiceExtraction schema (SPEC 3.1, verbatim). Used as the structured-output format."""
from pydantic import BaseModel, Field
from typing import Optional, List


class Evidence(BaseModel):
    quote: str = Field(description="Verbatim text from the document supporting the value, max 120 chars")
    page: int = Field(description="1-based page number")


class StrField(BaseModel):
    value: Optional[str]
    confidence: float = Field(ge=0, le=1)
    evidence: Optional[Evidence]


class NumField(BaseModel):
    value: Optional[float]
    confidence: float = Field(ge=0, le=1)
    evidence: Optional[Evidence]


class LineItem(BaseModel):
    description: str
    quantity: Optional[float]
    unit_price: Optional[float]
    amount: Optional[float]            # line total as printed
    confidence: float = Field(ge=0, le=1)


class InvoiceExtraction(BaseModel):
    vendor_name: StrField
    vendor_tax_id: StrField
    vendor_address: StrField
    bill_to_name: StrField
    invoice_number: StrField
    invoice_date: StrField              # ISO YYYY-MM-DD or null
    due_date: StrField
    currency: StrField                  # ISO-4217
    po_references: List[str]            # all PO-like references found, verbatim, may be empty
    line_items: List[LineItem]
    subtotal: NumField                  # net of tax
    tax_amount: NumField
    tax_rate_pct: NumField
    total: NumField                     # gross, amount payable
    payment_terms: StrField
    document_notes: str                 # anything odd: handwriting, stamps, missing sections
    overall_confidence: float = Field(ge=0, le=1)
