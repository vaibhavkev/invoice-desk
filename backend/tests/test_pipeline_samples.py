"""End-to-end: all eight samples through the real runner, with recorded extractions (SPEC 9).

The ledger is reset, then samples run in demo_order (EC2b depends on EC2a having been approved).
Each run must match samples.json's expected_decision AND expected_rule_failures.
A separate ``live`` test hits the real API for HP only: ``pytest -m live``.
"""
from __future__ import annotations

import dataclasses
import json
import os
from datetime import date
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.config import settings as app_settings
from app.db import make_engine
from app.extraction.client import ExtractionResult
from app.extraction.schema import InvoiceExtraction
from app.models import LedgerEntry, RunEvent, RunStage
from app.pipeline.runner import PipelineRunner
from app.seed import reseed_ledger, seed_if_empty
from app.pipeline.types import STAGE_KEYS
from sqlmodel import SQLModel

from conftest import FIXTURES

DATA = app_settings.data_dir
EXTRACTIONS = FIXTURES / "extractions"
TODAY = date(2026, 11, 2)

pytestmark = pytest.mark.skipif(not (DATA / "samples.json").exists(), reason="data/samples.json not generated yet")


def _samples():
    if not (DATA / "samples.json").exists():
        return []
    return sorted(json.loads((DATA / "samples.json").read_text(encoding="utf-8")), key=lambda s: s["demo_order"])


def recorded_extractor(sample_id_by_hash):
    def extractor(pdf_bytes, text_layer, document_class, cfg):
        import hashlib
        sid = sample_id_by_hash[hashlib.sha256(pdf_bytes).hexdigest()]
        data = json.loads((EXTRACTIONS / f"{sid}.json").read_text(encoding="utf-8"))
        return ExtractionResult(extraction=InvoiceExtraction.model_validate(data), model=cfg.model,
                                usage={"input_tokens": 0, "output_tokens": 0}, latency_ms=1)
    return extractor


@pytest.fixture
def env(tmp_path):
    engine = make_engine(tmp_path / "test.db")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        assert seed_if_empty(s, DATA)
        reseed_ledger(s, DATA)
    settings = dataclasses.replace(app_settings, db_path=tmp_path / "test.db", upload_dir=tmp_path / "uploads",
                                   today_override=TODAY)
    import hashlib
    by_hash = {hashlib.sha256((DATA / s["file"]).read_bytes()).hexdigest(): s["id"] for s in _samples()}
    runner = PipelineRunner(engine, settings, extractor=recorded_extractor(by_hash))
    return engine, runner


def _detail(engine, run_id):
    with Session(engine) as s:
        stages = {st.key: st for st in s.exec(select(RunStage).where(RunStage.run_id == run_id)).all()}
        events = s.exec(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)).all()
    return stages, events


def test_all_samples_in_demo_order(env):
    engine, runner = env
    samples = _samples()
    assert len(samples) == 8
    mismatches = []
    for smp in samples:
        assert (EXTRACTIONS / f"{smp['id']}.json").exists(), f"missing recorded extraction for {smp['id']}"
        run_id = runner.create_run(Path(smp["file"]).name, sample_id=smp["id"], file_path=DATA / smp["file"])
        summary = runner.execute(run_id)
        stages, events = _detail(engine, run_id)
        assert summary["status"] == "completed", (smp["id"], summary["error"])
        rules = json.loads(stages["rules"].output_json)
        failed = sorted(rules["failed_hold"] + rules["failed_reject"], key=lambda c: int(c[1:]))
        expected = sorted(smp["expected_rule_failures"], key=lambda c: int(c[1:]))
        if summary["decision"] != smp["expected_decision"] or failed != expected:
            mismatches.append(f"{smp['id']}: got {summary['decision']} {failed}, "
                              f"expected {smp['expected_decision']} {expected}")
        # every stage emitted started + completed, events are sequential, run ends with run.completed
        types = [e.type for e in events]
        assert types[0] == "run.started" and types[-1] == "run.completed"
        assert types.count("stage.started") == 7 and types.count("stage.completed") == 7
        assert [e.seq for e in events] == list(range(1, len(events) + 1))
        assert all(stages[k].status in ("done", "warn") for k in STAGE_KEYS)
    assert not mismatches, "\n".join(mismatches)


def test_split_po_scenario_details(env):
    engine, runner = env
    by_id = {s["id"]: s for s in _samples()}
    outs = {}
    for sid in ("EC2a", "EC2b"):
        smp = by_id[sid]
        run_id = runner.create_run(Path(smp["file"]).name, sample_id=sid, file_path=DATA / smp["file"])
        runner.execute(run_id)
        stages, _ = _detail(engine, run_id)
        outs[sid] = json.loads(stages["decision"].output_json)
    assert outs["EC2a"]["decision"] == "APPROVE"
    assert outs["EC2a"]["booking"]["po_remaining_after"] == 4000.0
    assert outs["EC2b"]["decision"] == "HOLD"
    assert outs["EC2b"]["next_action"]["owner"] == "requester"
    with Session(engine) as s:
        rows = s.exec(select(LedgerEntry).where(LedgerEntry.source == "run")).all()
    assert {(r.invoice_number, r.decision) for r in rows} == {("HFM-2026-104", "APPROVE"), ("HFM-2026-118", "HOLD")}


def test_split_po_on_fresh_ledger_approves_and_consumes(env):
    engine, runner = env
    smp = next(s for s in _samples() if s["id"] == "EC2b")
    run_id = runner.create_run(Path(smp["file"]).name, sample_id="EC2b", file_path=DATA / smp["file"])
    assert runner.execute(run_id)["decision"] == "APPROVE"
    stages, _ = _detail(engine, run_id)
    d = json.loads(stages["decision"].output_json)
    assert d["booking"]["po_remaining_after"] == 0.0 and "fully consumed" in d["explanation"]


def test_rerun_same_sample_is_a_duplicate(env):
    engine, runner = env
    smp = next(s for s in _samples() if s["id"] == "HP")
    first = runner.execute(runner.create_run("HP.pdf", sample_id="HP", file_path=DATA / smp["file"]))
    second = runner.execute(runner.create_run("HP.pdf", sample_id="HP", file_path=DATA / smp["file"]))
    assert (first["decision"], second["decision"]) == ("APPROVE", "REJECT")


def test_failed_stage_stops_run_and_skips_rest(env, tmp_path):
    engine, runner = env
    bad = tmp_path / "not_a_pdf.pdf"
    bad.write_bytes(b"hello")
    summary = runner.execute(runner.create_run("not_a_pdf.pdf", file_path=bad))
    assert summary["status"] == "failed" and "not a PDF" in summary["error"]
    stages, events = _detail(engine, summary["id"])
    assert stages["intake"].status == "failed"
    assert all(stages[k].status == "skipped" for k in STAGE_KEYS[1:])
    assert [e.type for e in events] == ["run.started", "stage.started", "stage.failed", "run.failed"]


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set")
def test_live_extraction_hp(env):
    """Real API call for HP only."""
    engine, runner = env
    runner.extractor = None
    smp = next(s for s in _samples() if s["id"] == "HP")
    summary = runner.execute(runner.create_run("HP.pdf", sample_id="HP", file_path=DATA / smp["file"]))
    assert summary["status"] == "completed", summary["error"]
    assert summary["decision"] == "APPROVE"
    stages, _ = _detail(engine, summary["id"])
    ext = json.loads(stages["extraction"].output_json)
    assert ext["from_cache"] is False and ext["usage"]["input_tokens"] > 0
