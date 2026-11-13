"""Authoritative in-memory cursor; presentation progress is derived."""
from dataclasses import dataclass


@dataclass
class InstructionProgress:
    instructions: list[dict]
    index: int = 0

    @property
    def active(self):
        return self.instructions[self.index] if self.index < len(self.instructions) else None

    def complete(self):
        if self.active is None:
            raise ValueError("No active instruction")
        self.index += 1

    def validate_advance(self):
        if self.index + 1 >= len(self.instructions):
            raise ValueError(
                "当前已是最后一条指令，没有下一条可执行。不要将动作后的预期当作完成；"
                "仍需操作时将complete_current_instruction设为false，观察操作结果后用CompleteStep结束。"
            )

    def snapshot(self):
        return [{"instruction_id": item["id"], "status": "completed" if index < self.index else
                 "in_progress" if index == self.index else "pending"}
                for index, item in enumerate(self.instructions)]
