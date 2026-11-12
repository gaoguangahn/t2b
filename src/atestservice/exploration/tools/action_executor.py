"""Execute validated internal ResolvedAction objects through DeviceClient."""

from __future__ import annotations

import asyncio

from atestservice.contracts.action import ActionArgs, ClickPoint, ResolvedAction
from atestservice.contracts.observation import ScreenSize
from atestservice.device.client import DeviceClient


class ActionExecutor:
    """Execute whitelisted plugin actions."""

    SUPPORTED_ACTIONS = {
        "click",
        "double_click",
        "long_click",
        "input_text",
        "swipe",
        "drag",
        "back",
        "home",
        "open_multitask",
        "open_control",
        "open_notification",
        "start_app",
        "stop_app",
        "wait",
    }

    def __init__(
        self,
        action_client: DeviceClient,
        *,
        screen_size: ScreenSize | None = None,
    ):
        self.action_client = action_client
        self.screen_size = screen_size

    def set_screen_size(self, screen_size: ScreenSize | None) -> None:
        """Update screen size used by coordinate actions."""

        self.screen_size = screen_size

    async def execute(self, action: ResolvedAction) -> dict:
        """Execute a resolved internal action."""

        if action.action not in self.SUPPORTED_ACTIONS:
            return {"success": False, "message": f"unsupported action: {action.action}"}

        try:
            result = await self._execute(action)
            return self._normalize_result(result)
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    async def _execute(self, action: ResolvedAction) -> dict:
        args = action.args
        action_name = action.action

        if action_name == "click":
            x, y = self._to_pixel_point(self._require_click_point(args))
            return await self.action_client.click(x, y)

        if action_name == "double_click":
            x, y = self._to_pixel_point(self._require_click_point(args))
            return await self.action_client.double_click(x, y)

        if action_name == "long_click":
            x, y = self._to_pixel_point(self._require_click_point(args))
            return await self.action_client.long_click(x, y)

        if action_name == "input_text":
            return await self.action_client.input_text(self._require_text(args))

        if action_name == "swipe":
            times = args.times or 1
            interval = float(args.interval if args.interval is not None else 1.0)

            if args.direction is not None:
                return await self.action_client.swipe(
                    direction=args.direction,
                    times=times,
                    interval=interval,
                )

            start = self._to_pixel_point(self._require_start(args))
            end = self._to_pixel_point(self._require_end(args))
            return await self.action_client.swipe(
                start=start,
                end=end,
                times=times,
                interval=interval,
            )

        if action_name == "drag":
            start = self._to_pixel_point(self._require_start(args))
            end = self._to_pixel_point(self._require_end(args))
            return await self.action_client.drag(
                start=start,
                end=end,
                duration=float(args.duration or 1.0),
            )

        if action_name == "back":
            return await self.action_client.back()

        if action_name == "home":
            return await self.action_client.home()

        if action_name == "open_multitask":
            return await self.action_client.open_multitask()

        if action_name == "open_control":
            return await self.action_client.open_control()

        if action_name == "open_notification":
            return await self.action_client.open_notification()

        if action_name == "start_app":
            return await self.action_client.start_app(self._require_app_name(args))

        if action_name == "stop_app":
            return await self.action_client.stop_app()

        if action_name == "wait":
            duration = self._require_duration(args)
            await asyncio.sleep(duration)
            return {
                "success": True,
                "message": f"waited {duration} seconds",
                "duration": duration,
            }

        return {"success": False, "message": f"unhandled action: {action_name}"}

    @staticmethod
    def _normalize_result(result: dict) -> dict:
        """Normalize plugin action result to agent execution result."""

        if "success" in result:
            return result

        if "executed" in result:
            return {**result, "success": bool(result.get("executed"))}

        return {**result, "success": True}

    @staticmethod
    def _require_click_point(args: ActionArgs) -> ClickPoint:
        bounds = getattr(args, "bounds", None)
        if bounds is None:
            raise ValueError("click action requires args.bounds")
        return bounds.center_point()

    @staticmethod
    def _require_text(args: ActionArgs) -> str:
        if args.text is None:
            raise ValueError("input_text requires args.text")
        return args.text

    @staticmethod
    def _require_start(args: ActionArgs) -> ClickPoint:
        start = getattr(args, "start", None)
        if start is None:
            raise ValueError("coordinate action requires args.start")
        return start

    @staticmethod
    def _require_end(args: ActionArgs) -> ClickPoint:
        end = getattr(args, "end", None)
        if end is None:
            raise ValueError("coordinate action requires args.end")
        return end

    @staticmethod
    def _require_app_name(args: ActionArgs) -> str:
        if not args.app_name:
            raise ValueError("start_app requires args.app_name")
        return args.app_name

    @staticmethod
    def _require_duration(args: ActionArgs) -> float:
        if args.duration is None:
            raise ValueError("wait requires args.duration")
        return float(args.duration)

    def _to_pixel_point(self, point: ClickPoint) -> tuple[float, float]:
        if self.screen_size is None:
            raise ValueError("coordinate action requires screen_size")
        x = round(point.x / 1000 * self.screen_size.width)
        y = round(point.y / 1000 * self.screen_size.height)
        return x, y
