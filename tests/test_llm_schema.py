"""Exercise real LangChain/SDK serialization with an offline strict HTTP provider."""
import asyncio
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import unittest
from typing import Any
from unittest.mock import patch

import httpx
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, ValidationError

from atestservice.case_preparation.models import CaseExtraction
from atestservice.case_preparation.parser import CaseParser
from atestservice.contracts.case import CaseSpec
from atestservice.contracts.script import CodegenResult
from atestservice.exploration.tools.tool_definitions import EXPLORE_ACTION_TOOLS, tool_call_to_decision
from atestservice.llm.client import LangChainStructuredLLM
from atestservice.llm.schema import ModelSchemaError, strict_schema, strict_tool, validate_strict_schema
from atestservice.llm.types import LLMCallOptions, LLMCapabilities, LLMModelConfig
from atestservice.script_generation.planning.models import PlanningResponse
from atestservice.script_generation.targeting.models import TargetResponse


INSTRUCTION_TEXT = '输入原文「 a  b\n$test`" 」，向上滑动2次，每次间隔2.5秒'
CASE = {"case_name": "搜索", "case_goal": "搜索原文", "steps": [{"id": "s1", "goal": "搜索原文", "repeat": 3,
        "instructions": [{"id": "i1", "text": INSTRUCTION_TEXT, "kind": "ui"}]}],
        "verifications": [{"id": "v1", "goal": "验证不存在的提示", "anchor": {"step_id": "s1", "instruction_id": "i1", "position": "after"}, "scope": "each_iteration"}]}


class OpenParameters(BaseModel):
    parameters: dict[str, str]

RESPONSES = [
    (CaseExtraction, CASE),
    (PlanningResponse, {"plan": {"schema_version": "1.0", "actions": [], "conditions": [], "omitted_segments": [], "issues": []}, "observation_requests": []}),
    (TargetResponse, {"targets": [{"request_id": "op0", "kind": "unresolved", "target_description": "目标", "candidate_id": None,
                                  "candidate_observation_id": None, "verification": None,
                                  "attributes": [], "scope_candidate_id": None, "scope_attributes": [], "scope_index": None,
                                  "index": None, "attribute_role": "control_identity", "reason": "缺少证据"}]}),
    (TargetResponse, {"targets": [{"request_id": "verify:v1", "kind": "ui", "target_description": "Wi-Fi开关",
                                  "candidate_id": "e0", "candidate_observation_id": "o1", "attributes": ["resource_id"],
                                  "verification": {"method": "attribute", "attribute": "checked", "operator": "equals",
                                                   "expected_value": False, "evidence_observation_ids": ["o0", "o1"],
                                                   "baseline_operation_id": None, "basis": "checked表示开关状态，用户要求关闭"},
                                  "reason": "操作前后同一开关的状态属性"}]}),
    (CodegenResult, {"language": "python", "framework": "dynamic_framework", "filename": "test_case.py", "content": "def test_case():\n    pass\n", "notes": []}),
]


