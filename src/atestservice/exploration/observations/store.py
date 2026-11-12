"""基于插件动作能力采集观察信息。"""

from __future__ import annotations

from typing import Any
from datetime import datetime, timezone

from atestservice.exploration.config import AgentConfig
from atestservice.contracts.observation import (
    DeviceObservation,
    ScreenSize,
    ScreenshotArtifact,
)
from atestservice.device.client import DeviceClient


class ObservationStore:
    """采集模型观察，并保留完整 UI 状态。"""

    def __init__(
        self, action_client: DeviceClient, *, config: AgentConfig | None = None
    ):
        self.action_client = action_client
        self.config = config or AgentConfig()

    async def observe(self, *, index: int) -> DeviceObservation:
        """采集截图、页面元素和屏幕尺寸。"""

        started_at = datetime.now(timezone.utc).isoformat()
        observation_id = f"obs_{index:04d}"
        filename = f"{observation_id}.jpg"

        status = await self.action_client.status()
        screen_size = ScreenSize(
            width=self._require_int(status, "width"),
            height=self._require_int(status, "height"),
        )

        screenshot = await self.action_client.screenshot(
            filename, scale_factor=self.config.screenshot_scale_factor
        )
        screenshot_base64 = self._optional_string(screenshot, "image")

        if screenshot_base64 is None:
            raise ValueError("Screenshot content unavailable; cannot continue visual exploration")
        page_elements = await self.action_client.page_elements(light=True)
        elements = page_elements.get("elements")
        limitations = []
        if not isinstance(elements, list):
            elements = []
            limitations.append("UI tree unavailable; visual evidence only")

        return DeviceObservation(
            id=observation_id,
            index=index,
            activity=self._optional_string(status, "activity_name"),
            package=self._optional_string(status, "package_name"),
            screen_size=screen_size,
            screenshot=ScreenshotArtifact(
                filename=filename,
                mime_type="image/jpeg",
                base64=screenshot_base64,
            ),
            elements=[e for e in elements if isinstance(e, dict)],
            capture_started_at=started_at,
            capture_finished_at=datetime.now(timezone.utc).isoformat(),
            limitations=limitations,
        )

    @staticmethod
    def _require_int(data: dict[str, Any], key: str) -> int:
        value = data.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"plugin response field {key} must be int")
        return value

    @staticmethod
    def _optional_string(data: dict[str, Any], key: str) -> str | None:
        value = data.get(key)
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _require_list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
        value = data.get(key)
        if not isinstance(value, list):
            raise TypeError(f"plugin response field {key} must be list")
        return [item for item in value if isinstance(item, dict)]
