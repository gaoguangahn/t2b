"""Shared read-only evidence and bounded multimodal context for generation."""
import json
from atestservice.contracts.case import CaseSpec
from atestservice.contracts.exploration import ExplorationResult


class Evidence:
    def __init__(self, case: CaseSpec, exploration: ExplorationResult):
        self.case = case
        self.exploration = exploration
        self.operations = {o.id: o for o in exploration.trajectory.operations}
        self.observations = {o.id: o for o in exploration.trajectory.observations}
        self.checkpoints = {}
        steps = {s.id: s for s in case.steps}
        instruction_order = {i.id: n for n, i in enumerate(i for s in case.steps for i in s.instructions)}
        previous = -1
        for op in exploration.trajectory.operations:
            ref = op.semantic_ref
            if ref.step_id not in steps or ref.instruction_id not in {i.id for i in steps[ref.step_id].instructions}:
                raise ValueError(f"Invalid operation semantic reference: {op.id}")
            current = instruction_order[ref.instruction_id]
            if current < previous:
                raise ValueError("Operation instruction order contradicts CaseSpec")
            previous = current
        verifications = {v.id: v for v in case.verifications}
        for result in exploration.step_results:
            if result.step_id not in steps:
                raise ValueError(f"Unknown step result: {result.step_id}")
            for checkpoint in result.checkpoints:
                verification = verifications.get(checkpoint.verification_id)
                if verification is None or verification.anchor.step_id != result.step_id:
                    raise ValueError("Checkpoint does not match its case verification")
                if checkpoint.verification_id in self.checkpoints:
                    raise ValueError("Duplicate verification checkpoint")
                self.checkpoints[checkpoint.verification_id] = checkpoint

    def compact(self):
        return {
            "case_spec": self.case.model_dump(mode="json"),
            "operations": [o.model_dump(mode="json", exclude={"debug"}, exclude_none=True)
                           for o in self.operations.values()],
            "observations": [{"id": o.id, "package": o.package, "activity": o.activity,
                              "labels": [{"text": e.get("text"), "description": e.get("desc", e.get("description"))}
                                         for e in o.elements if e.get("text") or e.get("desc") or e.get("description")][:40],
                              "limitations": o.limitations} for o in self.observations.values()],
            "step_results": [s.model_dump(mode="json") for s in self.exploration.step_results],
        }

    def full_observation(self, identifier):
        return self.observations[identifier].model_dump(mode="json", exclude={"screenshot"})


def evidence_message(llm, evidence, identifiers):
    content = [{"type": "text", "text": json.dumps([evidence.full_observation(i) for i in identifiers], ensure_ascii=False)}]
    capabilities = getattr(getattr(llm, "config", None), "capabilities", None)
    if capabilities and capabilities.supports_vision:
        for identifier in identifiers:
            shot = evidence.observations[identifier].screenshot
            if shot.base64:
                content.extend([{"type": "text", "text": f"observation_id={identifier}"},
                                {"type": "image_url", "image_url": {"url": f"data:{shot.mime_type};base64,{shot.base64}"}}])
    return {"role": "user", "content": content}
