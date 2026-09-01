import copy
import unittest

import httpx

from backend.app.agents.nexus import NexusAgent
from backend.app.models.gemini import GeminiModel
from backend.app.models.catalog import ModelRegistry
from backend.app.models.openai_compatible import OpenAICompatibleModel
from backend.app.models.provider import ChatModelResponse, ChatToolCall
from backend.app.models.provider import tool_declarations
from backend.app.models.router import FallbackChatModel
from backend.app.core.config import Settings


def sample_tool(query: str, limit: int = 5) -> dict:
    """Search a bounded test index."""
    return {"query": query, "limit": limit}


class FakeModel:
    provider_name = "fake"
    model = "fake-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def chat(self, messages, tools):
        self.requests.append((copy.deepcopy(messages), tools))
        return self.responses.pop(0)


class FailingModel:
    provider_name = "failing"
    model = "failed-model"

    async def chat(self, messages, tools):
        raise RuntimeError("temporary provider failure")


class ModelProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_remote_tool_schema_removes_dialect_metadata(self):
        def remote_tool(**arguments):
            return arguments

        remote_tool.__nexus_tool_schema__ = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        declaration = tool_declarations([remote_tool])[0]
        self.assertNotIn("$schema", declaration["parameters"])
        self.assertEqual(declaration["parameters"]["type"], "OBJECT")
        self.assertEqual(declaration["parameters"]["properties"]["query"]["type"], "STRING")

    async def test_gemini_text_request(self):
        captured = []

        def handler(request):
            captured.append(request)
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{"text": "online"}]}}]
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model = GeminiModel("secret", model="gemini-test", client=client)
            response = await model.chat([
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Status?"},
            ], [sample_tool])

        self.assertEqual(response.content, "online")
        self.assertEqual(captured[0].headers["x-goog-api-key"], "secret")
        payload = __import__("json").loads(captured[0].content)
        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "Be concise.")
        declaration = payload["tools"][0]["functionDeclarations"][0]
        self.assertEqual(declaration["name"], "sample_tool")
        self.assertEqual(declaration["parameters"]["required"], ["query"])

    async def test_gemini_function_call_and_result_mapping(self):
        payloads = []

        def handler(request):
            payloads.append(__import__("json").loads(request.content))
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{
                    "functionCall": {"name": "sample_tool", "args": {"query": "nexus"}}
                }]}}]
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model = GeminiModel("secret", client=client)
            response = await model.chat([
                {"role": "user", "content": "Search"},
                {"role": "assistant", "content": "", "tool_calls": [
                    {"name": "sample_tool", "arguments": {"query": "nexus"}}
                ]},
                {"role": "tool", "tool_name": "sample_tool", "content": "{'ok': True}"},
            ], [sample_tool])

        self.assertEqual(response.tool_calls[0].name, "sample_tool")
        function_response = payloads[0]["contents"][-1]["parts"][0]["functionResponse"]
        self.assertEqual(function_response["name"], "sample_tool")

    async def test_gemini_multimodal_image_mapping(self):
        payloads = []

        def handler(request):
            payloads.append(__import__("json").loads(request.content))
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{"text": "diagram text"}]}}]
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model = GeminiModel("secret", client=client)
            response = await model.chat([{"role": "user", "content": [
                {"type": "text", "text": "Extract text"},
                {"type": "image", "mime_type": "image/png", "data": "aW1hZ2U="},
            ]}], [])

        self.assertEqual(response.content, "diagram text")
        image_part = payloads[0]["contents"][0]["parts"][1]["inlineData"]
        self.assertEqual(image_part["mimeType"], "image/png")
        self.assertEqual(image_part["data"], "aW1hZ2U=")

    async def test_nexus_uses_normalized_provider_loop(self):
        model = FakeModel([
            ChatModelResponse(tool_calls=[ChatToolCall("missing_tool")]),
            ChatModelResponse(content="done"),
        ])
        agent = NexusAgent(model_client=model)
        result = await agent.run("test")

        self.assertEqual(result, "done")
        follow_up = model.requests[1][0]
        self.assertEqual(follow_up[-1]["role"], "tool")
        self.assertIn("not available", follow_up[-1]["content"])

    def test_gemini_requires_key(self):
        with self.assertRaises(ValueError):
            GeminiModel("")

    async def test_openai_compatible_chat_and_tools(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={
                "choices": [{"message": {
                    "content": "",
                    "tool_calls": [{"function": {
                        "name": "sample_tool",
                        "arguments": '{"query":"nexus","limit":2}',
                    }}],
                }}]
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model = OpenAICompatibleModel(
                "groq", "test-model", "https://api.example.test/v1", "secret", client=client
            )
            response = await model.chat(
                [{"role": "user", "content": "Search"}], [sample_tool]
            )

        self.assertEqual(response.tool_calls[0].arguments["limit"], 2)
        payload = __import__("json").loads(requests[0].content)
        self.assertEqual(payload["tools"][0]["function"]["parameters"]["type"], "object")
        self.assertEqual(requests[0].headers["authorization"], "Bearer secret")

    async def test_router_falls_back_to_working_model(self):
        working = FakeModel([ChatModelResponse(content="fallback worked")])
        router = FallbackChatModel([FailingModel(), working])

        response = await router.chat([{"role": "user", "content": "status"}], [])

        self.assertEqual(response.content, "fallback worked")
        self.assertEqual(router.active_provider, "fake")

    def test_catalog_is_free_first_and_paid_models_are_blocked(self):
        settings = Settings(
            _env_file=None,
            model_provider="gemini",
            gemini_api_key="secret",
            openai_api_key="paid-secret",
            allow_paid_models=False,
        )
        registry = ModelRegistry(settings)
        catalog = registry.public_catalog()

        self.assertTrue(catalog["free_first"])
        self.assertEqual(catalog["default_model"], "gemini-3.7-flash")
        paid = next(item for item in catalog["models"] if item["provider"] == "openai")
        self.assertFalse(paid["allowed"])
        self.assertEqual(paid["state"], "blocked")
        qwen = next(item for item in catalog["models"] if item["model"] == "qwen3.8:27b")
        self.assertEqual(qwen["cost_tier"], "local")
        self.assertIn(qwen["state"], {"ready", "setup_required"})
        with self.assertRaises(ValueError):
            registry.routed("openai", "gpt-5.6-luna")


if __name__ == "__main__":
    unittest.main()
