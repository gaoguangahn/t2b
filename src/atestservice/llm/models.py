"""可用 LLM 模型配置。"""

from __future__ import annotations

from dataclasses import replace
import os
from typing import Any

from atestservice.llm.types import LLMCapabilities, LLMModelConfig

# Keep connection details outside versioned source. uv can load a local .env file.
COMAGIC_API_KEY = os.environ.get("COMAGIC_API_KEY", "EMPTY")
COMAGIC_BASE_URL = os.environ.get("COMAGIC_BASE_URL", "")
COMAGIC_MODEL = os.environ.get("COMAGIC_MODEL", "gpt-5.5-saas")
COMAGIC_EMPLOYEE_NO = os.environ.get("COMAGIC_EMPLOYEE_NO", "")

DEFAULT_LLM_MODEL = "company_model"


def default_llm_models() -> dict[str, LLMModelConfig]:
    """默认可用模型配置。"""

    return {
        "company_model": LLMModelConfig(
            base_url=COMAGIC_BASE_URL,
            model=COMAGIC_MODEL,
            api_key=COMAGIC_API_KEY,
            default_headers={"x-cm-employee-no": COMAGIC_EMPLOYEE_NO} if COMAGIC_EMPLOYEE_NO else {},
            # extra_body={
            #     "enable_thinking": False,
            # },
            structured_output_method="json_schema",
            capabilities=LLMCapabilities(
                supports_vision=True,
                supports_tool_calling=True,
                supports_json_schema=True,
                supports_json_mode=True,
            ),
            image_input_policy="error",
        ),
    }


def get_llm_model_config(
    model_name: str = DEFAULT_LLM_MODEL,
    **overrides: Any,
) -> LLMModelConfig:
    """读取模型配置，并允许调试脚本临时覆盖字段。"""

    models = default_llm_models()
    try:
        config = models[model_name]
    except KeyError as exc:
        available = ", ".join(models)
        raise ValueError(
            f"Unknown LLM model config: {model_name!r}. Available models: {available}."
        ) from exc

    if overrides:
        config = replace(
            config, **{k: v for k, v in overrides.items() if v is not None}
        )
    return config
