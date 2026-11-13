import json
import unittest
from unittest.mock import AsyncMock

from atestservice.contracts.case import CaseSpec
from atestservice.contracts.observation import DeviceObservation
from atestservice.exploration.context.ui_state import render_ui_state
from atestservice.exploration.tools.tool_definitions import EXPLORE_ACTION_TOOLS
from atestservice.llm.schema import strict_tool
from test_exploration_controls import make_node


class CompletionControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_category_cannot_restrict_composite_instruction_or_leak_into_context(self):
        node, llm = make_node([
            ("StartApp", {"app_name": "浏览器"}), ("Click", {"bounds": [100, 100, 200, 200]}),
            ("Back", {}), ("Home", {}), ("CompleteStep", {"summary": "完成复合流程"}),
        ])
        result = await node({"case_spec": {"steps": [{"id": "s1", "goal": "启动、关闭弹窗、返回桌面", "instructions": [
            {"id": "i1", "text": "启动浏览器、关闭弹窗后返回系统桌面", "kind": "app_launch"}]}]}})
        self.assertEqual(result["run"]["status"], "done")
        self.assertEqual([op["action"]["type"] for op in result["trajectory"]["operations"]], ["start_app", "click", "back", "home"])
        self.assertNotIn('"kind"', llm.requests[0][1]["content"])

    async def test_instruction_transition_is_not_gated_by_a_tool_category(self):
        node, _ = make_node([
            ("Click", {"bounds": [100, 100, 200, 200]}),
            ("Home", {"complete_current_instruction": True}), ("CompleteStep", {"summary": "done"}),
        ])
        case = CaseSpec(case_name="查看再回桌面", steps=[{"id": "s1", "goal": "查看并返回系统桌面", "instructions": [
            {"id": "i1", "text": "查看页面"}, {"id": "i2", "text": "返回系统桌面"}]}])
        result = await node({"case_spec": case.model_dump(mode="json")})
        self.assertEqual(result["run"]["status"], "done")
        self.assertEqual([op["semantic_ref"]["instruction_id"] for op in result["trajectory"]["operations"]], ["i1", "i2"])
    async def test_launch_can_dismiss_popup_before_completing_last_instruction(self):
        node, llm = make_node([
            ("StartApp", {"app_name": "QQ浏览器"}),
            ("Click", {"bounds": [100, 100, 200, 200]}),
            ("CompleteStep", {"summary": "QQ浏览器已启动并关闭遮挡弹窗"}),
        ])
        case = CaseSpec(case_name="启动浏览器", steps=[{"id": "s1", "goal": "启动QQ浏览器", "instructions": [
            {"id": "i1", "text": "启动QQ浏览器"}]}],
            verifications=[{"id": "v1", "goal": "原预期", "anchor": {"step_id": "s1", "instruction_id": "i1"}}])
        result = await node({"case_spec": case.model_dump(mode="json")})
        self.assertEqual(result["run"]["status"], "done")
        self.assertEqual([op["action"]["type"] for op in result["trajectory"]["operations"]], ["start_app", "click"])
        self.assertEqual([op["semantic_ref"]["instruction_id"] for op in result["trajectory"]["operations"]], ["i1", "i1"])
        self.assertEqual(result["step_results"][0]["checkpoints"][0]["observation_id"], "obs2")
        self.assertEqual(len(llm.requests), 3)
        self.assertEqual(node.step_loop.executor.execute.await_count, 2)

    async def test_launch_popup_cleanup_preserves_boundary_before_next_instruction(self):
        node, llm = make_node([
            ("StartApp", {"app_name": "QQ浏览器"}),
            ("Click", {"bounds": [100, 100, 200, 200]}),
            ("Click", {"bounds": [300, 300, 400, 400], "complete_current_instruction": True}),
            ("CompleteStep", {"summary": "已进入搜索"}),
        ])
        case = CaseSpec(case_name="启动后搜索", steps=[{"id": "s1", "goal": "启动QQ浏览器并搜索", "instructions": [
            {"id": "i1", "text": "启动QQ浏览器"}, {"id": "i2", "text": "进入搜索"}]}],
            verifications=[{"id": "v1", "goal": "原预期", "anchor": {"step_id": "s1", "instruction_id": "i1"}}])
        result = await node({"case_spec": case.model_dump(mode="json")})
        self.assertEqual(result["run"]["status"], "done")
        self.assertEqual([op["semantic_ref"]["instruction_id"] for op in result["trajectory"]["operations"]], ["i1", "i1", "i2"])
        self.assertEqual(result["step_results"][0]["checkpoints"][0]["observation_id"], "obs2")
        self.assertEqual(len(llm.requests), 4)

    async def test_last_instruction_flag_is_rejected_without_advancing(self):
        node, llm = make_node([
            ("Click", {"bounds": [100, 100, 200, 200], "complete_current_instruction": True}),
            ("Click", {"bounds": [800, 100, 900, 200]}),
            ("CompleteStep", {"summary": "开关已关闭"}),
        ])
        llm.invoke_structured = AsyncMock(side_effect=AssertionError("No independent completion call"))
        result = await node({"case_spec": {"steps": [{"id": "s1", "goal": "关闭开关"}]}})
        self.assertEqual(result["run"]["status"], "done")
        self.assertEqual(node.step_loop.executor.execute.await_count, 1)
        self.assertEqual(len(result["trajectory"]["operations"]), 1)
        self.assertIn("最后一条指令", str(llm.requests[1]))
        self.assertIn("已报告完成的要求 ID：[]", llm.requests[1][1]["content"])
        llm.invoke_structured.assert_not_awaited()

    async def test_current_page_drives_retry_then_finish_without_secondary_model(self):
        node, llm = make_node([
            ("Click", {"bounds": [600, 100, 700, 200]}),
            ("Click", {"bounds": [800, 100, 900, 200]}),
            ("CompleteStep", {"summary": "开关已关闭"}),
        ])
        llm.invoke_structured = AsyncMock(side_effect=AssertionError("No independent completion call"))

        async def observe(*, index):
            return DeviceObservation(id=f"obs{index}", index=index,
                screen_size={"width": 1000, "height": 2000}, screenshot={"filename": f"{index}.jpg"},
                elements=[{"text": "Wi-Fi", "resourceId": "settings:id/switch", "checked": index < 2}])

        node.step_loop.observation_store.observe = observe
        case = CaseSpec(case_name="wifi", steps=[{"id": "s1", "goal": "关闭Wi-Fi"}], verifications=[{
            "id": "v1", "goal": "BUSINESS_EXPECTATION", "anchor": {"step_id": "s1"}}])
        result = await node({"case_spec": case.model_dump(mode="json")})
        self.assertEqual(result["run"]["status"], "done")
        self.assertEqual(node.step_loop.executor.execute.await_count, 2)
        pages = [json.loads(messages[2]["content"][0]["text"].split("当前控件状态证据：")[1]) for messages in llm.requests]
        self.assertEqual([page["controls"][0]["checked"] for page in pages], [True, True, False])
        self.assertNotIn("BUSINESS_EXPECTATION", str(llm.requests))
        self.assertEqual(result["step_results"][0]["checkpoints"][0]["observation_id"], "obs2")
        self.assertEqual(result["step_results"][0]["instruction_results"][0]["status"], "completed")
        llm.invoke_structured.assert_not_awaited()

    async def test_persistent_last_instruction_flag_never_completes_or_dispatches_action(self):
        node, _ = make_node([("Click", {"bounds": [100, 100, 200, 200], "complete_current_instruction": True})] * 3)
        node.step_loop.config.step_attempt_limit = 3
        result = await node({"case_spec": {"steps": [{"id": "s1", "goal": "关闭开关"}]}})
        self.assertEqual(result["run"]["status"], "failed")
        self.assertEqual(result["step_results"][0]["instruction_results"][0]["status"], "in_progress")
        node.step_loop.executor.execute.assert_not_awaited()

    def test_only_phone_action_schemas_expose_completion_flag(self):
        control_tools = {"Observe", "CompleteInstruction", "CompleteStep", "ReportBlocker"}
        for tool in EXPLORE_ACTION_TOOLS:
            with self.subTest(tool=tool.__name__):
                properties = strict_tool(tool)["function"]["parameters"]["properties"]
                self.assertEqual("complete_current_instruction" in properties, tool.__name__ not in control_tools)

    async def test_transition_combines_next_action_and_preserves_both_boundary_checkpoints(self):
        node, llm = make_node([
            ("Click", {"bounds": [100, 100, 200, 200]}),
            ("Back", {"complete_current_instruction": True}),
            ("CompleteStep", {"summary": "已返回"}),
        ])
        llm.invoke_structured = AsyncMock(side_effect=AssertionError("No independent completion call"))
        case = CaseSpec(case_name="navigation", steps=[{"id": "s1", "goal": "打开并返回", "instructions": [
            {"id": "i1", "text": "打开页面"}, {"id": "i2", "text": "返回"}]}], verifications=[
            {"id": "v1", "goal": "原预期1", "anchor": {"step_id": "s1", "instruction_id": "i1", "position": "after"}},
            {"id": "v2", "goal": "原预期2", "anchor": {"step_id": "s1", "instruction_id": "i2", "position": "before"}},
        ])
        result = await node({"case_spec": case.model_dump(mode="json")})
        self.assertEqual(len(llm.requests), 3)
        self.assertEqual(node.step_loop.executor.execute.await_count, 2)
        self.assertEqual([op["semantic_ref"]["instruction_id"] for op in result["trajectory"]["operations"]], ["i1", "i2"])
        self.assertEqual([c["verification_id"] for c in result["step_results"][0]["checkpoints"]], ["v1", "v2"])
        for checkpoint in result["step_results"][0]["checkpoints"]:
            self.assertEqual(checkpoint["observation_id"], "obs1")
            self.assertEqual(checkpoint["after_operation_id"], "op_0000")
        self.assertIn('"id": "i2"', llm.requests[1][1]["content"].split("紧邻的下一条要求：")[1])
        llm.invoke_structured.assert_not_awaited()


    async def test_malformed_next_action_is_rejected_before_progress_changes(self):
        node, llm = make_node([
            ("Click", {"bounds": [100, 100, 200, 200]}),
            ("Click", {"bounds": [200, 100, 100, 200], "complete_current_instruction": True}),
            ("Back", {"complete_current_instruction": True}),
            ("CompleteStep", {"summary": "已返回"}),
        ])
        result = await node({"case_spec": {"steps": [{"id": "s1", "goal": "打开并返回", "instructions": [
            {"id": "i1", "text": "打开"}, {"id": "i2", "text": "返回"}]}]}})
        self.assertEqual(result["run"]["status"], "done")
        self.assertEqual(node.step_loop.executor.execute.await_count, 2)
        self.assertIn("当前要求 ID：i1", llm.requests[2][1]["content"])

    def test_ui_state_preserves_false_missing_fields_aliases_and_limits(self):
        state = json.loads(render_ui_state({"id": "obs", "elements": [
            {"resource-id": "switch", "content-desc": "Wi-Fi", "checked": False},
            {"text": "other", "enabled": False}, {"text": "missing"}]}))
        self.assertIs(state["controls"][0]["checked"], False)
        self.assertEqual(state["controls"][0]["content-desc"], "Wi-Fi")
        self.assertNotIn("checked", state["controls"][1])
        bounded = json.loads(render_ui_state({"elements": [{"checked": True}] * 100}))
        self.assertEqual(len(bounded["controls"]), 60)
        self.assertEqual(bounded["omitted"], 40)
