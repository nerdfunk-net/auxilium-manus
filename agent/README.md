# Auxilium Manus agent

A small Python service that runs **your own handlers** for the *Route to Agent* workflow step.
The step sends the attributes and content you select to a handler; the handler returns a JSON
object and the workflow writes it to an attribute bag. Use it for logic that is too complex for
expressions or templates, for example deriving a location name from Nautobot attributes.

The app sends **data, never code**: the step names a handler, and only handlers that exist in
this agent's `handlers/` directory can run.

## Security model

* Every message is one AES-256-GCM envelope, keyed (HKDF) by a secret that only the app and this
  agent know. Opening it proves who sent it and that it is untampered; the ids, direction and
  expiry are authenticated too. A response cannot be replayed as a request.
* A request is accepted once (its `command_id` is remembered until it expires) and only while
  it is valid. Keep the clocks of both hosts in sync (NTP).
* Over HTTP a bearer token derived from the secret lets the agent drop unauthenticated traffic
  early. Plain HTTP is fine inside a Docker network because the payload is encrypted;
  terminate TLS in front of the agent if it is reachable from elsewhere.
* Over Redis the agent uses its own Redis user, limited to its keys (see below), so a stolen
  agent host cannot touch the app's other Redis data or another agent's traffic.
* The agent never logs payloads. Handlers you write may see secrets that were selected as
  inputs: treat the handlers directory as trusted code.

## Run it

```bash
cd agent
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env        # edit it; export the variables or use --env-file / EnvironmentFile
set -a; . ./.env; set +a
./venv/bin/python -m manus_agent
```

In the app: **Settings → Credentials**, add a *shared secret* credential (global, 32+ random
characters: `openssl rand -base64 32`). **Settings → Sources → Agents → Add agent**: Agent ID
and the credential must match `MANUS_AGENT_ID` and `MANUS_AGENT_SECRET`. Save, then use
**Test connection**.

| Variable | Default | Meaning |
|---|---|---|
| `MANUS_AGENT_ID` | required | Lowercase id; equals the source's Agent ID. |
| `MANUS_AGENT_SECRET` | required | Shared secret, at least 32 characters. |
| `MANUS_AGENT_HTTP_PORT` | - | Enables the HTTP transport on this port. |
| `MANUS_AGENT_HTTP_HOST` | `0.0.0.0` | Bind address for HTTP. |
| `MANUS_AGENT_REDIS_URL` | - | Enables the Redis transport (`redis://`, `rediss://`, `unix://`). |
| `MANUS_AGENT_HANDLERS_DIR` | `handlers` | Directory with your handler files. |
| `MANUS_AGENT_MAX_CONCURRENCY` | `4` | Handlers running at once. |
| `MANUS_AGENT_MAX_BODY_BYTES` | 16 MiB | Largest HTTP request accepted. |
| `MANUS_AGENT_MAX_RESPONSE_BYTES` | 16 MiB | Largest answer a handler may return; above it the device fails with `InvalidOutput`. |
| `MANUS_AGENT_LOGLEVEL` | `INFO` | Python log level. |

At least one of `MANUS_AGENT_HTTP_PORT` and `MANUS_AGENT_REDIS_URL` is required.

## Writing handlers

Put a `.py` file in the handlers directory (files starting with `_` are skipped):

```python
from manus_agent.registry import handler

@handler("resolve_location")
def resolve_location(params, inputs):
    name = inputs["attributes"].get("nautobot.location.name", "")
    return {"location": name.split("-")[0]}
```

* `params` is the static JSON object configured on the step.
* `inputs` is `{"attributes": {path: value}, "content": {name: text}}`. A path or content the
  device does not have is missing, so use `.get`.
* Return a JSON object. The step only accepts the keys listed in its *output_keys*.
* `async def` handlers are supported; plain functions run in a thread, so blocking calls are
  fine. Raising an exception fails that device and shows the class and message to the user.
* A handler has until the request expires (the step's timeout); then it is reported as timed out.
  A plain function cannot be interrupted: after a timeout it keeps its slot (and its thread)
  until it returns, so a stuck handler reduces `MANUS_AGENT_MAX_CONCURRENCY` by one instead of
  piling up threads, and further requests report that the agent is busy. Give blocking calls
  their own timeouts (sockets, SSH, HTTP).
* Handlers should be **idempotent**: the replay protection is in memory, so a restart inside a
  request's validity window forgets which commands were seen and a captured request could run
  again until it expires.
* Exception messages (200 characters at most) are shown to users in the run view; keep secrets
  and device content out of them.
* `echo` is built in and returns its inputs: it is what *Test connection* calls. See
  `handlers/examples.py` for a complete example.

## HTTP transport

`POST /v1/invoke` with the envelope as the JSON body and `Authorization: Bearer <token>`.
`GET /healthz` answers `{"status": "ok"}` without authentication. Status codes: 401 bad token,
403 message failed authentication, 409 replayed, 400 malformed, 413 too large.

## Redis transport

The agent connects to the **app's Redis** and uses these keys (`<id>` is the agent id):

| Key | Type | Use |
|---|---|---|
| `manus-agent:<id>:req` | list | the app pushes requests, the agent pops them |
| `manus-agent:<id>:resp:<command>` | list | the agent pushes the answer (expires after 2 minutes) |
| `manus-agent:<id>:hb` | hash | heartbeat: status, version, handlers, last_heartbeat (expires after 90 s) |

Create a Redis user for the agent that can only do that (the dialog in the app shows the same
command for your agent id; use an ACL file so it survives restarts). `ACL SETUSER` only *adds*
rules to an existing user, so the command starts with `reset`: running it again replaces any
key patterns, commands and passwords the user had before. The app needs **Redis 7 or newer**
(`EXPIRE ... NX/GT`).

```
ACL SETUSER agent-<id> reset on ><redis-password> ~manus-agent:<id>:* +blpop +rpush +hset +expire +del +ping
```

The agent only pulls a request when it has capacity, so surplus work waits in Redis. If the
secret or Agent ID differs, the agent cannot verify a message and ignores it, so the app sees a
timeout rather than an error: check both when *Test connection* times out.

## Docker

```bash
docker build -t manus-agent .
docker run --rm --env-file .env -p 8080:8080 -v "$PWD/handlers:/app/handlers:ro" manus-agent
```

On the app's Docker network use `http://<container-name>:8080` as the agent URL.

## systemd

See `manus-agent.service` (user `manus-agent`, code in `/opt/manus-agent`, variables in
`/etc/manus-agent/agent.env`, mode 0600).

## Tests

```bash
pip install -r requirements-dev.txt && pytest
```

`manus_agent/envelope.py` is a standalone copy of `backend/services/agents/envelope.py`
(the agent must not import the backend). `backend/tests/unit/test_agent_envelope_sync.py` fails if
they drift apart, and `backend/tests/unit/test_agent_interop.py` runs the app's client against
this agent over HTTP and Redis.
