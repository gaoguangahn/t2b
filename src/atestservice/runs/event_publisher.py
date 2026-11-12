"""Publish lightweight run events for agent progress."""

from __future__ import annotations

import logging
from typing import Any

from atestservice.runtime.events import AgentEventPublisher
from atestservice.plugin.sessions import PluginSessionManager
from atestservice.runs.repository import RunRepository

logger = logging.getLogger("atestservice.runs.events")


class TransientAgentEventPublisher(AgentEventPublisher):
    """Push non-persisted agent progress events to the plugin."""

    def __init__(
        self,
        *,
        plugin_sessions: PluginSessionManager,
        plugin_session_id: str,
        run_id: str,
    ) -> None:
        self.plugin_sessions = plugin_sessions
        self.plugin_session_id = plugin_session_id
        self.run_id = run_id
        self.seq = 0

    async def node_started(self, *, stage: str, node: str, label: str) -> None:
        await self._push(
            {
                "type": "node_started",
                "run_id": self.run_id,
                "stage": stage,
                "node": node,
                "payload": {"title": label},
            }
        )

    async def node_finished(
        self, *, stage: str, node: str, payload: dict[str, Any]
    ) -> None:
        self.seq += 1
        await self._push_event(
            {
                "event_id": f"{self.run_id}:evt_{self.seq}",
                "run_id": self.run_id,
                "seq": self.seq,
                "type": "node_finished",
                "stage": stage,
                "node": node,
                "payload": payload,
            }
        )

    async def node_failed(
        self,
        *,
        stage: str,
        node: str,
        message: str,
    ) -> None:
        self.seq += 1
        await self._push_event(
            {
                "event_id": f"{self.run_id}:evt_{self.seq}",
                "run_id": self.run_id,
                "seq": self.seq,
                "type": "node_failed",
                "stage": stage,
                "node": node,
                "payload": {
                    "title": f"{label_node(node)}执行失败",
                    "blocks": [{"type": "text", "text": message}],
                },
            }
        )

    async def _push_event(self, event: dict[str, Any]) -> None:
        await self._push(
            {
                "type": "run_event",
                "run_id": self.run_id,
                "event": event,
            }
        )

    async def _push(self, message: dict[str, Any]) -> None:
        try:
            await self.plugin_sessions.send_event(self.plugin_session_id, message)
        except Exception as exc:
            logger.info("failed to push transient event: %s", exc)


class RunAgentEventPublisher(AgentEventPublisher):
    """Persist finished node events and push runtime events to the plugin."""

    def __init__(
        self,
        *,
        repository: RunRepository,
        plugin_sessions: PluginSessionManager,
        user_id: str,
        run_id: str,
        plugin_session_id: str,
    ) -> None:
        self.repository = repository
        self.plugin_sessions = plugin_sessions
        self.user_id = user_id
        self.run_id = run_id
        self.plugin_session_id = plugin_session_id

    async def node_started(self, *, stage: str, node: str, label: str) -> None:
        await self._update_progress(stage=stage, node=node)
        await self._push(
            {
                "type": "node_started",
                "run_id": self.run_id,
                "stage": stage,
                "node": node,
                "payload": {"title": label},
            }
        )

    async def node_finished(
        self, *, stage: str, node: str, payload: dict[str, Any]
    ) -> None:
        await self._update_progress(stage=stage, node=node)
        event = await self.repository.append_event(
            self.user_id,
            self.run_id,
            "node_finished",
            payload,
            stage=stage,
            node=node,
        )
        await self._push_event(event.model_dump(mode="json"))

    async def node_failed(
        self,
        *,
        stage: str,
        node: str,
        message: str,
    ) -> None:
        await self._update_progress(stage=stage, node=node)
        event = await self.repository.append_event(
            self.user_id,
            self.run_id,
            "node_failed",
            {
                "title": f"{label_node(node)}执行失败",
                "blocks": [
                    {
                        "type": "text",
                        "text": message,
                    }
                ],
            },
            stage=stage,
            node=node,
        )
        await self._push_event(event.model_dump(mode="json"))

    async def _update_progress(self, *, stage: str, node: str) -> None:
        try:
            await self.repository.update_run_progress(
                self.user_id,
                self.run_id,
                current_stage=stage,
                current_node=node,
            )
        except Exception as exc:
            logger.warning("failed to update run progress: %s", exc)

    async def _push_event(self, event: dict[str, Any]) -> None:
        await self._push(
            {
                "type": "run_event",
                "run_id": self.run_id,
                "event": event,
            }
        )

    async def _push(self, message: dict[str, Any]) -> None:
        try:
            await self.plugin_sessions.send_event(self.plugin_session_id, message)
        except Exception as exc:
            logger.info("failed to push run event: %s", exc)


from atestservice.runtime.event_payloads import text_event, screenshot_event, json_event, python_event, label_node
