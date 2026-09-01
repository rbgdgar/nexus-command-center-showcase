# NEXUS operations runbook

## Deployment

Render deploys `main` automatically from `render.yaml`. Confirm `/health`, `/ready`,
and `/api/config` after each deployment. The Cloud Run workflow runs the authenticated
smoke test after a successful deploy; run the same safe check for Render with:

```powershell
python scripts/smoke_deployment.py https://nexus-command-center-r3h8.onrender.com
```

Set `NEXUS_ACCESS_TOKEN` only in the process environment to include the authenticated
API check. It validates the Operations Matrix, model catalog, runner and contacts
status, plus a non-executing intent-route preview. The script never prints the token
or private API response bodies.

## Secret rotation

1. Create the replacement credential at the provider.
2. Replace it in Render and the corresponding GitHub Actions secret.
3. Replace the ignored local value when local testing needs it.
4. Redeploy and run the smoke test.
5. Revoke the previous credential after the replacement passes.

Never commit `.env` files or paste secret values into issues, logs, or chat.

## Rollback

Select the last healthy deploy in Render and redeploy it. Do not rewrite Git history.
If the failure is source-related, revert the dedicated milestone commit, run the full
validation gate, and push the revert as a new commit.

## Diagnostics

Application events are emitted as redacted JSON to standard output. Use request IDs
to correlate failures. Export provider logs from the Render dashboard, then run the
local diagnostic bundle procedure without adding `logs/` to Git.

## Readiness semantics

`/health` confirms the process is alive. `/ready` checks database connectivity and
whether the selected model provider is configured. A failing readiness check returns
HTTP 503 so deployment systems do not mistake a partially configured service for a
working command center.

## V2.2 operations matrix

The authenticated `/api/operations` endpoint combines database connectivity,
model-provider policy and configuration, MCP discovery, media providers,
local-runner pairing, and PWA asset safety. `ready` means configured for use; it
does not claim that an untested third-party quota or billing account is available.

Run `python scripts/check_local_readiness.py` before pulling large local models.
SQLite recovery uses a create-only backup and verifies it with
`PRAGMA integrity_check`. Runner startup requeues jobs interrupted in `running`
state for over fifteen minutes while retaining their approval history.

After deployment, validate the public PWA and authenticated operations endpoint
without printing the token:

```powershell
python scripts/smoke_deployment.py https://nexus-command-center-r3h8.onrender.com --env-file .env.deployment
```
