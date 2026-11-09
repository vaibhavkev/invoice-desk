"""Small shared helpers: money rounding/formatting, normalisation, timestamps."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

LEGAL_SUFFIXES = {"ltd", "limited", "inc", "llc", "gmbh", "bv", "pvt", "plc", "co", "corp", "corporation"}

ARITH_TOLERANCE = 0.05  # SPEC 4.4: absolute tolerance for arithmetic checks
EPS = 0.005             # float comparison slack for money already rounded to 2 dp


def r2(x: Optional[float]) -> Optional[float]:
    """Round half-up to 2 dp via Decimal (avoids 2.675 -> 2.67 float surprises)."""
    if x is None:
        return None
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def money(x: Optional[float]) -> str:
    """1234.5 -> '1,234.50'."""
    if x is None:
        return "n/a"
    return f"{r2(x):,.2f}"


def pct(x: float, digits: int = 1) -> str:
    """0.08 -> '8.0%'; trims '2.0%' to '2%'."""
    s = f"{x * 100:.{digits}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s + "%"


def norm_tax_id(s: Optional[str]) -> str:
    """Strip spaces, dashes and dots; uppercase (SPEC 4.4)."""
    if not s:
        return ""
    return re.sub(r"[\s\-\.]", "", s).upper()


def norm_ref(s: Optional[str]) -> str:
    """PO refs and invoice numbers: uppercase, strip non-alphanumerics (SPEC 4.4)."""
    if not s:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", s).upper()


def norm_name(s: Optional[str]) -> str:
    """Lowercase, strip punctuation and legal suffixes, collapse whitespace (SPEC 4.5)."""
    if not s:
        return ""
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^\w\s]", " ", s)
    tokens = [t for t in s.split() if t not in LEGAL_SUFFIXES]
    return " ".join(tokens)


def parse_iso_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    s = s.strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_run_id() -> str:
    return "run_" + uuid.uuid4().hex
