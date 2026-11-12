"""Derive non-truncated parameter facts without inventing device outcomes."""
import json

from atestservice.contracts.execution import ExecutionResult


def parameter_action_ledger(trajectory: dict, step_id: str) -> list[dict]:
    """Group counted actions by instruction, requested parameters and outcome.

    requested_total is the total requested by commands with the given status,
    never a substitute for device-reported completion counts.
    """
    groups = {}
    for operation in trajectory.get("operations", []):
        reference = operation.get("semantic_ref", {})
        action = operation.get("action", {})
        action_type = action.get("type")
        if reference.get("step_id") != step_id or action_type not in {"swipe", "wait"}:
            continue
        args = action.get("args", {})
        outcome = ExecutionResult.model_validate(operation["execution"])
        key = (reference.get("instruction_id"), action_type,
               json.dumps(args, ensure_ascii=False, sort_keys=True), outcome.status)
        if key not in groups:
            groups[key] = {
                "instruction_id": reference.get("instruction_id"),
                "action_type": action_type,
                "requested_args": dict(args),
                "execution_status": outcome.status,
                "command_count": 0,
                "requested_total": 0,
                "unit": "swipes" if action_type == "swipe" else "seconds",
                "device_reported_commands": 0,
                "device_reported_count": None,
            }
        group = groups[key]
        group["command_count"] += 1
        group["requested_total"] += (args.get("times") or 1) if action_type == "swipe" else args["duration"]
        if outcome.completed_count is not None:
            group["device_reported_commands"] += 1
            group["device_reported_count"] = (group["device_reported_count"] or 0) + outcome.completed_count
    return list(groups.values())
