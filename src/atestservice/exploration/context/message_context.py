"""Agent Loop 的标准消息上下文管理。"""

from __future__ import annotations

import json
from typing import Any


from atestservice.exploration.observations.media import image_from_snapshot
from atestservice.llm import StructuredLLM
from atestservice.contracts.execution import ExecutionResult
from atestservice.exploration.prompts import CURRENT_SCREEN_TEXT


class AgentLoopContext:
    """Render task state and latest observation, retaining only the last result.

    Tool calls remain output transport; previous assistant/tool messages are not
    resent. Progress is provided by the execution cursor, not conversation memory.
    """

    def __init__(
        self,
        *,
        system_prompt: str,
        task_text: str,
    ):
        self.system_prompt = system_prompt
        self.task_text = task_text.strip()
        self.last_result: dict[str, Any] | None = None

    def build_messages(
        self,
        *,
        llm: StructuredLLM,
        observation: dict[str, Any],
        progress_summary: str | None = None,
    ) -> list[Any]:
        """构造本轮模型输入。"""

        task_content = self.task_text
        if progress_summary:
            task_content = f"{task_content}\n\n{progress_summary.strip()}"

        if self.last_result:
            task_content += "\n最近一次结果：" + json.dumps(self.last_result, ensure_ascii=False)

        page_text = f"{CURRENT_SCREEN_TEXT} observation_id={observation.get('id')}"
        foreground = {key: observation[key] for key in ("package", "activity") if observation.get(key)}
        if foreground:
            page_text += "\n当前前台信息：" + json.dumps(foreground, ensure_ascii=False)
        builder = llm.message_builder.text(page_text)
        builder.image(image_from_snapshot(observation))
        current_user_message = builder.build()[0]

        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task_content},
            current_user_message,
        ]

    def record_result(self, result: dict[str, Any]) -> None:
        """Keep the latest execution/control feedback; no conversation history."""
        self.last_result = result


def tool_result_content(*, execution: dict[str, Any]) -> dict[str, Any]:
    """给模型看的工具结果保持极简，复杂轨迹信息只写入内部 trajectory。"""

    outcome = ExecutionResult.model_validate(execution)
    result = {"success": outcome.status == "succeeded", "execution_status": outcome.status, "message": outcome.message}
    if outcome.completed_count is not None:
        result["completed_count"] = outcome.completed_count
    return result
