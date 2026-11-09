"""In-process pub/sub keyed by run_id (SPEC 7). Thread-safe publish into asyncio queues."""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, List, Tuple

TERMINAL_EVENTS = ("run.completed", "run.failed")


class EventBroker:
    def __init__(self) -> None:
        self._subs: Dict[str, List[Tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
        self._lock = threading.Lock()

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        with self._lock:
            self._subs.setdefault(run_id, []).append((loop, q))
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        with self._lock:
            subs = self._subs.get(run_id, [])
            self._subs[run_id] = [(l, x) for l, x in subs if x is not q]
            if not self._subs[run_id]:
                self._subs.pop(run_id, None)

    def publish(self, run_id: str, event: Dict[str, Any]) -> None:
        """Callable from any thread."""
        with self._lock:
            subs = list(self._subs.get(run_id, []))
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, event)
            except RuntimeError:  # loop closed: subscriber is gone
                self.unsubscribe(run_id, q)


broker = EventBroker()
