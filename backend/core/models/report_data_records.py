from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ReportDataRecord(Base):
    """One row of flat, scalar-valued facts about a device, collected for reports.

    A *collection* is everything one step execution wrote for one (dataset, device),
    sharing a ``collection_id``. A device dataset has exactly one row per collection;
    an item dataset (interfaces, NTP servers, ...) has one row per item. A collection
    that found no items is stored as a single marker row (``is_empty``, ``data={}``)
    so the newest collection still wins over an older, non-empty one.

    Append-only history: every collection adds rows, so ``created_at`` is the trend
    axis. ``run_id`` is provenance only and nullable (rows from imports or manual
    writers have none, and it is cleared when the run is purged). Within one run,
    writing the same (dataset, device) again replaces that run's earlier collection,
    so a retried step does not duplicate its rows.
    """

    __tablename__ = "report_data_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dataset: Mapped[str] = mapped_column(String(100), nullable=False)
    # JSONB on PostgreSQL (queryable by the Reports app); plain JSON elsewhere (SQLite unit tests).
    data: Mapped[Any] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    collection_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Zero-based position of the row inside its collection. With the partial unique index
    # below it stops two overlapping writers of one run's collection from both landing.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_empty: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    run_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True
    )
    # The workflow node that wrote the collection (provenance within a run). Another node
    # writing the same (run, dataset, device) is refused instead of silently replacing it.
    node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Latest-collection and per-device trend lookups.
        Index("idx_report_data_dataset_device_created", "dataset", "device_name", "created_at"),
        # Newest rows of a dataset (the catalog's bounded sample read).
        Index("idx_report_data_dataset_id", "dataset", "id"),
        # Fetching a collection's rows by id.
        Index("idx_report_data_collection", "collection_id"),
        # One collection per (run, dataset, device): rows are numbered by ``position``, so a
        # second writer of the same collection hits this index instead of duplicating it.
        Index(
            "uq_report_data_run_collection_row",
            "run_id",
            "dataset",
            "device_name",
            "position",
            unique=True,
            postgresql_where=text("run_id IS NOT NULL"),
        ),
        # Retention cleanup by age.
        Index("idx_report_data_created_at", "created_at"),
    )
