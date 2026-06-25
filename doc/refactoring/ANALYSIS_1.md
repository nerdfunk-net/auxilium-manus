# Backend Analysis — Architectural Violations & Refactoring Candidates

> Generated: 2026-06-25
> Last updated: 2026-06-25 — Items 1–7 implemented in `doc/refactoring/REFACTORING_1.md`

## Executive Summary

The backend is structurally sound in most domains (workflows, credentials, settings, auth, runs) — these follow the full Model→Repository→Service→Router layering correctly with thin routers delegating to services. The primary concentration of violations is in the **git domain**, where three large router files contain significant business logic that duplicates or bypasses an existing service layer. Two service files exceed the 800-line limit. A stale import of a non-existent `services.settings.manager` module exists and would fail at runtime on a specific code path.

---

## 1. File Size Violations (>800 lines)

| File | Lines | Concern |
|------|-------|---------|
| `services/git/file_service.py` | 871 | `GitFileService` with 9 methods spanning file search, content, history, CSV parsing — high cohesion but worth splitting |
| `services/sources/nautobot/query_service.py` | 807 | `NautobotSourceQueryService` — right at boundary; acceptable as already extracted from a larger class |

**Near-limit files (600–799 lines) — watch zone:**

| File | Lines | Concern |
|------|-------|---------|
| `routers/git/debug.py` | 745 | **Router** at 745 lines — routers must be thin; see Section 3 |
| `services/git/service.py` | 745 | `GitService` with 12 methods — see Section 2 |
| `routers/git/operations.py` | 429 | Contains full git clone/pull logic — see Section 3 |

---

## 2. God Object Services

### `GitService` — `services/git/service.py` (745 lines, 12 methods)

**Methods:** `get_repo_path`, `open_or_clone`, `clone`, `_clone_fresh`, `pull`, `push`, `commit`, `commit_and_push`, `fetch`, `get_status`, `with_auth_environment`, plus private helpers.

**Why it's a concern:** The class combines cloning, pulling, pushing, committing, fetching, and status-checking — essentially all git operations — in a single class. Each operation group is independently testable and used independently. The git domain already has `services/git/operations.py` (GitOperationsService), `services/git/auth.py` (auth), `services/git/cache.py` (caching), and `services/git/diff.py` (diffs), so the decomposition pattern already exists but was not applied to `GitService` itself.

**Suggested split:**
- `GitCloneService` — `open_or_clone`, `clone`, `_clone_fresh`
- `GitSyncService` — `pull`, `fetch`
- `GitCommitService` — `commit`, `commit_and_push`, `push`
- Keep `get_status` in `GitOperationsService` (already exists)

### `GitFileService` — `services/git/file_service.py` (871 lines, 9 methods)

**Methods:** `search_files`, `get_commit_files`, `get_file_last_commit`, `get_file_history`, `get_file_content`, `get_file_content_parsed`, `get_directory_tree`, `get_directory_files`, `list_csv_files`, `get_csv_headers`.

**Why it's a concern:** Mixes file browsing (search, tree, listing), content retrieval, history queries, and CSV-specific parsing. CSV parsing has no relation to the other file operations.

**Suggested split:**
- `GitFileQueryService` — search, listing, tree, content, history
- `GitCsvService` — `list_csv_files`, `get_csv_headers`, `get_file_content_parsed`

### `RedisCacheService` — `services/cache/redis_cache_service.py` (461 lines, 14 methods)

**Assessment:** Borderline. The class mixes core cache operations with admin/diagnostic operations (`stats`, `get_entries`, `get_performance_metrics`, `cleanup_expired`). Not a blocker but the admin surface could be extracted to a `CacheAdminService` wrapper if the file grows.

---

## 3. Business Logic in Routers

### CRITICAL: `routers/git/operations.py` — Git sync/clone in router (429 lines) ✅ DONE

The `sync_repository` endpoint (lines 81–225) and `remove_and_sync_repository` endpoint (lines 229–351) perform **full git clone/pull operations directly inside route handlers**, including:
- Directory creation (`os.makedirs`)
- Repository backup (`shutil.move`)
- Git clone (`Repo.clone_from`)
- Git pull (`origin.pull`)
- Error classification by string matching
- Cleanup on failure (`shutil.rmtree`)

**The violation:** `GitOperationsService` at `services/git/operations.py` already implements `sync_repository` and `remove_and_sync` with identical logic. The router uses `git_operations_service` **only** for `get_repository_status` (line 66) and completely reimplements the sync operations itself.

**Fix:** Replace the 140+ lines of git logic in `sync_repository` with:
```python
result = git_operations_service.sync_repository(repository)
if not result.success:
    raise HTTPException(status_code=500, detail=result.message)
return {"success": True, "message": result.message, "repository_path": result.repo_path}
```
Similarly for `remove_and_sync_repository`.

