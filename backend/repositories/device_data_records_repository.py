from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.models.device_data_records import DeviceDataRecord


class DeviceDataRecordRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert(self, *, device_name: str, storage_key: str, data: Any) -> DeviceDataRecord:
        try:
            return self._upsert(device_name=device_name, storage_key=storage_key, data=data)
        except Exception:
            # Any failure leaves the session needing a rollback; the caller keeps using it.
            self.db.rollback()
            raise

    def _upsert(self, *, device_name: str, storage_key: str, data: Any) -> DeviceDataRecord:
        existing = self._get(device_name, storage_key)
        if existing is not None:
            self._overwrite(existing, data)
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
            self._overwrite(existing, data)
            self.db.commit()
            self.db.refresh(existing)
            return existing
        self.db.refresh(record)
        return record

    @staticmethod
    def _overwrite(record: DeviceDataRecord, data: Any) -> None:
        """Replace the data and always move ``updated_at``: an equal JSON value sends no UPDATE
        on its own, so a re-stored identical value would otherwise keep its old date (the
        get-age-of-backup marker relies on ``updated_at`` meaning "last stored")."""
        record.data = data
        record.updated_at = func.now()

    def get(self, *, device_name: str, storage_key: str) -> DeviceDataRecord | None:
        return self._get(device_name, storage_key)

    def _get(self, device_name: str, storage_key: str) -> DeviceDataRecord | None:
        return self.db.scalar(
            select(DeviceDataRecord).where(
                DeviceDataRecord.device_name == device_name,
                DeviceDataRecord.storage_key == storage_key,
            )
        )
