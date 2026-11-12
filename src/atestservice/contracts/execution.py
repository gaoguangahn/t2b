"""Canonical execution facts; plugin booleans are normalized at the boundary."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator


class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "succeeded", "failed", "unknown"]
    message: str = ""
    completed_count: int | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_plugin_result(cls, value):
        if not isinstance(value, dict):
            return value
        status = value.get("execution_status") or value.get("status")
        if status is None:
            success = value.get("success", value.get("executed"))
            if success is None:
                raise ValueError("execution result has no status")
            status = "succeeded" if success else "failed"
        return {"status": status, "message": str(value.get("message") or ""),
                "completed_count": value.get("completed_count")}


def normalize_execution(result):
    return ExecutionResult.model_validate(result).model_dump(mode="json", exclude_none=True)


def execution_succeeded(result):
    return ExecutionResult.model_validate(result).status == "succeeded"
