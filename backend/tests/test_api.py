"""HTTP API and SSE replay (SPEC 5, 6), plus extraction cache semantics (SPEC 3.4)."""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import deps
from app.config import settings
from app.extraction.client import ExtractionError
from app.pipeline.events import broker
from app.pipeline.runner import PipelineRunner
from app.pipeline.types import STAGE_KEYS

from test_pipeline_samples import DATA, TODAY, _samples, recorded_extractor

pytestmark = pytest.mark.skipif(not (DATA / "samples.json").exists(), reason="data/samples.json not generated yet")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "api.db")
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "today_override", TODAY)
    monkeypatch.setattr(settings, "frontend_dist", tmp_path / "dist")
    by_hash = {hashlib.sha256((DATA / s["file"]).read_bytes()).hexdigest(): s["id"] for s in _samples()}
    with TestClient(__import__("app.main", fromlist=["app"]).app) as c:
        runner = PipelineRunner(db.get_engine(), settings, broker=broker, extractor=recorded_extractor(by_hash))
        deps.set_runner(runner)
        c.runner = runner
        yield c
    deps.set_runner(None)


def _sse(text: str):
    events, cur = [], {}
    for line in text.splitlines():
        if not line.strip():
            if cur:
                events.append(cur)
                cur = {}
            continue
        if line.startswith(":"):
            continue
        k, _, v = line.partition(":")
        cur[k] = v[1:] if v.startswith(" ") else v
    if cur:
        events.append(cur)
    return events


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"ok": True, "model": settings.extraction.model, "db": "ok"}


def test_policy(client):
    r = client.get("/api/policy")
    assert r.status_code == 200
    body = r.json()
    pol, ext = settings.policy, settings.extraction
    assert body["policy"]["tolerance_pct"] == pol.tolerance_pct
    assert body["policy"]["tolerance_abs_floor"] == pol.tolerance_abs_floor
    assert set(body["policy"]) == {"tolerance_pct", "tolerance_abs_floor", "confidence_floor", "date_window_days",
                                   "future_date_grace_days", "duplicate_date_window_days", "scanned_chars_per_page"}
    assert body["extraction"] == {"model": ext.model, "effort": ext.effort, "cache_fallback": ext.cache_fallback}


def test_samples_list_and_file(client):
    items = client.get("/api/samples").json()
    assert [s["id"] for s in items][:2] == ["HP", "EC1"]
    assert items[0]["url"] == "/api/samples/HP/file"
    r = client.get(items[0]["url"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:5] == b"%PDF-"


def test_run_sample_end_to_end_with_sse_replay(client):
    r = client.post("/api/runs", json={"sample_id": "HP"})
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    assert run_id.startswith("run_")

    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["status"] == "completed" and detail["decision"] == "APPROVE"
    assert detail["po_number"] == "PO-2026-0107" and detail["vendor_id"] == "V003"
    assert [s["key"] for s in detail["stages"]] == STAGE_KEYS
    assert [s["index"] for s in detail["stages"]] == list(range(1, 8))

    with client.stream("GET", f"/api/runs/{run_id}/events") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())
    events = _sse(body)
    types = [e["event"] for e in events]
    assert types[0] == "run.started" and types[-1] == "run.completed"
    assert types.count("stage.started") == 7 and types.count("stage.completed") == 7
    assert [int(e["id"]) for e in events] == list(range(1, len(events) + 1))
    final = json.loads(events[-1]["data"])
    assert final["decision"]["decision"] == "APPROVE" and final["summary"]["id"] == run_id

    listing = client.get("/api/runs").json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == run_id
    assert client.get("/api/runs?decision=HOLD").json()["total"] == 0
    assert client.get("/api/runs?q=meridian").json()["total"] == 1
    assert client.get(f"/api/runs/{run_id}/file").content[:5] == b"%PDF-"

    stats = client.get("/api/stats").json()
    assert stats["runs"] == 1 and stats["approve"] == 1 and stats["auto_approval_rate"] == 1.0

    po = next(p for p in client.get("/api/reference/pos").json() if p["po_number"] == "PO-2026-0107")
    assert po["billed_net_to_date"] == 4800.0 and po["remaining_net"] == 0.0
    assert po["invoices"][0]["source"] == "run" and len(po["lines"]) == 2
    ledger = client.get("/api/reference/ledger").json()
    assert ledger[0]["run_id"] == run_id


