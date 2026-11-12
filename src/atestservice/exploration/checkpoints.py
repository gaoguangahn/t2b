"""Bind semantic verification boundaries to immutable execution evidence."""
class CheckpointRecorder:
    def __init__(self, case_spec, step_id):
        self.verifications = case_spec.get("verifications", [])
        self.step_id = step_id
        self.records = []

    def capture(self, instruction_id, position, observations, operations):
        for verification in self.verifications:
            anchor = verification.get("anchor") or {}
            if (anchor.get("step_id"), anchor.get("instruction_id"), anchor.get("position")) == (self.step_id, instruction_id, position):
                self.records.append({"verification_id": verification["id"],
                    "observation_id": observations[-1]["id"], "capture_status": "captured",
                    "after_operation_id": operations[-1]["id"] if operations else None})
