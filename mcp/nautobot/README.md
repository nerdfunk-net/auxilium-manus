# Nautobot MCP server

A **read-only** [Model Context Protocol](https://modelcontextprotocol.io) server that lets an
LLM query Nautobot: locations, devices, prefixes, IP addresses and the vocabulary around
them (roles, statuses, tags, location types, namespaces). It is a standalone project
(like `agent/<name>/`) and does not import the Manus backend.

Design, decisions and verified Nautobot behavior: [`doc/DESIGN.md`](doc/DESIGN.md),
[`doc/NAUTOBOT_FINDINGS.md`](doc/NAUTOBOT_FINDINGS.md).

## How it answers questions

The server does **not** parse natural language; the calling LLM turns "the German routers"
into tool arguments. The server makes that reliable:

- Typed tools with a fixed set of filters. The LLM never writes GraphQL.
- Every name (role, status, location, ...) is checked against this instance's real
  vocabulary first. A miss returns `No device role 'router'. Closest: …. Available: …` so the
  model can retry; nothing invalid is sent to Nautobot.
- At startup the server reads the live vocabulary into its `instructions`, so the model knows
  the roles, statuses and location types of this instance before the first call.
- Filtering by a location includes its child locations. Ambiguous names (two locations called
  "Berlin") are reported with their full paths and ids.
- Results are paged (`limit` 1-200, default 50; `has_more` tells when to ask for the next
  `offset`) and echo `applied_filters` so the model can state how it interpreted the question.

## Tools

| Area | Tool | Purpose |
|------|------|---------|
| Organization | `list_locations`, `get_location` | Location tree; filter by type, parent, status, tag, name |
| | `list_location_types`, `list_roles`, `list_statuses`, `list_tags` | Vocabulary (roles/statuses/tags take a `content_type`, e.g. `dcim.device`) |
| DCIM | `list_devices` | Filter by location (incl. children), role, status, tag, device type, platform, name |
| | `get_device` | One device with interfaces and their IPs (by name or id) |
| | `list_device_types`, `list_platforms` | Vocabulary for the device filters |
| IPAM | `list_ip_addresses` | Filter by address, prefix, device, namespace, role, status, tag, DNS name |
| | `list_prefixes` | Filter by prefix, `within`, `contains`, location, namespace, role, status, tag |
| | `list_namespaces` | Vocabulary for the namespace filters |

All tools are annotated read-only. Writes are out of scope for now.

## Install

Python 3.12, from this directory:

```bash
python3.12 -m venv venv
./venv/bin/pip install -e .
```

This installs the package into the venv (dependencies come from `requirements.txt`) and creates
the command `venv/bin/nautobot-mcp`, so the server starts from any working directory with no
`PYTHONPATH`. Clients such as Claude Desktop start it from an unrelated directory; without the
install they fail with `No module named nautobot_mcp`.

## Configuration

| Variable | Required | Meaning |
|----------|----------|---------|
| `NAUTOBOT_URL` | yes | e.g. `http://127.0.0.1:8080` (`http://` or `https://`) |
| `NAUTOBOT_TOKEN` | yes | A **read-only** Nautobot API token. Never commit it |
| `NAUTOBOT_ALLOW_INSECURE_HTTP` | no | `true` allows cleartext `http://` to a non-local host (loopback, private IPs and single-label names are always allowed) |
| `NAUTOBOT_VERIFY_SSL` | no | `false`/`0`/`no`/`off` disables certificate checks (default on) |

The server exits with code 2 and a message on stderr when a required value is missing. See
`.env.example`.

## Run (stdio)

```bash
NAUTOBOT_URL=http://127.0.0.1:8080 NAUTOBOT_TOKEN=… ./venv/bin/nautobot-mcp
```

stdout carries the MCP protocol; all logs go to stderr. (Use `MCP_TRANSPORT=http` below for remote clients.)

### Claude Code

```bash
claude mcp add nautobot \
  --env NAUTOBOT_URL=http://127.0.0.1:8080 \
  --env NAUTOBOT_TOKEN=… \
  -- /absolute/path/to/mcp/nautobot/venv/bin/nautobot-mcp
```

### Claude Desktop

Claude Desktop reads its own settings file (not part of this repo, and not Claude Code's
`~/.claude*`):

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- or in the app: **Settings → Developer → Edit Config**

The file usually exists already. **Merge** the `nautobot` entry into its `"mcpServers"` object
(create that object if it is missing) instead of replacing the file, then quit and restart
Claude Desktop. The token is stored in this file in plain text, so keep it private. Use
absolute paths:

```json
{
  "mcpServers": {
    "nautobot": {
      "command": "/absolute/path/to/mcp/nautobot/venv/bin/nautobot-mcp",
      "env": {
        "NAUTOBOT_URL": "http://127.0.0.1:8080",
        "NAUTOBOT_TOKEN": "…"
      }
    }
  }
}
```

If the log says `No module named nautobot_mcp`, the package is not installed in that venv: run
`./venv/bin/pip install -e .` in this directory. (Desktop's logs are in
`~/Library/Logs/Claude/mcp-server-nautobot.log` on macOS.)

This file starts local stdio servers. For the HTTP/Docker server use Claude Code (`claude mcp add
--transport http …` above); whether and how Claude Desktop connects to a remote server is a
setting of the app, not of this file, and has not been verified here.

## Run over HTTP (remote and Docker clients)

stdio needs no authentication because the client starts the process itself. For clients that
cannot (containers, other hosts) run the server as an HTTP service. **Every request must carry
a bearer token**; without at least one configured token the server refuses to start.

```bash
MCP_TRANSPORT=http MCP_HOST=0.0.0.0 MCP_PORT=8000 \
MCP_ALLOWED_HOSTS=nautobot-mcp:8000 \
MCP_CLIENT_TOKENS="ui=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
NAUTOBOT_URL=… NAUTOBOT_TOKEN=… \
./venv/bin/nautobot-mcp
```

| Variable | Default | Meaning |
|----------|---------|---------|
| `MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8000` | Bind address. Inside a container use `0.0.0.0` |
| `MCP_ALLOWED_HOSTS` | loopback names | `Host` headers accepted (comma separated, `name:*` allows any port). **Required** when `MCP_HOST` is not loopback: clients that call `nautobot-mcp:8000` need exactly that entry, otherwise they get 421 |
| `MCP_CLIENT_TOKENS` | – | `name=token` pairs, comma separated. One token per client (min. 32 characters, unique) so each can be revoked alone |
| `MCP_CLIENT_TOKENS_FILE` | – | File with one `name=token` per line (`#` comments); merged with the variable. Use a Docker secret |

- Endpoint: `POST/GET <host>:<port>/mcp` with `Authorization: Bearer <token>`. Unknown or
  missing token: `401`. Wrong `Host`: `421`.
- `GET /healthz` needs no token and does not touch Nautobot (for Docker health checks).
- The server is stateless (no session kept in memory), so several replicas can run behind a
  load balancer.
- The server speaks plain HTTP (see [Docker](#docker) for a container). **Terminate TLS in front of it** (reverse proxy), or keep it on
  a private Docker network. Tokens travel in a header and are only as private as the transport.
- All clients share the one read-only Nautobot token of the server; they all see the same data.
- Rejected requests are logged (peer address only); tokens are never logged.

Client configuration, for example Claude Code:

```bash
claude mcp add --transport http nautobot http://nautobot-mcp:8000/mcp \
  --header "Authorization: Bearer <token>"
```

### Docker

`Dockerfile` and `docker-compose.example.yml` run the HTTP server unprivileged (uid 999) on a
read-only root filesystem with all capabilities dropped. It keeps no state.

```bash
cd mcp/nautobot
printf 'ui=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" > mcp_client_tokens.txt
chmod 0444 mcp_client_tokens.txt        # the unprivileged container user must be able to read it
cat > .env <<'EOF2'
NAUTOBOT_URL=http://host.docker.internal:8080
NAUTOBOT_TOKEN=…read-only token…
EOF2
docker compose -f docker-compose.example.yml up -d --build
```

- `NAUTOBOT_URL` must be reachable **from the container**: `127.0.0.1` is the container itself.
  For a Nautobot on the Docker host use `http://host.docker.internal:8080` (Docker Desktop,
  OrbStack).
- Clients on the same Docker network call `http://nautobot-mcp:8000/mcp` with their token. To
  reach it from another compose project, attach that project's services to the network
  `nautobot-mcp` (`external: true`). No port is published unless you uncomment `ports:`.
- A different public name (reverse proxy) must be added to `MCP_ALLOWED_HOSTS`.
- Behind a TLS-inspecting proxy put the company root CAs (`*.crt`/`*.pem`) into `certs/` before
  building, as for the agents.
- `./check-image.sh` builds the image and smoke-tests it without a Nautobot (CI runs it).

## Develop

```bash
./venv/bin/pip install -r requirements-dev.txt
./venv/bin/ruff check .
./venv/bin/python -m pytest -q --cov=nautobot_mcp --cov-fail-under=100
./venv/bin/pip-audit -r requirements.txt
```

CI (`.github/workflows/mcp-ci.yml`) runs the same and requires 100 % coverage. The tool tests
talk to the server over the real MCP protocol in memory against a fake Nautobot
(`tests/conftest.py`); nothing needs a running Nautobot.

Rules for new tools: register them in `nautobot_mcp/tools/`, mark them read-only, validate
names through `VocabularyCache` and addresses through `networks.py` **before** calling
Nautobot, wrap them with `@guarded` (only `ToolError` text reaches the model), return
`envelope(...)`, and check the query against a live instance first.
