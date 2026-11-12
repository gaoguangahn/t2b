"""插件 WebSocket 路由。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from atestservice.auth import get_websocket_user
from atestservice.config import ServerSettings
from atestservice.plugin import protocol
from atestservice.plugin.sessions import PluginSession, PluginSessionManager

logger = logging.getLogger("atestservice.plugin")
router = APIRouter()


@router.websocket("/ws/plugin")
async def plugin_websocket(websocket: WebSocket) -> None:
    """接收 VS Code 插件长连接。"""

    await websocket.accept()

    settings: ServerSettings = websocket.app.state.settings
    manager: PluginSessionManager = websocket.app.state.plugin_sessions
    session: PluginSession | None = None

    try:
        user = get_websocket_user(websocket, settings)
        register_message = await websocket.receive_json()
        session = await _register_plugin(manager, websocket, user.user_id, register_message)
        await websocket.send_json(protocol.make_hello(session.plugin_session_id))
        logger.info(
            "plugin registered: user=%s session=%s instance=%s capabilities=%s",
            session.user_id,
            session.plugin_session_id,
            session.plugin_instance_id,
            session.capabilities,
        )

        while True:
            message = await websocket.receive_json()
            await _handle_message(manager, session, message)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("plugin websocket error: %s", exc)
        await _close_safely(websocket, str(exc)[:120])
    finally:
        if session is not None:
            await manager.unregister(session.plugin_session_id)
            logger.info("plugin disconnected: session=%s", session.plugin_session_id)


async def _register_plugin(
    manager: PluginSessionManager,
    websocket: WebSocket,
    user_id: str,
    message: dict[str, Any],
) -> PluginSession:
    if message.get("type") != protocol.MSG_REGISTER:
        raise ValueError("first plugin message must be register")

    plugin_instance_id = message.get("pluginInstanceId")
    if not isinstance(plugin_instance_id, str) or not plugin_instance_id.strip():
        raise ValueError("register.pluginInstanceId is required")

    metadata = message.get("metadata")
    capabilities = message.get("capabilities")

    return await manager.register(
        websocket=websocket,
        user_id=user_id,
        plugin_instance_id=plugin_instance_id,
        metadata=metadata if isinstance(metadata, dict) else {},
        capabilities=[item for item in capabilities if isinstance(item, str)]
        if isinstance(capabilities, list)
        else [],
    )


async def _handle_message(
    manager: PluginSessionManager,
    session: PluginSession,
    message: dict[str, Any],
) -> None:
    session.touch()
    message_type = message.get("type")

    if message_type == protocol.MSG_HEARTBEAT:
        await session.websocket.send_json(protocol.make_heartbeat_ack(message.get("timestamp")))
        return

    if message_type == protocol.MSG_COMMAND_RESULT:
        manager.resolve_command(session.plugin_session_id, message)
        return

    if message_type in {protocol.MSG_LOG, protocol.MSG_EVENT}:
        logger.info(
            "plugin %s %s: %s",
            session.plugin_session_id,
            message_type,
            message,
        )
        return

    logger.warning("unknown plugin message: session=%s message=%s", session.plugin_session_id, message)


async def _close_safely(websocket: WebSocket, reason: str) -> None:
    try:
        await websocket.close(code=1011, reason=reason)
    except RuntimeError:
        pass
