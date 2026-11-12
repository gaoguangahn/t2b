"""Resolve all target uses through one evidence-based protocol, preserving user expectations."""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from atestservice.contracts.action import ClickBounds
from atestservice.contracts.observation import DeviceObservation
from atestservice.contracts.script import Locator, ScriptPlan, Selector, TargetResolution
from atestservice.llm.types import LLMCallOptions, StructuredLLM
from atestservice.script_generation.evidence import Evidence, evidence_message
from atestservice.script_generation.targeting.models import TargetPick, TargetResponse
from atestservice.script_generation.targeting.stability import requested_index, selector_problem
from atestservice.ui.coordinate import bounds_to_normalized_point
from atestservice.ui.elements import normalize_elements, contains, matches, target_pixels

CLICK_TYPES = {"click", "double_click", "long_click"}
_PROMPT = Path(__file__).parents[1] / "prompts" / "targets.md"
_OPTIONS = LLMCallOptions(temperature=0.1, max_completion_tokens=8192, timeout=120, structured_output_method="function_calling")


@dataclass
class TargetRequest:
    id: str
    usage: Literal["action", "condition", "verification"]
    goal: str
    description: str
    observation_id: str | None
    bounds: ClickBounds | None = None


def requests_for_plan(evidence: Evidence, plan: ScriptPlan) -> list[TargetRequest]:
    requests = []
    instructions = {i.id: i for s in evidence.case.steps for i in s.instructions}
    for action in plan.actions:
        op = evidence.operations[action.operation_id]
        if op.action.type in CLICK_TYPES:
            requests.append(TargetRequest(op.id, "action", instructions[op.semantic_ref.instruction_id].text,
                                          action.description, op.observation_transition.before_observation_id, op.action.args.bounds))
    for condition in plan.conditions:
        first = next(a for a in plan.actions if a.condition_id == condition.id)
        op = evidence.operations[first.operation_id]
        requests.append(TargetRequest(f"condition:{condition.id}", "condition", condition.description,
                                      condition.description, op.observation_transition.before_observation_id))
    for verification in evidence.case.verifications:
        checkpoint = evidence.checkpoints.get(verification.id)
        requests.append(TargetRequest(f"verify:{verification.id}", "verification", verification.goal, verification.goal,
                                      checkpoint.observation_id if checkpoint and checkpoint.capture_status == "captured" else None))
    return requests


def _fallback(request: TargetRequest, reason: str) -> TargetResolution:
    if request.usage == "action" and request.bounds:
        return TargetResolution(description=request.description, status="coordinate", observation_id=request.observation_id,
                                point=tuple(bounds_to_normalized_point(request.bounds.root)),
                                rationale=reason,
                                notes=[f"{request.id}：{reason} 使用本次坐标，布局变化时需要调整。"])
    return TargetResolution(description=request.description, status="unresolved", observation_id=request.observation_id,
                            rationale=reason,
                            notes=[f"{request.id}：{reason} 保留原要求，需按框架能力补充。"])


def _selector(element, keys):
    if not keys or len(keys) != len(set(keys)) or any(not element.get(k) for k in keys):
        raise ValueError("Selected attribute is unavailable in UI evidence")
    return Selector(**{k: element[k] for k in keys})


