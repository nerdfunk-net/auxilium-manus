# Migration System - Complete Overview

## ✅ What Was Implemented

### 1. **Versioned Migration System**

A complete migration framework with:
- ✅ Numbered migration files (`001_`, `002_`, etc.)
- ✅ Automatic discovery and execution
- ✅ Migration tracking in database
- ✅ Execution time logging
- ✅ Idempotent (safe to run multiple times)

### 2. **File Structure**

```
backend/
├── migrations/
│   ├── __init__.py                 # Package exports
│   ├── base.py                     # BaseMigration class
│   ├── runner.py                   # Migration runner
│   ├── auto_schema.py              # Auto schema detection
│   ├── versions/                   # Migration files
│   │   ├── __init__.py
│   │   └── 001_audit_log.py        # First migration
│   ├── README.md                   # Complete guide
│   ├── MIGRATION_SYSTEM.md         # This file
│   └── AUDIT_LOG_USAGE.md          # Audit log usage
│
├── core/
│   ├── database.py                 # ✅ Cleaned up (old migrations removed)
│   └── models.py                   # ✅ AuditLog table added
│
└── start.py                        # Runs migrations on startup
```

### 3. **Database Changes**

#### `audit_logs` table (created by migration `001_audit_log.py`):
```sql
CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL,
    user_id INTEGER REFERENCES users(id),
    event_type VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    ip_address VARCHAR(45),
    resource_type VARCHAR(100),
    resource_id VARCHAR(255),
    resource_name VARCHAR(255),
    severity VARCHAR(20) DEFAULT 'info',
    extra_data TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

**Indexes:**
- `idx_audit_logs_event_type_created_at` (event_type, created_at)
- `idx_audit_logs_username_created_at` (username, created_at)
- `idx_audit_logs_resource` (resource_type, resource_id)
- `idx_audit_logs_severity` (severity)

#### `schema_migrations` table (tracking):
```sql
CREATE TABLE schema_migrations (
    id SERIAL PRIMARY KEY,
    migration_name VARCHAR(255) UNIQUE NOT NULL,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    description TEXT,
    execution_time_ms INTEGER
);
```

## 🚀 How It Works

### On Application Startup:

1. **Initialize Database** (`core/database.py::init_db()`)
   ```python
   from migrations.runner import MigrationRunner
   runner = MigrationRunner(engine, Base)
   runner.run_migrations()
   ```

2. **Migration Runner** (`migrations/runner.py`)
   - Creates `schema_migrations` tracking table if needed
   - Scans `migrations/versions/` for files matching `NNN_*.py`
   - Sorts by numeric prefix
   - Loads each migration class
   - Checks if already applied
   - Executes pending migrations in order
   - Records each in `schema_migrations`

3. **Migration Execution** (`migrations/versions/001_audit_log.py`)
   - Uses `AutoSchemaMigration` to detect schema changes
   - Creates missing tables from `core/models.py`
   - Adds missing columns to existing tables
   - Creates missing indexes
   - Returns statistics

### Example Startup Log:

```
============================================================
Starting database migration process
============================================================
Creating schema_migrations tracking table
✓ schema_migrations table created
Discovered 1 migration file(s)
▶ 001_audit_log: Add audit_logs table for tracking user activities and system events
[001_audit_log] Creating audit_logs table...
[001_audit_log] Creating missing table: audit_logs
[001_audit_log] ✓ Created table: audit_logs
[001_audit_log] Creating index idx_audit_logs_event_type_created_at on audit_logs
[001_audit_log] ✓ Created index: idx_audit_logs_event_type_created_at
[001_audit_log] Creating index idx_audit_logs_username_created_at on audit_logs
[001_audit_log] ✓ Created index: idx_audit_logs_username_created_at
[001_audit_log] Creating index idx_audit_logs_resource on audit_logs
[001_audit_log] ✓ Created index: idx_audit_logs_resource
[001_audit_log] Creating index idx_audit_logs_severity on audit_logs
[001_audit_log] ✓ Created index: idx_audit_logs_severity
✓ 001_audit_log: Completed in 67ms (tables: 1, columns: 0, indexes: 5)
============================================================
Migration summary: 1 migration(s) applied, 1 table(s) created, 0 column(s) added, 5 index(es) created
============================================================
Database initialized successfully (46 tables)
```

## 📝 Creating New Migrations

### Quick Guide:

1. **Create numbered file:**
   ```bash
   touch migrations/versions/002_my_feature.py
   ```

2. **Write migration class:**
   ```python
   from migrations.base import BaseMigration
   from migrations.auto_schema import AutoSchemaMigration

   class Migration(BaseMigration):
       @property
       def name(self) -> str:
           return "002_my_feature"

       @property
       def description(self) -> str:
           return "Add my_feature table"

       def upgrade(self) -> dict:
           auto = AutoSchemaMigration(self.engine, self.base)
           return auto.run()
   ```

3. **Add model to `core/models.py`:**
   ```python
   class MyFeature(Base):
       __tablename__ = "my_feature"
       id = Column(Integer, primary_key=True)
       name = Column(String(255), nullable=False)
   ```

4. **Restart app** - Migration runs automatically!

## 🔧 Key Components

### `BaseMigration` (base.py)
Abstract base class all migrations inherit from.

**Required properties:**
- `name` - Unique migration identifier
- `description` - Human-readable description

**Required method:**
- `upgrade()` - Apply the migration, return stats dict

**Helper methods:**
- `log_info()`, `log_debug()`, `log_warning()`, `log_error()`

### `AutoSchemaMigration` (auto_schema.py)
Compares SQLAlchemy models with database schema.

**Detects and creates:**
- Missing tables
- Missing columns
- Missing indexes

**Usage:**
```python
auto = AutoSchemaMigration(engine, base)
results = auto.run()
# Returns: {"tables_created": 1, "columns_added": 0, "indexes_created": 5}
```

### `MigrationRunner` (runner.py)
Orchestrates migration discovery and execution.

**Key methods:**
- `discover_migrations()` - Find `NNN_*.py` files
- `load_migration(filename)` - Import and instantiate
- `is_migration_applied(name)` - Check tracking table
- `record_migration(name, ...)` - Record in database
- `run_migrations()` - Execute all pending

## 📊 Checking Migration Status

### View Applied Migrations:

```sql
SELECT migration_name, applied_at, execution_time_ms, description
FROM schema_migrations
ORDER BY migration_name;
```

Example output:
```
 migration_name  |         applied_at         | execution_time_ms |              description
