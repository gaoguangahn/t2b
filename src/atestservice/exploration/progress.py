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

    def snapshot(self):
        return [{"instruction_id": item["id"], "status": "completed" if index < self.index else
                 "in_progress" if index == self.index else "pending"}
                for index, item in enumerate(self.instructions)]
