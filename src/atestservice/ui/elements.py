"""控件的统一数据处理与基础查询，不负责模型筛选或脚本编码。

观察入库时统一插件字段；bounds 统一为 0～1000，节点 ID 只在当前快照内有效。
"""
from collections import Counter

from atestservice.ui.coordinate import parse_bounds, to_normalized_bounds


def normalize_elements(elements, screen_size):
    """整理插件的像素控件列表，入库前统一坐标；不推断状态或选择操作目标。"""
    elements = [item for item in elements if isinstance(item, dict)]
    paths = [_node_path(raw.get("node_path")) for raw in elements]
    path_counts = Counter(path for path in paths if path is not None)
    path_map = {path: f"e{index}" for index, path in enumerate(paths)
                if path is not None and path_counts[path] == 1}
    result = []
    for index, raw in enumerate(elements):
        path = paths[index]
        parent = None
        if path is not None:
            # 中间节点可能被插件过滤，寻找最近的已保留祖先，不要求直接父节点存在。
            for depth in range(len(path) - 1, 0, -1):
                parent = path_map.get(path[:depth])
                if parent is not None:
                    break
        bounds = parse_bounds(raw.get("bounds"))
        if bounds and (bounds[2] <= bounds[0] or bounds[3] <= bounds[1]):
            bounds = None
        if bounds is not None:
            bounds = to_normalized_bounds(bounds, screen_size)
        result.append({
            "id": f"e{index}",
            "resource_id": _string(raw, "resource_id", "resourceId", "resource-id"),
            "text": raw.get("text") if isinstance(raw.get("text"), str) else None,
            "description": _string(raw, "description", "desc", "content-desc", "contentDescription"),
            "class_name": _string(raw, "class_name", "className", "class"),
            "bounds": bounds,
            **{key: boolean_value(raw.get(key))
               for key in ("clickable", "checked", "checkable", "selected", "enabled")},
            "parent_id": parent,
            "node_path": list(path) if path is not None else None,
            "hint": _string(raw, "hint", "hintText"),
            "placeholder": _string(raw, "placeholder"),
        })
    return result


def _string(raw, *keys):
    return next((raw[key] for key in keys if isinstance(raw.get(key), str) and raw[key]), None)


def _node_path(value):
    if isinstance(value, (list, tuple)) and value and all(type(part) is int and part >= 0 for part in value):
        return tuple(value)
    return None


def boolean_value(value):
    """仅接受实际布尔值或布尔字符串，缺失与其他类型保持未知。"""
    if type(value) is bool:
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    return None


def contains(outer, inner):
    """判断同一坐标空间内的矩形包含关系。"""
    return bool(outer and inner and outer[0] <= inner[0] and outer[1] <= inner[1]
                and outer[2] >= inner[2] and outer[3] >= inner[3])


def intersects(a, b):
    """判断两个矩形是否有正面积交集。"""
    return bool(a and b and min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1]))


def matches(element, selector):
    """按选择器中实际提供的属性匹配控件。"""
    return all(element.get(k) == v for k, v in selector.model_dump(exclude_none=True).items())
