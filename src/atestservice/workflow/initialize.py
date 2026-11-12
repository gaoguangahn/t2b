"""Initialization node for the first-stage mobile agent graph."""

from __future__ import annotations

from typing import Any

from atestservice.exploration.config import AgentConfig
from atestservice.workflow.state import MobileAgentState


def initialize_state(
    state: MobileAgentState, agent_config: AgentConfig | None = None
) -> MobileAgentState:
    """Fill the new request/case/trajectory/run containers."""

    agent_config = agent_config or AgentConfig()
    request = _request_from_state(state)
    raw_run = state.get("run") if isinstance(state.get("run"), dict) else {}
    max_rounds = int(raw_run.get("max_rounds") or agent_config.safety_min_rounds)

    return {
        **state,
        "request": request,
        "case_spec": state.get("case_spec"),
        "run": {
            "status": "running",
            "max_rounds": max_rounds,
            "failure_reason": None,
            "finish_reason": None,
            **raw_run,
        },
        "result": state.get("result", {}),
    }


def _request_from_state(state: dict[str, Any]) -> dict[str, Any]:
    raw_request = state.get("request")
    request = dict(raw_request) if isinstance(raw_request, dict) else {}

    raw_text = str(
        request.get("raw_text")
        or state.get("editable_text")
        or state.get("raw_text")
        or ""
    ).strip()
    framework = str(
        request.get("framework")
        or state.get("framework")
        or "dynamic_framework"
    ).strip()

    request["raw_text"] = raw_text
    request["framework"] = framework or "dynamic_framework"
    return request
