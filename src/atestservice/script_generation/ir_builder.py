"""Deterministically assemble ordered actions, conditions, repeats and user verifications."""
from itertools import groupby
from atestservice.contracts.script import (
    ActionNode, ConditionNode, RepeatNode, ScriptActionArgs, ScriptIR, VerifyNode,
    ScriptPlan, TargetResolution,
)
from atestservice.script_generation.evidence import Evidence
from atestservice.script_generation.targeting.resolver import CLICK_TYPES


def build_script_ir(evidence: Evidence, plan: ScriptPlan, targets: dict[str, TargetResolution]) -> ScriptIR:
    if any(issue.blocking for issue in plan.issues):
        raise ValueError("Cannot build IR from a blocked plan")
    conditions = {c.id: c for c in plan.conditions}
    result = []

    def verifications(destination, step_id, instruction_id, position, scope):
        for verification in evidence.case.verifications:
            anchor = verification.anchor
            if (anchor.step_id, anchor.instruction_id, anchor.position, verification.scope) == (step_id, instruction_id, position, scope):
                destination.append(VerifyNode(verification_id=verification.id, expectation=verification.goal,
                                              anchor=anchor, target=targets[f"verify:{verification.id}"]))

    def action_node(action):
        op = evidence.operations[action.operation_id]
        args = op.action.args.model_dump(mode="json", exclude_none=True, exclude={"bounds"})
        for name in ("start", "end"):
            if name in args:
                args[name] = [round(args[name][k] / 1000, 4) for k in ("x", "y")]
        before = evidence.observations[op.observation_transition.before_observation_id]
        after = evidence.observations.get(op.observation_transition.after_observation_id)
        return ActionNode(source_operation_id=op.id, description=action.description, action_type=op.action.type,
                          parameters=ScriptActionArgs(**args), target=targets[op.id] if op.action.type in CLICK_TYPES else None,
                          activity=after.activity if after else None,
                          activity_changed=bool(before.activity and after and after.activity and before.activity != after.activity))

    for step in evidence.case.steps:
        verifications(result, step.id, None, "before", "outside_repeat")
        body = []
        verifications(body, step.id, None, "before", "each_iteration")
        for instruction in step.instructions:
            verifications(body, step.id, instruction.id, "before", "each_iteration")
            actions = [a for a in plan.actions if evidence.operations[a.operation_id].semantic_ref.instruction_id == instruction.id]
            for condition_id, group in groupby(actions, key=lambda a: a.condition_id):
                nodes = [action_node(a) for a in group]
                if condition_id:
                    body.append(ConditionNode(description=conditions[condition_id].description,
                                              target=targets[f"condition:{condition_id}"], body=nodes))
                else:
                    body.extend(nodes)
            verifications(body, step.id, instruction.id, "after", "each_iteration")
        verifications(body, step.id, None, "after", "each_iteration")
        if step.repeat > 1 and body:
            result.append(RepeatNode(times=step.repeat, description=step.goal, body=body))
        else:
            result.extend(body)
        verifications(result, step.id, None, "after", "outside_repeat")
    if not result:
        raise ValueError("No script steps: neither actions nor verifications")
    return ScriptIR(case_name=evidence.case.case_name, steps=result)
