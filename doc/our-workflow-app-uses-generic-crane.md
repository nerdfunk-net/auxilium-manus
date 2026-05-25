# Plan: Port Cockpit Git Service to Auxilium Manus

## Context

Auxilium-manus currently has a minimal git "service" (`services/sources/git/git_source_service.py`) that does bare-bones clone/pull and YAML device parsing. The cockpit app has a production-grade git service with full PostgreSQL-backed repository CRUD, sync workflows, version control queries, file browsing, credential management, and 5 sub-router groups. The user wants to replace the simple inline service with the full cockpit implementation so the app is ready for all future git features.

## What Gets Removed

- `backend/services/sources/git/git_source_service.py` — replaced by `services/git/` layer
- `backend/routers/sources/git/ops.py` (preview endpoint) — replaced by cockpit routers
- `backend/routers/sources/git/__init__.py` export and `main.py` import of `git_source_ops_router`

The `workflow_steps/get_git_devices/` step is updated (not deleted) to use the new service.

---

## Phase 1 — Database + Infrastructure

### 1a. Add `get_db_session()` to `core/database.py`
The cockpit's `BaseRepository` calls `get_db_session()` (a direct session factory, not an async generator). Add it:
```python
def get_db_session() -> Session:
    return SessionLocal()
```

### 1b. Create `repositories/base.py`
Copy cockpit's `BaseRepository` verbatim. It uses `get_db_session()` and provides `get_by_id`, `get_all`, `create`, `update`, `delete` via a `_db_session()` context manager that owns or borrows a session.

### 1c. Add SQLAlchemy model — `core/models/git.py`
Copy cockpit's `core/models/git.py` verbatim: `GitRepository` table with all columns (id, name, category, url, branch, auth_type, credential_name, path, verify_ssl, git_author_name, git_author_email, description, is_active, last_sync, sync_status, created_at, updated_at) + two indexes.

### 1d. Update `core/models/__init__.py`
Add `from core.models.git import GitRepository` and add `"GitRepository"` to `__all__`.

### 1e. Create database migration
Create `migrations/versions/XXXX_add_git_repositories.py` using the project's existing migration runner pattern to create the `git_repositories` table.

---

## Phase 2 — Pydantic Models

Copy these two files verbatim from cockpit:
- `backend/models/git_repositories.py` — `GitRepositoryRequest`, `GitRepositoryUpdateRequest`, `GitRepositoryResponse`, `GitRepositoryListResponse`, `GitConnectionTestRequest`, `GitConnectionTestResponse`, `GitCategory` enum, `GitAuthType` enum
- `backend/models/git.py` — `GitCommit`, `GitAuthor`, `SyncResult`, `CloneResult`, `DiffLine`, `DiffResult`, etc.

The `GitCategory` values from cockpit (`device_configs`, `cockpit_configs`, `templates`, `agent`, `csv_imports`, `csv_exports`) can be kept as-is or extended later — no functional impact.

---

## Phase 3 — Repository Layer

### 3a. Create `repositories/git/__init__.py` (empty)

### 3b. Copy `repositories/git/git_repository_repository.py`
Copy verbatim from cockpit. Imports `BaseRepository` from `repositories.base` and `GitRepository` from `core.models`.

### 3c. Update `repositories/__init__.py`
```python
from repositories.git.git_repository_repository import GitRepositoryRepository
__all__ = ["GitRepositoryRepository"]
```

---

## Phase 4 — Service Layer

Copy all files from `cockpit/backend/services/git/` with these targeted adaptations:

| File | Adaptation |
|---|---|
| `__init__.py` | verbatim (empty) |
| `service.py` | verbatim |
| `repository_service.py` | verbatim |
| `operations.py` | verbatim |
| `auth.py` | verbatim — `resolve_credentials()` already catches all exceptions and returns `(None, None, None)` if `build_credentials_service` doesn't exist; credential support is a future task |
| `connection.py` | verbatim |
| `cache.py` | Replace `SettingsManager.get_cache_settings()` call with hardcoded defaults: `{"enabled": True, "ttl_seconds": 600, "max_commits": 500}` |
| `diff.py` | verbatim |
| `file_service.py` | verbatim |
| `config.py` | verbatim |
| `env.py` | verbatim |
| `paths.py` | Replace `Path(config_settings.data_directory) / "git"` → `PROJECT_ROOT / "data" / "git"` (import `PROJECT_ROOT` from `core.config`) |
| `shared_utils.py` | verbatim |

