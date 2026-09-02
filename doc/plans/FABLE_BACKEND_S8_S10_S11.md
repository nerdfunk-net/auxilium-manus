# Plan: Fix S8, S10, S11

Source: `doc/analysis/FABLE_BACKEND_20260902.md` §5.3.
Scope: three MEDIUM backend findings. All three are small, independent, and can land
in any order.
Status: **implemented** on branch `fix/fable-backend-s8-s10-s11` (`1184086`, docs `HEAD`).

| # | Sev | Issue | Clarity | Decision |
|---|---|---|---|---|
| S8 | M | Git path-traversal guard uses a string `startswith` prefix | Clear | D1 |
| S10 | M | Bootstrap admin is re-granted `admin` on every startup | Clear | D2 |
| S11 | M | Schema DDL runs at startup with no cross-process lock | Clear | D3 |

Every issue ends with the tests that must exist before the fix is considered done.

---

## 0. Decisions (resolved)

**D1 — one containment helper in `services/git/paths.py`, raising `AccessDeniedError`.**

`services/git/file_service.py` (×4) and `services/git/csv_service.py` (×1) each
re-implement the same "is this resolved path inside the repo" check with
`resolved.startswith(repo_root)`. Both modules already import `AccessDeniedError`
from `core.domain_exceptions` and `repo_path` from `services.git.paths`, so the new
helper goes next to `repo_path` (which already does correct containment via
`Path.relative_to`) and raises `AccessDeniedError` directly. No new module, no new
import lines beyond the helper name. (`core.domain_exceptions` is a leaf module —
importing it from `paths.py` introduces no cycle; confirm with
`python -c "import services.git.paths"` after the change.)

**D2 — S10: grant the bootstrap admin role only when nobody holds it.**

`main.py::lifespan` currently calls `assign_role_to_user_by_name(admin.id, "admin")`
unconditionally. Replace with: grant **iff** no user currently holds `admin`. This:

- still works on first boot (the freshly created admin has no roles yet → granted);
- self-heals a system that somehow lost every admin (→ re-granted to `INITIAL_USERNAME`);
- respects a deliberate demotion of `INITIAL_USERNAME` as long as at least one other
  admin remains (→ not re-granted).

No signature change to `AuthService.ensure_initial_admin` (keeps its five call sites
untouched). The same guard is also applied to `admin_reseed_rbac`'s non-wipe path.

**D3 — S11: `pg_advisory_xact_lock` inside `engine.begin()`.**

A transaction-scoped advisory lock is released automatically when the transaction
ends (commit *or* rollback), so a pooled connection returned to the pool with only a
`ROLLBACK` cannot leak it — unlike session-level `pg_advisory_lock`, which survives
`ROLLBACK` and would need a guaranteed manual `pg_advisory_unlock`. The lock
connection is held open for the duration of the schema sync while
`AutoSchemaMigration` / `SchemaManager` open their own pooled connections for the
DDL. A full migration framework (Alembic) is the analysis's stronger alternative and
remains a separate, larger effort — this is the minimal safe fix.

---

## 1. S8 — Path-traversal guard is a string prefix test

### 1.1 Problem in one sentence

`GitFileService` and `GitCsvService` reject out-of-repo paths with
`resolved.startswith(repo_root_resolved)`, so a repository on disk at
`.../data/git/foo` also matches `.../data/git/foo-other` — a request for
`../foo-other/secret.txt` passes the check. Repository paths are admin-defined, so
exploitation needs an adjacent repo, but the check is wrong.

Occurrences (all the same bug):

| File | Function | Line |
|---|---|---|
| `services/git/file_service.py` | `_resolve_directory_listing_path` | ~138 |
| `services/git/file_service.py` | `get_file_content` | ~502 |
| `services/git/file_service.py` | `get_file_content_parsed` | ~553 |
| `services/git/file_service.py` | `get_directory_tree` | ~615 |
| `services/git/csv_service.py` | `get_csv_headers` | ~110 |

