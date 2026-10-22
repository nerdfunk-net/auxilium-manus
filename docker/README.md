# Auxilium Manus Docker Deployment

Docker files for building and running Auxilium Manus in development and air-gapped production environments.

Running the application requires **two pieces**:

1. **The application image** — frontend, backend API, and Hatchet worker (built from this directory).
2. **Hatchet** — workflow orchestration engine (started separately from `docker/hatchet/`).

PostgreSQL and Redis are bundled in the application `docker-compose.yml`. Hatchet brings its own PostgreSQL and RabbitMQ on the private `internal` network.

**Optional:** `docker/pyats/` runs Cisco pyATS/Genie in its own container behind a thin HTTP shim, for pyATS-backed workflow steps and the pyATS source under Settings → Sources. See `docker/pyats/README.md` and `doc/PYATS_INTEGRATION.md`.

## Quick start (development)

### 1. Create Docker networks

Create the one external network once (the Hatchet compose project creates its own private
`internal` network):

```bash
docker network create --internal hatchet 2>/dev/null || true
```

| Network | Purpose |
|---|---|
| `internal` | Created by the Hatchet compose project: Hatchet private infra (postgres, rabbitmq, migrate, setup) |
| `hatchet` | External, `--internal`: engine ↔ `manus-web` / `manus-worker` / `manus-background-worker` (no outside routing) |
| `data` | Created by the app compose project, internal only: postgres, redis, web, workers. Postgres and Redis are on this network only. |
| `ingress` | App compose: `manus-web` only. Your reverse proxy joins it, or uses the published `127.0.0.1:3000`. |
| `egress` | App compose: the two workers (outbound to devices, Nautobot, git remotes). |

An optional Route to Agent agent (`docker-compose.agent.example.yml`) joins `data`, so the app reaches it at
`http://manus-agent:8080` and it reaches `manus-redis` without publishing a port.

### 2. Start Hatchet

```bash
cd docker/hatchet
cp .env.example .env
# edit .env: HATCHET_DB_PASSWORD and HATCHET_RABBITMQ_PASSWORD (openssl rand -hex 24),
# HATCHET_ADMIN_EMAIL and HATCHET_ADMIN_PASSWORD (the dashboard login; there is no default).
# The password needs 8-64 characters with an upper-case letter, a lower-case letter and a digit,
# for example "Aa1-$(openssl rand -hex 12)"; otherwise hatchet-setup-config exits with an error
# (fix .env, run `docker compose down -v`, start again).
docker compose up -d
```

Wait ~60 seconds for `hatchet-setup-config` to finish and `hatchet-dashboard` to become healthy.

**First-time Hatchet setup:**

1. Create an API token: run `./create-token.sh` in `docker/hatchet` (it prints the token), or open
   http://localhost:8888, sign in with `HATCHET_ADMIN_EMAIL` / `HATCHET_ADMIN_PASSWORD` and go to
   **Settings → API Tokens → Create Token**
2. Set `HATCHET_CLIENT_TOKEN` in `docker/.env` (see step 3)

The dashboard is published on `127.0.0.1:8888` only; the engine's gRPC port is not published at all
(the application containers reach it on the isolated `hatchet` network). To run a backend and workers on the
host instead (INSTALL.md), add `-f docker-compose.dev.yml` to the `docker compose` command, which
publishes the engine on `127.0.0.1:7077`.

### 3. Start the application stack

`docker-compose.yml` has no working defaults for `SECRET_KEY`,
`INITIAL_PASSWORD`, `CREDENTIAL_ENCRYPTION_KEY`, `DATABASE_PASSWORD`,
`MANUS_REDIS_PASSWORD`, or `HATCHET_CLIENT_TOKEN` — `docker compose up`
refuses to start without them, on purpose (see [DOCKER.md](./DOCKER.md)).
Copy the template and fill it in first:

```bash
cd docker
cp .env.example .env
# edit .env — SECRET_KEY and CREDENTIAL_ENCRYPTION_KEY: openssl rand -hex 32
docker compose up -d --build
```

For local development (relaxed `ENV`, `/docs` enabled — secrets in `.env`
are still required):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Or run the helper script, which creates `.env` from the template
interactively if it doesn't exist yet:

```bash
./start-docker.sh
```

`manus-web`, `manus-worker`, and `manus-background-worker` all join the `hatchet` network (gRPC to `hatchet-engine:7070`, REST to `hatchet-dashboard:8080`); the web container also joins `ingress` and `data`, the workers `data` and `egress`.

