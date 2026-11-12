"""Configuration objects for the mobile test agent."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AgentConfig:
    """Runtime limits for exploration."""

    safety_min_rounds: int = 80
    safety_rounds_per_step: int = 8
    step_attempt_limit: int = 12
    non_step_plan_limit: int = 10
    execution_error_limit: int = 3
    screenshot_scale_factor: float = 0.5
    observation_max_age_seconds: float = 30.0
    consecutive_observe_limit: int = 3
    observe_wait_budget_seconds: float = 15.0
