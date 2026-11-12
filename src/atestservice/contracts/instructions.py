"""Instruction and verification boundaries shared by parsing and execution."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from atestservice.contracts.action import ActionType

# Semantic requirements shared by exploration enforcement and script coverage checks.
REQUIRED_ACTION_TYPES: dict[str, ActionType] = {
    "app_launch": "start_app", "app_stop": "stop_app",
    "system_home": "home", "multitask": "open_multitask",
}

InstructionKind = Literal["ui", "app_launch", "app_stop", "system_home", "multitask"]


class Instruction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    kind: InstructionKind = Field(
        default="ui", description="语义类别。返回应用首页、返回上一页或关闭面板属于 ui；system_home 只指系统桌面，app_stop 只指明确停止应用。"
    )
    parameters: dict[str, str | int | float] = Field(default_factory=dict)


class VerificationAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str = Field(min_length=1)
    instruction_id: str | None = None
    position: Literal["before", "after"] = "after"
