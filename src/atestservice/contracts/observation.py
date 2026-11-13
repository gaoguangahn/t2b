"""观察快照契约：截图、设备信息，以及统一格式的完整控件列表。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScreenSize(BaseModel):
    """设备屏幕的像素尺寸，用于采集入口和按需坐标转换。"""

    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ScreenshotArtifact(BaseModel):
    """本次观察对应的截图。"""

    filename: str
    mime_type: str = "image/jpeg"
    base64: str | None = None


class DeviceObservation(BaseModel):
    """某一时刻的完整现场；控件标准化在采集入口完成。"""

    id: str
    index: int = Field(ge=0)
    activity: str | None = None
    package: str | None = None
    screen_size: ScreenSize
    screenshot: ScreenshotArtifact
    # 这里只接收已处理的控件：bounds 为 0～1000；读取快照时不再次转换。
    elements: list[dict[str, Any]] = Field(default_factory=list)
    capture_started_at: str | None = None
    capture_finished_at: str | None = None
    limitations: list[str] = Field(default_factory=list)
    capture_reason: str = "capture"
