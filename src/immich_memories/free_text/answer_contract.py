"""The small field contracts used by free-text questions, even without server-side schemas."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any


def shape_hint(schema: Mapping[str, Any]) -> str:
    """State field types and limits; large option lists already live in the question."""

    def compact(value):
        if isinstance(value, dict):
            result = {key: compact(item) for key, item in value.items() if key != "enum"}
            if "enum" in value:
                if len(value["enum"]) <= 40:
                    result["enum"] = value["enum"]
                else:
                    result["description"] = "Use only values permitted by the question."
            return result
        return value

    return "Return only JSON matching this field contract: " + json.dumps(compact(dict(schema)))


def valid_answer(value: Any, schema: Mapping[str, Any]) -> bool:
    """Check the types and constraints emitted by this package's question builders."""
    kind = schema["type"]
    if isinstance(kind, list):
        return any(valid_answer(value, {**schema, "type": item}) for item in kind)
    if not _valid_type(value, kind):
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if kind == "object":
        fields = schema["properties"]
        return (
            set(schema.get("required", ())) <= value.keys()
            and (schema.get("additionalProperties", True) or value.keys() <= fields.keys())
            and all(valid_answer(item, fields[key]) for key, item in value.items() if key in fields)
        )
    if kind == "array":
        return len(value) <= schema.get("maxItems", len(value)) and all(
            valid_answer(item, schema["items"]) for item in value
        )
    if kind == "string":
        return len(value) <= schema.get("maxLength", len(value)) and (
            "pattern" not in schema or re.search(schema["pattern"], value) is not None
        )
    if kind == "integer":
        return schema.get("minimum", value) <= value <= schema.get("maximum", value)
    return True


def _valid_type(value: Any, kind: str) -> bool:
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if kind == "null":
        return value is None
    return kind in types and type(value) is types[kind]