### 1.2 The helper — `services/git/paths.py`

before (end of file):

```python
def repo_path(repository: dict) -> Path:
    """Compute the on-disk path for a repository under ``data/git/``.

    Rejects ``..`` segments and any resolved path that escapes the git data root.
    """
    raw = repository.get("path") or repository.get("name")
    if raw is None or not str(raw).strip():
        raise ValueError("repository path/name is required")

    sub_path = _sanitize_git_subpath(str(raw))
    root = _GIT_DATA_ROOT.resolve()
    candidate = (root / sub_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"repository path escapes data/git: {raw!r}") from exc
    return candidate
```

after (add the import and the helper):

```python
from core.config import PROJECT_ROOT
from core.domain_exceptions import AccessDeniedError

_GIT_DATA_ROOT = PROJECT_ROOT / "data" / "git"

# ... _sanitize_git_subpath and repo_path unchanged ...


def resolve_within_repo(repo_root: str | Path, relative: str | None) -> Path:
    """Resolve ``relative`` under ``repo_root`` and fail closed if it escapes.

    Uses proper path-boundary containment (``Path.is_relative_to``), not a string
    ``startswith`` — ``/data/git/foo-other`` must not count as inside
    ``/data/git/foo``. Symlinks are resolved (``Path.resolve``), matching the
    previous ``os.path.realpath`` behaviour. An absolute or ``..`` ``relative``
    that lands outside the repo raises ``AccessDeniedError``.
    """
    root = Path(repo_root).resolve()
    target = (root / relative).resolve() if relative else root
    if not target.is_relative_to(root):
        raise AccessDeniedError("Access denied: path is outside repository")
    return target
```

### 1.3 Call sites

**`file_service.py::_resolve_directory_listing_path`** — before:

```python
def _resolve_directory_listing_path(repo_path: str, path: str) -> str | None:
    target_path = os.path.join(repo_path, path) if path else repo_path
    target_path_resolved = os.path.realpath(target_path)
    repo_path_resolved = os.path.realpath(repo_path)

    if not target_path_resolved.startswith(repo_path_resolved):
        raise AccessDeniedError("Access denied: path is outside repository")

    if not os.path.exists(target_path_resolved):
        return None

    if not os.path.isdir(target_path_resolved):
        raise ValidationFailedError(f"Path is not a directory: {path}")

    return target_path_resolved
```

after:

```python
def _resolve_directory_listing_path(repo_path: str, path: str) -> str | None:
    target_path_resolved = str(resolve_within_repo(repo_path, path))

    if not os.path.exists(target_path_resolved):
        return None

    if not os.path.isdir(target_path_resolved):
        raise ValidationFailedError(f"Path is not a directory: {path}")

    return target_path_resolved
```

**`file_service.py::get_file_content`** — before:

```python
            repo_path = git_repo_path(repository)

            if not os.path.exists(repo_path):
                raise NotFoundError(f"Repository directory not found: {repo_path}")

            file_path = os.path.join(repo_path, path)
            file_path_resolved = os.path.realpath(file_path)
            repo_path_resolved = os.path.realpath(repo_path)

            if not file_path_resolved.startswith(repo_path_resolved):
                raise AccessDeniedError("Access denied: file path is outside repository")

            if not os.path.exists(file_path_resolved):
                raise NotFoundError(f"File not found: {path}")
```

after:

```python
            repo_path = git_repo_path(repository)

            if not os.path.exists(repo_path):
                raise NotFoundError(f"Repository directory not found: {repo_path}")

            file_path_resolved = str(resolve_within_repo(repo_path, path))

            if not os.path.exists(file_path_resolved):
                raise NotFoundError(f"File not found: {path}")
```

**`file_service.py::get_file_content_parsed`** and **`get_directory_tree`** — identical
transformation: delete the three `os.path.join` / `os.path.realpath` / `startswith`
lines and replace with

```python
            file_path_resolved = str(resolve_within_repo(repo_path, path))
```

