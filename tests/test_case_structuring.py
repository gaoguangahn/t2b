"""确认稿只做结构转换；结构纠错不重新调用优化服务。"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from atestservice.exploration.case_structuring import CaseParser, StructureCaseNode
from atestservice.exploration.case_structuring.models import CaseExtraction
from atestservice.contracts.case import CaseSpec


def extraction(case):
    return CaseExtraction.model_validate(case.model_dump(mode="json", exclude={"schema_version", "source_revision"}))


class StructuringTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmed_text_is_the_only_input_and_existing_case_needs_no_model(self):
        text = '【流程】\n1) 输入 "a  b" + C++'
        case = CaseSpec(case_name="确认稿", steps=[{"id": "s1", "goal": text}])
        model = SimpleNamespace(invoke_structured=AsyncMock(return_value=extraction(case)))
        node = StructureCaseNode(llm=model)
        result = await node({"request": {"raw_text": text}})
        prompt, schema = model.invoke_structured.call_args.args
        self.assertIs(schema, CaseExtraction)
        self.assertIn(json.dumps({"confirmed_text": text}, ensure_ascii=False), prompt)
        self.assertIn("不再次优化", prompt)
        self.assertNotIn("{confirmed_case_json}", prompt)
        self.assertEqual(result["case_spec"]["steps"][0]["instructions"][0]["text"], text)
        import hashlib
        self.assertEqual(result["case_spec"]["source_revision"], hashlib.sha256(text.encode()).hexdigest())
        again = await node({"case_spec": result["case_spec"]})
        self.assertEqual(again, result)
        model.invoke_structured.assert_awaited_once()

    async def test_single_iteration_normalizes_scope_without_moving_instruction_anchor(self):
        item = CaseExtraction(case_name="wifi", case_goal="关闭Wi-Fi", steps=[{
            "id": "s1", "goal": "关闭Wi-Fi", "repeat": 1,
            "instructions": [{"id": "i1", "text": "关闭Wi-Fi"}]}], verifications=[{
            "id": "v1", "goal": "Wi-Fi确实关闭", "anchor": {"step_id": "s1", "instruction_id": "i1", "position": "after"},
            "scope": "outside_repeat"}])
        model = SimpleNamespace(invoke_structured=AsyncMock(return_value=item))
        result = await CaseParser(model).parse("到设置中关闭wifi开关并且验证确实关闭了开关")
        self.assertEqual(result.verifications[0].scope, "each_iteration")
        self.assertEqual(result.verifications[0].anchor.instruction_id, "i1")
        self.assertEqual(item.verifications[0].scope, "outside_repeat")
        model.invoke_structured.assert_awaited_once()

    async def test_repeated_case_requires_model_correction_and_preserves_expectation(self):
        item = CaseExtraction(case_name="repeat", case_goal="repeat", steps=[{
            "id": "s1", "goal": "操作", "repeat": 3,
            "instructions": [{"id": "i1", "text": "操作"}]}], verifications=[{
            "id": "v1", "goal": "用户预期", "anchor": {"step_id": "s1", "instruction_id": "i1", "position": "after"},
            "scope": "outside_repeat"}])
        corrected = item.model_copy(deep=True)
        corrected.verifications[0].scope = "each_iteration"
        model = SimpleNamespace(invoke_structured=AsyncMock(side_effect=[item, corrected]))
        case = await CaseParser(model).parse("每轮操作后验证，重复3次")
        self.assertEqual(model.invoke_structured.await_count, 2)
        self.assertIn("outside_repeat must anchor", model.invoke_structured.call_args.args[0])
        self.assertEqual(case.verifications[0].goal, "用户预期")
        self.assertEqual(case.steps[0].repeat, 3)
        model.invoke_structured = AsyncMock(return_value=item)
        with self.assertRaisesRegex(ValueError, "纠正两次"):
            await CaseParser(model).parse("描述")
        self.assertEqual(model.invoke_structured.await_count, 3)

    async def test_json_parse_errors_are_retried_but_provider_failures_are_not(self):
        from langchain_core.exceptions import OutputParserException
        valid = extraction(CaseSpec(case_name="case", steps=[{"id": "s1", "goal": "操作"}]))
        model = SimpleNamespace(invoke_structured=AsyncMock(side_effect=[OutputParserException("bad json"), valid]))
        await CaseParser(model).parse("描述")
        self.assertEqual(model.invoke_structured.await_count, 2)
        model.invoke_structured = AsyncMock(side_effect=RuntimeError("provider unavailable"))
        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            await CaseParser(model).parse("描述")
        model.invoke_structured.assert_awaited_once()

