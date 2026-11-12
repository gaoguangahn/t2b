"""Observation schemas for mobile UI exploration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScreenSize(BaseModel):
    """Physical screen size in pixels."""

    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ScreenshotArtifact(BaseModel):
    """Screenshot captured for a device observation."""

    filename: str
    mime_type: str = "image/jpeg"
    base64: str | None = None


class DeviceObservation(BaseModel):
    """A full UI observation captured at one point in the trajectory."""

    id: str
    index: int = Field(ge=0)
    activity: str | None = None
    package: str | None = None
    screen_size: ScreenSize
    screenshot: ScreenshotArtifact
    elements: list[dict[str, Any]] = Field(default_factory=list)
    capture_started_at: str | None = None
    capture_finished_at: str | None = None
    limitations: list[str] = Field(default_factory=list)
    capture_reason: str = "capture"