(for `get_directory_tree` the local is `target_path_resolved` and `repo_path` is the
`str(git_repo_path(...))` value — the helper accepts both `str` and `Path`).

**Import change in `file_service.py`** — before:

```python
from services.git.paths import repo_path as git_repo_path
```

after:

```python
from services.git.paths import repo_path as git_repo_path
from services.git.paths import resolve_within_repo
```

**`csv_service.py::get_csv_headers`** — before:

```python
            repo_path_str = str(git_repo_path(repository))

            if not os.path.exists(repo_path_str):
                raise NotFoundError("Repository directory not found")

            file_path = os.path.join(repo_path_str, path)
            file_path_resolved = os.path.realpath(file_path)
            repo_path_resolved = os.path.realpath(repo_path_str)

            if not file_path_resolved.startswith(repo_path_resolved):
                raise AccessDeniedError("Access denied: path is outside repository")

            if not os.path.exists(file_path_resolved):
                raise NotFoundError(f"File not found: {path}")
```

after:

```python
            repo_path_str = str(git_repo_path(repository))

            if not os.path.exists(repo_path_str):
                raise NotFoundError("Repository directory not found")

            file_path_resolved = str(resolve_within_repo(repo_path_str, path))

            if not os.path.exists(file_path_resolved):
                raise NotFoundError(f"File not found: {path}")
```

**Import change in `csv_service.py`** — add `resolve_within_repo` to the existing
`from services.git.paths import ...` line. `AccessDeniedError` may now be unused in
`csv_service.py` — check and drop it from the import if so (ruff `F401`).

### 1.4 Tests (write first)

New `tests/unit/test_git_paths.py` (or extend an existing paths test):

| Test | Asserts |
|---|---|
| `test_resolve_within_repo_allows_nested_path` | `resolve_within_repo("/tmp/repo", "a/b/c.txt")` → `/tmp/repo/a/b/c.txt` |
| `test_resolve_within_repo_allows_empty_relative` | `relative=None` / `""` → the repo root itself |
| `test_resolve_within_repo_rejects_sibling_prefix` | root `/tmp/repo`, `relative="../repo-other/x"` → `AccessDeniedError` (this is the S8 bug: old `startswith` passed) |
| `test_resolve_within_repo_rejects_parent_escape` | `relative="../../etc/passwd"` → `AccessDeniedError` |
| `test_resolve_within_repo_rejects_absolute_relative` | `relative="/etc/passwd"` → `AccessDeniedError` |

Extend `tests/unit/test_git_file_service.py`:

| Test | Asserts |
|---|---|
| `test_get_file_content_rejects_sibling_repo` | create `<tmp>/data/git/foo` and `<tmp>/data/git/foo-evil/secret`, call `get_file_content(repo_id, "../foo-evil/secret")` → `AccessDeniedError` |
| existing traversal tests (lines ~166, ~208) | still raise `AccessDeniedError` |

Add the equivalent sibling-repo test for `GitCsvService.get_csv_headers` in
`tests/unit/test_git_csv_service.py` (create it if absent).

---

## 2. S10 — Bootstrap admin re-granted on every startup

### 2.1 Problem in one sentence

`main.py::lifespan` unconditionally runs
`RBACService(db).assign_role_to_user_by_name(admin_user.id, "admin")` on every boot,
so demoting or restricting `INITIAL_USERNAME` is silently undone by the next restart.
`admin_reseed_rbac` has the same unconditional re-grant on its non-wipe path.

### 2.2 New `RBACService` helper

`backend/services/auth/rbac_service.py` — add next to `assign_role_to_user_by_name`:

```python
    def role_has_members(self, role_name: str) -> bool:
        """True if at least one user currently holds the named role."""
        role = self._repo.get_role_by_name(role_name)
        if role is None:
            return False
        return bool(self._repo.get_users_with_role(role.id))
```

(`RBACRepository.get_role_by_name` and `get_users_with_role` already exist and are
used by `assert_not_last_admin`.)

