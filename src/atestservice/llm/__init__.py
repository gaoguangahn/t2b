"""图节点使用的 LLM 公共入口。

外部代码统一从这里导入 LLM 能力，避免依赖内部文件结构：

    from atestservice.llm import create_llm, StructuredLLM
"""

from __future__ import annotations

from atestservice.llm.client import (
    LangChainStructuredLLM,
    create_llm,
    normalize_openai_base_url,
)
from atestservice.llm.messages import (
    MessageBuilder,
    build_user_message,
    image_content_from_base64,
    text_content,
)
from atestservice.llm.models import (
    DEFAULT_LLM_MODEL,
    default_llm_models,
    get_llm_model_config,
)
from atestservice.llm.types import (
    ImageInputPolicy,
    LLMCallOptions,
    LLMCapabilities,
    LLMModelConfig,
    StructuredLLM,
    StructuredOutputMethod,
    T,
)


class MissingLLM:
    """未配置真实模型时使用的占位 LLM。"""

    @property
    def message_builder(self):
        raise RuntimeError("No StructuredLLM configured for mobile test agent")

    async def invoke_structured(self, prompt, schema, *, options=None):
        raise RuntimeError("No StructuredLLM configured for mobile test agent")

    async def invoke_structured_debug(self, prompt, schema, *, options=None):
        raise RuntimeError("No StructuredLLM configured for mobile test agent")
    async def invoke_tool(self, prompt, tools, *, options=None):
        raise RuntimeError("No StructuredLLM configured for mobile test agent")

    async def invoke_tool_message(self, prompt, tools, *, options=None):
        raise RuntimeError("No StructuredLLM configured for mobile test agent")


__all__ = [
    "DEFAULT_LLM_MODEL",
    "ImageInputPolicy",
    "LangChainStructuredLLM",
    "LLMCallOptions",
    "LLMCapabilities",
    "LLMModelConfig",
    "MessageBuilder",
    "MissingLLM",
    "StructuredLLM",
    "StructuredOutputMethod",
    "T",
    "build_user_message",
    "create_llm",
    "default_llm_models",
    "get_llm_model_config",
    "image_content_from_base64",
    "normalize_openai_base_url",
    "text_content",
]
