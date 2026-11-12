"""Framework-independent generation artifacts. Exploration remains immutable."""
from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from atestservice.contracts.action import ActionType
from atestservice.contracts.instructions import VerificationAnchor


class ScriptModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerationIssue(ScriptModel):
    code: str
    message: str
    blocking: bool = False
    source_ids: list[str] = Field(default_factory=list)


class PlannedAction(ScriptModel):
    operation_id: str
    description: str = Field(min_length=1)
    condition_id: str | None = None


class ExecutionCondition(ScriptModel):
    id: str
    description: str = Field(min_length=1, description="此组操作在什么可观察条件下执行，不含框架 API。")


class OmittedSegment(ScriptModel):
    operation_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)
    state_effects: str = Field(min_length=1, description="解释片段对必要业务状态的影响，以及为何删除后仍满足用户要求。")
    observation_ids: list[str] = Field(min_length=1)


class ScriptPlan(ScriptModel):
    schema_version: Literal["1.0"] = "1.0"
    actions: list[PlannedAction] = Field(default_factory=list)
    conditions: list[ExecutionCondition] = Field(default_factory=list)
    omitted_segments: list[OmittedSegment] = Field(default_factory=list)
    issues: list[GenerationIssue] = Field(default_factory=list)


class Selector(ScriptModel):
    resource_id: str | None = None
    text: str | None = None
    description: str | None = None
    class_name: str | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not any(self.model_dump().values()):
            raise ValueError("selector must contain an attribute")
        return self


class Locator(ScriptModel):
    selector: Selector
    within: Selector | None = None
    within_index: int | None = Field(default=None, ge=0, description="用户指定的所属条目序号，从0起；不同于条目内目标序号。")
    index: int | None = Field(default=None, ge=0, description="仅用户明确指定位置时使用，从 0 起。")

    @model_validator(mode="after")
    def scope_index_requires_scope(self):
        if self.within_index is not None and self.within is None:
            raise ValueError("within_index requires a scope selector")
        return self


class TargetResolution(ScriptModel):
    description: str
    rationale: str = ""
    status: Literal["resolved", "coordinate", "unresolved", "non_ui"]
    observation_id: str | None = None
    locator: Locator | None = None
    point: tuple[float, float] | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "resolved") != (self.locator is not None):
            raise ValueError("resolved target requires a locator")
        if (self.status == "coordinate") != (self.point is not None):
            raise ValueError("coordinate target requires a point")
        if self.point and any(not 0 <= v <= 1 for v in self.point):
            raise ValueError("point must use 0..1 coordinates")
        return self


class ScriptActionArgs(ScriptModel):
    text: str | None = None
    direction: Literal["up", "down", "left", "right"] | None = None
    times: int | None = Field(default=None, ge=1)
    interval: float | None = Field(default=None, ge=0)
    start: tuple[float, float] | None = None
    end: tuple[float, float] | None = None
    duration: float | None = Field(default=None, gt=0)
    app_name: str | None = None


class ActionNode(ScriptModel):
    type: Literal["action"] = "action"
    source_operation_id: str
    description: str
    action_type: ActionType
    parameters: ScriptActionArgs
    target: TargetResolution | None = None
    activity: str | None = None
    activity_changed: bool = False


class VerifyNode(ScriptModel):
    type: Literal["verify"] = "verify"
    verification_id: str
    expectation: str
    anchor: VerificationAnchor
    target: TargetResolution


class ConditionNode(ScriptModel):
    type: Literal["condition"] = "condition"
    description: str
    target: TargetResolution
    body: list[ScriptNode]


class RepeatNode(ScriptModel):
    type: Literal["repeat"] = "repeat"
    times: int = Field(ge=2)
    description: str
    body: list[ScriptNode]


ScriptNode = Annotated[ActionNode | VerifyNode | ConditionNode | RepeatNode, Field(discriminator="type")]
ConditionNode.model_rebuild()
RepeatNode.model_rebuild()


class ScriptIR(ScriptModel):
    schema_version: Literal["1.0"] = "1.0"
    case_name: str
    steps: list[ScriptNode] = Field(min_length=1)


class CodegenResult(ScriptModel):
    language: Literal["python"] = "python"
    framework: str
    filename: str
    content: str
    notes: list[str] = Field(default_factory=list)


class GenerationPreparation(ScriptModel):
    plan: ScriptPlan
    ir: ScriptIR | None = None


class GenerationResult(ScriptModel):
    status: Literal["ready", "draft", "blocked"]
    plan: ScriptPlan
    ir: ScriptIR | None = None
    script: CodegenResult | None = None

    @model_validator(mode="after")
    def consistent(self):
        if self.status == "blocked":
            if self.script is not None or self.ir is not None:
                raise ValueError("blocked generation cannot contain executable output")
        elif self.ir is None or self.script is None:
            raise ValueError("ready/draft generation requires both IR and script")
        if self.status == "ready" and (self.script.notes or any(i.blocking for i in self.plan.issues)):
            raise ValueError("ready generation cannot contain unresolved notes or blockers")
        return self
