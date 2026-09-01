from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from backend.app.models.provider import (
    ChatModelResponse,
    ChatToolCall,
    tool_declarations,
)


class GeminiModel:
    provider_name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.1-flash-lite",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key.strip():
            raise ValueError("NEXUS_GEMINI_API_KEY is required for the Gemini provider")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.client = client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[object],
    ) -> ChatModelResponse:
        payload = self._payload(messages, tools)
        endpoint = f"{self.base_url}/models/{quote(self.model, safe='')}:generateContent"
        if self.client:
            response = await self.client.post(
                endpoint,
                headers={"x-goog-api-key": self.api_key},
                json=payload,
            )
        else:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    endpoint,
                    headers={"x-goog-api-key": self.api_key},
                    json=payload,
                )
        response.raise_for_status()
        return self._parse(response.json())

    @staticmethod
    def _payload(messages: list[dict[str, Any]], tools: list[object]) -> dict[str, Any]:
        system_parts = [
            {"text": message["content"]}
            for message in messages
            if message["role"] == "system"
        ]
        contents: list[dict[str, Any]] = []

        for message in messages:
            role = message["role"]
            if role == "system":
                continue
            if role == "tool":
                contents.append({
                    "role": "user",
                    "parts": [{
                        "functionResponse": {
                            "name": message["tool_name"],
                            "response": {"result": message.get("content", "")},
                        }
                    }],
                })
                continue

            parts = GeminiModel._content_parts(message.get("content"))
            for tool_call in message.get("tool_calls", []):
                parts.append({
                    "functionCall": {
                        "name": tool_call["name"],
                        "args": tool_call.get("arguments", {}),
                    }
                })
            if parts:
                contents.append({
                    "role": "model" if role == "assistant" else "user",
                    "parts": parts,
                })

        payload: dict[str, Any] = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        if tools:
            payload["tools"] = [{"functionDeclarations": tool_declarations(tools)}]
        return payload

    @staticmethod
    def _content_parts(content: Any) -> list[dict[str, Any]]:
        if isinstance(content, str):
            return [{"text": content}] if content else []
        parts = []
        for item in content or []:
            if item.get("type") == "text" and item.get("text"):
                parts.append({"text": item["text"]})
            elif item.get("type") == "image" and item.get("data"):
                parts.append({
                    "inlineData": {
                        "mimeType": item.get("mime_type", "image/jpeg"),
                        "data": item["data"],
                    }
                })
        return parts

    @staticmethod
    def _parse(data: dict[str, Any]) -> ChatModelResponse:
        candidates = data.get("candidates") or []
        if not candidates:
            feedback = data.get("promptFeedback", {})
            raise RuntimeError(
                f"Gemini returned no response: {feedback.get('blockReason', 'unknown reason')}"
            )

        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts)
        calls = [
            ChatToolCall(
                name=part["functionCall"]["name"],
                arguments=part["functionCall"].get("args", {}),
            )
            for part in parts
            if "functionCall" in part
        ]
        return ChatModelResponse(content=text, tool_calls=calls)
