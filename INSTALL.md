# Installation

> Development setup. Do not expose these ports; for production use [`docker/README.md`](docker/README.md).

## Prerequisites

- Docker and Docker Compose
- Python 3.14 with a virtual environment at `.venv/`
- Node.js 26 (see `frontend/.nvmrc`)

## First-time setup

### 1. Create Docker networks

The application compose file attaches to one external network that must exist before starting
services (the Hatchet compose project creates its own private `internal` network):

```bash
docker network create --internal hatchet
```

Only needed once. Skip if the network already exists.

### 2. Start infrastructure

Manus depends on **Hatchet** (workflow orchestration), **PostgreSQL** (application
database), and **Redis** (cache). **Hatchet must be running before you start Manus** —
the backend and workers connect to Hatchet over gRPC on startup; without it, workflow
runs cannot be scheduled or executed.

Optional: OpenBao-backed credential storage — see
[`doc/VAULT_INTEGRATION.md`](doc/VAULT_INTEGRATION.md) (production setup) and
`docker/openbao/` (development only).

#### Hatchet (start first)

Hatchet runs from its own Compose file, separate from the application stack:

[`docker/hatchet/docker-compose.yml`](docker/hatchet/docker-compose.yml)

The file uses official pre-built Hatchet images from `ghcr.io/hatchet-dev/hatchet/`
(there is no local Dockerfile to build in this directory). Pull the images and start the
stack:

```bash
cd docker/hatchet
cp .env.example .env
# edit .env: both passwords (openssl rand -hex 24), HATCHET_ADMIN_EMAIL and HATCHET_ADMIN_PASSWORD
# HATCHET_ADMIN_PASSWORD: 8-64 characters with an upper-case letter, a lower-case letter and a digit
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

`docker-compose.dev.yml` publishes the engine on `127.0.0.1:7077` so that the backend and workers
you start on the host (below) can reach it. Compose pulls any missing images automatically.
Without the overlay the engine is reachable only from other containers, which is what the
Docker deployment in `docker/README.md` uses.

This brings up:

| Service | Purpose |
|---|---|
| `hatchet-postgres` | Hatchet's own PostgreSQL database |
| `hatchet-rabbitmq` | Message queue for Hatchet |
| `hatchet-migrate` | One-shot database migrations |
| `hatchet-setup-config` | One-shot setup (encryption keys, default admin user) |
| `hatchet-engine` | gRPC workflow engine — published on `127.0.0.1:7077` (loopback only, with the dev overlay) |
| `hatchet-dashboard` | Web UI and REST API at [http://localhost:8888](http://localhost:8888) (loopback only) |

Wait about **60 seconds** for the one-shot jobs (`hatchet-migrate`,
`hatchet-setup-config`) to finish and `hatchet-dashboard` to start. To watch progress:

```bash
docker compose logs -f hatchet-setup-config hatchet-dashboard
```

When ready, `hatchet-engine` and `hatchet-dashboard` should show as running:

```bash
docker compose ps
```

Configure the Manus backend to reach Hatchet via `HATCHET_CLIENT_HOST_PORT=localhost:7077`
in `backend/.env` (see step 3 below for the API token).

#### PostgreSQL and Redis

The application database and Redis cache must also be available before starting Manus.
For the local four-terminal setup below, connection settings are in `backend/.env.example`
(`localhost:5432` for PostgreSQL, `localhost:6379` for Redis). Install and run them on
the host, or use your own preferred method.

For a fully Docker-based deployment (application image plus infrastructure), see
[`docker/README.md`](docker/README.md).

### 3. Configure Hatchet

Open the Hatchet dashboard at [http://localhost:8888](http://localhost:8888) and sign in with
`HATCHET_ADMIN_EMAIL` / `HATCHET_ADMIN_PASSWORD` from `docker/hatchet/.env`.

> **Password rule:** Hatchet accepts only an admin password of 8-64 characters with at least one
> upper-case letter, one lower-case letter and one digit. A weaker one makes `hatchet-setup-config`
> exit with an error ("ADMIN_PASSWORD does not meet requirements") and the stack does not start.
> Fix `.env`, run `docker compose down -v` in `docker/hatchet`, and start again.

Go to **Settings → API Tokens → Create Token**, or run `docker/hatchet/create-token.sh`, which prints
a token without the dashboard. Copy the token, then add it to `backend/.env`:

```
HATCHET_CLIENT_TOKEN=<paste token here>
```

### 4. Install dependencies

```bash
# Backend
source .venv/bin/activate
pip install -r backend/requirements.txt

# Frontend
cd frontend && npm install
```

## Running the app

Open four terminals:

**Terminal 1 — Backend API**
```bash
source .venv/bin/activate
cd backend && python start.py
```

API available at [http://localhost:8000](http://localhost:8000) · Swagger docs at [http://localhost:8000/docs](http://localhost:8000/docs)

**Terminal 2 — Live worker**
```bash
source .venv/bin/activate
cd backend && python -m hatchet.worker
```

The live worker receives workflow execution jobs from Hatchet and runs them on your machine. Every network device connection (SSH, config retrieval, command execution) happens inside this process. It handles every workflow run by default.

**Terminal 3 — Frontend**
```bash
cd frontend && npm run dev
```

App available at [http://localhost:3000](http://localhost:3000) · Default credentials: `admin / admin` (development only: set `ENV=development` in `backend/.env`; the forced password change on first login still applies)

**Terminal 4 — Background worker**
```bash
source .venv/bin/activate
cd backend && python -m hatchet.dynamic_worker
```

A second, separate worker process, required alongside the live worker. It only
executes workflows explicitly **published** to the background tier (Properties
panel → "Publish to background tier") — e.g. a nightly backup job that should
get its own Hatchet-native concurrency limit, isolated from live/interactive
runs. Unpublished workflows still run on the live worker as normal; this
process just needs to be up so publishing works whenever you use it. See
`doc/ARCHITECTURAL_OVERVIEW.md` → "Background-tier workflows" for how it works.

## Services overview

| Service | URL | Purpose |
|---|---|---|
| Frontend | http://localhost:3000 | Main application |
| Backend API | http://localhost:8000 | REST API |
| Hatchet dashboard | http://localhost:8888 | Workflow run history and monitoring |
| PostgreSQL (app) | localhost:5432 | Application database |
| Redis | localhost:6379 | Cache and pub/sub |

## Stopping

```bash
# Stop the app processes with Ctrl+C in each terminal, then:

# Hatchet stack
cd docker/hatchet && docker compose down

# To also delete Hatchet data:
cd docker/hatchet && docker compose down -v
```

## Development notes

- The backend restarts automatically on code changes (uvicorn `--reload`).
- Neither worker hot-reloads — restart manually after changing code in `backend/hatchet/` or `backend/services/execution/`. For auto-restart during development, use `python scripts/run_worker_dev.py` (live worker) or `python scripts/run_dynamic_worker_dev.py` (background worker) instead of the bare `python -m hatchet.*` commands above — the background worker's script also auto-restarts when a workflow is published/unpublished, not just on code changes.
- Database migrations run automatically on backend startup.
- Hatchet Docker containers only manage job scheduling. All actual workflow execution happens in the worker processes on your machine.

## Docker / production deployment

For a fully containerized deployment (application image + Hatchet, including an
air-gapped production setup), see [`docker/README.md`](docker/README.md). That
guide covers building the app image, running everything under Docker Compose, and
configuring `HATCHET_CLIENT_TOKEN` for the containerized worker instead of a local
`backend/.env`.
