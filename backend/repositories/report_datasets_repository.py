from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from core.models.report_datasets import ReportDataset


class ReportDatasetRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert(self, *, dataset: str, mode: str, field_names: list[str]) -> ReportDataset:
        """Create or update the catalog entry; the newest write wins.

        A lost insert race on the unique dataset name is retried as an update.
        """
        existing = self.get(dataset)
        if existing is not None:
            return self._update(existing, mode, field_names)

        entry = ReportDataset(
            dataset=dataset,
            mode=mode,
            field_names=list(field_names),
            last_collected_at=datetime.now(UTC),
        )
        self.db.add(entry)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.get(dataset)
            if existing is None:
                raise
            return self._update(existing, mode, field_names)
        except SQLAlchemyError:
            self.db.rollback()
            raise
        self.db.refresh(entry)
        return entry

    def get(self, dataset: str) -> ReportDataset | None:
        return self.db.scalar(select(ReportDataset).where(ReportDataset.dataset == dataset))

    def list_all(self) -> list[ReportDataset]:
        return list(self.db.scalars(select(ReportDataset).order_by(ReportDataset.dataset)))

    def _update(self, entry: ReportDataset, mode: str, field_names: list[str]) -> ReportDataset:
        entry.mode = mode
        entry.field_names = list(field_names)
        entry.last_collected_at = datetime.now(UTC)
        try:
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise
        self.db.refresh(entry)
        return entry
