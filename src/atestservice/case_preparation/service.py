"""Single-case preparation: parse meaning, then render an editable draft."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from atestservice.case_preparation.parser import CaseParser
from atestservice.contracts.rendering import render_case
from atestservice.runtime.events import AgentEventPublisher, NoopAgentEventPublisher
from atestservice.runtime.event_payloads import json_event


class PreparedCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    editable_text: str


class CasePreparationService:
    def __init__(self, parser: CaseParser | None = None):
        self.parser = parser or CaseParser()

    async def prepare(
        self, raw_text: str, *, event_publisher: AgentEventPublisher | None = None
    ) -> PreparedCase:
        if not raw_text.strip():
            raise ValueError("case input is empty")
        publisher = event_publisher or NoopAgentEventPublisher()
        await publisher.node_started(stage="prepare", node="prepare_case", label="正在整理用例描述")
        try:
            case = await self.parser.parse(raw_text)
            draft = PreparedCase(title=case.case_name, editable_text=render_case(case))
        except Exception as exc:
            await publisher.node_failed(stage="prepare", node="prepare_case", message=str(exc))
            raise
        await publisher.node_finished(
            stage="prepare", node="prepare_case",
            payload=json_event("用例描述整理完成", "已整理当前用例，可确认和编辑。", "prepared_case.json",
                               draft.model_dump(mode="json")),
        )
        return draft


async def prepare_case(
    raw_text: str, *, event_publisher: AgentEventPublisher | None = None
) -> PreparedCase:
    return await CasePreparationService().prepare(raw_text, event_publisher=event_publisher)
