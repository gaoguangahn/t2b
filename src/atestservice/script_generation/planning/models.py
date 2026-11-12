"""Private LLM protocol; not part of exploration or workflow state."""
from pydantic import Field
from atestservice.contracts.script import ScriptModel, ScriptPlan


class PlanningResponse(ScriptModel):
    plan: ScriptPlan | None = None
    observation_requests: list[str] = Field(default_factory=list, description="需要读取完整 UI/截图的已有 observation ID；需要补证时 plan 可为空。")
