"""VS Code 插件 WebSocket 协议 helper。"""

from __future__ import annotations

import uuid
from typing import Any

MSG_REGISTER = "register"
MSG_HELLO = "hello"
MSG_HEARTBEAT = "heartbeat"
MSG_HEARTBEAT_ACK = "heartbeat_ack"
MSG_COMMAND = "command"
MSG_COMMAND_RESULT = "command_result"
MSG_EVENT = "event"
MSG_LOG = "log"


def new_command_id() -> str:
    """生成服务端下发命令 ID。"""

    return f"cmd_{uuid.uuid4().hex}"


def make_hello(plugin_session_id: str) -> dict[str, Any]:
    return {
        "type": MSG_HELLO,
        "pluginSessionId": plugin_session_id,
        "message": "registered",
    }


def make_heartbeat_ack(timestamp: Any = None) -> dict[str, Any]:
    message: dict[str, Any] = {"type": MSG_HEARTBEAT_ACK}
    if timestamp is not None:
        message["timestamp"] = timestamp
    return message


def make_command(
    *,
    command_id: str,
    command: str,
    params: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "type": MSG_COMMAND,
        "command_id": command_id,
        "command": command,
        "params": params or {},
    }
    if run_id:
        message["run_id"] = run_id
    return message


def make_success(command_id: str, data: Any = None) -> dict[str, Any]:
    return {
        "type": MSG_COMMAND_RESULT,
        "command_id": command_id,
        "success": True,
        "data": data,
        "error": None,
    }


def make_error(command_id: str, code: str, message: str) -> dict[str, Any]:
    return {
        "type": MSG_COMMAND_RESULT,
        "command_id": command_id,
        "success": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
        },
    }
