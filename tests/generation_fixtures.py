"""Recorded evidence fixtures: no model, network or device required."""
import base64
from atestservice.contracts.case import CaseSpec
from atestservice.contracts.exploration import ExplorationResult
from atestservice.script_generation.evidence import Evidence


def element(text="搜索", **kwargs):
    return {"text": text, "bounds": [90, 90, 210, 210], **kwargs}


def evidence(pages=("home", "result"), *, elements=None, actions=None, goal="打开搜索", repeat=1, verifications=None):
    case = CaseSpec(case_name="example", steps=[{"id": "s1", "goal": goal, "repeat": repeat,
                    "instructions": [{"id": "i1", "text": goal}]}], verifications=verifications or [])
    observations = [{"id": f"o{i}", "index": i, "package": "example.app", "activity": "MainActivity",
                     "screen_size": {"width": 1000, "height": 1000},
                     "screenshot": {"filename": f"o{i}.jpg", "base64": base64.b64encode(page.encode()).decode()},
                     "elements": elements if elements is not None else [element()]}
                    for i, page in enumerate(pages)]
    operations = []
    for i in range(len(pages) - 1):
        action = actions[i] if actions else {"type": "click", "args": {"bounds": [100, 100, 200, 200]}}
        operations.append({"id": f"op{i}", "index": i, "semantic_ref": {"step_id": "s1", "instruction_id": "i1"},
                           "observation_transition": {"before_observation_id": f"o{i}", "after_observation_id": f"o{i+1}"},
                           "intent": {"tool_name": "Click", "reason": f"目的与现场 {i}"}, "action": action,
                           "execution": {"status": "succeeded"}})
    exploration = ExplorationResult(trajectory={"observations": observations, "operations": operations},
        step_results=[{"step_id": "s1", "status": "completed", "summary": "操作完成，未执行业务断言",
                       "checkpoints": [{"verification_id": v["id"], "observation_id": f"o{len(pages)-1}",
                                        "capture_status": "captured", "after_operation_id": operations[-1]["id"] if operations else None}
                                       for v in (verifications or [])]}])
    return Evidence(case, exploration)


def all_actions(e):
    return [{"operation_id": op.id, "description": op.intent.reason} for op in e.operations.values()]
