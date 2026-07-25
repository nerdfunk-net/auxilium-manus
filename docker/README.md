# Auxilium Manus Docker Deployment

Docker files for building and running Auxilium Manus in development and air-gapped production environments.

Running the application requires **two pieces**:

1. **The application image** — frontend, backend API, and Hatchet worker (built from this directory).
2. **Hatchet** — workflow orchestration engine (started separately from `docker/hatchet/`).

PostgreSQL and Redis are bundled in the application `docker-compose.yml`. Hatchet brings its own PostgreSQL and RabbitMQ on the private `internal` network.

## Quick start (development)

### 1. Create Docker networks

Create the external networks once:

```bash
docker network create internal 2>/dev/null || true
docker network create --internal hatchet 2>/dev/null || true
```

| Network | Purpose |
|---|---|
| `internal` | Hatchet private infra (postgres, rabbitmq, migrate, setup) |
| `hatchet` | Isolated (`--internal`): engine/dashboard ↔ `manus-web` / `manus-worker` (no outside routing) |
| `frontend` | App-stack bridge (created by compose): postgres, redis, web, worker; published ports for users |

### 2. Start Hatchet

```bash
cd docker/hatchet
docker compose up -d
```

Wait ~60 seconds for `hatchet-setup-config` to finish and `hatchet-dashboard` to become healthy.

**First-time Hatchet setup:**

1. Open http://localhost:8888
2. Sign in: `admin@example.com` / `Admin1234!`
3. Go to **Settings → API Tokens → Create Token** and copy the token
4. Set `HATCHET_CLIENT_TOKEN` in `docker/docker-compose.yml` (`x-manus-app-env`)

### 3. Start the application stack

```bash
cd docker
docker compose up -d --build
```

Or run the helper script:

```bash
./start-docker.sh
```

`manus-web` and `manus-worker` join both `frontend` (users + app DB/Redis) and `hatchet` (gRPC to `hatchet-engine:7070`).

### Access URLs

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| Hatchet dashboard | http://localhost:8888 |

## Networking

```
┌── network: frontend (bridge) ──────────────────────────────┐
│  postgres · redis · manus-web · manus-worker               │
│  ports 3000 / 8000 published from manus-web → host/users   │
└───────────────────────────┬────────────────────────────────┘
                            │ manus-web / manus-worker
┌───────────────────────────┴────────────────────────────────┐
│  network: hatchet (external, --internal)                   │
│  manus-web · manus-worker ──gRPC :7070──► hatchet-engine   │
│                              hatchet-dashboard (:8888 host) │
└────────────────────────────────────────────────────────────┘
```

| Setting | Value |
|---|---|
| `HATCHET_CLIENT_HOST_PORT` | `hatchet-engine:7070` |
| `manus-web` networks | `frontend` + `hatchet` |
| `manus-worker` networks | `frontend` + `hatchet` |
| TLS | `HATCHET_CLIENT_TLS_STRATEGY=none` for local Hatchet |

The `hatchet` network has no inter-network routing. Host access to the dashboard (and optional bare-metal gRPC on `:7077`) uses published ports, not the `hatchet` network.

### Accessing the Hatchet dashboard from outside Docker

The Hatchet UI is served by `hatchet-dashboard` on container port 80, published as host port **8888** in `docker/hatchet/docker-compose.yml`. External access goes through that published port (or a reverse proxy), not through the isolated `hatchet` network.

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

## Files

| File | Purpose |
|---|---|
| `Dockerfile.all-in-one` | Self-contained production image (air-gap) |
| `Dockerfile.basic` | Faster online development build |
| `Dockerfile.worker` | Standalone Hatchet worker (optional) |
| `docker-compose.yml` | App stack: postgres, redis, web, worker (`frontend` + `hatchet` networks) |
| `.env.example` | Optional template (prefer editing `x-manus-app-env` in compose) |
| `hatchet/docker-compose.yml` | Hatchet stack (engine, dashboard, dependencies) |
| `prepare-all-in-one.sh` | Build and export air-gap image |
| `deploy-all-in-one.sh` | Load and run image in air-gap environment |
| `validate-all-in-one.sh` | Post-deployment health checks |
| `build-with-proxy.sh` | Build with proxy env vars |
| `run-with-proxy.sh` | Run container with proxy env vars |
| `start-docker.sh` | Interactive setup and `docker compose up` |

## Environment variables

Copy `.env.example` to `.env`. Key values:

```bash
HATCHET_CLIENT_TOKEN=          # API token from Hatchet dashboard
HATCHET_CLIENT_HOST_PORT=hatchet-engine:7070   # isolated hatchet network
HATCHET_CLIENT_TLS_STRATEGY=none

POSTGRES_DB=manus              # mapped to DATABASE_* inside the app containers
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
MANUS_REDIS_PASSWORD=changeme  # Redis host/port are fixed to the redis service

# CREDENTIAL_ENCRYPTION_KEY=   # recommended in production; falls back to SECRET_KEY
```

Compose hardcodes in-container hostnames (`postgres`, `redis`) and maps `POSTGRES_*` into `DATABASE_*` for the app. Bind address, backend port, `BACKEND_URL`, and `NODE_ENV` for processes inside `manus-web` are set by `supervisord-web.conf`, not by `.env`.

See `.env.example` for the full template.

## Proxy support

Build scripts detect proxy environment variables automatically:

```bash
export HTTP_PROXY=http://proxy.company.com:8080
export HTTPS_PROXY=http://proxy.company.com:8080
export NO_PROXY=localhost,127.0.0.1,.local

./docker/prepare-all-in-one.sh
```

## Production ports

| Service | Port |
|---|---|
| Frontend | 3000 |
| Backend API | 8000 |
| Hatchet dashboard | 8888 |
| Hatchet gRPC (host) | 7077 |

## Runtime dependencies

The all-in-one image bundles the application (frontend + backend + worker supervisor config). These services must be available at runtime:

| Dependency | Provided by |
|---|---|
| PostgreSQL (app) | `docker-compose.yml` → `postgres` |
| Redis | `docker-compose.yml` → `redis` |
| Hatchet | `docker/hatchet/docker-compose.yml` |

Pass connection settings via `.env` or container environment variables.

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
docker logs manus-web
```
