import json
import unittest
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage

from atestservice.contracts.case import CaseSpec
from atestservice.exploration.config import AgentConfig
from atestservice.llm.messages import MessageBuilder
from atestservice.exploration.case_step_runner import CaseStepRunnerNode
from atestservice.contracts.observation import DeviceObservation
from atestservice.contracts.exploration import ExplorationResult
from atestservice.contracts.script import ScriptPlan, TargetResolution
from atestservice.script_generation.evidence import Evidence
from atestservice.script_generation.ir_builder import build_script_ir
from atestservice.contracts.rendering import render_case


class FakeLLM:
    def __init__(self):
        self.requests = []
        self.calls = iter([
            ("Click", {"bounds": [100, 100, 200, 200]}),
            ("CompleteInstruction", {"summary": "searched"}),
            ("Back", {}),
            ("CompleteInstruction", {"summary": "returned"}),
            ("CompleteStep", {"summary": "done", "status": "completed"}),
        ])

    @property
    def message_builder(self):
        return MessageBuilder()

    async def invoke_tool_message(self, messages, tools, **kwargs):
        self.requests.append(messages)
        name, args = next(self.calls)
        return AIMessage(content="", tool_calls=[{
            "id": str(len(self.requests)), "name": name, "args": {"reason": "visible target", **args},
        }])


def example_case():
    return CaseSpec.model_validate({
        "case_name": "search", "steps": [{"id": "s1", "goal": "search and return", "repeat": 7,
            "instructions": [{"id": "i1", "text": "search"}, {"id": "i2", "text": "return"}]}],
        "verifications": [
            {"id": "v1", "goal": "UNSEEN_EXPECTATION", "anchor": {"step_id": "s1", "instruction_id": "i1"}},
            {"id": "v2", "goal": "outside", "anchor": {"step_id": "s1"}, "scope": "outside_repeat"},
        ],
    })


class ExplorationFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_executed_action_survives_observation_failure(self):
        node = CaseStepRunnerNode(action_client=object(), llm=FakeLLM())
        node.step_loop.executor.execute = AsyncMock(return_value={"success": True})
        node.step_loop._settle_after_action = AsyncMock()
        first = DeviceObservation(id="initial", index=0, screen_size={"width": 1000, "height": 2000},
                                  screenshot={"filename": "initial.jpg"})
        node.step_loop.observation_store.observe = AsyncMock(side_effect=[first, RuntimeError("capture unavailable")])
        state = await node({"case_spec": example_case().model_dump(mode="json")})
        self.assertEqual(state["run"]["status"], "failed")
        operation = state["trajectory"]["operations"][0]
        self.assertEqual(operation["execution"]["status"], "succeeded")
        self.assertIsNone(operation["observation_transition"]["after_observation_id"])
        self.assertIn("capture unavailable", operation["observation_error"])

    async def test_unknown_result_stops_before_repeating(self):
        node = CaseStepRunnerNode(action_client=object(), llm=FakeLLM())
        node.step_loop.executor.execute = AsyncMock(return_value={"success": False, "execution_status": "unknown"})
        node.step_loop._settle_after_action = AsyncMock()
        async def observe(*, index):
            return DeviceObservation(id=str(index), index=index, screen_size={"width": 1000, "height": 2000},
                                     screenshot={"filename": f"{index}.jpg"})
        node.step_loop.observation_store.observe = observe
        state = await node({"case_spec": example_case().model_dump(mode="json")})
        self.assertEqual(node.step_loop.executor.execute.await_count, 1)
        self.assertEqual(state["step_results"][0]["status"], "blocked")

    async def test_single_pass_checkpoints_and_repeat_generation(self):
        llm = FakeLLM()
        node = CaseStepRunnerNode(action_client=object(), llm=llm, config=AgentConfig())
        node.step_loop.executor.execute = AsyncMock(return_value={"success": True})
        node.step_loop._settle_after_action = AsyncMock()

        async def observe(*, index):
            return DeviceObservation(id=f"obs_{index:04d}", index=index,
                screen_size={"width": 1000, "height": 2000}, screenshot={"filename": f"{index}.jpg"})

        node.step_loop.observation_store.observe = observe
        case = example_case()
        state = await node({"case_spec": case.model_dump(mode="json")})
        self.assertEqual(state["run"]["status"], "done")
        self.assertEqual(node.step_loop.executor.execute.await_count, 2)
        checkpoints = state["step_results"][0]["checkpoints"]
        self.assertEqual(checkpoints[0]["observation_id"], "obs_0001")
        self.assertEqual(checkpoints[1]["observation_id"], "obs_0002")
        for request in llm.requests:
            serialized = str(request)
            self.assertNotIn("UNSEEN_EXPECTATION", serialized)
            self.assertNotIn("repeat", serialized)
        evidence = Evidence(case, ExplorationResult.model_validate({"trajectory": state["trajectory"], "step_results": state["step_results"]}))
        plan = ScriptPlan(actions=[{"operation_id": op.id, "description": op.intent.reason} for op in evidence.operations.values()])
        targets = {"op_0000": TargetResolution(description="search", status="coordinate", point=(0.15, 0.15))}
        targets.update({f"verify:{v.id}": TargetResolution(description=v.goal, status="unresolved") for v in case.verifications})
        ir = build_script_ir(evidence, plan, targets).model_dump(mode="json")
        self.assertEqual(ir["steps"][0]["times"], 7)
        self.assertEqual([n["type"] for n in ir["steps"][0]["body"]], ["action", "verify", "action"])
        self.assertEqual(ir["steps"][1]["verification_id"], "v2")

    def test_confirmation_keeps_internal_verification_position(self):
        text = render_case(example_case())
        self.assertLess(text.index("UNSEEN_EXPECTATION"), text.index("操作：return"))


if __name__ == "__main__":
    unittest.main()
