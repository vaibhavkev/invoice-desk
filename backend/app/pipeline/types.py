"""Shared stage types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

STAGES = [
    ("intake", "Intake"),
    ("doc_analysis", "Document analysis"),
    ("extraction", "LLM extraction"),
    ("integrity", "Normalisation & integrity"),
    ("matching", "Vendor & PO matching"),
    ("rules", "Policy rules"),
    ("decision", "Decision"),
]
STAGE_KEYS = [k for k, _ in STAGES]
STAGE_NAMES = dict(STAGES)


class StageError(Exception):
    """Raised by a stage to fail the run with a readable message (no silent failures)."""

    def __init__(self, message: str, output: Dict[str, Any] = None):
        super().__init__(message)
        self.message = message
        self.output = output or {}


@dataclass
class StageResult:
    summary: str
    output: Dict[str, Any]
    status: str = "done"  # done | warn
    warnings: List[str] = field(default_factory=list)
