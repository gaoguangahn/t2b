"""基于 LangChain ChatOpenAI 的 LLM 客户端适配器。"""

from __future__ import annotations

import json
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr

from atestservice.llm.messages import MessageBuilder
from atestservice.llm.models import DEFAULT_LLM_MODEL, get_llm_model_config
from atestservice.llm.types import LLMCallOptions, LLMModelConfig, T


class LangChainStructuredLLM:
    """把 LangChain ChatOpenAI 适配为图节点使用的 StructuredLLM 接口。"""

    def __init__(
        self,
        chat_model: ChatOpenAI,
        *,
        model_name: str,
        config: LLMModelConfig,
    ):
        self.chat_model: ChatOpenAI = chat_model
        self.model_name = model_name
        self.config = config

    async def invoke_structured(
        self,
        prompt: Any,
        schema: type[T],
        *,
        options: LLMCallOptions | None = None,
    ) -> T:
        """调用结构化输出，并使用传入 schema 做最终校验。"""

        method = options.structured_output_method if options else None
        model = self._chat_model(options).with_structured_output(
            schema,
            method=method or self.config.structured_output_method,
        )
        result = await model.ainvoke(self._normalize_prompt(prompt))
        if isinstance(result, schema):
            return result
        return schema.model_validate(result)

    async def invoke_structured_debug(
        self,
        prompt: Any,
        schema: type[T],
        *,
        options: LLMCallOptions | None = None,
    ) -> dict[str, Any]:
        """调用结构化输出并保留原始消息 metadata，用于诊断截断/解析问题。"""

        method = options.structured_output_method if options else None
        model = self._chat_model(options).with_structured_output(
            schema,
            method=method or self.config.structured_output_method,
            include_raw=True,
        )
        result = await model.ainvoke(self._normalize_prompt(prompt))
        if not isinstance(result, dict):
            parsed = (
                result if isinstance(result, schema) else schema.model_validate(result)
            )
            return {
                "parsed": parsed,
                "diagnostics": {
                    "response_metadata": {},
                    "usage_metadata": {},
                    "parsing_error": None,
                    "raw_content_preview": "",
                },
            }

        raw = result.get("raw")
        parsed = result.get("parsed")
        parsing_error = result.get("parsing_error")
        if parsed is not None and not isinstance(parsed, schema):
            parsed = schema.model_validate(parsed)

        return {
            "parsed": parsed,
            "diagnostics": {
                "response_metadata": getattr(raw, "response_metadata", {})
                if raw
                else {},
                "usage_metadata": getattr(raw, "usage_metadata", {}) if raw else {},
                "parsing_error": str(parsing_error) if parsing_error else None,
                "raw_content_preview": str(getattr(raw, "content", "")) if raw else "",
            },
        }

    async def invoke_tool(
        self,
        prompt: Any,
        tools: list[type[BaseModel]],
        *,
        options: LLMCallOptions | None = None,
    ) -> dict[str, Any]:
        """调用 tool calling，并要求模型恰好选择一个工具。"""

        result = await self.invoke_tool_message(prompt, tools, options=options)
        tool_calls = getattr(result, "tool_calls", None) or []
        if len(tool_calls) != 1:
            raise ValueError(f"expected exactly one tool call, got {len(tool_calls)}")

        tool_call = tool_calls[0]
        args = tool_call.get("args") or {}
        if isinstance(args, str):
            args = json.loads(args)

        return {"name": tool_call.get("name"), "args": args}

    async def invoke_tool_message(
        self,
        prompt: Any,
        tools: list[type[BaseModel]],
        *,
        options: LLMCallOptions | None = None,
    ) -> Any:
        """调用 tool calling，并返回原始 AIMessage。

        agent loop 需要把 assistant tool_call 消息放回标准上下文，因此这里不只
        返回 name/args，而是保留 LangChain 返回的完整消息对象。
        """

        if not self.config.capabilities.supports_tool_calling:
            raise ValueError(
                f"LLM model {self.model_name!r} does not support tool calling."
            )

        model = self._chat_model(options).bind_tools(tools, tool_choice="any")
        return await model.ainvoke(self._normalize_prompt(prompt))

    @property
    def message_builder(self) -> MessageBuilder:
        """返回携带当前模型能力约束的消息构造器。"""

        return MessageBuilder(
            capabilities=self.config.capabilities,
            image_policy=self.config.image_input_policy,
        )

    def _chat_model(self, options: LLMCallOptions | None = None) -> Any:
        """返回应用了单次调用参数的模型 runnable。"""

        if options is None:
            return self.chat_model

        kwargs: dict[str, Any] = {}
        if options.temperature is not None:
            kwargs["temperature"] = options.temperature
        if options.top_p is not None:
            kwargs["top_p"] = options.top_p
        if options.max_completion_tokens is not None:
            kwargs["max_completion_tokens"] = options.max_completion_tokens
        if options.timeout is not None:
            kwargs["timeout"] = options.timeout

        if not kwargs:
            return self.chat_model
        return self.chat_model.bind(**kwargs)

    def _normalize_prompt(self, prompt: Any) -> Any:
        if isinstance(prompt, list):
            return self._normalize_messages(prompt)
        return str(prompt)

    def _normalize_messages(self, messages: list[Any]) -> list[Any]:
        """根据模型能力处理多模态消息。"""

        if self.config.capabilities.supports_vision:
            return messages
        if self.config.image_input_policy == "drop":
            return [_drop_image_content(message) for message in messages]
        if _contains_image_content(messages):
            raise ValueError(
                f"LLM model {self.model_name!r} / {self.config.model!r} "
                "does not support image input. Use a vision-capable model "
                "or set image_input_policy='drop'."
            )
        return messages


