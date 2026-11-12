"""Resolve all target uses through one evidence-based protocol, preserving user expectations."""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from atestservice.contracts.action import ClickBounds
from atestservice.contracts.observation import DeviceObservation
from atestservice.contracts.script import ScriptPlan, TargetResolution, VerificationPlan
from atestservice.llm.types import LLMCallOptions, StructuredLLM
from atestservice.script_generation.evidence import Evidence, evidence_message
from atestservice.script_generation.targeting.models import TargetPick, TargetResponse
from atestservice.script_generation.targeting.context import build_target_context
from atestservice.script_generation.targeting.locators import resolve_locator, validate_anchor_locator
from atestservice.script_generation.targeting.verification import validate_verification
from atestservice.ui.coordinate import bounds_to_normalized_point
from atestservice.ui.elements import target_pixels
from atestservice.ui.spatial import spatial_relation

CLICK_TYPES = {"click", "double_click", "long_click"}
_PROMPT = Path(__file__).parents[1] / "prompts" / "targets.md"
_OPTIONS = LLMCallOptions(temperature=0.1, max_completion_tokens=8192, timeout=120)


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
                            verification=VerificationPlan(method="unresolved", basis=reason) if request.usage == "verification" else None,
                            notes=[f"{request.id}：{reason} 保留原要求，需按框架能力补充。"])


def resolve_pick(request: TargetRequest, pick: TargetPick, elements: list[dict], observation: DeviceObservation,
                 *, frames: dict[str, list[dict]] | None = None, operation_ids: set[str] | None = None) -> TargetResolution:
    """Validate model choice against actual UI; never fall back to an arbitrary candidate."""
    if pick.kind == "non_ui":
        if request.usage != "verification":
            return _fallback(request, "动作或执行条件不能解析成非 UI 验证。")
        return TargetResolution(description=pick.target_description, status="non_ui", observation_id=request.observation_id, rationale=pick.reason)
    if pick.kind == "unresolved":
        return _fallback(request, pick.reason)
    frames = frames or {observation.id: elements}
    source_id = pick.candidate_observation_id or observation.id
    if source_id != observation.id and (request.usage != "verification" or pick.verification is None):
        return _fallback(request, "动作或条件不能换帧定位；历史验证定位需明确验证方式及证据来源。")
    if source_id not in frames:
        return _fallback(request, "控件来源不属于提供的当前位置证据。")
    if request.usage != "verification" and (pick.verification is not None or pick.attribute_role == "state_indicator"):
        return _fallback(request, "状态验证特征不能用作操作身份或执行条件。")
    if pick.attribute_role == "state_indicator" and (pick.verification is None or pick.verification.method != "ui_feature"):
        return _fallback(request, "状态指示文本必须用于有明确依据的UI特征验证。")
    source_elements = frames[source_id]
    by_id = {e["id"]: e for e in source_elements}
    element = by_id.get(pick.candidate_id)
    if not element:
        return _fallback(request, "选择的控件没有现场证据。")
    try:
        verification = validate_verification(pick, element, source_id, frames, operation_ids or set()) if request.usage == "verification" else None
        collection = verification is not None and verification.method == "count"
        locator = resolve_locator(pick, element, source_elements, request.goal, collection=collection)
        if source_id != observation.id:
            validate_anchor_locator(locator, elements, collection=collection)
        if verification is not None and verification.method == "ui_feature" and not (
            locator.selector.text or locator.selector.description
        ):
            return _fallback(request, "UI状态特征存在判断需包含实际状态文案或描述，不能只检查开关控件存在。")
        if request.usage == "action":
            expected = target_pixels(request.bounds, observation.screen_size)
            spatial = spatial_relation(expected, element["bounds"], observation.screen_size)
            if spatial["relation"] not in {"point_hit", "overlap", "nearby"}:
                return _fallback(request, "所选控件与原操作区域缺少足够重叠或邻近依据。")
            rationale = pick.reason + f" 空间关系：{spatial['relation']}。"
        else:
            rationale = pick.reason
        return TargetResolution(description=pick.target_description, status="resolved", observation_id=request.observation_id,
                                rationale=rationale, locator=locator, verification=verification)
    except (ValueError, TypeError) as error:
        return _fallback(request, str(error))


async def resolve_targets(evidence: Evidence, plan: ScriptPlan, llm: StructuredLLM) -> dict[str, TargetResolution]:
    requests = requests_for_plan(evidence, plan)
    resolutions = {}
    retained_ids = {action.operation_id for action in plan.actions}
    # Anchor is fixed; bounded supporting frames explain identity without moving it.
    for request in requests:
        observation = evidence.observations.get(request.observation_id)
        if observation is None:
            resolutions[request.id] = _fallback(request, "对应位置的观察不可用。")
            continue
        payload, frames = build_target_context(evidence, request, retained_operation_ids=retained_ids)
        messages = [{"role": "system", "content": _PROMPT.read_text(encoding="utf-8")},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        # Label every image; do not lose frame IDs when adding comparison evidence.
        images = []
        for identifier in list(frames)[:3]:
            full = evidence_message(llm, evidence, [identifier])
            shots = [block for block in full["content"] if block["type"] == "image_url"]
            if shots:
                images.extend([{"type": "text", "text": f"observation_id={identifier}; role={'anchor' if identifier == observation.id else 'support'}"}, *shots])
        if images:
            messages.append({"role": "user", "content": images})
        response = await llm.invoke_structured(messages, TargetResponse, options=_OPTIONS)
        if len(response.targets) != 1 or response.targets[0].request_id != request.id:
            raise ValueError(f"Target response must match request exactly: {request.id}")
        resolutions[request.id] = resolve_pick(request, response.targets[0], frames[observation.id], observation,
                                               frames=frames, operation_ids=set(payload["runtime_baseline_operation_ids"]))
    return resolutions
