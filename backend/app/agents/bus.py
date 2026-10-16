"""In-memory SSE event bus: one asyncio.Queue per run."""

from __future__ import annotations

import asyncio
from typing import Any

from app.agents.schema import AgentEvent

# Sentinel placed on the queue when a run finishes (after run_done).
RUN_COMPLETE = object()


class EventBus:
    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[AgentEvent | object]] = {}
        self._history: dict[str, list[AgentEvent]] = {}
        self._lock = asyncio.Lock()

    async def create_run(self, run_id: str) -> None:
        async with self._lock:
            if run_id not in self._queues:
                self._queues[run_id] = asyncio.Queue()
            if run_id not in self._history:
                self._history[run_id] = []

    async def publish(self, event: AgentEvent) -> None:
        async with self._lock:
            q = self._queues.get(event.run_id)
            hist = self._history.get(event.run_id)
            if hist is not None:
                hist.append(event)
        if q is not None:
            await q.put(event)

    async def complete(self, run_id: str) -> None:
        q = self._queues.get(run_id)
        if q is not None:
            await q.put(RUN_COMPLETE)

    async def subscribe(self, run_id: str) -> asyncio.Queue[AgentEvent | object] | None:
        async with self._lock:
            return self._queues.get(run_id)

    def history(self, run_id: str) -> list[AgentEvent]:
        return list(self._history.get(run_id, []))

    def get_run_meta(self, run_id: str) -> dict[str, Any] | None:
        if run_id not in self._queues and run_id not in self._history:
            return None
        return {"run_id": run_id, "event_count": len(self._history.get(run_id, []))}


# Process-wide bus for the FastAPI app
bus = EventBus()
