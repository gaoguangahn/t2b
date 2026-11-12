import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from atestservice.case_preparation.parser import CaseParser
from atestservice.case_preparation.models import CaseExtraction
from atestservice.case_preparation.service import CasePreparationService
from atestservice.case_preparation.structure_case import StructureCaseNode
from atestservice.config import ServerSettings
from atestservice.contracts.case import CaseSpec
from atestservice.runs.repository import InMemoryRunRepository
from atestservice.runs.routes import router
from atestservice.runs.service import RunService
from test_workflow import Publisher


def extraction(case):
    data = case.model_dump(mode="json", exclude={"schema_version", "source_revision"})
    return CaseExtraction.model_validate(data)


class CasePreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_and_node_share_parser(self):
        source = '输入 "a  b" + C++'
        case = CaseSpec(case_name="原值", steps=[{"id": "s1", "goal": source}])
        model = SimpleNamespace(invoke_structured=AsyncMock(return_value=extraction(case)))
        parser = CaseParser(llm=model)
        publisher = Publisher()
        draft = await CasePreparationService(parser).prepare(source, event_publisher=publisher)
        result = await StructureCaseNode(parser=parser)({"request": {"raw_text": source}})
        self.assertEqual(model.invoke_structured.await_count, 2)
        prompt, schema = model.invoke_structured.call_args.args
        self.assertEqual(schema, CaseExtraction)
        self.assertIn(json.dumps({"raw_text": source}, ensure_ascii=False), prompt)
        self.assertIn(source, draft.editable_text)
        self.assertNotIn("明确参数：", draft.editable_text)
        self.assertEqual(result["case_spec"]["source_revision"], parser_revision(source))
        self.assertEqual(publisher.events[-1]["node"], "prepare_case")
        artifact = publisher.events[-1]["payload"]["blocks"][1]
        self.assertEqual(artifact["filename"], "prepared_case.json")
        self.assertIsInstance(artifact["content"], dict)

    async def test_empty_input_does_not_call_model(self):
        parser = SimpleNamespace(parse=AsyncMock())
        with self.assertRaises(ValueError):
            await CasePreparationService(parser).prepare("  ")
        parser.parse.assert_not_awaited()

    async def test_failure_publishes_error_without_finished_draft(self):
        publisher = Publisher()
        parser = SimpleNamespace(parse=AsyncMock(side_effect=ValueError("invalid case")))
        with self.assertRaisesRegex(ValueError, "invalid case"):
            await CasePreparationService(parser).prepare("描述", event_publisher=publisher)
        self.assertEqual(len(publisher.events), 2)
        self.assertEqual(publisher.events[-1]["message"], "invalid case")


def parser_revision(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
        case = CaseSpec(case_name="单个用例", steps=[{"id": "s1", "goal": "打开应用"}])
        model = SimpleNamespace(invoke_structured=AsyncMock(return_value=extraction(case)))
        preparation = CasePreparationService(CaseParser(llm=model))
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
