from __future__ import annotations

import re
from collections.abc import Generator

import psycopg
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from core.config import settings
from core.models import Base

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from migrations.runner import MigrationRunner

    ensure_database_exists()
    runner = MigrationRunner(engine=engine, base=Base)
    runner.run_migrations()

    if settings.environment == "development":
        Base.metadata.create_all(bind=engine)


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
