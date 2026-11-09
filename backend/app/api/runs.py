"""Runs: create, list, detail, SSE events, file (SPEC 5, 6)."""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import or_
from sqlmodel import Session, func, select
from sse_starlette.sse import EventSourceResponse

from ..db import get_engine, get_session
from ..models import Run, RunEvent, RunStage
from ..pipeline.events import TERMINAL_EVENTS, broker
from ..pipeline.runner import OverrideRefused, run_summary, stage_record
from ..schemas import OverrideRequest
from .deps import ApiError, execute_run, find_sample, get_runner, run_exclusive, sample_path

router = APIRouter(prefix="/api/runs", tags=["runs"])

MAX_UPLOAD = 16 * 1024 * 1024  # intake enforces the 15 MB rule; this only stops absurd bodies


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


@router.post("", status_code=202)
async def create_run(request: Request, background: BackgroundTasks):
    ctype = request.headers.get("content-type", "")
    runner = get_runner()
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise ApiError(400, "file_missing", "Send the invoice as a multipart field named 'file'.")
        data = await upload.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise ApiError(413, "file_too_large", "The file is larger than 15 MB.")
        filename = upload.filename or "upload.pdf"
        run_id = runner.create_run(filename, data=data, use_cache=_truthy(form.get("use_cache", "false")))
    else:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError(400, "bad_request", "Send multipart 'file' or JSON {\"sample_id\": \"HP\"}.")
        if not isinstance(body, dict) or not body.get("sample_id"):
            raise ApiError(400, "sample_id_missing", "JSON body must include 'sample_id'.")
        sample = find_sample(str(body["sample_id"]))
        path = sample_path(sample)
        run_id = runner.create_run(path.name, sample_id=sample["id"], use_cache=bool(body.get("use_cache", False)),
                                   file_path=path)
    background.add_task(execute_run, run_id)
    return JSONResponse({"run_id": run_id}, status_code=202)


@router.get("")
def list_runs(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), decision: Optional[str] = None,
              q: Optional[str] = None, session: Session = Depends(get_session)):
    stmt = select(Run)
    count = select(func.count()).select_from(Run)
    conds = []
    if decision:  # filters on the final decision, so an overridden HOLD lists under its override
        conds.append(func.coalesce(Run.override_decision, Run.decision) == decision.upper())
    if q:
        like = f"%{q}%"
        conds.append(or_(Run.filename.ilike(like), Run.vendor_name.ilike(like), Run.invoice_number.ilike(like),
                         Run.po_number.ilike(like), Run.sample_id.ilike(like)))
    for c in conds:
        stmt, count = stmt.where(c), count.where(c)
    rows = session.exec(stmt.order_by(Run.created_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [run_summary(r) for r in rows], "total": session.exec(count).one()}


def _get_run(session: Session, run_id: str) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise ApiError(404, "run_not_found", f"No run with id {run_id!r}.")
    return run


@router.get("/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)):
    run = _get_run(session, run_id)
    stages = session.exec(select(RunStage).where(RunStage.run_id == run_id).order_by(RunStage.index)).all()
    out = run_summary(run)
    out["stages"] = [stage_record(st) for st in stages]
    return out


@router.post("/{run_id}/override")
async def override_run(run_id: str, body: OverrideRequest):
    with Session(get_engine()) as s:
        _get_run(s, run_id)
    try:
        return await run_exclusive(get_runner().apply_override, run_id, body.decision, body.note, body.reviewer)
    except OverrideRefused as exc:
        raise ApiError(409, "override_not_allowed", str(exc))


@router.get("/{run_id}/file")
def get_run_file(run_id: str, session: Session = Depends(get_session)):
    run = _get_run(session, run_id)
    from pathlib import Path
    if not run.file_path or not Path(run.file_path).exists():
        raise ApiError(404, "file_missing", "The PDF for this run is no longer available.")
    return FileResponse(run.file_path, media_type="application/pdf", filename=run.filename, content_disposition_type="inline")


def _stored_events(run_id: str, after: int = 0):
    with Session(get_engine()) as s:
        return s.exec(select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq > after)
                      .order_by(RunEvent.seq)).all()


def _run_finished(run_id: str) -> bool:
    with Session(get_engine()) as s:
        run = s.get(Run, run_id)
        return run is None or run.status in ("completed", "failed")


@router.get("/{run_id}/events")
async def run_events(run_id: str, request: Request):
    with Session(get_engine()) as s:
        _get_run(s, run_id)
    queue = broker.subscribe(run_id)  # subscribe before replay so nothing falls in the gap

    async def stream():
        last = 0
        try:
            # Replay everything stored, including an `override` recorded after the terminal event.
            ended = False
            for ev in _stored_events(run_id):
                last = ev.seq
                yield {"id": str(ev.seq), "event": ev.type, "data": ev.data_json}
                ended = ended or ev.type in TERMINAL_EVENTS
            if ended:
                return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    # Safety net: catch up from the table in case a live event was missed.
                    missed = _stored_events(run_id, after=last)
                    for e in missed:
                        last = e.seq
                        yield {"id": str(e.seq), "event": e.type, "data": e.data_json}
                        if e.type in TERMINAL_EVENTS:
                            return
                    if not missed and _run_finished(run_id) and not _stored_events(run_id, after=last):
                        return
                    continue
                if ev["seq"] <= last:
                    continue
                last = ev["seq"]
                yield {"id": str(ev["seq"]), "event": ev["type"], "data": ev["data"]}
                if ev["type"] in TERMINAL_EVENTS:
                    return
        finally:
            broker.unsubscribe(run_id, queue)

    return EventSourceResponse(stream(), ping=15)