def resolve_pick(request: TargetRequest, pick: TargetPick, elements: list[dict], observation: DeviceObservation) -> TargetResolution:
    """Validate model choice against actual UI; never fall back to an arbitrary candidate."""
    if pick.kind == "non_ui":
        if request.usage != "verification":
            return _fallback(request, "动作或执行条件不能解析成非 UI 验证。")
        return TargetResolution(description=pick.target_description, status="non_ui", observation_id=request.observation_id, rationale=pick.reason)
    if pick.kind == "unresolved":
        return _fallback(request, pick.reason)
    by_id = {e["id"]: e for e in elements}
    element = by_id.get(pick.candidate_id)
    if not element:
        return _fallback(request, "选择的控件没有现场证据。")
    try:
        selector = _selector(element, pick.attributes)
        problem = selector_problem(selector, element, request.goal, pick.attribute_role)
        if problem:
            return _fallback(request, problem)
        scope = None
        scope_bounds = None
        if pick.scope_candidate_id:
            parent = by_id.get(pick.scope_candidate_id)
            if not parent or parent == element or not contains(parent["bounds"], element["bounds"]):
                return _fallback(request, "缺少目标所属区域的可靠证据。")
            scope = _selector(parent, pick.scope_attributes)
            problem = selector_problem(scope, parent, request.goal, "control_identity")
            if problem:
                return _fallback(request, problem)
            parents = [e for e in elements if matches(e, scope)]
            if pick.scope_index is not None:
                if requested_index(request.goal) != pick.scope_index or pick.scope_index >= len(parents) or parents[pick.scope_index]["id"] != parent["id"]:
                    return _fallback(request, "所属条目的序号缺少用户要求或与现场目标不一致。")
            elif len(parents) != 1:
                return _fallback(request, "目标所属区域不能唯一确定。")
            scope_bounds = parent["bounds"]
        elif pick.scope_index is not None or pick.scope_attributes:
            return _fallback(request, "区域索引或属性缺少对应区域。")
        matched = [e for e in elements if matches(e, selector) and (not scope or contains(scope_bounds, e["bounds"]))]
        if pick.index is not None:
            if requested_index(request.goal) != pick.index:
                return _fallback(request, "用户未指定此位置，不能用索引消除歧义。")
            if pick.index >= len(matched) or matched[pick.index]["id"] != element["id"]:
                return _fallback(request, "位置定位与现场目标不一致。")
        elif len(matched) != 1:
            return _fallback(request, "定位存在多个匹配，需要限定所属区域或保留用户的位置语义。")
        if request.usage == "action":
            expected = target_pixels(request.bounds, observation.screen_size)
            center = [(expected[0] + expected[2]) / 2, (expected[1] + expected[3]) / 2] if expected else None
            if not center or not contains(element["bounds"], center + center):
                return _fallback(request, "控件没有覆盖实际操作点，不能仅凭矩形相交替换原操作。")
        return TargetResolution(description=pick.target_description, status="resolved", observation_id=request.observation_id,
                                rationale=pick.reason,
                                locator=Locator(selector=selector, within=scope, within_index=pick.scope_index, index=pick.index))
    except (ValueError, TypeError):
        return _fallback(request, "选择的定位属性不完整或缺少证据。")


async def resolve_targets(evidence: Evidence, plan: ScriptPlan, llm: StructuredLLM) -> dict[str, TargetResolution]:
    requests = requests_for_plan(evidence, plan)
    resolutions = {}
    # Each request is bounded to its own observation; no final-page substitution.
    for request in requests:
        observation = evidence.observations.get(request.observation_id)
        if observation is None:
            resolutions[request.id] = _fallback(request, "对应位置的观察不可用。")
            continue
        elements = normalize_elements(observation.elements)
        payload = {"request_id": request.id, "usage": request.usage, "user_goal": request.goal,
                   "action_description": request.description, "observation_id": request.observation_id,
                   "target_bounds_pixels": target_pixels(request.bounds, observation.screen_size), "elements": elements}
        messages = [{"role": "system", "content": _PROMPT.read_text(encoding="utf-8")},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        # Only relevant frame is sent, and only to vision-capable models.
        full = evidence_message(llm, evidence, [request.observation_id])
        images = [c for c in full["content"] if c["type"] == "image_url"]
        if images:
            messages.append({"role": "user", "content": images})
        response = await llm.invoke_structured(messages, TargetResponse, options=_OPTIONS)
        if len(response.targets) != 1 or response.targets[0].request_id != request.id:
            raise ValueError(f"Target response must match request exactly: {request.id}")
        resolutions[request.id] = resolve_pick(request, response.targets[0], elements, observation)
    return resolutions
