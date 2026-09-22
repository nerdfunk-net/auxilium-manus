from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class DeviceDataRecord(Base):
    """One device's data stored under a storage key by the store-in-db step.

    Keyed by (device_name, storage_key) rather than device_name alone so a device
    can hold several independently-named stored items (e.g. one workflow stores a
    rendered template under "config_backup", another stores an attribute under
    "site_id") without clobbering each other.
    """

    __tablename__ = "device_data_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    data: Mapped[Any] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "device_name", "storage_key", name="uq_device_data_records_device_storage_key"
        ),
    )
