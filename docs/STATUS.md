# NEXUS project status

Last recorded: 2026-09-02

## Current release

NEXUS is at V2.21.0 on `main`; the live Render deployment still reflects the latest published V2.20 build until the next approved deploy:

- Live URL: https://nexus-command-center-r3h8.onrender.com/
- Showcase repository: https://github.com/rbgdgar/nexus-command-center-showcase
- Full source repository: https://github.com/rbgdgar/nexus-command-center
- Recruiter showcase: https://github.com/rbgdgar/nexus-command-center-showcase
- Implementation baseline: V2.21 bulk conversation management and sidebar polish milestone
- Latest commit: `f8655aee337fe0afd0855134f7570c338617af19` (`feat: add bulk conversation management`)
- Latest GitHub validation: passed — [Validate NEXUS run 33331909822](https://github.com/rbgdgar/nexus-command-center/actions/runs/33331909822)
- Cloud Run deployment workflow: skipped; deployment remains intentionally gated
- Local validation: 110 tests, backend compile/import, frontend lint/build all passed

## Delivered milestones

- V1.7: CI, readiness, request tracing, security headers, deployment operations.
- V1.8: free-first multi-model gateway (Gemini, OpenRouter, Groq, Ollama) with
  paid OpenAI GPT-5.6 models explicitly disabled by default.
- V1.9: image understanding, protected media assets, image/video provider
  adapters, Media Studio UI, upload/output limits.
- V2.0: Streamable HTTP MCP discovery/calls, HTTPS and environment-secret
  validation, allowlists, safety registration, bounded specialist runs.
- V2.1: installable PWA shell, mobile layout, reconnect state, outbound-only
  local runner with fixed tools and approval-gated create-only file writes.
- V2.2: operations matrix, capacity diagnostics, and runner/database/PWA recovery.
- V2.3: bounded offline system speech through an approval-gated runner tool.
- V2.4: explicitly enabled local wake-word detection with no audio retention or upload.
- V2.5: authenticated provider-key verification with encrypted or session-only runtime linking.
- V2.6: Delete, Pin, Add to Project, and preview-confirmed Integrate actions on chat messages.
- V2.7: fixed approval-gated media and volume actions through the Windows local runner.
- V2.8: local-only configured application ID launcher with fixed argument arrays.
- V2.9: approval-gated screenshot capture and protected asset upload through the local runner.
- V2.10: bounded, read-only structured public search and current-news adapters.
- V2.11: consent-bound SMTP contact messaging with final approval before delivery.
- V2.12: direct local GGUF llama.cpp inference with fixed no-shell subprocess arguments.
- V2.13: explicitly launched Windows tray companion with online, attention, and offline states.
- V2.14: non-executing intent-routing visualization with safety and approval boundaries.
- V2.15: preview-confirmed, bounded multi-agent plans with no tools or recursive delegation.
- V2.16: authenticated live orchestration events with durable, redacted timelines.
- V2.17: durable operator cancellation and bounded interrupted-run recovery.
- V2.18: independently scrolling, adjustable workspace with confirmed conversation deletion.
- V2.19: searchable conversations with bounded rename, pin, archive, and restore controls.
- V2.20: 30-day recently deleted recovery, confirmed permanent purge, and persistent conversation sorting.
- V2.21: selectable sidebar conversations with bulk archive, restore, delete, and purge controls.

## Live verification evidence

- Render `/api/config`: version `2.20.0` after the V2.20 deployment.
- Render `/health`: `healthy`; `/ready`: `ready`.
- Gemini chat completed successfully through the configured production route.
- Gemini image understanding: returned a correct description of the repository
  hero image.
- OpenAI Docs MCP: five tools discovered and `search_openai_docs` executed.
- All five specialist agents report `ready`.
- PWA manifest, icon, and service worker return HTTP 200.

## V2.21 pre-deployment gate

V2.21 is implemented, committed, pushed, and validated in GitHub Actions, but it
has not been promoted to Render. Keep the live service on V2.20 until the release
is explicitly approved and independently verified.

- [x] V2.21 sidebar selection and bulk archive, restore, delete, and purge controls implemented.
- [x] Local validation passed: compile/import, 109 tests, frontend lint, and frontend build.
- [x] GitHub Actions validation passed for commit `f8655ae`.
- [x] No deployment workflow ran for the V2.21 push.
- [x] Public recruiter showcase repository created with the complete project documentation set.
- [x] Read-only demo-mode safety boundary implemented and tested in the full source repository.
- [ ] Approve the Render deployment.
- [ ] Confirm the Render release reports `/api/config` version `2.21.0`.
- [ ] Run the authenticated deployment smoke test and confirm `/health` and `/ready`.
- [ ] Perform browser verification of sidebar selection, independent scrolling, width adjustment, and bulk actions.
- [ ] Record the deployment timestamp, commit, endpoint results, and any rollback decision here.

The anonymous demo host is not provisioned yet. The showcase repository is public,
but no public demo URL should be advertised until a separate host is configured
with `NEXUS_DEMO_MODE=true`, no secrets, disposable data, and independent endpoint
and browser verification.

## Optional configuration still pending

- `NEXUS_OPENROUTER_API_KEY` and `NEXUS_GROQ_API_KEY` are not configured.
- `NEXUS_POLLINATIONS_API_KEY` is not configured, so image/video generation is
  present but disabled until a provider key with available credits is supplied.
- `NEXUS_GITHUB_TOKEN` is not configured for the optional hosted GitHub MCP;
  the existing read-only GitHub integration remains separate.
- OpenAI media/models remain paid-gated by `NEXUS_ALLOW_PAID_MODELS=false`.

## V2.2 operational notes

- Windows Python 3.12.10 and the repository virtual environment were repaired.
- Ollama 0.33.1 is installed; `qwen3:4b` remains the usable 16 GB-machine default.
- Qwen3.8 27B is an optional 18 GB artifact and is not a safe default for the
  current 15.3 GB RAM workstation.
- The repository default remains Gemini 3.7 Flash. Check Render after deployment
  for any dashboard-level model override.
- Source and endpoint health cannot prove that the previously exposed Gemini key
  was rotated; verify replacement metadata in the provider or Render control plane.

## Resume checklist for the next Codex run

1. Read this file, `ROADMAP.md`, `AGENTS.md`, and `git status` before editing.
2. Treat the latest completed milestone commit on `main` as the current baseline; do not redo completed milestones.
3. Preserve one milestone per commit and run the required validation gate.
4. If enabling providers, add secrets only through Render/GitHub secret managers;
   never commit `.env`, deployment files, tokens, or API keys.
5. Rotate the Gemini key previously pasted into chat before further production
   use, then update the Render secret.
