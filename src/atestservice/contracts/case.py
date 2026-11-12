"""Shared case contracts. No runtime, LLM, or plugin dependencies."""

from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from atestservice.contracts.instructions import Instruction, VerificationAnchor


class CaseStep(BaseModel):
    """A business-goal block for single-pass exploration and later script generation."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="目标块 id，例如 step_001。")
    goal: str = Field(description="目标块描述，使用中文。")
    repeat: int = Field(default=1, ge=1, description="脚本生成时该目标块的重复次数；探索阶段只执行一次。")
    instructions: list[Instruction] = Field(default_factory=list, description="这一轮的有序操作指令，不含业务验证。")

    @model_validator(mode="before")
    @classmethod
    def normalize_input(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "goal" not in data:
            for legacy_key in ("text", "instruction", "description"):
                if legacy_key in data:
                    data["goal"] = data.pop(legacy_key)
                    break
        data.setdefault("repeat", 1)
        return data

    @model_validator(mode="after")
    def validate_step(self) -> CaseStep:
        self.id = self.id.strip()
        self.goal = self.goal.strip()
        if not self.id:
            raise ValueError("case step id is empty")
        if not self.goal:
            raise ValueError("case step goal is empty")
        if not self.instructions:
            self.instructions = [Instruction(id=f"{self.id}_instruction", text=self.goal)]
        return self


class CaseVerification(BaseModel):
    """A verification goal for later script generation, not an exploration action."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="验证目标 id，例如 verify_001。")
    goal: str = Field(description="验证目标描述，使用中文。")
    anchor: VerificationAnchor
    scope: str = Field(default="each_iteration", pattern="^(each_iteration|outside_repeat)$")

    @model_validator(mode="before")
    @classmethod
    def normalize_input(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "goal" not in data:
            for legacy_key in ("text", "instruction", "description"):
                if legacy_key in data:
                    data["goal"] = data.pop(legacy_key)
                    break
        if "step_id" not in data:
            for legacy_key in ("after_step_id", "after"):
                if legacy_key in data:
                    data["step_id"] = data.pop(legacy_key)
                    break
        legacy_step = data.pop("step_id", None)
        if legacy_step:
            if data.get("anchor") and data["anchor"]["step_id"] != legacy_step:
                raise ValueError("verification step and anchor disagree")
            data.setdefault("anchor", {"step_id": legacy_step})
        return data

    @property
    def step_id(self):
        return self.anchor.step_id if self.anchor else None

    @model_validator(mode="after")
    def validate_verification(self) -> CaseVerification:
        self.id = self.id.strip()
        self.goal = self.goal.strip()
        if not self.id:
            raise ValueError("verification id is empty")
        if not self.goal:
            raise ValueError("verification goal is empty")
        return self


class CaseSpec(BaseModel):
    """Minimal case spec produced from a user case description."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2.0"] = "2.0"
    source_revision: str = ""

    case_name: str = Field(description="用例名称。")
    case_goal: str = Field(default="", description="用例整体目标摘要。")
    steps: list[CaseStep] = Field(default_factory=list, description="Agent 探索阶段逐块执行一次的业务目标块。")
    verifications: list[CaseVerification] = Field(default_factory=list, description="后续脚本生成使用的验证目标。")

    @model_validator(mode="before")
    @classmethod
    def normalize_input(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        data.setdefault("case_name", "")
        data.setdefault("case_goal", "")
        if "steps" not in data and "operation_steps" in data:
            data["steps"] = data.pop("operation_steps")
        if "verifications" not in data and "verification_steps" in data:
            data["verifications"] = data.pop("verification_steps")
        data.setdefault("steps", [])
        data.setdefault("verifications", [])
        return data

    @model_validator(mode="after")
    def validate_case(self) -> CaseSpec:
        self.case_name = self.case_name.strip()
        self.case_goal = self.case_goal.strip()
        step_ids = [step.id for step in self.steps]
        verification_ids = [verification.id for verification in self.verifications]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("duplicate case step id")
        if len(verification_ids) != len(set(verification_ids)):
            raise ValueError("duplicate verification id")
        for verification in self.verifications:
            if verification.step_id is not None and verification.step_id not in step_ids:
                raise ValueError(f"unknown verification step reference: {verification.step_id}")
            if verification.anchor is None:
                raise ValueError("verification requires an explicit anchor")
            step = next(s for s in self.steps if s.id == verification.anchor.step_id)
            instruction_id = verification.anchor.instruction_id
            if instruction_id and instruction_id not in {i.id for i in step.instructions}:
                raise ValueError(f"unknown instruction reference: {instruction_id}")
            if instruction_id and verification.scope == "outside_repeat":
                raise ValueError("outside_repeat must anchor to a whole step")
        instruction_ids = [i.id for step in self.steps for i in step.instructions]
        if len(instruction_ids) != len(set(instruction_ids)):
            raise ValueError("duplicate instruction id")
        return self
