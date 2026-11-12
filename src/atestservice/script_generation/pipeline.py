"""Production and offline generation use the same typed stage boundary and pipeline."""
from atestservice.contracts.case import CaseSpec
from atestservice.contracts.exploration import ExplorationResult
from atestservice.contracts.script import GenerationIssue, GenerationPreparation, GenerationResult
from atestservice.llm import create_llm
from atestservice.llm.types import StructuredLLM
from atestservice.runtime.events import AgentEventPublisher, NoopAgentEventPublisher
from atestservice.runtime.event_payloads import json_event, python_event
from atestservice.script_generation.evidence import Evidence
from atestservice.script_generation.planning.planner import plan_actions
from atestservice.script_generation.targeting.resolver import resolve_targets
from atestservice.script_generation.ir_builder import build_script_ir
from atestservice.script_generation.codegen import generate_code


async def prepare_script(case_spec: CaseSpec | dict, exploration_result: ExplorationResult | dict, *,
                         llm: StructuredLLM, publisher: AgentEventPublisher | None = None) -> GenerationPreparation:
    publisher = publisher or NoopAgentEventPublisher()
    evidence = Evidence(CaseSpec.model_validate(case_spec), ExplorationResult.model_validate(exploration_result))
    await publisher.node_started(stage="script_gen", node="plan_script", label="正在整理可回放动作")
    plan = await plan_actions(evidence, llm)
    completed = {s.step_id for s in evidence.exploration.step_results if s.status == "completed"}
    missing = [s.id for s in evidence.case.steps if s.id not in completed]
    if missing:
        plan.issues.append(GenerationIssue(code="incomplete_exploration", message="存在未完成或缺少结果的目标块，不能生成完整脚本。", blocking=True, source_ids=missing))
    await publisher.node_finished(stage="script_gen", node="plan_script", payload=json_event(
        "动作计划已整理", f"保留 {len(plan.actions)} 个操作，删除 {len(plan.omitted_segments)} 个片段，条件组 {len(plan.conditions)} 个。",
        "script_plan.json", plan.model_dump(mode="json")))
    if any(i.blocking for i in plan.issues):
        return GenerationPreparation(plan=plan)
    await publisher.node_started(stage="script_gen", node="resolve_targets", label="正在解析操作、验证和条件目标")
    targets = await resolve_targets(evidence, plan, llm)
    await publisher.node_finished(stage="script_gen", node="resolve_targets", payload=json_event(
        "目标解析完成", "已保留定位结果、验证预期和无法确认的限制。", "targets.json",
        {key: target.model_dump(mode="json", exclude_none=True) for key, target in targets.items()}))
    ir = build_script_ir(evidence, plan, targets)
    return GenerationPreparation(plan=plan, ir=ir)


def target_notes(nodes):
    notes = []
    for node in nodes:
        target = getattr(node, "target", None)
        if target:
            notes.extend(target.notes)
        if hasattr(node, "body"):
            notes.extend(target_notes(node.body))
    return notes


async def generate_script(case_spec: CaseSpec | dict, exploration_result: ExplorationResult | dict, *,
                          llm: StructuredLLM | None = None, profile_name: str | None = None,
                          publisher: AgentEventPublisher | None = None) -> GenerationResult:
    llm = llm or create_llm()
    preparation = await prepare_script(case_spec, exploration_result, llm=llm, publisher=publisher)
    if preparation.ir is None:
        return GenerationResult(status="blocked", plan=preparation.plan)
    publisher = publisher or NoopAgentEventPublisher()
    await publisher.node_started(stage="script_gen", node="encode_script", label="正在按框架规范生成脚本")
    script = await generate_code(preparation.ir, llm=llm, profile_name=profile_name)
    script.notes = list(dict.fromkeys(script.notes + target_notes(preparation.ir.steps) +
                                     [i.message for i in preparation.plan.issues]))
    await publisher.node_finished(stage="script_gen", node="encode_script", payload=python_event(
        "脚本编码完成", "已按框架规范输出代码。", script.filename, script.content))
    return GenerationResult(status="draft" if script.notes else "ready", plan=preparation.plan, ir=preparation.ir, script=script)
