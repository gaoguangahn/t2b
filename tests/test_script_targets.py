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
        refined = self.resolve(elements, pick())
        self.assertEqual(refined.status, "resolved")
        self.assertEqual(refined.locator.selector.resource_id, "app:id/like")
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

    def test_empty_or_entirely_unavailable_attributes_have_specific_diagnostics(self):
        elements = [element("搜索", className="android.widget.Button")]
        cases = [([], "未选择定位属性"), (["resource_id", "description"], "所选属性均为空或未提供：resource_id、description")]
        for attributes, expected in cases:
            with self.subTest(attributes=attributes):
                result = self.resolve(elements, pick(attributes=attributes), goal="打开搜索")
                self.assertEqual(result.status, "coordinate")
                self.assertIn("来源观察 o0", result.rationale)
                self.assertIn("目标控件 e0", result.rationale)
                self.assertIn(expected, result.rationale)
                self.assertIn("可用属性：text、class_name", result.rationale)
                self.assertIsNone(result.locator)

    def test_one_usable_attribute_survives_empty_or_duplicate_selected_attributes(self):
        elements = [element("设置", resourceId=None, description="")]
        for attributes in (["text"], ["text", "resource_id", "description"], ["text", "text", "resource_id"]):
            for usage in ("action", "condition", "verification"):
                with self.subTest(attributes=attributes, usage=usage):
                    result = self.resolve(elements, pick(attributes=attributes), goal="打开设置", usage=usage)
                    self.assertEqual(result.status, "resolved")
                    self.assertEqual(result.locator.selector.model_dump(exclude_none=True), {"text": "设置"})
                    self.assertEqual(result.notes, [])

    def test_filtering_empty_fields_does_not_bypass_duplicates_or_dynamic_identity(self):
        duplicate = self.resolve([element("点赞"), element("点赞", bounds=[500, 500, 600, 600])],
                                 pick(attributes=["text", "resource_id"]))
        self.assertEqual(duplicate.status, "coordinate")
        self.assertIn("多个不可区分", duplicate.rationale)
        dynamic = self.resolve([element("128赞")], pick(attributes=["text", "resource_id"]))
        self.assertEqual(dynamic.status, "coordinate")
        self.assertIn("动态展示值", dynamic.rationale)

    def test_scope_can_use_one_valid_attribute_without_dropping_its_constraint(self):
        elements = [element("点赞"), element("点赞", bounds=[500, 500, 600, 600]),
                    element("指定区域", bounds=[0, 0, 250, 250])]
        result = self.resolve(elements, pick(attributes=["text", "resource_id"], scope_candidate_id="e2",
                                             scope_attributes=["text", "resource_id", "text"]))
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.locator.within.model_dump(exclude_none=True), {"text": "指定区域"})
        self.assertEqual(result.locator.selector.text, "点赞")

    def test_missing_scope_attribute_is_not_reported_as_missing_target_value(self):
        elements = [element("点赞", resourceId="app:id/like"),
                    element("列表区域", bounds=[0, 0, 250, 250])]
        result = self.resolve(elements, pick(attributes=["resource_id"], scope_candidate_id="e1",
                                             scope_attributes=["resource_id"]))
        self.assertEqual(result.status, "coordinate")
        self.assertIn("所属区域 e1", result.rationale)
        self.assertIn("所选属性均为空或未提供：resource_id", result.rationale)
        self.assertIn("可用属性：text", result.rationale)

    def test_overlapping_neighbor_that_does_not_cover_actual_click_is_rejected(self):
        result = self.resolve([element("搜索", bounds=[190, 190, 250, 250])], pick(), goal="打开搜索")
        self.assertEqual(result.status, "coordinate")

    def test_meaningful_overlap_and_small_offset_do_not_require_center_hit(self):
        for bounds in ([160, 110, 260, 190], [205, 115, 255, 185]):
            with self.subTest(bounds=bounds):
                result = self.resolve([element("搜索", bounds=bounds)], pick(), goal="打开搜索")
                self.assertEqual(result.status, "resolved")
        result = self.resolve([element("搜索", bounds=[0, 0, 1000, 1000])], pick(), goal="打开搜索")
        self.assertEqual(result.status, "coordinate")

    def test_identical_controls_are_not_resolved_by_nearest_index(self):
        result = self.resolve([element("点赞", resourceId="app:id/like"),
                               element("点赞", resourceId="app:id/like", bounds=[500, 500, 600, 600])], pick())
        self.assertEqual(result.status, "coordinate")

    def test_explicit_parent_identity_can_disambiguate_same_controls(self):
        elements = [element("点赞", id="like1", parent_id="row1", resourceId="app:id/like"),
                    element("点赞", id="like2", parent_id="row2", resourceId="app:id/like", bounds=[500, 500, 600, 600]),
                    element("", id="row1", resourceId="app:id/first_card", bounds=[0, 0, 250, 250]),
                    element("", id="row2", resourceId="app:id/other_card", bounds=[450, 450, 650, 650])]
        result = self.resolve(elements, pick())
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.locator.within.resource_id, "app:id/first_card")

    def test_state_text_is_not_automatically_added_to_action_identity(self):
        result = self.resolve([element("开关", resourceId="app:id/switch", description="已开启"),
                               element("开关", resourceId="app:id/switch", description="已关闭", bounds=[500, 500, 600, 600])],
                              pick(attributes=["resource_id"]), goal="点击Wi-Fi开关")
        self.assertEqual(result.status, "coordinate")

    def test_refinement_does_not_bind_unrequested_display_content(self):
        result = self.resolve([element("推荐商品甲", resourceId="app:id/item", description="用户甲"),
                               element("推荐商品乙", resourceId="app:id/item", description="用户乙", bounds=[500, 500, 600, 600])],
                              pick(attributes=["resource_id"]), goal="点击推荐商品")
        self.assertEqual(result.status, "coordinate")

    def test_switch_attribute_plan_does_not_rewrite_expected_to_observed(self):
        selection = pick(attributes=["resource_id"], verification={
            "method": "attribute", "attribute": "checked", "operator": "equals", "expected_value": True,
            "evidence_observation_ids": ["o0"], "basis": "该控件checked表达Wi-Fi开关状态，用户要求开启"})
        result = self.resolve([element("Wi-Fi", resourceId="app:id/wifi", checked=False)], selection,
                              goal="验证Wi-Fi开关已打开", usage="verification")
        self.assertEqual(result.status, "resolved")
        self.assertIs(result.verification.expected_value, True)
        self.assertEqual(result.verification.method, "attribute")

    def test_explicit_ui_state_feature_works_without_checked(self):
        selection = pick(attribute_role="state_indicator", verification={
            "method": "ui_feature", "operator": "exists", "evidence_observation_ids": ["o0"],
            "basis": "WLAN已关闭是页面明确状态提示，直接表达原预期"})
        result = self.resolve([element("WLAN已关闭")], selection, goal="验证Wi-Fi关闭", usage="verification")
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.verification.method, "ui_feature")
        # Merely seeing the switch control does not prove its state.
        selection.attributes = ["resource_id"]
        result = self.resolve([element("", resourceId="app:id/wifi")], selection,
                              goal="验证Wi-Fi关闭", usage="verification")
        self.assertEqual(result.status, "unresolved")

    def test_count_preserves_collection_instead_of_forcing_unique_selector(self):
        selection = pick(attributes=["resource_id"], verification={
            "method": "count", "operator": "equals", "expected_value": 2,
            "evidence_observation_ids": ["o0"], "basis": "用户要求两个同类条目，读取匹配集合数量"})
        result = self.resolve([element("甲", resourceId="app:id/item"),
                               element("乙", resourceId="app:id/item", bounds=[500, 500, 600, 600])], selection,
                              goal="验证列表有2个条目", usage="verification")
        self.assertEqual(result.status, "resolved")
        self.assertIsNone(result.locator.selector.text)
        self.assertIsNone(result.locator.index)

    def test_invalid_or_invented_verification_evidence_is_reported_as_unresolved(self):
        for value in (
            {"method": "attribute", "attribute": "checked", "operator": "equals", "expected_value": "true",
             "evidence_observation_ids": ["o0"], "basis": "错误值类型"},
            {"method": "attribute", "attribute": "checked", "operator": "equals", "expected_value": True,
             "evidence_observation_ids": ["invented"], "basis": "虚构来源"},
        ):
            with self.subTest(value=value):
                result = self.resolve([element("Wi-Fi", resourceId="app:id/wifi", checked=True)],
                    pick(attributes=["resource_id"], verification=value), goal="验证Wi-Fi开启", usage="verification")
                self.assertEqual(result.status, "unresolved")

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
