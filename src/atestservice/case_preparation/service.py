"""单用例描述优化：返回可编辑文本，不生成或依赖执行用例结构。"""
from __future__ import annotations

import json
from pathlib import Path

from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from atestservice.llm import StructuredLLM, create_llm
from atestservice.runtime.events import AgentEventPublisher, NoopAgentEventPublisher
from atestservice.runtime.event_payloads import json_event

_PROMPT = Path(__file__).parent / "prompts" / "optimize_case.md"


class PreparedCase(BaseModel):
    """优化服务的输出协议，只含标题和用户可编辑的完整描述。"""
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, description="简短明确的用例名称。")
    editable_text: str = Field(min_length=1, description="整理后的完整单用例文本，按原顺序保留操作、验证与循环关系。")

    @field_validator("title", "editable_text")
    @classmethod
    def require_content(cls, value):
        if not value.strip():
            raise ValueError("标题和确认稿不能为空")
        return value  # 不 strip 正文，避免破坏用户输入原文中的空格和换行。


class CasePreparationService:
    def __init__(self, llm: StructuredLLM | None = None):
        self.llm = llm

    async def prepare(
        self, raw_text: str, *, event_publisher: AgentEventPublisher | None = None
    ) -> PreparedCase:
        if not raw_text.strip():
            raise ValueError("case input is empty")
        publisher = event_publisher or NoopAgentEventPublisher()
        await publisher.node_started(stage="prepare", node="prepare_case", label="正在整理用例描述")
        try:
            draft = await self._optimize(raw_text)
        except Exception as exc:
            await publisher.node_failed(stage="prepare", node="prepare_case", message=str(exc))
            raise
        await publisher.node_finished(
            stage="prepare", node="prepare_case",
            payload=json_event("用例描述整理完成", "已整理当前用例，可确认和编辑。", "prepared_case.json",
                               draft.model_dump(mode="json")),
        )
        return draft

    async def _optimize(self, raw_text: str) -> PreparedCase:
        prompt = _PROMPT.read_text(encoding="utf-8").replace(
            "{raw_case_json}", json.dumps({"raw_text": raw_text}, ensure_ascii=False)
        )
        if self.llm is None:
            self.llm = create_llm()
        request = prompt
        for attempt in range(3):
            try:
                result = await self.llm.invoke_structured(request, PreparedCase)
                return PreparedCase.model_validate(result.model_dump(mode="json"))
            except (ValidationError, OutputParserException) as error:
                # 仅重试输出格式错误；提供方异常直接交给任务失败处理。
                errors = ([{"path": list(item["loc"]), "message": item["msg"]}
                           for item in error.errors(include_url=False, include_input=False)]
                          if isinstance(error, ValidationError) else
                          [{"path": [], "message": "返回结果无法解析为要求的JSON对象"}])
                if attempt == 2:
                    raise ValueError("用例优化输出格式错误，纠正两次后仍不合法：" +
                                     json.dumps(errors, ensure_ascii=False)) from error
                request = prompt + "\n\n只纠正输出格式，不增删原用例要求。重新返回完整对象：\n" + json.dumps(errors, ensure_ascii=False)


async def prepare_case(
    raw_text: str, *, event_publisher: AgentEventPublisher | None = None
) -> PreparedCase:
    return await CasePreparationService().prepare(raw_text, event_publisher=event_publisher)
