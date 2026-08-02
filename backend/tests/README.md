# Backend tests

```text
backend/tests/
  conftest.py          # puts backend/ on sys.path
  unit/                # mocked / in-memory — default suite
  integration/         # real devices / live services — opt-in
```

Unit tests use stdlib `unittest` (`TestCase` / `IsolatedAsyncioTestCase`) and run under **pytest**. External I/O is mocked; DB-backed cases use in-memory SQLite. No running PostgreSQL, Redis, Hatchet, or Nautobot is required for `unit/`.

## Prerequisites

1. Project virtualenv at the **repo root** (`.venv/`, Python 3.14 — not `backend/.venv`).
2. Dev dependencies installed once:

```bash
# from repo root
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
```

Config: `backend/pyproject.toml` (`testpaths = ["tests/unit"]`).

## How to start tests

### Unit (default)

From **`backend/`**:

```bash
cd backend
python -m pytest
```

From the **repo root**:

```bash
python -m pytest backend/tests/unit
```

One file / class / test:

```bash
python -m pytest tests/unit/test_rbac_service.py
python -m pytest tests/unit/test_rbac_service.py::RBACServiceHasPermissionTests
python -m pytest tests/unit/test_rbac_service.py::RBACServiceHasPermissionTests::test_role_grant_allows
```

By keyword / verbose / coverage:

```bash
python -m pytest -k "rbac or fan_out"
python -m pytest -v
python -m pytest --cov=. --cov-report=term-missing
```

### Integration (opt-in)

```bash
cd backend
python -m pytest tests/integration
# or:
python -m pytest -m integration
```

See `integration/README.md` for credentials and device conventions.

### unittest discovery

```bash
cd backend && python -m unittest discover -s tests/unit
```

## Common mistake

If you see dozens of collection errors like `ModuleNotFoundError: No module named 'core'`, use the project `.venv` and one of the commands above (imports are wired via `tests/conftest.py`).

## Related checks (not under `tests/`)

From `backend/`:

```bash
python scripts/check_asyncio_run.py
python scripts/check_http_500_leaks.py
python scripts/check_router_repositories.py
python scripts/check_text_sql.py
ruff check .
```
