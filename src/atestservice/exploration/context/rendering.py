"""Prompt context helpers for executing one case step."""

from __future__ import annotations
from atestservice.contracts.execution import ExecutionResult
import json

from typing import Any


def render_step_task_text(
    *,
    current_step: dict[str, Any],
    step_results: list[dict[str, Any]] | None,
) -> str:
    """Render the stable non-image user message for one StepAgent loop."""

    step_id = str(current_step.get("id") or "").strip() or "unknown_step"
    goal = str(current_step.get("goal") or "").strip()
    lines = [f"当前操作块：{step_id}", f"单轮目标：{goal}", "有序操作要求（每项可包含多个工具动作）：",
             json.dumps(current_step.get("instructions") or [], ensure_ascii=False),
             "前序实际结果（仅作背景，不重做）：", render_step_results(step_results or [])]
    return "\n".join(lines)


def render_step_results(step_results: list[dict[str, Any]], *, limit: int = 6) -> str:
    """Render completed-step ledger for model context."""

    if not step_results:
        return "无"
    items = step_results[-limit:]
    omitted = len(step_results) - len(items)
    lines: list[str] = []
    if omitted > 0:
        lines.append(f"[前 {omitted} 个目标块已完成，已省略]")
    for index, step in enumerate(items, start=1):
        step_id = str(step.get("id") or step.get("step_id") or "").strip() or "unknown_step"
        status = str(step.get("status") or "unknown").strip()
        summary = str(step.get("summary") or "").strip() or "无摘要"
        lines.append(f"{index}. {step_id} {status}：{summary}")
    return "\n".join(lines)


def render_recent_step_actions(
    *,
    trajectory: dict[str, list[dict[str, Any]]] | None,
    step_id: str,
    limit: int = 6,
) -> str:
    """Render recent operations already performed for the current step."""

    if not isinstance(trajectory, dict):
        return "无"
    operations = trajectory.get("operations")
    if not isinstance(operations, list):
        return "无"

    step_ops = [op for op in operations if _operation_step_id(op) == step_id]
    if not step_ops:
        return "无"

    recent = step_ops[-max(limit, 0) :] if limit else []
    lines: list[str] = []
    for index, operation in enumerate(recent, start=1):
        op_id = str(operation.get("id") or f"op_{index}")
        intent = operation.get("intent") if isinstance(operation.get("intent"), dict) else {}
        execution = operation.get("execution") if isinstance(operation.get("execution"), dict) else {}
        tool_name = str(intent.get("tool_name") or "unknown")
        reason = str(intent.get("reason") or "未提供原因").strip()
        outcome = ExecutionResult.model_validate(execution)
        message = outcome.message
        suffix = f"，{message}" if message else ""
        action = operation.get("action") or {}
        lines.append(f"{index}. {op_id} {tool_name}：{reason}。请求参数："
                     f"{json.dumps(action.get('args', {}), ensure_ascii=False)}。命令状态：{outcome.status}{suffix}。")
    return "\n".join(lines) if lines else "无"


def _operation_step_id(operation: Any) -> str | None:
    if not isinstance(operation, dict):
        return None
    semantic_ref = operation.get("semantic_ref")
    if not isinstance(semantic_ref, dict):
        return None
    value = semantic_ref.get("step_id")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
