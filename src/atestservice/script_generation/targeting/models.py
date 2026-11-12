"""Private target-picking protocol; selector values are copied from evidence by code."""
from typing import Literal
from pydantic import Field
from atestservice.contracts.script import ScriptModel

Attribute = Literal["resource_id", "text", "description", "class_name"]


class TargetPick(ScriptModel):
    request_id: str
    kind: Literal["ui", "non_ui", "unresolved"]
    target_description: str
    candidate_id: str | None = None
    attributes: list[Attribute] = Field(default_factory=list)
    scope_candidate_id: str | None = None
    scope_attributes: list[Attribute] = Field(default_factory=list)
    scope_index: int | None = Field(default=None, ge=0, description="所属条目在区域匹配中的序号，不能把第一条内容偷换成全局第一个按钮。")
    index: int | None = Field(default=None, ge=0)
    attribute_role: Literal["control_identity", "user_value", "dynamic_content"] = "control_identity"
    reason: str = Field(min_length=1)


class TargetResponse(ScriptModel):
    targets: list[TargetPick]
