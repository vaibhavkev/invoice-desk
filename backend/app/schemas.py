"""API and stage pydantic models (SPEC sections 4, 5, 6)."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class StageRecord(BaseModel):
    key: str
    index: int
    name: str
    status: str = "pending"  # pending | running | done | warn | failed | skipped
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    summary: str = ""
    warnings: List[str] = Field(default_factory=list)
    output: Optional[Dict[str, Any]] = None


class RunSummary(BaseModel):
    id: str
    created_at: str
    filename: str
    sample_id: Optional[str] = None
    file_hash: Optional[str] = None
    status: str
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
    override_decision: Optional[str] = None
    override_note: Optional[str] = None
    override_by: Optional[str] = None
    override_at: Optional[str] = None
    override_booking: Optional[Dict[str, Any]] = None
    final_decision: Optional[str] = None  # override_decision if set, else decision


class RunDetail(RunSummary):
    stages: List[StageRecord]


class RunList(BaseModel):
    items: List[RunSummary]
    total: int


class CreateRunRequest(BaseModel):
    sample_id: str
    use_cache: bool = False


class CreateRunResponse(BaseModel):
    run_id: str


class OverrideRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    note: str = Field(min_length=10, max_length=500)
    reviewer: str = Field(default="AP reviewer", max_length=80)

    @field_validator("note", "reviewer", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("reviewer")
    @classmethod
    def _default_reviewer(cls, v: str) -> str:
        return v or "AP reviewer"


class ResetRequest(BaseModel):
    clear_runs: bool = False
    reload_reference: bool = False


class Stats(BaseModel):
    runs: int
    approve: int
    hold: int
    reject: int
    auto_approval_rate: float
    median_duration_ms: Optional[int]
    last_24h: int
