#!/usr/bin/env python3
"""
Database repair tool — the fallback for "the app won't start because of a
database/schema problem".

Usage (from backend/, with the project venv active):

    python scripts/repair_database.py migrate            # safe: sync schema + seed
    python scripts/repair_database.py migrate --force    # also apply risky column changes
    python scripts/repair_database.py reset              # DESTRUCTIVE: drop + rebuild everything
    python scripts/repair_database.py reset --yes        # skip the confirmation prompt

Both subcommands run against the database configured by backend/.env
(DATABASE_*) — exactly like the running app. There is no --env override;
point .env at whatever database you mean to repair before running this.

migrate
    Safe to run against a database that already has data. Creates the
    database if it doesn't exist (core.database.ensure_database_exists),
    then applies missing tables/columns/indexes and safe type widening
    (core.schema_manager.SchemaManager — the same engine the app's HTTP
    admin "sync schema" action uses), and seeds the initial admin user +
    RBAC catalog if missing, self-healing the admin role assignment exactly
    like main.py's lifespan does. Pass --force to also apply risky column
    changes (may truncate data, or add NOT NULL to a column that could
    hold NULLs) — equivalent to `scripts/database/sync.py --migrate --force`.

reset
    The last resort. Terminates other connections to the database, DROPs
    it entirely, then runs the same bootstrap as `migrate` against a
    brand-new database. Everything in the database is lost. Requires
    typing the database name to confirm, unless --yes is passed.

There is exactly one implementation of "how to build the schema"
(migrations/auto_schema.py's AutoSchemaMigration, wrapped by
core.schema_manager.SchemaManager) behind every entry point: the app
itself on startup, the HTTP admin endpoint (routers/system.py), the manual
CLI (scripts/database/sync.py), and this script — see doc/MIGRATION_SYSTEM.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add backend/ to Python path so imports resolve correctly.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import logging  # noqa: E402

# Suppress library noise; the script prints its own structured output.
logging.basicConfig(level=logging.WARNING)

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from core.config import settings  # noqa: E402
from core.database import DATABASE_NAME_PATTERN, engine, ensure_database_exists  # noqa: E402

_WIDTH = 64
# Same key core.database.init_db() locks on, so this script can't race a
# concurrently-booting app instance while it syncs the schema.
_SCHEMA_SYNC_LOCK_KEY = 911_020_902


def _banner(title: str) -> None:
    print("=" * _WIDTH)
    print(title)
    print(f"Database: {settings.database_name} @ {settings.database_host}:{settings.database_port}")
    print("=" * _WIDTH)


def _confirm_reset(*, skip_prompt: bool) -> None:
    if skip_prompt:
        return
    print()
    print("This will PERMANENTLY DELETE every table and row in this database.")
    typed = input(f"Type the database name ({settings.database_name!r}) to confirm: ")
    if typed != settings.database_name:
        print("Confirmation did not match — aborting. Nothing was changed.")
        raise SystemExit(1)


def _drop_database() -> None:
    """DROP DATABASE IF EXISTS, terminating other connections first.

    Uses psycopg's sql.Identifier for safe quoting (same approach as
    core.database.ensure_database_exists) rather than composing the name
    into a SQL string — settings.database_name is operator-controlled
    config, but there is no reason not to quote it properly.
    """
    if not DATABASE_NAME_PATTERN.fullmatch(settings.database_name):
        raise SystemExit(
            f"DATABASE_NAME {settings.database_name!r} contains unsupported characters"
        )

    maintenance_url = make_url(settings.maintenance_database_url)
    driver_name = maintenance_url.drivername.split("+", maxsplit=1)[0]
    psycopg_url = maintenance_url.set(drivername=driver_name).render_as_string(hide_password=False)

    with psycopg.connect(psycopg_url) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (settings.database_name,),
            )
            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(settings.database_name))
            )
    print(f"Dropped database {settings.database_name!r} (if it existed).")


def _seed_baseline() -> None:
    """Same admin + RBAC bootstrap as main.py's lifespan."""
    from core.database import SessionLocal
    from services.auth.auth_service import AuthService
    from services.auth.rbac_seed import seed_rbac
    from services.auth.rbac_service import RBACService

    with SessionLocal() as db:
        admin_user = AuthService(db).ensure_initial_admin()
        seed_rbac(db)
        rbac = RBACService(db)
        # Mirrors main.py: only (re-)grant the bootstrap admin role when
        # *nobody* holds it, so a deliberate demotion of INITIAL_USERNAME
        # survives a repair run as long as another admin remains.
        if not rbac.role_has_members("admin"):
            print(
                "No user holds the 'admin' role; granting it to initial user "
                f"{admin_user.username!r}"
            )
            rbac.assign_role_to_user_by_name(admin_user.id, "admin")
    print("Seeded initial admin user, RBAC catalog, and admin role assignment.")


def _print_migration_result(result: dict) -> None:
    print(f"  tables created:  {result['tables_created']}")
    print(f"  columns added:   {result['columns_added']}")
    print(f"  indexes created: {result['indexes_created']}")
    for c in result["column_changes_applied"]:
        print(f"  column changed:  {c}")
    for c in result["column_changes_skipped"]:
        print(f"  skipped (risky, rerun with --force): {c}")
    for e in result["errors"]:
        print(f"  ERROR: {e}")
    print(result["message"])


def _migrate(*, force: bool) -> bool:
    """Ensure the database exists and its schema is in sync, then seed it.

    Delegates all actual schema comparison/apply work to SchemaManager
    (core/schema_manager.py), which wraps AutoSchemaMigration
    (migrations/auto_schema.py) — the same code path core.database.init_db()
    and the HTTP `POST /system/schema/migrate` admin endpoint use.
    """
    print("Ensuring database exists...")
    ensure_database_exists()

    from core.schema_manager import SchemaManager

    print("Syncing schema" + (" (including risky changes, --force)" if force else "") + "...")
    with engine.begin() as lock_conn:
        lock_conn.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SCHEMA_SYNC_LOCK_KEY}
        )
        result = SchemaManager().perform_migration(force=force)
    _print_migration_result(result)

    _seed_baseline()
    return bool(result["success"])


def cmd_migrate(args: argparse.Namespace) -> int:
    _banner("Database Repair — migrate")
    success = _migrate(force=args.force)
    return 0 if success else 1


def cmd_reset(args: argparse.Namespace) -> int:
    _banner("Database Repair — reset (DESTRUCTIVE)")
    _confirm_reset(skip_prompt=args.yes)
    _drop_database()
    success = _migrate(force=False)
    return 0 if success else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate_parser = subparsers.add_parser(
        "migrate", help="Create/sync the database schema in place; safe on existing data."
    )
    migrate_parser.add_argument(
        "--force",
        action="store_true",
        help="Also apply risky column changes (may cause data loss).",
    )
    migrate_parser.set_defaults(func=cmd_migrate)

    reset_parser = subparsers.add_parser(
        "reset", help="DROP the database and rebuild it from scratch. Destroys all data."
    )
    reset_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt (for non-interactive use).",
    )
    reset_parser.set_defaults(func=cmd_reset)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
