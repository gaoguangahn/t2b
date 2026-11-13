"""Private target-picking protocol; selector values are copied from evidence by code."""
from typing import Literal
from pydantic import Field
from atestservice.contracts.script import ScriptModel, VerificationPlan

Attribute = Literal["resource_id", "text", "description", "class_name"]


class TargetPick(ScriptModel):
    request_id: str
    kind: Literal["ui", "non_ui", "unresolved"]
    target_description: str
    candidate_id: str | None = None
    candidate_observation_id: str | None = Field(default=None, description="候选来源帧，null表示锚点帧。动作和条件只从锚点选择；验证的已知控件身份或状态UI特征可从提供的历史支持帧选择，但不改变验证锚点。")
    attributes: list[Attribute] = Field(default_factory=list, description="目标定位属性名，不是属性值。kind=ui时至少选一项，只选候选节点上值非null且非空字符串的属性，不重复。一个稳定属性即可唯一定位时只选该项，无需其他属性都有值；需要消歧时再组合。节点含某个字段名不表示它有可用值。")
    scope_candidate_id: str | None = None
    scope_attributes: list[Attribute] = Field(default_factory=list, description="所属区域的定位属性名，仅从scope_candidate_id节点上有非空现场值的属性选择，不从目标节点借用。有scope_candidate_id时至少一项；无所属区域时填空数组。")
    scope_index: int | None = Field(default=None, ge=0, description="所属条目在区域匹配中的序号，不能把第一条内容偷换成全局第一个按钮。")
    index: int | None = Field(default=None, ge=0)
    attribute_role: Literal["control_identity", "user_value", "state_indicator", "dynamic_content"] = "control_identity"
    verification: VerificationPlan | None = Field(default=None, description="仅验证请求填写：直接属性、明确状态UI特征、文本或数量的判断方式。预期来自user_goal，不能由observed值替换。其他请求填null。")
    reason: str = Field(min_length=1)


class TargetResponse(ScriptModel):
    targets: list[TargetPick]
