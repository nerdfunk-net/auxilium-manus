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
from core.schema_manager import pg_cast  # noqa: E402
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


def _migrate(
    diff: SchemaDiff,
    auto: AutoSchemaMigration,
    force: bool,
    drop: bool = False,
    drop_columns: bool = False,
) -> None:
    tables_created = columns_added = types_changed = indexes_created = skipped = 0
    tables_dropped = columns_dropped = 0

    if drop:
        for table_name in diff.extra_tables:
            try:
                with auto.engine.connect() as conn:
                    conn.execute(text(f"DROP TABLE {table_name}"))
                    conn.commit()
                print(f"  Dropped table: {table_name}")
                tables_dropped += 1
            except Exception as e:
                print(f"  Failed to drop table {table_name}: {e}")

    if drop_columns:
        for table_name, col_name in diff.extra_columns:
            try:
                with auto.engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE {table_name} DROP COLUMN {col_name}"))
                    conn.commit()
                print(f"  Dropped column: {table_name}.{col_name}")
                columns_dropped += 1
            except Exception as e:
                print(f"  Failed to drop column {table_name}.{col_name}: {e}")

    for table_name in diff.missing_tables:
        try:
            table = auto.base.metadata.tables[table_name]
            table.create(bind=auto.engine)
            print(f"  Created table: {table_name}")
            tables_created += 1
        except Exception as e:
            print(f"  Failed to create table {table_name}: {e}")

    # Re-inspect so subsequent steps see newly created tables.
    if diff.missing_tables:
        auto.inspector = sa_inspect(auto.engine)

    for table_name, col_name in diff.missing_columns:
        try:
            table = auto.base.metadata.tables[table_name]
            column = next(c for c in table.columns if c.name == col_name)
            col_def = auto.get_column_definition(column)
            with auto.engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}"))
                conn.commit()
            print(f"  Added column: {table_name}.{col_name}")
            columns_added += 1
        except Exception as e:
            print(f"  Failed to add column {table_name}.{col_name}: {e}")

    for cd in diff.column_diffs:
        if not cd.safe and not force:
            risky_desc = (
                f"{cd.db_type} -> {cd.model_type}" if cd.type_changed else "NULL -> NOT NULL"
            )
            print(
                f"  Skipped risky change: {cd.table}.{cd.column} "
                f"({risky_desc}) — rerun with --force"
            )
            skipped += 1
            continue
        try:
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
                with auto.engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE {cd.table} {stmt}"))
                    conn.commit()
            change = f"{cd.db_type} -> {cd.model_type}" if cd.type_changed else "nullable changed"
            print(f"  Changed: {cd.table}.{cd.column} ({change})")
            types_changed += 1
        except Exception as e:
            print(f"  Failed to change {cd.table}.{cd.column}: {e}")

    for table_name, idx_name in diff.missing_indexes:
        try:
            table = auto.base.metadata.tables.get(table_name)
            if not table:
                continue
            index = next((i for i in table.indexes if i.name == idx_name), None)
            if index:
                index.create(bind=auto.engine)
                print(f"  Created index: {idx_name}")
                indexes_created += 1
        except Exception as e:
            print(f"  Failed to create index {idx_name}: {e}")

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
