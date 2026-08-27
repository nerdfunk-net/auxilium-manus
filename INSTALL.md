# Installation

## Prerequisites

- Docker and Docker Compose
- Python 3.14 with a virtual environment at `.venv/`
- Node.js 20+

## First-time setup

### 1. Create Docker networks

The compose file uses two external networks that must exist before starting services:

```bash
docker network create internal
docker network create --internal hatchet
```

Only needed once. Skip if the networks already exist.

### 2. Start infrastructure

```bash
docker compose up -d
```

This starts PostgreSQL, Redis, and the Hatchet workflow engine. Wait ~30 seconds for all services to become healthy.

### 3. Configure Hatchet

Open the Hatchet dashboard at [http://localhost:8888](http://localhost:8888) and sign in:

- Email: `admin@example.com`
- Password: `Admin123!!`

Go to **Settings → API Tokens → Create Token**, copy the token, then add it to `backend/.env`:

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

API available at [http://localhost:8001](http://localhost:8001) · Swagger docs at [http://localhost:8001/docs](http://localhost:8001/docs)

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

App available at [http://localhost:3000](http://localhost:3000) · Default credentials: `admin / admin`

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
| Backend API | http://localhost:8001 | REST API |
| Hatchet dashboard | http://localhost:8888 | Workflow run history and monitoring |
| PostgreSQL (app) | localhost:5432 | Application database |
| Redis | localhost:6379 | Cache and pub/sub |

## Stopping

```bash
# Stop the app processes with Ctrl+C in each terminal, then:
docker compose down

# To also delete all data:
docker compose down -v
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
