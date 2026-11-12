"""Agent Loop 的操作轨迹条目构造。"""

from __future__ import annotations

from typing import Any

from atestservice.exploration.decisions import LoopActionDecision
from atestservice.contracts.action import ResolvedAction




def build_operation_entry(
    *,
    index: int,
    decision: LoopActionDecision,
    action: ResolvedAction,
    execution: dict[str, Any],
    raw_tool_call: dict[str, Any],
    before_observation: dict[str, Any],
    after_observation: dict[str, Any],
    current_step: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造一条内部操作轨迹。

    operation 是一次真实底层动作，不等同于用户语义步骤。脚本生成应优先消费
    semantic_ref + action + execution，debug 只用于排查模型原始输出。
    """

    return {
        "id": f"op_{index:04d}",
        "index": index,
        "observation_transition": _observation_transition(
            before_observation=before_observation,
            after_observation=after_observation,
        ),
        "semantic_ref": _semantic_ref(
            current_step=current_step,
        ),
        "intent": _intent(decision),
        "action": _action(action),
        "execution": execution,
        "debug": {
            "raw_tool_call": raw_tool_call,
        },
    }


def _observation_transition(
    *,
    before_observation: dict[str, Any],
    after_observation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "before_observation_id": before_observation.get("id"),
        "after_observation_id": after_observation.get("id"),
    }


def _semantic_ref(*, current_step: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(current_step, dict):
        raise ValueError("operation requires a current step")
    return {
        "step_id": current_step.get("id"),
        "instruction_id": current_step.get("active_instruction_id"),
    }


def _intent(decision: LoopActionDecision) -> dict[str, Any]:
    return {
        "tool_name": decision.raw_tool_name,
        "reason": decision.reason,
    }


def _action(action: ResolvedAction) -> dict[str, Any]:
    return {
        "type": action.action,
        "args": action.args.model_dump(mode="json", exclude_none=True),
    }
