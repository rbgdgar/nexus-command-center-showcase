from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from types import UnionType
from typing import Any, Protocol, Union, get_args, get_origin, get_type_hints


@dataclass
class ChatToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatModelResponse:
    content: str = ""
    tool_calls: list[ChatToolCall] = field(default_factory=list)


class ChatModel(Protocol):
    provider_name: str
    model: str

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[object],
    ) -> ChatModelResponse: ...


def tool_declarations(tools: list[object]) -> list[dict[str, Any]]:
    return [_tool_declaration(tool) for tool in tools]


def _tool_declaration(tool: object) -> dict[str, Any]:
    custom_schema = getattr(tool, "__nexus_tool_schema__", None)
    if custom_schema:
        return {
            "name": getattr(tool, "__name__", tool.__class__.__name__),
            "description": inspect.getdoc(tool) or "NEXUS tool",
            "parameters": _normalize_schema(custom_schema),
        }
    signature = inspect.signature(tool)
    try:
        type_hints = get_type_hints(tool)
    except (NameError, TypeError):
        type_hints = {}
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, parameter in signature.parameters.items():
        properties[name] = _annotation_schema(type_hints.get(name, parameter.annotation))
        if parameter.default is inspect.Parameter.empty:
            required.append(name)

    parameters: dict[str, Any] = {
        "type": "OBJECT",
        "properties": properties,
    }
    if required:
        parameters["required"] = required

    return {
        "name": getattr(tool, "__name__", tool.__class__.__name__),
        "description": inspect.getdoc(tool) or "NEXUS tool",
        "parameters": parameters,
    }


def _normalize_schema(schema: Any) -> Any:
    if isinstance(schema, list):
        return [_normalize_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    normalized = {
        key: _normalize_schema(value)
        for key, value in schema.items()
        if key != "$schema"
    }
    if isinstance(normalized.get("type"), str):
        normalized["type"] = normalized["type"].upper()
    return normalized


def _annotation_schema(annotation: object) -> dict[str, Any]:
    if annotation is inspect.Parameter.empty:
        return {"type": "STRING"}

    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in {Union, UnionType}:
        non_null = [item for item in args if item is not type(None)]
        return _annotation_schema(non_null[0]) if non_null else {"type": "STRING"}
    if origin in {list, tuple, set}:
        item_type = args[0] if args else str
        return {"type": "ARRAY", "items": _annotation_schema(item_type)}
    if origin is dict:
        return {"type": "OBJECT"}
    if annotation is bool:
        return {"type": "BOOLEAN"}
    if annotation is int:
        return {"type": "INTEGER"}
    if annotation is float:
        return {"type": "NUMBER"}
    if annotation is Path:
        return {"type": "STRING"}
    return {"type": "STRING"}
