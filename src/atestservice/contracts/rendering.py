"""Ordered confirmation view, derived from the case contract."""
from atestservice.contracts.case import CaseSpec


def render_case(case: CaseSpec) -> str:
    lines = ["【用例名称】", case.case_name, "", "【流程】"]

    def verifies(step_id, instruction_id, position, scope):
        for item in case.verifications:
            a = item.anchor
            if (a.step_id, a.instruction_id, a.position, item.scope) == (step_id, instruction_id, position, scope):
                label = "循环外验证" if scope == "outside_repeat" else "每轮验证"
                lines.append(f"  {label}：{item.goal}")

    for index, step in enumerate(case.steps, 1):
        verifies(step.id, None, "before", "outside_repeat")
        lines.append(f"{index}. {step.goal}" + (f"（以下整轮执行 {step.repeat} 次）" if step.repeat > 1 else ""))
        verifies(step.id, None, "before", "each_iteration")
        for instruction in step.instructions:
            verifies(step.id, instruction.id, "before", "each_iteration")
            lines.append(f"  操作：{instruction.text}")
            verifies(step.id, instruction.id, "after", "each_iteration")
        verifies(step.id, None, "after", "each_iteration")
        if step.repeat > 1:
            lines.append("  以上整组重复流程结束。")
        verifies(step.id, None, "after", "outside_repeat")
    return "\n".join(lines)
