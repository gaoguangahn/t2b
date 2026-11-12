import json
import unittest
from types import SimpleNamespace
from atestservice.contracts.script import ScriptPlan
from atestservice.script_generation.planning.models import PlanningResponse
from atestservice.script_generation.planning.planner import plan_actions
from atestservice.script_generation.planning.validation import validate_plan
from generation_fixtures import evidence, all_actions


def detour_plan():
    return ScriptPlan(actions=[{"operation_id": key, "description": "推进搜索"} for key in ("op0", "op3")],
        omitted_segments=[{"operation_ids": ["op1", "op2"], "reason": "误入页面后返回，没有完成必要业务操作",
                           "state_effects": "只做错误导航和返回，未修改数据，不影响后续搜索",
                           "observation_ids": ["o1", "o3"]}])


class PlanValidationTests(unittest.TestCase):
    def test_closed_detour_removed_without_mutating_evidence(self):
        e = evidence(("home", "list", "wrong", "list", "search"))
        before = e.exploration.model_dump()
        plan = validate_plan(detour_plan(), e)
        self.assertFalse(plan.issues)
        self.assertEqual([a.operation_id for a in plan.actions], ["op0", "op3"])
        self.assertEqual(before, e.exploration.model_dump())

    def test_open_gap_and_internal_verification_block(self):
        e = evidence(("home", "list", "wrong", "different", "search"))
        # Different visible data as well as image, otherwise UI evidence is identical.
        e.observations["o3"].elements = [{"text": "other"}]
        result = validate_plan(detour_plan(), e)
        self.assertIn("path_gap", [i.code for i in result.issues if i.blocking])
        e = evidence(("home", "list", "wrong", "list", "search"), verifications=[
            {"id": "v1", "goal": "验证中间页面", "anchor": {"step_id": "s1"}}])
        cp = e.checkpoints["v1"]
        cp.after_operation_id, cp.observation_id = "op1", "o2"
        e.observations["o2"].elements = [{"text": "wrong"}]
        self.assertIn("verification_boundary", [i.code for i in validate_plan(detour_plan(), e).issues])

    def test_normal_returns_and_setting_changes_can_all_be_kept(self):
        for pages in [("detail", "list", "home"), ("home", "settings", "home")]:
            with self.subTest(pages=pages):
                e = evidence(pages)
                plan = validate_plan(ScriptPlan(actions=all_actions(e)), e)
                self.assertEqual(len(plan.actions), 2)
                self.assertFalse(plan.issues)

    def test_missing_duplicate_reordered_or_invented_operations_rejected(self):
        e = evidence(("a", "b", "c"))
        for ids in [["op0"], ["op0", "op0"], ["op1", "op0"], ["op0", "made_up"]]:
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                validate_plan(ScriptPlan(actions=[{"operation_id": i, "description": "x"} for i in ids]), e)

    def test_failed_and_unknown_are_context_not_successful_script_actions(self):
        for status in ("failed", "unknown"):
            e = evidence()
            e.operations["op0"].execution.status = status
            plan = validate_plan(ScriptPlan(actions=all_actions(e)), e)
            self.assertTrue(any(i.blocking for i in plan.issues))

    def test_condition_group_is_generic_contiguous_and_cannot_cross_instruction(self):
        e = evidence(("a", "b", "c", "d"))
        actions = all_actions(e)
        actions[0]["condition_id"] = actions[2]["condition_id"] = "c1"
        with self.assertRaisesRegex(ValueError, "contiguous"):
            validate_plan(ScriptPlan(actions=actions, conditions=[{"id": "c1", "description": "出现引导时"}]), e)

    def test_required_launch_cannot_become_optional(self):
        e = evidence(actions=[{"type": "start_app", "args": {"app_name": "示例"}}])
        e.case.steps[0].instructions[0].kind = "app_launch"
        plan = ScriptPlan(actions=[{"operation_id": "op0", "description": "启动", "condition_id": "c1"}],
                          conditions=[{"id": "c1", "description": "可选"}])
        self.assertIn("missing_required_action", [i.code for i in validate_plan(plan, e).issues])

    def test_explicit_swipe_count_cannot_silently_shrink(self):
        e = evidence(("a", "b", "b"), actions=[
            {"type": "swipe", "args": {"direction": "up", "times": 3}},
            {"type": "swipe", "args": {"direction": "up", "times": 2}}])
        e.case.steps[0].instructions[0].parameters = {"times": 5}
        plan = ScriptPlan(actions=[{"operation_id": "op0", "description": "滑动"}], omitted_segments=[
            {"operation_ids": ["op1"], "reason": "误认为多余", "state_effects": "页面未变化", "observation_ids": ["o1", "o2"]}])
        self.assertIn("parameter_coverage", [i.code for i in validate_plan(plan, e).issues])

    def test_known_failed_retry_can_be_removed_with_recovery_evidence(self):
        e = evidence(("a", "a", "b"))
        e.operations["op0"].execution.status = "failed"
        plan = ScriptPlan(actions=[{"operation_id": "op1", "description": "再次打开"}], omitted_segments=[
            {"operation_ids": ["op0"], "reason": "失败无副作用", "state_effects": "页面及必要状态未变", "observation_ids": ["o0", "o1"]}])
        self.assertFalse(validate_plan(plan, e).issues)


class PlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_parameters_failures_and_verifications_in_context(self):
        e = evidence(actions=[{"type": "input_text", "args": {"text": "原值\n$abc`"}}],
                     verifications=[{"id": "v1", "goal": "不保证成立的预期", "anchor": {"step_id": "s1"}}])
        captured = []
        class LLM:
            async def invoke_structured(self, messages, schema, **kwargs):
                captured.append(messages)
                return schema(plan={"actions": all_actions(e)})
        await plan_actions(e, LLM())
        data = json.loads(captured[0][1]["content"])
        self.assertEqual(data["operations"][0]["action"]["args"]["text"], "原值\n$abc`")
        self.assertEqual(data["case_spec"]["verifications"][0]["goal"], "不保证成立的预期")

    async def test_relevant_evidence_request_adds_frame_and_ui_then_finishes(self):
        e = evidence()
        captured = []
        class LLM:
            config = SimpleNamespace(capabilities=SimpleNamespace(supports_vision=True))
            async def invoke_structured(self, messages, schema, **kwargs):
                captured.append(list(messages))
                return schema(observation_requests=["o0"]) if len(captured) == 1 else schema(plan={"actions": all_actions(e)})
        plan = await plan_actions(e, LLM())
        self.assertEqual(len(plan.actions), 1)
        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[-1][-1]["content"][-1]["type"], "image_url")
        self.assertEqual(json.loads(captured[-1][-1]["content"][0]["text"])[0]["id"], "o0")

    async def test_repeated_requests_stop_with_explicit_problem(self):
        e = evidence()
        class LLM:
            async def invoke_structured(self, messages, schema, **kwargs):
                return schema(observation_requests=["o0"])
        plan = await plan_actions(e, LLM())
        self.assertEqual(plan.issues[0].code, "evidence_budget")
        self.assertTrue(plan.issues[0].blocking)
