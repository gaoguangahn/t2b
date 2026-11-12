import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from pydantic import ValidationError
from generation_fixtures import evidence, element, all_actions
from atestservice.contracts.script import ScriptIR, ScriptPlan, TargetResolution
from atestservice.script_generation.ir_builder import build_script_ir
from atestservice.script_generation.pipeline import generate_script
from atestservice.script_generation.codegen import generate_code
from atestservice.script_generation.script_gen_node import ScriptGenNode
from atestservice.script_generation.targeting.resolver import resolve_targets


class GeneratorLLM:
    def __init__(self, e, plan=None, extra_notes=None):
        self.e = e
        self.plan = plan or ScriptPlan(actions=all_actions(e))
        self.requests = []
        self.extra_notes = extra_notes or []

    async def invoke_structured(self, messages, schema, **kwargs):
        self.requests.append((schema.__name__, deepcopy(messages)))
        if schema.__name__ == "PlanningResponse":
            return schema(plan=self.plan)
        if schema.__name__ == "TargetResponse":
            request = json.loads(messages[1]["content"])
            if request["elements"]:
                target = {"request_id": request["request_id"], "kind": "ui", "target_description": "固定搜索入口",
                          "candidate_id": "e0", "attributes": ["resource_id"], "reason": "入口 ID 与操作位置对应"}
            else:
                target = {"request_id": request["request_id"], "kind": "unresolved", "target_description": "目标",
                          "reason": "当前 UI 无可用属性"}
            return schema(targets=[target])
        if schema.__name__ == "CodegenResult":
            return schema(framework="dynamic_framework", filename="test_search.py", content=
                          "def test_search(self):\n    self.device.click(resourceId='app:id/search')\n", notes=self.extra_notes)
        raise AssertionError(schema.__name__)


