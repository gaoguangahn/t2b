"""RunRepository 接口与内存实现。"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from atestservice.runs.models import RunEventRecord, RunRecord, RunStatus


class RunRepository(ABC):
    @abstractmethod
    async def create_run(self, record: RunRecord) -> RunRecord: ...

    @abstractmethod
    async def update_run_status(
        self,
        user_id: str,
        run_id: str,
        status: RunStatus,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> RunRecord: ...

    @abstractmethod
    async def update_run_progress(
        self,
        user_id: str,
        run_id: str,
        *,
        current_stage: str | None = None,
        current_node: str | None = None,
    ) -> RunRecord: ...

    @abstractmethod
    async def append_event(
        self,
        user_id: str,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        stage: str | None = None,
        node: str | None = None,
    ) -> RunEventRecord: ...

    @abstractmethod
    async def get_run(self, user_id: str, run_id: str) -> RunRecord | None: ...

    @abstractmethod
    async def list_runs(self, user_id: str) -> list[RunRecord]: ...

    @abstractmethod
    async def list_events(self, user_id: str, run_id: str) -> list[RunEventRecord]: ...


class InMemoryRunRepository(RunRepository):
    """MVP 内存 RunRepository。"""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._events: dict[str, list[RunEventRecord]] = {}
        self._lock = asyncio.Lock()

    async def create_run(self, record: RunRecord) -> RunRecord:
        async with self._lock:
            self._runs[record.run_id] = record
            self._events.setdefault(record.run_id, [])
            return record

    async def update_run_status(
        self,
        user_id: str,
        run_id: str,
        status: RunStatus,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> RunRecord:
        async with self._lock:
            record = self._require_user_run(user_id, run_id)
            now = datetime.now(UTC)
            updates: dict[str, Any] = {"status": status}

            if status == RunStatus.RUNNING and record.started_at is None:
                updates["started_at"] = now

            if status in {RunStatus.DONE, RunStatus.ERROR, RunStatus.STOPPED}:
                updates["finished_at"] = now

            if result is not None:
                updates["result"] = result
            if error is not None:
                updates["error"] = error

            updated = record.model_copy(update=updates)
            self._runs[run_id] = updated
            return updated

    async def update_run_progress(
        self,
        user_id: str,
        run_id: str,
        *,
        current_stage: str | None = None,
        current_node: str | None = None,
    ) -> RunRecord:
        async with self._lock:
            record = self._require_user_run(user_id, run_id)
            updates: dict[str, Any] = {}

            if current_stage is not None:
                updates["current_stage"] = current_stage
            if current_node is not None:
                updates["current_node"] = current_node

            if not updates:
                return record

            updated = record.model_copy(update=updates)
            self._runs[run_id] = updated
            return updated

    async def append_event(
        self,
        user_id: str,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        stage: str | None = None,
        node: str | None = None,
    ) -> RunEventRecord:
        async with self._lock:
            self._require_user_run(user_id, run_id)
            events = self._events.setdefault(run_id, [])
            event = RunEventRecord(
                event_id=f"evt_{uuid.uuid4().hex}",
                run_id=run_id,
                user_id=user_id,
                seq=len(events) + 1,
                type=event_type,
                stage=stage,
                node=node,
                payload=payload or {},
            )
            events.append(event)
            return event

    async def get_run(self, user_id: str, run_id: str) -> RunRecord | None:
        async with self._lock:
            record = self._runs.get(run_id)
            if not record or record.user_id != user_id:
                return None
            return record

    async def list_runs(self, user_id: str) -> list[RunRecord]:
        async with self._lock:
            runs = [
                record for record in self._runs.values() if record.user_id == user_id
            ]
            return sorted(runs, key=lambda item: item.created_at, reverse=True)

    async def list_events(self, user_id: str, run_id: str) -> list[RunEventRecord]:
        async with self._lock:
            self._require_user_run(user_id, run_id)
            return list(self._events.get(run_id, []))

    def _require_user_run(self, user_id: str, run_id: str) -> RunRecord:
        record = self._runs.get(run_id)
        if not record or record.user_id != user_id:
            raise KeyError(f"run not found: {run_id}")
        return record
