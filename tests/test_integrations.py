import json
import unittest

import httpx

from backend.app.integrations.github import GitHubProvider
from backend.app.integrations.mcp import MCPAdapter, MCPServerConfig
from backend.app.security.safety import RiskLevel, ToolRegistry


class IntegrationTests(unittest.TestCase):
    def test_mcp_registration_and_status(self):
        adapter = MCPAdapter()
        adapter.load_json(json.dumps([
            {"name": "github", "transport": "http", "endpoint": "http://localhost:9000"}
        ]))
        status = adapter.status()
        self.assertEqual(status[0]["name"], "github")
        self.assertEqual(status[0]["status"], "configured")
        with self.assertRaises(ValueError):
            adapter.register(MCPServerConfig("bad", "shell", "command"))

    def test_mcp_discovery_call_and_safety_registration(self):
        calls = []

        def handler(request):
            payload = json.loads(request.content)
            calls.append((payload["method"], request.headers))
            if payload["method"] == "initialize":
                return httpx.Response(200, headers={"content-type": "application/json"}, json={
                    "jsonrpc": "2.0", "id": 1,
                    "result": {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}},
                })
            if payload["method"] == "notifications/initialized":
                return httpx.Response(202)
            if payload["method"] == "tools/list":
                return httpx.Response(200, headers={"content-type": "application/json"}, json={
                    "jsonrpc": "2.0", "id": 2, "result": {"tools": [
                        {"name": "lookup", "description": "Safe lookup", "inputSchema": {
                            "type": "object", "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        }},
                        {"name": "not_allowed", "inputSchema": {"type": "object"}},
                    ]},
                })
            return httpx.Response(200, headers={"content-type": "application/json"}, json={
                "jsonrpc": "2.0", "id": 100,
                "result": {"content": [{"type": "text", "text": "answer"}]},
            })

        client = httpx.Client(transport=httpx.MockTransport(handler))
        adapter = MCPAdapter(client)
        adapter.register(MCPServerConfig(
            "docs", "streamable_http", "https://example.com/mcp",
            allowed_tools=("lookup",),
        ))
        registry = ToolRegistry()
        status = adapter.refresh("docs", registry)

        self.assertEqual(status["status"], "online")
        self.assertEqual(status["tool_count"], 1)
        definition = registry.get("mcp_docs_lookup")
        self.assertEqual(definition.risk_level, RiskLevel.READ_ONLY)
        self.assertEqual(definition.function(query="NEXUS")["content"][0]["text"], "answer")
        self.assertEqual(calls[-1][1]["mcp-protocol-version"], "2025-11-25")

    def test_mcp_rejects_unsafe_endpoints_and_unlisted_calls(self):
        adapter = MCPAdapter()
        with self.assertRaises(ValueError):
            adapter.register(MCPServerConfig("bad", "http", "http://example.com/mcp"))
        with self.assertRaises(ValueError):
            adapter.register(MCPServerConfig("bad", "http", "https://user:secret@example.com/mcp"))

    def test_github_read_only_resources(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"ok": True})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = GitHubProvider(token="test-token", client=client)
        self.assertEqual(provider.repository("openai/codex"), {"ok": True})
        self.assertTrue(requests[0].url.path.endswith("/repos/openai/codex"))
        self.assertEqual(requests[0].headers["authorization"], "Bearer test-token")
        self.assertEqual(provider.status("openai/codex")["mode"], "read-only")

    def test_repository_validation(self):
        provider = GitHubProvider(client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))))
        with self.assertRaises(ValueError):
            provider.repository("invalid")


if __name__ == "__main__":
    unittest.main()