### 2.3 `main.py::lifespan`

before:

```python
    with SessionLocal() as db:
        admin_user = AuthService(db).ensure_initial_admin()
        seed_rbac(db)
        RBACService(db).assign_role_to_user_by_name(admin_user.id, "admin")
        LoggingSettingsService(db).apply_to_current_process("app")
```

after:

```python
    with SessionLocal() as db:
        admin_user = AuthService(db).ensure_initial_admin()
        seed_rbac(db)
        rbac = RBACService(db)
        # S10: only (re-)grant the bootstrap admin role when *nobody* holds it.
        # First boot: the freshly created admin has no roles yet → granted.
        # Deliberate demotion of INITIAL_USERNAME survives a restart as long as
        # another admin remains. If every admin is gone, self-heal by granting
        # it back to INITIAL_USERNAME.
        if not rbac.role_has_members("admin"):
            logger.warning(
                "No user holds the 'admin' role; granting it to initial user '%s'",
                admin_user.username,
            )
            rbac.assign_role_to_user_by_name(admin_user.id, "admin")
        LoggingSettingsService(db).apply_to_current_process("app")
```

### 2.4 `admin_reseed_rbac` (same guard on the non-wipe path)

`backend/services/auth/rbac_seed.py` — before:

```python
    if remove_existing:
        remove_all_rbac_data(db)

    seed_rbac(db)

    from services.auth.auth_service import AuthService
    from services.auth.rbac_service import RBACService

    admin_user = AuthService(db).ensure_initial_admin()
    RBACService(db).assign_role_to_user_by_name(admin_user.id, "admin")
```

after:

```python
    if remove_existing:
        remove_all_rbac_data(db)

    seed_rbac(db)

    from services.auth.auth_service import AuthService
    from services.auth.rbac_service import RBACService

    admin_user = AuthService(db).ensure_initial_admin()
    rbac = RBACService(db)
    # After a wipe nobody holds any role, so this still re-grants (intended —
    # remove_all_rbac_data cascaded user_roles). Without a wipe, respect a
    # deliberate demotion exactly as main.py's lifespan does (S10).
    if not rbac.role_has_members("admin"):
        rbac.assign_role_to_user_by_name(admin_user.id, "admin")
```

### 2.5 Tests (write first)

New `tests/unit/test_bootstrap_admin_grant.py` (in-memory SQLite, real
`RBACService` / `RBACRepository`, seeded RBAC):

| Test | Asserts |
|---|---|
| `test_role_has_members_false_when_unassigned` | fresh seed, no user_roles → `role_has_members("admin")` is `False` |
| `test_role_has_members_true_after_assign` | assign admin to a user → `True` |
| `test_role_has_members_unknown_role` | `role_has_members("nope")` → `False` |
| `test_grant_runs_on_first_boot` | simulate lifespan step with no admin holder → `INITIAL_USERNAME` ends up with `admin` |
| `test_grant_skipped_when_other_admin_exists` | assign `admin` to user B, ensure `INITIAL_USERNAME` has none, run the step → `INITIAL_USERNAME` still has **no** `admin` role |
| `test_grant_self_heals_when_no_admin` | strip every `admin` holder, run the step → `INITIAL_USERNAME` regains `admin` |

Update `tests/unit/test_auth_service.py` only if it asserted on the lifespan grant
(it tests `ensure_initial_admin` in isolation, so likely no change). Grep
`tests/` for `assign_role_to_user_by_name` and adjust any test that assumed the
unconditional call.

---

## 3. S11 — Schema DDL at startup with no lock

### 3.1 Problem in one sentence

`init_db()` runs `AutoSchemaMigration.run()` (`CREATE TABLE` / `ALTER TABLE ADD
COLUMN` / `CREATE INDEX`) on every boot; two web replicas starting together race and
one errors on a duplicate object. `ensure_database_exists()` has the same
check-then-`CREATE DATABASE` race on a first-ever boot.

### 3.2 `core/database.py`

