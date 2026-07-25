# Migration System - Overview

## How It Works

Schema changes are **automatic**. There are no numbered migration files to write.

On startup, `init_db()` (`backend/core/database.py`) calls `AutoSchemaMigration`, which compares
the live PostgreSQL schema against the SQLAlchemy models registered in `Base.metadata` and applies
any safe differences.

### To add or modify a table

1. **Edit the SQLAlchemy model** in `/backend/core/models/{domain}.py`
2. **Export it** from `/backend/core/models/__init__.py` (if new model)
3. **Restart the app** — tables, columns, and indexes are created automatically

That's it. No migration file required.

---

## File Structure

```
backend/
├── migrations/
│   ├── __init__.py          # Exports AutoSchemaMigration, ColumnDiff, SchemaDiff
│   └── auto_schema.py       # AutoSchemaMigration — detects and applies schema diffs
│
├── core/
│   ├── database.py          # init_db() — runs AutoSchemaMigration on startup
│   ├── schema_manager.py    # SchemaManager — used by the API endpoints and sync script
│   └── models/               # SQLAlchemy model definitions (one file per domain)
│
├── routers/system.py         # GET /api/system/schema/status, POST /api/system/schema/migrate
│
└── scripts/database/
    └── sync.py                # CLI tool for manual inspection and migration
```

---

## What Gets Applied Automatically (on Startup)

| Change | Applied? |
|--------|----------|
| Create missing tables | ✅ Always |
| Add missing columns | ✅ Always |
| Create missing indexes | ✅ Always |
| Safe type widening (e.g. `VARCHAR→TEXT`, `INTEGER→BIGINT`) | ⚠ Only when `APPLY_SAFE_DATABASE_MIGRATION=true` |
| Risky type casts (may truncate data) | ⚠ Only when `APPLY_RISKY_DATABASE_MIGRATION=true` |
| Adding `NOT NULL` to nullable column | ⚠ Only when `APPLY_RISKY_DATABASE_MIGRATION=true` |
| Drop extra tables or columns | ❌ Never (use `sync.py --drop` / `--drop-columns` manually) |

Structural changes (missing tables, columns, indexes) always apply on every startup, regardless of
env vars. Column *type* and *nullable* changes are opt-in.

---

## CLI Sync Tool

For manual inspection and controlled migrations:

```bash
# From backend/ (with the project venv active)

# Check: report all differences without touching the database
python scripts/database/sync.py

# Apply safe changes (same as startup)
python scripts/database/sync.py --migrate

# Also apply risky type changes (may cause data loss — use with care)
python scripts/database/sync.py --migrate --force

# Drop tables absent from models
python scripts/database/sync.py --migrate --drop

# Drop columns absent from models
python scripts/database/sync.py --migrate --drop-columns

# Focus on a single table
python scripts/database/sync.py --table users
```

Check mode (no `--migrate`) exits with code 1 if differences exist — usable in CI.

---

## API Endpoints

Both require RBAC permission `system.database:read` (status) or `system.database:write` (migrate):

```
GET  /api/system/schema/status          # read-only diff report
POST /api/system/schema/migrate?force=  # apply changes (force=true also applies risky changes)
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APPLY_SAFE_DATABASE_MIGRATION` | `false` | When `true`, also applies safe column type/nullable changes (e.g. `VARCHAR` widening) on startup |
| `APPLY_RISKY_DATABASE_MIGRATION` | `false` | When `true`, also applies risky type casts and `NOT NULL` additions on startup (implies safe column changes too) |

---

## Startup Log Example

```
Schema sync: 1 table(s) created, 2 column(s) added, 3 index(es) created
```

When the schema is already in sync:

```
Database schema is up to date
```

---

## Risky Changes

Changes that could cause data loss are **never applied automatically** unless
`APPLY_RISKY_DATABASE_MIGRATION=true`. They appear in `sync.py` output as:

```
~ CHANGED   my_table.some_column   VARCHAR(100) -> VARCHAR(50)  [risky - use --force to apply]
```

To apply risky changes:
- Manually via CLI: `python scripts/database/sync.py --migrate --force`
- Via API: `POST /api/system/schema/migrate?force=true`
- At startup: set `APPLY_RISKY_DATABASE_MIGRATION=true` in `.env` (remove after the deployment)

---

## Production Checklist

Before deploying a model change:

1. Test on a staging database first (`sync.py` check mode)
2. Back up the production database
3. Review risky changes if any
4. Deploy — safe structural changes (tables/columns/indexes) apply automatically on startup
5. If column type/nullable changes are needed, set `APPLY_SAFE_DATABASE_MIGRATION=true` and/or
   `APPLY_RISKY_DATABASE_MIGRATION=true`, deploy, then unset it

---

## Key Components

### `AutoSchemaMigration` (`migrations/auto_schema.py`)
Core engine. Inspects the live database and compares it against `Base.metadata`. Exposes:
- `analyze(table_filter?)` → `SchemaDiff` — read-only diff, no DB changes
- `run()` → stats dict — applies safe structural changes (tables, columns, indexes)

### `SchemaManager` (`core/schema_manager.py`)
Wraps `AutoSchemaMigration` for use by the API endpoints and the sync script. Adds column
type/nullable change application (`perform_migration(force=True|False)`).

### `scripts/database/sync.py`
CLI for developers and operators. Check mode exits with code 1 if differences exist (useful in
CI).
