"""Run case_spec steps one by one."""

from __future__ import annotations

from typing import Any

from atestservice.exploration.config import AgentConfig
from atestservice.runtime.events import NoopAgentEventPublisher
from atestservice.llm import StructuredLLM
from atestservice.exploration.loop_node import ExploreAgentLoopNode
from atestservice.exploration._runtime import ExplorationInput, ExplorationUpdate
from atestservice.device.client import DeviceClient
from atestservice.runtime.event_payloads import json_event, text_event


class CaseStepRunnerNode:
    """Code-owned outer loop over case_spec.steps."""

    def __init__(
        self,
        *,
        action_client: DeviceClient,
        llm: StructuredLLM | None = None,
        config: AgentConfig | None = None,
    ):
        self.config = config or AgentConfig()
        self.step_loop = ExploreAgentLoopNode(
            action_client=action_client,
            llm=llm,
            config=self.config,
        )

    async def __call__(self, state: ExplorationInput) -> ExplorationUpdate:
        publisher = state.get("event_publisher") or NoopAgentEventPublisher()
        await publisher.node_started(
            stage="exploration",
            node="run_case_steps",
            label="正在按目标块执行用例",
        )

        case_spec = state.get("case_spec") if isinstance(state.get("case_spec"), dict) else {}
        steps = _case_steps(case_spec)
        if not steps:
            message = "结构化用例中没有可执行目标块，未进入手机执行。"
            await publisher.node_finished(
                stage="exploration",
                node="run_case_steps",
                payload=text_event("无需执行手机操作", message),
            )
            run = dict(state.get("run") or {})
            return {
                "run": {
                    **run,
                    "status": "done",
                    "finish_reason": "no_case_steps",
                    "failure_reason": None,
                },
                "result": {
                    **(state.get("result") or {}),
                    "status": "skipped",
                    "message": message,
                },
            }

        trajectory = _trajectory_copy(state.get("trajectory"))
        step_results = list(state.get("step_results") or [])
        run = dict(state.get("run") or {})

        for index, step in enumerate(steps):
            current_step = {"id": step["id"], "goal": step["goal"], "instructions": step.get("instructions", [])}
            step_state: ExplorationInput = {
                **state,
                "trajectory": trajectory,
                "current_step": current_step,
                "step_results": step_results,
                "run": run,
            }
            update = await self.step_loop(step_state)
            trajectory = _trajectory_copy(update.get("trajectory") or trajectory)
            step_result = _normalize_step_result(
                update.get("current_step_result"),
                current_step=current_step,
            )
            step_results.append(step_result)

            await publisher.node_finished(
                stage="exploration",
                node="case_step_finished",
                payload=json_event(
                    f"目标块 {current_step['id']} 执行完成",
                    step_result["summary"],
                    f"step_result_{index + 1:03d}.json",
                    step_result,
                ),
            )

            if step_result["status"] != "completed":
                return {
                    "trajectory": trajectory,
                    "step_results": step_results,
                    "run": {
                        **run,
                        "status": "failed",
                        "failure_reason": step_result["summary"],
                        "finish_reason": None,
                    },
                }

        await publisher.node_finished(
            stage="exploration",
            node="run_case_steps",
            payload=text_event("目标块执行完成", "全部目标块已执行完成。"),
        )
        return {
            "trajectory": trajectory,
            "step_results": step_results,
            "run": {
                **run,
                "status": "done",
                "finish_reason": "all_steps_completed",
                "failure_reason": None,
            },
        }


def _case_steps(case_spec: dict[str, Any]) -> list[dict[str, Any]]:
    steps = case_spec.get("steps") if isinstance(case_spec, dict) else []
    result: list[dict[str, Any]] = []
    if not isinstance(steps, list):
        return result
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id") or "").strip()
        goal = str(step.get("goal") or "").strip()
        if not step_id or not goal:
            continue
        result.append({"id": step_id, "goal": goal, "instructions": step.get("instructions", [])})
    return result


def _normalize_step_result(value: Any, *, current_step: dict[str, str]) -> dict[str, Any]:
    if isinstance(value, dict):
        status = str(value.get("status") or "error").strip()
        summary = str(value.get("summary") or "").strip()
        return {
            "step_id": str(value.get("step_id") or current_step["id"]),
            "status": status if status in {"completed", "error", "blocked"} else "error",
            "summary": summary or f"目标块 {current_step['id']} 未返回执行摘要。",
            "checkpoints": list(value.get("checkpoints") or []),
            "instruction_results": list(value.get("instruction_results") or []),
        }
    return {
        "step_id": current_step["id"],
        "status": "error",
        "summary": f"目标块 {current_step['id']} 未返回执行结果。",
    }


def _trajectory_copy(value: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        return {"observations": [], "operations": []}
    observations = value.get("observations")
    operations = value.get("operations")
    return {
        "observations": list(observations) if isinstance(observations, list) else [],
        "operations": list(operations) if isinstance(operations, list) else [],
    }
