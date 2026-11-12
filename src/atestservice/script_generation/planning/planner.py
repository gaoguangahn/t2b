"""Bounded evidence-assisted planning; no phone actions or business assertions."""
import json
from pathlib import Path
from atestservice.contracts.script import GenerationIssue, ScriptPlan
from atestservice.llm.types import LLMCallOptions
from atestservice.script_generation.planning.models import PlanningResponse
from atestservice.script_generation.evidence import Evidence, evidence_message
from atestservice.script_generation.planning.validation import validate_plan

_PROMPT = Path(__file__).parents[1] / "prompts" / "plan.md"
_OPTIONS = LLMCallOptions(temperature=0.1, max_completion_tokens=8192, timeout=120)


async def plan_actions(evidence: Evidence, llm) -> ScriptPlan:
    messages = [{"role": "system", "content": _PROMPT.read_text(encoding="utf-8")},
                {"role": "user", "content": json.dumps(evidence.compact(), ensure_ascii=False)}]
    supplied = set()
    for round_index in range(3):
        response = await llm.invoke_structured(messages, PlanningResponse, options=_OPTIONS)
        requested = list(dict.fromkeys(response.observation_requests))
        if not requested:
            if response.plan is None:
                raise ValueError("Planner returned neither plan nor evidence request")
            return validate_plan(response.plan, evidence)
        if any(i not in evidence.observations for i in requested):
            raise ValueError("Planner requested an unknown observation")
        fresh = [i for i in requested if i not in supplied]
        if round_index == 2 or not fresh or len(supplied | set(fresh)) > 12:
            return ScriptPlan(issues=[GenerationIssue(code="evidence_budget", blocking=True,
                              message="路径整理仍需要更多证据，已达到本次补证预算。", source_ids=requested)])
        supplied.update(fresh)
        messages.append(evidence_message(llm, evidence, fresh))
    raise AssertionError("unreachable")
