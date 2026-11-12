"""Workflow adapter. Runtime dependencies never enter serialized state."""
from atestservice.runtime.events import NoopAgentEventPublisher
from atestservice.runtime.event_payloads import json_event
from atestservice.script_generation.pipeline import generate_script


class ScriptGenNode:
    def __init__(self, llm=None, publisher=None):
        self.llm = llm
        self.publisher = publisher or NoopAgentEventPublisher()

    async def __call__(self, state):
        await self.publisher.node_started(stage="script_gen", node="generate_script", label="正在生成脚本")
        try:
            generated = await generate_script(state["case_spec"], state["exploration_result"], llm=self.llm,
                                              profile_name=state.get("framework"), publisher=self.publisher)
        except Exception as exc:
            await self.publisher.node_failed(stage="script_gen", node="generate_script", message=str(exc))
            raise
        result = generated.model_dump(mode="json", exclude_none=True)
        if generated.script is None:
            await self.publisher.node_finished(stage="script_gen", node="generate_script", payload=json_event(
                "脚本计划需要复核", "证据不足，已保留整理结果与问题。", "generation.json", result))
            return {"result": result, "run": {**state.get("run", {}), "status": "failed", "failure_reason": "script_plan_blocked"}}
        await self.publisher.node_finished(stage="script_gen", node="generate_script", payload=json_event(
            "脚本待完善" if generated.status == "draft" else "脚本生成完成",
            "请查看脚本、动作计划与待完善说明。", "generation.json", result))
        return {"result": result}
