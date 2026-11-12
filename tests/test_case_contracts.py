"""Offline checks for the shared case boundary, with no model/device calls."""
import unittest

from pydantic import ValidationError

from atestservice.contracts.case import CaseSpec


class CaseContractTests(unittest.TestCase):
    def test_repeat_and_literal_values_survive_serialization(self):
        text = '输入 "a  b" + C++'
        case = CaseSpec.model_validate({
            "case_name": "literal", "steps": [{"id": "step_001", "goal": text, "repeat": 5}],
            "verifications": [{"id": "verify_001", "step_id": "step_001", "goal": "提示不存在"}],
        })
        restored = CaseSpec.model_validate_json(case.model_dump_json())
        self.assertEqual(restored.steps[0].goal, text)
        self.assertEqual(restored.steps[0].repeat, 5)
        self.assertEqual(len(restored.steps), 1)
        self.assertEqual(restored.verifications[0].goal, "提示不存在")

    def test_duplicate_ids_are_rejected(self):
        for field, item in [
            ("steps", {"id": "same", "goal": "操作"}),
            ("verifications", {"id": "same", "goal": "验证"}),
        ]:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                CaseSpec.model_validate({"case_name": "duplicate", field: [item, item]})

    def test_dangling_verification_reference_is_rejected(self):
        with self.assertRaises(ValidationError):
            CaseSpec.model_validate({"case_name": "invalid", "verifications": [
                {"id": "verify_001", "step_id": "missing", "goal": "验证"},
            ]})

    def test_existing_legacy_names_normalize_at_boundary(self):
        case = CaseSpec.model_validate({"case_name": "legacy", "operation_steps": [
            {"id": "step_001", "text": "搜索"},
        ], "verification_steps": [
            {"id": "verify_001", "after_step_id": "step_001", "text": "保留预期"},
        ]})
        self.assertEqual(case.verifications[0].step_id, "step_001")
        self.assertNotIn("operation_steps", case.model_dump())


if __name__ == "__main__":
    unittest.main()
