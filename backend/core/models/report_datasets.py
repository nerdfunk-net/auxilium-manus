from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ReportDataset(Base):
    """Catalog entry for one report dataset, kept up to date by the Store for Report step.

    It records what the step *declares* (grain and field names), so the Reports app can list
    datasets without scanning ``report_data_records``. Field types and sample values are not
    stored here; they are read from the newest rows when a query is built. If two steps write
    the same dataset, the newest write wins, like the newest collection does for reads.
    """

    __tablename__ = "report_datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    # "device": one row per device. "items": one row per list element.
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    field_names: Mapped[list[Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    last_collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
