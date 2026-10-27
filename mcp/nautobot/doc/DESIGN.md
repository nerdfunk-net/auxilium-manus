# Nautobot MCP Server — Design

Status: discussion, no code yet. Last updated 2026-10-27.
Facts about the Nautobot instance are in [NAUTOBOT_FINDINGS.md](NAUTOBOT_FINDINGS.md).

## Goal

A read-only MCP server (official Python SDK, `FastMCP`) that lets an LLM query Nautobot.

Scope of v1:
- **Organization**: locations, location types, tags, statuses, roles
- **DCIM**: devices (plus device types and platforms as filter vocabulary)
- **IPAM**: IP addresses, prefixes

Later: writes, VLANs, interfaces, circuits, and so on.

## Placement

Standalone project in this repo, `mcp/nautobot/`, following the `agent/<name>/` convention:
own requirements, own `ruff.toml`, own CI matrix entry. It does **not** import `backend/`.

`backend/services/nautobot/client.py` depends on `core.ssl_config`, `core.safe_urls`,
`models.failure` and `services.network.transport_failure`, so it is not reusable as is.
The server gets a small dedicated async client (httpx + GraphQL). We copy ideas from the
backend (query shapes, pagination), not imports.

## The core question: mapping human text to queries

**The server does not parse natural language.** The calling LLM does that. "German routers"
and "network devices of Germany" are both turned into structured tool arguments by the
client model. The server's job is to make that translation easy and hard to get wrong.

The hard problem is **vocabulary**, not language. What "Germany" and "router" mean is
specific to each Nautobot instance. The test instance shows this: devices have the role
`Network`, not `Router`, and locations are called `Country A`, not `Germany`.

### Design rules

1. **Typed tools with a closed filter set.** The LLM never writes GraphQL. The server owns a
   whitelist mapping each tool parameter to a Nautobot filter and builds the query itself.
   Unknown parameters are rejected.
2. **Vocabulary discovery tools.** `list_roles`, `list_statuses`, `list_location_types`,
   `list_tags`, `list_locations` return the real names in this instance. Roles and statuses
   take a `content_type` parameter (for example `dcim.device`), because unscoped lists mix
   IPAM and DCIM entries.
3. **Dynamic server `instructions`.** Built at startup from live vocabulary (short TTL cache),
   for example: "device roles: Network, Server, lab; location types: Country > State > City >
   Building > Room". Most requests then need no discovery call.
4. **Tolerant resolution with guiding errors.** Parameters accept name or UUID,
   case-insensitive. A miss never returns a silent empty list. It returns
   `No role 'router'. Closest: 'Network'. Available: Network, Server, lab`, so the LLM can
   retry. Fuzzy matching (`rapidfuzz`) over the cached vocabulary; no embeddings.
5. **Tool descriptions carry the semantics.** Each parameter documents accepted values and
   examples. The location filter is documented as including child locations.
6. **Responses are self-describing.** Every list response returns `items`, `returned`,
   `has_more`, and the `applied_filters` (with resolved names), so the LLM can state its
   interpretation to the user.
7. **No synonym tables in code.** They go stale and differ per installation.

### Decided: "router" (2026-10-27)

Where the data does not use a role called `Router`, a word like "router" may live in the
role, the device type or the platform. **v1 uses discovery tools plus LLM reasoning only.**

A `search_devices(text)` tool is deferred. It is purely additive: a new tool beside
`list_devices`, reusing the same client, vocabulary cache and response envelope, so it can be
added later without changing existing tools. Nautobot's `q` filter on devices is the
building block.

### Decided: dynamic instructions (2026-10-27)

The server `instructions` are built at startup from the live vocabulary (device roles,
location types, statuses). A short TTL cache refreshes the vocabulary; if Nautobot is
unreachable at startup, the server starts with static instructions and reports the failure
through tool errors, not a crash.

### Consequence of the live checks: validate before querying

Nautobot fails the whole query when any filter value is not a known name
(see NAUTOBOT_FINDINGS.md). Therefore every name parameter is resolved against the cached
vocabulary **before** the GraphQL call, and a miss returns the guiding error from rule 4.

