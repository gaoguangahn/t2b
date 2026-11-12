"""Explicit wire schemas, independent of SDK-specific Pydantic conversions."""
from copy import deepcopy
from typing import Any

from pydantic import BaseModel


class ModelSchemaError(ValueError):
    """The model-facing contract cannot be represented by strict structured output."""


_UNSUPPORTED = {
    "allOf", "oneOf", "not", "if", "then", "else", "dependentRequired",
    "dependentSchemas", "patternProperties", "propertyNames", "prefixItems",
    "unevaluatedProperties", "contains", "additionalItems",
    "uniqueItems",
}


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Require every declared key; reject open maps instead of dropping their data."""
    schema = deepcopy(model.model_json_schema())

    def convert(node: dict, path: str):
        unsupported = _UNSUPPORTED.intersection(node)
        if unsupported:
            raise ModelSchemaError(f"{model.__name__} {path}: unsupported keywords {sorted(unsupported)}")
        node.pop("default", None)
        if "const" in node:
            node["enum"] = [node.pop("const")]
        if node.get("type") == "object" or "properties" in node:
            if node.get("additionalProperties", False) is not False:
                raise ModelSchemaError(
                    f"{model.__name__} {path}: open dictionaries are unsupported; "
                    "use explicit fields or a name/value entry list in the model-facing contract"
                )
            properties = node.setdefault("properties", {})
            required = node.get("required", [])
            if not isinstance(required, list) or any(key not in properties for key in required):
                raise ModelSchemaError(f"{model.__name__} {path}: required contains undeclared properties")
            node["required"] = list(properties)
            node["additionalProperties"] = False
            for name, child in properties.items():
                convert(child, f"{path}.properties.{name}")
        for name, child in node.get("$defs", {}).items():
            convert(child, f"{path}.$defs.{name}")
        if isinstance(node.get("items"), dict):
            convert(node["items"], f"{path}.items")
        for index, child in enumerate(node.get("anyOf", [])):
            convert(child, f"{path}.anyOf[{index}]")

    convert(schema, "$")
    validate_strict_schema(schema)
    return schema


def validate_strict_schema(schema: dict[str, Any]) -> None:
    """Check the schema to be sent, including all nested objects and references."""
    if schema.get("type") != "object" or "anyOf" in schema:
        raise ModelSchemaError("$: root schema must be an object")

    def visit(node: dict, path: str):
        if _UNSUPPORTED.intersection(node) or "default" in node:
            raise ModelSchemaError(f"{path}: unsupported schema keyword")
        if node.get("type") == "object" or "properties" in node:
            properties = node.get("properties", {})
            required = node.get("required")
            if (not isinstance(required, list) or len(required) != len(set(required))
                    or set(required) != set(properties)):
                raise ModelSchemaError(f"{path}: required must include every property exactly once")
            if node.get("additionalProperties") is not False:
                raise ModelSchemaError(f"{path}: additionalProperties must be false")
            for key, value in properties.items():
                visit(value, f"{path}.properties.{key}")
        if "$ref" in node:
            reference = node["$ref"]
            if reference != "#" and not reference.startswith("#/"):
                raise ModelSchemaError(f"{path}: only local schema references are supported")
            target = schema
            try:
                for key in reference[2:].split("/") if reference != "#" else []:
                    target = target[key.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError) as error:
                raise ModelSchemaError(f"{path}: unknown schema reference {reference}") from error
        for key, value in node.get("$defs", {}).items():
            visit(value, f"{path}.$defs.{key}")
        if "items" in node:
            if not isinstance(node["items"], dict):
                raise ModelSchemaError(f"{path}: array items must be a schema")
            visit(node["items"], f"{path}.items")
        if not any(key in node for key in ("type", "anyOf", "$ref", "enum")):
            raise ModelSchemaError(f"{path}: untyped values are unsupported")
        for index, value in enumerate(node.get("anyOf", [])):
            visit(value, f"{path}.anyOf[{index}]")

    visit(schema, "$")


def strict_tool(model: type[BaseModel]) -> dict[str, Any]:
    schema = strict_schema(model)
    return {"type": "function", "function": {
        "name": model.__name__, "description": schema.get("description", model.__name__),
        "strict": True, "parameters": schema,
    }}
