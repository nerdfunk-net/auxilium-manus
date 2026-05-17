from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.orm import DeclarativeBase

from migrations.base import BaseMigration

MIGRATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id SERIAL PRIMARY KEY,
    migration_name VARCHAR(255) UNIQUE NOT NULL,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    description TEXT,
    execution_time_ms INTEGER
)
"""
MIGRATION_ADVISORY_LOCK_ID = 2026051601


class MigrationRunner:
    def __init__(self, engine: Engine, base: type[DeclarativeBase]) -> None:
        self.engine = engine
        self.base = base
        self.versions_dir = Path(__file__).resolve().parent / "versions"

    def run_migrations(self) -> list[dict[str, Any]]:
        self._ensure_migrations_table()
        applied_results: list[dict[str, Any]] = []

        with self.engine.connect() as lock_connection:
            lock_connection.execute(
                text("SELECT pg_advisory_lock(:lock_id)"),
                {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
            )

            try:
                for migration_file in self._discover_migration_files():
                    migration = self._load_migration(migration_file)

                    if self._is_migration_applied(migration.name):
                        continue

                    started_at = time.perf_counter()
                    result = migration.upgrade()
                    execution_time_ms = int((time.perf_counter() - started_at) * 1000)
                    self._record_migration(
                        migration_name=migration.name,
                        description=migration.description,
                        execution_time_ms=execution_time_ms,
                    )
                    applied_results.append(
                        {
                            "name": migration.name,
                            "description": migration.description,
                            "execution_time_ms": execution_time_ms,
                            **result,
                        },
                    )
            finally:
                lock_connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
                )

        return applied_results

    def _ensure_migrations_table(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(MIGRATIONS_TABLE_SQL))

    def _discover_migration_files(self) -> list[Path]:
        return sorted(self.versions_dir.glob("[0-9][0-9][0-9]_*.py"))

    def _load_migration(self, migration_file: Path) -> BaseMigration:
        module_name = f"migrations.versions.{migration_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, migration_file)

        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load migration: {migration_file.name}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "Migration"):
            raise RuntimeError(f"Migration class missing in {migration_file.name}")

        migration_class = module.Migration

        if not isinstance(migration_class, type) or not issubclass(
            migration_class,
            BaseMigration,
        ):
            raise RuntimeError(f"Migration class invalid in {migration_file.name}")

        return migration_class(engine=self.engine, base=self.base)

    def _is_migration_applied(self, migration_name: str) -> bool:
        with self.engine.connect() as connection:
            result = connection.execute(
                text(
                    "SELECT 1 FROM schema_migrations "
                    "WHERE migration_name = :migration_name LIMIT 1",
                ),
                {"migration_name": migration_name},
            )

            return result.scalar_one_or_none() is not None

    def _record_migration(
        self,
        migration_name: str,
        description: str,
        execution_time_ms: int,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO schema_migrations "
                    "(migration_name, description, execution_time_ms) "
                    "VALUES (:migration_name, :description, :execution_time_ms)",
                ),
                {
                    "migration_name": migration_name,
                    "description": description,
                    "execution_time_ms": execution_time_ms,
                },
            )
