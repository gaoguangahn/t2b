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


def _inline_references(schema: dict[str, Any], model_name: str) -> dict[str, Any]:
    """Avoid relying on gateways to resolve $ref at array items or union branches."""
    def expand(node: dict, path: str, active: tuple[str, ...]) -> dict:
        if "$ref" in node:
            reference = node["$ref"]
            if reference in active:
                raise ModelSchemaError(f"{model_name} {path}: recursive references cannot be inlined")
            if reference != "#" and not reference.startswith("#/"):
                raise ModelSchemaError(f"{model_name} {path}: only local schema references are supported")
            target = schema
            try:
                for key in reference[2:].split("/") if reference != "#" else []:
                    target = target[key.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError) as error:
                raise ModelSchemaError(f"{model_name} {path}: unknown schema reference {reference}") from error
            base = expand(target, path, (*active, reference))
            siblings = expand({key: value for key, value in node.items() if key != "$ref"}, path, active)
            for key, value in siblings.items():
                if key in base and key not in {"title", "description"} and base[key] != value:
                    raise ModelSchemaError(f"{model_name} {path}: conflicting reference sibling {key}")
            return {**base, **siblings}
        result = {key: deepcopy(value) for key, value in node.items() if key != "$defs"}
        if "properties" in result:
            result["properties"] = {key: expand(value, f"{path}.properties.{key}", active)
                                    for key, value in result["properties"].items()}
        if isinstance(result.get("items"), dict):
            result["items"] = expand(result["items"], f"{path}.items", active)
        if "anyOf" in result:
            result["anyOf"] = [expand(value, f"{path}.anyOf[{index}]", active)
                               for index, value in enumerate(result["anyOf"])]
        return result

    return expand(schema, "$", ())


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Require every declared key; reject open maps instead of dropping their data."""
    schema = _inline_references(deepcopy(model.model_json_schema()), model.__name__)

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
        if isinstance(node.get("items"), dict):
            convert(node["items"], f"{path}.items")
        for index, child in enumerate(node.get("anyOf", [])):
            convert(child, f"{path}.anyOf[{index}]")

    convert(schema, "$")
    validate_strict_schema(schema)
    return schema


def validate_strict_schema(schema: dict[str, Any]) -> None:
    """Check the explicit, reference-free schema actually sent to model gateways."""
    if schema.get("type") != "object" or "anyOf" in schema:
        raise ModelSchemaError("$: root schema must be an object")

    def visit(node: dict, path: str):
        if _UNSUPPORTED.intersection(node) or "default" in node:
            raise ModelSchemaError(f"{path}: unsupported schema keyword")
        if "$ref" in node or "$defs" in node:
            raise ModelSchemaError(f"{path}: wire schema must inline references")
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
        if "items" in node:
            if not isinstance(node["items"], dict):
                raise ModelSchemaError(f"{path}: array items must be a schema")
            if "type" not in node["items"] and "anyOf" not in node["items"]:
                raise ModelSchemaError(f"{path}.items: array item must declare a type or typed union")
            visit(node["items"], f"{path}.items")
        if not any(key in node for key in ("type", "anyOf", "enum")):
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
