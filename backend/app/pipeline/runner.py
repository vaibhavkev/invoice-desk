"""Pipeline runner: executes the seven stages, persists stage records and events, writes the ledger.

``PipelineRunner.execute`` is synchronous (it runs in a worker thread under the API's lock), so the
same code path is used by the HTTP API and by the end-to-end sample tests.
"""
from __future__ import annotations

import json
import logging
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from sqlmodel import Session, func, select

from ..config import Settings
from ..extraction.cache import ExtractionCacheStore
from ..models import LedgerEntry, Run, RunEvent, RunStage
from ..refdata import RefData
from ..rules.rules import RuleContext
from ..util import new_run_id, utcnow_iso
from .events import EventBroker
from .stages.decision import run_decision
from .stages.doc_analysis import run_doc_analysis
from .stages.extraction import Extractor, run_extraction
from .stages.intake import run_intake
from .stages.integrity import run_integrity
from .stages.matching import run_matching
from .stages.rules import run_rules
from .types import STAGE_KEYS, STAGE_NAMES, STAGES, StageError, StageResult

log = logging.getLogger(__name__)

SUMMARY_FIELDS = ("id", "created_at", "filename", "sample_id", "file_hash", "status", "document_class", "decision",
                  "confidence", "vendor_name", "vendor_id", "invoice_number", "invoice_date", "currency", "net_total",
                  "gross_total", "po_number", "duration_ms", "current_stage", "error",
                  "override_decision", "override_note", "override_by", "override_at")


class OverrideRefused(Exception):
    pass


def run_summary(run: Run) -> Dict[str, Any]:
    out = {k: getattr(run, k) for k in SUMMARY_FIELDS}
    out["override_booking"] = json.loads(run.override_booking_json) if run.override_booking_json else None
    out["final_decision"] = run.override_decision or run.decision
    return out


def stage_record(st: RunStage) -> Dict[str, Any]:
    return {"key": st.key, "index": st.index, "name": st.name, "status": st.status, "started_at": st.started_at,
            "finished_at": st.finished_at, "duration_ms": st.duration_ms, "summary": st.summary,
            "warnings": json.loads(st.warnings_json or "[]"), "output": json.loads(st.output_json or "null")}


class _Abort(Exception):
    pass


