"""Validate references and conservative deletion boundaries; UI equality is not business equivalence."""
from atestservice.contracts.script import GenerationIssue, ScriptPlan
from atestservice.contracts.instructions import REQUIRED_ACTION_TYPES
from atestservice.script_generation.evidence import Evidence


def same_ui(a, b):
    if a is None or b is None:
        return False
    if a.id == b.id:
        return True
    if a.screenshot.base64 and a.screenshot.base64 == b.screenshot.base64:
        return True
    return bool(a.elements and a.package and a.activity and
                (a.package, a.activity, a.elements) == (b.package, b.activity, b.elements))


def validate_plan(plan: ScriptPlan, evidence: Evidence) -> ScriptPlan:
    plan = plan.model_copy(deep=True)
    ops = evidence.operations
    order = {identifier: n for n, identifier in enumerate(ops)}
    kept = [a.operation_id for a in plan.actions]
    dropped = [identifier for segment in plan.omitted_segments for identifier in segment.operation_ids]
    if len(kept + dropped) != len(set(kept + dropped)) or set(kept + dropped) != set(ops):
        raise ValueError("Plan must account for every operation exactly once")
    if kept != sorted(kept, key=order.__getitem__):
        raise ValueError("Plan must preserve source operation order")
    conditions = {c.id: c for c in plan.conditions}
    if len(conditions) != len(plan.conditions):
        raise ValueError("Duplicate execution condition")
    used = {}
    for position, action in enumerate(plan.actions):
        op = ops[action.operation_id]
        if op.execution.status != "succeeded":
            plan.issues.append(GenerationIssue(code="uncertain_execution", message="保留操作的执行结果未确认成功。", blocking=True, source_ids=[op.id]))
        if action.condition_id:
            if action.condition_id not in conditions:
                raise ValueError("Unknown execution condition")
            used.setdefault(action.condition_id, []).append((position, op))
    if set(used) != set(conditions):
        raise ValueError("Unused execution condition")
    for items in used.values():
        positions = [p for p, _ in items]
        refs = {(op.semantic_ref.step_id, op.semantic_ref.instruction_id) for _, op in items}
        if positions != list(range(positions[0], positions[-1] + 1)) or len(refs) != 1:
            raise ValueError("Condition group must be contiguous within one instruction")
    for segment in plan.omitted_segments:
        positions = [order[i] for i in segment.operation_ids]
        if positions != list(range(positions[0], positions[-1] + 1)):
            raise ValueError("Omitted segment must be contiguous and ordered")
        if any(i not in evidence.observations for i in segment.observation_ids):
            raise ValueError("Omitted segment cites unknown observation")
        first, last = ops[segment.operation_ids[0]], ops[segment.operation_ids[-1]]
        before_id = first.observation_transition.before_observation_id
        after_id = last.observation_transition.after_observation_id
        if before_id not in segment.observation_ids or (after_id is not None and after_id not in segment.observation_ids):
            raise ValueError("Omitted segment must cite its boundary observations")
        if not same_ui(evidence.observations.get(before_id), evidence.observations.get(after_id)):
            plan.issues.append(GenerationIssue(code="path_gap", message="删除片段的前后界面缺少可靠衔接证据，需要复核。", blocking=True, source_ids=segment.operation_ids))
        for checkpoint in evidence.checkpoints.values():
            if checkpoint.after_operation_id in segment.operation_ids and not same_ui(
                    evidence.observations.get(checkpoint.observation_id), evidence.observations.get(after_id)):
                plan.issues.append(GenerationIssue(code="verification_boundary", message="验证检查点位于删除片段内部，不能自动挪动。", blocking=True, source_ids=[checkpoint.verification_id]))
    # Explicit method requirements cannot silently disappear or become optional.
    for step in evidence.case.steps:
        for instruction in step.instructions:
            source_actions = [op for op in ops.values() if op.semantic_ref.instruction_id == instruction.id]
            retained = [ops[a.operation_id] for a in plan.actions if ops[a.operation_id].semantic_ref.instruction_id == instruction.id]
            if source_actions and not retained:
                plan.issues.append(GenerationIssue(code="instruction_coverage", message=f"指令的全部操作被删除，需要确认是否仍完成要求：{instruction.text}", blocking=True, source_ids=[instruction.id]))
            action_type = REQUIRED_ACTION_TYPES.get(instruction.kind)
            if action_type and not any(ops[a.operation_id].semantic_ref.instruction_id == instruction.id
                                       and ops[a.operation_id].action.type == action_type and not a.condition_id
                                       for a in plan.actions):
                plan.issues.append(GenerationIssue(code="missing_required_action", message=f"必要操作缺失或被改为可选：{instruction.text}", blocking=True, source_ids=[instruction.id]))
    return plan
