# Auxilium Manus Docker Deployment

Docker files for building and running Auxilium Manus in development and air-gapped production environments.

Running the application requires **two pieces**:

1. **The application image** — frontend, backend API, and Hatchet worker (built from this directory).
2. **Hatchet** — workflow orchestration engine (started separately from `docker/hatchet/`).

PostgreSQL and Redis are bundled in the application `docker-compose.yml`. Hatchet brings its own PostgreSQL and RabbitMQ.

> **Port conflict:** `docker/hatchet/docker-compose.yml` also defines PostgreSQL and Redis (for local bare-metal development). Do not start both composes' `postgres` and `redis` services on the same host — use the app stack's database and cache when running the full Docker deployment.

## Quick start (development)

### 1. Create shared Docker networks

Hatchet and the application backend must be able to reach each other on the same Docker network. Create the external networks once:

```bash
docker network create internal 2>/dev/null || true
docker network create backend 2>/dev/null || true
```

| Network | Purpose |
|---|---|
| `internal` | Hatchet internal services (database, message queue, engine internals) |
| `backend` | Shared network between Hatchet engine/dashboard and the Auxilium Manus backend/worker |

### 2. Start Hatchet

```bash
cd docker/hatchet
docker compose up -d \
  hatchet-postgres hatchet-rabbitmq \
  hatchet-migrate hatchet-setup-config \
  hatchet-engine hatchet-dashboard
```

This starts only the Hatchet services (not the `postgres` / `redis` services in the same file, which would conflict with the app stack on ports 5432 and 6379).

Wait ~60 seconds for `hatchet-setup-config` to finish and `hatchet-dashboard` to become healthy.

**First-time Hatchet setup:**

1. Open http://localhost:8888
2. Sign in: `admin@example.com` / `Admin1234!`
3. Go to **Settings → API Tokens → Create Token** and copy the token

### 3. Start the application stack

```bash
cd docker
cp .env.example .env   # set HATCHET_CLIENT_TOKEN and other secrets
```

Connect the app containers to the shared `backend` network and point the Hatchet client at the engine service name:

```bash
# In .env
HATCHET_CLIENT_TOKEN=<paste token from step 2>
HATCHET_CLIENT_HOST_PORT=hatchet-engine:7070
HATCHET_CLIENT_TLS_STRATEGY=none
```

Use the network override so `manus-web` and `manus-worker` join `backend`:

```bash
docker compose -f docker-compose.yml -f docker-compose.hatchet-network.yml up -d --build
```

Or run the helper script (creates `.env` if missing, then starts the stack):

```bash
./start-docker.sh
```

> **Note:** `start-docker.sh` uses the default compose file only. When Hatchet runs in Docker, always add `docker-compose.hatchet-network.yml` as shown above, or attach containers to `backend` manually (see [Networking](#networking)).

### Access URLs

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| Hatchet dashboard | http://localhost:8888 |

## Networking

The Auxilium Manus backend and Hatchet worker connect to Hatchet over **gRPC**. For reliable workflow execution, the application containers and Hatchet engine must share a Docker network.

```
┌─────────────────────────────────────────────────────────────┐
│  network: backend (external)                                │
│                                                             │
│  ┌──────────────┐     gRPC      ┌─────────────────────┐   │
│  │  manus-web   │──────────────►│  hatchet-engine     │   │
│  │  manus-worker│  :7070        │  hatchet-dashboard  │   │
│  └──────────────┘               └─────────────────────┘   │
│         │                                    │             │
│         │ manus-network                      │ :8888      │
└─────────┼────────────────────────────────────┼─────────────┘
          │                                    │
     postgres, redis                    published to host
```

### Same-network configuration (recommended)

| Setting | Value |
|---|---|
| `HATCHET_CLIENT_HOST_PORT` | `hatchet-engine:7070` |
| App containers on | `backend` network (in addition to `manus-network`) |
| TLS | `HATCHET_CLIENT_TLS_STRATEGY=none` for local Hatchet |

The Hatchet compose file attaches `hatchet-engine` and `hatchet-dashboard` to `backend`. Attach `manus-web` and `manus-worker` to the same network via `docker-compose.hatchet-network.yml`.

### Host-bridge fallback (not recommended)

The default `.env.example` uses `host.docker.internal:7077`, which routes gRPC through the host port mapping instead of the Docker network. This works when Hatchet publishes `7077:7070` but does **not** put the app and Hatchet on the same network. Prefer the shared-network setup above.

### Accessing the Hatchet dashboard from outside Docker

The Hatchet UI is served by `hatchet-dashboard` on container port 80, published as host port **8888** in `docker/hatchet/docker-compose.yml`.

To reach the dashboard from your browser or another machine:

- The `hatchet-dashboard` service must publish port `8888` to a host interface that clients can reach.
- For remote access, bind or proxy that port on the host (firewall rules, reverse proxy, etc.) — the `backend` network alone is internal to Docker; external access always goes through published ports or an ingress layer.

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
| `docker-compose.yml` | App stack: postgres, redis, web, worker |
| `docker-compose.hatchet-network.yml` | Override: attach app to Hatchet `backend` network |
| `hatchet/docker-compose.yml` | Hatchet stack (engine, dashboard, dependencies) |
| `prepare-all-in-one.sh` | Build and export air-gap image |
| `deploy-all-in-one.sh` | Load and run image in air-gap environment |
| `validate-all-in-one.sh` | Post-deployment health checks |
| `build-with-proxy.sh` | Build with proxy env vars |
| `run-with-proxy.sh` | Run container with proxy env vars |
| `start-docker.sh` | Interactive setup and `docker compose up` |

## Environment variables

Copy `.env.example` to `.env`. Key Hatchet-related values:

```bash
HATCHET_CLIENT_TOKEN=          # API token from Hatchet dashboard
HATCHET_CLIENT_HOST_PORT=hatchet-engine:7070   # when on shared backend network
HATCHET_CLIENT_TLS_STRATEGY=none
```

See `.env.example` for database, Redis, and application settings.

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

# Confirm app containers are on the backend network
docker network inspect backend

# Worker / backend Hatchet connection logs
docker logs manus-worker
docker logs manus-web
```