## Proposed v1 tools (draft)

| Tool | Main parameters |
|------|-----------------|
| `list_locations` | `location_type`, `parent`, `status`, `tag`, `name_contains`, `limit`, `offset` |
| `get_location` | `location` (name or id) |
| `list_location_types` | — |
| `list_roles` | `content_type` |
| `list_statuses` | `content_type` |
| `list_tags` | `content_type` |
| `list_devices` | `location`, `role`, `status`, `tag`, `device_type`, `platform`, `name_contains`, `limit`, `offset` |
| `get_device` | `device` (name or id) — includes interfaces and IPs |
| `list_device_types`, `list_platforms` | — (vocabulary) |
| `list_prefixes` | `prefix`, `location`, `status`, `role`, `namespace`, `tag`, `limit`, `offset` |
| `list_ip_addresses` | `address`, `parent_prefix`, `status`, `role`, `namespace`, `tag`, `device`, `limit`, `offset` |
| `search` (maybe later) | `text` — across the above |

## Technical decisions

- **GraphQL for reads** (field selection, nesting). REST only where GraphQL lacks something,
  chiefly **total counts**: GraphQL has `limit`/`offset` but no total. Approach: fetch
  `limit + 1` to compute `has_more`; use REST `count` only if an exact total is needed.
- **Auth**: Nautobot API token from env (`NAUTOBOT_URL`, `NAUTOBOT_TOKEN`), validated at
  startup. Optional `NAUTOBOT_VERIFY_SSL`. The server never logs the token.
- **Limits**: default page 50, hard max 200. No tool returns "everything".
- **Transport**: stdio first; streamable HTTP later if the server is shared.
- **Errors**: tool errors are short, actionable messages for the LLM. No raw exception text
  and no stack traces.

## SDK notes (official `mcp` 2.3.0, pinned)

- 2.x renamed `FastMCP` to **`MCPServer`**: `from mcp.server.mcpserver import MCPServer`.
  `mcp.server.fastmcp` no longer exists. Most online examples still show the 1.x import.
- `instructions` is a **constructor argument** and a read-only property afterwards. So the
  dynamic instructions are built *before* the server object: fetch the vocabulary once in
  `main()`, then `MCPServer(name, instructions=...)`. They stay fixed for that session.
  The TTL cache only refreshes the vocabulary used for **validation** inside the tools.
- Tools: `@server.tool(annotations=ToolAnnotations(readOnlyHint=True))`. Run with
  `server.run("stdio")`.
- Tests: `mcp.client.Client(server)` talks to a server in memory (`InMemoryTransport`), so
  tool tests need no subprocess or network.

## Project layout and conventions

Mirrors `agent/<name>/`: `requirements.txt`, `requirements-dev.txt`, `ruff.toml`
(py312, same rules as the agents), `pytest.ini`, `.env.example`, local `venv/` (ignored).
Python 3.12. Package `nautobot_mcp/`:

| Module | Role | Status |
|--------|------|--------|
| `config.py` | env to frozen `Config`, fail fast, token hidden from `repr` | done |
| `vocabulary.py` | `Vocabulary.resolve()`: case-insensitive, "Closest/Available" errors | done |
| `vocabularies.py` | `LocationDirectory` (name / `A → B` path / id, ambiguity), TTL `VocabularyCache`, specs | done |
| `client.py` | async GraphQL client, token auth, `list_page` (limit+1 for `has_more`), `list_all`, safe errors | done |
| `context.py`, `server.py` | `AppContext`, `build_server()` registers the tool groups | done |
| `instructions.py` | live-vocabulary instructions, static fallback if Nautobot is down | done |
| `__main__.py` | `python -m nautobot_mcp`, stdio, logs to stderr, exit 2 on bad config | done |
| `tools/common.py` | `@guarded` (domain errors to `ToolError`), `envelope()`, `Limit`/`Offset` | done |
| `tools/organization.py` | `list_locations`, `get_location`, `list_location_types`, `list_roles`, `list_statuses`, `list_tags` | done |
| `tools/dcim.py` | `list_devices`, `get_device`, `list_device_types`, `list_platforms` | done |
| `networks.py` | validates addresses/prefixes before any query (`InvalidInputError`) | done |
| `tools/ipam.py` | `list_ip_addresses`, `list_prefixes`, `list_namespaces` | done |

