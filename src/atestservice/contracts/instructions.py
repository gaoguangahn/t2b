"""Instruction and verification boundaries shared by parsing and execution."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Instruction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_kind(cls, value):
        """Read old cases/bundles without retaining the retired classification."""
        if isinstance(value, dict) and "kind" in value:
            return {key: item for key, item in value.items() if key != "kind"}
        return value


class VerificationAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str = Field(min_length=1)
    instruction_id: str | None = None
    position: Literal["before", "after"] = "after"