def test_upload_multipart(client):
    pdf = (DATA / "samples" / "EC3_variance_apex_AIC-26-27-0931.pdf").read_bytes()
    r = client.post("/api/runs", files={"file": ("my invoice.pdf", pdf, "application/pdf")})
    assert r.status_code == 202
    d = client.get(f"/api/runs/{r.json()['run_id']}").json()
    assert d["filename"] == "my invoice.pdf" and d["decision"] == "HOLD" and d["sample_id"] is None


def test_upload_non_pdf_fails_at_intake(client):
    r = client.post("/api/runs", files={"file": ("notes.txt", b"hello", "text/plain")})
    d = client.get(f"/api/runs/{r.json()['run_id']}").json()
    assert d["status"] == "failed" and "not a PDF" in d["error"]
    assert d["stages"][0]["status"] == "failed" and all(s["status"] == "skipped" for s in d["stages"][1:])


def test_errors_use_contract_shape(client):
    r = client.get("/api/runs/run_nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "run_not_found"
    r = client.post("/api/runs", json={"sample_id": "NOPE"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "sample_not_found"
    r = client.post("/api/runs", json={})
    assert r.status_code == 400 and r.json()["error"]["code"] == "sample_id_missing"
    assert client.get("/api/unknown").json()["error"]["code"] == "not_found"


def test_reset_restores_ledger_and_clears_runs(client):
    client.post("/api/runs", json={"sample_id": "EC2a"})
    assert client.post("/api/runs", json={"sample_id": "EC2b"}).status_code == 202
    assert client.get("/api/runs?decision=HOLD").json()["total"] == 1
    r = client.post("/api/admin/reset", json={"clear_runs": True})
    assert r.json()["ok"] is True
    assert client.get("/api/runs").json()["total"] == 0
    assert all(row["source"] == "seed" for row in client.get("/api/reference/ledger").json())
    # fresh ledger: EC2b alone approves and consumes the PO
    rid = client.post("/api/runs", json={"sample_id": "EC2b"}).json()["run_id"]
    assert client.get(f"/api/runs/{rid}").json()["decision"] == "APPROVE"


def test_spa_fallback(client, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (dist / "assets" / "a.js").write_text("console.log(1)", encoding="utf-8")
    assert client.get("/dashboard").text == "<html>app</html>"
    assert client.get("/runs/run_x").text == "<html>app</html>"
    assert client.get("/assets/a.js").text == "console.log(1)"
    assert client.get("/api/nope").status_code == 404


# ---------------------------------------------------------------- extraction cache
def test_api_error_falls_back_to_cache_with_warn(client):
    rid = client.post("/api/runs", json={"sample_id": "HP"}).json()["run_id"]  # fills the cache
    client.post("/api/admin/reset", json={"clear_runs": True})

    def broken(*_a, **_k):
        raise ExtractionError("connection refused")

    client.runner.extractor = broken
    rid = client.post("/api/runs", json={"sample_id": "HP"}).json()["run_id"]
    d = client.get(f"/api/runs/{rid}").json()
    ext = d["stages"][2]
    assert d["status"] == "completed" and d["decision"] == "APPROVE"
    assert ext["status"] == "warn" and ext["output"]["from_cache"] is True
    assert ext["summary"].startswith("Used cached extraction (API error: connection refused)")


def test_api_error_without_cache_fails_readably(client):
    def broken(*_a, **_k):
        raise ExtractionError("The Anthropic API returned 529: overloaded")

    client.runner.extractor = broken
    rid = client.post("/api/runs", json={"sample_id": "EC6"}).json()["run_id"]
    d = client.get(f"/api/runs/{rid}").json()
    assert d["status"] == "failed" and "529" in d["error"]
    assert d["stages"][2]["status"] == "failed"


@pytest.mark.parametrize("error", [TypeError("Could not resolve authentication method"),
                                   ExtractionError("The model declined to read this document")])
def test_any_extraction_exception_falls_back_to_cache(client, error):
    client.post("/api/runs", json={"sample_id": "HP"})
    client.post("/api/admin/reset", json={"clear_runs": True})

    def broken(*_a, **_k):
        raise error

    client.runner.extractor = broken
    rid = client.post("/api/runs", json={"sample_id": "HP"}).json()["run_id"]
    d = client.get(f"/api/runs/{rid}").json()
    ext = d["stages"][2]
    assert d["status"] == "completed" and ext["status"] == "warn" and ext["output"]["from_cache"] is True
    assert ext["summary"].startswith("Used cached extraction (")


def test_unexpected_exception_without_cache_fails_readably(client):
    def broken(*_a, **_k):
        raise TypeError("Could not resolve authentication method")

    client.runner.extractor = broken
    rid = client.post("/api/runs", json={"sample_id": "EC6"}).json()["run_id"]
    d = client.get(f"/api/runs/{rid}").json()
    assert d["status"] == "failed" and "Could not resolve authentication method" in d["error"]


def test_real_client_with_missing_key_falls_back_to_cache(client, monkeypatch):
    client.post("/api/runs", json={"sample_id": "HP"})
    client.post("/api/admin/reset", json={"clear_runs": True})
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr("app.extraction.client._client", None)
    client.runner.extractor = None
    rid = client.post("/api/runs", json={"sample_id": "HP"}).json()["run_id"]
    d = client.get(f"/api/runs/{rid}").json()
    assert d["status"] == "completed" and d["stages"][2]["status"] == "warn", d["stages"][2]


def test_warm_cache_stores_every_sample(tmp_path, capsys):
    from sqlmodel import Session, SQLModel, select

    from app.models import ExtractionCache
    from tools import warm_cache

    engine = db.make_engine(tmp_path / "warm.db")
    SQLModel.metadata.create_all(engine)
    by_hash = {hashlib.sha256((DATA / s["file"]).read_bytes()).hexdigest(): s["id"] for s in _samples()}
    assert warm_cache.main(set(), extractor=recorded_extractor(by_hash), engine=engine) == 0
    with Session(engine) as s:
        assert {r.file_hash for r in s.exec(select(ExtractionCache)).all()} == set(by_hash)
    out = capsys.readouterr().out
    assert all(f"{sid}: " in out for sid in by_hash.values()) and "failed=0" in out


def test_use_cache_flag_reads_cache_without_calling_api(client):
    client.post("/api/runs", json={"sample_id": "HP"})
    client.post("/api/admin/reset", json={"clear_runs": True})
    calls = []

    def spy(*a, **k):
        calls.append(1)
        raise AssertionError("API must not be called")

    client.runner.extractor = spy
    rid = client.post("/api/runs", json={"sample_id": "HP", "use_cache": True}).json()["run_id"]
    d = client.get(f"/api/runs/{rid}").json()
    assert d["decision"] == "APPROVE" and d["stages"][2]["output"]["from_cache"] is True and not calls


# ---- reviewer override (brief E) ----------------------------------------------------------
def _po(client, po_number):
    return next(p for p in client.get("/api/reference/pos").json() if p["po_number"] == po_number)


def _ledger_row(client, run_id):
    return next((r for r in client.get("/api/reference/ledger").json() if r["run_id"] == run_id), None)


def test_override_hold_to_approve_books_it_and_later_runs_see_it(client):
    a = client.post("/api/runs", json={"sample_id": "EC2a"}).json()["run_id"]
    b = client.post("/api/runs", json={"sample_id": "EC2b"}).json()["run_id"]
    hold = client.get(f"/api/runs/{b}").json()
    assert hold["decision"] == "HOLD" and hold["final_decision"] == "HOLD" and hold["override_decision"] is None
    po_number = hold["po_number"]
    before = _po(client, po_number)
    assert _ledger_row(client, b)["decision"] == "HOLD"

    r = client.post(f"/api/runs/{b}/override", json={"decision": "APPROVE", "note": "Requester confirmed the PO top-up."})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["decision"] == "HOLD" and out["final_decision"] == "APPROVE"
    assert out["override_by"] == "AP reviewer" and out["override_note"] == "Requester confirmed the PO top-up."
    assert out["override_at"]
    bk = out["override_booking"]
    assert bk["po_number"] == po_number and bk["net_amount"] == hold["net_total"] and bk["gross_amount"] == hold["gross_total"]
    assert bk["po_remaining_after"] == round(before["remaining_net"] - hold["net_total"], 2)

    # The pipeline's own decision stage output is untouched.
    detail = client.get(f"/api/runs/{b}").json()
    assert next(s for s in detail["stages"] if s["key"] == "decision")["output"]["decision"] == "HOLD"
    assert detail["final_decision"] == "APPROVE"

    # Ledger row flipped, so cumulative billing includes EC2b.
    assert _ledger_row(client, b)["decision"] == "APPROVE"
    after = _po(client, po_number)
    assert after["billed_net_to_date"] == round(before["billed_net_to_date"] + hold["net_total"], 2)
    assert after["remaining_net"] == bk["po_remaining_after"]

    # A later run on the same PO sees the billed amount (R5) and the approved row for duplicates (R3).
    c = client.post("/api/runs", json={"sample_id": "EC2b"}).json()["run_id"]
    again = client.get(f"/api/runs/{c}").json()
    match = next(s for s in again["stages"] if s["key"] == "matching")["output"]["po"]
    assert match["billed_net_to_date"] == after["billed_net_to_date"]
    rules = {x["code"]: x for x in next(s for s in again["stages"] if s["key"] == "rules")["output"]["results"]}
    assert rules["R3"]["passed"] is False and again["decision"] == "REJECT"

    # Stats and the list use the final decision.
    stats = client.get("/api/stats").json()
    assert (stats["approve"], stats["hold"], stats["reject"]) == (2, 0, 1)
    assert stats["auto_approval_rate"] == round(1 / 3, 3)
    approved = client.get("/api/runs?decision=APPROVE").json()
    assert {x["id"] for x in approved["items"]} == {a, b}
    assert client.get("/api/runs?decision=HOLD").json()["total"] == 0

    # The override was recorded as a run event and replays after run.completed.
    evs = _sse(client.get(f"/api/runs/{b}/events").text)
    assert [e["event"] for e in evs][-2:] == ["run.completed", "override"]
    assert json.loads(evs[-1]["data"])["summary"]["final_decision"] == "APPROVE"


def test_override_hold_to_reject_excludes_row(client):
    client.post("/api/runs", json={"sample_id": "EC2a"})
    b = client.post("/api/runs", json={"sample_id": "EC2b"}).json()["run_id"]
    before = _po(client, client.get(f"/api/runs/{b}").json()["po_number"])
    r = client.post(f"/api/runs/{b}/override", json={"decision": "REJECT", "note": "Vendor billed twice for October.",
                                                     "reviewer": "  Priya  "})
    assert r.status_code == 200 and r.json()["override_by"] == "Priya" and r.json()["override_booking"] is None
    assert _ledger_row(client, b)["decision"] == "REJECT"
    assert _po(client, before["po_number"])["billed_net_to_date"] == before["billed_net_to_date"]


def test_override_refusals(client):
    client.post("/api/runs", json={"sample_id": "EC2a"})
    b = client.post("/api/runs", json={"sample_id": "EC2b"}).json()["run_id"]
    hp = client.post("/api/runs", json={"sample_id": "HP"}).json()["run_id"]
    ok = {"decision": "APPROVE", "note": "Confirmed with the requester by phone."}

    r = client.post(f"/api/runs/{hp}/override", json=ok)  # APPROVE run
    assert r.status_code == 409 and r.json()["error"]["code"] == "override_not_allowed"
    for bad in ({"decision": "HOLD", "note": "x" * 20}, {"decision": "APPROVE", "note": "too short"},
                {"decision": "APPROVE", "note": "x" * 501}, {"note": "x" * 20}):
        r = client.post(f"/api/runs/{b}/override", json=bad)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", bad
    assert client.post("/api/runs/nope/override", json=ok).status_code == 404

    assert client.post(f"/api/runs/{b}/override", json=ok).status_code == 200
    r = client.post(f"/api/runs/{b}/override", json=dict(ok, decision="REJECT"))  # second override
    assert r.status_code == 409 and "already overridden" in r.json()["error"]["message"]
    assert client.get(f"/api/runs/{b}").json()["final_decision"] == "APPROVE"
