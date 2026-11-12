"""Model-facing extraction protocol, converted once into the shared CaseSpec."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from atestservice.contracts.case import CaseSpec
from atestservice.contracts.instructions import InstructionKind, VerificationAnchor


class _ExtractionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedInstruction(_ExtractionModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    kind: InstructionKind


class ExtractedStep(_ExtractionModel):
    id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    repeat: int = Field(ge=1)
    instructions: list[ExtractedInstruction] = Field(min_length=1)


class ExtractedVerification(_ExtractionModel):
    id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    anchor: VerificationAnchor
    scope: Literal["each_iteration", "outside_repeat"]


class CaseExtraction(_ExtractionModel):
    case_name: str
    case_goal: str
    steps: list[ExtractedStep]
    verifications: list[ExtractedVerification]

    def to_case_spec(self) -> CaseSpec:
        return CaseSpec.model_validate(self.model_dump(mode="json"))
