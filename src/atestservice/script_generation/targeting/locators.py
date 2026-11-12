"""Validate and refine selectors for one chosen identity, never pick a different node."""
from itertools import combinations
import re

from atestservice.contracts.script import Locator, Selector
from atestservice.script_generation.targeting.stability import requested_index, selector_problem
from atestservice.ui.elements import contains, matches


def selector_for(element, keys):
    if not keys or len(keys) != len(set(keys)) or any(not element.get(key) for key in keys):
        raise ValueError("选择的定位属性缺少现场值。")
    return Selector(**{key: element[key] for key in keys})


def _safe_addition(element, key, goal, role):
    value = element.get(key)
    if not value:
        return False
    if key == "resource_id":
        return not re.search(r"(?:\d{8,}|[0-9a-f]{20,}|[0-9a-f]{8}-[0-9a-f-]{20,})", value.rsplit("/", 1)[-1], re.I)
    if key in {"text", "description"}:
        # Do not undo the model's choice to omit display content by adding a
        # nickname/title/state merely because it makes this snapshot unique.
        # Nonliteral stable labels can still be selected explicitly by the model.
        return value in goal
    return True


def _refine(element, selector, pool, goal, role):
    """Add the smallest available stable combination; never invent an index."""
    if sum(matches(item, selector) for item in pool) == 1:
        return selector
    extra = [key for key in ("resource_id", "description", "class_name", "text")
             if _safe_addition(element, key, goal, role) and getattr(selector, key) is None]
    for size in range(1, len(extra) + 1):
        for keys in combinations(extra, size):
            candidate = Selector(**{**selector.model_dump(exclude_none=True), **{key: element[key] for key in keys}})
            if not selector_problem(candidate, element, goal, role) and sum(matches(item, candidate) for item in pool) == 1:
                return candidate
    return selector


def resolve_locator(pick, element, elements, goal, *, collection=False):
    selector = selector_for(element, pick.attributes)
    problem = selector_problem(selector, element, goal, pick.attribute_role)
    if problem:
        raise ValueError(problem)
    scope = None
    scope_bounds = None
    parent = None
    by_id = {item["id"]: item for item in elements}
    if pick.scope_candidate_id:
        parent = by_id.get(pick.scope_candidate_id)
        if not parent or parent == element or not contains(parent["bounds"], element["bounds"]):
            raise ValueError("缺少目标所属区域的可靠证据。")
        scope = selector_for(parent, pick.scope_attributes)
        problem = selector_problem(scope, parent, goal, "control_identity")
        if problem:
            raise ValueError(problem)
        if pick.scope_index is None:
            scope = _refine(parent, scope, elements, goal, "control_identity")
        parents = [item for item in elements if matches(item, scope)]
        if pick.scope_index is not None:
            if (requested_index(goal) != pick.scope_index or pick.scope_index >= len(parents)
                    or parents[pick.scope_index]["id"] != parent["id"]):
                raise ValueError("所属条目的序号缺少用户要求或与现场目标不一致。")
        elif len(parents) != 1:
            raise ValueError("目标所属区域不能唯一确定。")
        scope_bounds = parent["bounds"]
    elif pick.scope_index is not None or pick.scope_attributes:
        raise ValueError("区域索引或属性缺少对应区域。")

    pool = [item for item in elements if not scope or contains(scope_bounds, item["bounds"])]
    if collection and pick.index is not None:
        raise ValueError("数量验证应定位完整集合，不能只选择一个目标索引。")
    if pick.index is None and not collection:
        selector = _refine(element, selector, pool, goal, pick.attribute_role)
        # Only infer a scope from an explicit ancestor link, not screen overlap.
        if scope is None and sum(matches(item, selector) for item in pool) > 1:
            ancestor = element.get("parent_id")
            visited = set()
            while ancestor in by_id and ancestor not in visited:
                visited.add(ancestor)
                item = by_id[ancestor]
                keys = [key for key in ("resource_id", "description", "text") if _safe_addition(item, key, goal, "control_identity")]
                if keys and contains(item["bounds"], element["bounds"]):
                    for key in keys:
                        candidate_scope = selector_for(item, [key])
                        if selector_problem(candidate_scope, item, goal, "control_identity"):
                            continue
                        candidate_scope = _refine(item, candidate_scope, elements, goal, "control_identity")
                        scoped_pool = [entry for entry in elements if contains(item["bounds"], entry["bounds"])]
                        if sum(matches(entry, candidate_scope) for entry in elements) == 1 and sum(matches(entry, selector) for entry in scoped_pool) == 1:
                            scope, pool = candidate_scope, scoped_pool
                            break
                if scope is not None:
                    break
                ancestor = item.get("parent_id")
    matched = [item for item in pool if matches(item, selector)]
    if pick.index is not None:
        if requested_index(goal) != pick.index:
            raise ValueError("用户未指定此位置，不能用索引消除歧义。")
        if pick.index >= len(matched) or matched[pick.index]["id"] != element["id"]:
            raise ValueError("位置定位与现场目标不一致。")
    elif not collection and len(matched) != 1:
        raise ValueError("同一定位条件仍有多个不可区分的匹配，缺少稳定属性或所属区域，不能只凭本次坐标固定索引。")
    return Locator(selector=selector, within=scope, within_index=pick.scope_index, index=pick.index)


def validate_anchor_locator(locator, elements, *, collection=False):
    """A historical identity may be absent, but cannot introduce anchor ambiguity."""
    pool = elements
    if locator.within is not None:
        parents = [item for item in elements if matches(item, locator.within)]
        if locator.within_index is None and len(parents) > 1:
            raise ValueError("历史控件的所属区域在验证位置存在多个匹配。")
        index = locator.within_index or 0
        if index >= len(parents):
            return
        pool = [item for item in elements if contains(parents[index]["bounds"], item["bounds"])]
    if not collection and locator.index is None and sum(matches(item, locator.selector) for item in pool) > 1:
        raise ValueError("历史控件定位在验证位置存在多个匹配，需保留可复现的所属区域。")