-----------------+----------------------------+-------------------+----------------------------------------
 001_audit_log   | 2026-01-31 10:30:45+00     |                67 | Add audit_logs table for tracking...
```

### Check What Will Run:

```bash
# List files in versions/ directory
ls -1 backend/migrations/versions/
```

Output:
```
__init__.py
001_audit_log.py
002_next_migration.py  # Will run on next startup
```

## ⚠️ Important Notes

### DO:
- ✅ **Use sequential numbers** - 001, 002, 003...
- ✅ **Keep migrations small** - One logical change per migration
- ✅ **Test on dev first** - Before deploying to production
- ✅ **Commit migrations** - They're code, track them in git

### DON'T:
- ❌ **Skip numbers** - Always use next sequential number
- ❌ **Modify applied migrations** - Create new one instead
- ❌ **Delete applied migrations** - They're in production DBs
- ❌ **Reuse numbers** - Each number is unique forever

## 🔍 Troubleshooting

### Migration won't run?

Check:
1. File name matches pattern `NNN_*.py`
2. File is in `migrations/versions/` directory
3. Class is named `Migration` (exact case)
4. Migration not already in `schema_migrations` table

### Need to re-run a migration?

```sql
-- Remove from tracking (be careful!)
DELETE FROM schema_migrations WHERE migration_name = '002_my_migration';

-- Then restart app
```

### Migration fails?

1. Check error message in startup logs
2. Fix the issue
3. Remove from `schema_migrations` if partially applied
4. Restart app to retry

## 📚 Documentation

- **`README.md`** - Complete migration guide with examples
- **`AUDIT_LOG_USAGE.md`** - How to use audit logging
- **`MIGRATION_SYSTEM.md`** - This overview document

## 🎯 Next Steps

To use the new audit logging:

1. **Create repository** (`backend/repositories/audit_log_repository.py`)
2. **Create utilities** (`backend/utils/audit_logger.py`)
3. **Add logging to routes** (authentication, device operations, etc.)
4. **Create API endpoints** to query logs
5. **Build frontend UI** to display logs

See `AUDIT_LOG_USAGE.md` for detailed implementation examples.

## 🔐 Security Considerations

The audit log tracks:
- ✅ Who performed actions (username/user_id)
- ✅ What was done (event_type/message)
- ✅ When it happened (created_at)
- ✅ Where from (ip_address)
- ✅ What was affected (resource_type/id/name)
- ✅ Severity level (info/warning/error/critical)

This provides:
- Compliance audit trail
- Security incident investigation
- User activity monitoring
- Troubleshooting assistance

## 🚀 Production Deployment

### Before deploying:

1. **Test migrations on staging** database first
2. **Backup production database** before deploying
3. **Review migration code** for correctness
4. **Check for conflicts** with other developers' migrations
5. **Plan for rollback** if needed

### During deployment:

1. Application starts
2. Migrations run automatically
3. Check logs for success
4. Verify `schema_migrations` table updated
5. Test application functionality

### If migration fails:

1. Application won't start fully
2. Check error logs
3. Fix issue and redeploy
4. Or rollback deployment and investigate

## 📈 Advantages Over Old System

**Old system:**
- ❌ Manual migration functions in `database.py`
- ❌ Had to edit `init_db()` for each migration
- ❌ No clear order or tracking
- ❌ Hard to see what migrations exist
- ❌ No execution time tracking

**New system:**
- ✅ Numbered migration files
- ✅ Automatic discovery
- ✅ Database tracking
- ✅ Easy to see all migrations (just `ls versions/`)
- ✅ Execution time logged
- ✅ Professional, maintainable structure