There are **two** Hatchet worker containers, each running one process: `manus-worker`
(`supervisord-worker.conf` → `hatchet-worker`, `python -m hatchet.worker`) handles
every workflow by default; `manus-background-worker` (`supervisord-background-worker.conf`
→ `hatchet-dynamic-worker`, `python -m hatchet.dynamic_worker`) only handles workflows
explicitly published to the background tier. They're separate containers (not just
separate supervisord programs in one container) so restarting one to pick up a
publish/unpublish never disrupts a live/interactive run on the other. See
`doc/ARCHITECTURAL_OVERVIEW.md` → "Background-tier workflows" for what that split is for.

### Access URLs

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Hatchet dashboard | http://localhost:8888 |

## Networking

```
┌── network: data (internal) ─────────────────────────────────────────┐
│  manus-postgres · manus-redis · manus-web · manus-worker ·          │
│  manus-background-worker                                            │
└──────────┬──────────────────────┬──────────────────────┬────────────┘
   ingress │ (web only)           │ egress (workers)     │ hatchet
 published 127.0.0.1:3000         │ devices, Nautobot,   │ (external, --internal)
                                  │ git remotes          │ ──gRPC :7070──► hatchet-engine
```

| Setting | Value |
|---|---|
| `HATCHET_CLIENT_HOST_PORT` | `hatchet-engine:7070` |
| `manus-web` networks | `data` + `hatchet` + `ingress` |
| `manus-worker` networks | `data` + `hatchet` + `egress` |
| `manus-background-worker` networks | `data` + `hatchet` + `egress` |
| TLS | `HATCHET_CLIENT_TLS_STRATEGY=none` for local Hatchet |

The `hatchet` network has no inter-network routing. Host access to the dashboard (and optional bare-metal gRPC on `:7077`) uses published ports, not the `hatchet` network.

### Accessing the Hatchet dashboard from outside Docker

The Hatchet UI is served by `hatchet-dashboard` on container port 80, published as host port **8888** (loopback) in `docker/hatchet/docker-compose.yml`. Docker only publishes ports for containers that are on a non-internal network, so the dashboard also joins the ordinary `admin` network for that purpose; the engine does not. External access goes through that published port (or a reverse proxy), not through the isolated `hatchet` network.

### Health checks

