"""A missing unique index stops the start-up; a missing plain index is only a warning."""

from __future__ import annotations

import unittest

from sqlalchemy import Column, Index, Integer, String, create_engine, text
from sqlalchemy.orm import declarative_base

from migrations.auto_schema import AutoSchemaMigration, SchemaSyncError


def _base_with(*, unique: bool):
    base = declarative_base()

    class Item(base):  # type: ignore[valid-type, misc]
        __tablename__ = "items"
        id = Column(Integer, primary_key=True)
        name = Column(String(50), nullable=False)
        # A plain column: SQLite does not reflect expression indexes (PostgreSQL does).
        __table_args__ = (Index("ix_items_name", name, unique=unique),)

    return base


class UniqueIndexStartupTests(unittest.TestCase):
    def _engine_with_rows(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, name VARCHAR(50))"))
            conn.execute(text("INSERT INTO items (name) VALUES ('admin'), ('admin')"))
        return engine

    def test_duplicate_data_makes_startup_fail(self) -> None:
        engine = self._engine_with_rows()
        with self.assertRaises(SchemaSyncError) as ctx:
            AutoSchemaMigration(engine, _base_with(unique=True)).run()
        self.assertIn("ix_items_name", str(ctx.exception))

    def test_non_unique_index_failure_is_still_a_warning(self) -> None:
        engine = self._engine_with_rows()
        result = AutoSchemaMigration(engine, _base_with(unique=False)).run()
        self.assertEqual(result["indexes_created"], 1)

    def test_clean_data_creates_the_unique_index(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, name VARCHAR(50))"))
            conn.execute(text("INSERT INTO items (name) VALUES ('a'), ('b')"))
        result = AutoSchemaMigration(engine, _base_with(unique=True)).run()
        self.assertEqual(result["indexes_created"], 1)


if __name__ == "__main__":
    unittest.main()
