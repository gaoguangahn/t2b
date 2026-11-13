"""从标准观察快照组织目标筛选证据；附加信息不写回原始轨迹。"""
from collections import Counter, defaultdict

from atestservice.ui.spatial import spatial_relation


def related_operations(evidence, request):
    if request.usage != "verification":
        operation = evidence.operations.get(request.id)
        return [operation] if operation else []
    checkpoint = evidence.checkpoints.get(request.id.removeprefix("verify:"))
    if not checkpoint or not checkpoint.after_operation_id:
        return []
    boundary = evidence.operations.get(checkpoint.after_operation_id)
    if boundary is None:
        return []
    verification = next(item for item in evidence.case.verifications if f"verify:{item.id}" == request.id)
    operations = [item for item in evidence.operations.values()
                  if item.index <= boundary.index and item.semantic_ref.step_id == verification.anchor.step_id
                  and (verification.anchor.instruction_id is None or
                       item.semantic_ref.instruction_id == verification.anchor.instruction_id)]
    return operations[-2:]


def _correspondences(before, after):
    """Equality-based links are references, not proof that the operation succeeded."""
    links = []
    indexes = []
    for keys in (("resource_id",), ("description", "class_name"), ("text", "class_name")):
        left, right = defaultdict(list), defaultdict(list)
        for collection, index in ((before, left), (after, right)):
            for item in collection:
                if all(item.get(key) for key in keys):
                    index[tuple(item[key] for key in keys)].append(item)
        indexes.append((keys, left, right))
    for element in before:
        for keys, left, right in indexes:
            key_value = tuple(element.get(key) for key in keys)
            previous, current = left.get(key_value, []), right.get(key_value, [])
            if len(previous) == len(current) == 1:
                changed = {key: {"before": element.get(key), "after": current[0].get(key)}
                           for key in ("checked", "selected", "enabled", "text", "description")
                           if element.get(key) is not None and current[0].get(key) is not None
                           and element[key] != current[0][key]}
                links.append({"before_candidate_id": element["id"], "after_candidate_id": current[0]["id"],
                              "matched_by": list(keys), "changes": changed})
                break
        if len(links) >= 30:
            break
    return links


def build_target_context(evidence, request, *, retained_operation_ids=None):
    anchor = evidence.observations[request.observation_id]
    operations = related_operations(evidence, request)
    identifiers = [anchor.id]
    for operation in reversed(operations):
        transition = operation.observation_transition
        for identifier in (transition.before_observation_id, transition.after_observation_id):
            if identifier in evidence.observations and identifier not in identifiers:
                if request.usage == "verification" and evidence.observations[identifier].index > anchor.index:
                    continue
                identifiers.append(identifier)
    # At most anchor + two operation pairs. No full-run history or final-page substitution.
    frames = {identifier: evidence.observations[identifier].elements for identifier in identifiers[:5]}
    target = list(request.bounds.root) if request.bounds else None
    elements = [dict(element) for element in frames[anchor.id]]
    counts = {key: Counter(item.get(key) for item in elements if item.get(key))
              for key in ("resource_id", "text", "description", "class_name")}
    for element in elements:
        element["attribute_match_counts"] = {key: count[element[key]] for key, count in counts.items() if element.get(key)}
        if target:
            element["spatial"] = spatial_relation(target, element["bounds"], anchor.screen_size)
    summaries = []
    for operation in operations:
        transition = operation.observation_transition
        before, after = transition.before_observation_id, transition.after_observation_id
        summaries.append({"operation_id": operation.id, "instruction_id": operation.semantic_ref.instruction_id,
                          "action_type": operation.action.type, "reason": operation.intent.reason,
                          "parameters": operation.action.args.model_dump(mode="json", exclude_none=True),
                          "execution_status": operation.execution.status,
                          "before_observation_id": before, "after_observation_id": after,
                          "control_correspondences": _correspondences(frames.get(before, []), frames.get(after, []))})
    payload = {"request_id": request.id, "usage": request.usage, "user_goal": request.goal,
               "action_description": request.description, "observation_id": anchor.id,
               "screen_size": anchor.screen_size.model_dump(),
               "coordinate_space": "normalized_1000", "target_bounds": target, "elements": elements,
               "spatial_candidate_ids": [item["id"] for item in sorted(elements, key=lambda item: item.get("spatial", {}).get("score", 0), reverse=True)[:12]] if target else [],
               "related_operations": summaries,
               "runtime_baseline_operation_ids": [item.id for item in operations if item.id in (retained_operation_ids or set())],
               "supporting_observations": [{"observation_id": identifier,
                                            "screen_size": evidence.observations[identifier].screen_size.model_dump(), "elements": entries}
                                          for identifier, entries in frames.items() if identifier != anchor.id]}
    return payload, frames
