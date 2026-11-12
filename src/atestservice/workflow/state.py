"""Only serializable stage boundaries belong to the graph state."""
from typing import Any, TypedDict

class MobileAgentState(TypedDict, total=False):
    request: dict[str, Any]
    case_spec: dict[str, Any] | None
    exploration_result: dict[str, Any]
    run: dict[str, Any]
    result: dict[str, Any]
    framework: str
