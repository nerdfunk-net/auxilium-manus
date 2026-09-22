from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.models.device_data_records import DeviceDataRecord


class DeviceDataRecordRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert(self, *, device_name: str, storage_key: str, data: Any) -> DeviceDataRecord:
        existing = self._get(device_name, storage_key)
        if existing is not None:
            existing.data = data
            self.db.commit()
            self.db.refresh(existing)
            return existing

        record = DeviceDataRecord(device_name=device_name, storage_key=storage_key, data=data)
        self.db.add(record)
        try:
            self.db.commit()
        except IntegrityError:
            # Lost a race to a concurrent writer for the same (device_name,
            # storage_key) — retry as an update rather than surfacing a spurious
            # failure to the caller.
            self.db.rollback()
            existing = self._get(device_name, storage_key)
            if existing is None:
                raise
            existing.data = data
            self.db.commit()
            self.db.refresh(existing)
            return existing
        self.db.refresh(record)
        return record

    def _get(self, device_name: str, storage_key: str) -> DeviceDataRecord | None:
        return self.db.scalar(
            select(DeviceDataRecord).where(
                DeviceDataRecord.device_name == device_name,
                DeviceDataRecord.storage_key == storage_key,
            )
        )
