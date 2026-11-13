"""统一坐标下的候选空间关系，不负责判断语义或选择最终控件。"""
from math import hypot

from atestservice.ui.elements import contains
from atestservice.ui.coordinate import to_pixel_bounds


def area(bounds):
    """计算矩形面积，单位随输入坐标而定。"""
    return max(0, bounds[2] - bounds[0]) * max(0, bounds[3] - bounds[1]) if bounds else 0


def spatial_relation(target, candidate, screen_size):
    """输入均为 0～1000；仅在内部换算像素距离，保持横纵方向的物理尺度。"""
    if not area(target) or not area(candidate):
        return {"relation": "unavailable", "score": 0.0}
    # 不修改保存的控件；像素换算仅服务于距离和容差计算，避免竖屏比例失真。
    target = to_pixel_bounds(target, screen_size)
    candidate = to_pixel_bounds(candidate, screen_size)
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
    # 整页容器不应仅凭面积覆盖而排在小范围的有效控件之前。
    score -= min(1, area(candidate) / (screen_size.width * screen_size.height))
    return {"relation": relation, "overlap_fraction": round(overlap, 4),
            "gap_pixels": round(gap, 2), "score": round(score, 4)}
