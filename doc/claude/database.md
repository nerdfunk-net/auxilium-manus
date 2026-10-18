# Database

## Schema (Key Tables)

**Domain tables (27):** `users`, `credentials`, `git_repositories`, `inventories`, `settings`,
`templates`, `workflows`, `workflow_runs`, `workflow_step_results`,
`workflow_run_device_groups` (fan-out child progress), `workflow_run_events` (live in-step
events), `change_requests`, `workflow_schedules`, `workflow_background_tier`,
`workflow_changes`, `workflow_ai_sessions`, `notifications`, `user_preferences`,
`job_statistics`, `device_data_records`, `report_data_records`, `report_datasets`, `report_definitions`, `report_snapshots`, `secret_manager_connections`, `user_ai_settings`,
`ai_conversations`

**RBAC tables (5):** `roles`, `permissions`, `role_permissions`, `user_roles`, `user_permissions`

**`workflow_runs.parent_run_id`** (nullable self FK, `ON DELETE SET NULL`, indexed) links a run to the
run whose `start-workflow` step started it; `trigger_type` is then `workflow`.
**`workflow_runs.ancestor_workflow_ids`** (nullable JSON list) holds the workflow ids of every run above
it, root first. The recursion guard reads it because `parent_run_id` is cleared when an ancestor run is
deleted or purged.

## Migration System

Schema changes are applied by `AutoSchemaMigration` on start: `./doc/MIGRATION_SYSTEM.md`. There are no numbered migrations and no Alembic.

`core/database.py::init_db` runs `AutoSchemaMigration` under a Postgres
`pg_advisory_xact_lock` so concurrent replica boots serialize on `CREATE TABLE`/`ADD COLUMN`/
`CREATE INDEX`. It never drops or rewrites anything (see "What Gets Applied Automatically" in that file).

**`AutoSchemaMigration` ADD COLUMN limits:**
- NOT NULL columns need a scalar Python `default=` (not `server_default`) to back-fill rows
- JSON columns must be nullable
- A foreign-key column is added together with its `FOREIGN KEY … ON DELETE …` constraint, in the same transaction (O1-02); a constraint that cannot be created leaves no half-added column

## SQLAlchemy / Raw SQL Rules

- ✅ Prefer SQLAlchemy ORM/Core for all runtime data access
- ✅ Repository-layer `sqlalchemy.text()` allowed **only** under
  the allow-list in `backend/scripts/check_text_sql.py` (bound parameters, named constants for
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
| `ai_conversations.py` | `AiConversation` |
| `background_tier.py` | `WorkflowBackgroundTier` |
| `change_requests.py` | `ChangeRequest` |
| `credentials.py` | `Credential` |
| `device_data_records.py` | `DeviceDataRecord` |
| `git.py` | `GitRepository` |
| `inventories.py` | `Inventory` |
| `job_statistics.py` | `JobStatistic` |
| `notifications.py` | `Notification` |
| `rbac.py` | `Permission`, `Role`, `RolePermission`, `UserPermission`, `UserRole` |
| `report_data_records.py` | `ReportDataRecord` |
| `report_datasets.py` | `ReportDataset` |
| `report_definitions.py` | `ReportDefinition` |
| `report_snapshots.py` | `ReportSnapshot` |
| `runs.py` | `WorkflowRun`, `WorkflowStepResult`, `WorkflowRunDeviceGroup`, `WorkflowRunEvent` |
| `schedules.py` | `WorkflowSchedule` |
| `secret_manager.py` | `SecretManagerConnection` |
| `settings.py` | `Setting` |
| `templates.py` | `Template` |
| `user_preferences.py` | `UserPreference` |
| `user_ai_settings.py` | `UserAiSettings` |
| `users.py` | `User` |
| `workflow_ai_session.py` | `WorkflowAiSession` |
| `workflow_changes.py` | `WorkflowChange` |
| `workflows.py` | `Workflow` |

## Requirements Checklist

- ✅ Define tables as SQLAlchemy models in `/backend/core/models/` (one file per domain)
- ✅ Export all models from `/backend/core/models/__init__.py`
- ✅ Add indexes, foreign keys, timestamps (`created_at`, `updated_at`)
- ✅ Use repository pattern (`BaseRepository` in `/backend/repositories/base.py`)
- ✅ Production: PostgreSQL only. In-memory SQLite acceptable in **unit** tests when
  queries do not rely on PostgreSQL-only features
- ❌ Never create SQLite databases for production use
