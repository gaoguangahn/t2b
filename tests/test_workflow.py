import unittest
import json
from unittest.mock import patch, AsyncMock

from test_exploration_flow import FakeLLM, example_case
from atestservice.contracts.observation import DeviceObservation
from atestservice.workflow.graph import build_explore_graph
from atestservice.exploration.observations.store import ObservationStore
from atestservice.exploration.loop_node import ExploreAgentLoopNode
from atestservice.exploration.tools.action_executor import ActionExecutor


class WorkflowLLM(FakeLLM):
    async def invoke_structured(self, prompt, schema, **kwargs):
        if schema.__name__ == "PlanningResponse":
            return schema(plan={"actions": [{"operation_id": f"op_{i:04d}", "description": "original action"} for i in range(2)]})
        if schema.__name__ == "TargetResponse":
            request = json.loads(prompt[1]["content"])
            return schema(targets=[{"request_id": request["request_id"], "kind": "unresolved", "target_description": request["user_goal"], "reason": "no UI evidence"}])
        if schema.__name__ == "CodegenResult":
            return schema(language="python", framework="dynamic_framework", filename="test_generated.py",
                          content="def test_generated():\n    pass\n", notes=["fake model output"])
        raise AssertionError(schema.__name__)


class Publisher:
    def __init__(self): self.events = []
    async def node_started(self, **event): self.events.append(event)
    async def node_finished(self, **event): self.events.append(event)
    async def node_failed(self, **event): self.events.append(event)


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_preserves_boundaries_and_detailed_events(self):
        async def observe(self, *, index):
            return DeviceObservation(id=f"obs_{index:04d}", index=index,
                screen_size={"width": 1000, "height": 2000}, screenshot={"filename": f"{index}.jpg"})
        publisher = Publisher()
        with patch.object(ObservationStore, "observe", observe), \
             patch.object(ExploreAgentLoopNode, "_settle_after_action", AsyncMock()), \
             patch.object(ActionExecutor, "execute", AsyncMock(return_value={"success": True})):
            graph = build_explore_graph(action_client=object(), event_publisher=publisher, llm=WorkflowLLM())
            result = await graph.ainvoke({"case_spec": example_case().model_dump(mode="json"), "framework": "dynamic_framework"})
        self.assertNotIn("event_publisher", result)
        self.assertNotIn("current_step", result)
        self.assertEqual(result["result"]["ir"]["steps"][0]["times"], 7)
        self.assertEqual(result["result"]["status"], "draft")
        nodes = {event["node"] for event in publisher.events}
        self.assertTrue({"agent_decision", "action_started", "action_executed", "instruction_completed", "plan_script", "resolve_targets", "generate_script"} <= nodes)
