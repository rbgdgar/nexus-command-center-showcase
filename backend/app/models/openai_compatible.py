from __future__ import annotations

import json
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

import httpx

from backend.app.models.provider import (
    ChatModelResponse,
    ChatToolCall,
    tool_declarations,
)


def _lower_schema_types(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: item.lower() if key == "type" and isinstance(item, str)
            else _lower_schema_types(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_lower_schema_types(item) for item in value]
    return value


class OpenAICompatibleModel:
    """Chat-completions adapter for OpenAI, OpenRouter, Groq, and compatible APIs."""

    def __init__(
        self,
        provider_name: str,
        model: str,
        base_url: str,
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        if not provider_name.strip():
            raise ValueError("Provider name is required")
        if not model.strip():
            raise ValueError("Model name is required")
        parsed_url = urlsplit(base_url)
        secure_remote = parsed_url.scheme == "https" and bool(parsed_url.hostname)
        loopback = parsed_url.scheme == "http" and parsed_url.hostname in {
            "127.0.0.1", "::1", "localhost",
        }
        if not (secure_remote or loopback):
            raise ValueError("Compatible API must use HTTPS or a loopback HTTP URL")
        self.provider_name = provider_name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = headers or {}
        self.client = client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[object],
    ) -> ChatModelResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(messages),
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": _lower_schema_types(declaration)}
                for declaration in tool_declarations(tools)
            ]
        headers = {"Content-Type": "application/json", **self.headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        endpoint = f"{self.base_url}/chat/completions"
        if self.client:
            response = await self.client.post(endpoint, headers=headers, json=payload)
        else:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        return self._parse(response.json())

    @staticmethod
    def _messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        pending_calls: list[tuple[str, str]] = []
        for message_index, message in enumerate(messages):
            role = message["role"]
            if role == "assistant":
                item = {"role": role, "content": message.get("content") or None}
                calls = []
                for call_index, call in enumerate(message.get("tool_calls", [])):
                    call_id = f"call_{message_index}_{call_index}"
                    pending_calls.append((call["name"], call_id))
                    calls.append({
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call.get("arguments", {})),
                        },
                    })
                if calls:
                    item["tool_calls"] = calls
                converted.append(item)
            elif role == "tool":
                tool_name = message["tool_name"]
                match = next(
                    ((index, call_id) for index, (name, call_id) in enumerate(pending_calls)
                     if name == tool_name),
                    None,
                )
                if not match:
                    continue
                index, call_id = match
                pending_calls.pop(index)
                converted.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": message.get("content", ""),
                })
            else:
                converted.append({
                    "role": role,
                    "content": OpenAICompatibleModel._content(message.get("content", "")),
                })
        return converted

    @staticmethod
    def _content(content: Any) -> Any:
        if not isinstance(content, list):
            return deepcopy(content)
        converted = []
        for item in content:
            if item.get("type") == "text":
                converted.append({"type": "text", "text": item.get("text", "")})
            elif item.get("type") == "image" and item.get("data"):
                mime_type = item.get("mime_type", "image/jpeg")
                converted.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{item['data']}"},
                })
        return converted

    @staticmethod
    def _parse(data: dict[str, Any]) -> ChatModelResponse:
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("Compatible model returned no choices")
        message = choices[0].get("message", {})
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            arguments = function.get("arguments") or "{}"
            try:
                parsed_arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
            except json.JSONDecodeError:
                parsed_arguments = {}
            calls.append(ChatToolCall(
                name=function.get("name", ""),
                arguments=parsed_arguments if isinstance(parsed_arguments, dict) else {},
            ))
        return ChatModelResponse(content=str(content), tool_calls=calls)