def require_explicit_item_types(node, path="$"):
    """Emulate a gateway that does not resolve references at array items."""
    if isinstance(node, dict):
        if node.get("type") == "array" and "type" not in node.get("items", {}):
            raise ValueError(f"{path}.items: schema must have a type key")
        for key, value in node.items():
            require_explicit_item_types(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            require_explicit_item_types(value, f"{path}[{index}]")


class OfflineProvider:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def __call__(self, request):
        payload = json.loads(request.content)
        self.requests.append(payload)
        if payload.get("tools"):
            for tool in payload["tools"]:
                assert tool["function"]["strict"] is True
                require_explicit_item_types(tool["function"]["parameters"])
                validate_strict_schema(tool["function"]["parameters"])
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_fixture", "type": "function", "function": {
                "name": payload["tools"][0]["function"]["name"], "arguments": json.dumps(self.response)}}]}
            finish_reason = "tool_calls"
        else:
            output = payload["response_format"]
            if output["type"] == "json_schema":
                assert output["json_schema"]["strict"] is True
                require_explicit_item_types(output["json_schema"]["schema"])
                validate_strict_schema(output["json_schema"]["schema"])
            else:
                assert output["type"] == "json_object"
                assert "JSON" in str(payload["messages"])
            message = {"role": "assistant", "content": json.dumps(self.response)}
            finish_reason = "stop"
        return httpx.Response(200, json={"id": "chatcmpl-offline", "object": "chat.completion", "created": 0,
            "model": "offline-fixture", "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}]})


class SchemaTests(unittest.TestCase):
    def test_every_actual_output_and_exploration_tool_has_valid_wire_schema(self):
        for model in [item[0] for item in RESPONSES] + EXPLORE_ACTION_TOOLS:
            with self.subTest(schema=model.__name__):
                original = deepcopy(model.model_json_schema())
                wire = strict_schema(model)
                validate_strict_schema(wire)
                self.assertEqual(original, model.model_json_schema())

    def test_business_dictionary_is_rejected_instead_of_silently_closed(self):
        with self.assertRaisesRegex(ModelSchemaError, "parameters.*open dictionaries"):
            strict_schema(OpenParameters)
        self.assertEqual(CaseSpec(case_name="x").schema_version, "2.0")

    def test_required_and_additional_properties_failures_are_detected_recursively(self):
        wire = strict_schema(CaseExtraction)
        wire["required"].append("parameters")
        with self.assertRaisesRegex(ModelSchemaError, "required"):
            validate_strict_schema(wire)
        wire = strict_schema(CaseExtraction)
        wire["properties"]["steps"]["items"]["properties"]["instructions"]["items"]["additionalProperties"] = True
        with self.assertRaisesRegex(ModelSchemaError, "additionalProperties"):
            validate_strict_schema(wire)

    def test_nullable_fields_required_and_defaults_removed_without_losing_null(self):
        wire = strict_schema(TargetResponse)
        target = wire["properties"]["targets"]["items"]
        self.assertEqual(set(target["required"]), set(target["properties"]))
        index = target["properties"]["index"]
        self.assertNotIn("default", index)
        self.assertIn({"type": "null"}, index["anyOf"])

    def test_model_extraction_keeps_description_and_rejects_parameter_table(self):
        case = CaseExtraction.model_validate(CASE).to_case_spec()
        self.assertEqual(case.steps[0].repeat, 3)
        instruction = case.steps[0].instructions[0]
        self.assertEqual(instruction.text, INSTRUCTION_TEXT)
        self.assertEqual(set(instruction.model_dump()), {"id", "text", "kind"})
        self.assertEqual(case.verifications[0].goal, "验证不存在的提示")
        self.assertNotIn("source_revision", strict_schema(CaseExtraction)["properties"])
        broken = deepcopy(CASE)
        instruction = strict_schema(CaseExtraction)["properties"]["steps"]["items"]["properties"]["instructions"]["items"]
        self.assertNotIn("parameters", instruction["properties"])
        broken["steps"][0]["instructions"][0]["parameters"] = {}
        with self.assertRaises(ValidationError):
            CaseExtraction.model_validate(broken)

    def test_reference_validation_still_applies_after_extraction(self):
        broken = deepcopy(CASE)
        broken["verifications"][0]["anchor"]["step_id"] = "unknown"
        with self.assertRaisesRegex(ValidationError, "unknown verification"):
            CaseExtraction.model_validate(broken).to_case_spec()

    def test_extra_required_and_unsupported_tuple_contract_fail_before_sdk(self):
        class Broken(BaseModel):
            model_config = ConfigDict(json_schema_extra={"required": ["invented"]})
            value: str
        with self.assertRaisesRegex(ModelSchemaError, "undeclared"):
            strict_schema(Broken)
        class TupleContract(BaseModel):
            point: tuple[int, int]
        with self.assertRaisesRegex(ModelSchemaError, "prefixItems"):
            strict_schema(TupleContract)

    def test_untyped_values_are_not_silently_passed_to_provider(self):
        class Untyped(BaseModel):
            value: Any
        with self.assertRaisesRegex(ModelSchemaError, "untyped"):
            strict_schema(Untyped)

    def test_planning_array_reference_reproduces_error_and_expands_to_object(self):
        with self.assertRaisesRegex(ValueError, r"actions.items: schema must have a type key"):
            require_explicit_item_types(PlanningResponse.model_json_schema())
        wire = strict_schema(PlanningResponse)
        require_explicit_item_types(wire)
        self.assertNotIn("$defs", wire)
        self.assertNotIn('"$ref"', json.dumps(wire))
        plan = wire["properties"]["plan"]["anyOf"][0]
        self.assertEqual(plan["type"], "object")
        action = plan["properties"]["actions"]["items"]
        self.assertEqual(action["type"], "object")
        self.assertEqual(action["required"], ["operation_id", "description", "condition_id"])
        self.assertFalse(action["additionalProperties"])
        self.assertIn({"type": "null"}, action["properties"]["condition_id"]["anyOf"])

    def test_repeated_reference_is_expanded_independently(self):
        class Child(BaseModel):
            value: str
        class Pair(BaseModel):
            first: Child
            second: Child
        wire = strict_schema(Pair)
        wire["properties"]["first"]["properties"]["value"]["description"] = "first only"
        self.assertNotIn("description", wire["properties"]["second"]["properties"]["value"])

    def test_recursive_reference_fails_locally_instead_of_sending_a_truncated_schema(self):
        class Node(BaseModel):
            children: list["Node"]
        with self.assertRaisesRegex(ModelSchemaError, "recursive"):
            strict_schema(Node)

    def test_unknown_reference_is_reported_before_http(self):
        class MissingReference(BaseModel):
            pass
        broken = {"type": "object", "properties": {"child": {"$ref": "#/$defs/Unknown"}}}
        with patch.object(MissingReference, "model_json_schema", return_value=broken), self.assertRaisesRegex(ModelSchemaError, "unknown schema reference"):
            strict_schema(MissingReference)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.aclose()

    def llm(self, provider, method="json_schema"):
        client = httpx.AsyncClient(transport=httpx.MockTransport(provider), trust_env=False)
        self.clients.append(client)
        chat = ChatOpenAI(model="offline-fixture", api_key="PRIVATE_KEY", base_url="https://offline.invalid/v1",
                          http_async_client=client, max_retries=0, http_socket_options=())
        return LangChainStructuredLLM(chat, model_name="fixture", config=LLMModelConfig(
            base_url="https://offline.invalid/v1", model="offline-fixture", structured_output_method=method,
            capabilities=LLMCapabilities()))

    async def test_sdk_final_payloads_for_all_outputs_in_both_strict_modes(self):
        for method in ("json_schema", "function_calling"):
            for schema, value in RESPONSES:
                with self.subTest(method=method, schema=schema.__name__):
                    provider = OfflineProvider(value)
                    result = await self.llm(provider, method).invoke_structured("fixture", schema)
                    self.assertIsInstance(result, schema)
                    self.assertEqual(result.model_dump(mode="json"), schema.model_validate(value).model_dump(mode="json"))
                    self.assertEqual(len(provider.requests), 1)

    async def test_real_prepare_path_preserves_description_without_parameter_extraction(self):
        provider = OfflineProvider(CASE)
        parser = CaseParser(self.llm(provider))
        case = await parser.parse("fixture input")
        self.assertEqual(case.steps[0].instructions[0].text, INSTRUCTION_TEXT)
        self.assertNotIn("parameters", case.steps[0].instructions[0].model_dump())
        self.assertEqual(len(case.source_revision), 64)
        wire = provider.requests[0]["response_format"]["json_schema"]
        self.assertEqual(wire["name"], "CaseExtraction")
        self.assertNotIn("schema_version", wire["schema"]["properties"])

    async def test_exploration_tools_use_strict_wire_and_still_decode(self):
        provider = OfflineProvider({"reason": "当前可见目标", "complete_current_instruction": False, "bounds": [100, 100, 200, 200]})
        result = await self.llm(provider).invoke_tool("fixture", EXPLORE_ACTION_TOOLS)
        decision = tool_call_to_decision(result)
        self.assertEqual(decision.action.action, "click")
        self.assertEqual(len(provider.requests[0]["tools"]), len(EXPLORE_ACTION_TOOLS))

    async def test_diagnostic_call_uses_same_schema_without_printing(self):
        provider = OfflineProvider(RESPONSES[-1][1])
        output = io.StringIO()
        with redirect_stdout(output):
            result = await self.llm(provider).invoke_structured_debug("PRIVATE_CASE_TEXT", CodegenResult)
        self.assertIsInstance(result["parsed"], CodegenResult)
        expected = strict_schema(CodegenResult)
        expected.pop("title", None)  # The SDK uses the root title as response_format.name.
        self.assertEqual(provider.requests[0]["response_format"]["json_schema"]["schema"], expected)
        self.assertIsNone(result["diagnostics"]["parsing_error"])
        self.assertEqual(result["diagnostics"]["response_metadata"]["finish_reason"], "stop")
        self.assertEqual(output.getvalue(), "")

    async def test_invalid_schema_raises_before_http_without_printing(self):
        provider = OfflineProvider({})
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaisesRegex(ModelSchemaError, "parameters"):
            await self.llm(provider).invoke_structured("private", OpenParameters)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(provider.requests, [])

    async def test_json_mode_carries_schema_instruction_and_validates_locally(self):
        provider = OfflineProvider(RESPONSES[-1][1])
        result = await self.llm(provider, "json_mode").invoke_structured([{"role": "user", "content": "fixture"}], CodegenResult)
        self.assertIsInstance(result, CodegenResult)
        self.assertIn("required", provider.requests[0]["messages"][0]["content"])
        self.assertEqual(provider.requests[0]["response_format"], {"type": "json_object"})

    async def test_json_schema_messages_satisfy_qwen_json_keyword_requirement(self):
        for prompt in ("整理用例", [{"role": "user", "content": "整理用例"}]):
            with self.subTest(prompt_type=type(prompt).__name__):
                provider = OfflineProvider(CASE)

                def require_json_keyword(request):
                    payload = json.loads(request.content)
                    if not any("json" in str(message["content"]).lower() for message in payload["messages"]):
                        return httpx.Response(400, json={"error": {
                            "type": "invalid_request_error", "code": "Algo.InvalidParameter",
                            "message": "'messages' must contain the word 'json' in some form"}})
                    return provider(request)

                result = await self.llm(require_json_keyword, "json_schema").invoke_structured(prompt, CaseExtraction)
                self.assertIsInstance(result, CaseExtraction)
                self.assertEqual(len(provider.requests), 1)
                output = provider.requests[0]["response_format"]
                self.assertEqual(output["type"], "json_schema")
                self.assertTrue(output["json_schema"]["strict"])

    async def test_call_options_override_model_method_and_bad_output_is_not_accepted(self):
        provider = OfflineProvider({"language": "not-python"})
        llm = self.llm(provider, "json_schema")
        with self.assertRaises(ValidationError):
            await llm.invoke_structured("fixture", CodegenResult, options=LLMCallOptions(structured_output_method="function_calling"))
        self.assertIn("tools", provider.requests[0])
        self.assertNotIn("response_format", provider.requests[0])

    async def test_unsupported_capability_fails_before_http(self):
        provider = OfflineProvider({})
        llm = self.llm(provider)
        llm.config.capabilities.supports_json_schema = False
        with self.assertRaisesRegex(ValueError, "does not support json_schema"):
            await llm.invoke_structured("fixture", CodegenResult)
        self.assertEqual(provider.requests, [])

    async def test_http_schema_rejection_is_not_hidden_by_mode_fallback(self):
        requests = []
        def reject(request):
            requests.append(json.loads(request.content))
            return httpx.Response(400, json={"error": {"type": "invalid_request_error", "message": "fixture schema rejection", "code": "invalid_json_schema"}})
        from openai import BadRequestError
        with self.assertRaisesRegex(BadRequestError, "fixture schema rejection"):
            await self.llm(reject).invoke_structured("fixture", CodegenResult)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["response_format"]["type"], "json_schema")
