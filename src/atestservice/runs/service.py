"""Run 创建、执行与停止服务。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from atestservice.case_preparation import prepare_case
from atestservice.exploration.config import AgentConfig
from atestservice.workflow.runner import MobileTestAgentRunner
from atestservice.auth import AuthUser
from atestservice.plugin.action_client import PluginActionClient
from atestservice.plugin.sessions import PluginSessionManager
from atestservice.runs.event_publisher import (
    RunAgentEventPublisher,
    TransientAgentEventPublisher,
    text_event,
)
from atestservice.runs.models import (
    CreateRunRequest,
    PrepareRunRequest,
    PrepareRunResponse,
    RunRecord,
    RunStatus,
)
from atestservice.runs.repository import RunRepository

logger = logging.getLogger("atestservice.runs.service")


class RunService:
    """围绕插件会话执行一次自动化生成任务。"""

    def __init__(
        self,
        *,
        repository: RunRepository,
        plugin_sessions: PluginSessionManager,
        agent_config: AgentConfig | None = None,
    ) -> None:
        self.repository = repository
        self.plugin_sessions = plugin_sessions
        self.agent_config = agent_config or AgentConfig()
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def prepare_run(
        self, user: AuthUser, request: PrepareRunRequest
    ) -> PrepareRunResponse:
        """整理一个用例，返回一个用户可编辑的草稿。"""

        session = self.plugin_sessions.get(request.pluginSessionId)
        if session is None or session.user_id != user.user_id:
            raise ValueError("plugin session not found")

        event_publisher = TransientAgentEventPublisher(
            plugin_sessions=self.plugin_sessions,
            plugin_session_id=session.plugin_session_id,
            run_id="prepare_run",
        )
        draft = await prepare_case(
            request.input,
            event_publisher=event_publisher,
        )
        return PrepareRunResponse(
            title=draft.title,
            editableText=draft.editable_text,
        )

    async def create_run(self, user: AuthUser, request: CreateRunRequest) -> RunRecord:
        """创建 run，并启动后台执行。"""

        session = self.plugin_sessions.get(request.pluginSessionId)
        if session is None or session.user_id != user.user_id:
            raise ValueError("plugin session not found")

        run = RunRecord(
            run_id=f"sr_{uuid.uuid4().hex}",
            user_id=user.user_id,
            plugin_session_id=session.plugin_session_id,
            plugin_instance_id=session.plugin_instance_id,
            editable_text=request.editableText,
            input_payload=request.model_dump(),
        )
        await self.repository.create_run(run)

        task = asyncio.create_task(self._execute_run(run))
        self._tasks[run.run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run.run_id, None))
        return run

    async def stop_run(self, user: AuthUser, run_id: str) -> RunRecord:
        """停止 run。"""

        run = await self.repository.get_run(user.user_id, run_id)
        if run is None:
            raise KeyError(f"run not found: {run_id}")

        task = self._tasks.get(run_id)
        if task and not task.done():
            task.cancel()

        event = await self.repository.append_event(
            user.user_id,
            run_id,
            "stop_requested",
            text_event("正在停止任务", "已请求停止当前任务。"),
            stage="finished",
            node="run",
        )
        await self._push_run_event(run, event.model_dump(mode="json"))
        return await self.repository.update_run_status(
            user.user_id,
            run_id,
            RunStatus.STOPPED,
        )

    async def get_run(self, user: AuthUser, run_id: str) -> RunRecord | None:
        return await self.repository.get_run(user.user_id, run_id)

    async def list_runs(self, user: AuthUser) -> list[RunRecord]:
        return await self.repository.list_runs(user.user_id)

    async def list_events(self, user: AuthUser, run_id: str):
        return await self.repository.list_events(user.user_id, run_id)

    async def _execute_run(self, run: RunRecord) -> None:
        await self.repository.update_run_status(
            run.user_id,
            run.run_id,
            RunStatus.RUNNING,
        )
        started_event = await self.repository.append_event(
            run.user_id,
            run.run_id,
            "run_started",
            text_event("任务已开始", "任务已开始执行。"),
            stage="started",
            node="run",
        )
        await self._push_run_event(run, started_event.model_dump(mode="json"))

        try:
            action_client = PluginActionClient(
                self.plugin_sessions,
                run.plugin_session_id,
                run_id=run.run_id,
            )

            result = await self._run_agent(run, action_client)
            failed = result.get("status") == "failed" or (result.get("result") or {}).get("status") == "blocked"
            failure_reason = str(result.get("failureReason") or "script_plan_blocked") if failed else None
            draft = (result.get("result") or {}).get("status") == "draft"
            event = await self.repository.append_event(
                run.user_id,
                run.run_id,
                "run_failed" if failed else "run_finished",
                text_event("任务需要复核" if failed else "任务执行完成",
                           failure_reason if failed else "脚本已输出，含待完善项。" if draft else "任务执行完成。"),
                stage="finished",
                node="run",
            )
            await self._push_run_event(run, event.model_dump(mode="json"))
            await self.repository.update_run_status(
                run.user_id,
                run.run_id,
                RunStatus.ERROR if failed else RunStatus.DONE,
                result=result,
                error=failure_reason,
            )
        except asyncio.CancelledError:
            event = await self.repository.append_event(
                run.user_id,
                run.run_id,
                "run_stopped",
                text_event("任务已停止", "任务已停止。"),
                stage="finished",
                node="run",
            )
            await self._push_run_event(run, event.model_dump(mode="json"))
            await self.repository.update_run_status(
                run.user_id,
                run.run_id,
                RunStatus.STOPPED,
            )
        except Exception as exc:
            event = await self.repository.append_event(
                run.user_id,
                run.run_id,
                "run_failed",
                text_event("任务执行失败", f"任务执行失败：{exc}"),
                stage="finished",
                node="run",
            )
            await self._push_run_event(run, event.model_dump(mode="json"))
            await self.repository.update_run_status(
                run.user_id,
                run.run_id,
                RunStatus.ERROR,
                error=str(exc),
            )

    async def _push_run_event(self, run: RunRecord, event: dict[str, Any]) -> None:
        try:
            await self.plugin_sessions.send_event(
                run.plugin_session_id,
                {
                    "type": "run_event",
                    "run_id": run.run_id,
                    "event": event,
                },
            )
        except Exception:
            pass

    async def _run_agent(
        self,
        run: RunRecord,
        action_client: PluginActionClient,
    ) -> dict[str, Any]:
        """执行异步 agent 推理流程。"""

        event_publisher = RunAgentEventPublisher(
            repository=self.repository,
            plugin_sessions=self.plugin_sessions,
            user_id=run.user_id,
            run_id=run.run_id,
            plugin_session_id=run.plugin_session_id,
        )

        runner = MobileTestAgentRunner(
            action_client=action_client,
            config=self.agent_config,
        )
        state = await runner.run(
            str(run.input_payload.get("editableText") or ""),
            event_publisher=event_publisher,
            framework=run.input_payload.get("framework"),
            run_id=run.run_id,
        )

        agent_run = state.get("run") or {}
        return {
            "runId": run.run_id,
            "status": agent_run.get("status"),
            "failureReason": agent_run.get("failure_reason"),
            "finishReason": agent_run.get("finish_reason"),
            "caseSpec": state.get("case_spec"),
            "explorationResult": state.get("exploration_result"),
            "result": state.get("result"),
        }
