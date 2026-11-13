"""优化服务独立返回可编辑文本，正式执行结构由另一入口生成。"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.exceptions import OutputParserException

from atestservice.case_preparation.service import CasePreparationService, PreparedCase
from atestservice.config import ServerSettings
from atestservice.runs.repository import InMemoryRunRepository
from atestservice.runs.routes import router
from atestservice.runs.service import RunService
from test_workflow import Publisher


class CasePreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_optimization_returns_text_without_creating_execution_structure(self):
        source = '输入 "a  b" + C++'
        text = '【用例名称】\n输入内容\n【流程】\n1. 操作：'+source
        expected = PreparedCase(title="输入内容", editable_text=text)
        model = SimpleNamespace(invoke_structured=AsyncMock(return_value=expected))
        publisher = Publisher()
        draft = await CasePreparationService(llm=model).prepare(source, event_publisher=publisher)
        self.assertEqual(draft, expected)
        prompt, schema = model.invoke_structured.call_args.args
        self.assertIs(schema, PreparedCase)
        self.assertEqual(set(schema.model_fields), {"title", "editable_text"})
        self.assertIn(json.dumps({"raw_text": source}, ensure_ascii=False), prompt)
        self.assertNotIn("{raw_case_json}", prompt)
        model.invoke_structured.assert_awaited_once()
        self.assertEqual(publisher.events[-1]["node"], "prepare_case")
        artifact = publisher.events[-1]["payload"]["blocks"][1]
        self.assertEqual(artifact["filename"], "prepared_case.json")
        self.assertEqual(artifact["content"], expected.model_dump())

    async def test_empty_input_does_not_call_model(self):
        model = SimpleNamespace(invoke_structured=AsyncMock())
        with self.assertRaises(ValueError):
            await CasePreparationService(llm=model).prepare("  ")
        model.invoke_structured.assert_not_awaited()

    async def test_failure_publishes_error_without_finished_draft(self):
        publisher = Publisher()
        model = SimpleNamespace(invoke_structured=AsyncMock(side_effect=RuntimeError("provider unavailable")))
        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            await CasePreparationService(llm=model).prepare("描述", event_publisher=publisher)
        self.assertEqual(len(publisher.events), 2)
        self.assertEqual(publisher.events[-1]["message"], "provider unavailable")
        model.invoke_structured.assert_awaited_once()

    async def test_invalid_output_format_is_retried_without_execution_schema(self):
        expected = PreparedCase(title="关闭蓝牙", editable_text="关闭蓝牙，验证关闭")
        model = SimpleNamespace(invoke_structured=AsyncMock(side_effect=[OutputParserException("bad json"), expected]))
        self.assertEqual(await CasePreparationService(llm=model).prepare("关闭蓝牙，验证关闭"), expected)
        self.assertEqual(model.invoke_structured.await_count, 2)
        self.assertIn("只纠正输出格式", model.invoke_structured.call_args.args[0])
        self.assertTrue(all(call.args[1] is PreparedCase for call in model.invoke_structured.call_args_list))

    async def test_confirmed_edit_is_structured_without_optimizing_it_again(self):
        from atestservice.exploration.case_structuring import StructureCaseNode
        from atestservice.exploration.case_structuring.models import CaseExtraction
        edited = '1) 输入 "a  b"\n   验证：显示 "a  b"'
        extracted = CaseExtraction(case_name="输入", case_goal="", steps=[{
            "id": "s1", "goal": '输入 "a  b"', "repeat": 1,
            "instructions": [{"id": "i1", "text": '输入 "a  b"'}]}], verifications=[{
            "id": "v1", "goal": '显示 "a  b"', "anchor": {"step_id": "s1", "instruction_id": "i1", "position": "after"},
            "scope": "each_iteration"}])
        draft = PreparedCase(title="输入", editable_text='1. 输入 "a"，验证显示 "a"')
        model = SimpleNamespace(invoke_structured=AsyncMock(side_effect=[draft, extracted]))
        await CasePreparationService(llm=model).prepare("输入a并验证")
        result = await StructureCaseNode(llm=model)({"request": {"raw_text": edited}})
        self.assertEqual([call.args[1] for call in model.invoke_structured.call_args_list], [PreparedCase, CaseExtraction])
        self.assertIn(json.dumps({"confirmed_text": edited}, ensure_ascii=False), model.invoke_structured.call_args.args[0])
        self.assertEqual(result["case_spec"]["steps"][0]["instructions"][0]["text"], '输入 "a  b"')
        self.assertEqual(result["case_spec"]["verifications"][0]["goal"], '显示 "a  b"')


class PrepareApiTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.state.settings = ServerSettings(run_repository="memory")
        self.sessions = SimpleNamespace(
            get=lambda session_id: SimpleNamespace(user_id="mock-user", plugin_session_id=session_id) if session_id == "ps1" else None,
            send_event=AsyncMock(),
        )
        self.app.state.run_service = RunService(repository=InMemoryRunRepository(), plugin_sessions=self.sessions)
        self.client = TestClient(self.app)

    def test_single_case_response_and_session_checks(self):
        draft = PreparedCase(title="单个用例", editable_text="【流程】\n1. 打开应用")
        model = SimpleNamespace(invoke_structured=AsyncMock(return_value=draft))
        preparation = CasePreparationService(llm=model)
        with patch("atestservice.runs.service.prepare_case", side_effect=preparation.prepare):
            response = self.client.post("/api/v1/runs/prepare", json={"pluginSessionId": "ps1", "input": "打开应用"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(set(response.json()), {"title", "editableText"})
            self.assertEqual(response.json()["title"], "单个用例")
            model.invoke_structured.assert_awaited_once()
            invalid = self.client.post("/api/v1/runs/prepare", json={"pluginSessionId": "missing", "input": "打开应用"})
            self.assertEqual(invalid.status_code, 400)
            model.invoke_structured.assert_awaited_once()
        self.assertGreaterEqual(self.sessions.send_event.await_count, 2)

    def test_batch_and_empty_payloads_are_rejected(self):
        for payload in [
            {"pluginSessionId": "ps1", "inputs": [{"caseId": "c1", "input": "描述"}]},
            {"pluginSessionId": "ps1", "input": "描述", "inputs": []},
            {"pluginSessionId": "ps1", "input": "  "},
            {"pluginSessionId": "ps1", "input": ["描述"]},
        ]:
            with self.subTest(payload=payload):
                response = self.client.post("/api/v1/runs/prepare", json=payload)
                self.assertEqual(response.status_code, 422)
        self.sessions.send_event.assert_not_awaited()
