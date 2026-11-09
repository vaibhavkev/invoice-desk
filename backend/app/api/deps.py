"""Shared API plumbing: error type, samples catalogue, runner singleton and the run lock."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import anyio

from ..config import settings
from ..db import get_engine
from ..pipeline.events import broker
from ..pipeline.runner import PipelineRunner

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


_runner: Optional[PipelineRunner] = None
_run_lock: Optional[asyncio.Lock] = None


def get_runner() -> PipelineRunner:
    global _runner
    if _runner is None:
        _runner = PipelineRunner(get_engine(), settings, broker=broker)
    return _runner


def set_runner(runner: Optional[PipelineRunner]) -> None:
    """Tests inject a runner with a recorded-fixture extractor."""
    global _runner
    _runner = runner


def reset_run_lock() -> None:
    """Create the lock inside the serving event loop (called from the app lifespan)."""
    global _run_lock
    _run_lock = asyncio.Lock()


async def execute_run(run_id: str) -> None:
    """Background task: one run at a time, executed in a worker thread."""
    global _run_lock
    if _run_lock is None:
        _run_lock = asyncio.Lock()
    async with _run_lock:
        try:
            await anyio.to_thread.run_sync(get_runner().execute, run_id)
        except Exception:  # noqa: BLE001 - the runner records failures itself; this is a last resort log
            log.exception("Run %s crashed outside the stage machinery", run_id)


async def run_exclusive(fn, *args):
    """Run a synchronous DB writer in a worker thread under the run lock, so it never interleaves with a run."""
    global _run_lock
    if _run_lock is None:
        _run_lock = asyncio.Lock()
    async with _run_lock:
        return await anyio.to_thread.run_sync(fn, *args)


def load_samples() -> List[Dict[str, Any]]:
    path = Path(settings.data_dir) / "samples.json"
    if not path.exists():
        return []
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ApiError(500, "samples_invalid", f"data/samples.json is not valid JSON ({exc}).") from exc
    return sorted(items, key=lambda x: (x.get("demo_order", 999), x.get("id", "")))


def find_sample(sample_id: str) -> Dict[str, Any]:
    for s in load_samples():
        if s.get("id") == sample_id:
            return s
    raise ApiError(404, "sample_not_found", f"No sample with id {sample_id!r}.")


def sample_path(sample: Dict[str, Any]) -> Path:
    p = (Path(settings.data_dir) / sample["file"]).resolve()
    if not p.exists():
        raise ApiError(404, "sample_file_missing", f"The PDF for sample {sample['id']} is missing ({sample['file']}).")
    return p
