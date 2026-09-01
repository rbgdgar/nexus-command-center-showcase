# NEXUS Command Center — Recruiter Showcase

NEXUS is a local-first personal AI operating layer built with FastAPI, React,
 SQLite/PostgreSQL, Ollama, Gemini, and OpenAI-compatible APIs. It includes persistent conversations and memory,
project retrieval, approval-gated tools, integrations, specialist agents,
push-to-talk voice, controlled automations, and retryable UI error handling.

This repository is the recruiter-facing documentation mirror for the full NEXUS
project. The current implementation baseline is V2.21.0, including selectable
conversations and bulk archive, restore, delete, and purge controls. The full
source repository remains [rbgdgar/nexus-command-center](https://github.com/rbgdgar/nexus-command-center).

The V2.2 Operations Matrix reports which providers and services are ready,
policy-blocked, or awaiting configuration instead of presenting every catalog
entry as immediately usable.

V2.3 adds approval-gated offline speech through the outbound local runner. Install
`requirements-runner.txt` on the paired machine to use its system voices without
sending response text to a cloud TTS service.

V2.4 adds an optional offline wake-word companion. It must be launched with an
explicit `--enable` flag, uses an allow-listed openWakeWord ONNX model, and does
not retain or upload microphone frames. See [`docs/RUNNER.md`](docs/RUNNER.md).

V2.5 adds authenticated manual Provider Connections for Gemini, OpenRouter,
Groq, OpenAI, Pollinations, and allow-listed compatible APIs. Every key is tested
with a read-only provider request, never echoed to the browser, and either kept
session-only or encrypted at rest with an operator-managed Fernet key.

V2.6 adds per-message chat actions: delete with confirmation, pin to long-term
memory, add to the approved project knowledge index, and integrate through a
configured model only after an exact provider/content preview and final confirmation.

V2.7 adds approval-gated media and volume controls to the Windows local runner.
Only seven fixed actions are accepted, repeat counts are capped, and no arbitrary
key, executable, or shell input can cross the runner boundary.

V2.8 adds an approval-gated application launcher. The paired machine owns a
small `NEXUS_RUNNER_APP_ALLOWLIST` of application IDs mapped to absolute argument
arrays; NEXUS can submit only an ID, never a path or arbitrary arguments.

V2.9 adds approval-gated screenshots. The local runner caps and PNG-encodes a
capture, uploads it only while the matching authenticated job is running, and
stores it in protected Media Studio storage rather than exposing a filesystem path.

## Release history

| Release | GitHub milestone | Primary outcome |
| --- | --- | --- |
| Foundation | Initial local agent through secure web deployment | FastAPI/React command center, Ollama, conversations, memory, retrieval, approvals, voice, automations, specialists, and Render deployment |
| V1.7 | Production foundation | CI, readiness, request tracing, security headers, and deployment operations |
| V1.8 | Secure multi-model gateway | Gemini, Ollama, OpenRouter, Groq, OpenAI-compatible routing, fallback, and paid-model policy |
| V1.9 | Multimodal media | Protected image understanding plus pluggable image and video workflows |
| V2.0 | Remote MCP runtime | Allow-listed Streamable HTTP MCP tools and bounded specialist execution |
| V2.1 | Real-world client | Installable PWA and outbound-only approval-gated local runner |
| V2.2 | Operational hardening | Operations Matrix, capacity diagnostics, Qwen3.8 discovery, and recovery testing |
| V2.3 | Safe local speech | Approval-gated offline system speech through `pyttsx3` |
| V2.4 | Offline wake word | Explicitly enabled openWakeWord ONNX companion with no audio retention or upload |
| V2.5 | Provider Connections | UI credential verification, rotation, encrypted persistence, and immediate runtime linking |
| V2.6 | Chat message actions | Delete, Pin, Add to Project, and preview-confirmed provider integration |
| V2.7 | Media and volume controls | Fixed approval-gated Windows media-key operations through the local runner |
| V2.8 | Allowlisted application launcher | Local-only configured application IDs with fixed argument arrays |
| V2.9 | Protected screenshots | Approval-gated local capture with authenticated protected-media upload |
| V2.10 | Structured research | Bounded DuckDuckGo search and Google News RSS adapters |
| V2.11 | Confirmed messaging | Consent-bound SMTP preview and final approval workflow |
| V2.12 | Local GGUF inference | Fixed no-shell llama.cpp execution with bounded inputs |
| V2.13 | Tray companion | Explicitly launched Windows online, attention, and offline states |
| V2.14 | Intent routing | Non-executing safety and approval route visualization |
| V2.15 | Multi-agent orchestration | Preview-confirmed bounded specialist plans |
| V2.16 | Live agent operations | Durable redacted events and background execution |
| V2.17 | Operator recovery | Idempotent cancellation and interrupted-run recovery |
| V2.18 | Adjustable workspace | Independent scrolling, compact mode, and sidebar resizing |
| V2.19 | Conversation organization | Search, rename, pin, archive, and restore controls |
| V2.20 | Conversation recovery | Recently deleted recovery, purge confirmation, and sorting |
| V2.21 | Bulk conversation management | Sidebar selection and batch archive, restore, delete, and purge |

## Live deployment and demo status

The existing authenticated NEXUS Command Center is running at
[nexus-command-center-r3h8.onrender.com](https://nexus-command-center-r3h8.onrender.com/).
The protected application uses Gemini for online inference and Neon PostgreSQL
for persistent data. Its public health endpoint is available at
[`/health`](https://nexus-command-center-r3h8.onrender.com/health); application
APIs require the configured NEXUS bearer token.

The tokenless recruiter walkthrough is live at
[rbgdgar.github.io/nexus-command-center-showcase](https://rbgdgar.github.io/nexus-command-center-showcase/).
It is a static, interactive read-only V2.21 walkthrough with no backend requests
or secrets. The fuller backend demo is live as an isolated deployment using
`NEXUS_DEMO_MODE=true`, disposable fictional data, no provider keys, no runner
credentials, and no production database. Do not use the token-protected URL as
the recruiter demo.

The verified full V2.21 demo is live at
[nexus-command-center-demo.onrender.com](https://nexus-command-center-demo.onrender.com/).
It exposes the NEXUS UI and read-only API without a token. The demo reports
`demo_mode: true`, seeds fictional conversations, and rejects state-changing
requests. The original [protected Render service](https://nexus-command-center-r3h8.onrender.com/)
remains separate.

### Full backend demo deployment

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/rbgdgar/nexus-command-center-showcase)

The button creates the separate `nexus-command-center-demo` service from the
included `render.yaml`. It is designed to resemble the full NEXUS UI while
remaining anonymous and read-only: it seeds fictional conversations, uses local
disposable SQLite storage, disables provider calls, and rejects all state-changing
API methods. Do not connect this Blueprint to the production database or add
provider, runner, SMTP, MCP, or access-token secrets.

The delivery sequence is documented in [`ROADMAP.md`](ROADMAP.md), and production
procedures are maintained in [`docs/OPERATIONS.md`](docs/OPERATIONS.md).
For a start-to-current overview, see [`docs/PROJECT-SUMMARY.md`](docs/PROJECT-SUMMARY.md)
and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

For recruiter-friendly capabilities, V2.21 progress, and the planned anonymous
read-only experience, see the [NEXUS recruiter showcase repository](https://github.com/rbgdgar/nexus-command-center-showcase).
The showcase is separate from this token-protected deployment and will receive a
live demo URL only after its isolated host is independently verified.

## Full project source and local development

The runnable source, environment template, Docker configuration, tests, and
frontend are maintained in the [main repository](https://github.com/rbgdgar/nexus-command-center).
The following commands apply when working from that repository.

## Prerequisites

- Python 3.12+
- Node.js and npm
- Ollama with `qwen3:4b` (or configure `NEXUS_MODEL_NAME`)

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm --prefix frontend install
Copy-Item .env.example .env
```

## Run locally

Start Ollama, then use separate terminals from the repository root:

```powershell
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
npm --prefix frontend run dev
```

Open `http://localhost:5173`. The API health endpoint is
`http://127.0.0.1:8000/health`.

## Validate

```powershell
python -m compileall backend tests
python -m unittest discover -v
python -c "from backend.main import app; print('API OK', app.version)"
npm --prefix frontend run lint
npm --prefix frontend run build
git status --short
```

Runtime data is stored under `data/` and is intentionally ignored. Never commit
`.env`, databases, virtual environments, dependency folders, logs, caches, or
frontend build output.

## Model providers

Ollama remains the default for fully local use. To use Gemini online, create a
free-tier API key in Google AI Studio and set these values outside Git:

```powershell
$env:NEXUS_MODEL_PROVIDER = "gemini"
$env:NEXUS_GEMINI_API_KEY = "your-key"
$env:NEXUS_GEMINI_MODEL_NAME = "gemini-3.7-flash"
```

Never commit the API key. Cloud deployments must load it from a managed secret.

NEXUS exposes a capability and cost-aware catalog at `/api/models`. The online
free-first default is Gemini 3.7 Flash. Optional OpenRouter (`openrouter/free`) and
Groq free-plan routes can be enabled by adding their API keys as cloud secrets.
Ollama remains the no-API-cost local option. Current OpenAI models are listed but
cannot run unless `NEXUS_ALLOW_PAID_MODELS=true` is explicitly configured.
Provider setup, cost policy, and current source references are documented in
[`docs/MODELS.md`](docs/MODELS.md).

The authenticated **Provider Connections** page can verify and link credentials
without restarting NEXUS. Set `NEXUS_ACCESS_TOKEN` before enabling UI writes. For
durable connections, generate a Fernet key once and store it as
`NEXUS_PROVIDER_SECRET_ENCRYPTION_KEY` in the local or cloud secret manager:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Never rotate that encryption key until UI-managed provider credentials have been
disconnected or re-entered; losing it makes their encrypted database values unreadable.

For local inference, `qwen3:4b` remains the practical default on ordinary PCs.
Qwen3.8 27B can be installed with `ollama pull qwen3.8:27b`, but its 18 GB model
artifact requires substantially more runtime memory than a 16 GB machine can
provide reliably. Run `python scripts/check_local_readiness.py` before selecting it.

## Multimodal media

Media Studio accepts JPEG, PNG, and WebP uploads for vision-capable models. It
also provides pluggable image generation and asynchronous video generation.
Pollinations is the free-credit option and requires `NEXUS_POLLINATIONS_API_KEY`;
OpenAI image and video generation remains disabled unless paid models are
explicitly enabled. See [`docs/MEDIA.md`](docs/MEDIA.md) for provider and storage
details.

## Remote MCP and specialists

Version 2.0 connects to allow-listed Streamable HTTP MCP servers and makes
discovered tools available to NEXUS and its bounded specialist runs. The public
OpenAI documentation MCP is configured by default. The official GitHub remote
MCP can be enabled with a fine-grained token stored in `NEXUS_GITHUB_TOKEN`.
Configuration and safety rules are documented in [`docs/MCP.md`](docs/MCP.md).

## Installable client and local runner

The production frontend is an installable PWA with an offline application shell,
mobile layout, and automatic reconnect status. API responses and bearer tokens
are never placed in the service-worker cache.

The Local Runner page pairs a machine and queues fixed allow-listed operations
over outbound HTTPS polling. It exposes no local port and cannot execute arbitrary
shell commands. Read-only inspection runs automatically; creating a new text file
requires approval and existing files cannot be overwritten. Setup and recovery
commands are in [`docs/RUNNER.md`](docs/RUNNER.md).

For an internet deployment, also set a high-entropy `NEXUS_ACCESS_TOKEN`. The
browser keeps this token in session storage and sends it only as an HTTPS bearer
token. Local development remains open when this setting is empty.

## Online deployment

Online instances use a pooled Neon PostgreSQL connection in
`NEXUS_DATABASE_URL`; local development continues to use SQLite when that value
is empty. Create a Neon Free project, copy its pooled connection string, and
keep it only in host or GitHub secrets.

To copy existing local data once into an empty Neon database:

```powershell
python scripts/migrate_sqlite_to_postgres.py `
  --database-url "postgresql://...-pooler.../neondb?sslmode=require"
```

The migration refuses to write to a non-empty target to prevent duplicate
messages or history.

### Primary: Google Cloud Run

The GitHub workflow in `.github/workflows/deploy-cloud-run.yml` uses keyless
Workload Identity Federation and deploys from `main`. Configure these GitHub
repository settings, then set the `GCP_DEPLOY_ENABLED` variable to `true`:

- Variables: `GCP_PROJECT_ID`
- Secrets: `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`,
  `NEXUS_DATABASE_URL`, `NEXUS_GEMINI_API_KEY`, `NEXUS_ACCESS_TOKEN`

Cloud Run is configured with zero minimum instances and one maximum instance to
limit exposure, but Google Cloud still requires a billing account and budgets
are alerts rather than hard spending caps.

### Strict no-billing switch: Render

The root `render.yaml` creates a Free Docker web service. Connect this GitHub
repository as a Render Blueprint without adding a payment method, then enter
`NEXUS_DATABASE_URL` and `NEXUS_GEMINI_API_KEY` when prompted. Render generates
the access token. Copy that generated value from the service environment to log
in to NEXUS.

Without a payment method, Render suspends free services instead of charging when
included usage is exhausted. Free services sleep after inactivity and can take
about a minute to wake, so this target is a safe fallback rather than an
always-on production host.

## Safety model

Read-only tools can run automatically. Writes and privileged actions require an
approval record, while destructive tools are blocked. Project indexing is
restricted to approved roots, and infrastructure commands use allow-listed
argument arrays without a shell.
