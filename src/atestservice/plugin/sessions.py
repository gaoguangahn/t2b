"""插件 WebSocket 会话与 command RPC 管理。"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from atestservice.plugin import protocol


class PluginSessionError(RuntimeError):
    """插件会话异常。"""


class PluginCommandError(PluginSessionError):
    """插件命令执行失败。"""


@dataclass(slots=True)
class PendingCommand:
    command_id: str
    future: asyncio.Future[dict[str, Any]]


@dataclass(slots=True)
class PluginSession:
    """当前插件 WebSocket 连接。"""

    plugin_session_id: str
    user_id: str
    plugin_instance_id: str
    websocket: WebSocket
    metadata: dict[str, Any] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    connected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    pending: dict[str, PendingCommand] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def touch(self) -> None:
        self.last_seen_at = datetime.now(UTC)


class PluginSessionManager:
    """管理在线插件连接，并提供服务端到插件的 command RPC。"""

    def __init__(self) -> None:
        self._sessions: dict[str, PluginSession] = {}
        self._by_user: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        *,
        websocket: WebSocket,
        user_id: str,
        plugin_instance_id: str,
        metadata: dict[str, Any] | None = None,
        capabilities: list[str] | None = None,
    ) -> PluginSession:
        plugin_session_id = f"ps_{uuid.uuid4().hex}"
        session = PluginSession(
            plugin_session_id=plugin_session_id,
            user_id=user_id,
            plugin_instance_id=plugin_instance_id,
            websocket=websocket,
            metadata=metadata or {},
            capabilities=capabilities or [],
        )

        async with self._lock:
            self._sessions[plugin_session_id] = session
            self._by_user.setdefault(user_id, set()).add(plugin_session_id)

        return session

    async def unregister(self, plugin_session_id: str) -> None:
        async with self._lock:
            session = self._sessions.pop(plugin_session_id, None)
            if not session:
                return
            user_sessions = self._by_user.get(session.user_id)
            if user_sessions is not None:
                user_sessions.discard(plugin_session_id)
                if not user_sessions:
                    self._by_user.pop(session.user_id, None)

        self._reject_pending(session, "plugin session disconnected")

    def get(self, plugin_session_id: str) -> PluginSession | None:
        return self._sessions.get(plugin_session_id)

    def require(self, plugin_session_id: str) -> PluginSession:
        session = self.get(plugin_session_id)
        if session is None:
            raise PluginSessionError(f"plugin session not found: {plugin_session_id}")
        return session

    def list_user_sessions(self, user_id: str) -> list[PluginSession]:
        return [
            self._sessions[session_id]
            for session_id in self._by_user.get(user_id, set())
            if session_id in self._sessions
        ]

    def belongs_to_user(self, plugin_session_id: str, user_id: str) -> bool:
        session = self.get(plugin_session_id)
        return bool(session and session.user_id == user_id)

    async def send_event(
        self,
        plugin_session_id: str,
        message: dict[str, Any],
    ) -> None:
        session = self.require(plugin_session_id)
        if session.websocket.client_state != WebSocketState.CONNECTED:
            raise PluginSessionError(f"plugin session is not connected: {plugin_session_id}")
        async with session.send_lock:
            await session.websocket.send_json(message)

    async def send_command(
        self,
        plugin_session_id: str,
        command: str,
        params: dict[str, Any] | None = None,
        *,
        run_id: str | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        session = self.require(plugin_session_id)
        if session.websocket.client_state != WebSocketState.CONNECTED:
            raise PluginSessionError(f"plugin session is not connected: {plugin_session_id}")

        command_id = protocol.new_command_id()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        session.pending[command_id] = PendingCommand(command_id=command_id, future=future)

        message = protocol.make_command(
            command_id=command_id,
            command=command,
            params=params,
            run_id=run_id,
        )

        try:
            async with session.send_lock:
                await session.websocket.send_json(message)
            result = await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as exc:
            raise PluginSessionError(f"plugin command timeout: {command}") from exc
        finally:
            session.pending.pop(command_id, None)

        if not result.get("success", False):
            error = result.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else None
            raise PluginCommandError(message or f"plugin command failed: {command}")

        data = result.get("data")
        return data if isinstance(data, dict) else {"value": data}

    def resolve_command(self, plugin_session_id: str, message: dict[str, Any]) -> None:
        session = self.require(plugin_session_id)
        session.touch()

        command_id = message.get("command_id")
        if not isinstance(command_id, str):
            return

        pending = session.pending.get(command_id)
        if pending and not pending.future.done():
            pending.future.set_result(message)

    @staticmethod
    def _reject_pending(session: PluginSession, reason: str) -> None:
        for pending in list(session.pending.values()):
            if not pending.future.done():
                pending.future.set_exception(PluginSessionError(reason))
        session.pending.clear()
