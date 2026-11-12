"""LLM 层共享类型定义。

LLM 层只描述“有哪些模型、如何连接、模型具备什么能力”。
每个 node / agent loop 的 temperature、timeout、token 上限等调用参数，
由调用方通过 LLMCallOptions 自己决定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeAlias, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

StructuredOutputMethod: TypeAlias = Literal[
    "function_calling", "json_mode", "json_schema"
]
ImageInputPolicy: TypeAlias = Literal["error", "drop"]


@dataclass(slots=True)
class LLMCapabilities:
    """模型能力标记，用于在发送请求前做能力校验。"""

    supports_vision: bool = False
    supports_tool_calling: bool = True
    supports_json_schema: bool = True
    supports_json_mode: bool = True


@dataclass(slots=True)
class LLMCallOptions:
    """单次 LLM 调用参数，由具体 node/agent loop 按任务自行决定。"""

    temperature: float | None = None
    top_p: float | None = None
    max_completion_tokens: int | None = None
    timeout: float | None = None
    structured_output_method: StructuredOutputMethod | None = None


@dataclass(slots=True)
class LLMModelConfig:
    """单个模型服务配置。"""

    base_url: str
    model: str
    api_key: str = "EMPTY"
    default_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)
    structured_output_method: StructuredOutputMethod = "json_schema"
    capabilities: LLMCapabilities = field(default_factory=LLMCapabilities)
    image_input_policy: ImageInputPolicy = "error"
    debug_schema: bool = False


class StructuredLLM(Protocol):
    """图节点依赖的最小 LLM 接口。"""

    @property
    def message_builder(self) -> Any:
        """返回带当前模型能力约束的消息构造器。"""
        ...

    async def invoke_structured(
        self,
        prompt: Any,
        schema: type[T],
        *,
        options: LLMCallOptions | None = None,
    ) -> T:
        """调用模型并返回已通过 Pydantic 校验的结构化结果。"""
        ...

    async def invoke_structured_debug(
        self,
        prompt: Any,
        schema: type[T],
        *,
        options: LLMCallOptions | None = None,
    ) -> dict[str, Any]:
        """调用结构化输出，并返回 parsed 对象和原始响应诊断信息。"""
        ...
    async def invoke_tool(
        self,
        prompt: Any,
        tools: list[type[BaseModel]],
        *,
        options: LLMCallOptions | None = None,
    ) -> dict[str, Any]:
        """调用模型选择一个工具，并返回工具名和参数。"""
        ...

    async def invoke_tool_message(
        self,
        prompt: Any,
        tools: list[type[BaseModel]],
        *,
        options: LLMCallOptions | None = None,
    ) -> Any:
        """调用模型选择工具，并返回原始 AIMessage。"""
        ...
