# Backend tests

Unit and light integration tests for the FastAPI backend. They live under `backend/tests/` as `test_*.py` modules, written in stdlib `unittest` style (`TestCase` / `IsolatedAsyncioTestCase`) and run with **pytest**.

External I/O is mocked; DB-backed cases use in-memory SQLite. No running PostgreSQL, Redis, Hatchet, or Nautobot is required.

## Prerequisites

1. Project virtualenv at the **repo root** (`.venv/`, Python 3.14 — not `backend/.venv`).
2. Dev dependencies installed once:

```bash
# from repo root
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
```

`requirements-dev.txt` pulls in runtime deps (`requirements.txt`) plus `pytest` and `pytest-cov`. Config is in `backend/pyproject.toml`.

## How to start tests

Preferred — from **`backend/`**:

```bash
cd backend
python -m pytest
```

Also works from the **repo root** (imports are fixed via `tests/conftest.py`):

```bash
python -m pytest backend/tests
```

One file / class / test:

```bash
# from backend/
python -m pytest tests/test_rbac_service.py
python -m pytest tests/test_rbac_service.py::RBACServiceHasPermissionTests
python -m pytest tests/test_rbac_service.py::RBACServiceHasPermissionTests::test_role_grant_allows
```

By keyword:

```bash
python -m pytest -k "rbac or fan_out"
```

Verbose / coverage:

```bash
python -m pytest -v
python -m pytest --cov=. --cov-report=term-missing
```

Equivalent with stdlib unittest:

```bash
cd backend && python -m unittest discover -s tests
```

## Common mistake

If you see dozens of collection errors like:

```text
ModuleNotFoundError: No module named 'core'
```

pytest was started without `backend/` on `sys.path` (old docs / wrong cwd / no `conftest`). Use one of:

```bash
cd backend && python -m pytest
# or from repo root:
python -m pytest backend/tests
```

Use the **project** `.venv` (`source .venv/bin/activate` from the repo root), not a random system Python.

## What these tests cover

Workflow step executors, `StepRunner`, workflow context, RBAC, credentials, git/filesystem artifact sinks, Netmiko session pool (mocked sessions), ISE/Nautobot helpers (mocked HTTP), and a few FastAPI `TestClient` router checks.

They do **not** replace a live stack (Postgres + Redis + Hatchet worker + frontend).

## Related checks (not under `tests/`)

From `backend/`:

```bash
python scripts/check_asyncio_run.py
python scripts/check_http_500_leaks.py
python scripts/check_router_repositories.py
python scripts/check_text_sql.py
ruff check .
```
