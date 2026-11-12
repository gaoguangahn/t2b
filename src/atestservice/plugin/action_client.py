"""服务端调用插件动作能力的异步客户端。"""

from __future__ import annotations

from typing import Any

from atestservice.plugin.sessions import PluginSessionError, PluginSessionManager


class PluginActionClient:
    """通过插件 WebSocket 调用插件本地能力。"""

    def __init__(
        self,
        session_manager: PluginSessionManager,
        plugin_session_id: str,
        *,
        run_id: str | None = None,
    ):
        self.session_manager = session_manager
        self.plugin_session_id = plugin_session_id
        self.run_id = run_id

    async def command(
        self,
        command: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """下发插件 command。"""

        try:
            return await self.session_manager.send_command(
                self.plugin_session_id,
                command,
                params or {},
                run_id=self.run_id,
                timeout=timeout,
            )
        except PluginSessionError as exc:
            return {"success": False, "message": str(exc),
                    "execution_status": "unknown" if "timeout" in str(exc).lower() else "failed"}

    async def action(
        self,
        action: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """下发插件侧 device.action。"""

        return await self.command(
            "device.action",
            {"action": action, "arguments": arguments or {}},
            timeout=timeout,
        )

    async def status(self) -> dict[str, Any]:
        return await self.command("device.status", timeout=10.0)

    async def screen_state(self) -> dict[str, Any]:
        return await self.action("screen_state", timeout=10.0)

    async def top_activity(self) -> dict[str, Any]:
        return await self.action("top_activity", timeout=10.0)

    async def page_elements(self, light: bool = False) -> dict[str, Any]:
        return await self.action("page_elements", {"light": light}, timeout=15.0)

    async def page_icons(self, desktop_package: str) -> dict[str, Any]:
        return await self.action(
            "page_icons",
            {"desktop_package": desktop_package},
            timeout=15.0,
        )

    async def screenshot(
        self,
        name: str,
        *,
        scale_factor: float = 1.0,
    ) -> dict[str, Any]:
        return await self.action(
            "screenshot",
            {"name": name, "scale_factor": scale_factor},
            timeout=20.0,
        )

    async def click(self, x: float, y: float) -> dict[str, Any]:
        return await self.action("click", {"target": self.point(x, y)}, timeout=10.0)

    async def double_click(self, x: float, y: float) -> dict[str, Any]:
        return await self.action(
            "double_click",
            {"target": self.point(x, y), "duration": 0.1},
            timeout=10.0,
        )

    async def long_click(self, x: float, y: float) -> dict[str, Any]:
        return await self.action(
            "long_click",
            {"target": self.point(x, y), "duration": 1.0},
            timeout=10.0,
        )

    async def input_text(self, text: str) -> dict[str, Any]:
        return await self.action("input_text", {"text": text}, timeout=10.0)

    async def swipe(
        self,
        *,
        direction: str | None = None,
        start: list[float] | tuple[float, float] | None = None,
        end: list[float] | tuple[float, float] | None = None,
        times: int = 1,
        interval: float = 1.0,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {"steps": 30, "times": times, "interval": interval}

        if direction is not None:
            if start is not None or end is not None:
                raise ValueError("direction 与 start/end 不能同时使用")
            arguments["direction"] = direction
        else:
            if start is None or end is None:
                raise ValueError("必须传 direction，或同时传 start 和 end")
            arguments["start"] = list(start)
            arguments["end"] = list(end)

        return await self.action("swipe", arguments, timeout=180.0)

    async def drag(
        self,
        start: list[float] | tuple[float, float],
        end: list[float] | tuple[float, float],
        *,
        duration: float = 1.0,
    ) -> dict[str, Any]:
        return await self.action(
            "drag",
            {"start": list(start), "end": list(end), "duration": duration},
            timeout=15.0,
        )

    async def back(self) -> dict[str, Any]:
        return await self.action("back")

    async def home(self) -> dict[str, Any]:
        return await self.action("home")

    async def open_multitask(self) -> dict[str, Any]:
        return await self.action("open_multitask")

    async def open_control(self) -> dict[str, Any]:
        return await self.action("open_control")

    async def open_notification(self) -> dict[str, Any]:
        return await self.action("open_notification")

    async def start_app(self, app_name: str) -> dict[str, Any]:
        return await self.action("start_app", {"app_name": app_name}, timeout=30.0)

    async def stop_app(self) -> dict[str, Any]:
        return await self.action("stop_app", {}, timeout=15.0)

    async def script_write(
        self,
        script_name: str,
        content: str,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self.command(
            "script.write",
            {"scriptName": script_name, "content": content},
            timeout=timeout,
        )

    @staticmethod
    def point(x: float, y: float) -> dict[str, Any]:
        return {"type": "point", "x": x, "y": y}
