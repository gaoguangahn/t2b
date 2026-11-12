"""Check predicate provenance and capability without evaluating user assertions."""
from atestservice.contracts.script import VerificationPlan


def validate_verification(pick, element, source_id, frames, operation_ids):
    plan = pick.verification
    if plan is None:
        # Older/injected pickers can still provide a locator; codegen uses the original goal.
        return None
    plan.validate_method()
    if plan.method == "unresolved":
        raise ValueError(plan.basis)
    if any(identifier not in frames for identifier in plan.evidence_observation_ids):
        raise ValueError("验证依据引用了未提供或不属于当前位置的观察。")
    if plan.method != "unresolved" and not plan.evidence_observation_ids:
        raise ValueError("验证方式缺少实际证据来源。")
    if plan.method == "attribute" and type(element.get(plan.attribute)) is not bool:
        raise ValueError("所选控件证据未提供可读取的状态属性，需选择有依据的其他UI验证方式。")
    if plan.method in {"text", "number"} and element.get("text") is None:
        raise ValueError("所选控件没有文本读取证据，不能假定其可读取文本或数字。")
    if source_id not in plan.evidence_observation_ids and plan.method != "unresolved":
        raise ValueError("验证依据未包含所选控件的来源帧。")
    if plan.baseline_operation_id is not None and plan.baseline_operation_id not in operation_ids:
        raise ValueError("运行时基准引用了未提供或未保留的操作。")
    # Never compare the observed value to expected_value here. A false expectation
    # still needs to be emitted as a failing assertion in the generated script.
    return VerificationPlan.model_validate(plan.model_dump(mode="json"))
