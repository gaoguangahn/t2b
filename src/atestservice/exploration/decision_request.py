"""Request and correct a single model decision before any device side effect."""
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from atestservice.exploration.decisions import LoopActionDecision
from atestservice.exploration.tools import EXPLORE_ACTION_TOOLS, tool_call_to_decision
from atestservice.llm.diagnostics import response_summary
from atestservice.llm.types import LLMCallOptions, StructuredLLM
from atestservice.runtime.event_payloads import json_event
from atestservice.runtime.events import AgentEventPublisher

_LOGGER = logging.getLogger(__name__)


class DecisionResponseError(ValueError):
    """A response could not provide one complete, valid decision."""


def _decode(message):
    calls = getattr(message, "tool_calls", None) or []
    invalid = getattr(message, "invalid_tool_calls", None) or []
    if (getattr(message, "response_metadata", None) or {}).get("finish_reason") == "length":
        raise DecisionResponseError("模型输出被长度限制截断，未接受本轮决策。")
    if len(calls) != 1 or invalid:
        raise DecisionResponseError(f"模型需返回恰好一个完整工具调用，实际有效 {len(calls)} 个、参数JSON损坏 {len(invalid)} 个。")
    try:
        return tool_call_to_decision(calls[0]), calls[0]
    except ValidationError as error:
        details = [{"path": list(item["loc"]), "message": item["msg"]}
                   for item in error.errors(include_url=False, include_input=False)[:4]]
        raise DecisionResponseError("工具参数不符合要求：" + json.dumps(details, ensure_ascii=False)) from error
    except (ValueError, TypeError) as error:
        raise DecisionResponseError("工具决策无效：" + str(error)[:300]) from error


async def request_decision(
    llm: StructuredLLM, *,
    build_messages: Callable[[str | None], Awaitable[list[Any]]],
    options: LLMCallOptions,
    publisher: AgentEventPublisher,
    step_id: str,
    instruction_id: str | None,
    round_index: int,
    retry_limit: int = 1,
) -> tuple[LoopActionDecision, dict[str, Any]]:
    """Retry invalid responses only; provider errors and device execution are outside."""
    correction = None
    retry_limit = max(0, retry_limit)
    for attempt in range(retry_limit + 1):
        # The caller rebuilds current evidence, refreshing stale pages if needed.
        messages = await build_messages(correction)
        message = await llm.invoke_tool_message(messages, EXPLORE_ACTION_TOOLS, options=options)
        try:
            return _decode(message)
        except DecisionResponseError as error:
            diagnostics = {"step_id": step_id, "instruction_id": instruction_id, "round": round_index,
                           "attempt": attempt + 1, "max_attempts": retry_limit + 1,
                           "model": getattr(getattr(llm, "config", None), "model", None),
                           "valid_tool_call_count": len(getattr(message, "tool_calls", None) or []),
                           "invalid_tool_call_count": len(getattr(message, "invalid_tool_calls", None) or []),
                           **response_summary(message)}
            _LOGGER.warning("Exploration decision rejected: %s", json.dumps(diagnostics, ensure_ascii=False))
            if attempt == retry_limit:
                raise DecisionResponseError(f"模型决策连续 {attempt + 1} 次未通过校验：{error}") from error
            correction = (f"本轮模型响应未通过校验：{error}\n"
                          "这份被拒绝的响应没有下发任何手机动作，也没有推进指令。请根据当前任务、已执行事实和最新页面重新判断，"
                          "通过工具调用返回恰好一个完整、参数合法的决定，不用普通文本或正文JSON代替工具调用。"
                          "不要重做已完成操作；已完成用对应结束工具，无法继续用ReportBlocker。简洁说明依据，不复述整个任务。")
            await publisher.node_finished(stage="exploration", node="decision_retry", payload=json_event(
                "模型响应无效，正在重新判断", f"目标块 {step_id}：{error} 即将重试 {attempt + 1}/{retry_limit}；本轮尚未下发手机动作。",
                f"{step_id}_decision_{round_index:04d}_retry_{attempt + 1}.json", diagnostics))
    raise AssertionError("unreachable")
