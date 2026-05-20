# Auxilium Manus

A NetDevOps workflow builder for network engineers. Design, configure, and execute network automation workflows visually.

## Prerequisites

- Docker and Docker Compose
- Python 3.14 with a virtual environment at `.venv/`
- Node.js 20+

## First-time setup

### 1. Start infrastructure

```bash
docker compose up -d
```

This starts PostgreSQL, Redis, and the Hatchet workflow engine. Wait ~30 seconds for all services to become healthy.

### 2. Configure Hatchet

Open the Hatchet dashboard at [http://localhost:8888](http://localhost:8888) and sign in:

- Email: `admin@example.com`
- Password: `Admin1234!`

Go to **Settings → API Tokens → Create Token**, copy the token, then add it to `backend/.env`:

```
HATCHET_CLIENT_TOKEN=<paste token here>
```

### 3. Install dependencies

```bash
# Backend
source .venv/bin/activate
pip install -r backend/requirements.txt

# Frontend
cd frontend && npm install
```

## Running the app

Open three terminals:

**Terminal 1 — Backend API**
```bash
source .venv/bin/activate
cd backend && python start.py
```

API available at [http://localhost:8001](http://localhost:8001) · Swagger docs at [http://localhost:8001/docs](http://localhost:8001/docs)

**Terminal 2 — Workflow worker**
```bash
source .venv/bin/activate
cd backend && python -m hatchet.worker
```

The worker receives workflow execution jobs from Hatchet and runs them on your machine.

**Terminal 3 — Frontend**
```bash
cd frontend && npm run dev
```

App available at [http://localhost:3000](http://localhost:3000) · Default credentials: `admin / admin`

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
- The worker does **not** hot-reload — restart it manually after changing code in `backend/hatchet/` or `backend/services/execution/`.
- Database migrations run automatically on backend startup.
- Hatchet Docker containers only manage job scheduling. All actual workflow execution happens in the worker process on your machine.
