from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from core.models.device_data_records import DeviceDataRecord
from repositories.device_data_records_repository import DeviceDataRecordRepository


class DeviceDataService:
    def __init__(self, db: Session) -> None:
        self.repository = DeviceDataRecordRepository(db)

    def store_device_data(
        self, *, device_name: str, storage_key: str, data: Any
    ) -> DeviceDataRecord:
        try:
            json.dumps(data, default=str)
        except TypeError as exc:
            raise ValueError(
                f"store-in-db: data for device {device_name!r} is not JSON-serializable"
            ) from exc
        return self.repository.upsert(device_name=device_name, storage_key=storage_key, data=data)
