"""Summarize response transport without logging prompts, arguments or reasoning."""
import json


def _argument_state(arguments):
    if arguments is None:
        return "null"
    if arguments == "":
        return "empty_string"
    try:
        value = json.loads(arguments) if isinstance(arguments, str) else arguments
    except (ValueError, TypeError):
        return "invalid_json"
    if isinstance(value, dict):
        return "empty_object" if not value else "object"
    return type(value).__name__


def response_summary(raw):
    metadata = getattr(raw, "response_metadata", {}) or {}
    extra = getattr(raw, "additional_kwargs", {}) or {}
    tools = []
    for call in extra.get("tool_calls") or []:
        function = call.get("function") or {}
        tools.append({"name": function.get("name"), "arguments_state": _argument_state(function.get("arguments")),
                      "arguments_source": "raw"})
    if not tools:
        # Current LangChain versions discard the original string for valid tool
        # JSON. In particular, an empty string and '{}' both become parsed {}.
        # Label this limitation rather than inventing an original response.
        for call in getattr(raw, "tool_calls", []) or []:
            tools.append({"name": call.get("name"), "arguments_state": _argument_state(call.get("args")),
                          "arguments_source": "parsed"})
        for call in getattr(raw, "invalid_tool_calls", []) or []:
            tools.append({"name": call.get("name"), "arguments_state": _argument_state(call.get("args")),
                          "arguments_source": "raw_invalid"})
    usage = getattr(raw, "usage_metadata", {}) or {}
    return {"finish_reason": metadata.get("finish_reason"),
            "usage": {key: usage[key] for key in ("input_tokens", "output_tokens", "total_tokens") if key in usage},
            "tool_calls": tools,
            "content_present": bool(getattr(raw, "content", None))}
