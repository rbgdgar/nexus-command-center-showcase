# NEXUS project summary

NEXUS is a local-first personal AI operating layer. It began as a private
FastAPI/React workspace with SQLite and Ollama, then grew into a protected,
deployable command center without giving up local control or safety gates.

## Where it is now

- **Release:** V2.21.0
- **Showcase repository:** https://github.com/rbgdgar/nexus-command-center-showcase
- **Full source repository:** https://github.com/rbgdgar/nexus-command-center
- **Online service:** https://nexus-command-center-r3h8.onrender.com/
- **Primary online model:** Gemini free-tier route
- **Strict no-billing host:** Render Free; Cloud Run remains optional but requires a billing account
- **Persistence:** SQLite locally; pooled Neon PostgreSQL online
- **Client:** React/Vite installable PWA with mobile layout and reconnect state

## Evolution from the start

| Stage | What was added | Result |
| --- | --- | --- |
| Local foundation | FastAPI API, React/Vite UI, SQLite, Ollama, conversations, memory, project retrieval | Private local command center |
| V1.7 | CI, readiness checks, request IDs, security headers, deployment operations | Observable and deployable baseline |
| V1.8 | Capability/cost-aware model gateway, Gemini, Ollama, OpenRouter, Groq, paid-model gate, fallback routing | Free-first multi-model access |
| V1.9 | Image understanding, image/video adapters, protected media assets, Media Studio | Multimodal workflows |
| V2.0 | Streamable HTTP MCP, HTTPS/auth/allowlists, tool discovery, specialist agents | Bounded real-world integrations |
| V2.1 | PWA shell, mobile UX, outbound-only local runner, fixed tools, approval-gated file creation | Usable online and safely connected to a local machine |
| V2.2 | Operations matrix, recovery tests, Qwen3.8 discovery, cinematic command UI | Honest service state and stronger recovery |
| V2.3 | Approval-gated local speech through the outbound runner | Offline spoken responses without weakening machine boundaries |
| V2.4 | Explicitly enabled openWakeWord companion | Offline activation without retaining or uploading microphone audio |
| V2.5 | Authenticated Provider Connections | Verified API-key linking with encrypted or explicitly session-only storage |
| V2.6 | Durable per-message chat actions | Delete, pin, project knowledge, and preview-confirmed provider handoff |
| V2.7 | Fixed media and volume controls | Approval-gated Windows media keys without arbitrary command input |
| V2.8 | Allowlisted application launcher | Fixed local executable arrays selected only by application ID |
| V2.9 | Protected screenshot capture | Approval-gated local PNGs stored through protected media assets |
| V2.10 | Structured research | Bounded search and current-news adapters |
| V2.11 | Confirmed messaging | Consent-bound SMTP with preview and final approval |
| V2.12 | Local GGUF inference | Fixed no-shell llama.cpp provider |
| V2.13 | Tray companion | Explicit local online, attention, and offline states |
| V2.14 | Intent routing | Non-executing route and safety visualization |
| V2.15 | Multi-agent orchestration | Preview-confirmed bounded specialist plans |
| V2.16 | Live agent operations | Durable redacted event timelines |
| V2.17 | Operator recovery | Cancellation and interrupted-run recovery |
| V2.18 | Adjustable workspace | Independent scrolling, compact mode, and resizing |
| V2.19 | Conversation organization | Search, rename, pin, archive, and restore |
| V2.20 | Conversation recovery | Recently deleted recovery, purge, and sorting |
| V2.21 | Bulk conversation management | Sidebar selection and batch conversation actions |

## Main capabilities

1. Chat with durable per-message actions, persistent conversations, long-term memory, project indexing, and retrieval.
2. Model selection with free-first routing, explicit paid-model opt-in, and manual provider linking.
3. Image-to-text understanding plus pluggable image and asynchronous video generation.
4. MCP discovery and calls for allow-listed remote services, including OpenAI Docs.
5. Five bounded specialist agents that remain inside NEXUS safety controls.
6. Voice input, controlled automations, approvals, notifications, and audit-friendly logs.
7. Local Runner operations: system info, Git status/diff, safe file listing/reading, approval-gated create-only text files, speech, fixed media controls, local allowlisted applications, and protected screenshot capture.
8. Recruiter demo boundary: anonymous read-only access through explicit demo mode, with no production secrets, runner credentials, or mutable API operations.

## Safety and cost boundaries

- Read-only operations may run automatically; safe writes require approval.
- Destructive actions are blocked, and arbitrary shell execution is not exposed.
- MCP endpoints must be HTTPS (loopback is allowed for local development), use secret references rather than inline credentials, and be explicitly allow-listed.
- Runner communication is outbound polling only; it opens no inbound port.
- Uploads, generated assets, project roots, and subprocess arguments are bounded.
- Secrets belong only in local/cloud secret managers. Never commit `.env`, tokens, API keys, databases, logs, or build output.

## Optional providers still available

OpenRouter, Groq, Pollinations, and hosted GitHub MCP can be enabled by adding
their secrets. OpenAI GPT-5.6 and OpenAI media providers are listed but remain
disabled unless `NEXUS_ALLOW_PAID_MODELS=true` is deliberately configured.

## How to resume work

Read `AGENTS.md`, `ROADMAP.md`, this file, and `docs/ARCHITECTURE.md` first.
Treat V1.7–V2.1 as complete. Start any new feature as its own milestone,
validate it with the required gate, create one dedicated commit, and push it.
