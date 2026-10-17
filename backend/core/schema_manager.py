"""
Database Schema Manager
Uses AutoSchemaMigration to compare SQLAlchemy models with the live database
and apply schema changes on demand.

Safe changes (create missing tables/columns/indexes, safe type widening) can
be applied directly.  Risky changes (type casts that may truncate data, adding
NOT NULL to a column that may have NULL values) require force=True and are
never applied automatically on startup.
"""

import logging
from typing import Any

from core.database import engine
from core.models import Base
from migrations.auto_schema import AutoSchemaMigration

logger = logging.getLogger(__name__)


class SchemaManager:
    def __init__(self):
        from core import models  # noqa: F401 — registers all models with Base.metadata

        self._auto = AutoSchemaMigration(engine, Base)

    def get_schema_status(self) -> dict[str, Any]:
        diff = self._auto.analyze()
        return {
            "is_up_to_date": not diff.has_differences,
            "missing_tables": diff.missing_tables,
            "extra_tables": diff.extra_tables,
            "missing_columns": [{"table": t, "column": c} for t, c in diff.missing_columns],
            "extra_columns": [{"table": t, "column": c} for t, c in diff.extra_columns],
            "column_diffs": [
                {
                    "table": cd.table,
                    "column": cd.column,
                    "db_type": cd.db_type,
                    "model_type": cd.model_type,
                    "type_changed": cd.type_changed,
                    "nullable_changed": cd.nullable_changed,
                    "db_nullable": cd.db_nullable,
                    "model_nullable": cd.model_nullable,
                    "safe": cd.safe,
                }
                for cd in diff.column_diffs
            ],
            "missing_indexes": [{"table": t, "index": i} for t, i in diff.missing_indexes],
            "extra_indexes": [{"table": t, "index": i} for t, i in diff.extra_indexes],
        }

    def perform_migration(self, force: bool = False) -> dict[str, Any]:
        """
        Apply schema changes.

        Always applies:
          - Missing tables (CREATE TABLE)
          - Missing columns (ALTER TABLE ADD COLUMN)
          - Missing indexes
          - Safe type widening (VARCHAR->TEXT, VARCHAR(n)->VARCHAR(m) where m>n, etc.)

        Only when force=True:
          - Risky type casts (may truncate / coerce data)
          - Adding NOT NULL to a column that may contain NULL values
        """
        diff = self._auto.analyze()

        try:
            safe_results = self._auto.run()
        except Exception as e:
            logger.error("Safe schema migration failed: %s", e)
            return {
                "success": False,
                "message": "Migration failed — check backend logs.",
                "tables_created": 0,
                "columns_added": 0,
                "indexes_created": 0,
                "column_changes_applied": [],
                "column_changes_skipped": [],
                "errors": ["Structural migration failed — check backend logs."],
            }

        col_result = self._auto.apply_column_diffs(diff, force=force)
        all_errors = [f"{label}: {msg}" for label, msg in col_result.failed]

        return {
            "success": len(all_errors) == 0,
            "message": (
                "Schema synchronized successfully."
                if not all_errors
                else f"Completed with {len(all_errors)} error(s) — check backend logs."
            ),
            "tables_created": safe_results.get("tables_created", 0),
            "columns_added": safe_results.get("columns_added", 0),
            "indexes_created": safe_results.get("indexes_created", 0),
            "column_changes_applied": col_result.succeeded,
            "column_changes_skipped": col_result.skipped,
            "errors": all_errors,
        }
