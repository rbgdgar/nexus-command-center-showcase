from __future__ import annotations

from typing import Any

from backend.app.core.logging import log_event
from backend.app.models.provider import ChatModelResponse


class FallbackChatModel:
    provider_name = "router"

    def __init__(self, clients: list[object]):
        if not clients:
            raise ValueError("At least one model client is required")
        self.clients = clients
        self.model = clients[0].model
        self.active_provider = clients[0].provider_name
        self.active_model = clients[0].model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[object],
    ) -> ChatModelResponse:
        failures = []
        for client in self.clients:
            try:
                response = await client.chat(messages, tools)
                self.active_provider = client.provider_name
                self.active_model = client.model
                return response
            except Exception as error:
                failures.append(f"{client.provider_name}:{client.model}: {error}")
                log_event(
                    "model_fallback",
                    provider=client.provider_name,
                    model=client.model,
                    error=str(error),
                )
        raise RuntimeError("All configured model providers failed: " + " | ".join(failures))
