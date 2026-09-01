# NEXUS model providers

NEXUS uses a cost-aware catalog and defaults to providers that can operate without
API usage charges. Free tiers have quotas, rate limits, availability constraints,
and provider data-use terms; they are not unlimited production capacity.

| Provider | Default model | Cost policy | Configuration |
| --- | --- | --- | --- |
| Gemini | `gemini-3.7-flash` | Free tier | `NEXUS_GEMINI_API_KEY` |
| OpenRouter | `openrouter/free` | Free router | `NEXUS_OPENROUTER_API_KEY` |
| Groq | `openai/gpt-oss-120b` | Free plan | `NEXUS_GROQ_API_KEY` |
| Ollama | `qwen3:4b` | Local compute | Local Ollama service |
| OpenAI | `gpt-5.6-luna` | Paid | API key plus `NEXUS_ALLOW_PAID_MODELS=true` |
| Compatible API | Operator-selected | Unknown by default | Base URL, model, and optional key |

The V2.2 operations matrix distinguishes `ready`, `setup_required`, and `blocked`
models. It checks Ollama's installed-model inventory instead of assuming that every
catalog entry is already downloaded. The local catalog includes Qwen 3.8 27B, but
keeps `qwen3:4b` as the practical default for the current 15.3 GB workstation: the
27B artifact alone is about 18 GB before runtime overhead. Qwen 3.8 Flash-Next is
listed for visibility but its available 113 GB MLX build is not suitable for this
Windows host.

The UI disables providers that are not configured and paid models that are not
explicitly allowed. Default requests may fall back only to configured and allowed
providers. Choosing a model explicitly disables fallback so the requested model is
never silently replaced.

## Manual Provider Connections

The authenticated Provider Connections page accepts keys for Gemini, OpenRouter,
Groq, OpenAI, Pollinations, and a compatible API. Connect performs a read-only
provider request before activating a credential. NEXUS never returns key values,
stores them in browser storage, includes them in audit arguments, or logs provider
response bodies.

Set `NEXUS_ACCESS_TOKEN` to enable connection writes. Without
`NEXUS_PROVIDER_SECRET_ENCRYPTION_KEY`, verified keys remain in server memory and
are visibly labeled `session`; they disappear on restart. With a stable Fernet
key, credentials are encrypted before SQLite/PostgreSQL storage and labeled
`encrypted`. Generate the key once and place it only in the deployment secret manager:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Known providers use fixed HTTPS endpoints. A compatible endpoint must be loopback
or its hostname must appear in the comma-separated `NEXUS_PROVIDER_ALLOWED_HOSTS`
setting, preventing the UI from becoming an unrestricted server-side request proxy.
OpenAI keys may be connected and verified while paid model/media execution remains
blocked unless `NEXUS_ALLOW_PAID_MODELS=true` is deliberately enabled.

Current source references:

- Gemini models and pricing: <https://ai.google.dev/gemini-api/docs/models> and
  <https://ai.google.dev/gemini-api/docs/pricing>
- OpenRouter free router: <https://openrouter.ai/docs/cookbook/get-started/free-models-router-playground>
- Groq free-plan limits: <https://console.groq.com/docs/rate-limits>
- OpenAI model catalog: <https://developers.openai.com/api/docs/models>
- Ollama Qwen 3.8 tags: <https://ollama.com/library/qwen3.8/tags>
- Ollama Qwen 3.8 Flash-Next: <https://ollama.com/library/qwen3.8-flash-next>

Model availability changes independently of NEXUS. Update the checked-in catalog,
tests, and documentation together when providers deprecate or replace model IDs.
