"""Pixel-space relations for candidate ranking, independent of semantic policy."""
from math import hypot

from atestservice.ui.elements import contains


def area(bounds):
    return max(0, bounds[2] - bounds[0]) * max(0, bounds[3] - bounds[1]) if bounds else 0


def spatial_relation(target, candidate, screen_size):
    if not area(target) or not area(candidate):
        return {"relation": "unavailable", "score": 0.0}
    center = [(target[0] + target[2]) / 2, (target[1] + target[3]) / 2]
    intersection = max(0, min(target[2], candidate[2]) - max(target[0], candidate[0])) * max(
        0, min(target[3], candidate[3]) - max(target[1], candidate[1]))
    overlap = intersection / min(area(target), area(candidate))
    gap = hypot(max(target[0] - candidate[2], candidate[0] - target[2], 0),
                max(target[1] - candidate[3], candidate[1] - target[3], 0))
    tolerance = max(4, min(screen_size.width, screen_size.height) * 0.015)
    if area(candidate) > screen_size.width * screen_size.height * 0.7 and area(target) < area(candidate) * 0.1:
        relation = "broad_container"
    elif contains(candidate, center + center):
        relation = "point_hit"
    elif overlap >= 0.2:
        relation = "overlap"
    elif gap <= tolerance and intersection == 0:
        relation = "nearby"
    else:
        relation = "weak_or_distant"
    score = {"point_hit": 4, "overlap": 3, "nearby": 1}.get(relation, 0) + overlap
    # A whole-page parent should not outrank a small meaningful control by size.
    score -= min(1, area(candidate) / (screen_size.width * screen_size.height))
    return {"relation": relation, "overlap_fraction": round(overlap, 4),
            "gap_pixels": round(gap, 2), "score": round(score, 4)}
