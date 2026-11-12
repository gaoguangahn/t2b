"""Runner facade for first-stage mobile UI exploration."""

from __future__ import annotations

from typing import Any

from atestservice.exploration.config import AgentConfig
from atestservice.runtime.events import AgentEventPublisher
from atestservice.workflow.state import MobileAgentState
from atestservice.workflow.graph import build_explore_graph
from atestservice.device.client import DeviceClient


class MobileTestAgentRunner:
    """High-level entry point for case_spec + trajectory exploration."""

    def __init__(self, *, action_client: DeviceClient, config: AgentConfig | None = None):
        self.config = config or AgentConfig()
        self.action_client = action_client

    async def run(
        self,
        raw_text: str,
        *,
        event_publisher: AgentEventPublisher | None = None,
        case_spec: dict[str, Any] | None = None,
        framework: str | None = None,
        run_id: str | None = None,
        **overrides: Any,
    ) -> MobileAgentState:
        """Explore the plugin-connected device from confirmed case text."""

        initial_state: MobileAgentState = {
            "request": {"raw_text": raw_text, "framework": framework or "dynamic_framework", "run_id": run_id},
            "framework": framework or "dynamic_framework",
            "case_spec": case_spec,
            **overrides,
        }
        graph = build_explore_graph(action_client=self.action_client, config=self.config, event_publisher=event_publisher)
        return await graph.ainvoke(initial_state)