### CRITICAL: `routers/git/debug.py` — 745-line router with all operations inline ✅ DONE

Debug endpoints (`debug_read_test`, `debug_write_test`, `debug_delete_test`, `debug_push_test`, plus diagnostics at lines 420+) implement file I/O, git push, SSL certificate checking, SSH key testing, and connection diagnostics **directly in the router**. There is no `GitDebugService` — all logic is in route handlers.

**Fix:** Extract a `GitDebugService` in `services/git/debug_service.py` and delegate. The router becomes a thin pass-through to the service.

### MODERATE: `routers/git/version_control.py` — commit iteration in router (253 lines) ✅ DONE

The `get_commits` endpoint (lines 51–108) iterates commits, formats commit dicts, and manages cache key logic inline. The `compare_commits` endpoint uses `difflib` directly. This logic should live in `GitCacheService` or a new `GitVersionControlService`.

---

## 4. Layer Violations

### Direct DB access pattern in `GitRepositoryRepository` ✅ DONE

`repositories/git/git_repository_repository.py` calls `get_db_session()` directly inside each method (creating and closing its own session per call) rather than accepting an injected `Session`. This deviates from the pattern used by `InventoryRepository`, `WorkflowRepository`, `RunRepository`, and `SettingsRepository`, which all accept `db: Session` in `__init__`.

The result: `GitRepositoryService` is constructed with no `db` argument and cannot participate in a shared transaction scope. It is a module-level singleton (`git_repo_manager = GitRepositoryManager()` in `shared_utils.py`) rather than a request-scoped service.

**Impact:** Git repository CRUD operations cannot be batched in atomic transactions with other domain operations.

### `InventoryPersistenceService` is a thick service, not a persistence layer ✅ DONE (renamed to `InventoryService`)

`services/sources/nautobot/persistence_service.py` (366 lines, 15 methods) wraps `InventoryRepository` but also contains:
- Business access-control logic (`_assert_access`)
- Group path manipulation logic (`rename_group`, `get_all_groups`)
- Health check (`health_check`)
- Data transformation (`_model_to_dict`)

The name (`PersistenceService`) implies it is a repository. It is actually a service class. Rename to `InventoryService` to clarify its role in the layer stack.

### Stale/broken import: `services/settings/manager.py` does not exist ✅ DONE

`routers/git/files.py` (line 59) contains:
```python
from services.settings.manager import SettingsManager
```
The file `services/settings/manager.py` **does not exist**. This import is inside a function body so it does not fail at startup — it fails at runtime when `get_file_complete_history` is called. This is dead code from a prior refactoring.

**Fix:** Remove the import and `SettingsManager` usage; replace `cache_cfg` with a direct call to `CacheSettingsService` or hardcode defaults.

### `git_repo_manager` singleton bypasses FastAPI DI

`services/git/shared_utils.py` exposes a module-level singleton:
```python
git_repo_manager = GitRepositoryManager()
```
This is imported directly in three router files (`repositories.py`, `operations.py`, `debug.py`), bypassing the `Depends()` injection system. Services accessed in routers should go through FastAPI's DI system for testability and lifecycle management.

---

## 5. text() SQL Violations

**None found in application code.**

`text()` usage is confined exclusively to migration files (`migrations/versions/*.py`, `migrations/runner.py`), which are explicitly exempt per the documented policy. No violations.

---

## 6. HTTPException 5xx Leaks

### CONFIRMED 5xx violations in `routers/git/operations.py` ✅ DONE

```
routers/git/operations.py:218  raise HTTPException(status_code=500, detail=message)
routers/git/operations.py:344  raise HTTPException(status_code=500, detail=message)
```

The `message` variable is built from strings like `f"Git clone failed: {err}"` and `f"Unexpected error: {str(e)}"` — raw exception text in 500 responses. Must use `raise_internal_server_error(logger, ..., exc)` instead.

### CONFIRMED 5xx violations in `routers/git/repositories.py`

```
routers/git/repositories.py:148  raise HTTPException(status_code=500, detail="Failed to update repository")
routers/git/repositories.py:184  raise HTTPException(status_code=500, detail="Failed to delete repository")
```

These use static strings (no exception text leaked). Should still use `raise_internal_server_error`. **Low severity.**

### 4xx with `str(exc)` — leaks internal exception messages to clients

Not a 5xx violation, but `str(exc)` in 4xx responses leaks internal error messages. Found in:

| File | Lines | Status codes |
|------|-------|-------------|
| `routers/credentials.py` | 68, 93, 95, 109, 124, 126 | 404, 409 |
| `routers/sources/nautobot/ops.py` | 75, 200, 271 | 400, 403 |
| `routers/sources/nautobot/crud.py` | 61, 184, 240, 262, 301, 322 | 400, 403 |
| `routers/git/repositories.py` | 119, 164 | 400 |
| `routers/sources/git/ops.py` | 86 | 400 |

