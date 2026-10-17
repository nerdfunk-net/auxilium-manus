"""Tests for ReportDatasetRepository (the dataset catalog)."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from core.models.base import Base
from core.models.report_datasets import ReportDataset
from repositories.report_datasets_repository import ReportDatasetRepository


class ReportDatasetRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[ReportDataset.__table__])
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.repo = ReportDatasetRepository(self.db)

    def test_upsert_creates_an_entry(self) -> None:
        entry = self.repo.upsert(dataset="inventory", mode="device", field_names=["a", "b"])

        self.assertEqual(entry.dataset, "inventory")
        self.assertEqual(entry.mode, "device")
        self.assertEqual(entry.field_names, ["a", "b"])
        self.assertIsNotNone(entry.last_collected_at)

    def test_upsert_updates_in_place_and_newest_wins(self) -> None:
        first = self.repo.upsert(dataset="inv", mode="device", field_names=["a"])
        second = self.repo.upsert(dataset="inv", mode="items", field_names=["x", "y"])

        self.assertEqual(first.id, second.id)
        self.assertEqual(second.mode, "items")
        self.assertEqual(second.field_names, ["x", "y"])
        self.assertEqual(len(self.repo.list_all()), 1)

    def test_get_and_list(self) -> None:
        self.repo.upsert(dataset="b", mode="device", field_names=["f"])
        self.repo.upsert(dataset="a", mode="items", field_names=["g"])

        self.assertEqual([d.dataset for d in self.repo.list_all()], ["a", "b"])
        found = self.repo.get("a")
        self.assertIsNotNone(found)
        self.assertEqual(found.mode, "items")  # type: ignore[union-attr]
        self.assertIsNone(self.repo.get("missing"))

    def test_lost_insert_race_is_retried_as_update(self) -> None:
        existing = ReportDataset(dataset="inv", mode="device", field_names=["a"])
        self.db.add(existing)
        self.db.commit()

        original_get = self.repo.get
        calls = {"n": 0}

        def fake_get(dataset: str):
            calls["n"] += 1
            return None if calls["n"] == 1 else original_get(dataset)

        self.repo.get = fake_get  # type: ignore[method-assign]
        entry = self.repo.upsert(dataset="inv", mode="items", field_names=["z"])

        self.assertEqual(entry.id, existing.id)
        self.assertEqual(entry.field_names, ["z"])
        self.assertEqual(len(self.repo.list_all()), 1)

    def test_dataset_is_unique(self) -> None:
        self.db.add(ReportDataset(dataset="inv", mode="device", field_names=[]))
        self.db.commit()
        self.db.add(ReportDataset(dataset="inv", mode="device", field_names=[]))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()
