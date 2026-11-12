import unittest
from unittest.mock import AsyncMock

from test_exploration_controls import make_node


class Publisher:
    def __init__(self):
        self.events = []

    async def node_started(self, **event):
        pass

    async def node_finished(self, **event):
        self.events.append(event)


class StepEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_step_publishes_one_result_with_terminal_decision(self):
        calls = []
        for number in (1, 2):
            calls.extend([
                ("Click", {"bounds": [10, 10, 100, 100]}),
                ("CompleteStep", {"summary": f"done {number}", "complete_current_instruction": True}),
            ])
        node, _ = make_node(calls)
        publisher = Publisher()
        result = await node({"case_spec": {"steps": [
            {"id": "s1", "goal": "click first"}, {"id": "s2", "goal": "click second"}]},
            "event_publisher": publisher})
        self.assertEqual(result["run"]["status"], "done")
        finished = [e for e in publisher.events if e["node"] == "case_step_finished"]
        self.assertEqual(len(finished), 2)
        for index, event in enumerate(finished, 1):
            self.assertEqual(event["payload"]["title"], f"目标块 s{index} 执行完成")
            blocks = event["payload"]["blocks"]
            self.assertEqual(blocks[-1]["content"]["raw_tool_call"]["name"], "CompleteStep")
            texts = [b["text"] for e in publisher.events for b in e["payload"]["blocks"] if b["type"] == "text"]
            self.assertEqual(texts.count(f"done {index}"), 1)
        self.assertFalse(any(e["node"] == "step_agent_loop" for e in publisher.events))
        self.assertEqual([e["payload"]["title"] for e in publisher.events if e["node"] == "run_case_steps"], ["探索阶段完成"])
        self.assertNotIn("completion_event", result)
        self.assertTrue(all("completion_event" not in step for step in result["step_results"]))

    async def test_failure_and_blocker_have_accurate_titles_and_no_success_notice(self):
        for tool, args, status, title in (
            ("CompleteStep", {"status": "error", "summary": "cannot finish"}, "error", "执行失败"),
            ("ReportBlocker", {"summary": "login required"}, "blocked", "遇到阻塞"),
        ):
            with self.subTest(status=status):
                node, _ = make_node([(tool, args)])
                publisher = Publisher()
                result = await node({"case_spec": {"steps": [{"id": "s1", "goal": "click"}]}, "event_publisher": publisher})
                self.assertEqual(result["step_results"][0]["status"], status)
                self.assertEqual(result["run"]["status"], "failed")
                self.assertEqual(len(publisher.events), 2)  # Initial observation and one terminal result.
                self.assertEqual(publisher.events[-1]["payload"]["title"], f"目标块 s1 {title}")
                self.assertEqual(publisher.events[-1]["payload"]["blocks"][-1]["content"]["raw_tool_call"]["name"], tool)

    async def test_rejected_completion_is_not_announced_as_success(self):
        node, _ = make_node([
            ("CompleteStep", {"summary": "premature"}),
            ("Click", {"bounds": [10, 10, 100, 100]}),
            ("CompleteStep", {"summary": "done", "complete_current_instruction": True}),
        ])
        publisher = Publisher()
        await node({"case_spec": {"steps": [{"id": "s1", "goal": "click"}]}, "event_publisher": publisher})
        rejected = [e for e in publisher.events if e["node"] == "step_finish_rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["payload"]["title"], "目标块结束请求未通过")
        self.assertEqual(len([e for e in publisher.events if e["node"] == "case_step_finished"]), 1)

    async def test_program_failure_without_terminal_tool_still_has_failure_event(self):
        node, _ = make_node([])
        node.step_loop = AsyncMock(return_value={"current_step_result": {
            "step_id": "s1", "status": "error", "summary": "invalid tool calls"}})
        publisher = Publisher()
        await node({"case_spec": {"steps": [{"id": "s1", "goal": "click"}]}, "event_publisher": publisher})
        self.assertEqual(len(publisher.events), 1)
        self.assertEqual(publisher.events[0]["payload"]["title"], "目标块 s1 执行失败")
