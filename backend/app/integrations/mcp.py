from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.app.security.safety import RiskLevel, ToolDefinition, ToolRegistry


PROTOCOL_VERSION = "2025-11-25"
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
DESTRUCTIVE_WORDS = {"delete", "destroy", "drop", "erase", "purge", "remove"}


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: str
    endpoint: str
    enabled: bool = True
    auth_env: str | None = None
    read_only: bool = True
    allowed_tools: tuple[str, ...] = field(default_factory=tuple)


class MCPAdapter:
    """Minimal MCP Streamable HTTP client with an explicit safety boundary."""

    def __init__(self, client: httpx.Client | None = None):
        self.client = client
        self._servers: dict[str, MCPServerConfig] = {}
        self._sessions: dict[str, str] = {}
        self._protocols: dict[str, str] = {}
        self._tools: dict[str, list[dict[str, Any]]] = {}
        self._functions: dict[str, object] = {}
        self._errors: dict[str, str] = {}

    def register(self, config: MCPServerConfig):
        if config.transport not in {"http", "streamable_http"}:
            raise ValueError("Only MCP Streamable HTTP transport is supported")
        if not SAFE_NAME.fullmatch(config.name):
            raise ValueError("MCP server name must use letters, numbers, dots, dashes, or underscores")
        self._validate_endpoint(config.endpoint)
        if config.auth_env and not ENV_NAME.fullmatch(config.auth_env):
            raise ValueError("MCP authentication must reference a valid environment variable")
        for tool in config.allowed_tools:
            if not SAFE_NAME.fullmatch(tool):
                raise ValueError(f"Invalid MCP tool allowlist entry: {tool}")
        self._servers[config.name] = config

    def load_json(self, value: str):
        decoded = json.loads(value or "[]")
        if not isinstance(decoded, list):
            raise ValueError("NEXUS_MCP_SERVERS must be a JSON list")
        for item in decoded:
            if not isinstance(item, dict):
                raise ValueError("Each MCP server configuration must be an object")
            item = dict(item)
            item["allowed_tools"] = tuple(item.get("allowed_tools") or ())
            self.register(MCPServerConfig(**item))

    def status(self) -> list[dict]:
        results = []
        for server in self._servers.values():
            item = asdict(server)
            item["allowed_tools"] = list(server.allowed_tools)
            item["auth_configured"] = not server.auth_env or bool(os.getenv(server.auth_env))
            item["status"] = self._status(server)
            item["protocol_version"] = self._protocols.get(server.name)
            item["tool_count"] = len(self._tools.get(server.name, []))
            item["tools"] = self._tools.get(server.name, [])
            item["last_error"] = self._errors.get(server.name)
            results.append(item)
        return results

    def refresh(self, server_name: str, registry: ToolRegistry | None = None) -> dict:
        server = self._server(server_name)
        if not server.enabled:
            raise ValueError("MCP server is disabled")
        try:
            with self._client_context() as client:
                initialized = self._rpc(client, server, 1, "initialize", {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "nexus-command-center", "version": "2.0.0"},
                }, initializing=True)
                protocol = initialized.get("protocolVersion", PROTOCOL_VERSION)
                self._protocols[server.name] = protocol
                self._notify(client, server, "notifications/initialized")
                discovered: list[dict[str, Any]] = []
                cursor = None
                for request_id in range(2, 12):
                    params = {"cursor": cursor} if cursor else {}
                    page = self._rpc(client, server, request_id, "tools/list", params)
                    discovered.extend(page.get("tools") or [])
                    cursor = page.get("nextCursor")
                    if not cursor:
                        break
            filtered = [
                self._public_tool(server, tool)
                for tool in discovered
                if self._allowed(server, tool.get("name", ""))
            ]
            self._tools[server.name] = filtered
            self._errors.pop(server.name, None)
            if registry:
                self._register_functions(server, discovered, registry)
            return next(item for item in self.status() if item["name"] == server.name)
        except Exception as error:
            self._errors[server.name] = str(error)[:500]
            raise

    def call(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> dict:
        server = self._server(server_name)
        if not self._allowed(server, tool_name):
            raise ValueError("MCP tool is not in the configured allowlist")
        if not any(item.get("name") == tool_name for item in self._tools.get(server.name, [])):
            raise ValueError("MCP tool has not been discovered; refresh the connector first")
        with self._client_context() as client:
            return self._rpc(client, server, 100, "tools/call", {
                "name": tool_name, "arguments": arguments,
            })

    def tool_functions(self) -> list[object]:
        return list(self._functions.values())

    def nexus_tool_name(self, server_name: str, tool_name: str) -> str:
        return self._nexus_name(server_name, tool_name)

    def _register_functions(self, server: MCPServerConfig, tools: list[dict], registry: ToolRegistry):
        for tool in tools:
            remote_name = tool.get("name", "")
            if not self._allowed(server, remote_name):
                continue
            nexus_name = self._nexus_name(server.name, remote_name)

            def remote_function(_server=server.name, _tool=remote_name, **arguments):
                return self.call(_server, _tool, arguments)

            remote_function.__name__ = nexus_name
            remote_function.__doc__ = tool.get("description") or f"Call {remote_name} on {server.name} MCP"
            remote_function.__nexus_tool_schema__ = tool.get("inputSchema") or {
                "type": "object", "properties": {},
            }
            risk = self._risk(server, remote_name)
            registry.register(ToolDefinition(
                name=nexus_name,
                category=f"mcp:{server.name}",
                risk_level=risk,
                writes=risk != RiskLevel.READ_ONLY,
                approval_required=risk != RiskLevel.READ_ONLY,
                function=remote_function,
            ))
            self._functions[nexus_name] = remote_function

    def _rpc(self, client, server, request_id, method, params, initializing=False):
        response = self._post(client, server, {
            "jsonrpc": "2.0", "id": request_id, "method": method, "params": params,
        }, initializing=initializing)
        payload = self._decode(response, request_id)
        if "error" in payload:
            error = payload["error"]
            raise RuntimeError(f"MCP {method} failed: {error.get('message', error)}")
        return payload.get("result") or {}

    def _notify(self, client, server, method):
        self._post(client, server, {"jsonrpc": "2.0", "method": method})

    def _post(self, client, server, payload, initializing=False):
        response = client.post(
            server.endpoint, json=payload, headers=self._headers(server, initializing)
        )
        response.raise_for_status()
        session = response.headers.get("mcp-session-id")
        if session:
            self._sessions[server.name] = session
        return response

    def _headers(self, server, initializing):
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if server.auth_env:
            token = os.getenv(server.auth_env)
            if not token:
                raise ValueError(f"MCP secret {server.auth_env} is not configured")
            headers["Authorization"] = f"Bearer {token}"
        if not initializing:
            headers["MCP-Protocol-Version"] = self._protocols.get(server.name, PROTOCOL_VERSION)
            if self._sessions.get(server.name):
                headers["Mcp-Session-Id"] = self._sessions[server.name]
        if server.read_only and urlparse(server.endpoint).hostname == "api.githubcopilot.com":
            headers["X-MCP-Readonly"] = "true"
        return headers

    @staticmethod
    def _decode(response: httpx.Response, request_id: int) -> dict:
        if "text/event-stream" not in response.headers.get("content-type", ""):
            return response.json()
        messages = []
        for line in response.text.splitlines():
            if line.startswith("data:"):
                messages.append(json.loads(line.partition(":")[2].strip()))
        for message in messages:
            if message.get("id") == request_id:
                return message
        raise RuntimeError("MCP server returned no matching JSON-RPC response")

    def _client_context(self):
        if self.client:
            return _BorrowedClient(self.client)
        return httpx.Client(timeout=30.0, follow_redirects=False)

    def _server(self, name):
        server = self._servers.get(name)
        if not server:
            raise ValueError("Unknown MCP server")
        return server

    @staticmethod
    def _allowed(server, tool_name):
        return bool(tool_name) and tool_name in server.allowed_tools

    @staticmethod
    def _risk(server, tool_name):
        words = set(re.split(r"[._-]", tool_name.lower()))
        if words & DESTRUCTIVE_WORDS:
            return RiskLevel.DESTRUCTIVE
        return RiskLevel.READ_ONLY if server.read_only else RiskLevel.SAFE_WRITE

    @staticmethod
    def _nexus_name(server, tool):
        value = re.sub(r"[^A-Za-z0-9_]", "_", f"mcp_{server}_{tool}")
        return value[:128]

    @staticmethod
    def _public_tool(server, tool):
        name = tool.get("name", "")
        return {
            "name": name,
            "nexus_name": MCPAdapter._nexus_name(server.name, name),
            "description": tool.get("description", ""),
            "risk_level": MCPAdapter._risk(server, name).value,
            "input_schema": tool.get("inputSchema") or {},
        }

    @staticmethod
    def _validate_endpoint(endpoint):
        parsed = urlparse(endpoint)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
            raise ValueError("Remote MCP endpoints must use HTTPS; HTTP is loopback-only")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("MCP endpoints cannot contain credentials, query strings, or fragments")

    def _status(self, server):
        if not server.enabled:
            return "disabled"
        if server.auth_env and not os.getenv(server.auth_env):
            return "needs_secret"
        if server.name in self._errors:
            return "error"
        return "online" if server.name in self._tools else "configured"


class _BorrowedClient:
    def __init__(self, client): self.client = client
    def __enter__(self): return self.client
    def __exit__(self, *_): return False


mcp_adapter = MCPAdapter()
