"""Execution-method requirements, independent of prompts and transport."""
from dataclasses import dataclass

from atestservice.contracts.execution import execution_succeeded
from atestservice.contracts.instructions import REQUIRED_ACTION_TYPES


@dataclass(frozen=True)
class MethodRequirement:
    action: str
    tool: str
    meaning: str


METHOD_REQUIREMENTS = {
    "app_launch": MethodRequirement(REQUIRED_ACTION_TYPES["app_launch"], "StartApp", "启动或重新进入指定应用"),
    "app_stop": MethodRequirement(REQUIRED_ACTION_TYPES["app_stop"], "StopApp", "停止当前应用"),
    "system_home": MethodRequirement(REQUIRED_ACTION_TYPES["system_home"], "Home", "返回系统桌面"),
    "multitask": MethodRequirement(REQUIRED_ACTION_TYPES["multitask"], "OpenMultitask", "打开系统多任务界面"),
}
EXPLICIT_ONLY_ACTIONS = {"home": "system_home", "stop_app": "app_stop"}


def render_method_rules():
    """Expose the same method requirements that the executor checks."""
    return "\n".join(
        f"- kind={kind}（{rule.meaning}）：必须使用 {rule.tool}，不能以桌面图标点击或模拟手势替代。"
        for kind, rule in METHOD_REQUIREMENTS.items()
    )


def validate_completion(instruction, operations):
    rule = METHOD_REQUIREMENTS.get(instruction.get("kind", "ui"))
    required = rule.action if rule else None
    if required and not any(
        op["semantic_ref"].get("instruction_id") == instruction["id"]
        and op["action"]["type"] == required and execution_succeeded(op["execution"])
        for op in operations
    ):
        raise ValueError(f"当前指令尚未成功执行规定方法 {required}，不能报告完成。")


def validate_action(instruction, action):
    explicit_kind = EXPLICIT_ONLY_ACTIONS.get(action.action)
    if explicit_kind and instruction.get("kind", "ui") != explicit_kind:
        raise ValueError(f"当前操作未明确要求 {METHOD_REQUIREMENTS[explicit_kind].tool}，不能用于自动恢复或代替应用内导航。")
    rule = METHOD_REQUIREMENTS.get(instruction.get("kind", "ui"))
    required = rule.action if rule else None
    if required and action.action != required:
        raise ValueError(f"当前操作必须使用 {required}，不能以其他动作替代。")


def validate_action_transition(current_instruction, next_instruction, action, operations):
    """Validate both sides of a proposed transition before the caller changes state."""
    if next_instruction is None:
        raise ValueError(
            "当前已是最后一条指令，没有下一条可执行。不要将动作后的预期当作完成；"
            "仍需操作时将complete_current_instruction设为false，观察操作结果后用CompleteStep结束。"
        )
    validate_completion(current_instruction, operations)
    validate_action(next_instruction, action)
