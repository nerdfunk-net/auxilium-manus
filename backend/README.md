# Auxilium Manus Backend

FastAPI backend for the Auxilium Manus workflow builder.

## Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python start.py
```

The API runs on `http://127.0.0.1:8000`.

## API Docs

FastAPI exposes Swagger UI in development at:

```text
http://127.0.0.1:8000/docs
```

Set `DOCS_ENABLED=false` outside local development to disable Swagger UI and
ReDoc.

The application expects PostgreSQL to be available with these defaults:

```text
database: manus
username: postgres
password: postgres
```

Override them in `.env` when needed.

If the `manus` database does not exist yet, startup connects to the maintenance
database (`postgres` by default) and creates it before running schema migrations.

On startup, the backend runs pending migrations and creates the initial admin
user if it does not already exist. The local defaults are:

```text
username: admin
password: admin
```

Log in through Swagger UI with:

```bash
POST /api/auth/login
```

## Plugin Registry

At startup, the backend reads `../plugins/plugins.yaml`, validates the plugin
registry, and keeps it in memory for the process lifetime. It only reads plugin
metadata, including the mandatory `filename` field. The referenced plugin code
files are not opened or executed during startup.

Available endpoints:

```text
GET /health
POST /api/auth/login
GET /api/auth/me
GET /api/plugins
GET /api/plugins?include_disabled=true
GET /api/plugins/registry
GET /api/plugins/{plugin_id}
```

## Workflow run retention

Finished runs (`success`, `failed`, `cancelled`) and their step logs (`workflow_step_results`,
including `output` and `error_message`) can be purged from PostgreSQL after a retention period.
`pending` and `running` runs are never deleted.

Configure in `.env`:

```text
RUN_RETENTION_ENABLED=true
RUN_RETENTION_DAYS=90
RUN_RETENTION_BATCH_SIZE=500
```

Preview and purge manually:

```bash
cd backend
python scripts/purge_retention.py --dry-run
python scripts/purge_retention.py --force   # when RUN_RETENTION_ENABLED=false
```

Example cron (daily at 03:00):

```cron
0 3 * * * cd /path/to/auxilium-manus/backend && /path/to/.venv/bin/python scripts/purge_retention.py
```

Hatchet keeps its own run history in the Hatchet database; purging Postgres does not remove
those dashboard entries.
