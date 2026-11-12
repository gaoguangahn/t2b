"""手机自动化测试全流程的 LangGraph 构建：执行 → 脚本生成。

流程::

    initialize → build_case_spec → run_case_steps
        → (执行成功?) generate_script : failed
        → END

执行成功后由图自动路由到 generate_script，串联 IR 生成 + 代码生成；
失败走 failed 分支，不进入脚本生成。
"""

from __future__ import annotations

from atestservice.runtime.events import AgentEventPublisher
from typing import Any

from atestservice.exploration.config import AgentConfig
from atestservice.case_preparation.structure_case import StructureCaseNode
from atestservice.exploration import CaseStepRunnerNode
from atestservice.workflow.initialize import initialize_state
from atestservice.script_generation.script_gen_node import ScriptGenNode
from atestservice.workflow.state import MobileAgentState
from atestservice.device.client import DeviceClient


def build_explore_graph(*, action_client: DeviceClient, config: AgentConfig | None = None, event_publisher: AgentEventPublisher | None = None, llm=None) -> Any:
    """构建第一阶段探索工作流。"""

    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:
        raise RuntimeError("langgraph is required to build the mobile exploration graph") from exc

    config = config or AgentConfig()
    graph = StateGraph(MobileAgentState)

    parser = StructureCaseNode(llm=llm)
    explorer = CaseStepRunnerNode(action_client=action_client, config=config, llm=llm)
    generator = ScriptGenNode(llm=llm, publisher=event_publisher)

    def local(state):
        return {**state, "event_publisher": event_publisher}

    def initialize(state):
        data = initialize_state(state, agent_config=config)
        return {"request": data["request"], "run": data["run"], "result": data["result"]}

    async def parse(state):
        return await parser(local(state))

    async def explore(state):
        data = await explorer(local(state))
        exploration_result = {"trajectory": data.get("trajectory", {"observations": [], "operations": []}),
                              "step_results": data.get("step_results", [])}
        from atestservice.contracts.exploration import ExplorationResult
        checked = ExplorationResult.model_validate(exploration_result)
        output = {"exploration_result": checked.model_dump(mode="json", exclude_none=True), "run": data["run"]}
        if "result" in data:
            output["result"] = data["result"]
        run_id = state.get("request", {}).get("run_id")
        if run_id:
            import asyncio
            from atestservice.contracts.exploration import ExplorationBundle
            from atestservice.runtime.artifacts import save_exploration_bundle
            bundle = ExplorationBundle(case_spec=state["case_spec"], exploration_result=checked)
            await asyncio.to_thread(save_exploration_bundle, bundle, run_id)
        return output

    async def generate(state):
        return await generator(state)

    graph.add_node("initialize", initialize)
    graph.add_node("build_case_spec", parse)
    graph.add_node("run_case_steps", explore)
    graph.add_node("generate_script", generate)
    graph.add_node("failed", _mark_failed)

    graph.set_entry_point("initialize")
    graph.add_edge("initialize", "build_case_spec")
    graph.add_edge("build_case_spec", "run_case_steps")
    graph.add_conditional_edges(
        "run_case_steps",
        _route_after_case_steps,
        {"done": "generate_script", "failed": "failed", "skipped": END},
    )
    graph.add_edge("generate_script", END)
    graph.add_edge("failed", END)
    return graph.compile()


def _route_after_case_steps(state: MobileAgentState) -> str:
    run = state.get("run") or {}
    if run.get("status") == "failed":
        return "failed"
    if not (state.get("case_spec") or {}).get("steps"):
        return "skipped"
    return "done"


def _mark_failed(state: MobileAgentState) -> MobileAgentState:
    run = dict(state.get("run") or {})
    failure_reason = run.get("failure_reason") or "exploration failed"
    return {"run": {**run, "status": "failed", "failure_reason": failure_reason}}
