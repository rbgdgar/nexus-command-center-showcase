# Anonymous demo safety contract

The recruiter demo is a separate deployment from the token-protected NEXUS
service. It must be configured with:

- `NEXUS_DEMO_MODE=true`
- No `NEXUS_ACCESS_TOKEN` and no provider, SMTP, MCP, or runner secrets
- A disposable seeded database containing fictional showcase data only
- No production database URL, local-runner pairing, or outbound automation
- Rate limiting at the hosting or edge layer

The application rejects all API methods other than GET, HEAD, and OPTIONS while
demo mode is enabled. This protects conversation mutation, provider connection,
media generation, messaging, runner, orchestration execution, and other writes
even when the host allows unauthenticated HTTP traffic.

The demo URL is not considered ready for a CV until `/api/config`, `/health`, and
`/ready` are checked anonymously and the browser workflow is verified.
