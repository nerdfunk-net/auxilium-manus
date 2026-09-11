#!/usr/bin/env python3
"""
Database schema synchronization tool.

Compares SQLAlchemy model definitions against the live PostgreSQL database,
reports all differences, and optionally applies safe changes.

Usage (from backend/):
    python scripts/database/sync.py                    # check mode
    python scripts/database/sync.py --migrate          # apply safe changes
    python scripts/database/sync.py --migrate --force  # also apply risky type changes
    python scripts/database/sync.py --table users      # focus on one table
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add backend/ to Python path so imports resolve correctly.
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import logging  # noqa: E402

# Suppress library noise; the script prints its own structured output.
logging.basicConfig(level=logging.WARNING)

from sqlalchemy import inspect as sa_inspect  # noqa: E402
from sqlalchemy import text  # noqa: E402

from core.database import engine  # noqa: E402
from core.models import Base  # noqa: E402
from migrations.auto_schema import AutoSchemaMigration, SchemaDiff  # noqa: E402

_WIDTH = 64


def _report(diff: SchemaDiff, table_filter: str | None = None) -> None:
    print("=" * _WIDTH)
    print("Database Schema Analysis")
    if table_filter:
        print(f"Table filter: {table_filter}")
    print("=" * _WIDTH)
    print()

    has_output = False

    if diff.missing_tables or diff.extra_tables:
        has_output = True
        print("Tables")
        for t in diff.missing_tables:
            print(f"  x MISSING   {t}")
        for t in diff.extra_tables:
            print(f"  ! EXTRA     {t}  [use --migrate --drop to remove]")
        print()

    if diff.missing_columns or diff.extra_columns or diff.column_diffs:
        has_output = True
        print("Columns")
        for table, col in diff.missing_columns:
            print(f"  x MISSING   {table}.{col}")
        for cd in sorted(diff.column_diffs, key=lambda d: (d.table, d.column)):
            parts = []
            if cd.type_changed:
                parts.append(f"{cd.db_type} -> {cd.model_type}")
            if cd.nullable_changed:
                db_null = "NULL" if cd.db_nullable else "NOT NULL"
                model_null = "NULL" if cd.model_nullable else "NOT NULL"
                parts.append(f"{db_null} -> {model_null}")
            change_str = ", ".join(parts)
            safety = "[safe]" if cd.safe else "[risky - use --force to apply]"
            print(f"  ~ CHANGED   {cd.table}.{cd.column}   {change_str}  {safety}")
        for table, col in diff.extra_columns:
            print(f"  ! EXTRA     {table}.{col}  [use --migrate --drop-columns to remove]")
        print()

    if diff.missing_indexes or diff.extra_indexes:
        has_output = True
        print("Indexes")
        for table, idx in diff.missing_indexes:
            print(f"  x MISSING   {idx}  (on {table})")
        for table, idx in diff.extra_indexes:
            print(f"  ! EXTRA     {idx}  (on {table})  [not dropped]")
        print()

    if not has_output:
        print("  OK - No differences found - schema is in sync.")
        print()

    print("=" * _WIDTH)
    parts = []
    if diff.missing_tables:
        parts.append(f"{len(diff.missing_tables)} missing table(s)")
    if diff.missing_columns:
        parts.append(f"{len(diff.missing_columns)} missing column(s)")
    if diff.column_diffs:
        safe_n = sum(1 for d in diff.column_diffs if d.safe)
        risky_n = len(diff.column_diffs) - safe_n
        if safe_n and risky_n:
            parts.append(
                f"{len(diff.column_diffs)} type change(s) ({safe_n} safe, {risky_n} risky)"
            )
        elif safe_n:
            parts.append(f"{safe_n} safe type change(s)")
        else:
            parts.append(f"{risky_n} risky type change(s)")
    if diff.missing_indexes:
        parts.append(f"{len(diff.missing_indexes)} missing index(es)")

    if parts:
        print("Summary: " + ", ".join(parts))
        if "--migrate" not in sys.argv:
            print("Run with --migrate to apply safe changes.")
    else:
        print("Summary: Schema is in sync.")
    print("=" * _WIDTH)


def _drop_extra_tables(diff: SchemaDiff, auto: AutoSchemaMigration) -> int:
    tables_dropped = 0
    for table_name in diff.extra_tables:
        try:
            with auto.engine.connect() as conn:
                conn.execute(text(f"DROP TABLE {table_name}"))
                conn.commit()
            print(f"  Dropped table: {table_name}")
            tables_dropped += 1
        except Exception as e:
            print(f"  Failed to drop table {table_name}: {e}")
    return tables_dropped


def _drop_extra_columns(diff: SchemaDiff, auto: AutoSchemaMigration) -> int:
    columns_dropped = 0
    for table_name, col_name in diff.extra_columns:
        try:
            with auto.engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE {table_name} DROP COLUMN {col_name}"))
                conn.commit()
            print(f"  Dropped column: {table_name}.{col_name}")
            columns_dropped += 1
        except Exception as e:
            print(f"  Failed to drop column {table_name}.{col_name}: {e}")
    return columns_dropped


# The four functions below are thin CLI reporting wrappers. The actual
# apply logic (FK-dependency ordering + deferred-constraint handling for
# tables, ALTER TABLE for columns/indexes/type changes) lives in exactly
# one place — AutoSchemaMigration, in migrations/auto_schema.py — so this
# CLI, the automatic startup sync, and SchemaManager (the HTTP-facing
# admin "sync schema" action) can't drift out of sync with each other.


def _create_missing_tables(diff: SchemaDiff, auto: AutoSchemaMigration) -> int:
    result = auto.create_tables(diff.missing_tables)
    for name in result.created:
        print(f"  Created table: {name}")
    for name, err in result.failed:
        print(f"  Failed to create table {name}: {err}")
    for name in result.constraints_added:
        print(f"  Added deferred foreign key constraint: {name}")
    for name, err in result.constraints_failed:
        print(f"  Failed to add deferred foreign key constraint {name}: {err}")
    return len(result.created)


def _add_missing_columns(diff: SchemaDiff, auto: AutoSchemaMigration) -> int:
    result = auto.add_columns(diff.missing_columns)
    for label in result.succeeded:
        print(f"  Added column: {label}")
    for label, err in result.failed:
        print(f"  Failed to add column {label}: {err}")
    return len(result.succeeded)


def _apply_column_diffs(
    diff: SchemaDiff, auto: AutoSchemaMigration, *, force: bool
) -> tuple[int, int]:
    result = auto.apply_column_diffs(diff, force=force)
    for label in result.skipped:
        print(f"  Skipped risky change: {label} — rerun with --force")
    for label in result.succeeded:
        print(f"  Changed: {label}")
    for label, err in result.failed:
        print(f"  Failed to change {label}: {err}")
    return len(result.succeeded), len(result.skipped)


def _create_missing_indexes(diff: SchemaDiff, auto: AutoSchemaMigration) -> int:
    result = auto.create_indexes(diff.missing_indexes)
    for name in result.succeeded:
        print(f"  Created index: {name}")
    for name, err in result.failed:
        print(f"  Failed to create index {name}: {err}")
    return len(result.succeeded)


def _print_migrate_summary(
    *,
    tables_dropped: int,
    columns_dropped: int,
    tables_created: int,
    columns_added: int,
    types_changed: int,
    indexes_created: int,
    skipped: int,
) -> None:
    print()
    print("=" * _WIDTH)
    applied = []
    if tables_dropped:
        applied.append(f"{tables_dropped} table(s) dropped")
    if columns_dropped:
        applied.append(f"{columns_dropped} column(s) dropped")
    if tables_created:
        applied.append(f"{tables_created} table(s) created")
    if columns_added:
        applied.append(f"{columns_added} column(s) added")
    if types_changed:
        applied.append(f"{types_changed} change(s) applied")
    if indexes_created:
        applied.append(f"{indexes_created} index(es) created")
    if skipped:
        applied.append(f"{skipped} risky change(s) skipped")
    print("Summary: " + (", ".join(applied) if applied else "No changes applied."))
    print("=" * _WIDTH)


def _migrate(
    diff: SchemaDiff,
    auto: AutoSchemaMigration,
    force: bool,
    drop: bool = False,
    drop_columns: bool = False,
) -> None:
    tables_dropped = columns_dropped = 0
    if drop:
        tables_dropped = _drop_extra_tables(diff, auto)
    if drop_columns:
        columns_dropped = _drop_extra_columns(diff, auto)

    tables_created = _create_missing_tables(diff, auto)
    if diff.missing_tables:
        auto.inspector = sa_inspect(auto.engine)

    columns_added = _add_missing_columns(diff, auto)
    types_changed, skipped = _apply_column_diffs(diff, auto, force=force)
    indexes_created = _create_missing_indexes(diff, auto)

    _print_migrate_summary(
        tables_dropped=tables_dropped,
        columns_dropped=columns_dropped,
        tables_created=tables_created,
        columns_added=columns_added,
        types_changed=types_changed,
        indexes_created=indexes_created,
        skipped=skipped,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check and sync the database schema against SQLAlchemy models.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Apply safe schema changes (add missing tables, columns, indexes; safe type changes).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="With --migrate: also apply risky type changes (may cause data loss).",
    )
    parser.add_argument(
        "--drop",
        action="store_true",
        help="With --migrate: drop tables that exist in the database but not in any model.",
    )
    parser.add_argument(
        "--drop-columns",
        action="store_true",
        dest="drop_columns",
        help="With --migrate: drop columns that exist in the database but not in any model.",
    )
    parser.add_argument(
        "--table",
        metavar="TABLE",
        help="Focus analysis on a specific table name.",
    )
    args = parser.parse_args()

    if args.force and not args.migrate:
        parser.error("--force requires --migrate")
    if args.drop and not args.migrate:
        parser.error("--drop requires --migrate")
    if args.drop_columns and not args.migrate:
        parser.error("--drop-columns requires --migrate")

    # Import all models so they register with Base.metadata.
    from core import models  # noqa: F401

    auto = AutoSchemaMigration(engine, Base)
    diff = auto.analyze(table_filter=args.table)

    _report(diff, table_filter=args.table)

    if args.migrate:
        print()
        print("Applying changes...")
        print()
        _migrate(diff, auto, force=args.force, drop=args.drop, drop_columns=args.drop_columns)

    # Non-zero exit when check mode finds actionable differences.
    if not args.migrate and diff.has_differences:
        sys.exit(1)


if __name__ == "__main__":
    main()
