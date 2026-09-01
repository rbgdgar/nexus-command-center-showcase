# Multimodal media

NEXUS V1.9 adds a protected Media Studio and API for image understanding, image
generation, and asynchronous video generation.

## Capabilities

- `POST /api/media/understand` sends a validated JPEG, PNG, or WebP image to a
  configured vision model. Gemini is the free-tier default.
- `POST /api/media/images` generates and stores an image synchronously.
- `POST /api/media/videos` queues video generation and returns a job immediately.
- `/api/media/jobs` and `/api/media/assets/{id}` expose metadata and protected
  assets to authenticated clients.

## Provider policy

| Provider | Images | Videos | Cost policy |
| --- | --- | --- | --- |
| Pollinations | Flux | Wan, Seedance, Veo | Account free credits; API key required |
| OpenAI | GPT Image 2 | Sora 2 | Paid; blocked unless `NEXUS_ALLOW_PAID_MODELS=true` |

No provider is treated as unlimited or permanently free. The UI reports whether
each provider is configured and allowed before enabling generation.

## Configuration

```text
NEXUS_POLLINATIONS_API_KEY=<cloud secret>
NEXUS_POLLINATIONS_BASE_URL=https://gen.pollinations.ai
NEXUS_MEDIA_STORAGE_PATH=data/media
```

The Pollinations key is sent only in an authorization header. Upload and output
size limits are enforced by the backend. Generated assets require the same NEXUS
bearer token as the rest of the application.

Render Free filesystems are ephemeral, so generated asset files can disappear on
restart or redeploy even though job metadata persists in Neon. Download important
outputs promptly. Durable object storage is intentionally deferred because the
project currently targets strict no-billing hosting.

Video work runs in the web process. A job interrupted by a host restart remains
recorded but is not automatically resumed in V1.9.
