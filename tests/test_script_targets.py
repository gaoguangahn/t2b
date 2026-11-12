import json
import unittest
from atestservice.contracts.script import ScriptPlan
from atestservice.script_generation.targeting.models import TargetPick
from atestservice.script_generation.targeting.resolver import TargetRequest, resolve_pick, resolve_targets
from atestservice.ui.elements import normalize_elements
from generation_fixtures import evidence, element, all_actions


def pick(**kwargs):
    return TargetPick(request_id="op0", kind="ui", target_description="目标", candidate_id="e0",
                      attributes=kwargs.pop("attributes", ["text"]), reason="控件语义匹配", **kwargs)


class TargetTests(unittest.TestCase):
    def resolve(self, elements, selection, goal="点赞", usage="action"):
        e = evidence(elements=elements, goal=goal)
        request = TargetRequest("op0", usage, goal, goal, "o0", e.operations["op0"].action.args.bounds if usage == "action" else None)
        return resolve_pick(request, selection, normalize_elements(elements), e.observations["o0"])

    def test_like_count_never_becomes_identity_but_resource_id_can(self):
        for count in ("128赞", "2.3万赞"):
            with self.subTest(count=count):
                elements = [element(count, resourceId="app:id/like")]
                self.assertEqual(self.resolve(elements, pick()).status, "coordinate")
                result = self.resolve(elements, pick(attributes=["resource_id"]))
                self.assertEqual(result.locator.selector.resource_id, "app:id/like")
        result = self.resolve([element("", resourceId="app:id/like")], pick(attributes=["resource_id"]))
        self.assertEqual(result.status, "resolved")

    def test_recommendation_hint_rejected_identity_of_search_field_used(self):
        elements = [element("今日热搜", hint="今日热搜", resourceId="app:id/search")]
        self.assertEqual(self.resolve(elements, pick(), goal="打开搜索框").status, "coordinate")
        result = self.resolve(elements, pick(attributes=["resource_id"]), goal="打开搜索框")
        self.assertEqual(result.status, "resolved")
        self.assertEqual(self.resolve([element("今日热搜")], pick(), goal="打开搜索框").status, "coordinate")

    def test_explicit_user_value_is_preserved_not_arbitrary_exploration_title(self):
        elements = [element("商品123")]
        result = self.resolve(elements, pick(attribute_role="user_value"), goal="点击商品123")
        self.assertEqual(result.locator.selector.text, "商品123")
        result = self.resolve(elements, pick(attribute_role="user_value"), goal="点击第一条商品")
        self.assertEqual(result.status, "coordinate")
        self.assertEqual(self.resolve(elements, pick(), goal="点击第一条商品").status, "coordinate")

    def test_duplicate_text_combined_selector_and_position(self):
        elements = [element("点赞", resourceId="app:id/like"), element("点赞", resourceId="app:id/other", bounds=[300, 300, 400, 400])]
        self.assertEqual(self.resolve(elements, pick()).status, "coordinate")
        self.assertEqual(self.resolve(elements, pick(attributes=["text", "resource_id"])).status, "resolved")
        self.assertEqual(self.resolve(elements, pick(index=0), goal="点赞").status, "coordinate")
        self.assertEqual(self.resolve(elements, pick(index=0), goal="点击第一条的点赞").status, "resolved")

    def test_scope_and_overlap_must_have_evidence(self):
        elements = [element("点赞"), element("点赞", bounds=[500, 500, 600, 600]),
                    element("", resourceId="app:id/first_card", bounds=[0, 0, 250, 250])]
        result = self.resolve(elements, pick(scope_candidate_id="e2", scope_attributes=["resource_id"]))
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.locator.within.resource_id, "app:id/first_card")
        result = self.resolve([element("搜索", bounds=[500, 500, 600, 600])], pick(), goal="搜索")
        self.assertEqual(result.status, "coordinate")

    def test_first_item_scope_is_not_replaced_by_first_global_button(self):
        elements = [element("点赞", resourceId="app:id/like"),
                    element("点赞", resourceId="app:id/like", bounds=[500, 500, 600, 600]),
                    element("", resourceId="app:id/card", bounds=[0, 0, 250, 250]),
                    element("", resourceId="app:id/card", bounds=[450, 450, 650, 650])]
        selection = pick(attributes=["resource_id"], scope_candidate_id="e2", scope_attributes=["resource_id"], scope_index=0)
        result = self.resolve(elements, selection, goal="给第一条内容点赞")
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.locator.within_index, 0)
        self.assertIsNone(result.locator.index)
        self.assertEqual(result.locator.within.resource_id, "app:id/card")
        result = self.resolve(elements, selection, goal="给内容点赞")
        self.assertEqual(result.status, "coordinate")

    def test_invalid_candidate_attribute_and_dynamic_role_never_select_first(self):
        for selection in [pick(attributes=["resource_id"]), pick(attribute_role="dynamic_content")]:
            self.assertEqual(self.resolve([element()], selection).status, "coordinate")
        selection = pick()
        selection.candidate_id = "invented"
        self.assertEqual(self.resolve([element()], selection).status, "coordinate")

    def test_overlapping_neighbor_that_does_not_cover_actual_click_is_rejected(self):
        result = self.resolve([element("搜索", bounds=[190, 190, 250, 250])], pick(), goal="打开搜索")
        self.assertEqual(result.status, "coordinate")

    def test_amount_verification_resolves_field_identity_not_observed_expected_value(self):
        result = self.resolve([element("99元", resourceId="app:id/amount")],
                              pick(attributes=["resource_id"]), goal="验证实付金额100元", usage="verification")
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.locator.selector.resource_id, "app:id/amount")
        result = self.resolve([element("99元")], pick(), goal="验证实付金额100元", usage="verification")
        self.assertEqual(result.status, "unresolved")


class TargetRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_click_and_verification_use_their_own_anchor_and_keep_expectation(self):
        e = evidence(("before", "checkpoint", "final"), verifications=[
            {"id": "v1", "goal": "验证不出现错误提示", "anchor": {"step_id": "s1"}}])
        e.checkpoints["v1"].observation_id = "o1"
        e.checkpoints["v1"].after_operation_id = "op0"
        requests = []
        class LLM:
            async def invoke_structured(self, messages, schema, **kwargs):
                request = json.loads(messages[1]["content"])
                requests.append(request)
                return schema(targets=[{"request_id": request["request_id"], "kind": "unresolved",
                                        "target_description": request["user_goal"], "reason": "未看到目标，不改写验证"}])
        result = await resolve_targets(e, ScriptPlan(actions=all_actions(e)), LLM())
        self.assertEqual([r["observation_id"] for r in requests], ["o0", "o1", "o1"])
        self.assertEqual(requests[-1]["user_goal"], "验证不出现错误提示")
        self.assertEqual(result["verify:v1"].status, "unresolved")
        self.assertIsNone(result["verify:v1"].point)

    async def test_missing_checkpoint_does_not_use_last_frame_or_drop_verification(self):
        e = evidence(verifications=[{"id": "v1", "goal": "显示成功", "anchor": {"step_id": "s1"}}])
        e.checkpoints.clear()
        class LLM:
            async def invoke_structured(self, messages, schema, **kwargs):
                request = json.loads(messages[1]["content"])
                return schema(targets=[{"request_id": request["request_id"], "kind": "unresolved",
                                        "target_description": "目标", "reason": "无定位"}])
        result = await resolve_targets(e, ScriptPlan(actions=all_actions(e)), LLM())
        self.assertIsNone(result["verify:v1"].observation_id)
        self.assertEqual(result["verify:v1"].status, "unresolved")

    async def test_mismatched_model_response_is_protocol_error(self):
        e = evidence()
        class LLM:
            async def invoke_structured(self, messages, schema, **kwargs):
                return schema(targets=[])
        with self.assertRaisesRegex(ValueError, "match request"):
            await resolve_targets(e, ScriptPlan(actions=all_actions(e)), LLM())
