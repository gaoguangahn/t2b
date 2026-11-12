"""Translate a validated script plan into framework code; never re-plan exploration."""
import ast
import json
from pathlib import Path
from atestservice.contracts.script import CodegenResult, ScriptIR
from atestservice.llm.types import LLMCallOptions, StructuredLLM
from atestservice.script_generation.framework_profiles import load_profile

_PROMPT = Path(__file__).parent / "prompts" / "codegen.md"
_OPTIONS = LLMCallOptions(temperature=0.1, max_completion_tokens=12000, timeout=120, structured_output_method="function_calling")


async def generate_code(ir: ScriptIR, *, llm: StructuredLLM, profile_name: str | None = None) -> CodegenResult:
    messages = [{"role": "system", "content": _PROMPT.read_text(encoding="utf-8")},
                {"role": "user", "content": json.dumps({"ir": ir.model_dump(mode="json", exclude_none=True),
                                                           "codegen_profile": load_profile(profile_name)}, ensure_ascii=False)}]
    result = await llm.invoke_structured(messages, CodegenResult, options=_OPTIONS)
    tree = ast.parse(result.content)
    if not result.content.strip() or not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree)):
        raise ValueError("Generated script must define a test function or method")
    if Path(result.filename).name != result.filename or "/" in result.filename or "\\" in result.filename or not result.filename.endswith(".py"):
        raise ValueError("Generated filename must be a plain Python filename")
    return result
