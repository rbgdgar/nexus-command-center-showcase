# Anonymous demo safety contract

The recruiter demo is a separate deployment from the token-protected NEXUS
service. It must be configured with:

- `NEXUS_DEMO_MODE=true`
- No `NEXUS_ACCESS_TOKEN` and no provider, SMTP, MCP, or runner secrets
- A disposable seeded database containing fictional showcase data only
- No production database URL, local-runner pairing, or outbound automation
- Rate limiting at the hosting or edge layer
- Seeded fictional conversations that make the V2.21 workspace visible without
  requiring a provider call

The application rejects all API methods other than GET, HEAD, and OPTIONS while
demo mode is enabled. This protects conversation mutation, provider connection,
media generation, messaging, runner, orchestration execution, and other writes
even when the host allows unauthenticated HTTP traffic.

The demo URL is not considered ready for a CV until `/api/config`, `/health`, and
`/ready` are checked anonymously and the browser workflow is verified.

## Host setup

Create a new Render Blueprint from this repository, not from the protected main
repository. The included `render.yaml` creates `nexus-command-center-demo` with
the demo safety settings. Do not add provider keys, a production database URL,
an access token, SMTP credentials, MCP credentials, or runner credentials.

After the first deploy, verify anonymously:

```powershell
curl.exe -sS https://<demo-host>/api/config
curl.exe -sS https://<demo-host>/health
curl.exe -sS https://<demo-host>/ready
```

The expected configuration reports `demo_mode: true` and
`authentication_required: false`. The demo is ready for recruiter use only when
the browser shows the seeded V2.21 conversations and the UI displays the
`RECRUITER DEMO · READ-ONLY · NO TOKEN REQUIRED` banner.
