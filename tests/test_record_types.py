import unittest
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError

from atestservice.contracts.case import CaseSpec
from atestservice.contracts.execution import ExecutionResult
from atestservice.contracts.exploration import OperationRecord, Trajectory
from atestservice.runs.models import RunRecord, RunStatus
from types import SimpleNamespace
from atestservice.runs.service import RunService


def operation():
    return {"id": "op0", "index": 0, "semantic_ref": {"step_id": "s1", "instruction_id": "i1"},
            "observation_transition": {"before_observation_id": "o0", "after_observation_id": None},
            "intent": {"tool_name": "Click", "reason": "visible target"},
            "action": {"type": "click", "args": {"bounds": [1, 1, 20, 20]}},
            "execution": {"status": "succeeded"}}


class RecordTypeTests(unittest.TestCase):
    def test_execution_serializes_one_status(self):
        result = ExecutionResult.model_validate({"success": False, "execution_status": "unknown", "message": "timeout"})
        self.assertEqual(result.model_dump(exclude_none=True), {"status": "unknown", "message": "timeout"})

    def test_verification_serializes_one_step_reference(self):
        case = CaseSpec(case_name="test", steps=[{"id": "s1", "goal": "open"}], verifications=[
            {"id": "v1", "step_id": "s1", "goal": "expected"}])
        data = case.model_dump()["verifications"][0]
        self.assertNotIn("step_id", data)
        self.assertEqual(data["anchor"]["step_id"], "s1")

    def test_nested_action_is_validated(self):
        data = operation()
        data["action"] = {"type": "click", "args": {}}
        with self.assertRaises(ValidationError):
            OperationRecord.model_validate(data)

    def test_reference_check_uses_well_formed_records(self):
        data = operation()
        data["observation_transition"]["before_observation_id"] = "missing"
        with self.assertRaisesRegex(ValidationError, "unknown observation"):
            Trajectory(observations=[{"id": "o0", "index": 0, "screen_size": {"width": 100, "height": 200},
                                      "screenshot": {"filename": "o0.jpg"}}], operations=[data])


class RunBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_generation_is_persisted_as_error_with_plan(self):
        repository = SimpleNamespace(update_run_status=AsyncMock(),
                                     append_event=AsyncMock(return_value=SimpleNamespace(model_dump=lambda **kwargs: {})))
        sessions = SimpleNamespace(send_event=AsyncMock())
        service = RunService(repository=repository, plugin_sessions=sessions)
        record = RunRecord(run_id="r1", user_id="u1", plugin_session_id="p1", plugin_instance_id="i1", editable_text="case")
        generated = {"status": "failed", "failureReason": "script_plan_blocked",
                     "result": {"status": "blocked", "plan": {"issues": ["missing evidence"]}}}
        service._run_agent = AsyncMock(return_value=generated)
        await service._execute_run(record)
        args = repository.update_run_status.await_args
        self.assertEqual(args.args[2], RunStatus.ERROR)
        self.assertEqual(args.kwargs["result"]["result"]["plan"], generated["result"]["plan"])
        self.assertEqual(args.kwargs["error"], "script_plan_blocked")

    async def test_run_result_has_one_exploration_source(self):
        service = RunService(repository=object(), plugin_sessions=object())
        record = RunRecord(run_id="r1", user_id="u1", plugin_session_id="p1", plugin_instance_id="i1", editable_text="case")
        state = {"run": {"status": "done"}, "exploration_result": {"trajectory": {"observations": [], "operations": []}}}
        with patch("atestservice.runs.service.MobileTestAgentRunner") as runner:
            runner.return_value.run = AsyncMock(return_value=state)
            result = await service._run_agent(record, object())
        self.assertNotIn("trajectory", result)
        self.assertNotIn("executionPlan", result)
        self.assertEqual(result["explorationResult"], state["exploration_result"])
