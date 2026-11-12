import re
from typing import Any


def parse_bounds(value: Any) -> list[int] | None:
    """Parse bounds from list, tuple, or '[x1,y1][x2,y2]' string."""

    if isinstance(value, str):
        numbers = re.findall(r"-?\d+", value)

        if len(numbers) >= 4:
            return [int(number) for number in numbers[:4]]

        return None

    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return [int(number) for number in value]
        except (TypeError, ValueError):
            return None

    return None


def to_pixel_bounds(bounds: list[int], screen_size: Any | None) -> list[int]:
    """Convert normalized 0-1000 bounds to pixel bounds when possible."""

    if screen_size is None:
        return bounds

    width = screen_dimension(screen_size, "width")
    height = screen_dimension(screen_size, "height")
    if width is None or height is None:
        return bounds

    x1, y1, x2, y2 = bounds
    return [
        round(x1 * width / 1000),
        round(y1 * height / 1000),
        round(x2 * width / 1000),
        round(y2 * height / 1000),
    ]


def to_normalized_bounds(bounds: list[int], screen_size: Any | None) -> list[int]:
    """Convert pixel bounds to normalized 0-1000 bounds when possible."""

    if screen_size is None:
        return bounds

    width = screen_dimension(screen_size, "width")
    height = screen_dimension(screen_size, "height")
    if width is None or height is None:
        return bounds

    x1, y1, x2, y2 = bounds
    return [
        round(x1 * 1000 / width),
        round(y1 * 1000 / height),
        round(x2 * 1000 / width),
        round(y2 * 1000 / height),
    ]


def bounds_to_normalized_point(bounds: Any) -> list[float] | None:
    """Convert bounds center from 0-1000 coordinates to 0-1 point."""

    parsed_bounds = parse_bounds(bounds)

    if parsed_bounds is None:
        return None

    x1, y1, x2, y2 = parsed_bounds

    return [
        round(((x1 + x2) / 2) / 1000, 4),
        round(((y1 + y2) / 2) / 1000, 4),
    ]


def click_point_to_normalized_point(point: Any) -> list[float] | None:
    """Convert ClickPoint-style 0-1000 coordinates to 0-1 point."""

    if not isinstance(point, dict):
        return None

    x = point.get("x")
    y = point.get("y")

    try:
        return [
            round(float(x) / 1000, 4),
            round(float(y) / 1000, 4),
        ]
    except (TypeError, ValueError):
        return None


def screen_dimension(screen_size: Any, name: str) -> int | None:
    """Read a screen dimension from a model or dict."""

    value = getattr(screen_size, name, None)
    if value is None and isinstance(screen_size, dict):
        value = screen_size.get(name)

    try:
        dimension = int(value)
    except (TypeError, ValueError):
        return None

    return dimension if dimension > 0 else None
