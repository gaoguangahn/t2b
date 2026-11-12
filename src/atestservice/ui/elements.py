"""UI field normalization and geometric queries, independent of generation policy."""
from atestservice.ui.coordinate import parse_bounds, to_pixel_bounds


def normalize_elements(elements):
    result = []
    for index, raw in enumerate(elements):
        result.append({"id": f"e{index}", "resource_id": raw.get("resource_id") or raw.get("resourceId") or raw.get("resource-id"),
                       "text": raw.get("text"), "description": raw.get("desc") or raw.get("description") or raw.get("content-desc"),
                       "class_name": raw.get("class_name") or raw.get("className") or raw.get("class"),
                       "bounds": parse_bounds(raw.get("bounds")), "clickable": raw.get("clickable"),
                       "hint": raw.get("hint") or raw.get("hintText"), "placeholder": raw.get("placeholder")})
    return result


def contains(outer, inner):
    return bool(outer and inner and outer[0] <= inner[0] and outer[1] <= inner[1]
                and outer[2] >= inner[2] and outer[3] >= inner[3])


def intersects(a, b):
    return bool(a and b and min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1]))


def matches(element, selector):
    return all(element.get(k) == v for k, v in selector.model_dump(exclude_none=True).items())


def target_pixels(bounds, size):
    return to_pixel_bounds(list(bounds.root), size) if bounds else None
