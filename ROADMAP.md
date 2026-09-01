# NEXUS roadmap

Milestones are delivered sequentially. Each version receives the complete validation
gate in `AGENTS.md`, one dedicated commit, and a GitHub push before work continues.

## V1.7 - Production foundation (completed)

- Continuous integration for backend and frontend validation.
- Dependency readiness, request tracing, security headers, and deployment smoke tests.
- Operational procedures for secrets, deployment, rollback, and diagnostics.

## V1.8 - Secure multi-model gateway (completed)

- Capability-based model catalog and per-request model selection.
- Gemini, Ollama, OpenAI, and configurable OpenAI-compatible endpoints.
- Free-first routing, explicit cost labels, fallback policy, and provider health.

## V1.9 - Multimodal media (completed)

- Image inputs for model-based understanding and extraction.
- Pluggable image generation and asynchronous video generation.
- Safe upload validation, media metadata persistence, and command-center UI.

## V2.0 - Remote MCP and agent runtime (completed)

- Streamable HTTP MCP connections with authentication references and allowlists.
- Capability discovery, health checks, and specialist-agent readiness reporting.
- Remote tools remain subject to the NEXUS approval and destructive-action policy.

## V2.1 - Real-world client (completed)

- Installable PWA, resilient reconnect behavior, and mobile interaction.
- Secure outbound-only local runner contract for approved machine operations.
- End-to-end deployment checks and recovery documentation.

## V2.2 - Operational hardening (completed)

- Provider and service readiness matrix with explicit ready, blocked, and setup states.
- Qwen3.8 local-model discovery plus capacity-aware setup diagnostics.
- Authenticated PWA, SQLite backup recovery, and interrupted-runner recovery tests.
- Original cinematic operations HUD inspired by synthetic-intelligence interfaces.

## V2.3 - Safe local speech output (completed)

- Approval-gated `speak_text` capability on the outbound-only local runner.
- Offline `pyttsx3` system speech with bounded text, rate, volume, and voice selection.
- Structured Command Center controls and runner-specific dependency installation.

## V2.4 - Offline wake-word companion (completed)

- Explicitly enabled local 16 kHz microphone listener using openWakeWord ONNX.
- Allow-listed pretrained phrases, bounded detection threshold, and activation cooldown.
- No audio retention or upload; activation can only report an event or open a validated Command Center URL.

## V2.5 - Manual provider connections (completed)

- Authenticated UI connection forms for Gemini, OpenRouter, Groq, OpenAI, Pollinations, and compatible APIs.
- Read-only credential verification with masked status, rotation, disconnect, and immediate runtime availability.
- Fernet-encrypted database persistence when an operator secret is configured; otherwise explicitly session-only.
- Compatible endpoints restricted to loopback or an operator-configured HTTPS host allowlist.

## V2.6 - Durable chat message actions (completed)

- Stable message identities with Delete, Pin, Add to Project, and Integrate controls.
- Pins become durable long-term notes; project additions remain searchable across source reindexing.
- Integration preview performs no provider request and shows provider, model, cost tier, instruction, and message size.
- Final integration confirmation sends only to the selected configured model with tools disabled.

## V2.7 - Fixed media and volume controls (completed)

- Approval-gated local-runner operation for play/pause, next, previous, stop, mute, volume down, and volume up.
- Fixed Windows media-key map with no arbitrary virtual-key or executable input.
- Bounded repeat count and structured Command Center controls.

## V2.8 - Allowlisted application launcher (completed)

- Approval-gated `launch_app` runner operation that accepts only a local application ID.
- Paired-machine `NEXUS_RUNNER_APP_ALLOWLIST` maps IDs to existing absolute executable argument arrays.
- No browser or server executable paths, arbitrary arguments, or shell execution.

## V2.9 - Protected screenshot capture (completed)

- Approval-gated `capture_screenshot` runner operation with no user-supplied arguments.
- Bounded PNG capture uploaded outbound only while its matching authenticated runner job is active.
- Screenshots use existing protected Media Studio storage and authenticated asset delivery.

