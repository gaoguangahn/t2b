"""Serializable exploration results; checkpoints are evidence, never assertions."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from atestservice.contracts.case import CaseSpec
from atestservice.contracts.observation import DeviceObservation
from atestservice.contracts.action import ResolvedAction, ActionType, ActionArgs
from atestservice.contracts.execution import ExecutionResult


class VerificationCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verification_id: str
    observation_id: str | None = None
    capture_status: Literal["captured", "unavailable"]
    after_operation_id: str | None = None

    @model_validator(mode="after")
    def validate_capture(self):
        if self.capture_status == "captured" and self.observation_id is None:
            raise ValueError("captured checkpoint requires an observation")
        return self


class InstructionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction_id: str
    status: Literal["completed", "in_progress", "pending", "blocked", "error"]


class SemanticReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    instruction_id: str | None = None


class ObservationTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before_observation_id: str
    after_observation_id: str | None = None


class ActionIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str
    reason: str


class RecordedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: ActionType
    args: ActionArgs

    @model_validator(mode="after")
    def validate_action(self):
        ResolvedAction(action=self.type, args=self.args)
        return self


class StepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    status: Literal["completed", "blocked", "error"]
    summary: str
    checkpoints: list[VerificationCheckpoint] = Field(default_factory=list)
    instruction_results: list[InstructionResult] = Field(default_factory=list)


class OperationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    index: int
    semantic_ref: SemanticReference
    observation_transition: ObservationTransition
    intent: ActionIntent
    action: RecordedAction
    execution: ExecutionResult
    debug: dict[str, Any] = Field(default_factory=dict)
    observation_error: str | None = None


class Trajectory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observations: list[DeviceObservation] = Field(default_factory=list)
    operations: list[OperationRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self):
        observation_ids = [o.id for o in self.observations]
        operation_ids = [o.id for o in self.operations]
        if len(set(observation_ids)) != len(observation_ids) or len(set(operation_ids)) != len(operation_ids):
            raise ValueError("duplicate trajectory identifier")
        positions = {identifier: index for index, identifier in enumerate(observation_ids)}
        for operation in self.operations:
            transition = operation.observation_transition
            before = transition.before_observation_id
            after = transition.after_observation_id
            if before not in positions or (after is not None and after not in positions):
                raise ValueError("operation references an unknown observation")
            if after is not None and positions[before] > positions[after]:
                raise ValueError("operation observation order is invalid")
        return self


class ExplorationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trajectory: Trajectory
    step_results: list[StepResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_checkpoints(self):
        observations = {o.id for o in self.trajectory.observations}
        operations = {o.id for o in self.trajectory.operations}
        ids = [r.step_id for r in self.step_results]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate step result")
        for result in self.step_results:
            for checkpoint in result.checkpoints:
                if checkpoint.observation_id is not None and checkpoint.observation_id not in observations:
                    raise ValueError("checkpoint references an unknown observation")
                if checkpoint.after_operation_id is not None and checkpoint.after_operation_id not in operations:
                    raise ValueError("checkpoint references an unknown operation")
        return self


class ExplorationBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2.0"] = "2.0"
    case_spec: CaseSpec
    exploration_result: ExplorationResult
