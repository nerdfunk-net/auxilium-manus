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

from sqlalchemy import text

from core.database import engine
from core.models import Base
from migrations.auto_schema import AutoSchemaMigration, SchemaDiff

logger = logging.getLogger(__name__)


def pg_cast(canonical_type: str) -> str:
    _map = {
        "TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ",
        "DOUBLE PRECISION": "DOUBLE PRECISION",
    }
    return _map.get(canonical_type, canonical_type)


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

    def _apply_column_diffs(self, diff: SchemaDiff, force: bool) -> dict[str, Any]:
        applied: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        for cd in sorted(diff.column_diffs, key=lambda d: (d.table, d.column)):
            if not cd.safe and not force:
                skipped.append(f"{cd.table}.{cd.column}")
                continue

            stmts = []
            if cd.type_changed:
                cast = pg_cast(cd.model_type)
                stmts.append(
                    f"ALTER COLUMN {cd.column} TYPE {cd.model_type} USING {cd.column}::{cast}"
                )
            if cd.nullable_changed:
                if cd.model_nullable:
                    stmts.append(f"ALTER COLUMN {cd.column} DROP NOT NULL")
                else:
                    stmts.append(f"ALTER COLUMN {cd.column} SET NOT NULL")

            for stmt in stmts:
                try:
                    with self._auto.engine.connect() as conn:
                        conn.execute(text(f"ALTER TABLE {cd.table} {stmt}"))
                        conn.commit()
                    change = (
                        f"{cd.db_type} -> {cd.model_type}"
                        if cd.type_changed
                        else "nullable changed"
                    )
                    applied.append(f"{cd.table}.{cd.column} ({change})")
                except Exception as e:
                    logger.error("Failed to alter %s.%s: %s", cd.table, cd.column, e)
                    errors.append(f"{cd.table}.{cd.column}: failed to apply")

        return {"applied": applied, "skipped": skipped, "errors": errors}

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

        col_results = self._apply_column_diffs(diff, force=force)
        all_errors = col_results["errors"]

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
            "column_changes_applied": col_results["applied"],
            "column_changes_skipped": col_results["skipped"],
            "errors": all_errors,
        }