## V2.10 - Structured search and news adapters (completed)

- Read-only, bounded structured search through DuckDuckGo's public instant-answer API.
- Read-only current-news summaries through Google News RSS, without article-page fetching.
- HTTPS-only result URLs, no credential forwarding or query persistence, and a dedicated Research view.

## V2.11 - Confirmed contact and messaging integration (completed)

- SMTP plain-text email to manually recorded, consent-bound contacts only.
- A consent source, subject, timestamp, optional expiry, and immediate opt-out block are required safeguards.
- Message preview plus a final approval are required before an outbound delivery attempt; audit history excludes message bodies.

## V2.12 - Direct GGUF llama.cpp provider (completed)

- Direct local GGUF inference uses only an existing absolute `llama-cli` executable and existing absolute `.gguf` model path.
- Execution is a bounded fixed argument array with no shell, 120-second timeout, and no tool or vision support.

## V2.13 - Windows tray companion states (completed)

- Explicitly launched tray companion shows online, attention, or offline state from health and readiness checks.
- It opens only a validated HTTPS or loopback Command Center URL and exposes no listener.

## V2.14 - Intent-routing visualization (completed)

- Non-executing intent preview shows classifier, safety policy, destination, risk level, and approval boundary.

## V2.15 - Bounded multi-agent orchestration (completed)

- Server-stored execution plans preview the exact registered specialists, provider, model, risk, and limits before any model call.
- Up to four specialists run with one provider call each plus one final synthesis call, a 90-second overall timeout, empty tool lists, and recursive delegation disabled.
- Destructive objectives remain blocked; safe-write objectives must pass through the existing approval queue before analysis can run.
- Completed plans retain per-specialist contributions and failures with a consolidated execution summary.

## V2.16 - Live agent operations (completed)

- Preview-confirmed plans can start once in the background while an authenticated event stream reports queued, running, specialist, synthesis, and terminal states.
- The event timeline is durable across page refreshes and contains metadata only; objectives, prompts, responses, credentials, and raw exceptions are excluded.
- The existing synchronous execution contract remains available, and all V2.15 provider-call, timeout, tool, recursion, approval, and destructive-action limits remain enforced.

## V2.17 - Operator control and recovery (completed)

- Authenticated operators can request an idempotent stop for queued or running orchestration plans without granting specialists any new capability.
- Queued plans cancel before provider work begins; running plans stop through local task cancellation plus durable cooperative checks between bounded provider stages.
- Interrupted active records close only after the fixed 90-second execution limit and a 30-second recovery grace window, with metadata-only recovery events.
- Graceful application shutdown requests cancellation for active local runs, while destructive actions, tools, recursive delegation, approval rules, and provider-call limits remain unchanged.

## V2.18 - Adjustable workspace and conversation deletion (completed)

- The desktop sidebar and main workspace scroll independently within the viewport.
- Operators can resize the sidebar from 220 to 420 pixels or switch to a persistent compact mode.
- Every conversation has a directly accessible, explicitly confirmed delete control that cascades only its local messages and action metadata.
- Small-screen layouts retain access to conversations while reverting to natural document scrolling.

## V2.19 - Conversation organization (completed)

- Rename, pin, archive, and search conversations from the sidebar.
- Preserve bounded titles and explicit controls while keeping archived chats out of the default active list.

## V2.20 - Conversation recovery and sorting (completed)

- Recover recently deleted conversations before a bounded retention deadline or permanently purge them with confirmation.
- Sort active, archived, and deleted conversations by recent activity, creation time, or title.

## V2.21 - Bulk conversation management and sidebar polish (completed)

- Select conversations directly from the sidebar and apply batch archive, restore, delete, or purge actions.
- Surface visible-selection counts and bulk controls so sidebar cleanup feels more deliberate and faster.
- Add clearer selected-state feedback to the sidebar conversation list while keeping the main workspace unchanged.