`text` is already imported (`from sqlalchemy import create_engine, text`).

before:

```python
def init_db() -> None:
    from migrations.auto_schema import AutoSchemaMigration

    ensure_database_exists()

    auto = AutoSchemaMigration(engine, Base)
    results = auto.run()

    total_changes = (
        results["tables_created"] + results["columns_added"] + results["indexes_created"]
    )
    if total_changes:
        logger.info(
            "Schema sync: %s table(s) created, %s column(s) added, %s index(es) created",
            results["tables_created"],
            results["columns_added"],
            results["indexes_created"],
        )
    else:
        logger.info("Database schema is up to date")

    if settings.apply_safe_migrations and not settings.apply_risky_migrations:
        from core.schema_manager import SchemaManager

        logger.info(
            "APPLY_SAFE_DATABASE_MIGRATION=true — applying safe column type/nullable changes"
        )
        _log_column_migration_result(SchemaManager().perform_migration(force=False))

    if settings.apply_risky_migrations:
        from core.schema_manager import SchemaManager

        logger.warning("APPLY_RISKY_DATABASE_MIGRATION=true — applying risky column changes")
        _log_column_migration_result(SchemaManager().perform_migration(force=True))
```

after:

```python
# S11: fixed, arbitrary key (fits a signed 32-bit int) so every booting process
# contends on the same Postgres advisory lock while syncing the schema.
_SCHEMA_SYNC_LOCK_KEY = 415_588_2026 % 2_147_483_647  # any stable constant is fine


def init_db() -> None:
    ensure_database_exists()

    # Serialize schema sync across processes/replicas. Two instances starting
    # together would otherwise race on CREATE TABLE / ADD COLUMN / CREATE INDEX
    # and one would error out. pg_advisory_xact_lock is released automatically
    # when this transaction ends (commit or rollback), so a pooled connection
    # cannot leak it. The lock connection is held open while AutoSchemaMigration
    # / SchemaManager take their own pooled connections for the DDL (default
    # pool size 5 + 10 overflow — plenty). A second booter blocks on the lock,
    # then runs _sync_schema() and finds nothing to do.
    with engine.begin() as lock_conn:
        lock_conn.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": _SCHEMA_SYNC_LOCK_KEY},
        )
        _sync_schema()


def _sync_schema() -> None:
    from migrations.auto_schema import AutoSchemaMigration

    auto = AutoSchemaMigration(engine, Base)
    results = auto.run()

    total_changes = (
        results["tables_created"] + results["columns_added"] + results["indexes_created"]
    )
    if total_changes:
        logger.info(
            "Schema sync: %s table(s) created, %s column(s) added, %s index(es) created",
            results["tables_created"],
            results["columns_added"],
            results["indexes_created"],
        )
    else:
        logger.info("Database schema is up to date")

    if settings.apply_safe_migrations and not settings.apply_risky_migrations:
        from core.schema_manager import SchemaManager

        logger.info(
            "APPLY_SAFE_DATABASE_MIGRATION=true — applying safe column type/nullable changes"
        )
        _log_column_migration_result(SchemaManager().perform_migration(force=False))

    if settings.apply_risky_migrations:
        from core.schema_manager import SchemaManager

        logger.warning("APPLY_RISKY_DATABASE_MIGRATION=true — applying risky column changes")
        _log_column_migration_result(SchemaManager().perform_migration(force=True))
```

> Pick a plain readable literal for `_SCHEMA_SYNC_LOCK_KEY` (e.g. `911_020_902`);
> the only requirements are that it is stable across releases and fits a signed
> 64-bit integer. The `% 2_147_483_647` above is just a reminder it must be bounded.

### 3.3 `ensure_database_exists` — swallow the concurrent-create race

before:

```python
            if not database_exists:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(settings.database_name),
                    ),
                )
```

after:

