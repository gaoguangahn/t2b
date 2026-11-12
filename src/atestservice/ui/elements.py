"""UI field normalization and geometric queries, independent of generation policy."""
from collections import Counter
from atestservice.ui.coordinate import parse_bounds, to_pixel_bounds


def normalize_elements(elements):
    result = []
    source_ids = [str(raw.get("node_id", raw.get("id"))) for raw in elements]
    counts = Counter(source_ids)
    source_map = {identifier: f"e{index}" for index, identifier in enumerate(source_ids)
                  if identifier != "None" and counts[identifier] == 1}
    for index, raw in enumerate(elements):
        result.append({"id": f"e{index}", "resource_id": raw.get("resource_id") or raw.get("resourceId") or raw.get("resource-id"),
                       "text": raw.get("text"), "description": raw.get("desc") or raw.get("description") or raw.get("content-desc") or raw.get("contentDescription"),
                       "class_name": raw.get("class_name") or raw.get("className") or raw.get("class"),
                       "bounds": parse_bounds(raw.get("bounds")), "clickable": boolean_value(raw.get("clickable")),
                       **{key: boolean_value(raw.get(key)) for key in ("checked", "checkable", "selected", "enabled")},
                       "parent_id": source_map.get(str(raw.get("parent_id", raw.get("parentId")))),
                       "hint": raw.get("hint") or raw.get("hintText"), "placeholder": raw.get("placeholder")})
    return result


def boolean_value(value):
    if type(value) is bool:
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return None


def contains(outer, inner):
    return bool(outer and inner and outer[0] <= inner[0] and outer[1] <= inner[1]
                and outer[2] >= inner[2] and outer[3] >= inner[3])


def intersects(a, b):
    return bool(a and b and min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1]))


def matches(element, selector):
    return all(element.get(k) == v for k, v in selector.model_dump(exclude_none=True).items())


def target_pixels(bounds, size):
    return to_pixel_bounds(list(bounds.root), size) if bounds else None
