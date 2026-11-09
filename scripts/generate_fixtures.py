#!/usr/bin/env python
"""Generate the synthetic reference data and sample invoice PDFs for PS-1.

Run from the repo root:

    python scripts/generate_fixtures.py              # regenerate everything, then verify
    python scripts/generate_fixtures.py --verify     # verify existing files only
    python scripts/generate_fixtures.py --preview DIR  # also render every PDF to PNG in DIR

Outputs (all under data/):
    vendors.csv, purchase_orders.csv, po_lines.csv, ledger_seed.csv   (SPEC 2.1-2.4)
    samples/*.pdf                                                     (SPEC 2.6, eight files)
    samples.json                                                      (SPEC 2.5)

Determinism: reportlab runs in invariant mode (fixed dates and document ids), the scan
noise for EC1 comes from a seeded RNG, and nothing reads the wall clock. Two runs with the
same library versions (scripts/requirements.txt) produce byte-identical files.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import random
import statistics
import sys
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Callable, Optional

from reportlab import rl_config

rl_config.invariant = 1  # fixed CreationDate / ModDate / document ID -> byte-identical output

import pymupdf as fitz
from PIL import Image, ImageChops, ImageDraw, ImageFilter
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle

SEED = 20261101
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SAMPLES_DIR = DATA / "samples"
CENT = Decimal("0.01")
REFERENCE_TODAY = dt.date(2026, 11, 8)  # demo/interview week; only used by --verify's R9 check

pdfmetrics.registerFont(TTFont("Vera", "Vera.ttf"))
pdfmetrics.registerFont(TTFont("Vera-Bold", "VeraBd.ttf"))
pdfmetrics.registerFont(TTFont("Vera-Italic", "VeraIt.ttf"))


def D(x) -> Decimal:
    return Decimal(str(x))


def q2(x) -> Decimal:
    return D(x).quantize(CENT, rounding=ROUND_HALF_UP)


def m(x) -> str:
    """CSV money: two-decimal string, no separators."""
    return f"{q2(x):.2f}"


def qty_str(x) -> str:
    x = D(x)
    return str(int(x)) if x == x.to_integral_value() else f"{x.normalize()}"


def fmt(x, style: str = "en") -> str:
    """Printed money: 1,250.00 (en) or 1.250,00 (de)."""
    s = f"{q2(x):,.2f}"
    if style == "de":
        s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return s


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


# --------------------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------------------

VENDORS = [
    dict(vendor_id="V001", legal_name="Northwind Office Supplies Ltd", aliases="Northwind Office Supplies",
         tax_id="GB123456789", country="GB", currency="GBP", status="approved", payment_terms_days=30,
         contact_email="accounts@northwind-office.example.com"),
    dict(vendor_id="V002", legal_name="Apex Industrial Components Pvt Ltd", aliases="Apex Industrial",
         tax_id="27AAACA1234A1Z5", country="IN", currency="INR", status="approved", payment_terms_days=45,
         contact_email="receivables@apex-industrial.example.com"),
    dict(vendor_id="V003", legal_name="Meridian Cloud Services Inc", aliases="Meridian Cloud",
         tax_id="12-3456789", country="US", currency="USD", status="approved", payment_terms_days=30,
         contact_email="billing@meridiancloud.example.com"),
    dict(vendor_id="V004", legal_name="Helios Facility Management GmbH", aliases="Helios FM",
         tax_id="DE123456789", country="DE", currency="EUR", status="approved", payment_terms_days=14,
         contact_email="rechnung@helios-fm.example.com"),
    dict(vendor_id="V005", legal_name="Bluegrass Logistics LLC", aliases="",
         tax_id="98-7654321", country="US", currency="USD", status="suspended", payment_terms_days=30,
         contact_email="ar@bluegrass-logistics.example.com"),
    dict(vendor_id="V006", legal_name="Quantum Lab Supplies BV", aliases="Quantum Lab",
         tax_id="NL123456789B01", country="NL", currency="EUR", status="approved", payment_terms_days=30,
         contact_email="invoices@quantumlab.example.com"),
]
VENDOR = {v["vendor_id"]: v for v in VENDORS}

# Requesters at the (single) customer, Zamp Demo Customer Ltd.
REQ = {
    "priya": ("Priya Nair", "priya.nair@example.com"),
    "tom": ("Tom Hughes", "tom.hughes@example.com"),
    "lena": ("Lena Fischer", "lena.fischer@example.com"),
    "daniel": ("Daniel Kim", "daniel.kim@example.com"),
    "sanne": ("Sanne de Vries", "sanne.devries@example.com"),
    "marcus": ("Marcus Reed", "marcus.reed@example.com"),
}

# (po_number, vendor_id, po_date, status, requester, description, [(desc, qty, unit), ...])
SCENARIO_POS = [
    ("PO-2026-0102", "V002", "2026-09-10", "open", "priya",
     "Flanges and fasteners for Bengaluru plant line 2",
     [("Stainless steel flange DN50", 200, "450.00"), ("Hex bolt M12 (box of 100)", 50, "1200.00")]),
    ("PO-2026-0103", "V001", "2026-10-06", "open", "tom",
     "Ergonomic seating and desk lighting, London office 3rd floor",
     [("Ergonomic chair model K2", 5, "180.00"), ("Desk lamp LED", 10, "35.00")]),
    ("PO-2026-0105", "V004", "2026-08-20", "open", "lena",
     "Office cleaning, Munich branch, Sep-Nov 2026 (3 months)",
     [("Facility cleaning services – monthly", 3, "4000.00")]),
    ("PO-2026-0106", "V003", "2026-08-25", "open", "daniel",
     "Managed backup service, September 2026",
     [("Managed backup service – Sep 2026", 1, "2400.00")]),
    ("PO-2026-0107", "V003", "2026-09-28", "open", "daniel",
     "Cloud hosting and object storage, October 2026",
     [("Cloud hosting – Oct 2026", 1, "3200.00"), ("Object storage 10TB", 1, "1600.00")]),
    ("PO-2026-0109", "V006", "2026-10-12", "open", "sanne",
     "Lab consumables restock, Amsterdam lab",
     [("Nitrile gloves (box of 100)", 150, "9.00"), ("Pipette tips 1000µl (rack)", 60, "30.00")]),
]

FILLER_POS = [
    ("PO-2026-0101", "V001", "2026-08-17", "closed", "tom",
     "Copier paper and toner, Q3 restock",
     [("A4 copier paper 80gsm (box of 5 reams)", 40, "21.50"), ("Toner cartridge black, high yield", 6, "89.00")]),
    ("PO-2026-0104", "V002", "2026-08-18", "closed", "priya",
     "Machined brackets and washers for plant line 1",
     [("Aluminium bracket AB-40 (machined)", 500, "85.00"), ("Zinc-plated washer M10 (pack of 500)", 20, "640.00")]),
    ("PO-2026-0108", "V005", "2026-08-19", "closed", "marcus",
     "Freight Newark to Columbus, August consolidation",
     [("LTL freight – 6 pallets", 1, "1850.00"), ("Liftgate delivery", 1, "150.00")]),
    ("PO-2026-0110", "V006", "2026-08-27", "closed", "sanne",
     "Centrifuge tubes and lab wipes",
     [("Centrifuge tubes 50ml (pack of 500)", 8, "74.00"), ("Lab wipes (box of 280)", 40, "6.50")]),
    ("PO-2026-0111", "V003", "2026-09-24", "open", "daniel",
     "Managed security monitoring, Q4 2026",
     [("Managed SIEM monitoring – monthly", 3, "950.00")]),
    ("PO-2026-0112", "V004", "2026-08-21", "closed", "lena",
     "HVAC preventive maintenance, Munich branch",
     [("HVAC preventive maintenance visit", 2, "1450.00"), ("Filter replacement set", 4, "125.00")]),
    ("PO-2026-0113", "V001", "2026-09-30", "open", "tom",
     "Meeting room furniture, London office",
     [("Conference table 2.4m oak veneer", 1, "1150.00"), ("Stacking chair grey", 12, "64.00")]),
]

# Ledger rows: (invoice_number, vendor_id, invoice_date, net, gross, po, decision, hash_source, processed_at)
# hash_source "original:<key>" -> sha256 of the original PDF rendered in memory by this script.
SCENARIO_LEDGER = [
    ("HFM-2026-091", "V004", "2026-10-05", "4000.00", "4760.00", "PO-2026-0105", "APPROVE",
     "original:HFM-2026-091", "2026-10-06T14:05:00Z"),
    ("MCS-10398", "V003", "2026-10-01", "2400.00", "2400.00", "PO-2026-0106", "APPROVE",
     "original:MCS-10398", "2026-10-02T09:41:00Z"),
]
FILLER_LEDGER = [
    ("NW-7655", "V001", "2026-08-28", "1394.00", "1672.80", "PO-2026-0101", "APPROVE", "", "2026-08-29T10:12:00Z"),
    ("AIC/26-27/0544", "V002", "2026-09-12", "55300.00", "65254.00", "PO-2026-0104", "APPROVE", "", "2026-09-15T06:48:00Z"),
    ("BGL-55102", "V005", "2026-08-30", "2000.00", "2000.00", "PO-2026-0108", "APPROVE", "", "2026-09-01T15:30:00Z"),
    ("BGL-55187", "V005", "2026-09-21", "420.00", "420.00", "PO-2026-0108", "HOLD", "", "2026-09-22T11:02:00Z"),
    ("HFM-2026-077", "V004", "2026-09-08", "3400.00", "4046.00", "PO-2026-0112", "APPROVE", "", "2026-09-09T08:20:00Z"),
    ("QLS-26-1187", "V006", "2026-09-22", "852.00", "1030.92", "PO-2026-0110", "APPROVE", "", "2026-09-23T13:44:00Z"),
    ("NW-7702", "V001", "2026-10-09", "1150.00", "1380.00", "PO-2026-0113", "APPROVE", "", "2026-10-10T09:05:00Z"),
    ("MCS-10411", "V003", "2026-10-16", "950.00", "950.00", "PO-2026-0111", "APPROVE", "", "2026-10-17T16:27:00Z"),
]

# --------------------------------------------------------------------------------------
# SPEC 2.6, typed in independently so --verify is not circular.
# --------------------------------------------------------------------------------------

SPEC_VENDORS = {
    "V001": ("Northwind Office Supplies Ltd", "GB", "GBP", "GB123456789", "approved", "Northwind Office Supplies"),
    "V002": ("Apex Industrial Components Pvt Ltd", "IN", "INR", "27AAACA1234A1Z5", "approved", "Apex Industrial"),
    "V003": ("Meridian Cloud Services Inc", "US", "USD", "12-3456789", "approved", "Meridian Cloud"),
    "V004": ("Helios Facility Management GmbH", "DE", "EUR", "DE123456789", "approved", "Helios FM"),
    "V005": ("Bluegrass Logistics LLC", "US", "USD", "98-7654321", "suspended", ""),
    "V006": ("Quantum Lab Supplies BV", "NL", "EUR", "NL123456789B01", "approved", "Quantum Lab"),
}
SPEC_POS = {
    "PO-2026-0102": ("V002", "INR", "150000.00", "open",
                     [("Stainless steel flange DN50", "200", "450.00"), ("Hex bolt M12 (box of 100)", "50", "1200.00")]),
    "PO-2026-0103": ("V001", "GBP", "1250.00", "open",
                     [("Ergonomic chair model K2", "5", "180.00"), ("Desk lamp LED", "10", "35.00")]),
    "PO-2026-0105": ("V004", "EUR", "12000.00", "open", [("Facility cleaning services – monthly", "3", "4000.00")]),
    "PO-2026-0106": ("V003", "USD", "2400.00", "open", [("Managed backup service – Sep 2026", "1", "2400.00")]),
    "PO-2026-0107": ("V003", "USD", "4800.00", "open",
                     [("Cloud hosting – Oct 2026", "1", "3200.00"), ("Object storage 10TB", "1", "1600.00")]),
    "PO-2026-0109": ("V006", "EUR", "3150.00", "open",
                     [("Nitrile gloves (box of 100)", "150", "9.00"), ("Pipette tips 1000µl (rack)", "60", "30.00")]),
}
SPEC_LEDGER = {
    "HFM-2026-091": ("V004", "2026-10-05", "4000.00", "4760.00", "PO-2026-0105", "APPROVE"),
    "MCS-10398": ("V003", "2026-10-01", "2400.00", "2400.00", "PO-2026-0106", "APPROVE"),
}
# id: (file, vendor_id, invoice_no, date, po_ref, net, tax_rate_pct, tax, total, expected_decision)
SPEC_SAMPLES = {
    "HP": ("HP_meridian_MCS-10422.pdf", "V003", "MCS-10422", "2026-10-31", "PO-2026-0107",
           "4800.00", "0", "0.00", "4800.00", "APPROVE"),
    "EC1": ("EC1_scanned_northwind_NW-7781.pdf", "V001", "NW-7781", "2026-10-27", "PO-2026-0103",
            "1250.00", "20", "250.00", "1500.00", "APPROVE"),
    "EC2a": ("EC2a_split_helios_HFM-2026-104.pdf", "V004", "HFM-2026-104", "2026-10-30", "PO-2026-0105",
             "4000.00", "19", "760.00", "4760.00", "APPROVE"),
    "EC2b": ("EC2b_split_helios_HFM-2026-118.pdf", "V004", "HFM-2026-118", "2026-10-31", "PO-2026-0105",
             "8000.00", "19", "1520.00", "9520.00", "HOLD"),
    "EC3": ("EC3_variance_apex_AIC-26-27-0931.pdf", "V002", "AIC/26-27/0931", "2026-10-29", "PO-2026-0102",
            "157200.00", "18", "28296.00", "185496.00", "HOLD"),
    "EC4": ("EC4_duplicate_meridian_MCS-10398_resent.pdf", "V003", "MCS-10398", "2026-10-01", "PO-2026-0106",
            "2400.00", "0", "0.00", "2400.00", "REJECT"),
    "EC5": ("EC5_missing_quantum_no-number.pdf", "V006", None, "2026-10-30", None,
            "3150.00", "21", "661.50", "3811.50", "HOLD"),
    "EC6": ("EC6_unknown_silverline_SCP-0042.pdf", None, "SCP-0042", "2026-10-28", "PO-2026-0199",
            "2500.00", "0", "0.00", "2500.00", "REJECT"),
}

# --------------------------------------------------------------------------------------
# Invoice model
# --------------------------------------------------------------------------------------


@dataclass
class Line:
    description: str
    qty: Decimal
    unit_price: Decimal
    code: str = ""  # SKU / HSN code, printed in its own column where the template has one
    uom: str = ""

    @property
    def amount(self) -> Decimal:
        return q2(self.qty * self.unit_price)


@dataclass
class Invoice:
    key: str
    vendor_id: Optional[str]  # None for the unknown vendor
    invoice_no: Optional[str]
    date: dt.date
    terms_days: int
    currency: str
    po_ref: Optional[str]
    lines: list
    tax_rate: Decimal  # percent
    extra: dict = field(default_factory=dict)

    @property
    def net(self) -> Decimal:
        return q2(sum((ln.amount for ln in self.lines), Decimal("0")))

    @property
    def tax(self) -> Decimal:
        return q2(self.net * self.tax_rate / Decimal(100))

    @property
    def total(self) -> Decimal:
        return q2(self.net + self.tax)

    @property
    def due(self) -> dt.date:
        return self.date + dt.timedelta(days=self.terms_days)


def L(desc, qty, unit, code="", uom="") -> Line:
    return Line(desc, D(qty), D(unit), code, uom)


# --- vendor print profiles (addresses, banks: all fictional) ---------------------------

PROFILE = {
    "V001": dict(
        addr=["Unit 4, Riverside Trade Park", "Kingsway, Manchester M19 2LN", "United Kingdom"],
        phone="+44 161 496 0732", email="accounts@northwind-office.example.com",
        web="www.northwind-office.example.com", tax_print="GB 123 4567 89", company_no="08123456",
        bank=["Northern Counties Bank plc", "Sort code 20-45-77", "Account 43218765",
              "IBAN GB29 NWBK 6016 1331 9268 19"]),
    "V002": dict(
        addr=["Plot No. 47, MIDC Industrial Area, Bhosari", "Pune 411026, Maharashtra, India"],
        phone="+91 20 2712 4400", email="receivables@apex-industrial.example.com", pan="AAACA1234A",
        bank=dict(name="Deccan Commercial Bank Ltd", acct="50200012345678", ifsc="DCBK0000417", branch="Bhosari")),
    "V003": dict(
        addr=["2201 Westlake Avenue, Suite 900", "Seattle, WA 98121, USA"],
        phone="+1 (206) 555-0148", email="billing@meridiancloud.example.com", web="meridiancloud.example.com",
        bank=["Cascade Pacific Bank, N.A.", "ACH routing 999000123", "Account 7700112233", "SWIFT CPBKUS6S"]),
    "V004": dict(
        addr=["Leopoldstraße 112", "80802 München", "Deutschland"],
        phone="+49 89 1234 5670", email="rechnung@helios-fm.example.com", web="www.helios-fm.example.com",
        md="Markus Brandt", hrb="HRB 234567", court="Amtsgericht München",
        bank=["Isar Handelsbank AG", "IBAN DE89 3704 0044 0532 0130 00", "BIC ISHADEMMXXX"]),
    "V006": dict(
        addr=["Science Park 402", "1098 XH Amsterdam", "The Netherlands"],
        phone="+31 20 555 0193", email="invoices@quantumlab.example.com", web="quantumlab.example.com",
        kvk="81234567",
        bank=["Amstel Handelsbank N.V.", "IBAN NL91 ABNA 0417 1643 00", "BIC ABNANL2A"]),
    "SILVERLINE": dict(
        name="Silverline Consulting Partners",
        addr=["1100 Congress Avenue, Suite 400", "Austin, TX 78701"],
        phone="(512) 555-0176", email="billing@silverline-partners.example.com", ein="45-6789012",
        bank=["Lone Star Commerce Bank", "Routing 999000456", "Account 3301987654"]),
}

CUSTOMER = "Zamp Demo Customer Ltd"
BILL_TO = {
    "GB": [CUSTOMER, "Accounts Payable", "3rd Floor, 20 Eastcheap Row", "London EC3M 1AB", "United Kingdom"],
    "IN": [CUSTOMER + " (India Branch)", "3rd Floor, Orion Tech Park, Outer Ring Road",
           "Bengaluru 560103, Karnataka, India"],
    "US": [CUSTOMER, "Attn: Accounts Payable", "350 Fifth Avenue, Floor 21", "New York, NY 10118"],
    "DE": [CUSTOMER, "Zweigniederlassung München", "z. Hd. Kreditorenbuchhaltung", "Sonnenstraße 19",
           "80331 München"],
    "NL": [CUSTOMER, "Attn. Accounts Payable", "Herengracht 450", "1017 CA Amsterdam", "The Netherlands"],
}

# --- the eight samples, plus the two "original" ledger invoices --------------------------

INVOICES = {
    "HP": Invoice("HP", "V003", "MCS-10422", d("2026-10-31"), 30, "USD", "PO-2026-0107",
                  [L("Cloud hosting – Oct 2026", 1, "3200.00"), L("Object storage 10TB", 1, "1600.00")],
                  D(0)),
    "EC1": Invoice("EC1", "V001", "NW-7781", d("2026-10-27"), 30, "GBP", "PO-2026-0103",
                   [L("Ergonomic chair model K2", 5, "180.00", code="ERG-K2"),
                    L("Desk lamp LED", 10, "35.00", code="LMP-LED")],
                   D(20), extra=dict(delivered="22/10/2026")),
    "EC2a": Invoice("EC2a", "V004", "HFM-2026-104", d("2026-10-30"), 14, "EUR", "PO-2026-0105",
                    [L("Facility cleaning services – October", 1, "4000.00")],
                    D(19), extra=dict(period="01.10.2026 – 31.10.2026")),
    "EC2b": Invoice("EC2b", "V004", "HFM-2026-118", d("2026-10-31"), 14, "EUR", "PO-2026-0105",
                    [L("Facility cleaning services – Nov + Dec", 2, "4000.00")],
                    D(19), extra=dict(period="01.11.2026 – 31.12.2026")),
    "EC3": Invoice("EC3", "V002", "AIC/26-27/0931", d("2026-10-29"), 45, "INR", "PO-2026-0102",
                   [L("Stainless steel flange DN50", 200, "486.00", code="7307", uom="Nos"),
                    L("Hex bolt M12 (box of 100)", 50, "1200.00", code="7318", uom="Box")],
                   D(18), extra=dict(po_date="10-Sep-2026", delivery_note="DN/26-27/1147",
                                     dispatch_doc="LR 558120", carrier="Road – Deccan Freight Carriers")),
    "EC4": Invoice("EC4", "V003", "MCS-10398", d("2026-10-01"), 30, "USD", "PO-2026-0106",
                   [L("Managed backup service – Sep 2026", 1, "2400.00")], D(0)),
    "EC5": Invoice("EC5", "V006", None, d("2026-10-30"), 30, "EUR", None,
                   [L("Nitrile gloves (box of 100)", 150, "9.00"), L("Pipette tips 1000µl (rack)", 60, "30.00")],
                   D(21)),
    "EC6": Invoice("EC6", None, "SCP-0042", d("2026-10-28"), 15, "USD", "PO-2026-0199",
                   [L("Strategy workshop facilitation – ref. PO-2026-0199", 1, "2500.00")], D(0)),
}

ORIGINALS = {  # ledger-seed invoices, rendered in their vendor's usual template only to hash them
    "MCS-10398": Invoice("orig-MCS-10398", "V003", "MCS-10398", d("2026-10-01"), 30, "USD", "PO-2026-0106",
                         [L("Managed backup service – Sep 2026", 1, "2400.00")], D(0)),
    "HFM-2026-091": Invoice("orig-HFM-2026-091", "V004", "HFM-2026-091", d("2026-10-05"), 14, "EUR",
                            "PO-2026-0105", [L("Facility cleaning services – September", 1, "4000.00")],
                            D(19), extra=dict(period="01.09.2026 – 30.09.2026")),
}

# --------------------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------------------


def ps(font="Helvetica", size=9, leading=None, color=colors.black, align=TA_LEFT, **kw) -> ParagraphStyle:
    return ParagraphStyle("p", fontName=font, fontSize=size, leading=leading or size * 1.25,
                          textColor=color, alignment=align, **kw)


def P(text, style) -> Paragraph:
    return Paragraph(text, style)


def place(c, flowable, x, y_top, avail_w, avail_h=2000) -> float:
    _, h = flowable.wrapOn(c, avail_w, avail_h)
    flowable.drawOn(c, x, y_top - h)
    return h


def new_canvas(buf, pagesize, title, author, creator):
    c = canvas.Canvas(buf, pagesize=pagesize, invariant=1, pageCompression=1)
    c.setTitle(title)
    c.setAuthor(author)
    c.setCreator(creator)
    c.setSubject("Invoice")
    return c


def lines_at(c, x, y, lines, font="Helvetica", size=9, leading=None, color=colors.black, right=False):
    leading = leading or size * 1.3
    c.setFont(font, size)
    c.setFillColor(color)
    for i, t in enumerate(lines):
        (c.drawRightString if right else c.drawString)(x, y - i * leading, t)
    return y - len(lines) * leading


def us_date(x: dt.date) -> str:
    return x.strftime("%B ") + str(x.day) + x.strftime(", %Y")


def us_date_short(x: dt.date) -> str:
    return x.strftime("%b ") + str(x.day) + x.strftime(", %Y")


# --------------------------------------------------------------------------------------
# Template 1 - Northwind (GB): tax-inclusive layout
# --------------------------------------------------------------------------------------


def render_northwind(inv: Invoice) -> bytes:
    v, p = VENDOR["V001"], PROFILE["V001"]
    teal, grey = colors.HexColor("#1f5f5b"), colors.HexColor("#5f6b6a")
    W, H = A4
    buf = io.BytesIO()
    c = new_canvas(buf, A4, f"VAT Invoice {inv.invoice_no}", v["legal_name"], "Northwind Billing 3.2")
    x0, x1 = 42, W - 42

    c.setFillColor(teal)
    c.rect(0, H - 14, W, 14, stroke=0, fill=1)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(x0, H - 56, v["legal_name"])
    y = lines_at(c, x0, H - 72, p["addr"] + [f"Tel {p['phone']}  ·  {p['email']}",
                                             f"VAT Reg. No. {p['tax_print']}"], size=8.5, color=grey)
    c.setFillColor(teal)
    c.setFont("Helvetica-Bold", 22)
    c.drawRightString(x1, H - 58, "VAT INVOICE")

    meta = [["Invoice no.", inv.invoice_no], ["Invoice date", inv.date.strftime("%d/%m/%Y")],
            ["Due date", inv.due.strftime("%d/%m/%Y")], ["Payment terms", f"{inv.terms_days} days net"],
            ["Your PO", inv.po_ref]]
    t = Table(meta, colWidths=[78, 92])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (0, -1), "Helvetica", 8.5), ("FONT", (1, 0), (1, -1), "Helvetica-Bold", 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), grey), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#c9d3d2")),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    place(c, t, x1 - 170, H - 76, 170)

    yb = H - 190
    c.setFillColor(teal)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x0, yb, "INVOICE TO")
    lines_at(c, x0, yb - 14, BILL_TO["GB"], size=9.5, leading=12.5)
    c.setFillColor(teal)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(300, yb, "DELIVER TO")
    lines_at(c, 300, yb - 14, [CUSTOMER, "Reception, 3rd Floor", "20 Eastcheap Row", "London EC3M 1AB"],
             size=9.5, leading=12.5)

    cell = ps("Helvetica", 9)
    hdr = ps("Helvetica-Bold", 8, color=colors.white)
    hdr_r = ps("Helvetica-Bold", 8, color=colors.white, align=TA_RIGHT)
    rows = [[P("Code", hdr), P("Description", hdr), P("Qty", hdr_r), P("Unit price (net)", hdr_r),
             P("VAT", hdr_r), P("Net amount", hdr_r)]]
    for ln in inv.lines:
        rows.append([ln.code, P(ln.description, cell), qty_str(ln.qty), fmt(ln.unit_price),
                     f"{inv.tax_rate:.0f}%", fmt(ln.amount)])
    t = Table(rows, colWidths=[62, 205, 40, 84, 38, 82])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), teal), ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#c9d3d2")),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    y = H - 300
    y -= place(c, t, x0, y, x1 - x0)

    # Totals: net and VAT small, gross big.
    y -= 18
    c.setFont("Helvetica", 7.5)
    c.setFillColor(grey)
    c.drawString(x1 - 200, y, "Subtotal (net)")
    c.drawRightString(x1 - 8, y, f"£{fmt(inv.net)}")
    c.drawString(x1 - 200, y - 11, f"VAT @ {inv.tax_rate:.0f}%")
    c.drawRightString(x1 - 8, y - 11, f"£{fmt(inv.tax)}")
    by = y - 64
    c.setFillColor(teal)
    c.roundRect(x1 - 210, by, 210, 42, 4, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x1 - 200, by + 16, "Total incl. VAT")
    c.setFont("Helvetica-Bold", 19)
    c.drawRightString(x1 - 10, by + 14, f"£{fmt(inv.total)}")

    note = ps("Helvetica", 8.5, color=grey, leading=11.5)
    place(c, P(f"Goods delivered {inv.extra['delivered']} to your London office.<br/>"
               "Unit prices are shown excluding VAT. The amount payable is the total including VAT.<br/>"
               f"Please quote <b>{inv.invoice_no}</b> as the reference with your payment.", note),
          x0, y + 4, 250)

    # Footer
    fy = 92
    c.setStrokeColor(teal)
    c.setLineWidth(0.8)
    c.line(x0, fy, x1, fy)
    c.setFillColor(teal)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x0, fy - 14, "Bank details")
    lines_at(c, x0, fy - 26, [p["bank"][0], f"{p['bank'][1]}  ·  {p['bank'][2]}", p["bank"][3]],
             size=8, leading=10.5, color=grey)
    c.setFillColor(teal)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(310, fy - 14, "Company")
    lines_at(c, 310, fy - 26, [f"Registered in England & Wales No. {p['company_no']}",
                               f"VAT Reg. No. {p['tax_print']}", p["web"]], size=8, leading=10.5, color=grey)
    c.setFillColor(teal)
    c.setFont("Helvetica-Oblique", 9)
    c.drawCentredString(W / 2, 30, "Thank you for your custom!")
    c.showPage()
    c.save()
    return buf.getvalue()


# --------------------------------------------------------------------------------------
# Template 2 - Apex (IN): table-heavy GST tax invoice
# --------------------------------------------------------------------------------------

ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
        "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n):
    return ONES[n] if n < 20 else TENS[n // 10] + (" " + ONES[n % 10] if n % 10 else "")


def _three(n):
    parts = []
    if n // 100:
        parts.append(ONES[n // 100] + " Hundred")
    if n % 100:
        parts.append(_two(n % 100))
    return " ".join(parts)


def indian_words(amount: Decimal) -> str:
    n = int(amount)
    paise = int((q2(amount) - n) * 100)
    crore, n = divmod(n, 10 ** 7)
    lakh, n = divmod(n, 10 ** 5)
    thousand, n = divmod(n, 1000)
    parts = []
    if crore:
        parts.append(_three(crore) + " Crore")
    if lakh:
        parts.append(_two(lakh) + " Lakh")
    if thousand:
        parts.append(_two(thousand) + " Thousand")
    if n:
        parts.append(_three(n))
    s = "INR " + " ".join(parts)
    if paise:
        s += " and " + _two(paise) + " Paise"
    return s + " Only"


def render_apex(inv: Invoice) -> bytes:
    v, p = VENDOR["V002"], PROFILE["V002"]
    W, H = A4
    buf = io.BytesIO()
    c = new_canvas(buf, A4, f"Tax Invoice {inv.invoice_no}", v["legal_name"], "Apex ERP - GST Invoicing")
    x0, width = 36, W - 72
    F, FB = "Times-Roman", "Times-Bold"
    s = ps(F, 8.5, leading=10.5)
    sb = ps(FB, 8.5, leading=10.5)
    lab = ps(F, 7, leading=8.5, color=colors.HexColor("#444444"))
    val = ps(FB, 8.5, leading=10)
    grid = ("GRID", (0, 0), (-1, -1), 0.6, colors.black)

    c.setFont(FB, 13)
    c.drawCentredString(W / 2, H - 40, "TAX INVOICE")
    c.setFont(F, 7.5)
    c.drawRightString(x0 + width, H - 40, "(ORIGINAL FOR RECIPIENT)")
    y = H - 48

    def meta(pairs):
        rows = []
        for (la, va), (lb, vb) in zip(pairs[0::2], pairs[1::2]):
            rows.append([[P(la, lab), P(va, val)], [P(lb, lab), P(vb, val)]])
        t = Table(rows, colWidths=[width / 4] * 2)
        t.setStyle(TableStyle([("INNERGRID", (0, 0), (-1, -1), 0.6, colors.black),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        return t

    seller = P(f"<font name='{FB}' size='10.5'>{v['legal_name']}</font><br/>" + "<br/>".join(p["addr"]) +
               f"<br/>GSTIN/UIN: <b>{v['tax_id']}</b><br/>State Name: Maharashtra, Code: 27"
               f"<br/>PAN: {p['pan']}<br/>Tel: {p['phone']}<br/>E-Mail: {p['email']}", s)
    buyer = P("<font size='7' color='#444444'>Buyer (Bill to)</font><br/>"
              f"<b>{BILL_TO['IN'][0]}</b><br/>" + "<br/>".join(BILL_TO["IN"][1:]) +
              "<br/>GSTIN/UIN: 29AABCZ9876K1Z3<br/>State Name: Karnataka, Code: 29<br/>Place of Supply: Karnataka", s)
    meta1 = meta([("Invoice No.", inv.invoice_no), ("Dated", inv.date.strftime("%d-%b-%Y")),
                  ("Delivery Note", inv.extra["delivery_note"]), ("Mode/Terms of Payment", f"{inv.terms_days} Days"),
                  ("Buyer's Order No.", inv.po_ref), ("Dated", inv.extra["po_date"])])
    meta2 = meta([("Dispatch Doc No.", inv.extra["dispatch_doc"]), ("Dispatched through", inv.extra["carrier"]),
                  ("Destination", "Bengaluru"), ("Terms of Delivery", "Door delivery, freight paid"),
                  ("Due Date", inv.due.strftime("%d-%b-%Y")), ("Reverse Charge", "No")])
    t = Table([[seller, meta1], [buyer, meta2]], colWidths=[width / 2] * 2)
    t.setStyle(TableStyle([grid, ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (1, 0), (1, -1), 0), ("RIGHTPADDING", (1, 0), (1, -1), 0),
                           ("TOPPADDING", (1, 0), (1, -1), 0), ("BOTTOMPADDING", (1, 0), (1, -1), 0),
                           ("TOPPADDING", (0, 0), (0, -1), 4), ("BOTTOMPADDING", (0, 0), (0, -1), 5)]))
    y -= place(c, t, x0, y, width)

    hc = ps(FB, 8, leading=9.5, align=TA_CENTER)
    rows = [[P(h, hc) for h in ["Sl<br/>No.", "Description of Goods", "HSN/SAC", "Quantity", "Rate", "per", "Amount"]]]
    for i, ln in enumerate(inv.lines, 1):
        rows.append([str(i), P(f"<b>{ln.description}</b>", s), ln.code, f"{qty_str(ln.qty)} {ln.uom}",
                     fmt(ln.unit_price), ln.uom, fmt(ln.amount)])
    spacer_idx = len(rows)
    rows.append(["", "", "", "", "", "", ""])
    rows.append(["", P("<b>Taxable Value</b>", ps(F, 8.5, align=TA_RIGHT)), "", "", "", "", fmt(inv.net)])
    rows.append(["", P(f"<b>IGST @ {inv.tax_rate:.0f}%</b>", ps(F, 8.5, align=TA_RIGHT)), "", "",
                 f"{inv.tax_rate:.0f} %", "", fmt(inv.tax)])
    rows.append(["", P("<b>Total</b>", ps(FB, 9.5, align=TA_RIGHT)), "", "", "", "", f"INR {fmt(inv.total)}"])
    n = len(rows)
    t = Table(rows, colWidths=[26, 206, 50, 58, 60, 32, 91],
              rowHeights=[None] * spacer_idx + [150, None, None, None])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, colors.black), ("INNERGRID", (0, 0), (-1, 0), 0.6, colors.black),
        ("LINEAFTER", (0, 0), (-2, -1), 0.6, colors.black),
        ("LINEABOVE", (0, n - 1), (-1, n - 1), 0.6, colors.black),
        ("FONT", (0, 1), (-1, -1), F, 8.5), ("FONT", (6, n - 1), (6, n - 1), FB, 9.5),
        ("FONT", (6, 1), (6, spacer_idx - 1), FB, 8.5),
        ("ALIGN", (0, 1), (0, -1), "CENTER"), ("ALIGN", (2, 1), (2, -1), "CENTER"),
        ("ALIGN", (3, 1), (4, -1), "RIGHT"), ("ALIGN", (5, 1), (5, -1), "CENTER"),
        ("ALIGN", (6, 1), (6, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    y -= place(c, t, x0, y, width)

    words = Table([[P(f"Amount Chargeable (in words)<br/><b>{indian_words(inv.total)}</b>", s),
                    P("E. &amp; O.E", ps(F, 8, align=TA_RIGHT))]], colWidths=[width - 60, 60])
    words.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    y -= place(c, words, x0, y, width)

    hsn_rows = [[P(h, hc) for h in ["HSN/SAC", "Taxable Value", "IGST Rate", "IGST Amount", "Total Tax Amount"]]]
    for ln in inv.lines:
        tax = q2(ln.amount * inv.tax_rate / 100)
        hsn_rows.append([ln.code, fmt(ln.amount), f"{inv.tax_rate:.0f}%", fmt(tax), fmt(tax)])
    hsn_rows.append(["Total", fmt(inv.net), "", fmt(inv.tax), fmt(inv.tax)])
    t = Table(hsn_rows, colWidths=[143, 110, 70, 100, 100])
    t.setStyle(TableStyle([grid, ("FONT", (0, 1), (-1, -1), F, 8.5), ("FONT", (0, -1), (-1, -1), FB, 8.5),
                           ("ALIGN", (1, 1), (-1, -1), "RIGHT"), ("ALIGN", (0, 1), (0, -1), "CENTER"),
                           ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
    y -= place(c, t, x0, y, width)

    tw = Table([[P(f"Tax Amount (in words): <b>{indian_words(inv.tax)}</b>", s)]], colWidths=[width])
    tw.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.black)]))
    y -= place(c, tw, x0, y, width)

    b = p["bank"]
    left = P("<b>Company's Bank Details</b><br/>"
             f"Bank Name: {b['name']}<br/>A/c No.: {b['acct']}<br/>Branch &amp; IFS Code: {b['branch']} &amp; {b['ifsc']}"
             "<br/><br/><u>Declaration</u><br/>We declare that this invoice shows the actual price of the goods "
             "described and that all particulars are true and correct.", s)
    right = P(f"<para align='right'><b>for {v['legal_name']}</b><br/><br/><br/><br/><br/>Authorised Signatory</para>", s)
    t = Table([[left, right]], colWidths=[width * 0.58, width * 0.42])
    t.setStyle(TableStyle([grid, ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    y -= place(c, t, x0, y, width)

    c.setFont(F, 8)
    c.drawCentredString(W / 2, y - 14, "SUBJECT TO PUNE JURISDICTION")
    c.drawCentredString(W / 2, y - 25, "This is a Computer Generated Invoice")
    c.setFont("Times-Italic", 9)
    c.drawCentredString(W / 2, y - 40, "Thank you for your business.")
    c.showPage()
    c.save()
    return buf.getvalue()


# --------------------------------------------------------------------------------------
# Template 3 - Meridian (US): logo block
# --------------------------------------------------------------------------------------


def draw_meridian_logo(c, x, y, r=19):
    navy, cyan = colors.HexColor("#1b2a4a"), colors.HexColor("#19a3c4")
    c.setFillColor(navy)
    c.circle(x + r, y + r, r, stroke=0, fill=1)
    c.setStrokeColor(cyan)
    c.setLineWidth(1.6)
    for w in (r * 0.35, r * 0.75):
        c.ellipse(x + r - w, y + 2, x + r + w, y + 2 * r - 2, stroke=1, fill=0)
    c.line(x + 3, y + r, x + 2 * r - 3, y + r)
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 21)
    c.drawString(x + 2 * r + 10, y + r - 1, "MERIDIAN")
    c.saveState()
    t = c.beginText(x + 2 * r + 11, y + 4)
    t.setFont("Helvetica", 7.5)
    t.setCharSpace(2.6)
    t.setFillColor(cyan)
    t.textOut("CLOUD SERVICES")
    c.drawText(t)
    c.restoreState()


def render_meridian(inv: Invoice) -> bytes:
    v, p = VENDOR["V003"], PROFILE["V003"]
    navy, cyan, grey = colors.HexColor("#1b2a4a"), colors.HexColor("#19a3c4"), colors.HexColor("#6b7280")
    W, H = LETTER
    buf = io.BytesIO()
    c = new_canvas(buf, LETTER, f"Invoice {inv.invoice_no}", v["legal_name"], "Meridian Billing Platform")
    x0, x1 = 48, W - 48

    draw_meridian_logo(c, x0, H - 92)
    lines_at(c, x0, H - 112, [v["legal_name"]] + p["addr"] + [f"EIN {v['tax_id']}  ·  {p['phone']}"],
             size=8.5, leading=11, color=grey)
    c.setFillColor(navy)
    c.setFont("Helvetica", 30)
    c.drawRightString(x1, H - 80, "INVOICE")

    meta = [["Invoice #", inv.invoice_no], ["Invoice date", us_date_short(inv.date)],
            ["Due date", us_date_short(inv.due)], ["Terms", f"Net {inv.terms_days}"], ["PO Number", inv.po_ref]]
    t = Table(meta, colWidths=[80, 100])
    t.setStyle(TableStyle([("FONT", (0, 0), (0, -1), "Helvetica", 8.5), ("TEXTCOLOR", (0, 0), (0, -1), grey),
                           ("FONT", (1, 0), (1, -1), "Helvetica-Bold", 9), ("TEXTCOLOR", (1, 0), (1, -1), navy),
                           ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    place(c, t, x1 - 180, H - 100, 180)

    yb = H - 200
    c.setFillColor(cyan)
    c.rect(x0, yb - 64, 2.5, 72, stroke=0, fill=1)
    c.setFillColor(grey)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(x0 + 10, yb, "BILL TO")
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x0 + 10, yb - 14, BILL_TO["US"][0])
    lines_at(c, x0 + 10, yb - 27, BILL_TO["US"][1:], size=9, leading=11.5, color=colors.HexColor("#374151"))

    rows = [["DESCRIPTION", "QTY", "RATE", "AMOUNT"]]
    for ln in inv.lines:
        rows.append([P(ln.description, ps("Helvetica", 9.5)), qty_str(ln.qty), f"${fmt(ln.unit_price)}",
                     f"${fmt(ln.amount)}"])
    t = Table(rows, colWidths=[286, 50, 85, 95])
    style = [("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("FONT", (1, 1), (-1, -1), "Helvetica", 9.5),
             ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
             ("LINEBELOW", (0, -1), (-1, -1), 0.6, navy)]
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f1f5f9")))
    t.setStyle(TableStyle(style))
    y = H - 300
    y -= place(c, t, x0, y, x1 - x0)

    y -= 22
    tot = [["Subtotal", f"${fmt(inv.net)}"], [f"Sales tax ({inv.tax_rate:.0f}%)", f"${fmt(inv.tax)}"]]
    t = Table(tot, colWidths=[110, 90])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 9.5), ("TEXTCOLOR", (0, 0), (0, -1), grey),
                           ("ALIGN", (1, 0), (1, -1), "RIGHT")]))
    y -= place(c, t, x1 - 200, y, 200)
    y -= 8
    c.setFillColor(cyan)
    c.rect(x1 - 200, y - 30, 200, 30, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x1 - 194, y - 19, "AMOUNT DUE (USD)")
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(x1 - 8, y - 20, f"${fmt(inv.total)}")

    place(c, P("<b>Notes</b><br/>No sales tax applies to these services.<br/>"
               f"Please reference invoice {inv.invoice_no} on your remittance.", ps("Helvetica", 8.5, color=grey)),
          x0, y + 6, 240)

    fy = 96
    c.setStrokeColor(colors.HexColor("#d1d5db"))
    c.setLineWidth(0.6)
    c.line(x0, fy, x1, fy)
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x0, fy - 14, "REMIT TO")
    lines_at(c, x0, fy - 26, [p["bank"][0], f"{p['bank'][1]}  ·  {p['bank'][2]}  ·  {p['bank'][3]}"],
             size=8, leading=10.5, color=grey)
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(360, fy - 14, "QUESTIONS")
    lines_at(c, 360, fy - 26, [p["email"], p["web"]], size=8, leading=10.5, color=grey)
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(W / 2, 36, "Thank you for your business!")
    c.showPage()
    c.save()
    return buf.getvalue()


# --------------------------------------------------------------------------------------
# Template 4 - Helios (DE): bundled single service line, DIN-5008-style letter
# --------------------------------------------------------------------------------------


def render_helios(inv: Invoice) -> bytes:
    v, p = VENDOR["V004"], PROFILE["V004"]
    amber, dark, grey = colors.HexColor("#c8641e"), colors.HexColor("#2b2b2b"), colors.HexColor("#6a6a6a")
    W, H = A4
    buf = io.BytesIO()
    c = new_canvas(buf, A4, f"Rechnung {inv.invoice_no}", v["legal_name"], "Helios FM Faktura 7")
    x0, x1 = 57, W - 57
    F, FB = "Vera", "Vera-Bold"

    # Logo block, top right
    c.setFillColor(amber)
    c.circle(x1 - 128, H - 58, 13, stroke=0, fill=1)
    c.setStrokeColor(amber)
    c.setLineWidth(1.4)
    for k in range(12):
        a = k * math.pi / 6
        c.line(x1 - 128 + 17 * math.cos(a), H - 58 + 17 * math.sin(a),
               x1 - 128 + 22 * math.cos(a), H - 58 + 22 * math.sin(a))
    c.setFillColor(dark)
    c.setFont(FB, 20)
    c.drawString(x1 - 98, H - 60, "HELIOS")
    c.setFont(F, 8.5)
    c.setFillColor(amber)
    c.drawString(x1 - 98, H - 73, "Facility Management")

    # Sender line + address window
    c.setFont(F, 6.5)
    c.setFillColor(grey)
    sender = f"{v['legal_name']} · {p['addr'][0]} · {p['addr'][1]}"
    c.drawString(x0, H - 128, sender)
    c.setLineWidth(0.3)
    c.setStrokeColor(grey)
    c.line(x0, H - 130, x0 + c.stringWidth(sender, F, 6.5), H - 130)
    lines_at(c, x0, H - 146, BILL_TO["DE"], font=F, size=9.5, leading=12.5, color=dark)

    info = [("Rechnungs-Nr. / Invoice no.", inv.invoice_no),
            ("Rechnungsdatum / Invoice date", inv.date.strftime("%d.%m.%Y")),
            ("Kunden-Nr. / Customer no.", "K-40017"),
            ("Leistungszeitraum / Service period", inv.extra["period"]),
            ("Fällig am / Due date", inv.due.strftime("%d.%m.%Y")),
            ("Zahlungsziel / Payment terms", f"{inv.terms_days} Tage / {inv.terms_days} days net"),
            ("USt-IdNr. / VAT ID", v["tax_id"])]
    t = Table([[P(a, ps(F, 7, color=grey)), P(b, ps(FB, 7.5, color=dark))] for a, b in info],
              colWidths=[132, 116])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    place(c, t, x1 - 248, H - 132, 248)

    y = H - 290
    c.setFillColor(dark)
    c.setFont(FB, 14)
    c.drawString(x0, y, f"Rechnung / Invoice {inv.invoice_no}")
    y -= 24
    body = ps(F, 9, leading=12.5, color=dark)
    y -= place(c, P("Sehr geehrte Damen und Herren,<br/>"
                    f"as per your order {inv.po_ref} we invoice the following services for your Munich branch "
                    f"(service period {inv.extra['period']}):", body), x0, y, x1 - x0)
    y -= 12

    hdr = ps(FB, 7.5, leading=9.5, color=colors.white)
    hdr_r = ps(FB, 7.5, leading=9.5, color=colors.white, align=TA_RIGHT)
    rows = [[P("Pos.", hdr), P("Leistung / Description", hdr), P("Menge / Qty", hdr_r),
             P("Einzelpreis EUR / Unit price", hdr_r), P("Betrag EUR / Amount", hdr_r)]]
    for i, ln in enumerate(inv.lines, 1):
        rows.append([str(i), P(ln.description, ps(F, 9.5, color=dark)), qty_str(ln.qty),
                     fmt(ln.unit_price, "de"), fmt(ln.amount, "de")])
    t = Table(rows, colWidths=[32, 215, 58, 88, 88])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), amber), ("FONT", (0, 1), (-1, -1), F, 9.5),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 1), (-1, -1), 9), ("BOTTOMPADDING", (0, 1), (-1, -1), 9),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, dark),
    ]))
    y -= place(c, t, x0, y, x1 - x0)

    y -= 10
    tot = [["Nettobetrag / Net amount", f"{fmt(inv.net, 'de')} €"],
           [f"zzgl. {inv.tax_rate:.0f} % USt. / VAT {inv.tax_rate:.0f} %", f"{fmt(inv.tax, 'de')} €"],
           ["Rechnungsbetrag / Total amount", f"{fmt(inv.total, 'de')} €"]]
    t = Table(tot, colWidths=[215, 95])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 9), ("FONT", (0, 2), (-1, 2), FB, 10.5),
                           ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("TEXTCOLOR", (0, 0), (-1, -1), dark),
                           ("LINEABOVE", (0, 2), (-1, 2), 0.8, dark), ("LINEBELOW", (0, 2), (-1, 2), 1.6, amber),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    y -= place(c, t, x1 - 310, y, 310)

    y -= 26
    y -= place(c, P(f"Bitte überweisen Sie den Rechnungsbetrag bis zum {inv.due.strftime('%d.%m.%Y')} unter Angabe "
                    "der Rechnungsnummer auf das unten genannte Konto.<br/>"
                    f"<font color='#6a6a6a'>Please transfer the total amount by {inv.due.strftime('%d.%m.%Y')} quoting "
                    "the invoice number to the account below.</font><br/><br/>"
                    "Vielen Dank für Ihren Auftrag! / Thank you for your business!<br/><br/>"
                    "Mit freundlichen Grüßen<br/>Helios Facility Management GmbH", body), x0, y, x1 - x0)

    fy = 78
    c.setStrokeColor(amber)
    c.setLineWidth(0.8)
    c.line(x0, fy, x1, fy)
    cols = [[v["legal_name"]] + p["addr"][:2],
            [f"Geschäftsführer: {p['md']}", f"{p['court']} {p['hrb']}", f"USt-IdNr.: {v['tax_id']}"],
            p["bank"],
            [f"Tel. {p['phone']}", p["email"], p["web"]]]
    fs = 6.3  # columns spread evenly across the full width, sized to their widest line
    widths = [max(c.stringWidth(t, F, fs) for t in col) for col in cols]
    gap = ((x1 - x0) - sum(widths)) / (len(cols) - 1)
    xx = x0
    for wcol, col in zip(widths, cols):
        lines_at(c, xx, fy - 12, col, font=F, size=fs, leading=8.5, color=grey)
        xx += wcol + gap
    c.showPage()
    c.save()
    return buf.getvalue()


# --------------------------------------------------------------------------------------
# Template 5 - Quantum (NL): two-column header
# --------------------------------------------------------------------------------------


def two_column_invoice(inv: Invoice, *, brand: dict) -> bytes:
    """Two-column header layout. Used by Quantum (its usual template)."""
    W, H = A4
    purple, lav, dark, grey = brand["primary"], brand["light"], colors.HexColor("#1f1b2e"), colors.HexColor("#5d5a6b")
    buf = io.BytesIO()
    title = f"Invoice {inv.invoice_no}" if inv.invoice_no else "Invoice"
    c = new_canvas(buf, A4, title, brand["name"], brand["creator"])
    x0, x1 = 42, W - 42
    hh = 150

    c.setFillColor(purple)
    c.rect(0, H - hh, W / 2, hh, stroke=0, fill=1)
    c.setFillColor(lav)
    c.rect(W / 2, H - hh, W / 2, hh, stroke=0, fill=1)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(x0, H - 50, brand["wordmark"])
    lines_at(c, x0, H - 70, brand["left_lines"], size=8.5, leading=11, color=colors.white)

    c.setFillColor(purple)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(W / 2 + 28, H - 52, "INVOICE")
    meta = brand["meta"]
    t = Table(meta, colWidths=[90, 120])
    t.setStyle(TableStyle([("FONT", (0, 0), (0, -1), "Helvetica", 8.5), ("TEXTCOLOR", (0, 0), (0, -1), grey),
                           ("FONT", (1, 0), (1, -1), "Helvetica-Bold", 9), ("TEXTCOLOR", (1, 0), (1, -1), dark),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    place(c, t, W / 2 + 28, H - 66, 220)

    y = H - hh - 30
    for xx, (label, blines) in zip((x0, W / 2 + 28), brand["address_cols"]):
        c.setFillColor(purple)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(xx, y, label)
        lines_at(c, xx, y - 14, blines, size=9.5, leading=12.5, color=dark)

    y = H - 305
    if brand.get("intro"):
        y -= place(c, P(brand["intro"], ps("Helvetica", 9, color=dark, leading=12)), x0, y, x1 - x0)
        y -= 10
    hdr = ps("Helvetica-Bold", 8, color=purple)
    hdr_r = ps("Helvetica-Bold", 8, color=purple, align=TA_RIGHT)
    cur = brand["cur"]
    rows = [[P("Description", hdr), P("Qty", hdr_r), P("Unit price", hdr_r), P("VAT", hdr_r), P("Amount", hdr_r)]]
    for ln in inv.lines:
        rows.append([P(ln.description, ps("Helvetica", 9.5, color=dark)), qty_str(ln.qty),
                     f"{cur}{fmt(ln.unit_price)}", f"{inv.tax_rate:.0f}%", f"{cur}{fmt(ln.amount)}"])
    t = Table(rows, colWidths=[251, 45, 80, 40, 95])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 1.4, purple), ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#d9d4e8")),
        ("FONT", (1, 1), (-1, -1), "Helvetica", 9.5), ("TEXTCOLOR", (0, 1), (-1, -1), dark),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    y -= place(c, t, x0, y, x1 - x0)

    y -= 14
    tot = [["Subtotal excl. VAT", f"{cur}{fmt(inv.net)}"], [f"VAT {inv.tax_rate:.0f}%", f"{cur}{fmt(inv.tax)}"],
           [brand["total_label"], f"{cur}{fmt(inv.total)}"]]
    t = Table(tot, colWidths=[130, 100])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, 1), "Helvetica", 9.5), ("TEXTCOLOR", (0, 0), (-1, -1), dark),
                           ("FONT", (0, 2), (-1, 2), "Helvetica-Bold", 11), ("BACKGROUND", (0, 2), (-1, 2), lav),
                           ("TEXTCOLOR", (0, 2), (-1, 2), purple), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    y -= place(c, t, x1 - 230, y, 230)

    fy = 110
    c.setStrokeColor(purple)
    c.setLineWidth(0.8)
    c.line(x0, fy, x1, fy)
    place(c, P(brand["footer_html"], ps("Helvetica", 8, leading=11, color=grey)), x0, fy - 8, x1 - x0)
    c.setFillColor(purple)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawCentredString(W / 2, 34, brand["thanks"])
    c.showPage()
    c.save()
    return buf.getvalue()


def render_quantum(inv: Invoice) -> bytes:
    v, p = VENDOR["V006"], PROFILE["V006"]
    meta = [["Invoice date", inv.date.strftime("%d-%m-%Y")], ["Due date", inv.due.strftime("%d-%m-%Y")],
            ["Payment terms", f"{inv.terms_days} days"], ["Currency", "EUR"]]
    if inv.invoice_no:  # EC5 deliberately has no number: the field is simply absent
        meta.insert(0, ["Invoice number", inv.invoice_no])
    brand = dict(
        name=v["legal_name"], creator="QLS Webshop Invoicing", wordmark="Quantum Lab Supplies",
        primary=colors.HexColor("#5b3fa0"), light=colors.HexColor("#efeaf8"), cur="€ ",
        left_lines=[v["legal_name"]] + p["addr"] + [f"KvK {p['kvk']}  ·  BTW {v['tax_id']}"],
        meta=meta,
        address_cols=[("BILLED TO", BILL_TO["NL"]),
                      ("SHIP TO", [CUSTOMER, "Lab 2 – Goods receiving", "Science Park 904", "1098 XH Amsterdam"])],
        total_label="Total incl. VAT",
        footer_html=(f"<b>Payment</b>: please transfer the total within {inv.terms_days} days to "
                     f"{p['bank'][0]}, {p['bank'][1]}, {p['bank'][2]}, in the name of {v['legal_name']}. "
                     "Please quote the invoice number with your payment.<br/>"
                     f"{v['legal_name']} · {', '.join(p['addr'])} · KvK {p['kvk']} · BTW {v['tax_id']} · "
                     f"{p['email']} · {p['phone']}"),
        thanks="Thank you for choosing Quantum Lab Supplies.",
    )
    return two_column_invoice(inv, brand=brand)


# --------------------------------------------------------------------------------------
# Template 6 - Silverline (unknown vendor, US): minimal / plain
# --------------------------------------------------------------------------------------


def render_silverline(inv: Invoice) -> bytes:
    p = PROFILE["SILVERLINE"]
    W, H = LETTER
    buf = io.BytesIO()
    c = new_canvas(buf, LETTER, f"Invoice {inv.invoice_no}", p["name"], "invoice.docx")
    x0, x1 = 72, W - 72
    F, FB = "Courier", "Courier-Bold"
    c.setFont(FB, 13)
    c.drawString(x0, H - 80, p["name"].upper())
    lines_at(c, x0, H - 96, p["addr"] + [f"{p['phone']}  {p['email']}", f"EIN {p['ein']}"], font=F, size=9,
             leading=11.5)

    y = H - 180
    c.setFont(FB, 12)
    c.drawString(x0, y, f"INVOICE {inv.invoice_no}")
    lines_at(c, x0, y - 18, [f"Date:  {us_date(inv.date)}", f"Due:   {us_date(inv.due)}",
                             f"Terms: Net {inv.terms_days}"], font=F, size=9.5, leading=12.5)
    c.setFont(FB, 9.5)
    c.drawString(330, y, "BILL TO")
    lines_at(c, 330, y - 18, BILL_TO["US"], font=F, size=9.5, leading=12.5)

    y = H - 300
    c.setLineWidth(0.8)
    c.line(x0, y + 14, x1, y + 14)
    c.setFont(FB, 9.5)
    c.drawString(x0, y, "DESCRIPTION")
    for xx, h in ((350, "QTY"), (420, "RATE"), (x1, "AMOUNT")):
        c.drawRightString(xx, y, h)
    c.line(x0, y - 6, x1, y - 6)
    y -= 22
    for ln in inv.lines:
        h = place(c, P(ln.description, ps(F, 9.5, leading=12)), x0, y + 10, 250)
        c.setFont(F, 9.5)
        c.drawRightString(350, y, qty_str(ln.qty))
        c.drawRightString(420, y, fmt(ln.unit_price))
        c.drawRightString(x1, y, fmt(ln.amount))
        y -= max(h, 12) + 8
    c.line(x0, y + 4, x1, y + 4)
    y -= 14
    for lab, val, bold in (("Subtotal", fmt(inv.net), False), (f"Tax ({inv.tax_rate:.0f}%)", fmt(inv.tax), False),
                           ("TOTAL DUE (USD)", fmt(inv.total), True)):
        c.setFont(FB if bold else F, 10 if bold else 9.5)
        c.drawString(330, y, lab)
        c.drawRightString(x1, y, val)
        y -= 15

    y -= 30
    lines_at(c, x0, y, ["Payment by wire or ACH:", f"  {p['bank'][0]}", f"  {p['bank'][1]}",
                        f"  {p['bank'][2]}", "", "Thank you - it was a pleasure working with your team."],
             font=F, size=9, leading=12)
    c.showPage()
    c.save()
    return buf.getvalue()


# --------------------------------------------------------------------------------------
# EC4 - Meridian re-sent from its dunning system: different template, overdue footer
# --------------------------------------------------------------------------------------


def render_meridian_reminder(inv: Invoice) -> bytes:
    v, p = VENDOR["V003"], PROFILE["V003"]
    W, H = LETTER
    red = colors.HexColor("#b42318")
    buf = io.BytesIO()
    c = new_canvas(buf, LETTER, f"Invoice {inv.invoice_no} (copy)", v["legal_name"], "Meridian Collections")
    x0, x1 = 60, W - 60
    F, FB = "Times-Roman", "Times-Bold"

    c.setFont(FB, 17)
    c.drawCentredString(W / 2, H - 64, v["legal_name"])
    c.setFont(F, 9.5)
    c.drawCentredString(W / 2, H - 79, "  ·  ".join(p["addr"]))
    c.drawCentredString(W / 2, H - 91, f"EIN {v['tax_id']}  ·  {p['phone']}  ·  {p['email']}")
    c.setLineWidth(1.2)
    c.line(x0, H - 102, x1, H - 102)
    c.setLineWidth(0.4)
    c.line(x0, H - 105, x1, H - 105)

    y = H - 140
    c.setFont(FB, 14)
    c.drawString(x0, y, "INVOICE")
    lines_at(c, x0, y - 22, ["Bill to:"] + BILL_TO["US"], font=F, size=10, leading=13)
    meta = [["Invoice No.", inv.invoice_no], ["Invoice Date", us_date(inv.date)], ["Due Date", us_date(inv.due)],
            ["Terms", f"Net {inv.terms_days}"]]
    t = Table(meta, colWidths=[80, 115])
    t.setStyle(TableStyle([("FONT", (0, 0), (0, -1), F, 10), ("FONT", (1, 0), (1, -1), FB, 10),
                           ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
                           ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey)]))
    place(c, t, x1 - 195, y + 10, 195)

    # rubber stamp
    c.saveState()
    c.translate(x1 - 100, y - 112)
    c.rotate(8)
    c.setStrokeColor(red)
    c.setFillColor(red)
    c.setLineWidth(1.8)
    c.roundRect(-72, -16, 144, 34, 4, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(0, -6, "SECOND COPY")
    c.restoreState()

    y -= 150
    body = ps(F, 10.5, leading=14)
    y -= place(c, P(f"This invoice relates to your purchase order {inv.po_ref} for managed backup services. "
                    "Our records show it remains unpaid; a copy is enclosed for your convenience.", body),
               x0, y, x1 - x0)
    y -= 14
    rows = [["Description", "Quantity", "Unit Price", "Amount"]]
    for ln in inv.lines:
        rows.append([P(ln.description, ps(F, 10.5)), qty_str(ln.qty), fmt(ln.unit_price), fmt(ln.amount)])
    rows += [["", "", "Subtotal", fmt(inv.net)], ["", "", f"Tax ({inv.tax_rate:.0f}%)", fmt(inv.tax)],
             ["", "", "Total (USD)", fmt(inv.total)]]
    t = Table(rows, colWidths=[260, 65, 85, 82])
    n = len(rows)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), FB, 10), ("FONT", (0, 1), (-1, -1), F, 10.5),
                           ("FONT", (2, n - 1), (-1, n - 1), FB, 11),
                           ("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.black),
                           ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.black),
                           ("LINEBELOW", (0, n - 4), (-1, n - 4), 0.4, colors.black),
                           ("LINEABOVE", (2, n - 1), (-1, n - 1), 0.8, colors.black),
                           ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    y -= place(c, t, x0, y, x1 - x0)

    y -= 30
    lines_at(c, x0, y, ["Remittance: " + p["bank"][0], f"{p['bank'][1]}  ·  {p['bank'][2]}  ·  {p['bank'][3]}",
                        f"Please reference invoice {inv.invoice_no} on your remittance."], font=F, size=10, leading=13)

    c.setFillColor(red)
    c.setFont(FB, 11)
    c.drawCentredString(W / 2, 74, "Reminder: payment overdue — second copy")
    c.setFillColor(colors.black)
    c.setFont("Times-Italic", 10)
    c.drawCentredString(W / 2, 56, "If you have already paid, please disregard this notice. Thank you for your business.")
    c.showPage()
    c.save()
    return buf.getvalue()


# --------------------------------------------------------------------------------------
# EC1 - "scan" a digital PDF into an image-only PDF
# --------------------------------------------------------------------------------------


def scan(pdf_bytes: bytes, seed: int = SEED, dpi: int = 150) -> bytes:
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    pix = src[0].get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    src.close()
    paper = 243
    img = img.point(lambda v: int(12 + v * (paper - 12) / 255))  # off-white paper, slightly lifted blacks
    img = img.rotate(1.5, resample=Image.BICUBIC, expand=False, fillcolor=paper)

    # Seeded gaussian noise via a uniform-byte -> inverse-normal-CDF lookup table (fast, deterministic).
    rng = random.Random(seed)
    nd = statistics.NormalDist(0, 9)
    lut = [max(0, min(255, round(128 + nd.inv_cdf((i + 0.5) / 256)))) for i in range(256)]
    noise = Image.frombytes("L", img.size, rng.randbytes(img.size[0] * img.size[1])).point(lut)
    img = ImageChops.add(img, noise, scale=1.0, offset=-128)

    # scanner-lid shadow on the left edge and a faint top edge
    dr = ImageDraw.Draw(img)
    for i in range(14):
        dr.line([(i, 0), (i, img.size[1])], fill=int(150 + i * 6.5))
    for i in range(6):
        dr.line([(0, i), (img.size[0], i)], fill=int(200 + i * 7))
    img = img.filter(ImageFilter.GaussianBlur(0.7))

    jpg = io.BytesIO()
    img.save(jpg, format="JPEG", quality=72)
    jpg.seek(0)
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4, invariant=1)
    c.setCreator("Office MFP Scan to PDF")
    c.setTitle("Scan")
    c.drawImage(ImageReader(jpg), 0, 0, width=A4[0], height=A4[1])
    c.showPage()
    c.save()
    return out.getvalue()


# --------------------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------------------

SAMPLE_META = {
    "HP": dict(title="Happy path — Meridian Cloud, PO matches exactly", scenario="happy_path",
               expected_decision="APPROVE", expected_rule_failures=[], demo_order=1,
               notes="Clean digital PDF, logo-block template on US Letter. Two lines exactly as PO-2026-0107, "
                     "no sales tax, PO in a labelled 'PO Number' field."),
    "EC1": dict(title="Scanned invoice — Northwind, image-only PDF", scenario="scanned",
                expected_decision="APPROVE", expected_rule_failures=[], demo_order=2,
                notes="Image-only PDF (150 dpi grey scan, 1.5° skew, noise, blur; no text layer). Tax-inclusive "
                      "layout: 'Total incl. VAT' is the big number, net subtotal and VAT are in small type."),
    "EC2a": dict(title="Split PO, part 1 — Helios, within remaining balance", scenario="split_po_within",
                 expected_decision="APPROVE", expected_rule_failures=[], demo_order=3,
                 notes="Bundled single service line; PO only inside a sentence. German number format (4.000,00 €) "
                       "and DD.MM.YYYY dates on purpose. Leaves 4,000.00 remaining on PO-2026-0105."),
    "EC2b": dict(title="Split PO, part 2 — Helios, exceeds remaining balance", scenario="split_po_over",
                 expected_decision="HOLD", expected_rule_failures=["R5"], demo_order=4,
                 notes="Run after EC2a: 8,000.00 billed + 8,000.00 > 12,000.00 PO, so R5 holds it. On a fresh "
                       "ledger (EC2a not run) it APPROVEs and fully consumes the PO. German number format."),
    "EC4": dict(title="Duplicate — Meridian MCS-10398 re-sent in a new layout", scenario="duplicate",
                expected_decision="REJECT", expected_rule_failures=["R3", "R5"], demo_order=5,
                notes="Ledger invoice MCS-10398 re-rendered in a plain dunning template with a 'SECOND COPY' "
                      "stamp and overdue footer; file hash differs from the ledger's. R5 also trips because the "
                      "original already consumed PO-2026-0106."),
    "EC3": dict(title="Price variance — Apex flange 8% above PO", scenario="price_variance",
                expected_decision="HOLD", expected_rule_failures=["R4", "R6"], demo_order=6,
                notes="Table-heavy Indian GST tax invoice (IGST 18%, HSN summary, amount in words). Flange rate "
                      "486.00 vs PO 450.00 (+8%); PO in the 'Buyer's Order No.' cell; buyer GSTIN also on page."),
    "EC5": dict(title="Missing invoice number and PO — Quantum Lab", scenario="missing_fields",
                expected_decision="HOLD", expected_rule_failures=["R8"], demo_order=7,
                notes="No invoice number and no PO reference anywhere. Lines exactly as PO-2026-0109 so the PO "
                      "can be inferred; R8 drafts a vendor email. R10 ignores absent fields, so only R8 fails."),
    "EC6": dict(title="Unknown vendor — Silverline Consulting Partners", scenario="unknown_vendor",
                expected_decision="REJECT", expected_rule_failures=["R1", "R2"], demo_order=8,
                notes="Minimal Courier invoice from a vendor not in the master. PO-2026-0199 (does not exist) "
                      "appears only inside the line description."),
}

RENDERERS: dict[str, Callable[[Invoice], bytes]] = {
    "HP": render_meridian, "EC1": render_northwind, "EC2a": render_helios, "EC2b": render_helios,
    "EC3": render_apex, "EC4": render_meridian_reminder, "EC5": render_quantum, "EC6": render_silverline,
}
ORIGINAL_RENDERERS = {"MCS-10398": render_meridian, "HFM-2026-091": render_helios}


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def render_all() -> dict[str, bytes]:
    out = {}
    for sid, inv in INVOICES.items():
        if sid == "EC1":
            out["EC1_digital"] = render_northwind(inv)
            out[sid] = scan(out["EC1_digital"])
        else:
            out[sid] = RENDERERS[sid](inv)
    return out


def original_hashes() -> dict[str, str]:
    return {k: sha256(ORIGINAL_RENDERERS[k](inv)) for k, inv in ORIGINALS.items()}


def write_csv(path: Path, header: list, rows: list):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def build():
    DATA.mkdir(exist_ok=True)
    SAMPLES_DIR.mkdir(exist_ok=True)

    write_csv(DATA / "vendors.csv",
              ["vendor_id", "legal_name", "aliases", "tax_id", "country", "currency", "status",
               "payment_terms_days", "contact_email"],
              [[v[k] for k in ("vendor_id", "legal_name", "aliases", "tax_id", "country", "currency", "status",
                               "payment_terms_days", "contact_email")] for v in VENDORS])

    pos = sorted(SCENARIO_POS + FILLER_POS, key=lambda r: r[0])
    po_rows, line_rows = [], []
    for po, vid, date, status, req, desc, lines in pos:
        net = sum(D(q) * D(u) for _, q, u in lines)
        po_rows.append([po, vid, date, VENDOR[vid]["currency"], m(net), status, REQ[req][0], REQ[req][1], desc])
        for i, (ld, q, u) in enumerate(lines, 1):
            line_rows.append([po, i, ld, qty_str(q), m(u), m(D(q) * D(u))])
    write_csv(DATA / "purchase_orders.csv",
              ["po_number", "vendor_id", "po_date", "currency", "net_total", "status", "requester_name",
               "requester_email", "description"], po_rows)
    write_csv(DATA / "po_lines.csv", ["po_number", "line_no", "description", "quantity", "unit_price", "line_total"],
              line_rows)

    hashes = original_hashes()
    ledger = []
    for inv_no, vid, date, net, gross, po, dec, hsrc, processed in sorted(SCENARIO_LEDGER + FILLER_LEDGER,
                                                                          key=lambda r: r[8]):
        fh = hashes[hsrc.split(":", 1)[1]] if hsrc.startswith("original:") else ""
        ledger.append([inv_no, vid, date, VENDOR[vid]["currency"], net, gross, po, dec, fh, processed])
    write_csv(DATA / "ledger_seed.csv",
              ["invoice_number", "vendor_id", "invoice_date", "currency", "net_total", "gross_total", "po_number",
               "decision", "file_hash", "processed_at"], ledger)

    pdfs = render_all()
    for f in SAMPLES_DIR.glob("*.pdf"):
        if f.name not in {s[0] for s in SPEC_SAMPLES.values()}:
            f.unlink()
    for sid, spec in SPEC_SAMPLES.items():
        (SAMPLES_DIR / spec[0]).write_bytes(pdfs[sid])

    samples = []
    for sid, meta in sorted(SAMPLE_META.items(), key=lambda kv: kv[1]["demo_order"]):
        inv = INVOICES[sid]
        samples.append({
            "id": sid,
            "title": meta["title"],
            "scenario": meta["scenario"],
            "file": f"samples/{SPEC_SAMPLES[sid][0]}",
            "vendor_id": inv.vendor_id,
            "expected_decision": meta["expected_decision"],
            "expected_rule_failures": meta["expected_rule_failures"],
            "demo_order": meta["demo_order"],
            "notes": meta["notes"],
            "invoice": {
                "invoice_number": inv.invoice_no,
                "invoice_date": inv.date.isoformat(),
                "currency": inv.currency,
                "po_reference": inv.po_ref,
                "net_total": float(inv.net),
                "tax_rate_pct": float(inv.tax_rate),
                "tax_amount": float(inv.tax),
                "gross_total": float(inv.total),
            },
        })
    (DATA / "samples.json").write_text(json.dumps(samples, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return pdfs


# --------------------------------------------------------------------------------------
# Verify
# --------------------------------------------------------------------------------------


class Checker:
    def __init__(self):
        self.failures, self.passes = [], 0

    def ok(self, cond, msg):
        if cond:
            self.passes += 1
        else:
            self.failures.append(msg)


def read_csv(name):
    with (DATA / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def pdf_text(b: bytes) -> tuple[int, str]:
    r = PdfReader(io.BytesIO(b))
    return len(r.pages), "".join((pg.extract_text() or "") for pg in r.pages)


def simulate_rules(sid, inv_json, vendors, pos, lines_by_po, ledger, cfg):
    """Re-derive which rules (SPEC 4.6) must fail, from data alone. Assumes perfect extraction;
    absent fields count as confidence 0.0. Returns sorted list of failing rule codes."""
    fails = set()
    spec = SPEC_SAMPLES[sid]
    vid = spec[1]
    v = vendors.get(vid) if vid else None
    if v is None:
        fails.add("R1")
    elif v["status"] != "approved":
        fails.add("R1")
    po_no = inv_json["po_reference"]
    if po_no is None and v is not None:  # infer: the vendor's open PO whose lines match exactly
        cands = [p for p in pos.values() if p["vendor_id"] == vid and p["status"] == "open"]
        inv_lines = {ln.description for ln in INVOICES[sid].lines}
        best = [p for p in cands if inv_lines <= {l["description"] for l in lines_by_po[p["po_number"]]}]
        po_no = best[0]["po_number"] if len(best) == 1 else None
    po = pos.get(po_no) if po_no else None
    net = q2(inv_json["net_total"])
    if po is None:
        fails.add("R2")
    else:
        if po["status"] != "open" or (vid and po["vendor_id"] != vid):
            fails.add("R2")
        pnet = q2(po["net_total"])
        tol = max(q2(pnet * D(cfg["pct"])), D(cfg["floor"][po["currency"]]))
        if net > pnet + tol:
            fails.add("R4")
        billed = sum((q2(r["net_total"]) for r in ledger if r["po_number"] == po_no and r["decision"] == "APPROVE"),
                     Decimal(0))
        # SPEC 4.6: R5 is skipped when nothing has been billed yet (R4 covers that case).
        if billed > 0 and billed + net > pnet + tol:
            fails.add("R5")
        po_lines = {l["description"]: l for l in lines_by_po[po_no]}
        for ln in INVOICES[sid].lines:
            pl = po_lines.get(ln.description)
            if pl is None:
                # SPEC: unmatched lines matter only if their amount exceeds the total tolerance;
                # a fuzzy match is assumed for the Helios month-named lines (token_set_ratio ~87).
                if not ln.description.startswith("Facility cleaning services") and ln.amount > tol:
                    fails.add("R6")
            elif abs(ln.unit_price - q2(pl["unit_price"])) > q2(pl["unit_price"]) * D(cfg["pct"]):
                fails.add("R6")
        if inv_json["currency"] != po["currency"]:
            fails.add("R7")
    if v is not None:
        for r in ledger:
            if r["vendor_id"] != vid or r["decision"] == "REJECT":
                continue
            same_no = inv_json["invoice_number"] and r["invoice_number"] == inv_json["invoice_number"]
            near = abs((d(r["invoice_date"]) - d(inv_json["invoice_date"])).days) <= cfg["dup_days"]
            if same_no or (q2(r["net_total"]) == net and near):
                fails.add("R3")
    if inv_json["invoice_number"] is None:
        fails.update({"R8"})
    age = (REFERENCE_TODAY - d(inv_json["invoice_date"])).days
    if not (0 <= age <= cfg["window"]):
        fails.add("R9")
    return sorted(fails, key=lambda s: int(s[1:]))


def verify(pdfs: Optional[dict] = None) -> bool:
    ck = Checker()
    vendors = {r["vendor_id"]: r for r in read_csv("vendors.csv")}
    pos = {r["po_number"]: r for r in read_csv("purchase_orders.csv")}
    lines = read_csv("po_lines.csv")
    ledger = read_csv("ledger_seed.csv")
    samples = json.loads((DATA / "samples.json").read_text(encoding="utf-8"))
    lines_by_po: dict[str, list] = {}
    for ln in lines:
        lines_by_po.setdefault(ln["po_number"], []).append(ln)

    # headers
    ck.ok(list(vendors["V001"].keys()) == ["vendor_id", "legal_name", "aliases", "tax_id", "country", "currency",
                                           "status", "payment_terms_days", "contact_email"], "vendors.csv header")
    ck.ok(list(next(iter(pos.values())).keys()) == ["po_number", "vendor_id", "po_date", "currency", "net_total",
                                                    "status", "requester_name", "requester_email", "description"],
          "purchase_orders.csv header")
    ck.ok(list(lines[0].keys()) == ["po_number", "line_no", "description", "quantity", "unit_price", "line_total"],
          "po_lines.csv header")
    ck.ok(list(ledger[0].keys()) == ["invoice_number", "vendor_id", "invoice_date", "currency", "net_total",
                                     "gross_total", "po_number", "decision", "file_hash", "processed_at"],
          "ledger_seed.csv header")

    # vendors
    ck.ok(set(vendors) == set(SPEC_VENDORS), "vendor ids")
    for vid, (name, ctry, cur, tax, status, alias) in SPEC_VENDORS.items():
        r = vendors[vid]
        ck.ok((r["legal_name"], r["country"], r["currency"], r["tax_id"], r["status"], r["aliases"]) ==
              (name, ctry, cur, tax, status, alias), f"vendor {vid} differs from SPEC")

    # POs: scenario rows exact, every PO internally consistent
    for po, (vid, cur, net, status, plines) in SPEC_POS.items():
        r = pos.get(po)
        ck.ok(r is not None, f"{po} missing")
        if not r:
            continue
        ck.ok((r["vendor_id"], r["currency"], r["net_total"], r["status"]) == (vid, cur, net, status),
              f"{po} header differs from SPEC")
        got = [(l["description"], l["quantity"], l["unit_price"]) for l in lines_by_po[po]]
        ck.ok(got == list(plines), f"{po} lines differ from SPEC: {got}")
    for po, r in pos.items():
        ls = lines_by_po.get(po, [])
        ck.ok(1 <= len(ls) <= 5, f"{po} has {len(ls)} lines")
        ck.ok(all(q2(D(l["quantity"]) * D(l["unit_price"])) == q2(l["line_total"]) for l in ls), f"{po} line math")
        ck.ok(sum(q2(l["line_total"]) for l in ls) == q2(r["net_total"]), f"{po} net_total != sum of lines")
        ck.ok(r["currency"] == vendors[r["vendor_id"]]["currency"], f"{po} currency != vendor currency")
        ck.ok(d("2026-08-15") <= d(r["po_date"]) <= d("2026-10-31"), f"{po} date out of range")
        ck.ok([int(l["line_no"]) for l in ls] == list(range(1, len(ls) + 1)), f"{po} line numbering")
    ck.ok("PO-2026-0199" not in pos, "PO-2026-0199 must not exist")
    ck.ok(any(r["status"] == "closed" for r in pos.values()), "some filler POs closed")
    ck.ok(6 <= len(pos) - len(SPEC_POS) <= 8, "6-8 filler POs")

    # ledger
    by_no = {r["invoice_number"]: r for r in ledger}
    for no, (vid, date, net, gross, po, dec) in SPEC_LEDGER.items():
        r = by_no.get(no)
        ck.ok(r is not None and (r["vendor_id"], r["invoice_date"], r["net_total"], r["gross_total"],
                                 r["po_number"], r["decision"]) == (vid, date, net, gross, po, dec),
              f"ledger {no} differs from SPEC")
    fillers = [r for r in ledger if r["invoice_number"] not in SPEC_LEDGER]
    ck.ok(6 <= len(fillers) <= 8, "6-8 filler ledger rows")
    hashes = original_hashes()
    ck.ok(by_no["MCS-10398"]["file_hash"] == hashes["MCS-10398"], "ledger MCS-10398 hash is not reproducible")
    for r in ledger:
        ck.ok(r["currency"] == vendors[r["vendor_id"]]["currency"], f"ledger {r['invoice_number']} currency")
        ck.ok(d("2026-08-15") <= d(r["invoice_date"]) <= d("2026-10-31"), f"ledger {r['invoice_number']} date")
        ck.ok(r["po_number"] == "" or r["po_number"] in pos, f"ledger {r['invoice_number']} PO unknown")
    for r in fillers:
        ck.ok(r["po_number"] not in SPEC_POS, f"filler ledger row {r['invoice_number']} is on a scenario PO")
        ck.ok(r["invoice_number"] not in {s[2] for s in SPEC_SAMPLES.values()}, f"filler {r['invoice_number']} collides")
        for sid, s in SPEC_SAMPLES.items():
            if s[1] == r["vendor_id"] and q2(s[5]) == q2(r["net_total"]):
                ck.ok(abs((d(s[3]) - d(r["invoice_date"])).days) > 3,
                      f"filler {r['invoice_number']} fuzzy-duplicates {sid}")
    # filler POs of V006 must not compete with PO-2026-0109 for EC5's inference
    ck.ok(all(r["status"] == "closed" for p, r in pos.items() if r["vendor_id"] == "V006" and p not in SPEC_POS),
          "V006 filler POs must be closed (EC5 inference)")

    # samples.json vs SPEC 2.6
    ck.ok([s["id"] for s in samples] == ["HP", "EC1", "EC2a", "EC2b", "EC4", "EC3", "EC5", "EC6"], "demo order")
    want_order = {"HP": 1, "EC1": 2, "EC2a": 3, "EC2b": 4, "EC4": 5, "EC3": 6, "EC5": 7, "EC6": 8}
    cfg = dict(pct="0.02", floor={"USD": 25, "EUR": 25, "GBP": 20, "INR": 2000}, dup_days=3, window=90)
    sim_ledger = [dict(r) for r in ledger]
    for s in samples:
        sid = s["id"]
        f, vid, no, date, po, net, rate, tax, total, decision = SPEC_SAMPLES[sid]
        j = s["invoice"]
        ck.ok(s["file"] == f"samples/{f}", f"{sid} file name")
        ck.ok(s["vendor_id"] == vid, f"{sid} vendor_id")
        ck.ok(s["expected_decision"] == decision, f"{sid} expected_decision")
        ck.ok(s["demo_order"] == want_order[sid], f"{sid} demo_order")
        ck.ok(j["invoice_number"] == no and j["invoice_date"] == date and j["po_reference"] == po,
              f"{sid} number/date/po differ from SPEC")
        ck.ok(q2(j["net_total"]) == q2(net) and q2(j["tax_amount"]) == q2(tax) and q2(j["gross_total"]) == q2(total)
              and D(j["tax_rate_pct"]) == D(rate), f"{sid} amounts differ from SPEC")
        inv = INVOICES[sid]
        ck.ok(inv.net == q2(net) and inv.tax == q2(tax) and inv.total == q2(total), f"{sid} generator math")
        ck.ok(q2(j["net_total"]) + q2(j["tax_amount"]) == q2(j["gross_total"]), f"{sid} net + tax != gross")
        derived = simulate_rules(sid, j, vendors, pos, lines_by_po, sim_ledger, cfg)
        ck.ok(derived == s["expected_rule_failures"],
              f"{sid} expected_rule_failures {s['expected_rule_failures']} but SPEC 4.6 logic gives {derived}")
        if "R1" not in derived and decision == "APPROVE":  # simulate booking for later samples (EC2a -> EC2b)
            sim_ledger.append(dict(invoice_number=no, vendor_id=vid, invoice_date=date, net_total=net,
                                   po_number=po, decision="APPROVE"))
    # EC2b on a fresh ledger must APPROVE (PO fully consumed)
    fresh = simulate_rules("EC2b", next(s for s in samples if s["id"] == "EC2b")["invoice"], vendors, pos,
                           lines_by_po, ledger, cfg)
    ck.ok(fresh == [], f"EC2b on fresh ledger should pass all rules, got {fresh}")
    # EC2a leaves 4000.00 remaining
    billed = sum(q2(r["net_total"]) for r in ledger if r["po_number"] == "PO-2026-0105" and r["decision"] == "APPROVE")
    ck.ok(q2(pos["PO-2026-0105"]["net_total"]) - billed - q2("4000.00") == q2("4000.00"), "EC2a remaining 4000.00")

    # PDFs
    files = {sid: (SAMPLES_DIR / s[0]).read_bytes() for sid, s in SPEC_SAMPLES.items()}
    ck.ok(sorted(p.name for p in SAMPLES_DIR.glob("*.pdf")) == sorted(s[0] for s in SPEC_SAMPLES.values()),
          "samples/ contains exactly the eight SPEC files")
    all_hashes = [sha256(b) for b in files.values()] + [r["file_hash"] for r in ledger if r["file_hash"]]
    ck.ok(len(set(all_hashes)) == len(all_hashes), "a sample hash collides with another file or the ledger")
    digital_ec1 = pdfs["EC1_digital"] if pdfs else render_northwind(INVOICES["EC1"])
    table = []
    for sid, b in files.items():
        pages, text = pdf_text(b)
        table.append((SPEC_SAMPLES[sid][0], sha256(b), pages, len(text.strip())))
        ck.ok(pages == 1, f"{sid} page count {pages}")
        if sid == "EC1":
            ck.ok(len(text.strip()) < 50, f"EC1 text layer has {len(text.strip())} chars (must be < 50)")
            _, text = pdf_text(digital_ec1)  # check content on the pre-scan render
        else:
            ck.ok(len(text.strip()) >= 200, f"{sid} text layer suspiciously short")
        inv = INVOICES[sid]
        style = "de" if inv.vendor_id == "V004" else "en"
        flat = " ".join(text.split())
        for needle in [fmt(inv.total, style), fmt(inv.net, style)] + ([inv.invoice_no] if inv.invoice_no else []):
            ck.ok(needle in flat, f"{sid}: '{needle}' not printed")
        if inv.po_ref:
            ck.ok(inv.po_ref in flat, f"{sid}: PO ref not printed")
        if inv.tax:
            ck.ok(fmt(inv.tax, style) in flat, f"{sid}: tax not printed")
        for ln in inv.lines:
            ck.ok(" ".join(ln.description.split()) in flat, f"{sid}: line '{ln.description}' not printed verbatim")
    ec5 = " ".join(pdf_text(files["EC5"])[1].split())
    ck.ok("PO-" not in ec5 and "Invoice number" not in ec5 and "Invoice no" not in ec5,
          "EC5 must contain no PO reference and no invoice number")
    ec4 = " ".join(pdf_text(files["EC4"])[1].split())
    ck.ok("Reminder: payment overdue — second copy" in ec4, "EC4 footer")
    ec6 = " ".join(pdf_text(files["EC6"])[1].split())
    ck.ok("Silverline Consulting Partners".upper() in ec6, "EC6 vendor name")

    print_table(table)
    print(f"\nverify: {ck.passes} checks passed, {len(ck.failures)} failed")
    for msg in ck.failures:
        print("  FAIL:", msg)
    return not ck.failures


def print_table(rows):
    print(f"\n{'file':<46} {'sha256':<64} {'pages':>5} {'chars':>6}")
    for f, h, pg, ch in rows:
        print(f"{f:<46} {h} {pg:>5} {ch:>6}")


def preview(outdir: Path, pdfs: Optional[dict] = None, dpi: int = 110):
    outdir.mkdir(parents=True, exist_ok=True)
    items = {sid: (SAMPLES_DIR / s[0]).read_bytes() for sid, s in SPEC_SAMPLES.items()}
    if pdfs:
        items["EC1_digital"] = pdfs["EC1_digital"]
    for k, inv in ORIGINALS.items():
        items[f"original_{k}"] = ORIGINAL_RENDERERS[k](inv)
    for name, b in items.items():
        doc = fitz.open(stream=b, filetype="pdf")
        doc[0].get_pixmap(dpi=dpi).save(str(outdir / f"{name}.png"))
        doc.close()
    print(f"previews written to {outdir}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true", help="only verify existing files against SPEC 2.6")
    ap.add_argument("--preview", metavar="DIR", help="also render each PDF to PNG in DIR")
    args = ap.parse_args()
    pdfs = None
    if not args.verify:
        pdfs = build()
        print(f"wrote {DATA.relative_to(ROOT)}/: 4 CSVs, samples.json, {len(SPEC_SAMPLES)} PDFs")
    if args.preview:
        preview(Path(args.preview), pdfs)
    sys.exit(0 if verify(pdfs) else 1)


if __name__ == "__main__":
    main()