```python
            if not database_exists:
                try:
                    cursor.execute(
                        sql.SQL("CREATE DATABASE {}").format(
                            sql.Identifier(settings.database_name),
                        ),
                    )
                except psycopg.errors.DuplicateDatabase:
                    # Another instance created it between our SELECT and now.
                    logger.info(
                        "Database %s already created by a concurrent starter",
                        settings.database_name,
                    )
```

### 3.4 Tests (write first)

Unit — `tests/unit/test_database_init.py` (new):

| Test | Asserts |
|---|---|
| `test_init_db_locks_before_sync` | patch `core.database.ensure_database_exists`, `core.database._sync_schema` (spy), and `engine.begin` (MagicMock ctx mgr). Call `init_db()`. Assert `lock_conn.execute` was called with a statement whose text contains `pg_advisory_xact_lock` and `params={"key": _SCHEMA_SYNC_LOCK_KEY}`, **before** `_sync_schema` ran, and inside the `begin()` context |
| `test_init_db_runs_full_sync` | `_sync_schema` with a stubbed `AutoSchemaMigration` returning zero changes logs "up to date"; with non-zero logs the summary line (moved verbatim, so this is a regression guard) |
| `test_ensure_database_exists_ignores_duplicate` | cursor raises `psycopg.errors.DuplicateDatabase` on `CREATE DATABASE` → `ensure_database_exists()` returns normally, logs the concurrent-create line |

Integration — extend `tests/integration/test_db_bootstrap.py`:

| Test | Asserts |
|---|---|
| `test_init_db_releases_advisory_lock` | after `init_db()`, a fresh connection sees `SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'` == 0 |
| `test_concurrent_init_db_no_error` (opt.) | run `init_db()` from 2–3 threads against the test DB; no exception, schema diff afterwards is empty |

---

## 4. Order of work and effort

| Step | Depends on | Effort |
|---|---|---|
| S8 — `resolve_within_repo` helper + 5 call sites + tests | none | 0.25 day |
| S10 — `role_has_members` + lifespan/reseed guard + tests | none | 0.25 day |
| S11 — advisory lock in `init_db` + `DuplicateDatabase` guard + tests | none | 0.25–0.5 day |

All three are independent. Suggested landing order S8 → S10 → S11 (smallest blast
radius first; S11 touches the startup path and wants the integration test run).

---

## 5. Definition of done

- [x] All tests in §1.4, §2.5, §3.4 exist and pass (`test_git_paths`,
      `test_git_file_service`, `test_git_csv_service`, `test_rbac_service`,
      `test_rbac_seed`, `test_database_init` — 2146 unit tests pass); coverage 82.24 %
      (ratchet 81 %).
- [x] `ruff check` clean on touched files; the four `scripts/check_*.py` guards pass;
      `python -c "import services.git.paths"` succeeds (no import cycle).
- [x] Grep confirms **zero** remaining `.startswith(repo_path_resolved)` /
      `.startswith(repo_path_str` containment checks under `backend/services/git/`;
      every FS path check goes through `resolve_within_repo`.
- [x] Booting with `INITIAL_USERNAME` demoted (another admin present) and restarting
      leaves it demoted. Removing every admin and restarting re-grants `admin` to
      `INITIAL_USERNAME`. First boot still yields a working admin.
      (`test_non_wipe_reseed_respects_deliberate_demotion`,
      `RBACServiceRoleHasMembersTests`.)
- [x] `init_db()` acquires `pg_advisory_xact_lock` before any DDL
      (`test_locks_before_sync_inside_transaction`); a concurrent first-boot
      `CREATE DATABASE` race is swallowed (`test_duplicate_database_is_swallowed`).
      Advisory-lock-release / concurrency assertions are left to the integration
      suite (needs a real Postgres).
- [x] `doc/analysis/FABLE_BACKEND_20260902.md` §5.3 rows S8, S10, S11 updated to
      "Fixed" with commit `1184086`.
- [x] CLAUDE.md: note under "Database Requirements" that startup schema sync is
      serialized by a Postgres advisory lock (still not a replacement for explicit
      migrations at scale).
