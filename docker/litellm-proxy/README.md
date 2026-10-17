# LiteLLM Proxy (optional LLM gateway)

An optional container that puts one OpenAI-compatible endpoint in front of many LLM providers
(AWS Bedrock, Azure OpenAI, Google Vertex AI, Cohere, Mistral, Groq, ...). The AI assistant
talks to it through its existing `openai_compat` provider, so **no application code change is
needed**. The real provider credentials live in this container, not in the app.

```
Auxilium Manus --(OpenAI format, /v1/chat/completions)--> LiteLLM proxy --(native API)--> provider
   openai_compat adapter                                   holds the provider keys
```

The Anthropic, Gemini and OpenAI providers are natively supported and do not need this. Use the
proxy for providers the app has no adapter for. Background and trade-offs:
`doc/ai_integration/AI_ASSISTANT.md` §3.1.

## Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | The `litellm` proxy (port 4000 on `127.0.0.1`, `backend` network) and its `litellm-db` PostgreSQL (`postgres:17-alpine`, private network, named volume) |
| `config.yaml` | Models exposed by the proxy (edit this) |
| `.env.example` | Template for `.env` (master key, database password, provider credentials) |

There is nothing to build: the compose file pulls the upstream images `ghcr.io/berriai/litellm`
and `postgres:17-alpine`.

## Install

Prerequisite: the app stack's `backend` network must exist. It is created the first time
`docker/docker-compose.yml` is brought up. Running this standalone? Create it once:

```bash
docker network create backend
```

1. Create the env file and fill it in:
   ```bash
   cd docker/litellm-proxy
   cp .env.example .env
   ```
   - `LITELLM_DB_PASSWORD` is required: `openssl rand -hex 16` (hex only, it goes into a URL).
     Set it before the first start; changing it later does not alter the existing data volume.
   - `LITELLM_MASTER_KEY` is required, must start with `sk-`, and is the key the app sends:
     `echo "sk-$(openssl rand -hex 24)"`
   - Set only the provider credentials you use.
2. Edit `config.yaml`. Each entry's `model_name` is the name you enter in the app. Replace the
   `<bedrock-model-id>` / `<your-deployment-name>` placeholders and delete entries you don't use.
   Provider syntax: https://docs.litellm.ai/docs/providers. Pick models with reliable
   tool/function calling; the assistant is a tool-using agent.
3. Start it:
   ```bash
   docker compose up -d
   ```
   The proxy waits for the database healthcheck and creates its schema on first start.
4. Verify:
   ```bash
   curl -s http://127.0.0.1:4000/health/liveliness
   curl -s http://127.0.0.1:4000/v1/models -H "Authorization: Bearer $LITELLM_MASTER_KEY"
   docker compose exec litellm-db pg_isready -U litellm -d litellm
   ```
   The admin UI is at http://127.0.0.1:4000/ui (log in with the master key).

## Connect the app

Settings → **AI Assistant** (setting the base URL is admin-only):

| Field | Value |
|-------|-------|
| Provider | `openai_compat` |
| Base URL | `http://litellm:4000/v1` (backend in a container on the `backend` network) or `http://127.0.0.1:4000/v1` (backend run natively) |
| API key | the value of `LITELLM_MASTER_KEY` |
| Model | a `model_name` from `config.yaml` |

The base URL goes through the backend's outbound URL policy (`base_url_policy.py`):
- Loopback is rejected by default. For a native backend on the host, set
  `ALLOW_LOOPBACK_SOURCE_URLS=true` in `backend/.env` (local lab only).
- Outside `ENV=development` an API key is only sent to an `https` URL, so put the proxy behind
  TLS for anything beyond a lab.

## Operate

```bash
docker compose logs -f litellm   # logs
docker compose restart litellm   # after editing config.yaml
docker compose pull && docker compose up -d   # upgrade
docker compose down              # stop and remove (keeps the database volume)
docker compose down -v           # also deletes the database volume (keys, spend history)
docker compose exec litellm-db pg_dump -U litellm litellm > litellm-backup.sql   # backup
```

## Security notes

- The proxy sees every prompt and every provider key. Treat it as a trusted component.
- Pin the image in `docker-compose.yml` to a reviewed tag or `@sha256` digest instead of
  following `main-stable`, and review release notes before upgrading.
- The port is published on `127.0.0.1` only. Don't expose it to the LAN without TLS and network
  controls.
- The bundled database (`litellm-db`) is only on the private `litellm` network (`internal: true`,
  no published port, not on `backend`). Its data lives in the `litellm_db_data` volume; back it up
  if you issue virtual keys. Models are still defined in `config.yaml`, not in the database.
- With the database you can issue per-user virtual keys (Admin UI or `/key/generate`) and give
  the app one of those instead of the master key.
- `.env` is gitignored. Never commit it.

## Limitations

The proxy translates every provider to the OpenAI format, which can drop provider-specific
state (e.g. Anthropic thinking blocks, Gemini thought signatures) in multi-step tool loops.
Test a multi-step tool use scenario with each model before relying on it. For Anthropic and
Gemini, prefer the native providers.
