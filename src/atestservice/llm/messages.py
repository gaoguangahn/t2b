"""OpenAI-compatible 文本/图片消息构造工具。

本模块只理解 LLM 消息块，不解析 agent 的业务状态对象。例如 snapshot 如何转换成
base64 图片块，仍由 agent/context.py 负责。
"""

from __future__ import annotations

from typing import Any

from atestservice.llm.types import LLMCapabilities


def text_content(text: str) -> dict[str, str]:
    """构造 OpenAI 多模态 content 中的文本块。"""

    return {"type": "text", "text": text}


def image_content_from_base64(
    data: str, *, media_type: str = "image/jpeg"
) -> dict[str, Any]:
    """构造 OpenAI image_url 图片块。"""

    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type};base64,{data}"},
    }


class MessageBuilder:
    """用于构建单条 user message 的轻量工具。"""

    def __init__(
        self,
        *,
        capabilities: LLMCapabilities | None = None,
        image_policy: str = "error",
    ):
        self._capabilities = capabilities
        self._image_policy = image_policy
        self._content: list[dict[str, Any]] = []
        self.dropped_images = 0

    def text(self, text: str) -> MessageBuilder:
        """追加文本块；空文本会被忽略。"""

        if text:
            self._content.append(text_content(text))
        return self

    def image(
        self, image: dict[str, Any] | None, *, label: str | None = None
    ) -> MessageBuilder:
        """追加图片块，可选在图片前追加说明文本。"""

        if image is None:
            return self

        # 这里不解析图片来源，只根据当前模型能力决定是否允许发送图片块。
        if not self._can_send_images():
            if self._image_policy == "drop":
                self.dropped_images += 1
                return self
            raise ValueError(
                "Current LLM provider does not support image input. "
                "Use a vision-capable provider or set image_policy='drop'."
            )

        if label:
            self.text(label)
        self._content.append(image)
        return self

    def build_content(self) -> list[dict[str, Any]]:
        """返回 OpenAI user message 的 content 数组。"""

        return list(self._content)

    def build(self) -> list[dict[str, Any]]:
        """返回 Chat Completions messages 数组。"""

        return [{"role": "user", "content": self.build_content()}]

    def _can_send_images(self) -> bool:
        return self._capabilities is None or self._capabilities.supports_vision


def build_user_message(
    *,
    text: str,
    images: list[dict[str, Any] | None] | None = None,
    capabilities: LLMCapabilities | None = None,
    image_policy: str = "error",
) -> list[dict[str, Any]]:
    """快捷构造包含文本和多张图片的 user message。"""

    builder = MessageBuilder(capabilities=capabilities, image_policy=image_policy).text(
        text
    )
    for image in images or []:
        builder.image(image)
    return builder.build()