def create_llm(
    model_name: str = DEFAULT_LLM_MODEL,
    *,
    model_override: str | None = None,
    supports_vision: bool | None = None,
    image_input_policy: str | None = None,
    structured_output_method: str | None = None,
) -> LangChainStructuredLLM:
    """按模型配置名称创建 OpenAI-compatible LLM 实例。"""

    import httpx

    config = get_llm_model_config(model_name)
    if model_override is not None:
        config.model = model_override
    if supports_vision is not None:
        config.capabilities.supports_vision = supports_vision
    if image_input_policy is not None:
        config.image_input_policy = image_input_policy  # type: ignore[assignment]
    if structured_output_method is not None:
        config.structured_output_method = structured_output_method  # type: ignore[assignment]

    # 显式关闭环境代理，保持和原本自部署模型调用行为一致。
    http_client = httpx.Client(proxy=None, trust_env=False)
    http_async_client = httpx.AsyncClient(proxy=None, trust_env=False)

    print(
        f"Create LLM: name={model_name}, base_url={config.base_url}, "
        f"model={config.model}, method={config.structured_output_method}"
    )

    chat_model = ChatOpenAI(
        base_url=normalize_openai_base_url(config.base_url),
        api_key=SecretStr(config.api_key),
        model=config.model,
        default_headers=config.default_headers or None,
        extra_body=config.extra_body or None,
        http_client=http_client,
        http_async_client=http_async_client,
    )

    return LangChainStructuredLLM(
        chat_model,
        model_name=model_name,
        config=config,
    )


def normalize_openai_base_url(base_url: str) -> str:
    """把 /chat/completions 端点转换为 OpenAI client 需要的 base_url。"""

    value = base_url.rstrip("/")
    suffix = "/chat/completions"
    if value.endswith(suffix):
        return value[: -len(suffix)]
    return value


def _contains_image_content(value: Any) -> bool:
    """递归判断 messages 中是否包含 image_url 内容块。"""

    if isinstance(value, dict):
        if value.get("type") == "image_url":
            return True
        return any(_contains_image_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_image_content(item) for item in value)
    return False


def _drop_image_content(message: Any) -> Any:
    """从单条 message 中移除 image_url 内容块。"""

    if not isinstance(message, dict):
        return message

    content = message.get("content")
    if not isinstance(content, list):
        return message

    return {
        **message,
        "content": [
            item
            for item in content
            if not (isinstance(item, dict) and item.get("type") == "image_url")
        ],
    }
