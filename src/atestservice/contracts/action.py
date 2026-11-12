"""系统内部标准动作协议。

这里定义的是已经解析完成、可被执行器和后续 trace/codegen 复用的内部动作结构。
不要把这里的 schema 直接当作 LLM tool schema；面向模型的工具定义位于
``exploration.tools.tool_definitions``。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator


class ClickPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0, le=1000)
    y: int = Field(ge=0, le=1000)


class ClickBounds(RootModel[tuple[
    Annotated[int, Field(ge=0, le=1000)],
    Annotated[int, Field(ge=0, le=1000)],
    Annotated[int, Field(ge=0, le=1000)],
    Annotated[int, Field(ge=0, le=1000)],
]]):
    """Normalized bounds [x1, y1, x2, y2]."""

    @model_validator(mode="after")
    def validate_bounds(self) -> "ClickBounds":
        if self.x2 <= self.x1:
            raise ValueError("bounds requires x2 > x1")
        if self.y2 <= self.y1:
            raise ValueError("bounds requires y2 > y1")
        return self

    @property
    def x1(self) -> int:
        return self.root[0]

    @property
    def y1(self) -> int:
        return self.root[1]

    @property
    def x2(self) -> int:
        return self.root[2]

    @property
    def y2(self) -> int:
        return self.root[3]

    def center_point(self) -> ClickPoint:
        """Return the normalized center point of these bounds."""

        return ClickPoint(
            x=round((self.x1 + self.x2) / 2),
            y=round((self.y1 + self.y2) / 2),
        )


class ActionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bounds: ClickBounds | None = None
    text: str | None = None
    direction: Literal["up", "down", "left", "right"] | None = None
    times: int | None = Field(default=None, ge=1, le=10)
    interval: float | None = Field(default=None, ge=0)
    start: ClickPoint | None = None
    end: ClickPoint | None = None
    duration: float | None = Field(default=None, gt=0)
    app_name: str | None = None


ActionType = Literal[
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
    ]


class ResolvedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ActionType
    args: ActionArgs = Field(default_factory=ActionArgs)

    @model_validator(mode="after")
    def validate_action(self) -> "ResolvedAction":
        args = self.args

        if (
            self.action in {"click", "double_click", "long_click"}
            and args.bounds is None
        ):
            raise ValueError(f"{self.action} requires args.bounds")
        if self.action == "input_text" and not args.text:
            raise ValueError("input_text requires args.text")
        if self.action == "swipe":
            has_direction = args.direction is not None
            has_points = args.start is not None or args.end is not None
            if has_direction == has_points:
                raise ValueError("swipe requires either direction or start/end")
            if has_points and (args.start is None or args.end is None):
                raise ValueError(
                    "coordinate swipe requires both args.start and args.end"
                )
        if self.action == "drag" and (args.start is None or args.end is None):
            raise ValueError("drag requires args.start and args.end")
        if self.action == "start_app" and not args.app_name:
            raise ValueError("start_app requires args.app_name")
        if self.action == "wait" and args.duration is None:
            raise ValueError("wait requires args.duration")

        return self
