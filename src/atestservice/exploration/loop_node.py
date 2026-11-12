"""Single-step autonomous mobile UI execution loop."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from atestservice.exploration.config import AgentConfig
from atestservice.runtime.events import NoopAgentEventPublisher
from atestservice.llm import LLMCallOptions, StructuredLLM, create_llm
from atestservice.exploration.context import AgentLoopContext, tool_result_content
from atestservice.exploration.decisions import LoopActionDecision
from atestservice.exploration.prompts import SYSTEM_PROMPT
from atestservice.exploration.context.rendering import (
    render_recent_step_actions,
    render_step_task_text,
)
from atestservice.exploration.context.facts import parameter_action_ledger
from atestservice.exploration.tools import (
    EXPLORE_ACTION_TOOLS,
    ActionExecutor,
    tool_call_to_decision,
)
from atestservice.exploration.trace import build_operation_entry
from atestservice.exploration.observations import ObservationStore
from atestservice.exploration.observations.media import screen_size_from_snapshot
from atestservice.exploration._runtime import ExplorationInput, StepLoopUpdate
from atestservice.exploration.policy import validate_action, validate_action_transition, validate_completion
from atestservice.exploration.progress import InstructionProgress
from atestservice.contracts.execution import normalize_execution, execution_succeeded
from atestservice.exploration.checkpoints import CheckpointRecorder
from atestservice.device.client import DeviceClient
from atestservice.runtime.event_payloads import json_event, screenshot_event, text_event

_EXPLORE_OPTIONS = LLMCallOptions(
    temperature=0.2,
    top_p=0.9,
    max_completion_tokens=2048,
    timeout=90.0,
    structured_output_method="function_calling",
)


class ExploreAgentLoopNode:
    """Run the agent loop for exactly one current_step."""

    def __init__(
        self,
        *,
        action_client: DeviceClient,
        llm: StructuredLLM | None = None,
        config: AgentConfig | None = None,
    ):
        self.config = config or AgentConfig()
        self.observation_store = ObservationStore(action_client, config=self.config)
        self.executor = ActionExecutor(action_client)
        self.llm = llm or create_llm()

    async def __call__(self, state: ExplorationInput) -> StepLoopUpdate:
        publisher = state.get("event_publisher") or NoopAgentEventPublisher()
        current_step = state.get("current_step") if isinstance(state.get("current_step"), dict) else None
        if not current_step:
            return _step_failed_update(
                trajectory=_trajectory_copy(state.get("trajectory")),
                step_result={
                    "step_id": None,
                    "status": "error",
                    "summary": "缺少 current_step，无法执行目标块。",
                                    },
            )

        step_id = str(current_step.get("id") or "").strip() or "unknown_step"
        await publisher.node_started(
            stage="exploration",
            node="step_agent_loop",
            label=f"正在执行目标块 {step_id}",
        )

        trajectory = _trajectory_copy(state.get("trajectory"))
        observations = trajectory["observations"]
        operations = trajectory["operations"]
        step_results = state.get("step_results") or []
        run = dict(state.get("run") or {})
        max_rounds = int(run.get("step_max_rounds") or self.config.step_attempt_limit)
        execution_error_count = 0

        instructions = current_step.get("instructions") or [{"id": step_id + "_instruction", "text": current_step["goal"]}]
        max_rounds = max(max_rounds, len(instructions) * self.config.step_attempt_limit)
        progress = InstructionProgress(instructions)
        recorder = CheckpointRecorder(state.get("case_spec") or {}, step_id)
        checkpoints = recorder.records
        consecutive_observes = 0
        observe_wait = 0.0

        def capture(instruction_id, position):
            recorder.capture(instruction_id, position, observations, operations)

        def fail(*, trajectory, step_result):
            step_result["checkpoints"] = list(checkpoints)
            step_result["instruction_results"] = progress.snapshot()
            return _step_failed_update(trajectory=trajectory, step_result=step_result)

        async def reject_finish(event: dict[str, Any], message: str, *, title: str = "目标块结束请求未通过") -> None:
            await publisher.node_finished(
                stage="exploration", node="step_finish_rejected",
                payload={**event, "title": title,
                         "blocks": [{"type": "text", "text": message}, *event["blocks"][1:]]},
            )

        task_text = render_step_task_text(
            current_step=current_step,
            step_results=step_results,
        )
        context = AgentLoopContext(
            system_prompt=SYSTEM_PROMPT,
            task_text=task_text,
        )

        if not observations:
            observations.append(await self._observe_and_record(index=0, publisher=publisher))

        capture(None, "before")
        capture(instructions[0]["id"], "before")
        for round_index in range(1, max_rounds + 1):
            active = instructions[progress.index] if progress.index < len(instructions) else None
            next_instruction = instructions[progress.index + 1] if progress.index + 1 < len(instructions) else None
            current_step["active_instruction_id"] = active["id"] if active else None
            context.task_text = render_step_task_text(current_step=current_step, step_results=step_results)
            context.task_text += "\n已报告完成的要求 ID：" + json.dumps([i["id"] for i in instructions[:progress.index]])
            context.task_text += "\n当前要求 ID：" + (active["id"] if active else "全部已报告完成，请结束当前块。")
            context.task_text += "\n紧邻的下一条要求：" + (
                json.dumps(next_instruction, ensure_ascii=False) if next_instruction else
                "无；动作的complete_current_instruction必须为false，完成后用CompleteStep结束。"
            )
            context.task_text += "\n次数与时长账本（全块累计；requested_total 是请求量，不是实测完成量）：\n" + json.dumps(
                parameter_action_ledger(trajectory, step_id), ensure_ascii=False)
            current_observation = observations[-1]
            captured_at = current_observation.get("capture_finished_at")
            if captured_at:
                from datetime import datetime, timezone
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(captured_at)).total_seconds()
                if age > self.config.observation_max_age_seconds:
                    current_observation = await self._observe_and_record(index=len(observations), publisher=publisher)
                    current_observation["capture_reason"] = "pre_decision_refresh"
                    observations.append(current_observation)
            state["current_observation_id"] = current_observation["id"]
            recent_actions = render_recent_step_actions(
                trajectory=trajectory,
                step_id=step_id,
                limit=6,
            )
            progress_summary = "当前目标块已执行动作：\n" + recent_actions
            messages = context.build_messages(
                llm=self.llm,
                observation=current_observation,
                progress_summary=progress_summary,
            )

            assistant_message = await self.llm.invoke_tool_message(
                messages, EXPLORE_ACTION_TOOLS, options=_EXPLORE_OPTIONS
            )
            tool_calls = getattr(assistant_message, "tool_calls", None) or []
            if len(tool_calls) != 1:
                return fail(
                    trajectory=trajectory,
                    step_result={
                        "step_id": step_id,
                        "status": "error",
                        "summary": f"模型工具调用数量异常：expected exactly one tool call, got {len(tool_calls)}",
                        },
                )

            tool_call = tool_calls[0]
            tool_call_id = str(tool_call.get("id") or f"call_{len(operations) + 1}")
            try:
                decision = tool_call_to_decision(tool_call)
            except Exception as exc:
                execution_error_count += 1
                if execution_error_count >= self.config.execution_error_limit:
                    return fail(
                        trajectory=trajectory,
                        step_result={
                            "step_id": step_id,
                            "status": "error",
                            "summary": f"工具调用无效且重试超限：{exc}",
                                },
                    )
                context.record_result(tool_result_content(
                        execution={
                            "success": False,
                            "message": f"工具调用无效：{exc}。请修正后重新调用。",
                        }
                    ),
                )
                continue

            decision_event = _decision_event(
                round_index=round_index,
                decision=decision,
                tool_call=tool_call,
                step_id=step_id,
            )
            if decision.kind not in {"finish", "blocker"}:
                await publisher.node_finished(
                    stage="exploration", node="agent_decision", payload=decision_event,
                )

            if active is not None and decision.kind == "instruction":
                try:
                    validate_completion(active, operations)
                except ValueError as exc:
                    context.last_result = {"success": False, "message": str(exc)}
                    await reject_finish(decision_event, str(exc), title="指令完成请求未通过")
                    continue

            if decision.kind == "observe":
                wait = decision.raw_args.get("wait_seconds", 0)
                consecutive_observes += 1
                observe_wait += wait
                if consecutive_observes > self.config.consecutive_observe_limit or observe_wait > self.config.observe_wait_budget_seconds:
                    return fail(trajectory=trajectory, step_result={"step_id": step_id, "status": "blocked",
                        "summary": "额外观察预算已耗尽，页面仍无法继续。"})
                await asyncio.sleep(wait)
                try:
                    refreshed = await self._observe_and_record(index=len(observations), publisher=publisher)
                except Exception as exc:
                    return fail(trajectory=trajectory, step_result={"step_id": step_id, "status": "blocked",
                        "summary": str(exc)})
                refreshed["capture_reason"] = "model_observe"
                observations.append(refreshed)
                context.last_result = {"success": True, "message": "已刷新页面，未执行手机操作。"}
                continue

            if decision.kind == "instruction":
                if active is None:
                    context.record_result({"success": False, "message": "没有待完成指令，请调用CompleteStep结束目标块。"})
                    continue
                if active is not None:
                    capture(active["id"], "after")
                    progress.complete()
                    if progress.index < len(instructions):
                        capture(instructions[progress.index]["id"], "before")
                await publisher.node_finished(stage="exploration", node="instruction_completed",
                    payload=json_event("指令进度", decision.reason, f"{step_id}_progress_{progress.index}.json",
                        {"step_id": step_id, "completed_instruction_id": active["id"] if active else None,
                         "checkpoints": checkpoints}))
                context.record_result({"success": active is not None, "message": "指令已记录，继续下一条。" if active else "没有待完成指令。"})
                continue

            if decision.kind == "finish" and decision.status == "completed":
                remaining = len(instructions) - progress.index
                if remaining > 1:
                    message = "仍有多条未完成的指令，请先完成当前指令并调用 CompleteInstruction。"
                    context.record_result({"success": False, "message": message})
                    await reject_finish(decision_event, message)
                    continue
                if active is not None:
                    try:
                        validate_completion(active, operations)
                    except ValueError as exc:
                        context.record_result({"success": False, "message": str(exc)})
                        await reject_finish(decision_event, str(exc))
                        continue
                    capture(active["id"], "after")
                    progress.complete()

            if decision.kind == "finish":
                capture(None, "after")
                status = decision.status or "completed"
                step_result = {
                    "step_id": step_id,
                    "status": status,
                    "summary": decision.reason,
                    "checkpoints": checkpoints,
                    "instruction_results": progress.snapshot(),
                }
                context.record_result(tool_result_content(
                        execution={"success": status == "completed", "message": decision.reason}
                    ),
                )
                return {"trajectory": trajectory, "current_step_result": step_result,
                        "completion_event": decision_event}

            if decision.kind == "blocker":
                update = fail(
                    trajectory=trajectory,
                    step_result={
                        "step_id": step_id,
                        "status": "blocked",
                        "summary": decision.reason,
                        },
                )
                update["completion_event"] = decision_event
                return update

            if decision.action is None:
                return fail(
                    trajectory=trajectory,
                    step_result={
                        "step_id": step_id,
                        "status": "error",
                        "summary": "模型动作决策缺少 action。",
                        },
                )

            if active is None:
                context.record_result({"success": False, "message": "全部指令已经完成，请结束当前块。"})
                continue
            try:
                advance = decision.raw_args.get("complete_current_instruction", False)
                if advance:
                    validate_action_transition(active, next_instruction, decision.action, operations)
                else:
                    validate_action(active, decision.action)
            except ValueError as exc:
                context.last_result = {"success": False, "message": str(exc)}
                await publisher.node_finished(stage="exploration", node="action_rejected", payload=text_event("动作未下发", str(exc)))
                continue
            consecutive_observes = 0
            self.executor.set_screen_size(screen_size_from_snapshot(current_observation))
            if advance:
                # All deterministic checks passed. Bind the old boundary before
                # recording or dispatching the action for the next instruction.
                completed_instruction_id = active["id"]
                capture(completed_instruction_id, "after")
                progress.complete()
                active = instructions[progress.index]
                current_step["active_instruction_id"] = active["id"]
                capture(active["id"], "before")
                await publisher.node_finished(
                    stage="exploration", node="instruction_completed",
                    payload=json_event("指令完成", f"已完成 {completed_instruction_id}，接下来执行 {active['id']}。",
                        f"{step_id}_progress_{progress.index}.json",
                        {"step_id": step_id, "completed_instruction_id": completed_instruction_id,
                         "next_instruction_id": active["id"], "checkpoints": list(checkpoints)}),
                )
            operation_index = len(operations)
            operation_entry = build_operation_entry(index=operation_index, decision=decision,
                action=decision.action, execution={"success": False, "status": "pending"},
                raw_tool_call=tool_call, before_observation=current_observation,
                after_observation={}, current_step=current_step)
            operations.append(operation_entry)
            await publisher.node_started(stage="exploration", node="action_started", label=decision.reason)
            execution = normalize_execution(await self.executor.execute(decision.action))
            operation_entry["execution"] = execution
            await self._settle_after_action(decision)
            try:
                next_observation = await self._observe_and_record(index=len(observations), publisher=publisher)
            except Exception as exc:
                operation_entry["observation_error"] = str(exc)
                return fail(trajectory=trajectory, step_result={
                    "step_id": step_id, "status": "blocked", "summary": f"动作已记录，但后续页面采集失败：{exc}",
                    "checkpoints": checkpoints})
            next_observation["capture_reason"] = "after_action"
            observations.append(next_observation)
            operation_entry["observation_transition"]["after_observation_id"] = next_observation["id"]
            if execution["status"] == "unknown":
                return fail(trajectory=trajectory, step_result={
                    "step_id": step_id, "status": "blocked", "summary": "命令结果未知，已重新观察，停止以避免重复提交。",
                    "checkpoints": checkpoints})

            await publisher.node_finished(
                stage="exploration",
                node="action_executed",
                payload=_action_execution_event(
                    round_index=operation_index + 1,
                    operation=operation_entry,
                ),
            )

            context.record_result(tool_result_content(execution=execution),
            )

            if not execution_succeeded(execution):
                execution_error_count += 1
                if execution_error_count >= self.config.execution_error_limit:
                    return fail(
                        trajectory=trajectory,
                        step_result={
                            "step_id": step_id,
                            "status": "error",
                            "summary": "连续动作执行失败次数过多。",
                                },
                    )
            else:
                execution_error_count = 0

        return fail(
            trajectory=trajectory,
            step_result={
                "step_id": step_id,
                "status": "error",
                "summary": "当前目标块达到最大动作轮次仍未完成。",
            },
        )

    async def _observe_and_record(self, *, index: int, publisher: Any) -> dict[str, Any]:
        observation = await self.observation_store.observe(index=index)
        data = observation.model_dump(mode="json")
        await publisher.node_finished(
            stage="exploration",
            node="observe",
            payload=screenshot_event(
                "已获取当前页面截图",
                "已获取当前页面截图。",
                observation.screenshot.filename,
            ),
        )
        return data

    async def _settle_after_action(self, decision: LoopActionDecision) -> None:
        if decision.action is None:
            return
        if decision.action.action == "start_app":
            await asyncio.sleep(2.0)
        elif decision.action.action == "wait":
            await asyncio.sleep(0.2)
        else:
            await asyncio.sleep(1.0)


def _decision_event(
    *,
    round_index: int,
    decision: LoopActionDecision,
    tool_call: dict[str, Any],
    step_id: str,
) -> dict[str, Any]:
    payload = {
        "round": round_index,
        "step_id": step_id,
        "kind": decision.kind,
        "tool_name": decision.raw_tool_name,
        "reason": decision.reason,
        "status": decision.status,
        "action": (
            {
                "type": decision.action.action,
                "args": decision.action.args.model_dump(mode="json", exclude_none=True),
            }
            if decision.action is not None
            else None
        ),
        "raw_tool_call": tool_call,
    }
    lines = [
        f"第 {round_index} 轮模型决策",
        f"目标块：{step_id}",
        f"工具：{decision.raw_tool_name}",
        f"说明：{decision.reason}",
    ]
    return json_event(
        f"模型决策 #{round_index}",
        "\n".join(lines),
        f"agent_decision_{round_index:04d}.json",
        payload,
    )


def _action_execution_event(
    *,
    round_index: int,
    operation: dict[str, Any],
) -> dict[str, Any]:
    intent = operation.get("intent") if isinstance(operation.get("intent"), dict) else {}
    action = operation.get("action") if isinstance(operation.get("action"), dict) else {}
    execution = operation.get("execution") if isinstance(operation.get("execution"), dict) else {}
    semantic_ref = operation.get("semantic_ref") if isinstance(operation.get("semantic_ref"), dict) else {}
    transition = operation.get("observation_transition") if isinstance(operation.get("observation_transition"), dict) else {}
    success = execution_succeeded(execution)
    lines = [
        f"第 {round_index} 轮动作执行",
        f"目标块：{semantic_ref.get('step_id') or '未知'}",
        f"工具：{intent.get('tool_name') or '未知'}",
        f"动作：{action.get('type') or '未知'}",
        f"结果：{'成功' if success else '失败'}",
        f"消息：{execution.get('message') or ''}",
    ]
    if transition.get("before_observation_id") or transition.get("after_observation_id"):
        lines.append(
            "状态变化："
            f"{transition.get('before_observation_id') or '未知'} -> "
            f"{transition.get('after_observation_id') or '未知'}"
        )
    return json_event(
        f"动作执行 #{round_index}",
        "\n".join(lines),
        f"operation_{round_index:04d}.json",
        operation,
    )


def _trajectory_copy(value: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        return {"observations": [], "operations": []}
    observations = value.get("observations")
    operations = value.get("operations")
    return {
        "observations": list(observations) if isinstance(observations, list) else [],
        "operations": list(operations) if isinstance(operations, list) else [],
    }


def _step_failed_update(
    *,
    trajectory: dict[str, list[dict[str, Any]]],
    step_result: dict[str, Any],
) -> StepLoopUpdate:
    return {"trajectory": trajectory, "current_step_result": step_result}
