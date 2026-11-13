"""Regression cases for evidence anchoring, state provenance and replay ambiguity."""
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace

from generation_fixtures import all_actions, element, evidence
from atestservice.contracts.script import ScriptPlan
from atestservice.llm.types import LLMCapabilities
from atestservice.script_generation.targeting.context import build_target_context
from atestservice.script_generation.targeting.models import TargetPick
from atestservice.script_generation.targeting.resolver import TargetRequest, resolve_pick, resolve_targets
from atestservice.ui.elements import normalize_elements


def verification_request(e):
    checkpoint = e.checkpoints["v1"]
    return TargetRequest("verify:v1", "verification", e.case.verifications[0].goal,
                         e.case.verifications[0].goal, checkpoint.observation_id)


def switch_evidence():
    e = evidence(("off", "on", "later"), verifications=[{
        "id": "v1", "goal": "验证Wi-Fi开启", "anchor": {"step_id": "s1", "instruction_id": "i1"}}])
    e.observations["o0"].elements = normalize_elements([element("Wi-Fi", resourceId="app:id/wifi", checked=False)], {'width': 1000, 'height': 1000})
    e.observations["o1"].elements = normalize_elements([element("Wi-Fi", resourceId="app:id/wifi", checked=True)], {'width': 1000, 'height': 1000})
    e.observations["o2"].elements = normalize_elements([element("后续页面")], {'width': 1000, 'height': 1000})
    e.checkpoints["v1"].observation_id = "o1"
    e.checkpoints["v1"].after_operation_id = "op0"
    return e


def historical_pick(**overrides):
    return TargetPick(request_id="verify:v1", kind="ui", target_description="明确的WLAN状态文案",
                      candidate_id="e0", candidate_observation_id="o0", attributes=["text"],
                      attribute_role="state_indicator", reason="来自操作前的真实状态文案，仍在原锚点检查实时状态",
                      verification={"method": "ui_feature", "operator": "exists", "basis": "用户预期WLAN已开启",
                                    "evidence_observation_ids": ["o0"]}, **overrides)


