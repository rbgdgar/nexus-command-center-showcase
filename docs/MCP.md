# Remote MCP connectors

NEXUS V2.0 implements the MCP 2025-11-25 initialization lifecycle, Streamable
HTTP JSON-RPC, `tools/list`, and `tools/call`. It accepts JSON and server-sent
event responses and carries negotiated protocol and session headers.

The public OpenAI documentation server is configured by default and is refreshed
at application startup. Its five read-only tools are available to NEXUS and the
Research Agent after discovery.

## Online GitHub connector

The official hosted GitHub MCP endpoint is `https://api.githubcopilot.com/mcp/`.
The example configuration selects its repository-only, read-only route:

```json
{
  "name": "github",
  "transport": "streamable_http",
  "endpoint": "https://api.githubcopilot.com/mcp/x/repos/readonly",
  "auth_env": "NEXUS_GITHUB_TOKEN",
  "read_only": true,
  "allowed_tools": ["get_file_contents", "search_code", "list_branches", "get_commit"]
}
```

Put the object inside the JSON list in `NEXUS_MCP_SERVERS`. Store the token as a
separate Render secret. NEXUS resolves only the named environment variable and
never returns its value in status output.

## Safety boundaries

- Remote endpoints require HTTPS. Plain HTTP is accepted only for loopback.
- Credentials, query strings, and fragments are rejected in endpoint URLs.
- A discovered tool is callable only when its exact name is allow-listed.
- Read-only servers run automatically. Tools on write-capable servers create an
  approval request. Names containing destructive verbs remain blocked.
- MCP annotations are displayed but never trusted to lower the configured risk.
- Redirect following is disabled so bearer credentials cannot cross hosts.

Connector discovery is safe to retry from the Integrations page. A connector
failure does not prevent NEXUS from starting; its last error is shown in status.
