# pyATS Shim

A thin FastAPI wrapper around Cisco pyATS/Genie, deployed as its own container
so the main backend (Python 3.14) never has to install pyATS directly (pyATS's
published wheels only confirm Python 3.12/3.13 support, and its dependency
tree risks colliding with the app's own deps).

See `doc/PYATS_INTEGRATION.md` at the repo root for the full architecture,
and `docker/pyats/` for how this service is built and run.

## Endpoints

- `GET /health` — liveness only.
- `GET /health/pyats` — imports pyats/genie and reports their versions.
- `POST /v1/jobs` (Bearer token required) — runs a pyATS `execute`/`parse`
  job against a batch of devices in one `pyats run job` subprocess call.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
PYATS_SHIM_TOKEN=dev-token pytest tests/ -v
PYATS_SHIM_TOKEN=dev-token uvicorn app.main:app --reload --port 8100
```

## Configuration (env vars)

| Variable                        | Default | Purpose                                   |
|----------------------------------|---------|--------------------------------------------|
| `PYATS_SHIM_TOKEN`               | —       | Required. Bearer token for `/v1/jobs`.     |
| `PYATS_SHIM_PORT`                | `8100`  | Listen port (also used by the Dockerfile). |
| `PYATS_SHIM_MAX_CONCURRENT_JOBS` | `4`     | Concurrent `pyats run job` subprocesses.   |
| `PYATS_SHIM_JOB_TIMEOUT_SECONDS` | `120`   | Default per-request job timeout.           |