class IRTests(unittest.IsolatedAsyncioTestCase):
    async def test_conditions_repeats_and_all_verification_positions(self):
        verifications = []
        for identifier, position, scope, instruction in [
            ("outside_before", "before", "outside_repeat", None), ("each_before", "before", "each_iteration", None),
            ("instruction_before", "before", "each_iteration", "i1"), ("instruction_after", "after", "each_iteration", "i1"),
            ("each_after", "after", "each_iteration", None), ("outside_after", "after", "outside_repeat", None)]:
            verifications.append({"id": identifier, "goal": "用户预期" + identifier,
                                  "anchor": {"step_id": "s1", "instruction_id": instruction, "position": position}, "scope": scope})
        e = evidence(("start", "dismissed", "confirmed"), elements=[element(resourceId="app:id/search")],
                     repeat=5, verifications=verifications)
        plan = ScriptPlan(actions=[{"operation_id": "op0", "description": "偶发引导关闭", "condition_id": "c1"},
                                   {"operation_id": "op1", "description": "用户要求的业务确认"}],
                          conditions=[{"id": "c1", "description": "当引导出现时"}])
        targets = await resolve_targets(e, plan, GeneratorLLM(e))
        ir = build_script_ir(e, plan, targets)
        self.assertEqual([n.type for n in ir.steps], ["verify", "repeat", "verify"])
        body = ir.steps[1].body
        self.assertEqual([n.type for n in body], ["verify", "verify", "condition", "action", "verify", "verify"])
        self.assertEqual(body[2].body[0].source_operation_id, "op0")
        self.assertEqual(body[3].source_operation_id, "op1")
        self.assertEqual(ir.steps[1].times, 5)
        self.assertNotIn("is_popup_handler", ir.model_dump_json())
        self.assertEqual(ScriptIR.model_validate_json(ir.model_dump_json()), ir)

    async def test_user_expectation_survives_different_actual_amount(self):
        e = evidence(elements=[element("99元", resourceId="app:id/amount")], verifications=[
            {"id": "v1", "goal": "实付金额为100元", "anchor": {"step_id": "s1"}}])
        targets = await resolve_targets(e, ScriptPlan(actions=all_actions(e)), GeneratorLLM(e))
        ir = build_script_ir(e, ScriptPlan(actions=all_actions(e)), targets)
        self.assertEqual(ir.steps[-1].expectation, "实付金额为100元")
        self.assertEqual(ir.steps[-1].target.locator.selector.resource_id, "app:id/amount")

    async def test_parameter_literals_and_coordinate_math_are_deterministic(self):
        original = " 原文\n$price`\" "
        e = evidence(("a", "b", "c", "d", "e"), actions=[
            {"type": "click", "args": {"bounds": [100, 200, 300, 400]}},
            {"type": "input_text", "args": {"text": original}},
            {"type": "swipe", "args": {"direction": "up", "times": 7, "interval": 2.5}},
            {"type": "drag", "args": {"start": {"x": 100, "y": 200}, "end": {"x": 900, "y": 800}}}])
        target = TargetResolution(description="点击", status="coordinate", point=(0.2, 0.3))
        ir = build_script_ir(e, ScriptPlan(actions=all_actions(e)), {"op0": target})
        self.assertEqual(ir.steps[1].parameters.text, original)
        self.assertEqual(ir.steps[2].parameters.times, 7)
        self.assertEqual(ir.steps[2].parameters.interval, 2.5)
        self.assertEqual(ir.steps[3].parameters.start, (0.1, 0.2))
        self.assertEqual(ir.steps[3].parameters.end, (0.9, 0.8))


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_and_draft_are_distinct_and_evidence_is_not_mutated(self):
        e = evidence(elements=[element(resourceId="app:id/search")])
        original = e.exploration.model_dump()
        result = await generate_script(e.case, e.exploration, llm=GeneratorLLM(e))
        self.assertEqual(result.status, "ready")
        self.assertEqual(e.exploration.model_dump(), original)
        self.assertEqual(result.ir.steps[0].target.locator.selector.resource_id, "app:id/search")
        result = await generate_script(e.case, e.exploration, llm=GeneratorLLM(e, extra_notes=["框架缺少某项能力"]))
        self.assertEqual(result.status, "draft")
        self.assertIn("框架缺少某项能力", result.script.notes)

    async def test_coordinate_and_missing_validation_target_keep_notes(self):
        e = evidence(elements=[], verifications=[{"id": "v1", "goal": "错误提示不存在", "anchor": {"step_id": "s1"}}])
        result = await generate_script(e.case, e.exploration, llm=GeneratorLLM(e))
        self.assertEqual(result.status, "draft")
        self.assertEqual(result.ir.steps[-1].expectation, "错误提示不存在")
        self.assertGreaterEqual(len(result.script.notes), 2)

    async def test_blocked_plan_never_reaches_locator_or_codegen_and_is_returned(self):
        e = evidence()
        plan = ScriptPlan(actions=all_actions(e), issues=[{"code": "state_effect", "message": "业务影响不明", "blocking": True}])
        llm = GeneratorLLM(e, plan=plan)
        result = await generate_script(e.case, e.exploration, llm=llm)
        self.assertEqual(result.status, "blocked")
        self.assertIsNone(result.script)
        self.assertEqual([name for name, _ in llm.requests], ["PlanningResponse"])
        state = await ScriptGenNode(llm)({"case_spec": e.case, "exploration_result": e.exploration, "run": {"status": "done"}})
        self.assertEqual(state["result"]["status"], "blocked")
        self.assertEqual(state["run"]["status"], "failed")

    async def test_incomplete_exploration_cannot_be_exported_as_ready(self):
        e = evidence()
        e.exploration.step_results[0].status = "blocked"
        result = await generate_script(e.case, e.exploration, llm=GeneratorLLM(e))
        self.assertEqual(result.status, "blocked")
        self.assertIn("incomplete_exploration", [i.code for i in result.plan.issues])

    async def test_codegen_gets_only_ir_and_profile_with_no_raw_trajectory(self):
        e = evidence(elements=[element(resourceId="app:id/search")])
        llm = GeneratorLLM(e)
        await generate_script(e.case, e.exploration, llm=llm)
        messages = next(messages for name, messages in llm.requests if name == "CodegenResult")
        self.assertEqual(set(json.loads(messages[1]["content"])), {"ir", "codegen_profile"})
        self.assertIn("condition", messages[0]["content"])
        self.assertNotIn("is_popup_handler", str(messages))

    async def test_codegen_rejects_syntax_error_empty_file_and_path_filename(self):
        ir = ScriptIR(case_name="test", steps=[{"type": "verify", "verification_id": "v1", "expectation": "用户预期",
                    "anchor": {"step_id": "s1"}, "target": {"description": "目标", "status": "unresolved"}}])
        for content, filename in [("def bad(:", "test_bad.py"), ("", "test_empty.py"), ("def test_x():\n    pass", "../test_escape.py")]:
            class LLM:
                async def invoke_structured(self, messages, schema, **kwargs):
                    return schema(framework="dynamic_framework", filename=filename, content=content)
            with self.subTest(filename=filename), self.assertRaises((ValueError, SyntaxError)):
                await generate_code(ir, llm=LLM())
