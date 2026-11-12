"""Reject known unstable attributes and unsupported positional assumptions."""
import re
from atestservice.contracts.script import Selector

_DYNAMIC = re.compile(r"(?:\d[\d.,万亿kK]*\s*(?:赞|人点赞|次播放|次浏览|评论|收藏|元|%))|(?:[¥￥$]\s*\d)|(?:\b\d{1,2}:\d{2}\b)")


def selector_problem(selector: Selector, element, goal, role):
    if role == "dynamic_content":
        return "候选依赖本次展示的动态内容。"
    for key in ("text", "description"):
        value = getattr(selector, key)
        if not value:
            continue
        explicit = value in goal
        if role == "user_value" and not explicit:
            return "定位内容不是用户明确指定的原值。"
        if (value == element.get("hint") or value == element.get("placeholder")) and not explicit:
            return "不能把输入提示或推荐占位内容当作控件身份。"
        if _DYNAMIC.search(value) and not explicit:
            return "定位依赖数量、价格或时间等动态展示值。"
        if key == "text" and not explicit and re.search(r"(?:打开|进入|点击).{0,6}搜索(?:框|栏|入口|页)?", goal) and "搜索" not in value:
            return "搜索入口不能绑定本次出现的推荐文本。"
        if requested_index(goal) is not None and not explicit and key == "text" and role != "state_indicator":
            return "序号目标不能绑定本次列表条目的展示标题。"
    return None


def requested_index(goal):
    match = re.search(r"第\s*(\d+)\s*(?:条|个|项|行)", goal)
    if match:
        return int(match.group(1)) - 1
    if re.search(r"第一|首条|首个|first\b", goal, flags=re.I):
        return 0
    match = re.search(r"第([一二两三四五六七八九十]+)(?:条|个|项|行)", goal)
    if match:
        digits = {c: n for n, c in enumerate("零一二三四五六七八九")}
        digits["两"] = 2
        value = match.group(1)
        if "十" in value:
            left, right = value.split("十", 1)
            if len(left) <= 1 and len(right) <= 1:
                return digits.get(left, 1) * 10 + digits.get(right, 0) - 1
        elif value in digits:
            return digits[value] - 1
    return None
