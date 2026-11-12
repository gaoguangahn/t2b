"""Single-case semantic parsing, independent of graph nodes and HTTP DTOs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from pydantic import ValidationError
from langchain_core.exceptions import OutputParserException

from atestservice.contracts.case import CaseSpec
from atestservice.case_preparation.models import CaseExtraction
from atestservice.llm import StructuredLLM, create_llm

_PROMPT_PATH = Path(__file__).parent / "prompts" / "parse_case.md"


class CaseParser:
    def __init__(self, llm: StructuredLLM | None = None):
        self.llm = llm

    async def parse(self, raw_text: str) -> CaseSpec:
        raw_text = raw_text.strip()
        if not raw_text:
            raise ValueError("case input is empty")
        prompt = _PROMPT_PATH.read_text(encoding="utf-8").replace(
            "{state_json}", json.dumps({"raw_text": raw_text}, ensure_ascii=False)
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
                    raise ValueError("用例结构整理失败，纠正两次后仍不合法：" +
                                     json.dumps(errors, ensure_ascii=False)) from error
                feedback = {"validation_errors": errors}
                if parsed is not None:
                    feedback["previous_output"] = parsed.model_dump(mode="json")
                request_prompt = prompt + "\n\n上次结果未通过校验，请根据原文重新输出完整结构，保留原意与验证位置，不删除出错的验证来通过校验：\n" + json.dumps(feedback, ensure_ascii=False)
                continue
            case.source_revision = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
            return case