---

## Phase 5 — Router Layer

Copy all files from `cockpit/backend/routers/git/` with one systematic change: replace every `Depends(require_permission("...", "..."))` with `Depends(get_current_user)` (import from `core.auth`). The `current_user` variable type changes from `dict` to `User`.

Files:
- `routers/git/__init__.py` — verbatim
- `routers/git/main.py` — verbatim
- `routers/git/repositories.py` — auth swap
- `routers/git/operations.py` — auth swap
- `routers/git/version_control.py` — auth swap
- `routers/git/files.py` — auth swap
- `routers/git/debug.py` — auth swap

---

## Phase 6 — Wire Up

### 6a. Add to `service_factory.py`
```python
def build_git_service():
    from services.git.service import GitService
    return GitService()

def build_git_auth_service():
    from services.git.auth import GitAuthenticationService
    return GitAuthenticationService()

def build_git_cache_service():
    from services.git.cache import GitCacheService
    cache = build_cache_service()
    return GitCacheService(cache)

def build_git_repository_service():
    from services.git.repository_service import GitRepositoryService
    return GitRepositoryService()

def build_git_operations_service():
    from services.git.operations import GitOperationsService
    return GitOperationsService()

def build_git_connection_service():
    from services.git.connection import GitConnectionService
    return GitConnectionService()
```

### 6b. Add to `dependencies.py`
```python
def get_git_service(): return service_factory.build_git_service()
def get_git_auth_service(): return service_factory.build_git_auth_service()
def get_git_cache_service(): return service_factory.build_git_cache_service()
def get_git_operations_service(): return service_factory.build_git_operations_service()
def get_git_connection_service(): return service_factory.build_git_connection_service()
```

### 6c. Update `main.py`
- Remove import of `git_source_ops_router`
- Add `from routers.git import router as git_router`
- Replace `app.include_router(git_source_ops_router, ...)` with `app.include_router(git_router, prefix=settings.api_prefix)`

---

## Phase 7 — Update `get_git_devices` Workflow Step

The step currently uses `git_source_id` (key in settings table) + `GitDeviceService`. Replace with `git_repository_id` (int ID in `git_repositories` table).

**`workflow_steps/get_git_devices/config.py`** — change `git_source_id: str` → `git_repository_id: int`.

**`workflow_steps/get_git_devices/executor.py`** — new logic:
1. `GitRepositoryService().get_repository(git_repository_id)` → repository dict
2. `GitOperationsService().sync_repository(repository)` → clone/pull
3. `repo_path(repository)` → local path
4. Glob YAML files matching `filename_pattern`
5. Parse with same YAML device extraction logic (move inline from old `git_source_service.py`)

---

## Phase 8 — Remove Old Files

- Delete `backend/services/sources/git/git_source_service.py`
- Delete `backend/routers/sources/git/ops.py` and `backend/routers/sources/git/__init__.py`
- Delete `backend/services/sources/git/` directory if empty

---

## Verification

1. Start backend: `cd backend && python start.py` — must start without import errors
2. Check DB migration applied: `git_repositories` table exists in PostgreSQL
3. Call `GET /api/git-repositories/` → returns `{"repositories": [], "total": 0}`
4. Call `POST /api/git-repositories/` with a test repo config → record created
5. Call `POST /api/git/{id}/sync` → repo clones to `data/git/`
6. Call `GET /api/git/{id}/branches` → returns branches
7. Confirm `get-git-devices` step config schema updated in `workflow_steps/registry.yaml`
8. Run router regression guards: `python scripts/check_asyncio_run.py` and `python scripts/check_http_500_leaks.py`
