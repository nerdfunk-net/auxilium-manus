# Agent integration (Route to Agent)

The **Route to Agent** workflow step (`route-to-agent`, palette category *Routing*) sends data the
workflow already holds to an **agent**: a small Python service you run, which executes a named
handler and returns JSON. The workflow writes the declared keys of that answer into an attribute
bag, so later steps use it like any other attribute.

Use it when the logic is too complex for expressions, filters or Jinja: for example, look at the
Nautobot attributes of a device and derive a location name from a naming convention.

Read this file before changing anything under `backend/services/agents/`,
`backend/workflow_steps/route_to_agent/`, `backend/routers/sources/agent/`, `agent/` or
`docker/redis/`. The operator-facing guide for writing handlers is `agent/README.md`.

## Contents

1. [How it works](#how-it-works)
2. [Security model](#security-model)
3. [The message envelope](#the-message-envelope)
4. [Transports](#transports)
5. [Setting it up](#setting-it-up)
6. [The step](#the-step)
7. [The agent](#the-agent)
8. [Failures and what they mean](#failures-and-what-they-mean)
9. [Operations](#operations)
10. [Troubleshooting](#troubleshooting)
11. [Known limits and deliberate decisions](#known-limits-and-deliberate-decisions)
12. [Where the code is](#where-the-code-is)

## How it works

```
 workflow run (Hatchet worker)                         agent (your host or container)
┌───────────────────────────────────┐                ┌─────────────────────────────────────┐
│ route-to-agent step               │                │ manus_agent                         │
│  per device:                      │                │  open envelope (secret, agent id,   │
│   resolve selected inputs         │   sealed       │   direction, expiry, replay)        │
│   AgentClient.invoke(handler, …)  │──────────────▶ │  run handler(params, inputs)        │
│   verify + unpack the answer      │ ◀────────────  │  seal the answer                    │
│   write declared keys to a bag    │   sealed       │ handlers/*.py  (your code)          │
└───────────────┬───────────────────┘                └──────────────▲──────────────────────┘
                │  HTTP:  POST {url}/v1/invoke                      │
                └─ Redis: manus-agent:<id>:req / :resp:<cmd> / :hb ──┘   (the app's Redis)
```

- An **agent source** (Settings → Sources → Agents) says how to reach one agent: transport,
  agent id, the shared secret (a global `shared_secret` credential) and per-agent limits. It is a
  Settings row `sources.agent.<id>`, like the other sources; there is no table.
- The **step** is configured with the source, a handler name, static `params`, the inputs to send
  and the output keys it accepts.
- The **agent** only runs handlers that exist in its own `handlers/` directory. The app sends a
  handler **name** and data, never code.
- Calls are **per device**. They run concurrently up to the agent's `max_concurrency`.

## Security model

What must hold: only the app can make the agent do anything, only the agent can answer the app,
and the content (attribute bags, configs, command output, which may contain secrets) is unreadable
to anything on the path, including other users of the app's Redis.

| Property | How |
|---|---|
| Confidentiality and integrity | One AES-256-GCM envelope around the whole message |
| Only the app may call the agent | A message must open with the agent's secret; HTTP also needs a bearer token derived from it |
| Only the agent may answer | The answer is sealed with a different key (per direction); its header binds agent id, command id and direction |
| Replay | `exp` on every message plus a seen-command-id set on the agent; the app rejects answers for other commands |
| One agent cannot read another's traffic | One secret per agent; on Redis, one ACL user per agent limited to `manus-agent:<id>:*` |
| Secrets stay in the app | The step refuses secret paths and values (below) |
| The agent cannot rewrite the device | Output keys are an allow-list; the destination cannot be `device.*`, a device field, `parsed`, `run_input` or `error` |

### Secrets never leave through this step

The step applies the same rules as `store-for-report` and the persisted copy of a run:

- **Paths, checked when the step starts** (a `ValueError` fails the step): a path that is, contains
  or lies within `SECRET_BAG_PATHS` or `SECRET_BAG_SUBTREES` (`services/workflow_context/secret_fields.py`:
  `tacacs.shared_secret`, `ise.tacacsSettings.sharedSecret`, `pyats_testbed.password`,
  `nautobot.config_context`, `nautobot.local_config_context_data`). This includes a **parent**: selecting
  the bag root `nautobot` would carry `config_context` along, so it is refused. Any path segment that
  names a secret (`password`, `*_token`, `*_secret`, `*_key`, ...) is refused too.
- **Values, checked per device**: a sealed secret anywhere in a selected value fails the device with
  `source_sealed`; a non-empty value under a secret-looking key inside a selected structure fails it with
  `source_secret`.
- The agent's own **handlers are trusted code** and may see whatever you select. Handler exception
  messages (200 characters at most) are stored on the device and shown in the run view, so they must not
  contain secrets or device content.

### What is not protected

- The agent host: anyone who controls it holds the secret and sees the data sent to it.
- Plain HTTP between the app and an agent on the same Docker network is acceptable because the payload is
  encrypted, but the metadata is visible: agent id, command id, timestamps, message sizes and timing (the
  handler name is inside the ciphertext). Put TLS in front of an agent that is reachable from elsewhere.
- Replay protection is in the agent's memory, see [limits](#known-limits-and-deliberate-decisions).

## The message envelope

`backend/services/agents/envelope.py` is the reference; `agent/manus_agent/envelope.py` is a standalone
copy (the agent must not import the backend). `backend/tests/unit/test_agent_envelope_sync.py` fails when
they drift, and the same test vectors (`backend/tests/unit/fixtures/agent_envelope_vectors.json`, copied to
`agent/tests/fixtures/`) are run by both suites. **Change both together**, then regenerate the agent copy
(it differs only in the `MIN_AGENT_SECRET_LENGTH` import line).

```json
{"v": 1, "agent_id": "geo-agent", "command_id": "<uuid hex>", "direction": "request",
 "iat": 1700000000, "exp": 1700000035, "nonce": "<b64url 12 bytes>", "ct": "<b64url ciphertext+tag>"}
```

- **Key**: HKDF-SHA256 over the agent secret, `info = "manus-agent/v1/<direction>/<agent_id>"`, 32 bytes.
  Request and response use different keys. The secret is generated with high entropy (at least 32
  characters, `MIN_AGENT_SECRET_LENGTH`), which is why there is no password stretching.
- **AAD**: the header (`v`, `agent_id`, `command_id`, `direction`, `iat`, `exp`) as canonical JSON, so none
  of them can change without failing the tag.
- **Validity**: a request lives for `timeout + 5` seconds; an answer for 60 seconds from the moment it was
  *produced*. A message issued more than 60 s in the future is refused (keep clocks in sync with NTP).
- **Errors never contain the secret or the payload.** `EnvelopePayloadError` (decrypts but is not a JSON
  object) is distinct from a failed tag, because the sender holds the secret.
- **HTTP token**: `base64url(HKDF(secret, "manus-agent/v1/token/<agent_id>"))`, a cheap pre-filter so the
  agent drops garbage before decrypting. It is not the security boundary.

Decrypted payloads:

```jsonc
// request
{"handler": "resolve_location", "params": {"strict": true},
 "inputs": {"attributes": {"nautobot.location.name": "Berlin-DC1"},
            "content":    {"running_config": "…",
                           "command_output:<node_id>": [{"command": "show version", "output": "…"}]}}}
// response
{"status": "success", "output": {"location": "Berlin"}}
{"status": "error",   "output": null, "error": {"type": "KeyError", "message": "…"}}
```

## Transports

`AgentTransport` (`services/agents/transport.py`) moves one sealed envelope and returns the sealed answer;
it never looks inside. `AgentClient` (`client.py`) owns the limits, the envelope and the error mapping, so
a new transport (a pull model is the obvious next one) does not touch the step or the protocol.

### HTTP

`POST {url}/v1/invoke`, body = envelope, `Authorization: Bearer <token>`. The URL is validated with
`validate_outbound_http_url` (no loopback unless `ALLOW_LOOPBACK_SOURCE_URLS`, no link-local or metadata
addresses). Plain `http://` is allowed on purpose (see above); container hostnames resolve to private
addresses and pass. Redirects are not followed. Responses are capped at 16 MiB while streaming.

Agent status codes: 200 (answer, including handler errors), 400 malformed, 401 bad token (with
`WWW-Authenticate: Bearer`), 403 message failed authentication, 409 replayed, 413 too large.
`GET /healthz` returns `{"status": "ok"}` without authentication.

### Redis

The agent connects to the **app's Redis** and uses keys under `manus-agent:<agent_id>:`:

| Key | Type | Written by | Notes |
|---|---|---|---|
| `req` | list | app `RPUSH`, agent `BLPOP` | one list for every in-flight call |
| `resp:<command_id>` | list | agent `RPUSH`+`EXPIRE` (2 min) | single use; the app `BLPOP`s then deletes it |
| `hb` | hash | agent `HSET`+`EXPIRE` (90 s) | `status`, `agent_id`, `version`, `handlers` (comma list), `last_heartbeat` |

- **Why lists, not pub/sub**: a request waits until the agent takes it, an answer cannot be missed by
  subscribing late, and nobody else sees another agent's channel.
- **Fail fast**: the app checks `hb` first; no heartbeat means `agent_offline` immediately, without queueing.
- **Timeout**: the app withdraws its request (`LREM`) and deletes the answer key; the envelope's `exp` makes
  an agent that comes back later discard anything stale.
- **Queue TTL** is set with `EXPIRE … NX` and then `GT`, so a short call can never shorten the TTL of a long
  call queued behind a busy agent. This needs **Redis 7 or newer** (the compose file uses `redis:8`).
- **Capacity**: the agent pulls a request only when it has a free slot, so surplus work stays in Redis.
- **Response size**: the agent enforces `MANUS_AGENT_MAX_RESPONSE_BYTES` (default 16 MiB); the app also
  refuses an oversized value before parsing it. The agent-side limit is the real bound, because the Redis
  client has already read the value by then.
- **ACL**: each agent gets its own Redis user limited to its keys and to
  `+blpop +rpush +hset +expire +del +ping`. With a secret mismatch the agent cannot verify a message and stays
  silent, so the app sees a **timeout**, not an auth error.

## Setting it up

### 1. Secret

Settings → Credentials → add a **shared secret** credential, *global* visibility, with at least 32 random
characters:

```bash
openssl rand -base64 32
```

Use one secret per agent.

### 2. Agent source

Settings → Sources → Agents → Add agent: source id, transport, **Agent ID** (lowercase, equals
`MANUS_AGENT_ID` on the agent), the URL (HTTP) and the credential. Limits (defaults): 4 parallel calls,
1 MiB per request, 60 s maximum timeout. A secret below 32 characters is refused when the source is saved.
Permissions: `sources.agent` `read` / `write` / `delete`; writes are admin-only (RBAC rule P3). The seeded
`viewer` role does not get `read`. The step editor lists agents through `GET /sources/agent`, so a user who
edits workflows needs `sources.agent:read` (grant it to their role), as for every other source type. Running a
workflow needs no such permission: the worker resolves the source itself. Without the permission the editor
says so and keeps the saved agent visible; see `doc/OPEN_TODOS.md`.

### 3. Run the agent

Standalone (`agent/README.md`): `python -m manus_agent` with `MANUS_AGENT_ID`, `MANUS_AGENT_SECRET` and
`MANUS_AGENT_HTTP_PORT` and/or `MANUS_AGENT_REDIS_URL`.

On the application's Docker host:

```bash
cd docker
cp docker-compose.agent.example.yml docker-compose.agent.yml
mkdir agent-handlers && cp ../agent/handlers/examples.py agent-handlers/
# docker/.env: MANUS_AGENT_ID, MANUS_AGENT_SECRET (and MANUS_AGENT_REDIS_PASSWORD for the Redis transport)
docker compose -f docker-compose.yml -f docker-compose.agent.yml up -d --build
```

The agent joins the internal `data` network: the app reaches it at `http://manus-agent:8080`, and it reaches
Redis at `manus-redis`, without publishing a port.

### 4. Redis users (Redis transport only)

`docker/redis/start.sh` runs as the entrypoint of `manus-redis` and writes `/data/users.acl` on **every
start**: the `default` user with the password from `MANUS_REDIS_PASSWORD`, then the `user` lines from
`docker/redis/agents.acl` (git-ignored; start from `agents.acl.example`). Add one line per agent, then
`docker compose restart manus-redis`:

```
user agent-geo-agent reset on #<sha256 of the agent's redis password> ~manus-agent:geo-agent:* +blpop +rpush +hset +expire +del +ping
```

The Settings dialog shows the same command for the agent id you typed (it starts with `reset`, so running
it again replaces any earlier key patterns, commands and passwords of that user).

> **Why the file is generated.** Loading an ACL file replaces the `default` user, and a file without a
> `default` line leaves it as `nopass`. A plain `--aclfile` next to `--requirepass` would therefore silently
> remove the password of the app's Redis (verified against `redis:8-alpine`). `start.sh` always writes the
> `default` line itself and ignores a `user default` line in `agents.acl`. An invalid line makes Redis refuse
> to start and name the line. Users added at runtime with `ACL SETUSER` are lost on restart unless they are
> also in `agents.acl`; do not rely on `ACL SAVE`, the file is rewritten at the next start.

### Agents on another host

The compose network is internal on purpose and Redis is not published. An agent on a different host needs
the app's Redis (or an HTTP path to the agent) over a private network or VPN, with TLS (`rediss://`, or HTTPS in
front of the agent). That is a decision for your environment and is **not** configured by this repository.
Never publish Redis to the internet. The per-agent ACL limits what a stolen agent can do; it does not make an
unauthenticated network path safe.

### 5. Verify

Edit the source and press **Test connection**: an encrypted `echo` with a fresh nonce through the configured
transport. For a Redis agent the dialog also shows the heartbeat (online, version, handlers). Success proves
transport, secret, agent id and handler execution at once.

## The step

Registry id `route-to-agent`, name *Route to Agent*, `requires: [identity]`, `produces: [attributes]`,
outcomes `success` and `failure`. It only **enriches**: the agent cannot choose an outcome. Like the other
enrichment steps it always emits `success` (possibly with no devices) and `failure` when a device failed.

| Field | Meaning |
|---|---|
| `agent_source_id` | the agent source |
| `handler` | handler name on the agent (`[A-Za-z][A-Za-z0-9_.-]{0,63}`) |
| `params` | static JSON object, at most 16 KiB, not templated, not for secrets |
| `input_paths` | attribute paths to send (bags, `parsed.*`, `device.*`); unresolved paths are left out; structured values keep their shape |
| `content_inputs` | `running_config`, `startup_config`, `latest_command_output`, `command_output:<node_id>` (a list of `{command, output}` in execution order) |
| `destination_path` | `bag.field`, for example `agent.geo`; written as real nested dicts, so `agent.geo.location` resolves |
| `output_keys` | the only keys the agent may return (plain names, no dots) |
| `allow_missing_outputs` | accept an answer that leaves out some declared keys (default false) |
| `timeout_seconds` | 1–600 per device (default 30); above the agent source's maximum fails the step before anything is sent |

At least one of `input_paths` and `content_inputs` is required. Output values must be JSON, at most
`STEP_OUTPUT_VALUE_MAX_BYTES` each and `STEP_OUTPUT_MAX_BYTES` in total, nested at most 8 levels; an undeclared
key, a missing key (unless allowed), a dotted key name or an oversized value fails the device with
`output_rejected` and a message that does not echo the values.

If the agent is **offline** or **rejects the secret**, the devices not yet sent fail immediately with the same
cause instead of waiting for a timeout each. A late answer is only a timeout for that device.

The editor (`frontend/src/components/features/workflow-steps/route-to-agent/`) mirrors the destination, handler
and output-key rules so a mistake shows up before a run; the backend is the authority. It does **not** mirror
the secret-path rules, which fail the step at start instead.

## The agent

`agent/` is a standalone package (Python 3.12, `cryptography`, `redis`, `aiohttp`) with its own tests, ruff
config, Dockerfile and CI (`.github/workflows/agent-ci.yml`). Layout:

- `manus_agent/envelope.py` generated copy of the backend envelope
- `manus_agent/core.py` opens a request, runs the handler, seals the answer (replay set, concurrency, limits)
- `manus_agent/http_server.py`, `redis_worker.py` the two transports; `main.py` wires them and supervises them
- `manus_agent/registry.py` the `@handler` decorator and directory loader; `handlers/examples.py`

Behaviour worth knowing:

- Authentication comes first: a message that fails it runs nothing and does not burn a command id.
- Plain-function handlers run in a thread pool sized to `MANUS_AGENT_MAX_CONCURRENCY`. A timeout cannot stop a
  thread, so the slot stays taken until the function returns: a stuck handler costs one slot (further requests
  report that the agent is busy) instead of leaking a thread per request.
- The answer is sealed **after** the handler returns, with a 60 s delivery window.
- If the Redis worker dies, the agent stops (exit 1) so a supervisor restarts it, instead of serving HTTP with
  Redis silently gone.

## Failures and what they mean

Per-device failures are `DeviceError`s with a `FailureInfo` (phase `agent`) and a `code`:

| `code` | `FailureInfo.kind` | Retryable | Meaning |
|---|---|---|---|
| `source_sealed` | `bad_request` | no | a selected value holds a sealed secret |
| `source_secret` | `bad_request` | no | a selected structure holds a value under a secret-looking key |
| `agent_offline` | `agent_offline` | yes | connection refused, or no heartbeat on Redis |
| `agent_timeout` | `timeout` | yes | no answer in time, or an answer that arrived expired |
| `agent_auth_failed` | `auth_failed` | no | the answer failed verification (wrong secret, tampered, wrong command), or HTTP 401/403 |
| `agent_transport_error` | `invalid_response` | no | HTTP error status, invalid or oversized answer, unusable payload |
| `payload_too_large` | `payload_too_large` | no | the request is above the agent's `max_request_bytes` |
| `agent_handler_error` | `agent_handler_error` | no | the handler raised, is unknown or returned something invalid |
| `output_rejected` | `output_rejected` | no | the answer broke the output contract |
| `agent_request_invalid` | `bad_request` | no | a request problem found before sending |
| `internal_error` | `internal_error` | no | a bug on our side; only the exception class name is kept |

The kinds are part of the closed vocabulary in `backend/models/failure.py`
(`doc/ai_integration/AI_ASSISTANT.md` §19).

## Operations

- **Rotating a secret** is manual and needs a short window: change the credential's value and the agent's
  `MANUS_AGENT_SECRET` together, then restart the agent. Calls in between fail as `agent_auth_failed` (HTTP) or
  time out (Redis). Overlapping old and new secrets is not implemented.
- **Redis**: the heartbeat key expires after 90 s, so an agent counts as offline 90 s after it stops. The app's
  rate limits and locks live in the same Redis; the agent users cannot touch them.
- **Logs**: the agent never logs payloads; the app logs only agent id, handler and counts.
- **Idempotence**: write handlers so that running twice is harmless (see replay below).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Test connection: "not reachable" | HTTP: wrong URL/port or the agent is not on the `data` network. Redis: the agent is down or cannot reach Redis (no heartbeat) |
| Test connection: timeout on a Redis agent | secret or Agent ID differs: the agent cannot verify the message and ignores it |
| Test connection: authentication failed (HTTP) | wrong secret or agent id; the agent answers 401/403 |
| `NOAUTH` / `NOPERM` in the agent log | Redis password or the user's ACL; check `docker/redis/agents.acl` and restart `manus-redis` |
| `ERR syntax error` on `EXPIRE` | Redis older than 7 |
| Step fails at start: "secrets are never sent" | an input path is, contains or lies within secret data; select specific non-secret values |
| Every device `agent_auth_failed` | the secret was changed on one side only |
| `output_rejected` | the handler returned a key that is not in `output_keys`, or too much data |
| `agent is busy` | handlers are stuck or slow; raise `MANUS_AGENT_MAX_CONCURRENCY` or fix the handler |
| Step fails: `timeout_seconds` above the maximum | raise the agent's max timeout in Settings → Sources or lower the step timeout |
| Redis starts but ignores a `user default` line | by design (`docker/redis/start.sh`) |

## Known limits and deliberate decisions

- **No key rotation overlap, no pull transport.** Both were scoped out of the first version; the transport
  interface leaves room for a pull model (the agent polls the app over HTTPS), which would avoid exposing Redis
  to remote agents but needs a machine-facing API on the backend.
- **Replay state is in the agent's memory.** A restart inside a request's validity window forgets which
  commands were seen, so a captured request could run again until it expires. A persistent store or a
  "refuse anything issued before the process started" rule was rejected because it would also drop requests that
  were legitimately queued in Redis during a restart. Handlers should be idempotent.
- **No DNS re-check at call time.** `resolve_connection` validates the URL without DNS, like the other sources
  (no DNS on the worker hot path; see `doc/SECURITY-NOTES.md`). The target is one fixed path, `/v1/invoke`.
- **Handler error text is stored on the device** (200 characters) because authors need it.
- **No batching.** One request per device; a fan-out of hundreds of devices means hundreds of round trips,
  bounded by the agent's `max_concurrency`.
- **`params` are static.** No templating, deliberately: another code-evaluation path.
- **Verification state.** The product owner confirmed the HTTP transport end to end (2026-10-22). The Redis
  transport, with a real `agents.acl` user on the recreated `manus-redis`, was covered by the unit suites, the
  backend↔agent interop tests (real HTTP socket, Redis through `fakeredis`) and throwaway-container tests of
  `docker/redis/start.sh`, but not yet run live. See `doc/OPEN_TODOS.md`.

## Where the code is

| What | Where |
|---|---|
| Envelope, client, transports, status | `backend/services/agents/` |
| Source config service | `backend/services/agents/source_config_service.py`, `core/source_keys.py` (`sources.agent.`) |
| Source API | `backend/routers/sources/agent/` (`crud.py`, `ops.py`: test-connection, status), `backend/models/agents.py` |
| Step | `backend/workflow_steps/route_to_agent/` (`request.py`, `output.py`, `executor.py`), `workflow_steps/common/agent_source.py` |
| Registry / dispatch | `backend/workflow_steps/registry.yaml`, `backend/services/execution/step_registry.py` |
| Failure vocabulary | `backend/models/failure.py` |
| Permissions | `backend/services/auth/rbac_seed.py` (`sources.agent`) |
| Frontend | `frontend/src/components/features/workflow-steps/route-to-agent/`, `frontend/src/components/features/settings/dialogs/agent-source-dialog.tsx`, `…/settings/components/agent-status-panel.tsx`, `…/settings/utils/agent-redis-acl.ts`, `frontend/src/hooks/queries/use-agent-sources-*.ts` |
| Agent | `agent/` |
| Redis ACL / compose | `docker/redis/`, `docker/docker-compose.yml` (`manus-redis`), `docker/docker-compose.agent.example.yml` |
| Tests | `backend/tests/unit/test_agent_*.py`, `test_route_to_agent_*.py` (incl. `test_agent_interop.py`, `test_agent_envelope_sync.py`), `agent/tests/`, frontend `route-to-agent/*.test.*`, `agent-source-dialog.test.tsx` |