For `credentials.py`, custom domain exceptions (`CredentialNotFoundError`, `CredentialNameConflictError`) are intentionally user-friendly — acceptable if messages are controlled. For generic `ValueError` in Nautobot routers, the text may contain internal details.

---

## 7. f-string Logging Violations

**None found.** All logging uses `%s` / `%d` parameter interpolation correctly throughout the codebase. ✅

---

## 8. Structural / Naming Issues

### Two Pydantic model files for the git domain

- `models/git.py` — commit/diff/operation models (`GitAuthor`, `CommitInfo`, `SyncResult`, etc.)
- `models/git_repositories.py` — repository CRUD models (`GitRepositoryRequest`, `GitRepositoryResponse`, etc.)

The split is acceptable given distinct concerns, but naming is inconsistent. Consider renaming `models/git.py` → `models/git_operations.py` to clarify.

### `models/__init__.py` is empty

Pydantic models in `models/` do not require re-export from `__init__.py`. No action needed.

### CLAUDE.md references non-existent SQLAlchemy models

CLAUDE.md lists `audit.py` (`AuditLog`) and `rbac.py` (`Permission`, `Role`, `RolePermission`, `UserPermission`, `UserRole`) as existing files in `core/models/`. **Neither file exists.** RBAC features are absent from the entire codebase — no models, repositories, services, or routers.

**Action:** Either remove these references from CLAUDE.md or create tracking issues for planned implementation.

---

## 9. Missing Layer Coverage

| Domain | Model | Repository | Service | Router | Gap |
|--------|-------|------------|---------|--------|-----|
| workflows | ✅ | ✅ | ✅ | ✅ | None |
| workflow runs | ✅ | ✅ | ✅ | ✅ | None |
| credentials | ✅ | ✅ | ✅ | ✅ | None |
| git repositories | ✅ | ✅ | ✅ | ✅ | Session injection in repository |
| settings | ✅ | ✅ | ✅ | ✅ | None |
| users / auth | ✅ | ✅ | ✅ | ✅ | None |
| inventories | ✅ | ✅ | ✅ (as `InventoryService`) | ✅ | Renamed ✅ |
| audit | ❌ | ❌ | ❌ | ❌ | Entirely missing |
| rbac (permissions/roles) | ❌ | ❌ | ❌ | ❌ | Entirely missing |
| cache | N/A | N/A | ✅ | ✅ | None |

---

## 10. Prioritized Refactoring Plan

### HIGH — Fix immediately (correctness)

1. ✅ **Fix broken import in `routers/git/files.py`** — `from services.settings.manager import SettingsManager` crashes at runtime. Replace with `CacheSettingsService` or hardcode defaults.

2. ✅ **Delegate git sync to `GitOperationsService` from `routers/git/operations.py`** — `sync_repository` and `remove_and_sync_repository` reimplent logic that already exists in `services/git/operations.py`. Remove ~140 lines of duplicate code from the router; call the service instead.

3. ✅ **Fix 5xx HTTPException leaks in `routers/git/operations.py`** — Lines 218 and 344 raise raw exception text in 500 responses. Replace with `raise_internal_server_error(logger, "...", exc)`.

### MEDIUM — Architecture clean-up

4. ✅ **Extract `GitDebugService` from `routers/git/debug.py`** — 745-line router must become thin. Extract all logic to `services/git/debug_service.py`.

5. ✅ **Move commit iteration out of `routers/git/version_control.py`** — `get_commits` builds dicts and manages cache keys inline; `compare_commits` uses `difflib`. Extract to `GitCacheService` or a new `GitVersionControlService`.

6. ✅ **Fix `GitRepositoryRepository` session injection** — Change to accept `db: Session` at `__init__` like all other repositories. Remove the module-level `git_repo_manager` singleton; register via FastAPI `Depends()`.

7. ✅ **Rename `InventoryPersistenceService` → `InventoryService`** — Clarifies its role as a service, not a persistence layer.

### LOW — Code quality

8. **Split `GitFileService` (871 lines)** — Extract CSV methods (`list_csv_files`, `get_csv_headers`, `get_file_content_parsed`) to `GitCsvService`.

9. **Split `GitService` (745 lines)** — Extract clone, sync, and commit groups into focused classes.

10. **Update CLAUDE.md** — Remove or track `audit.py` and `rbac.py` references that describe non-existent models.

11. **Audit `str(exc)` in 4xx responses** — Ensure all custom exception messages are user-safe; replace generic `ValueError` messages in Nautobot routers with controlled strings.