There is no health route through the Next.js proxy (it only forwards `/api/*`). Check the backend
from inside the container: `docker exec manus-web curl -fs http://127.0.0.1:8000/health`.
The workers have no health check (the image's web check does not apply to them).

### Optional integrations

`docker/pyats`, `batfish`, `openbao`, `mattermost` and `litellm-proxy` each create their own
private network (`manus-pyats`, `manus-batfish`, `manus-openbao`, `manus-mattermost`,
`manus-litellm`), shared only with the containers that use them. Attach the consumers once with
`docker network connect manus-pyats manus-worker`, or copy
`docker-compose.integrations.example.yml`, keep the integrations you run and start the app with
`-f docker-compose.yml -f docker-compose.integrations.yml` so it survives re-creation.
The images of these stacks are pinned: `mattermost`, `litellm-proxy` and `batfish` need
`MATTERMOST_IMAGE_TAG`, `LITELLM_IMAGE_TAG` and `BATFISH_IMAGE_TAG` set to a reviewed release in
their `.env`. Third-party services drop `NET_RAW`.

### Container hardening

The three application containers run with `no-new-privileges`, `cap_drop: ALL` plus only the
capabilities `start.sh` and supervisord need (`CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `KILL`, `SETGID`,
`SETUID`), a PID limit and `MANUS_MEM_LIMIT` (default 4g). A read-only root file system is not
enabled yet: it needs a trial run of the real image (start, log in, run a workflow, upload a
certificate, restart) to find every writable path.

## Building images

### Development build (online)

From `docker/`:

```bash
docker compose build
```

Uses `Dockerfile.all-in-one` by default. For a faster iterative build, switch the compose `dockerfile` to `Dockerfile.basic`.

### Air-gap production image

On an internet-connected machine (from project root):

```bash
./docker/prepare-all-in-one.sh
```

Transfer `docker/airgap-artifacts/auxilium-manus-all-in-one.tar.gz` to the air-gapped host, then:

```bash
./docker/deploy-all-in-one.sh
./docker/validate-all-in-one.sh
```

See [README-ALL-IN-ONE.md](./README-ALL-IN-ONE.md) for the full air-gap guide. In air-gap environments, deploy Hatchet separately and ensure the application container can reach the Hatchet engine host on the gRPC port (default `7077` on the host, or `7070` on the shared Docker network).

**Hatchet dashboard font dependency:** the upstream `hatchet-dashboard` image (`ghcr.io/hatchet-dev/hatchet/hatchet-dashboard`) ships a static `index.html` with a hardcoded `<link>` to `fonts.googleapis.com` (Ubuntu font) — there is no env var to disable it. In an air-gapped network the browser hangs on that request before falling back. On any machine whose browser opens the dashboard, add to the hosts file:

```
0.0.0.0 fonts.googleapis.com
0.0.0.0 fonts.gstatic.com
```

`0.0.0.0` fails the connection immediately (unlike `127.0.0.1`, which can hang if something else is listening on port 443 locally), so the page loads without waiting on the timeout.

## Files

| File | Purpose |
|---|---|
| `Dockerfile.all-in-one` | Self-contained production image (air-gap) |
| `Dockerfile.basic` | Faster online development build |
| `Dockerfile.worker` | Standalone Hatchet worker (optional) |
| `docker-compose.yml` | App stack: postgres, redis, web, live worker, background worker (`data`, `hatchet`, `ingress`, `egress` networks) |
| `docker-compose.agent.example.yml` | Example overlay: a Route to Agent agent on the `data` network (copy to `docker-compose.agent.yml`; see `../doc/AGENT_INTEGRATION.md`) |
| `redis/start.sh` | Entrypoint of `manus-redis`: writes the Redis ACL file at every start (`default` user with `MANUS_REDIS_PASSWORD` plus the agent users of `redis/agents.acl`) |
| `redis/agents.acl.example` | Template for `redis/agents.acl` (git-ignored): one Redis user per remote agent |
| `docker-compose.dev.yml` | Development override (`ENV=development`, `DOCS_ENABLED=true`) — use with `-f docker-compose.yml -f docker-compose.dev.yml` |
| `.env.example` | Required secrets template — copy to `.env` before `docker compose up` |
| `hatchet/docker-compose.yml` | Hatchet stack (engine, dashboard, dependencies) |
| `pyats/docker-compose.yml` | Optional pyATS shim stack (see `pyats/README.md`) |
| `prepare-all-in-one.sh` | Build and export air-gap image |
| `deploy-all-in-one.sh` | Load and run image in air-gap environment |
| `validate-all-in-one.sh` | Post-deployment health checks |
| `build-with-proxy.sh` | Build with proxy env vars |
| `run-with-proxy.sh` | Run container with proxy env vars |
| `start-docker.sh` | Interactive setup and `docker compose up` |

## Environment variables

Copy `.env.example` to `.env` and fill in the required values:

```bash
SECRET_KEY=                    # openssl rand -hex 32
INITIAL_PASSWORD=               # 12+ characters; the admin must change it on first login regardless
CREDENTIAL_ENCRYPTION_KEY=      # openssl rand -hex 32, must differ from SECRET_KEY
DATABASE_PASSWORD=              # the app's unprivileged database role "manus" (created on first start)
POSTGRES_PASSWORD=              # the PostgreSQL superuser; only manus-postgres receives it, 12+ characters, different from the one above
MANUS_REDIS_PASSWORD=           # shared by manus-redis and the app containers
HATCHET_CLIENT_TOKEN=           # API token from the Hatchet dashboard (step 2 above)
```

`docker compose up` refuses to start until every one of these is set — see
[DOCKER.md](./DOCKER.md) if you hit that. `ENV`, `DOCS_ENABLED`,
`INITIAL_USERNAME`, and `INSTALL_CERTIFICATE_FILES` are optional overrides
with working defaults; see `.env.example` for the full list.

Compose hardcodes in-container hostnames (`manus-postgres`, `manus-redis`) and other non-secret settings (`HATCHET_CLIENT_HOST_PORT`, `HATCHET_CLIENT_TLS_STRATEGY`, ports, retention/logging defaults) directly in `x-manus-common-env` — edit `docker-compose.yml` itself for those, not `.env`. Bind address, backend port, `BACKEND_URL`, and `NODE_ENV` for processes inside `manus-web` are set by `supervisord-web.conf`.

## Proxy support

Build scripts detect proxy environment variables automatically:

```bash
export HTTP_PROXY=http://proxy.company.com:8080
export HTTPS_PROXY=http://proxy.company.com:8080
export NO_PROXY=localhost,127.0.0.1,.local

./docker/prepare-all-in-one.sh
```

## Published ports

3000 on `127.0.0.1` only (override with `MANUS_WEB_PUBLISH`). The backend (8000) and the optional
services are not published on a LAN interface. The Hatchet dashboard (8888) is bound to `127.0.0.1` by
`hatchet/docker-compose.yml`; the engine's gRPC port is published (7077, loopback) only with
`hatchet/docker-compose.dev.yml`. A production deployment exposes the dashboard through its own proxy,
sets the secure cookie and cookie domain, and keeps gRPC on a private network
(`hatchet/docker-compose.prod.yml` publishes nothing).

## Runtime dependencies

The all-in-one image bundles the application (frontend + backend + worker supervisor config). These services must be available at runtime:

| Dependency | Provided by |
|---|---|
| PostgreSQL (app) | `docker-compose.yml` → `postgres` |
| Redis | `docker-compose.yml` → `redis` |
| Hatchet | `docker/hatchet/docker-compose.yml` |

Pass connection settings via `.env` or container environment variables.

## Backup and restore

Back these up together, from the same moment; they refer to each other:

| What | Where | Why |
|---|---|---|
| The `manus` database | `manus-postgres` | users, workflows, runs, credentials (encrypted), reports |
| `docker/data/` (`artifacts`, `exports`, `git`, `ssh_keys`, `settings`) | bind mount | run artifacts, exported configs, git working trees, SSH key files; `cache` and `logs` can be skipped |
| `config/` | bind mount | OIDC providers, operator CA certificates |
| `docker/.env` and `docker/oidc.env` | files | **`CREDENTIAL_ENCRYPTION_KEY` is part of the backup**: stored credentials can only be decrypted with the key they were encrypted with. Keep it apart from the dump, but with the same retention. `SECRET_KEY` only invalidates sessions if lost. |
| OpenBao data | its own volume | only if `VAULT_ENABLED`; see `doc/VAULT_INTEGRATION.md` |

Redis holds cache and locks only. Hatchet needs no backup for Manus to work: after losing its volumes create
a new token with `docker/hatchet/create-token.sh` and put it in `docker/.env`; keep `hatchet_postgres_data`
and `hatchet_config` only if you want Hatchet's own run history and tokens.

```bash
# backup (database dump; custom format)
docker exec manus-postgres pg_dump -U postgres -Fc manus > manus-$(date +%F).dump

# restore into a fresh stack (the "manus" role and an empty "manus" database exist after the first start)
docker compose stop manus-web manus-worker manus-background-worker
# only needed when restoring over a stack that already has data (harmless on a fresh one): start from
# an empty database. Keep "OWNER manus": the application connects as that unprivileged role, so the
# database must stay owned by it, as the first start creates it.
docker exec manus-postgres psql -U postgres -c 'DROP DATABASE manus' -c 'CREATE DATABASE manus OWNER manus'
docker exec -i manus-postgres pg_restore -U postgres -d manus --clean --if-exists < manus-2026-10-17.dump
# put docker/data, config/ and docker/.env (same CREDENTIAL_ENCRYPTION_KEY) back, then:
docker compose up -d
```

After a restore, open **Settings → Credentials** and run a connection test, then start one workflow to
check that credentials decrypt and artifacts open. There is no tool to re-encrypt credentials with a new
key: after a suspected key leak, enter the credentials again (steps in [`SECURITY.md`](../SECURITY.md), "Rotating `CREDENTIAL_ENCRYPTION_KEY`").

## Operating notes

- **Redis down:** open sessions keep working. Login and token refresh use an in-process rate limit instead
  (set `RATE_LIMIT_FAIL_CLOSED=true` to refuse instead, which blocks every login until Redis is back). Git
  steps need their per-repository lock in Redis and fail with a retryable `repo_locked` error until Redis is
  back (`GIT_REPO_LOCK_REQUIRED=false` runs them unlocked, which is only safe with a single run at a time).
- **Hatchet down:** starting a run returns `503` ("the workflow execution engine is unavailable") and the run
  is recorded as failed. The first attempt takes up to ~20 seconds (the SDK's own retries); for the following 15
  seconds further attempts fail at once. The rest of the application is not affected.
- **Database down:** API calls return `503` with `Retry-After: 30` and recover by themselves when it is back.
  `/health/ready` answers `503` within about 3 seconds whichever dependency hangs.
- **Redeploys:** the worker containers get 10 minutes (`stop_grace_period`) to finish running workflows
  before Docker kills them; a run killed anyway is marked failed by the run reaper after
  `RUN_REAPER_GRACE_MINUTES`.
- **Retention:** workflow runs older than `RUN_RETENTION_DAYS` (90) and their artifacts are deleted daily
  (`RUN_RETENTION_ENABLED=true` by default; `false` keeps everything). Run results may contain secrets.
- **Second copy next to another stack** (staging, upgrade rehearsal): give each `docker compose` call its own
  `-p <name>` (volumes and containers are scoped by it) and change the published ports. A backend started on the
  host from `backend/` also reads `backend/.env` (including the Hatchet token) and writes to the repository's
  `data/`; override `HATCHET_CLIENT_*` and `DATA_DIRECTORY` for a test instance.

## Troubleshooting

See [DOCKER.md](./DOCKER.md).

Common Hatchet issues:

```bash
# Hatchet service status
cd docker/hatchet && docker compose ps

# Confirm app containers are on the isolated hatchet network
docker network inspect hatchet

# Worker / backend Hatchet connection logs
docker logs manus-worker
docker logs manus-background-worker
docker logs manus-web
```
