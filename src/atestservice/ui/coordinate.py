"""坐标基础工具：内部统一使用 0～1000，需要设备像素时显式转换。"""
import re
from math import isfinite
from typing import Any


def parse_bounds(value: Any) -> list[float] | None:
    """解析四项列表、元组或矩形字符串，保留小数，不改变坐标单位。"""
    if isinstance(value, str):
        value = re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", value)
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        numbers = [float(number) for number in value]
    except (TypeError, ValueError, OverflowError):
        return None
    if any(type(number) is bool for number in value) or not all(isfinite(number) for number in numbers):
        return None
    return numbers


def _screen_dimensions(screen_size):
    width = screen_dimension(screen_size, "width")
    height = screen_dimension(screen_size, "height")
    if width is None or height is None:
        raise ValueError("坐标转换需要有效的屏幕宽高")
    return width, height


def to_pixel_bounds(bounds: list[float], screen_size: Any) -> list[float]:
    """将 0～1000 矩形转成设备像素，返回新列表，取整由最终调用方决定。"""
    width, height = _screen_dimensions(screen_size)
    x1, y1, x2, y2 = bounds
    return [x1 * width / 1000, y1 * height / 1000, x2 * width / 1000, y2 * height / 1000]


def to_normalized_bounds(bounds: list[float], screen_size: Any) -> list[float]:
    """将设备像素矩形转成 0～1000，保留浮点精度，不覆盖输入或裁剪边界。"""
    width, height = _screen_dimensions(screen_size)
    x1, y1, x2, y2 = bounds
    return [x1 * 1000 / width, y1 * 1000 / height, x2 * 1000 / width, y2 * 1000 / height]


def bounds_to_normalized_point(bounds: Any) -> list[float] | None:
    """将 0～1000 矩形中心转换为脚本使用的 0～1 点击点。"""
    parsed_bounds = parse_bounds(bounds)
    if parsed_bounds is None:
        return None
    x1, y1, x2, y2 = parsed_bounds
    return [round(((x1 + x2) / 2) / 1000, 4), round(((y1 + y2) / 2) / 1000, 4)]


def click_point_to_normalized_point(point: Any) -> list[float] | None:
    """将工具的 0～1000 点击点转换为脚本使用的 0～1 点击点。"""
    if not isinstance(point, dict):
        return None
    try:
        x, y = float(point.get("x")), float(point.get("y"))
    except (TypeError, ValueError, OverflowError):
        return None
    if not isfinite(x) or not isfinite(y):
        return None
    return [round(x / 1000, 4), round(y / 1000, 4)]


def screen_dimension(screen_size: Any, name: str) -> int | None:
    """从屏幕尺寸模型或字典中读取正整数宽高。"""
    value = getattr(screen_size, name, None)
    if value is None and isinstance(screen_size, dict):
        value = screen_size.get(name)
    if type(value) is bool:
        return None
    try:
        dimension = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return dimension if dimension > 0 else None