Deviation from the first draft: "did you mean" uses stdlib `difflib`, not `rapidfuzz`
(no extra dependency; vocabularies are small).

### Behaviors worth knowing

- **Only `ToolError` text reaches the model.** Any other exception becomes a bare
  "Error executing tool X". `@guarded` converts `UnknownNameError`, `AmbiguousNameError`
  and `NautobotError`; argument bounds (`limit` 1-200) are enforced by pydantic and are
  anticipated errors too.
- **Filters are validated before the call.** A bad name never reaches Nautobot
  (asserted in the tests: no page call is made).
- **Locations resolve to ids.** A parent is sent to Nautobot as a UUID (accepted by the
  `location` and `parent` filters), so duplicate names cannot match the wrong place.
- **Tags/statuses are scoped by content type** (`dcim.location`, ...). In the dev
  instance no tag applies to locations, so `list_locations(tag=...)` answers
  "No dcim.location tag 'lab'. None exist in this Nautobot."
- **Tests use the real MCP protocol in memory**, one connection per call (`McpHarness` in
  `tests/conftest.py`); a long-lived `Client` fixture crosses anyio task scopes and fails.

### Quality gate

126 tests, 100% coverage (CI enforces `--cov-fail-under=100`), `ruff check` clean,
`pip-audit` clean. Verified end to end against the live dev instance: the server was started
as a subprocess over stdio and driven by an MCP client (instructions, all organization tools,
a typo suggestion, a path lookup, devices by country including child locations, the "router" miss, prefixes and IPs by namespace/device/network, invalid-input rejection).

### DCIM notes

- `list_devices(location=...)` sends the location **id**; Nautobot includes child locations
  (live: `Country A` returns the devices in `City A`).
- `device_type` filters by **model name**, `platform` by name (both verified live).
- `get_device(name)` looks the id up first. Device names are unique only per location, so a
  repeated name returns the candidates with location and id. At most 100 interfaces are
  returned (`interface_count`, `interfaces_truncated` say when it was cut).
- Known gap: two manufacturers can share a device type model name; the model filter would
  then be ambiguous. Not handled yet (no such data to test against).

### IPAM notes

- **Nautobot silently ignores some invalid values**: `prefixes(contains: ["zzz"])` returned
  *every* prefix, and `ip_addresses(device: ["nope"])` returns nothing without an error. A
  model could report "all prefixes contain zzz". So `networks.py` validates every address and
  prefix first, and rejects with an example; nothing invalid reaches Nautobot.
- **`ip_addresses(device:)` works by exact name only** (a UUID matches nothing). `device_name()`
  in `tools/dcim.py` resolves a name or id to the exact name; repeated names are reported as
  ambiguous, as in `get_device`.
- `address` accepts `10.0.0.2` and `10.0.0.2/24`; `prefix` on IPs means "inside this
  network"; prefix `within` maps to `within_include` (includes the network itself).
- Namespaces are a vocabulary of their own (`Global`, `black` in the dev data).
- **Unverified:** whether the prefix `location` filter includes child locations (no prefix is
  assigned to a location in the dev data). The tool description says so.
- No `get_ip_address` / `get_prefix`: the list tools with an exact `address` / `prefix` filter
  cover it.

## Remote access (HTTP) — implemented

MCP servers run locally (stdio, spawned by the client) or remotely (streamable HTTP). Some
clients run in Docker containers, so HTTP is needed. Both transports exist (`MCP_TRANSPORT`).

### Two separate authentication layers

```
MCP client --(A: client to MCP server)--> nautobot-mcp --(B: Token auth)--> Nautobot
```

