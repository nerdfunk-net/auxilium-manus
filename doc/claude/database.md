# Database

## Schema (Key Tables)

**Domain tables:** `users`, `credentials`, `git_repositories`, `inventories`, `settings`,
`templates`, `workflows`, `workflow_runs`, `workflow_step_results`, `change_requests`

**RBAC tables:** `roles`, `permissions`, `role_permissions`, `user_roles`, `user_permissions`

## Migration System

Use the complete migration framework for all schema changes: `./doc/MIGRATION_SYSTEM.md`

`core/database.py::init_db` runs `AutoSchemaMigration` under a Postgres
`pg_advisory_xact_lock` so concurrent replica boots serialize on `CREATE TABLE`/`ADD COLUMN`/
`CREATE INDEX`. This is a safety net, not a substitute for explicit Alembic migrations at scale.

**`AutoSchemaMigration` ADD COLUMN limits:**
- NOT NULL columns need a scalar Python `default=` (not `server_default`) to back-fill rows
- JSON columns must be nullable
- No FK `REFERENCES` clause is emitted — add FKs via explicit migrations

## SQLAlchemy / Raw SQL Rules

- ✅ Prefer SQLAlchemy ORM/Core for all runtime data access
- ✅ Repository-layer `sqlalchemy.text()` allowed **only** under
  `doc/refactoring/REFACTORING_RAW_SQL.md` §3 (bound parameters, named constants for
  non-trivial SQL, no string composition of values, PostgreSQL integration coverage for
  dialect-specific behaviour)
- ✅ Health checks (`SELECT 1` in `core/database.py`) and migration/schema tooling are exempt
- ❌ Never call `text()` from routers, services, or Hatchet workers
- ❌ Never compose runtime values into raw SQL via f-strings or string concatenation
- ❌ Never bypass repository layer

## Model File Locations

SQLAlchemy models live in `/backend/core/models/` — one file per domain, all exported
from `/backend/core/models/__init__.py`:

| File | Models |
|------|--------|
| `base.py` | `Base` (declarative base) |
| `change_requests.py` | `ChangeRequest` |
| `credentials.py` | `Credential` |
| `git.py` | `GitRepository` |
| `inventories.py` | `Inventory` |
| `rbac.py` | `Permission`, `Role`, `RolePermission`, `UserPermission`, `UserRole` |
| `runs.py` | `WorkflowRun`, `WorkflowStepResult` |
| `settings.py` | `Setting` |
| `templates.py` | `Template` |
| `users.py` | `User` |
| `workflows.py` | `Workflow` |

## Requirements Checklist

- ✅ Define tables as SQLAlchemy models in `/backend/core/models/` (one file per domain)
- ✅ Export all models from `/backend/core/models/__init__.py`
- ✅ Add indexes, foreign keys, timestamps (`created_at`, `updated_at`)
- ✅ Use repository pattern (`BaseRepository` in `/backend/repositories/base.py`)
- ✅ Production: PostgreSQL only. In-memory SQLite acceptable in **unit** tests when
  queries do not rely on PostgreSQL-only features
- ❌ Never create SQLite databases for production use
