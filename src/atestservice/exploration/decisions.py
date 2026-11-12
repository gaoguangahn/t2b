"""Agent loop internal data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from atestservice.contracts.action import ResolvedAction

LoopDecisionKind = Literal["action", "finish", "blocker", "instruction", "observe"]
StepDecisionStatus = Literal["completed", "blocked", "error"]


@dataclass(slots=True)
class LoopActionDecision:
    """Unified decision parsed from one model tool call.

    reason 统一表达「为什么做这个动作」：
    - 动作工具：简述当前所在页面 + 这个动作要去哪/为什么，让后续审查层
      能从一串 reason 还原页面状态链，识别走错-恢复 detour 段。
    - finish/blocker：结束/阻塞的原因。
    """

    kind: LoopDecisionKind
    reason: str
    raw_tool_name: str
    raw_args: dict[str, Any] = field(default_factory=dict)
    action: ResolvedAction | None = None
    status: StepDecisionStatus | None = None
