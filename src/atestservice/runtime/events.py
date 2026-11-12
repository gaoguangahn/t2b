"""Agent runtime event publishing interfaces."""

from __future__ import annotations

from typing import Any, Protocol


class AgentEventPublisher(Protocol):
    """Publish lightweight agent progress events."""

    async def node_started(self, *, stage: str, node: str, label: str) -> None: ...

    async def node_finished(
        self,
        *,
        stage: str,
        node: str,
        payload: dict[str, Any],
    ) -> None: ...

    async def node_failed(
        self,
        *,
        stage: str,
        node: str,
        message: str,
    ) -> None: ...


class NoopAgentEventPublisher:
    """Drop agent progress events."""

    async def node_started(self, *, stage: str, node: str, label: str) -> None:
        return None

    async def node_finished(
        self,
        *,
        stage: str,
        node: str,
        payload: dict[str, Any],
    ) -> None:
        return None

    async def node_failed(
        self,
        *,
        stage: str,
        node: str,
        message: str,
    ) -> None:
        return None
