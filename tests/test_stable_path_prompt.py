import unittest

from atestservice.contracts.case import CaseSpec
from atestservice.exploration.context.facts import parameter_action_ledger
from atestservice.exploration.context.rendering import render_recent_step_actions
from atestservice.exploration.context.message_context import AgentLoopContext
from atestservice.exploration.prompts import SYSTEM_PROMPT
from atestservice.exploration.tools import EXPLORE_ACTION_TOOLS
from atestservice.llm.messages import MessageBuilder
from types import SimpleNamespace
from test_exploration_controls import make_node


class StablePathPromptTests(unittest.TestCase):
    def test_method_guidance_matches_real_tools_without_instruction_categories(self):
        names = {tool.__name__ for tool in EXPLORE_ACTION_TOOLS}
        for name in ("StartApp", "StopApp", "Home", "OpenMultitask", "OpenControl", "OpenNotification"):
            self.assertIn(name, names)
            self.assertIn(name, SYSTEM_PROMPT)
        self.assertNotIn("{method_rules}", SYSTEM_PROMPT)
        self.assertNotIn("kind=", SYSTEM_PROMPT)

    def test_current_page_includes_foreground_facts_without_internal_artifacts(self):
        messages = AgentLoopContext(system_prompt="rules", task_text="task").build_messages(
            llm=SimpleNamespace(message_builder=MessageBuilder()),
            observation={"id": "obs1", "package": "example.app", "activity": "Main",
                         "screenshot": {"filename": "internal.jpg"}})
        text = str(messages[-1]["content"])
        self.assertIn("example.app", text)
        self.assertIn("Main", text)
        self.assertNotIn("internal.jpg", text)

    def test_full_parameter_ledger_survives_recent_action_cutoff(self):
        operations = []
        for index in range(9):
            operations.append({"id": f"op{index}", "semantic_ref": {"step_id": "s1", "instruction_id": "i1"},
                "action": {"type": "swipe", "args": {"direction": "up", "times": 2, "interval": 3}},
                "intent": {"tool_name": "DirectionSwipe", "reason": "浏览列表"},
                "execution": {"status": "succeeded"}})
        operations.append({"id": "partial", "semantic_ref": {"step_id": "s1", "instruction_id": "i1"},
            "action": {"type": "swipe", "args": {"direction": "up", "times": 2, "interval": 3}},
            "intent": {"tool_name": "DirectionSwipe", "reason": "浏览列表"},
            "execution": {"status": "failed", "completed_count": 1}})
        trace = {"operations": operations}
        succeeded, failed = parameter_action_ledger(trace, "s1")
        self.assertEqual(succeeded["command_count"], 9)
        self.assertEqual(succeeded["requested_total"], 18)
        self.assertIsNone(succeeded["device_reported_count"])
        self.assertEqual(failed["device_reported_count"], 1)
        recent = render_recent_step_actions(trajectory=trace, step_id="s1", limit=6)
        self.assertNotIn("op0 ", recent)
        self.assertIn('"times": 2', recent)
        self.assertIn("failed", recent)

    def test_wait_ledger_does_not_include_observation_wait(self):
        trace = {"operations": [{"semantic_ref": {"step_id": "s1", "instruction_id": "i1"},
            "action": {"type": "wait", "args": {"duration": 10}}, "execution": {"status": "succeeded"}}] * 3}
        ledger = parameter_action_ledger(trace, "s1")
        self.assertEqual(ledger[0]["requested_total"], 30)
        self.assertEqual(ledger[0]["unit"], "seconds")
        self.assertEqual(parameter_action_ledger(trace, "other_step"), [])


class SemanticInstructionTests(unittest.IsolatedAsyncioTestCase):
    async def test_return_home_can_require_multiple_actions(self):
        node, llm = make_node([
            ("Back", {}), ("Back", {}), ("Click", {"bounds": [10, 10, 100, 100]}),
            ("CompleteStep", {"summary": "已到应用首页"}),
        ])
        case = CaseSpec(case_name="返回首页", steps=[{"id": "s1", "goal": "返回应用首页"}])
        result = await node({"case_spec": case.model_dump(mode="json")})
        operations = result["trajectory"]["operations"]
        self.assertEqual(len(operations), 3)
        self.assertEqual(len({operation["semantic_ref"]["instruction_id"] for operation in operations}), 1)
        self.assertEqual(result["step_results"][0]["status"], "completed")
        self.assertIn("一条指令可以需要多个工具动作", llm.requests[0][0]["content"])
        self.assertIn("当前要求 ID", llm.requests[0][1]["content"])

    async def test_large_wait_context_retains_full_requested_duration(self):
        node, llm = make_node([
            ("Wait", {"duration": 10}), ("Wait", {"duration": 10}), ("Wait", {"duration": 10}),
            ("CompleteStep", {"summary": "等待完成"}),
        ])
        case = CaseSpec(case_name="等待", steps=[{"id": "s1", "goal": "等待30秒"}])
        await node({"case_spec": case.model_dump(mode="json")})
        task = llm.requests[-1][1]["content"]
        self.assertIn('"requested_total": 30', task)
        self.assertIn('"device_reported_count": null', task)
        # The feedback is a command result; it does not invent a business assertion.
        self.assertIn('"execution_status": "succeeded"', task)
