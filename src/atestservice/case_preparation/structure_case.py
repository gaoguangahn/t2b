"""Build a minimal case spec for mobile agent execution."""

from __future__ import annotations

from typing import Any

from atestservice.contracts.case import CaseSpec
from atestservice.case_preparation.parser import CaseParser

from atestservice.runtime.events import NoopAgentEventPublisher
from atestservice.llm import StructuredLLM
from atestservice.workflow.state import MobileAgentState
from atestservice.runtime.event_payloads import json_event, text_event

class StructureCaseNode:
    """Parse confirmed editable text into the first-stage case spec."""

    def __init__(self, llm: StructuredLLM | None = None, *, parser: CaseParser | None = None):
        self.parser = parser or CaseParser(llm=llm)

    async def __call__(self, state: MobileAgentState) -> MobileAgentState:
        publisher = state.get("event_publisher") or NoopAgentEventPublisher()
        existing_case_spec = state.get("case_spec")
        if isinstance(existing_case_spec, dict) and (
            "steps" in existing_case_spec or "operation_steps" in existing_case_spec
        ):
            validated = CaseSpec.model_validate(existing_case_spec)
            return {"case_spec": validated.model_dump(mode="json")}

        raw_text = _raw_text_from_state(state)
        if not raw_text:
            case_spec = CaseSpec(case_name="", case_goal="", steps=[], verifications=[])
            await publisher.node_finished(
                stage="exploration",
                node="build_case_spec",
                payload=text_event("结构化用例跳过", "没有可解析的用例文本，未进入手机执行。"),
            )
            return {"case_spec": case_spec.model_dump(mode="json")}

        await publisher.node_started(
            stage="exploration",
            node="build_case_spec",
            label="正在解析结构化用例",
        )
        case_spec = await self.parser.parse(raw_text)
        data = case_spec.model_dump(mode="json")
        await publisher.node_finished(
            stage="exploration",
            node="build_case_spec",
            payload=json_event(
                "结构化用例完成",
                "已生成进入 Agent Loop 前使用的结构化数据。",
                "case_spec.json",
                data,
            ),
        )
        return {"case_spec": data}

def _raw_text_from_state(state: dict[str, Any]) -> str:
    request = state.get("request") or {}
    raw_text = str(request.get("raw_text") or "").strip() if isinstance(request, dict) else ""
    if raw_text:
        return raw_text
    return str(state.get("editable_text") or "").strip()
