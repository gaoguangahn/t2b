"""Agent loop tool definitions exposed to the LLM."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from atestservice.exploration.decisions import LoopActionDecision
from atestservice.contracts.action import ResolvedAction


class _ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(
        min_length=1,
        description="一句话说明当前可见依据和动作目的。处理遮挡或纠错时说明用途；保留用户的对象选择标准，不复述整个任务，不输出长篇推理。",
    )


class _ActionToolArgs(_ToolArgs):
    complete_current_instruction: bool = Field(
        default=False,
        description="false：本动作仍在实现当前指令。true：根据本次动作执行前的页面，当前指令已完成，本动作属于紧邻的下一条指令；reason需说明完成依据和下一条动作目的。不能表示执行本动作后预计完成。没有下一条指令时必须false，最后通过CompleteStep结束。",
    )


class Click(_ActionToolArgs):
    """单击当前截图中可见且明确可交互的目标。"""

    bounds: list[int] = Field(min_length=4, max_length=4, description="目标矩形 [x1,y1,x2,y2]，0-1000 归一化坐标。")


class DoubleClick(_ActionToolArgs):
    """双击当前截图中可见目标，仅在明确需要双击时使用。"""

    bounds: list[int] = Field(min_length=4, max_length=4, description="目标矩形 [x1,y1,x2,y2]，0-1000 归一化坐标。")


class LongClick(_ActionToolArgs):
    """长按当前截图中可见目标，用于菜单、编辑或明确长按功能。"""

    bounds: list[int] = Field(min_length=4, max_length=4, description="目标矩形 [x1,y1,x2,y2]，0-1000 归一化坐标。")


class InputText(_ActionToolArgs):
    """向正确且已聚焦的输入框输入原文，不追加回车暗中提交。目标需要提交时，输入后单独执行相应动作。"""

    text: str = Field(min_length=1, description="指令指定的原文，逐字符保留空格、标点和大小写。")


class DirectionSwipe(_ActionToolArgs):
    """按方向滑动当前页面或可滚动区域。固定次数、同方向且中间无需观察或验证时，一次调用完成整组滑动。例如“向上连续滑动3次，间隔1秒”使用 direction=up、times=3、interval=1，不拆为三次调用。寻找目标、遇到目标即停止或每次滑动后需判断时，逐次滑动并观察。"""

    direction: Literal["up", "down", "left", "right"] = Field(description="手指滑动方向。")
    times: int | None = Field(default=None, ge=1, le=10, description="本次调用内连续执行的滑动次数，单次最多10次。固定次数且无需中间判断时，填写本指令尚需执行的次数，不逐次填1；超过10次才分批。按账本扣除同一指令、同一手势已成功请求的次数；不能再次填写原始总数导致重复。需逐次观察时填1；未指定次数时可填null，表示一次。")
    interval: float | None = Field(default=None, ge=0, description="本次连续滑动之间的间隔，单位秒。例如“3次，每次间隔1秒”填写times=3、interval=1，不拆成滑动与Wait交替调用。用户未指定间隔时填null，不自行补值。")


class CoordinateSwipe(_ActionToolArgs):
    """按起止点滑动，适合明确指定滑动区域的场景。同一手势需固定重复且中间无需观察或验证时，用times一次表达整组次数；每次手势使用相同起止点。寻找目标或需要逐次判断时，每次只滑一次；普通页面滚动优先DirectionSwipe。"""

    start_x: int = Field(ge=0, le=1000, description="起点 x，0-1000 归一化坐标。")
    start_y: int = Field(ge=0, le=1000, description="起点 y，0-1000 归一化坐标。")
    end_x: int = Field(ge=0, le=1000, description="终点 x，0-1000 归一化坐标。")
    end_y: int = Field(ge=0, le=1000, description="终点 y，0-1000 归一化坐标。")
    times: int | None = Field(default=None, ge=1, le=10, description="本次调用内按相同起止点连续滑动的次数，单次最多10次。固定次数且无需中间判断时一次填写剩余次数，不拆成多次调用；例如同一手势重复3次填3。超过10次分批，扣除同一指令、同一手势已成功请求的次数；需逐次观察时填1，未指定次数时可填null。")
    interval: float | None = Field(default=None, ge=0, description="本次连续滑动之间的间隔，单位秒。用户指定时与times一起填写，不拆成滑动与Wait交替调用；未指定间隔时填null。")


class Drag(_ActionToolArgs):
    """拖动明确可拖拽对象，不用于普通页面滚动。"""

    start_x: int = Field(ge=0, le=1000, description="起点 x，0-1000 归一化坐标。")
    start_y: int = Field(ge=0, le=1000, description="起点 y，0-1000 归一化坐标。")
    end_x: int = Field(ge=0, le=1000, description="终点 x，0-1000 归一化坐标。")
    end_y: int = Field(ge=0, le=1000, description="终点 y，0-1000 归一化坐标。")
    duration: float | None = Field(default=None, gt=0, description="拖动持续时间，单位秒。")


class Back(_ActionToolArgs):
    """执行一次返回。一次返回不保证到达应用首页；依据新页面决定是否继续返回或导航。"""


class Home(_ActionToolArgs):
    """返回系统桌面，仅用于明确的桌面要求；不能代替返回应用首页。"""


class OpenMultitask(_ActionToolArgs):
    """打开系统最近任务界面。"""


class OpenControl(_ActionToolArgs):
    """打开系统控制中心。"""


class OpenNotification(_ActionToolArgs):
    """打开系统通知栏。"""


class StartApp(_ActionToolArgs):
    """按指定显示名称启动或进入应用。通用启动要求使用此方法，不点击桌面图标替代，不猜相似应用。"""

    app_name: str = Field(min_length=1, description="应用显示名称，例如 设置。")


class StopApp(_ActionToolArgs):
    """仅在当前要求明确停止应用时使用。不能为返回首页、关闭面板或绕过阻塞而自行重置应用。"""


class Wait(_ActionToolArgs):
    """执行用户明确要求的固定等待或观看时长。为判断加载页面而等待应使用 Observe，不能抵扣用户要求的时长。"""

    duration: float = Field(gt=0, le=10, description="本次固定等待秒数。超过单次上限时分批完成原时长，结合账本防止重复或截断。")


class CompleteStep(_ToolArgs):
    """结束当前目标块。依据最新页面确认全部操作要求已达到后调用；可同时完成最后一条指令，不需先CompleteInstruction。尚有多条待完成指令时先逐条CompleteInstruction。仅报告结果，不执行手机动作。"""

    status: Literal["completed", "error"] = Field(default="completed", description="当前目标块结果；完成单轮操作时使用 completed，执行错误时使用 error。")
    summary: str = Field(min_length=1, description="一句话总结实际完成情况及当前页面依据，或失败原因。关闭/开启等状态目标需说明对应状态；不能以点击命令成功代替目标已达到。")


class CompleteInstruction(_ToolArgs):
    """仅在最新页面表明当前语义要求已完成时调用，保存当前页面并推进下一条；不执行手机动作。一条要求可需多个动作。最后一条可直接CompleteStep，不能把动作尚未执行后的预期结果当完成。"""
    summary: str = Field(min_length=1, description="当前指令实际完成情况与当前页面依据；开关等状态目标需已达到指定状态，不只复述已点击。")


class Observe(_ToolArgs):
    """仅在加载或页面信息不足时重新观察。动作后已自动采集，无需例行调用；不是用户业务等待。"""
    wait_seconds: float = Field(default=0, ge=0, le=5)


class ReportBlocker(_ToolArgs):
    """遇到无法继续处理的阻塞，例如必须登录、缺少权限或任务信息不足。"""

    summary: str = Field(min_length=1, description="一句话总结阻塞原因和已尝试的关键动作，用于后续诊断。")


EXPLORE_ACTION_TOOLS = [
    Click, DoubleClick, LongClick, InputText, DirectionSwipe, CoordinateSwipe, Drag,
    Back, Home, OpenMultitask, OpenControl, OpenNotification, StartApp, StopApp,
    Wait, CompleteStep, CompleteInstruction, ReportBlocker, Observe,
]

_CLICK_TOOL_ACTIONS = {"Click": "click", "DoubleClick": "double_click", "LongClick": "long_click"}
_SIMPLE_TOOL_ACTIONS = {
    "Back": "back", "Home": "home", "OpenMultitask": "open_multitask",
    "OpenControl": "open_control", "OpenNotification": "open_notification", "StopApp": "stop_app",
}


def tool_call_to_decision(tool_call: dict[str, Any]) -> LoopActionDecision:
    """Convert one model tool call to an internal decision."""

    name = str(tool_call.get("name") or "")
    args = tool_call.get("args") or {}
    schema = next((tool for tool in EXPLORE_ACTION_TOOLS if tool.__name__ == name), None)
    if schema is None:
        raise ValueError(f"unknown tool: {name}")
    args = schema.model_validate(args).model_dump(exclude_none=True)

    if not isinstance(args, dict):
        raise ValueError(f"tool args must be object, got {type(args).__name__}")

    reason = str(args.get("reason") or "").strip()
    if not reason:
        raise ValueError(f"tool {name} requires reason")

    if name == "Observe":
        return LoopActionDecision(kind="observe", reason=reason, raw_tool_name=name, raw_args=args)

    if name == "CompleteStep":
        status = str(args.get("status") or "completed").strip()
        if status not in {"completed", "error"}:
            raise ValueError("CompleteStep status must be completed or error")
        summary = str(args.get("summary") or reason).strip()
        return LoopActionDecision(
            kind="finish", reason=summary, raw_tool_name=name, raw_args=args,
            status=status,
        )

    if name == "CompleteInstruction":
        return LoopActionDecision(kind="instruction", reason=str(args.get("summary") or reason), raw_tool_name=name, raw_args=args)

    if name == "ReportBlocker":
        summary = str(args.get("summary") or reason).strip()
        return LoopActionDecision(
            kind="blocker", reason=summary, raw_tool_name=name, raw_args=args,
            status="blocked",
        )

    action = _tool_call_to_action(name, args)
    return LoopActionDecision(
        kind="action", reason=reason, raw_tool_name=name, raw_args=args,
        action=action,
    )


def _tool_call_to_action(name: str, args: dict[str, Any]) -> ResolvedAction:
    if name in _CLICK_TOOL_ACTIONS:
        payload = {"action": _CLICK_TOOL_ACTIONS[name], "args": {"bounds": _bounds(args)}}
    elif name == "InputText":
        payload = {"action": "input_text", "args": {"text": args.get("text")}}
    elif name == "DirectionSwipe":
        swipe_args: dict[str, Any] = {"direction": args.get("direction")}
        if args.get("times") is not None:
            swipe_args["times"] = args.get("times")
        if args.get("interval") is not None:
            swipe_args["interval"] = args.get("interval")
        payload = {"action": "swipe", "args": swipe_args}
    elif name == "CoordinateSwipe":
        swipe_args = {
            "start": {"x": args.get("start_x"), "y": args.get("start_y")},
            "end": {"x": args.get("end_x"), "y": args.get("end_y")},
        }
        if args.get("times") is not None:
            swipe_args["times"] = args.get("times")
        if args.get("interval") is not None:
            swipe_args["interval"] = args.get("interval")
        payload = {"action": "swipe", "args": swipe_args}
    elif name == "Drag":
        drag_args: dict[str, Any] = {
            "start": {"x": args.get("start_x"), "y": args.get("start_y")},
            "end": {"x": args.get("end_x"), "y": args.get("end_y")},
        }
        if args.get("duration") is not None:
            drag_args["duration"] = args.get("duration")
        payload = {"action": "drag", "args": drag_args}
    elif name in _SIMPLE_TOOL_ACTIONS:
        payload = {"action": _SIMPLE_TOOL_ACTIONS[name], "args": {}}
    elif name == "StartApp":
        payload = {"action": "start_app", "args": {"app_name": args.get("app_name")}}
    elif name == "Wait":
        payload = {"action": "wait", "args": {"duration": args.get("duration")}}
    else:
        raise ValueError(f"unknown explore tool call: {name}")
    return ResolvedAction.model_validate(payload)


def _bounds(args: dict[str, Any]) -> list[int]:
    bounds = args.get("bounds") or []
    if len(bounds) != 4:
        raise ValueError("click bounds must be [x1,y1,x2,y2]")
    return [int(value) for value in bounds]
