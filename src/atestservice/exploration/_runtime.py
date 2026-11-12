"""Private inputs and outputs for exploration implementation functions."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from atestservice.runtime.events import AgentEventPublisher




class ExplorationInput(TypedDict, total=False):
    """Private execution inputs; never a cross-stage or persisted graph schema."""
    event_publisher: AgentEventPublisher
    request: dict[str, Any]
    case_spec: dict[str, Any]
    trajectory: dict[str, Any]
    step_results: list[dict[str, Any]]
    run: dict[str, Any]
    current_step: dict[str, Any]
    current_observation_id: str


class StepLoopUpdate(TypedDict):
    trajectory: dict[str, Any]
    current_step_result: dict[str, Any]
    completion_event: NotRequired[dict[str, Any]]


class ExplorationUpdate(TypedDict, total=False):
    trajectory: dict[str, Any]
    step_results: list[dict[str, Any]]
    run: dict[str, Any]
    result: dict[str, Any]
