"""Invalid model responses may be corrected before any phone operation is issued."""
import unittest
from datetime import datetime, timezone

from langchain_core.messages import AIMessage

from atestservice.contracts.case import CaseSpec
from atestservice.contracts.observation import DeviceObservation
from test_exploration_controls import ScriptedLLM, make_node
from test_step_events import Publisher


def tool(name="Click", **args):
    if name == "Click":
        args.setdefault("bounds", [10, 10, 100, 100])
    return AIMessage(content="", tool_calls=[{"id": "fixture", "name": name, "args": {"reason": "页面依据", **args}}])


class ResponsesLLM(ScriptedLLM):
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def invoke_tool_message(self, messages, tools, **kwargs):
        self.requests.append(messages)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def node_for(responses):
    node, _ = make_node([])
    llm = ResponsesLLM(responses)
    node.step_loop.llm = llm
    return node, llm


def one_step():
    return CaseSpec(case_name="点击", steps=[{"id": "s1", "goal": "点击目标"}]).model_dump(mode="json")


class DecisionRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_step_five_recovers_without_replaying_completed_steps(self):
        responses = [response for number in range(4) for response in (tool(), tool("CompleteStep", summary=f"done{number}"))]
        responses += [AIMessage(content="应当点击目标"), tool(), tool("CompleteStep", summary="done5")]
        node, llm = node_for(responses)
        publisher = Publisher()
        case = CaseSpec(case_name="五步", steps=[{"id": f"s{i}", "goal": f"点击目标{i}"} for i in range(1, 6)])
        with self.assertLogs("atestservice.exploration.decision_request", level="WARNING") as logged:
            result = await node({"case_spec": case.model_dump(mode="json"), "event_publisher": publisher})
        self.assertEqual(result["run"]["status"], "done")
        self.assertEqual(node.step_loop.executor.execute.await_count, 5)
        self.assertEqual(len(result["trajectory"]["operations"]), 5)
        self.assertEqual(len(result["trajectory"]["observations"]), 6)
        self.assertEqual(len(llm.requests), 11)
        self.assertEqual([step["status"] for step in result["step_results"]], ["completed"] * 5)
        self.assertEqual(len([event for event in publisher.events if event["node"] == "case_step_finished"]), 5)
        retries = [event for event in publisher.events if event["node"] == "decision_retry"]
        self.assertEqual(len(retries), 1)
        self.assertEqual(retries[0]["payload"]["blocks"][0]["type"], "text")
        correction = llm.requests[9][1]["content"]
        self.assertIn("本轮响应纠正要求", correction)
        self.assertIn("没有下发任何手机动作", correction)
        self.assertIn("当前操作块：s5", correction)
        self.assertIn('"step_id": "s5"', " ".join(logged.output))

    async def test_invalid_json_multiple_calls_and_partial_response_are_all_discarded(self):
        malformed = AIMessage(content="", invalid_tool_calls=[{"id": "bad", "name": "Click", "args": '{"bounds":', "error": "invalid"}])
        multiple = AIMessage(content="", tool_calls=tool().tool_calls + tool("Back").tool_calls)
        truncated = tool()
        truncated.response_metadata = {"finish_reason": "length"}
        mixed = AIMessage(content="", tool_calls=tool().tool_calls, invalid_tool_calls=malformed.invalid_tool_calls)
        for response in (malformed, multiple, truncated, mixed):
            with self.subTest(response=response.type):
                node, llm = node_for([response, tool(), tool("CompleteStep", summary="done")])
                with self.assertLogs("atestservice.exploration.decision_request", level="WARNING"):
                    result = await node({"case_spec": one_step()})
                self.assertEqual(result["run"]["status"], "done")
                self.assertEqual(node.step_loop.executor.execute.await_count, 1)
                self.assertEqual(len(result["trajectory"]["operations"]), 1)
                self.assertEqual(len(llm.requests), 3)

    async def test_bad_parameters_get_specific_feedback_and_retries_have_a_separate_budget(self):
        node, llm = node_for([tool(bounds=[10]), tool(), tool("CompleteStep", summary="done")])
        node.step_loop.config.execution_error_limit = 1
        with self.assertLogs("atestservice.exploration.decision_request", level="WARNING"):
            result = await node({"case_spec": one_step()})
        self.assertEqual(result["run"]["status"], "done")
        self.assertIn("bounds", llm.requests[1][1]["content"])
        self.assertEqual(node.step_loop.executor.execute.await_count, 1)

    async def test_second_invalid_response_exhausts_budget_and_reports_failure(self):
        node, llm = node_for([AIMessage(content="text"), AIMessage(content="text"), tool()])
        publisher = Publisher()
        with self.assertLogs("atestservice.exploration.decision_request", level="WARNING"):
            result = await node({"case_spec": one_step(), "event_publisher": publisher})
        self.assertEqual(result["run"]["status"], "failed")
        self.assertIn("连续 2 次", result["step_results"][0]["summary"])
        self.assertEqual(result["step_results"][0]["instruction_results"][0]["status"], "in_progress")
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(result["trajectory"]["operations"], [])
        node.step_loop.executor.execute.assert_not_awaited()
        self.assertIn("执行失败", publisher.events[-1]["payload"]["title"])

    async def test_truncated_advance_flag_cannot_move_cursor_or_verification_anchor(self):
        truncated = tool(complete_current_instruction=True)
        truncated.response_metadata = {"finish_reason": "length"}
        node, llm = node_for([truncated, tool(), tool("Back", complete_current_instruction=True), tool("CompleteStep", summary="done")])
        case = CaseSpec(case_name="进入并返回", steps=[{"id": "s1", "goal": "进入并返回", "instructions": [
            {"id": "i1", "text": "进入页面"}, {"id": "i2", "text": "返回"}]}],
            verifications=[{"id": "v1", "goal": "用户预期", "anchor": {"step_id": "s1", "instruction_id": "i1"}}])
        with self.assertLogs("atestservice.exploration.decision_request", level="WARNING"):
            result = await node({"case_spec": case.model_dump(mode="json")})
        self.assertIn("当前要求 ID：i1", llm.requests[1][1]["content"])
        self.assertEqual([operation["semantic_ref"]["instruction_id"] for operation in result["trajectory"]["operations"]], ["i1", "i2"])
        self.assertEqual(result["step_results"][0]["checkpoints"][0]["observation_id"], "obs1")

    async def test_retry_refreshes_stale_observation_and_records_action_against_it(self):
        node, llm = node_for([AIMessage(content="text"), tool(), tool("CompleteStep", summary="done")])
        node.step_loop.config.observation_max_age_seconds = float("inf")
        original_call = llm.invoke_tool_message
        async def invoke(*args, **kwargs):
            response = await original_call(*args, **kwargs)
            node.step_loop.config.observation_max_age_seconds = 30
            return response
        llm.invoke_tool_message = invoke
        async def observe(*, index):
            return DeviceObservation(id=f"o{index}", index=index, screen_size={"width": 1000, "height": 2000},
                screenshot={"filename": f"{index}.jpg"}, capture_finished_at=(
                    "2000-01-01T00:00:00+00:00" if index == 0 else datetime.now(timezone.utc).isoformat()))
        node.step_loop.observation_store.observe = observe
        with self.assertLogs("atestservice.exploration.decision_request", level="WARNING"):
            result = await node({"case_spec": one_step()})
        self.assertIn("observation_id=o1", str(llm.requests[1][-1]))
        self.assertEqual(result["trajectory"]["operations"][0]["observation_transition"]["before_observation_id"], "o1")
        self.assertEqual(len(result["trajectory"]["observations"]), 3)

    async def test_provider_error_is_not_treated_as_a_correctable_response(self):
        node, llm = node_for([RuntimeError("provider rejected request"), tool()])
        with self.assertRaisesRegex(RuntimeError, "provider rejected"):
            await node({"case_spec": one_step()})
        self.assertEqual(len(llm.requests), 1)
        node.step_loop.executor.execute.assert_not_awaited()

    async def test_valid_decision_has_no_extra_call_or_retry_event(self):
        node, llm = node_for([tool(), tool("CompleteStep", summary="done")])
        publisher = Publisher()
        result = await node({"case_spec": one_step(), "event_publisher": publisher})
        self.assertEqual(result["run"]["status"], "done")
        self.assertEqual(len(llm.requests), 2)
        self.assertFalse(any(event["node"] == "decision_retry" for event in publisher.events))
