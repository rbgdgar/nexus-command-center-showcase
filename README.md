# NEXUS Command Center — Recruiter Showcase

NEXUS is a local-first AI command center built with FastAPI, React, and Vite.
It combines model routing, durable conversations, retrieval, bounded specialists,
approval-aware operations, and a visible safety model in one operator workspace.

## V2.21 showcase

The current implementation includes:

- Selectable conversations with visible selection counts.
- Bulk archive, restore, delete, and permanent-purge controls.
- Independent sidebar/workspace scrolling and adjustable sidebar width.
- Search, sorting, rename, pin, archive, and recently deleted recovery.
- Preview-confirmed bounded multi-agent orchestration.
- Authenticated live operations, durable redacted events, and cooperative cancellation.
- Local runner controls restricted to fixed allowlisted capabilities.
- Read-only research, MCP discovery, provider health, PWA, and media surfaces.

## Live demo

The anonymous recruiter demo is being prepared as an isolated read-only deployment.
This repository will contain the verified URL once deployment and browser checks are
complete. No token will be required for the recruiter demo.

The full application remains available in the [main NEXUS repository](https://github.com/rbgdgar/nexus-command-center),
where the production-style deployment remains token-protected.

## Safety boundary

The public demo uses explicit `NEXUS_DEMO_MODE=true`. In this mode, public GET
requests can display the seeded showcase state, while all API state-changing
methods are rejected. It has no provider keys, runner credentials, personal data,
or production database. The authenticated deployment retains its existing bearer
token requirement and operational capabilities.

## Evidence

- Current release: V2.21.0
- Implementation commit: [`f8655ae`](https://github.com/rbgdgar/nexus-command-center/commit/f8655aee337fe0afd0855134f7570c338617af19)
- Demo safety boundary: [`ed7210d`](https://github.com/rbgdgar/nexus-command-center/commit/ed7210d)
- Validation: 110 local tests, backend compile/import, frontend lint, and frontend build
- Project status and pre-deployment gate: [main repository status](https://github.com/rbgdgar/nexus-command-center/blob/main/docs/STATUS.md)

## Technical snapshot

| Area | Implementation |
| --- | --- |
| Backend | FastAPI, Pydantic settings, SQLite/Postgres-compatible persistence |
| Frontend | React, Vite, installable PWA shell |
| AI | Gemini, OpenAI-compatible providers, Ollama, direct GGUF llama.cpp |
| Operations | Bounded specialists, approval queue, redacted audit/event timelines |
| Integrations | Read-only GitHub, MCP, structured search/news, protected media |
| Deployment | Render authenticated service; isolated anonymous demo planned |

## Repository relationship

This showcase is intentionally recruiter-oriented. It documents the validated
capabilities and demo contract without granting access to production secrets,
runner machines, provider credentials, or the token-protected deployment.
