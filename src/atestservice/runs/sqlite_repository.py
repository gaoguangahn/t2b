"""SQLite RunRepository implementation."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atestservice.runs.models import RunEventRecord, RunRecord, RunStatus
from atestservice.runs.repository import RunRepository


class SQLiteRunRepository(RunRepository):
    """本地 SQLite RunRepository。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._initialize()

    async def create_run(self, record: RunRecord) -> RunRecord:
        async with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO runs (
                        run_id, user_id, plugin_session_id, plugin_instance_id,
                        editable_text, input_payload, status, current_stage, current_node,
                        created_at, started_at, finished_at, result, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.run_id,
                        record.user_id,
                        record.plugin_session_id,
                        record.plugin_instance_id,
                        record.editable_text,
                        _dump_json(record.input_payload),
                        record.status,
                        record.current_stage,
                        record.current_node,
                        _dump_datetime(record.created_at),
                        _dump_datetime(record.started_at),
                        _dump_datetime(record.finished_at),
                        _dump_json(record.result),
                        record.error,
                    ),
                )
                conn.commit()
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
            with self._connect() as conn:
                record = self._require_user_run(conn, user_id, run_id)
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
                conn.execute(
                    """
                    UPDATE runs SET
                        status = ?, started_at = ?, finished_at = ?, result = ?, error = ?
                    WHERE run_id = ? AND user_id = ?
                    """,
                    (
                        updated.status,
                        _dump_datetime(updated.started_at),
                        _dump_datetime(updated.finished_at),
                        _dump_json(updated.result),
                        updated.error,
                        run_id,
                        user_id,
                    ),
                )
                conn.commit()
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
            with self._connect() as conn:
                record = self._require_user_run(conn, user_id, run_id)
                updates: dict[str, Any] = {}

                if current_stage is not None:
                    updates["current_stage"] = current_stage
                if current_node is not None:
                    updates["current_node"] = current_node

                if not updates:
                    return record

                updated = record.model_copy(update=updates)
                conn.execute(
                    """
                    UPDATE runs SET current_stage = ?, current_node = ?
                    WHERE run_id = ? AND user_id = ?
                    """,
                    (
                        updated.current_stage,
                        updated.current_node,
                        run_id,
                        user_id,
                    ),
                )
                conn.commit()
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
            with self._connect() as conn:
                self._require_user_run(conn, user_id, run_id)
                row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM run_events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                seq = int(row["next_seq"])
                event = RunEventRecord(
                    event_id=f"evt_{uuid.uuid4().hex}",
                    run_id=run_id,
                    user_id=user_id,
                    seq=seq,
                    type=event_type,
                    stage=stage,
                    node=node,
                    payload=payload or {},
                )
                conn.execute(
                    """
                    INSERT INTO run_events (
                        event_id, run_id, user_id, seq, type, stage, node, payload, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.run_id,
                        event.user_id,
                        event.seq,
                        event.type,
                        event.stage,
                        event.node,
                        _dump_json(event.payload),
                        _dump_datetime(event.created_at),
                    ),
                )
                conn.commit()
                return event

    async def get_run(self, user_id: str, run_id: str) -> RunRecord | None:
        async with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM runs WHERE run_id = ? AND user_id = ?",
                    (run_id, user_id),
                ).fetchone()
                return _row_to_run(row) if row else None

    async def list_runs(self, user_id: str) -> list[RunRecord]:
        async with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM runs WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,),
                ).fetchall()
                return [_row_to_run(row) for row in rows]

    async def list_events(self, user_id: str, run_id: str) -> list[RunEventRecord]:
        async with self._lock:
            with self._connect() as conn:
                self._require_user_run(conn, user_id, run_id)
                rows = conn.execute(
                    "SELECT * FROM run_events WHERE run_id = ? ORDER BY seq ASC",
                    (run_id,),
                ).fetchall()
                return [_row_to_event(row) for row in rows]

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    plugin_session_id TEXT NOT NULL,
                    plugin_instance_id TEXT,
                    editable_text TEXT NOT NULL DEFAULT '',
                    input_payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_stage TEXT,
                    current_node TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    result TEXT,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS run_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    stage TEXT,
                    node TEXT,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (run_id, seq),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_run_events_run_seq
                ON run_events (run_id, seq);

                CREATE INDEX IF NOT EXISTS idx_run_events_user_created
                ON run_events (user_id, created_at);

                DROP TABLE IF EXISTS run_artifacts;
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _require_user_run(
        conn: sqlite3.Connection, user_id: str, run_id: str
    ) -> RunRecord:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = ? AND user_id = ?",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"run not found: {run_id}")
        return _row_to_run(row)


def _row_to_run(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        run_id=row["run_id"],
        user_id=row["user_id"],
        plugin_session_id=row["plugin_session_id"],
        plugin_instance_id=row["plugin_instance_id"],
        editable_text=_row_value(row, "editable_text") or str(
            _load_json(row["input_payload"]).get("editableText") or ""
        ),
        input_payload=_load_json(row["input_payload"]),
        status=RunStatus(row["status"]),
        current_stage=row["current_stage"],
        current_node=row["current_node"],
        created_at=_load_datetime(row["created_at"]),
        started_at=_load_datetime(row["started_at"]),
        finished_at=_load_datetime(row["finished_at"]),
        result=_load_json(row["result"]),
        error=row["error"],
    )


def _row_to_event(row: sqlite3.Row) -> RunEventRecord:
    return RunEventRecord(
        event_id=row["event_id"],
        run_id=row["run_id"],
        user_id=row["user_id"],
        seq=row["seq"],
        type=row["type"],
        stage=row["stage"],
        node=row["node"],
        payload=_load_json(row["payload"]) or {},
        created_at=_load_datetime(row["created_at"]),
    )


def _row_value(row: sqlite3.Row, key: str) -> Any:
    return row[key] if key in row.keys() else None


def _dump_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _load_json(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def _dump_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _load_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)
