"""Samples, reference data, stats and admin endpoints (SPEC 5)."""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlmodel import Session, delete, select

from ..config import settings
from ..db import get_session
from ..models import LedgerEntry, Run, RunEvent, RunStage
from ..refdata import RefData
from ..schemas import ResetRequest
from ..seed import reseed_ledger, reseed_reference, seed_if_empty
from .deps import find_sample, load_samples, sample_path

router = APIRouter(prefix="/api", tags=["reference"])


@router.get("/samples")
def samples():
    return [dict(s, url=f"/api/samples/{s['id']}/file") for s in load_samples()]


@router.get("/samples/{sample_id}/file")
def sample_file(sample_id: str):
    path = sample_path(find_sample(sample_id))
    return FileResponse(path, media_type="application/pdf", filename=path.name, content_disposition_type="inline")


@router.get("/stats")
def stats(session: Session = Depends(get_session)):
    runs = session.exec(select(Run)).all()
    done = [r for r in runs if r.status == "completed"]
    # Counts use the final decision (a reviewer override wins); the auto-approval rate stays the pipeline's own.
    counts = {d: sum(1 for r in done if (r.override_decision or r.decision) == d) for d in ("APPROVE", "HOLD", "REJECT")}
    auto = sum(1 for r in done if r.decision == "APPROVE")
    durations = [r.duration_ms for r in done if r.duration_ms is not None]
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    def created(r: Run) -> datetime:
        try:
            return datetime.fromisoformat(r.created_at.replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)

    return {"runs": len(runs), "approve": counts["APPROVE"], "hold": counts["HOLD"], "reject": counts["REJECT"],
            "auto_approval_rate": round(auto / len(done), 3) if done else 0.0,
            "median_duration_ms": int(statistics.median(durations)) if durations else None,
            "last_24h": sum(1 for r in runs if created(r) >= since)}


@router.get("/policy")
def policy():
    """Loaded policy and extraction settings, read-only. No secrets live in either block."""
    pol, ext = settings.policy, settings.extraction
    return {"policy": {"tolerance_pct": pol.tolerance_pct, "tolerance_abs_floor": dict(pol.tolerance_abs_floor),
                       "confidence_floor": pol.confidence_floor, "date_window_days": pol.date_window_days,
                       "future_date_grace_days": pol.future_date_grace_days,
                       "duplicate_date_window_days": pol.duplicate_date_window_days,
                       "scanned_chars_per_page": pol.scanned_chars_per_page},
            "extraction": {"model": ext.model, "effort": ext.effort, "cache_fallback": ext.cache_fallback}}


@router.get("/reference/vendors")
def vendors(session: Session = Depends(get_session)):
    return [v.__dict__ for v in RefData.from_db(session).vendors]


@router.get("/reference/pos")
def pos(session: Session = Depends(get_session)):
    ref = RefData.from_db(session)
    out = []
    for p in sorted(ref.pos, key=lambda x: x.po_number):
        billed = ref.billed_net_to_date(p.po_number)
        invoices = [{"invoice_number": r.invoice_number, "net_total": r.net_total, "decision": r.decision,
                     "source": r.source, "invoice_date": r.invoice_date, "run_id": r.run_id}
                    for r in sorted(ref.ledger, key=lambda r: r.processed_at or "") if r.po_number == p.po_number]
        d = {k: v for k, v in p.__dict__.items() if k != "lines"}
        d.update(lines=[l.__dict__ for l in p.lines], billed_net_to_date=billed,
                 remaining_net=round(p.net_total - billed, 2), invoices=invoices)
        out.append(d)
    return out


@router.get("/reference/ledger")
def ledger(session: Session = Depends(get_session)):
    rows = session.exec(select(LedgerEntry).order_by(LedgerEntry.processed_at.desc(), LedgerEntry.id.desc())).all()
    return [r.model_dump() for r in rows]


async def _reset_body(request: Request) -> ResetRequest:
    try:
        raw = await request.body()
        return ResetRequest.model_validate_json(raw) if raw.strip() else ResetRequest()
    except ValueError:
        return ResetRequest()


@router.post("/admin/reset")
@router.post("/admin/reset-ledger", include_in_schema=False)
async def reset(request: Request, session: Session = Depends(get_session)):
    body = await _reset_body(request)
    if body.reload_reference:
        reseed_reference(session, settings.data_dir)
    else:
        seed_if_empty(session, settings.data_dir)
    n = reseed_ledger(session, settings.data_dir)
    removed = 0
    if body.clear_runs:
        for r in session.exec(select(Run)).all():
            if r.file_path and Path(r.file_path).parent == settings.upload_dir:
                Path(r.file_path).unlink(missing_ok=True)
            removed += 1
        session.exec(delete(RunEvent))
        session.exec(delete(RunStage))
        session.exec(delete(Run))
        session.commit()
    return {"ok": True, "ledger_rows": n, "runs_removed": removed}
