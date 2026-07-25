from __future__ import annotations

import logging
import re
from collections.abc import Generator
from typing import Any

import psycopg
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from core.config import settings
from core.models import Base

logger = logging.getLogger(__name__)

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def get_db_session() -> Session:
    return SessionLocal()


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


def _log_column_migration_result(result: dict[str, Any]) -> None:
    for change in result.get("column_changes_applied", []):
        logger.info("Column change applied: %s", change)
    skipped = result.get("column_changes_skipped", [])
    if skipped:
        logger.warning(
            "Risky column changes skipped (set APPLY_RISKY_DATABASE_MIGRATION=true to apply): %s",
            skipped,
        )
    for err in result.get("errors", []):
        logger.error("Column migration error: %s", err)


def ensure_database_exists() -> None:
    if not DATABASE_NAME_PATTERN.fullmatch(settings.database_name):
        raise ValueError("DATABASE_NAME contains unsupported characters")

    maintenance_url = make_url(settings.maintenance_database_url)
    driver_name = maintenance_url.drivername.split("+", maxsplit=1)[0]
    psycopg_url = maintenance_url.set(drivername=driver_name).render_as_string(
        hide_password=False,
    )

    with psycopg.connect(psycopg_url) as connection:
        connection.autocommit = True

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (settings.database_name,),
            )
            database_exists = cursor.fetchone() is not None

            if not database_exists:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(settings.database_name),
                    ),
                )
