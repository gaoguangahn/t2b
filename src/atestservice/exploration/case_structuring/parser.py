"""将用户确认稿转换为执行契约，只纠正结构错误，不重新优化用例。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from pydantic import ValidationError
from langchain_core.exceptions import OutputParserException

from atestservice.contracts.case import CaseSpec
from atestservice.exploration.case_structuring.models import CaseExtraction
from atestservice.llm import StructuredLLM, create_llm

_PROMPT_PATH = Path(__file__).parent / "prompts" / "structure_case.md"


class CaseParser:
    def __init__(self, llm: StructuredLLM | None = None):
        self.llm = llm

    async def parse(self, confirmed_text: str) -> CaseSpec:
        confirmed_text = confirmed_text.strip()
        if not confirmed_text:
            raise ValueError("case input is empty")
        prompt = _PROMPT_PATH.read_text(encoding="utf-8").replace(
            "{confirmed_case_json}", json.dumps({"confirmed_text": confirmed_text}, ensure_ascii=False)
        )
        if self.llm is None:
            self.llm = create_llm()
        request_prompt = prompt
        for attempt in range(3):
            parsed = None
            try:
                parsed = await self.llm.invoke_structured(request_prompt, CaseExtraction)
                parsed = CaseExtraction.model_validate(parsed.model_dump(mode="json"))
                case = parsed.to_case_spec()
            except (ValidationError, OutputParserException) as error:
                errors = ([{"path": list(item["loc"]), "message": item["msg"]}
                           for item in error.errors(include_url=False, include_input=False)]
                          if isinstance(error, ValidationError) else
                          [{"path": [], "message": "返回结果无法解析为要求的JSON结构，请重新输出完整对象。"}])
                if attempt == 2:
                    raise ValueError("确认稿结构转换失败，纠正两次后仍不合法：" +
                                     json.dumps(errors, ensure_ascii=False)) from error
                feedback = {"validation_errors": errors}
                if parsed is not None:
                    feedback["previous_output"] = parsed.model_dump(mode="json")
                request_prompt = prompt + "\n\n上次结果未通过校验，只修复结构、字段或引用错误，按确认稿重新输出完整结构；不得优化、增删或重排内容，不删除验证来通过校验：\n" + json.dumps(feedback, ensure_ascii=False)
                continue
            case.source_revision = hashlib.sha256(confirmed_text.encode("utf-8")).hexdigest()
            return case