- **B** exists: `NAUTOBOT_TOKEN`, a read-only Nautobot token held by the server.
- **A** does not exist for stdio, because whoever can start the process already has access.
  Over HTTP it is mandatory. The server must refuse to start in HTTP mode without it, so an
  unauthenticated port can never expose the inventory.

### Layer A: static bearer tokens (v1)

- Client sends `Authorization: Bearer <token>`; unknown or missing token gives HTTP 401.
- One token per client, so each can be revoked on its own. Tokens come from a secret
  (env var or file), are compared in constant time, and are never logged.
- TLS ends at a reverse proxy in front of the container; the server itself speaks plain HTTP
  on the Docker network.
- Later option: OAuth 2.1 as in the MCP spec (SDK: `TokenVerifier`, `AuthSettings`) if the
  existing OIDC provider should issue the tokens.
- **Decided: own ASGI middleware** (`http_auth.py`), not `AuthSettings`. The SDK's auth
  requires an OAuth `issuer_url` and advertises it in the protected-resource metadata, which
  would announce a fake authorization server for static tokens.
- Tokens are compared as SHA-256 digests with `hmac.compare_digest` over all clients (no
  early exit). `GET /healthz` is the only unauthenticated path.

### Which Nautobot identity is used

**Shared service token (v1):** every client sees what the read-only token sees. The location
and role caches are shared safely.

Rejected for now: passing each client's own Nautobot token through. Nautobot would enforce
per-user permissions, but every cache (locations, roles, ...) would have to be keyed per
token, otherwise one user's visible data leaks to another. Revisit if per-user permissions
become a requirement.

### Implementation notes (verified)

| Module | Role |
|--------|------|
| `http_config.py` | `HttpConfig`: host/port, allowed hosts, client tokens; fails fast (no token, short or duplicate token, public bind without `MCP_ALLOWED_HOSTS`) |
| `http_auth.py` | `BearerTokenMiddleware` |
| `http_app.py` | `build_http_app()`: stateless MCP app with DNS-rebinding protection, behind the middleware |
| `__main__.py` | `MCP_TRANSPORT` switch; `_serve_http` runs uvicorn (`server_header=False`) |

Tested with a real uvicorn socket (valid token, 401, 421, `/healthz`) and end to end as a
separate process against the dev Nautobot (token absent from the server log).
Docker: `Dockerfile`, `entrypoint.sh` (optional company CAs like the agents), `.dockerignore`,
`docker-compose.example.yml` (own network `nautobot-mcp`, file secret for the tokens, read-only
root, `cap_drop: ALL`, `no-new-privileges`, `pids_limit`, `mem_limit`, no published port) and
`check-image.sh` (CI smoke test without a Nautobot). Verified: built, started through compose
against the dev Nautobot via `host.docker.internal`, healthy, uid 999, read-only filesystem,
and a second container on the same network got 401 without a token and live results with one.
Not done: per-client rate limits, TLS in the server itself.

### HTTP deployment checklist

- Bind `0.0.0.0` inside the container; publish the port only on the Docker network or behind
  the TLS proxy.
- DNS-rebinding protection (`TransportSecuritySettings`) rejects unexpected `Host` headers.
  Container clients call the service as `nautobot-mcp:8000`, so `allowed_hosts` must list
  it (and the public name behind the proxy).
- `stateless_http=True` lets several replicas run without sticky sessions.
- Per-client rate limits; access logs without tokens or query contents.
- A `Dockerfile` and a compose entry modeled on the agents' (`agent/*/Dockerfile`): done.
- Config additions: `MCP_TRANSPORT` (`stdio` default | `http`), `MCP_HOST`, `MCP_PORT`,
  `MCP_ALLOWED_HOSTS`, `MCP_CLIENT_TOKENS`.

### Open decisions

1. Who are the Docker clients (own app such as the AI assistant, or third-party tools)?
   Third-party tools may expect OAuth rather than a static header.
2. Is one shared view of Nautobot acceptable?
3. Does the existing Docker setup already have a TLS reverse proxy?

## Next steps

1. Per-client rate limits for the HTTP transport.
2. Deferred: `search_devices(text)` using Nautobot's `q` filter.
