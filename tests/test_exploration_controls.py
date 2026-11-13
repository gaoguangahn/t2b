import unittest
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage
from atestservice.contracts.case import CaseSpec
from atestservice.contracts.exploration import Trajectory
from atestservice.contracts.observation import DeviceObservation
from atestservice.exploration.case_step_runner import CaseStepRunnerNode
from atestservice.llm.messages import MessageBuilder


class ScriptedLLM:
    def __init__(self, calls):
        self.calls = iter(calls)
        self.requests = []

    @property
    def message_builder(self):
        return MessageBuilder()

    async def invoke_tool_message(self, messages, tools, **kwargs):
        self.requests.append(messages)
        name, args = next(self.calls)
        return AIMessage(content="", tool_calls=[{
            "id": str(len(self.requests)), "name": name, "args": {"reason": "visible evidence", **args},
        }])


def make_node(calls):
    llm = ScriptedLLM(calls)
    node = CaseStepRunnerNode(action_client=object(), llm=llm)
    node.step_loop.executor.execute = AsyncMock(return_value={"success": True})
    node.step_loop._settle_after_action = AsyncMock()

    async def observe(*, index):
        return DeviceObservation(id=f"obs{index}", index=index, screen_size={"width": 1000, "height": 2000},
                                 screenshot={"filename": f"{index}.jpg"})
    node.step_loop.observation_store.observe = observe
    return node, llm


class ExploreControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_consecutive_observe_is_not_an_operation(self):
        node, llm = make_node([
            ("Observe", {}), ("Observe", {}), ("Click", {"bounds": [10, 10, 100, 100]}),
            ("CompleteStep", {"summary": "done"}),
        ])
        case = CaseSpec(case_name="observe", steps=[{"id": "s1", "goal": "click"}])
        state = await node({"case_spec": case.model_dump(mode="json")})
        trajectory = state["trajectory"]
        self.assertEqual(len(trajectory["operations"]), 1)
        self.assertEqual(len(trajectory["observations"]), 4)
        self.assertEqual(trajectory["operations"][0]["observation_transition"],
                         {"before_observation_id": "obs2", "after_observation_id": "obs3"})
        Trajectory.model_validate(trajectory)
        self.assertEqual(node.step_loop.executor.execute.await_count, 1)
        for messages in llm.requests:
            self.assertEqual([m["role"] for m in messages], ["system", "user", "user"])

    async def test_unclassified_launch_instruction_can_use_start_app_and_cleanup(self):
        node, llm = make_node([
            ("StartApp", {"app_name": "应用 A"}),
            ("Click", {"bounds": [10, 10, 100, 100]}),
            ("CompleteStep", {"summary": "done"}),
        ])
        case = CaseSpec(case_name="launch", steps=[{"id": "s1", "goal": "启动应用 A", "instructions": [
            {"id": "i1", "text": "启动应用 A"},
        ]}])
        state = await node({"case_spec": case.model_dump(mode="json")})
        self.assertEqual(state["run"]["status"], "done")
        self.assertEqual(node.step_loop.executor.execute.await_count, 2)
        self.assertEqual(state["trajectory"]["operations"][0]["action"]["args"]["app_name"], "应用 A")
        self.assertIn("启动应用 A", str(llm.requests[0]))
        self.assertNotIn('"kind"', llm.requests[0][1]["content"])

    async def test_progress_advances_only_with_explicit_completion(self):
        node, _ = make_node([
            ("Click", {"bounds": [10, 10, 100, 100]}),
            ("CompleteInstruction", {"summary": "已进入目标页面"}),
            ("Back", {}),
            ("CompleteStep", {"summary": "done"}),
        ])
        case = CaseSpec(case_name="progress", steps=[{"id": "s1", "goal": "open and return", "instructions": [
            {"id": "i1", "text": "open"}, {"id": "i2", "text": "return"},
        ]}], verifications=[{"id": "v1", "goal": "expected", "anchor": {"step_id": "s1", "instruction_id": "i1"}}])
        state = await node({"case_spec": case.model_dump(mode="json")})
        self.assertEqual([op["semantic_ref"]["instruction_id"] for op in state["trajectory"]["operations"]], ["i1", "i2"])
        checkpoint = state["step_results"][0]["checkpoints"][0]
        self.assertEqual(checkpoint["observation_id"], "obs1")
        self.assertEqual(checkpoint["after_operation_id"], "op_0000")

    async def test_observation_budget_is_bounded(self):
        node, _ = make_node([("Observe", {})] * 4)
        case = CaseSpec(case_name="loading", steps=[{"id": "s1", "goal": "open"}])
        state = await node({"case_spec": case.model_dump(mode="json")})
        self.assertEqual(state["step_results"][0]["status"], "blocked")
        node.step_loop.executor.execute.assert_not_awaited()

    def test_unknown_observation_reference_is_rejected(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            Trajectory.model_validate({"observations": [{"id": "obs0"}], "operations": [{
                "id": "op0", "index": 0, "semantic_ref": {}, "intent": {}, "action": {}, "execution": {},
                "observation_transition": {"before_observation_id": "missing", "after_observation_id": None},
            }]})
