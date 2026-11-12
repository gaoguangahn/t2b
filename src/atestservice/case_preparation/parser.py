"""Single-case semantic parsing, independent of graph nodes and HTTP DTOs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
        parsed = await self.llm.invoke_structured(prompt, CaseExtraction)
        # Also validate custom/injected model implementations at this boundary.
        case = CaseExtraction.model_validate(parsed.model_dump(mode="json")).to_case_spec()
        case.source_revision = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        return case
