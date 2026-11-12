"""用于构建模型 Prompt 上下文的辅助函数。"""

from __future__ import annotations

from typing import Any

from atestservice.contracts.observation import ScreenSize


def package_from_snapshot(snapshot: dict[str, Any] | None) -> str | None:
    if not snapshot:
        return None
    package = snapshot.get("package")
    return package if isinstance(package, str) else None


def image_from_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extract current observation screenshot as an OpenAI image_url block."""

    if not snapshot:
        return None

    data: Any = None
    media_type: Any = None
    screenshot = snapshot.get("screenshot")
    if isinstance(screenshot, dict):
        data = screenshot.get("base64")
        media_type = screenshot.get("mime_type")

    if not data:
        data = snapshot.get("screenshot_base64")
        media_type = snapshot.get("screenshot_media_type") or snapshot.get(
            "screenshot_mime_type"
        )

    if not isinstance(data, str) or not data:
        return None
    if not isinstance(media_type, str) or not media_type.startswith("image/"):
        media_type = "image/jpeg"

    return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{data}"}}


def screen_size_from_snapshot(snapshot: dict[str, Any]) -> ScreenSize | None:
    raw_size = snapshot.get("screen_size")
    if isinstance(raw_size, dict):
        return ScreenSize.model_validate(raw_size)
    return None