class PipelineRunner:
    def __init__(self, engine, settings: Settings, broker: Optional[EventBroker] = None,
                 extractor: Optional[Extractor] = None):
        self.engine = engine
        self.settings = settings
        self.broker = broker
        self.extractor = extractor
        self.cache = ExtractionCacheStore(engine)

    # ------------------------------------------------------------------ creation
    def create_run(self, filename: str, data: Optional[bytes] = None, sample_id: Optional[str] = None,
                   use_cache: bool = False, file_path: Optional[Path] = None) -> str:
        run_id = new_run_id()
        if data is not None:
            self.settings.upload_dir.mkdir(parents=True, exist_ok=True)
            file_path = self.settings.upload_dir / f"{run_id}.pdf"
            file_path.write_bytes(data)
        with Session(self.engine) as s:
            s.add(Run(id=run_id, created_at=utcnow_iso(), filename=filename, sample_id=sample_id,
                      file_path=str(file_path) if file_path else None, use_cache=use_cache, status="queued"))
            for i, (key, name) in enumerate(STAGES, start=1):
                s.add(RunStage(run_id=run_id, key=key, index=i, name=name))
            s.commit()
        return run_id

    # ------------------------------------------------------------------ events
    def _emit(self, s: Session, run_id: str, type_: str, data: Dict[str, Any]) -> None:
        seq = (s.exec(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run_id)).one() or 0) + 1
        payload = json.dumps(data, default=str)
        s.add(RunEvent(run_id=run_id, seq=seq, type=type_, data_json=payload, ts=utcnow_iso()))
        s.commit()
        if self.broker is not None:
            self.broker.publish(run_id, {"seq": seq, "type": type_, "data": payload})

    def _stage_row(self, s: Session, run_id: str, key: str) -> RunStage:
        return s.exec(select(RunStage).where(RunStage.run_id == run_id, RunStage.key == key)).one()

    def _run_stage(self, s: Session, run: Run, key: str, fn: Callable[[], StageResult]) -> StageResult:
        st = self._stage_row(s, run.id, key)
        st.status, st.started_at = "running", utcnow_iso()
        run.current_stage = key
        s.add(st)
        s.add(run)
        s.commit()
        self._emit(s, run.id, "stage.started", {"run_id": run.id, "stage": stage_record(st)})
        t0 = time.perf_counter()
        error = None
        try:
            res = fn()
        except StageError as exc:
            error, output = exc.message, exc.output
        except Exception as exc:  # noqa: BLE001 - surfaced as a readable stage failure, never swallowed
            log.error("Unexpected error in stage %s of %s:\n%s", key, run.id, traceback.format_exc())
            error, output = f"Unexpected error in {STAGE_NAMES[key].lower()}: {type(exc).__name__}: {exc}", {}
        st.finished_at = utcnow_iso()
        st.duration_ms = int((time.perf_counter() - t0) * 1000)
        if error is not None:
            st.status, st.summary, st.output_json = "failed", error, json.dumps(output or {}, default=str)
            s.add(st)
            s.commit()
            self._emit(s, run.id, "stage.failed", {"run_id": run.id, "stage": stage_record(st), "error": error})
            raise _Abort(error)
        st.status, st.summary = res.status, res.summary
        st.warnings_json = json.dumps(res.warnings or [])
        st.output_json = json.dumps(res.output, default=str)
        s.add(st)
        s.commit()
        self._emit(s, run.id, "stage.completed", {"run_id": run.id, "stage": stage_record(st)})
        return res

    # ------------------------------------------------------------------ execution
    def execute(self, run_id: str) -> Dict[str, Any]:
        t_start = time.perf_counter()
        with Session(self.engine, expire_on_commit=False) as s:
            run = s.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            run.status = "running"
            s.add(run)
            s.commit()
            self._emit(s, run_id, "run.started", {"run_id": run_id, "created_at": run.created_at,
                                                  "filename": run.filename, "sample_id": run.sample_id})
            try:
                decision = self._pipeline(s, run)
            except _Abort as exc:
                run.status, run.error = "failed", str(exc)
                run.duration_ms = int((time.perf_counter() - t_start) * 1000)
                for st in s.exec(select(RunStage).where(RunStage.run_id == run_id,
                                                        RunStage.status == "pending")).all():
                    st.status = "skipped"
                    s.add(st)
                s.add(run)
                s.commit()
                self._emit(s, run_id, "run.failed", {"run_id": run_id, "error": run.error,
                                                     "summary": run_summary(run)})
                return run_summary(run)
            run.status = "completed"
            run.duration_ms = int((time.perf_counter() - t_start) * 1000)
            s.add(run)
            s.commit()
            self._emit(s, run_id, "run.completed", {"run_id": run_id, "summary": run_summary(run),
                                                    "decision": decision})
            return run_summary(run)

    def _pipeline(self, s: Session, run: Run) -> Dict[str, Any]:
        cfg = self.settings
        data: bytes = b""

        def intake():
            nonlocal data
            path = Path(run.file_path) if run.file_path else None
            if path is None or not path.exists():
                raise StageError(f"The file for this run could not be found ({run.file_path}).")
            data = path.read_bytes()
            return run_intake(data, run.filename, run.sample_id)

        res = self._run_stage(s, run, "intake", intake)
        file_hash = res.output["sha256"]
        run.file_hash = file_hash

        doc = self._run_stage(s, run, "doc_analysis",
                              lambda: run_doc_analysis(data, cfg.policy.scanned_chars_per_page)).output
        run.document_class = doc["document_class"]

        ext = self._run_stage(s, run, "extraction", lambda: run_extraction(
            data, file_hash, doc, cfg.extraction, cache=self.cache, use_cache=run.use_cache,
            extractor=self.extractor, confidence_floor=cfg.policy.confidence_floor)).output

        integ = self._run_stage(s, run, "integrity", lambda: run_integrity(ext["extraction"])).output
        n = integ["normalised"]
        run.vendor_name, run.invoice_number, run.invoice_date = n["vendor_name"], n["invoice_number"], n["invoice_date"]
        run.currency, run.net_total, run.gross_total = n["currency"], n["subtotal"], n["total"]
        run.confidence = integ["critical_confidence"]["min"]

        ref = RefData.from_db(s)
        match = self._run_stage(s, run, "matching", lambda: run_matching(n, ref)).output
        if match["vendor"]["matched"]:
            run.vendor_id = match["vendor"]["vendor_id"]
            run.vendor_name = match["vendor"]["legal_name"]
        run.po_number = match["po"].get("po_number")

        ctx = RuleContext(normalised=n, checks=integ["checks"], critical_confidence=integ["critical_confidence"],
                          vendor=match["vendor"], po=match["po"], ref=ref, policy=cfg.policy, today=cfg.today(),
                          file_hash=file_hash, exclude_run_id=run.id)
        rules_out = self._run_stage(s, run, "rules", lambda: run_rules(ctx)).output
        decision = self._run_stage(s, run, "decision", lambda: run_decision(rules_out, ctx)).output
        run.decision = decision["decision"]
        run.confidence = decision["confidence"]
        self._write_ledger(s, run, n, match, decision, file_hash)
        return decision

    def _write_ledger(self, s: Session, run: Run, n: Dict[str, Any], match: Dict[str, Any],
                      decision: Dict[str, Any], file_hash: str) -> None:
        """SPEC 4.7: insert when invoice_number is non-null OR decision is APPROVE (REJECT rows kept for audit)."""
        if not (n.get("invoice_number") or decision["decision"] == "APPROVE"):
            return
        s.add(_ledger_entry(run, n, match, decision["decision"], file_hash))
        s.commit()

    # ------------------------------------------------------------------ reviewer override
    def apply_override(self, run_id: str, decision: str, note: str, reviewer: str) -> Dict[str, Any]:
        """Record a reviewer's APPROVE / REJECT on a HOLD run and update its ledger row (brief E).

        The pipeline decision is kept as it was. APPROVE books the run exactly as the decision stage books an
        approved run; REJECT marks the row REJECT so R3 and R5 ignore it. Runs under the run lock."""
        with Session(self.engine, expire_on_commit=False) as s:
            run = s.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            if run.status != "completed" or run.decision != "HOLD":
                raise OverrideRefused(f"Only a HOLD run can be overridden; this run is "
                                      f"{run.decision or run.status}.")
            if run.override_decision:
                raise OverrideRefused(f"This run was already overridden to {run.override_decision} by "
                                      f"{run.override_by}.")
            n = json.loads(self._stage_row(s, run_id, "integrity").output_json)["normalised"]
            match = json.loads(self._stage_row(s, run_id, "matching").output_json)
            row = s.exec(select(LedgerEntry).where(LedgerEntry.run_id == run_id)).first()
            booking = None
            if decision == "APPROVE":
                # Same arithmetic as stages/decision.py, against the PO balance as it stands now.
                net, po = n.get("subtotal"), match["po"]
                remaining_after = None
                if po.get("matched") and net is not None:
                    ref = RefData.from_db(s)  # this run's own row is HOLD, so not yet in billed_net_to_date
                    pr = ref.po(po["po_number"])
                    if pr is not None:
                        remaining_after = round(round(pr.net_total - ref.billed_net_to_date(pr.po_number), 2) - net, 2)
                booking = {"po_number": po.get("po_number"), "net_amount": net, "gross_amount": n.get("total"),
                           "currency": (n.get("currency") or po.get("currency") or "") or None,
                           "po_remaining_after": remaining_after}
            if row is None:
                # Same insert condition as _write_ledger (SPEC 4.7).
                if n.get("invoice_number") or decision == "APPROVE":
                    s.add(_ledger_entry(run, n, match, decision, run.file_hash))
            else:
                row.decision = decision
                s.add(row)
            run.override_decision, run.override_note, run.override_by = decision, note, reviewer
            run.override_at = utcnow_iso()
            run.override_booking_json = json.dumps(booking) if booking else None
            s.add(run)
            s.commit()
            summary = run_summary(run)
            self._emit(s, run_id, "override", {"run_id": run_id, "summary": summary})
            return summary


def _ledger_entry(run: Run, n: Dict[str, Any], match: Dict[str, Any], decision: str,
                  file_hash: Optional[str]) -> LedgerEntry:
    return LedgerEntry(
        invoice_number=n.get("invoice_number"),
        vendor_id=match["vendor"].get("vendor_id") if match["vendor"].get("matched") else None,
        invoice_date=n.get("invoice_date"), currency=n.get("currency"), net_total=n.get("subtotal"),
        gross_total=n.get("total"), po_number=match["po"].get("po_number") if match["po"].get("matched") else None,
        decision=decision, file_hash=file_hash, processed_at=utcnow_iso(), source="run", run_id=run.id)


def stage_keys() -> list:
    return list(STAGE_KEYS)
