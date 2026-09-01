from typing import Any

from ollama import AsyncClient

from backend.app.models.provider import ChatModelResponse, ChatToolCall


class OllamaModel:
    provider_name = "ollama"

    def __init__(
        self,
        model: str = "qwen3:4b",
        base_url: str = "http://localhost:11434",
        client: AsyncClient | None = None,
    ):
        self.model = model
        self.base_url = base_url
        self.client = client or AsyncClient(host=base_url)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[object],
    ) -> ChatModelResponse:
        response = await self.client.chat(
            model=self.model,
            messages=self._messages(messages),
            tools=tools,
        )
        calls = [
            ChatToolCall(
                name=tool_call.function.name,
                arguments=tool_call.function.arguments or {},
            )
            for tool_call in (response.message.tool_calls or [])
        ]
        return ChatModelResponse(
            content=response.message.content or "",
            tool_calls=calls,
        )

    @staticmethod
    def _messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted = []
        for message in messages:
            item = {key: value for key, value in message.items() if key != "tool_calls"}
            if message.get("tool_calls"):
                item["tool_calls"] = [
                    {"function": {
                        "name": call["name"],
                        "arguments": call.get("arguments", {}),
                    }}
                    for call in message["tool_calls"]
                ]
            converted.append(item)
        return converted
