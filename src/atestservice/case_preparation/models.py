"""Model-facing extraction protocol, converted once into the shared CaseSpec."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, model_validator

from atestservice.contracts.case import CaseSpec
from atestservice.contracts.instructions import InstructionKind, VerificationAnchor


class _ExtractionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParameterEntry(_ExtractionModel):
    name: str = Field(min_length=1, description="参数名，例如 app_name、text、times、duration、direction、interval。")
    value: StrictStr | StrictInt | StrictFloat = Field(description="用户原值，不改变文本字符，不把数字转成字符串。")


class ExtractedInstruction(_ExtractionModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    kind: InstructionKind
    parameters: list[ParameterEntry] = Field(description="参数条目列表；没有参数时填 []。")

    @model_validator(mode="after")
    def unique_parameters(self):
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("duplicate instruction parameter name")
        return self


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
        data = self.model_dump(mode="json")
        for step in data["steps"]:
            for instruction in step["instructions"]:
                instruction["parameters"] = {entry["name"]: entry["value"] for entry in instruction["parameters"]}
        return CaseSpec.model_validate(data)
