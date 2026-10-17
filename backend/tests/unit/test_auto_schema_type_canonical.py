"""Model column types are compared with the database in their PostgreSQL form."""

from __future__ import annotations

import unittest

from sqlalchemy import JSON, Integer, String, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

from migrations.auto_schema import AutoSchemaMigration


class CanonicalTypeTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        self.migration = AutoSchemaMigration(engine, declarative_base())

    def test_json_with_postgresql_jsonb_variant_is_jsonb(self) -> None:
        column_type = JSON().with_variant(JSONB(), "postgresql")
        self.assertEqual(self.migration._type_to_canonical(column_type), "JSONB")

    def test_plain_json_stays_json(self) -> None:
        self.assertEqual(self.migration._type_to_canonical(JSON()), "JSON")

    def test_variant_of_a_scalar_type_keeps_its_canonical_form(self) -> None:
        column_type = String(20).with_variant(String(40), "postgresql")
        self.assertEqual(self.migration._type_to_canonical(column_type), "VARCHAR(40)")
        self.assertEqual(self.migration._type_to_canonical(Integer()), "INTEGER")
