"""Run 数据结构。"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    STOPPED = "stopped"


class RunRecord(BaseModel):
    run_id: str
    user_id: str
    plugin_session_id: str
    plugin_instance_id: str
    editable_text: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    status: RunStatus = RunStatus.PENDING
    current_stage: str | None = None
    current_node: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class RunEventRecord(BaseModel):
    event_id: str
    run_id: str
    user_id: str
    seq: int
    type: str
    stage: str | None = None
    node: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class PrepareRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pluginSessionId: str
    input: str

    @model_validator(mode="after")
    def validate_input(self) -> PrepareRunRequest:
        self.pluginSessionId = self.pluginSessionId.strip()
        self.input = self.input.strip()
        if not self.pluginSessionId:
            raise ValueError("pluginSessionId is empty")
        if not self.input:
            raise ValueError("input is empty")
        return self


class PrepareRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    editableText: str


class CreateRunRequest(BaseModel):
    pluginSessionId: str
    editableText: str
    framework: str = "dynamic_framework"

    @model_validator(mode="after")
    def validate_prepared_input(self) -> CreateRunRequest:
        self.editableText = self.editableText.strip()
        if not self.editableText:
            raise ValueError("editableText is empty")
        return self


class StopRunResponse(BaseModel):
    runId: str
    status: RunStatus
