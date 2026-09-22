"""Tests for DeviceDataRecordRepository.upsert."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.base import Base
from core.models.device_data_records import DeviceDataRecord
from repositories.device_data_records_repository import DeviceDataRecordRepository


class DeviceDataRecordRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[DeviceDataRecord.__table__])
        self.addCleanup(engine.dispose)
        Session = sessionmaker(bind=engine)
        self.db = Session()
        self.addCleanup(self.db.close)
        self.repo = DeviceDataRecordRepository(self.db)

    def test_insert_creates_row(self) -> None:
        record = self.repo.upsert(device_name="lab", storage_key="backup", data={"a": 1})
        self.assertIsNotNone(record.id)
        self.assertEqual(record.device_name, "lab")
        self.assertEqual(record.storage_key, "backup")
        self.assertEqual(record.data, {"a": 1})

    def test_upsert_same_key_updates_in_place(self) -> None:
        first = self.repo.upsert(device_name="lab", storage_key="backup", data={"a": 1})
        second = self.repo.upsert(device_name="lab", storage_key="backup", data={"a": 2})

        self.assertEqual(first.id, second.id)
        self.assertEqual(second.data, {"a": 2})
        rows = self.db.query(DeviceDataRecord).all()
        self.assertEqual(len(rows), 1)

    def test_different_storage_key_creates_separate_row(self) -> None:
        self.repo.upsert(device_name="lab", storage_key="backup", data={"a": 1})
        self.repo.upsert(device_name="lab", storage_key="site_id", data="dc1")

        rows = self.db.query(DeviceDataRecord).all()
        self.assertEqual(len(rows), 2)

    def test_different_device_same_key_creates_separate_row(self) -> None:
        self.repo.upsert(device_name="lab1", storage_key="backup", data={"a": 1})
        self.repo.upsert(device_name="lab2", storage_key="backup", data={"a": 2})

        rows = self.db.query(DeviceDataRecord).all()
        self.assertEqual(len(rows), 2)

    def test_integrity_error_race_retries_as_update(self) -> None:
        # Simulate a concurrent writer that inserted the row between our SELECT
        # and INSERT by pre-creating it directly, then calling upsert again.
        existing = DeviceDataRecord(device_name="lab", storage_key="backup", data={"a": 1})
        self.db.add(existing)
        self.db.commit()

        original_get = self.repo._get
        calls = {"n": 0}

        def fake_get(device_name: str, storage_key: str):
            calls["n"] += 1
            # First lookup (before insert attempt) pretends nothing exists yet,
            # forcing the insert path to hit the unique constraint.
            if calls["n"] == 1:
                return None
            return original_get(device_name, storage_key)

        self.repo._get = fake_get  # type: ignore[method-assign]
        record = self.repo.upsert(device_name="lab", storage_key="backup", data={"a": 2})

        self.assertEqual(record.id, existing.id)
        self.assertEqual(record.data, {"a": 2})
        rows = self.db.query(DeviceDataRecord).all()
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
