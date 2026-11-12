"""从一份本地 INI 读取模型连接与能力配置。"""
from __future__ import annotations

import configparser
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from atestservice.llm.types import (
    ImageInputPolicy, LLMCapabilities, LLMModelConfig, StructuredOutputMethod,
)

_CONFIG_PATH = Path(__file__).with_name("models.ini")


def _read_config(config_path: str | Path | None = None) -> configparser.ConfigParser:
    path = Path(config_path) if config_path is not None else _CONFIG_PATH
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(path, encoding="utf-8-sig")
    return cfg


def _models_from_config(cfg: configparser.ConfigParser) -> dict[str, LLMModelConfig]:
    models = {}
    for name in cfg.sections():
        if name == "models":
            continue
        section = cfg[name]
        method = section.get("structured_output_method", "json_schema")
        policy = section.get("image_input_policy", "error")
        if method not in {"json_schema", "json_mode", "function_calling"}:
            raise ValueError(f"模型 {name} 的 structured_output_method 无效：{method}")
        if policy not in {"error", "drop"}:
            raise ValueError(f"模型 {name} 的 image_input_policy 无效：{policy}")
        employee_no = section.get("employee_no", "").strip()
        models[name] = LLMModelConfig(
            base_url=section.get("base_url", "").strip(),
            model=section.get("model", "").strip(),
            api_key=section.get("api_key", "EMPTY"),
            default_headers={"x-cm-employee-no": employee_no} if employee_no else {},
            structured_output_method=cast(StructuredOutputMethod, method),
            capabilities=LLMCapabilities(
                supports_vision=section.getboolean("supports_vision", fallback=True),
                supports_tool_calling=section.getboolean("supports_tool_calling", fallback=True),
                supports_json_schema=section.getboolean("supports_json_schema", fallback=True),
                supports_json_mode=section.getboolean("supports_json_mode", fallback=True),
            ),
            image_input_policy=cast(ImageInputPolicy, policy),
            debug_schema=section.getboolean("debug_schema", fallback=False),
        )
    return models


DEFAULT_LLM_MODEL = _read_config().get("models", "default", fallback="company_model")


def default_llm_models(config_path: str | Path | None = None) -> dict[str, LLMModelConfig]:
    return _models_from_config(_read_config(config_path))


def get_llm_model_config(model_name: str | None = None, **overrides: Any) -> LLMModelConfig:
    """读取指定模型；不传名称时使用 INI 的默认模型。"""
    cfg = _read_config()
    models = _models_from_config(cfg)
    if not models:
        raise ValueError(f"请在 {_CONFIG_PATH} 配置至少一个模型。")
    name = model_name if model_name is not None else cfg.get("models", "default", fallback="company_model")
    if name not in models:
        raise ValueError(f"unknown model: {name}; available: {', '.join(models)}")
    return replace(models[name], **{k: v for k, v in overrides.items() if v is not None})