class ContextTests(unittest.TestCase):
    def test_action_and_control_context_use_the_same_normalized_coordinates(self):
        e = evidence()
        anchor = e.observations["o0"]
        anchor.screen_size.width, anchor.screen_size.height = 1080, 2420
        anchor.elements = normalize_elements([
            element("搜索", bounds="[108,242][216,484]"),
        ], anchor.screen_size)
        request = TargetRequest("op0", "action", "搜索", "搜索", "o0", e.operations["op0"].action.args.bounds)
        payload, _ = build_target_context(e, request)
        self.assertEqual(payload["coordinate_space"], "normalized_1000")
        self.assertEqual(payload["target_bounds"], [100, 100, 200, 200])
        self.assertEqual(payload["elements"][0]["bounds"], [100, 100, 200, 200])
        self.assertNotIn("target_bounds_pixels", payload)
        self.assertEqual(payload["elements"][0]["spatial"]["relation"], "point_hit")

    def test_previous_state_is_context_and_future_state_cannot_replace_checkpoint(self):
        e = switch_evidence()
        original = deepcopy(e.exploration.model_dump())
        payload, frames = build_target_context(e, verification_request(e), retained_operation_ids={"op0"})
        self.assertEqual(set(frames), {"o0", "o1"})
        self.assertEqual(payload["observation_id"], "o1")
        self.assertIs(payload["elements"][0]["checked"], True)
        self.assertIs(payload["supporting_observations"][0]["elements"][0]["checked"], False)
        operations = payload["related_operations"]
        self.assertEqual([op["operation_id"] for op in operations], ["op0"])
        self.assertEqual(operations[0]["control_correspondences"][0]["changes"]["checked"],
                         {"before": False, "after": True})
        self.assertEqual(payload["runtime_baseline_operation_ids"], ["op0"])
        self.assertEqual(e.exploration.model_dump(), original)
        payload, _ = build_target_context(e, verification_request(e), retained_operation_ids={"op1"})
        self.assertEqual(payload["runtime_baseline_operation_ids"], [])

    def test_normalized_false_and_parent_links_do_not_turn_missing_state_into_false(self):
        rows = normalize_elements([
            element("", node_path=[0], checked="false", contentDescription="Wi-Fi行"),
            element("Wi-Fi", node_path=[0, 0], selected=False),
            element("其他", node_path=[1]), element("其他", node_path=[1]),
            element("子项", node_path=[1, 0]),
        ], {'width': 1000, 'height': 1000})
        self.assertIs(rows[0]["checked"], False)
        self.assertEqual(rows[0]["description"], "Wi-Fi行")
        self.assertIs(rows[1]["selected"], False)
        self.assertIsNone(rows[1]["checked"])
        self.assertEqual(rows[1]["parent_id"], "e0")
        self.assertIsNone(rows[4]["parent_id"])

    def test_historical_marker_does_not_move_anchor_or_mean_assertion_passed(self):
        e = switch_evidence()
        e.observations["o0"].elements = normalize_elements([element("WLAN已开启")], {'width': 1000, 'height': 1000})
        e.observations["o1"].elements = normalize_elements([element("WLAN已关闭")], {'width': 1000, 'height': 1000})
        request = verification_request(e)
        _, frames = build_target_context(e, request)
        result = resolve_pick(request, historical_pick(), frames["o1"], e.observations["o1"], frames=frames)
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.observation_id, "o1")
        self.assertEqual(result.locator.selector.text, "WLAN已开启")
        self.assertEqual(result.verification.operator, "exists")
        self.assertEqual(result.verification.evidence_observation_ids, ["o0"])

    def test_historical_marker_cannot_introduce_multiple_anchor_matches(self):
        e = switch_evidence()
        e.observations["o0"].elements = normalize_elements([element("WLAN已开启")], {'width': 1000, 'height': 1000})
        e.observations["o1"].elements = normalize_elements([element("WLAN已开启"), element("WLAN已开启", bounds=[500, 500, 600, 600])], {'width': 1000, 'height': 1000})
        request = verification_request(e)
        _, frames = build_target_context(e, request)
        result = resolve_pick(request, historical_pick(), frames["o1"], e.observations["o1"], frames=frames)
        self.assertEqual(result.status, "unresolved")
        self.assertIn("多个匹配", result.rationale)

    def test_empty_count_can_use_known_collection_without_asserting_presence(self):
        e = switch_evidence()
        e.observations["o0"].elements = normalize_elements([element("甲", resourceId="app:id/item"), element("乙", resourceId="app:id/item")], {'width': 1000, 'height': 1000})
        request = verification_request(e)
        _, frames = build_target_context(e, request)
        selection = TargetPick(request_id=request.id, kind="ui", target_description="待清空的集合",
            candidate_id="e0", candidate_observation_id="o0", attributes=["resource_id"], reason="用户要求清空条目",
            verification={"method": "count", "operator": "equals", "expected_value": 0,
                          "evidence_observation_ids": ["o0"], "basis": "用户预期集合为空，定位来自已知条目"})
        result = resolve_pick(request, selection, frames["o1"], e.observations["o1"], frames=frames)
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.verification.expected_value, 0)
        self.assertEqual(result.observation_id, "o1")
        self.assertIsNone(result.locator.selector.text)
        self.assertIsNone(result.locator.index)

    def test_action_cannot_use_a_matching_control_from_after_frame(self):
        e = switch_evidence()
        request = TargetRequest("op0", "action", "打开Wi-Fi", "打开Wi-Fi", "o0", e.operations["op0"].action.args.bounds)
        _, frames = build_target_context(e, request)
        selection = TargetPick(request_id="op0", kind="ui", target_description="Wi-Fi开关", candidate_id="e0",
                               candidate_observation_id="o1", attributes=["resource_id"], reason="动作后才出现")
        result = resolve_pick(request, selection, frames["o0"], e.observations["o0"], frames=frames)
        self.assertEqual(result.status, "coordinate")

    def test_delta_requires_a_retained_runtime_baseline_not_snapshot_arithmetic(self):
        e = switch_evidence()
        e.observations["o1"].elements = normalize_elements([element("5", resourceId="app:id/count")], {'width': 1000, 'height': 1000})
        request = verification_request(e)
        _, frames = build_target_context(e, request)
        selection = TargetPick(request_id=request.id, kind="ui", target_description="数量", candidate_id="e0",
            attributes=["resource_id"], reason="读取同一数量控件", verification={
                "method": "number", "operator": "delta", "expected_value": 1, "baseline_operation_id": "op0",
                "evidence_observation_ids": ["o1"], "basis": "纯整数数量，用户要求增加1，操作前读取运行时基准"})
        rejected = resolve_pick(request, selection, frames["o1"], e.observations["o1"], frames=frames)
        self.assertEqual(rejected.status, "unresolved")
        accepted = resolve_pick(request, selection, frames["o1"], e.observations["o1"], frames=frames, operation_ids={"op0"})
        self.assertEqual(accepted.status, "resolved")
        self.assertEqual(accepted.verification.expected_value, 1)
        self.assertEqual(accepted.verification.baseline_operation_id, "op0")

    def test_unresolved_strategy_is_reported_in_notes_even_with_valid_locator(self):
        e = switch_evidence()
        request = verification_request(e)
        selection = TargetPick(request_id=request.id, kind="ui", target_description="开关", candidate_id="e0",
            attributes=["resource_id"], reason="没有可用验证策略", verification={"method": "unresolved", "basis": "缺少状态证据"})
        result = resolve_pick(request, selection, e.observations["o1"].elements, e.observations["o1"])
        self.assertEqual(result.status, "unresolved")
        self.assertTrue(result.notes)


class ContextCallTests(unittest.IsolatedAsyncioTestCase):
    async def test_extra_evidence_does_not_add_model_calls_and_images_are_labelled(self):
        e = switch_evidence()
        calls = []
        class LLM:
            config = SimpleNamespace(capabilities=LLMCapabilities(supports_vision=True))
            async def invoke_structured(self, messages, schema, **kwargs):
                calls.append(messages)
                request = json.loads(messages[1]["content"])
                return schema(targets=[{"request_id": request["request_id"], "kind": "unresolved",
                                       "target_description": "目标", "reason": "没有稳定目标"}])
        result = await resolve_targets(e, ScriptPlan(actions=all_actions(e)), LLM())
        self.assertEqual(len(calls), 3)  # two clicks and one verification, no review pass
        verification = calls[-1]
        self.assertEqual(json.loads(verification[1]["content"])["observation_id"], "o1")
        labels = [block["text"] for message in verification[2:] for block in message["content"] if block["type"] == "text"]
        self.assertIn("observation_id=o1; role=anchor", labels)
        self.assertIn("observation_id=o0; role=support", labels)
        self.assertNotIn("o2", " ".join(labels))
        self.assertEqual(result["verify:v1"].observation_id, "o1")
